"""
DataCollectorAgent — Step 1 of the RCA workflow.

Receives the analysis target (order_id, product_id, or a batch request),
calls the appropriate diagnostic tools to gather raw evidence, and emits
RCA_DATA_COLLECTED with a structured evidence payload for the two analyzers.

It does NOT classify or judge — only collects.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rca.bus import AgentMessage, RCA_DATA_COLLECTED, RCA_FAILED
from tools.rca_tools import (
    get_order_failure_details,
    get_inventory_movement_audit,
    get_failed_orders_batch,
    get_inventory_alert_history,
    detect_stock_discrepancy,
)

_TOOLS = [
    {"type": "function", "function": {
        "name": "get_order_failure_details",
        "description": "Pull all diagnostic data for a failed/stuck order: status timeline, payment record, line items, and refund.",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_inventory_movement_audit",
        "description": "Pull the full movement history for a product and detect chain inconsistencies.",
        "parameters": {"type": "object",
                       "properties": {
                           "product_id": {"type": "string"},
                           "days":       {"type": "integer", "default": 60},
                       },
                       "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_inventory_alert_history",
        "description": "Return all inventory alerts for a product to understand when stock problems began.",
        "parameters": {"type": "object",
                       "properties": {"product_id": {"type": "string"}},
                       "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "detect_stock_discrepancy",
        "description": "Reconcile the product's current inventory_count against all recorded movements. Returns the discrepancy and any negative-stock events.",
        "parameters": {"type": "object",
                       "properties": {"product_id": {"type": "string"}},
                       "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_failed_orders_batch",
        "description": "Return a batch of failed or stuck orders. Use for batch-mode analysis to surface common failure patterns.",
        "parameters": {"type": "object",
                       "properties": {
                           "status_filter": {"type": "string", "enum": ["cancelled", "payment_failed", "processing", "confirmed"]},
                           "limit":         {"type": "integer", "default": 20},
                       }},
    }},
]


class DataCollectorAgent(BaseReroutingAgent):
    AGENT_NAME = "data_collector"

    def system_prompt(self, incoming: AgentMessage) -> str:
        target_type = incoming.payload.get("target_type", "order")
        target_id   = incoming.payload.get("target_id", "")

        if target_type == "order":
            return f"""You are the DataCollectorAgent gathering evidence for RCA of order {target_id}.

Call get_order_failure_details with order_id="{target_id}".
Also call get_inventory_movement_audit for EACH product_id found in the order's line items
(so the InventoryAnalyzer has movement data too).

Collect all tool results and stop. Do not interpret or classify — just report what the tools returned.
"""
        if target_type == "product":
            return f"""You are the DataCollectorAgent gathering evidence for RCA of product {target_id}.

Call these tools in order:
1. detect_stock_discrepancy(product_id="{target_id}")
2. get_inventory_movement_audit(product_id="{target_id}", days=60)
3. get_inventory_alert_history(product_id="{target_id}")

Collect all results and stop. Do not interpret — just report what the tools returned.
"""
        # batch mode
        return """You are the DataCollectorAgent gathering evidence for batch RCA.

Call get_failed_orders_batch with limit=20 to find the most common failure patterns.
Also call get_failed_orders_batch with status_filter="payment_failed" to isolate payment failures.

Collect results and stop.
"""

    def tools_schema(self) -> List[Dict]:
        return _TOOLS

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        if tool_name == "get_order_failure_details":
            return get_order_failure_details(args["order_id"], db)
        if tool_name == "get_inventory_movement_audit":
            return get_inventory_movement_audit(
                args["product_id"], db, days=args.get("days", 60))
        if tool_name == "get_inventory_alert_history":
            return get_inventory_alert_history(args["product_id"], db)
        if tool_name == "detect_stock_discrepancy":
            return detect_stock_discrepancy(args["product_id"], db)
        if tool_name == "get_failed_orders_batch":
            return get_failed_orders_batch(
                db,
                status_filter=args.get("status_filter"),
                limit=args.get("limit", 20),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        # Aggregate all tool results as structured evidence
        evidence: Dict[str, Any] = {}
        for tool_name, args, result_json in tool_calls_made:
            try:
                parsed = json.loads(result_json)
            except json.JSONDecodeError:
                parsed = {"raw": result_json}

            if tool_name == "get_order_failure_details":
                evidence["order_details"] = parsed
            elif tool_name == "get_inventory_movement_audit":
                pid = args.get("product_id", "unknown")
                evidence.setdefault("movement_audits", {})[pid] = parsed
            elif tool_name == "get_inventory_alert_history":
                pid = args.get("product_id", "unknown")
                evidence.setdefault("alert_histories", {})[pid] = parsed
            elif tool_name == "detect_stock_discrepancy":
                pid = args.get("product_id", "unknown")
                evidence.setdefault("discrepancies", {})[pid] = parsed
            elif tool_name == "get_failed_orders_batch":
                sf = args.get("status_filter", "all")
                evidence.setdefault("batch_patterns", {})[sf] = parsed

        return AgentMessage(
            message_type=RCA_DATA_COLLECTED,
            from_agent="data_collector",
            to_agent="analyzers",
            payload={
                "target_type": incoming.payload.get("target_type"),
                "target_id":   incoming.payload.get("target_id"),
                "evidence":    evidence,
                "tools_used":  [t[0] for t in tool_calls_made],
                "reasoning":   llm_reasoning,
            },
        )
