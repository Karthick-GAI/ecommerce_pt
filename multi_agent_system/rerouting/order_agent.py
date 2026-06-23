"""
OrderManagementAgent — entry point and final executor of the rerouting workflow.

Step 1 (assess): Call assess_order_stockout and emit STOCKOUT_DETECTED with the
                 structured list of blocked line items.

Step 4 (apply):  Receive REROUTE_PLAN, call apply_reroute_decision or
                 cancel_order_and_refund, emit REROUTE_APPLIED / ORDER_CANCELLED.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rerouting.bus import AgentMessage
from tools.rerouting_tools import (
    assess_order_stockout,
    apply_reroute_decision,
    cancel_order_and_refund,
)

_ASSESS_TOOLS = [
    {"type": "function", "function": {
        "name": "assess_order_stockout",
        "description": (
            "Inspect every line item of an order and return which are out-of-stock "
            "with current stock counts, categories, and the quantity requested."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order UUID to inspect."},
            },
            "required": ["order_id"],
        },
    }},
]

_APPLY_TOOLS = [
    {"type": "function", "function": {
        "name": "apply_reroute_decision",
        "description": (
            "Swap an order line item from an out-of-stock product to an approved substitute. "
            "Deducts substitute stock and appends an audit note to the order history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id":              {"type": "string"},
                "original_product_id":   {"type": "string"},
                "substitute_product_id": {"type": "string"},
                "reason":                {"type": "string"},
            },
            "required": ["order_id", "original_product_id", "substitute_product_id"],
        },
    }},
    {"type": "function", "function": {
        "name": "cancel_order_and_refund",
        "description": (
            "Cancel an order and initiate a full refund. Use ONLY as a last resort "
            "when the logistics plan explicitly says the reroute is infeasible."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason":   {"type": "string"},
            },
            "required": ["order_id"],
        },
    }},
]


class OrderManagementAgent(BaseReroutingAgent):
    AGENT_NAME = "order_management"

    def _is_apply_mode(self, incoming: AgentMessage) -> bool:
        return incoming.message_type == "REROUTE_PLAN"

    def system_prompt(self, incoming: AgentMessage) -> str:
        if self._is_apply_mode(incoming):
            orig_id = incoming.payload.get("original_product_id", "")
            sub_id  = incoming.payload.get("substitute_product_id", "")
            order_id = incoming.payload.get("order_id", "")

            if incoming.payload.get("action") == "cancel":
                return f"""You are the OrderManagementAgent executing a last-resort cancel.

The LogisticsAgent determined that no feasible reroute exists for order {order_id}.
Call cancel_order_and_refund with order_id="{order_id}" and a clear reason string.
"""
            return f"""You are the OrderManagementAgent applying an approved reroute plan.

You MUST call apply_reroute_decision with:
  order_id              = "{order_id}"
  original_product_id   = "{orig_id}"
  substitute_product_id = "{sub_id}"
  reason                = "Autonomous A2A reroute — original item out of stock"

Do not reason further — call the tool immediately with these exact IDs.
After the tool responds, summarise the result (applied=true/false) and stop.
"""
        # Default: assess mode
        order_id = incoming.payload.get("order_id", "")
        return f"""You are the OrderManagementAgent assessing order {order_id} for stock problems.

Call assess_order_stockout with order_id="{order_id}".
Report the result exactly as returned by the tool — do not add commentary.
"""

    def tools_schema(self) -> list:
        return _APPLY_TOOLS if False else _ASSESS_TOOLS  # overridden per mode in run

    async def run(self, incoming: AgentMessage, db: Session) -> AgentMessage:
        """Override to select the right tool set based on message type."""
        self._current_mode = "apply" if self._is_apply_mode(incoming) else "assess"
        return await super().run(incoming, db)

    def tools_schema(self) -> list:
        if getattr(self, "_current_mode", "assess") == "apply":
            return _APPLY_TOOLS
        return _ASSESS_TOOLS

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        if tool_name == "assess_order_stockout":
            return assess_order_stockout(args["order_id"], db)
        if tool_name == "apply_reroute_decision":
            return apply_reroute_decision(
                order_id=args["order_id"],
                original_product_id=args["original_product_id"],
                substitute_product_id=args["substitute_product_id"],
                db=db,
                reason=args.get("reason", "Autonomous A2A reroute"),
            )
        if tool_name == "cancel_order_and_refund":
            return cancel_order_and_refund(
                order_id=args["order_id"],
                db=db,
                reason=args.get("reason", "No viable substitute found"),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        tools_used = [t[0] for t in tool_calls_made]

        if self._is_apply_mode(incoming):
            # Extract result of apply / cancel from tool calls
            apply_result = {}
            cancel_result = {}
            for name, _, result_json in tool_calls_made:
                if name == "apply_reroute_decision":
                    try:
                        apply_result = json.loads(result_json)
                    except json.JSONDecodeError:
                        pass
                elif name == "cancel_order_and_refund":
                    try:
                        cancel_result = json.loads(result_json)
                    except json.JSONDecodeError:
                        pass

            if cancel_result:
                return AgentMessage(
                    message_type="ORDER_CANCELLED",
                    from_agent="order_management",
                    to_agent="coordinator",
                    payload={
                        "order_id":    incoming.payload.get("order_id"),
                        "cancel":      cancel_result,
                        "tools_used":  tools_used,
                        "reasoning":   llm_reasoning,
                    },
                )
            return AgentMessage(
                message_type="REROUTE_APPLIED",
                from_agent="order_management",
                to_agent="coordinator",
                payload={
                    "order_id":    incoming.payload.get("order_id"),
                    "apply":       apply_result,
                    "tools_used":  tools_used,
                    "reasoning":   llm_reasoning,
                },
            )

        # Assess mode — extract structured stockout data from tool result
        assess_result: dict = {}
        for name, _, result_json in tool_calls_made:
            if name == "assess_order_stockout":
                try:
                    assess_result = json.loads(result_json)
                except json.JSONDecodeError:
                    pass

        stockout_items   = assess_result.get("stockout_items", [])
        stockout_detected = assess_result.get("stockout_detected", False)

        if not stockout_detected:
            return AgentMessage(
                message_type="NO_ACTION_NEEDED",
                from_agent="order_management",
                to_agent="coordinator",
                payload={
                    "order_id":   assess_result.get("order_id"),
                    "message":    "All items are in stock. No rerouting required.",
                    "ok_items":   assess_result.get("ok_items", []),
                    "tools_used": tools_used,
                },
            )

        return AgentMessage(
            message_type="STOCKOUT_DETECTED",
            from_agent="order_management",
            to_agent="inventory",
            payload={
                "order_id":        assess_result.get("order_id"),
                "order_status":    assess_result.get("order_status"),
                "customer_id":     assess_result.get("customer_id"),
                "shipping_pincode": assess_result.get("shipping_pincode"),
                "stockout_items":  stockout_items,
                "ok_items":        assess_result.get("ok_items", []),
                "tools_used":      tools_used,
                "reasoning":       llm_reasoning,
            },
        )
