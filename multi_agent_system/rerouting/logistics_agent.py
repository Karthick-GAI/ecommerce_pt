"""
LogisticsAgent — validates feasibility and builds the concrete reroute plan.

Receives ALTERNATIVES_READY (containing recommended_substitutes from InventoryAgent),
calls create_logistics_reroute_plan for the first viable substitute, and emits
REROUTE_PLAN with a fully structured plan for the OrderManagementAgent to execute.

If feasibility check fails for all substitutes, emits REROUTE_PLAN with
action="cancel" so the coordinator routes to order cancellation.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rerouting.bus import AgentMessage
from tools.rerouting_tools import create_logistics_reroute_plan

_TOOLS = [
    {"type": "function", "function": {
        "name": "create_logistics_reroute_plan",
        "description": (
            "Validate stock sufficiency, compute price delta, and build a complete "
            "logistics plan for rerouting one line item to a substitute product. "
            "Returns feasible=true/false."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id":              {"type": "string"},
                "original_product_id":   {"type": "string"},
                "substitute_product_id": {"type": "string"},
            },
            "required": ["order_id", "original_product_id", "substitute_product_id"],
        },
    }},
]


class LogisticsAgent(BaseReroutingAgent):
    AGENT_NAME = "logistics"

    def system_prompt(self, incoming: AgentMessage) -> str:
        order_id     = incoming.payload.get("order_id", "")
        substitutes  = incoming.payload.get("recommended_substitutes", [])
        can_reroute  = incoming.payload.get("can_reroute", False)

        if not can_reroute or not substitutes:
            return f"""You are the LogisticsAgent evaluating reroute feasibility for order {order_id}.

The InventoryAgent found NO viable substitutes (can_reroute=false).
You do NOT need to call any tool.
Respond with exactly:
{{"feasible": false, "action": "cancel", "reason": "No in-stock substitute found by InventoryAgent."}}
"""
        sub_summary = "\n".join(
            f"  {i+1}. {s['substitute_name']} (id: {s['substitute_product_id']}, "
            f"stock: {s['stock_count']}, price_diff: {s['price_diff_pct']}%)"
            for i, s in enumerate(substitutes)
        )
        first = substitutes[0]
        return f"""You are the LogisticsAgent building the reroute plan for order {order_id}.

Recommended substitutes from InventoryAgent:
{sub_summary}

Your job:
1. Call create_logistics_reroute_plan with:
   - order_id              = "{order_id}"
   - original_product_id   = "{first['original_product_id']}"
   - substitute_product_id = "{first['substitute_product_id']}"
2. If the plan is feasible=true, report it in full.
3. If the plan is feasible=false (and there are more substitutes), try the next one.
4. If ALL substitutes fail feasibility, output:
   {{"feasible": false, "action": "cancel", "reason": "..."}}

Always use exact product IDs from the payload.
"""

    def tools_schema(self) -> List[Dict]:
        return _TOOLS

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        if tool_name == "create_logistics_reroute_plan":
            return create_logistics_reroute_plan(
                order_id=args["order_id"],
                original_product_id=args["original_product_id"],
                substitute_product_id=args["substitute_product_id"],
                db=db,
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        """
        Extract the reroute plan from tool results.
        Falls back to parsing the LLM text if no tool was called
        (e.g., logistics immediately decided to cancel).
        """
        order_id = incoming.payload.get("order_id")
        tools_used = [t[0] for t in tool_calls_made]

        # Try tool results first (most reliable)
        for name, args, result_json in tool_calls_made:
            if name == "create_logistics_reroute_plan":
                try:
                    plan_data = json.loads(result_json)
                except json.JSONDecodeError:
                    plan_data = {}

                if plan_data.get("feasible"):
                    rp = plan_data.get("reroute_plan", {})
                    return AgentMessage(
                        message_type="REROUTE_PLAN",
                        from_agent="logistics",
                        to_agent="order_management",
                        payload={
                            "order_id":              order_id,
                            "original_product_id":   rp.get("original_product", {}).get("product_id"),
                            "substitute_product_id": rp.get("substitute_product", {}).get("product_id"),
                            "reroute_plan":          rp,
                            "tools_used":            tools_used,
                            "reasoning":             llm_reasoning,
                        },
                    )

        # No feasible plan found — signal cancel
        return AgentMessage(
            message_type="REROUTE_PLAN",
            from_agent="logistics",
            to_agent="order_management",
            payload={
                "order_id":   order_id,
                "action":     "cancel",
                "reason":     "No feasible logistics reroute plan could be built.",
                "tools_used": tools_used,
                "reasoning":  llm_reasoning,
            },
        )
