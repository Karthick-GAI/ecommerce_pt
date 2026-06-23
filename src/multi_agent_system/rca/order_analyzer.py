"""
OrderAnalyzerAgent — Step 2b of the RCA workflow.

Receives the evidence payload from DataCollectorAgent and performs deep
order-failure analysis:
  • Full lifecycle trace (backwards transitions, stuck states, timing gaps)
  • Payment failure pattern (systemic vs isolated, gateway issues)
  • Stock-at-checkout classification (insufficient stock vs oversell)

Runs in parallel with InventoryAnalyzerAgent (same input, different lenses).
Emits RCA_ORD_ANOMALIES with classified failure patterns and severity.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rca.bus import (
    AgentMessage,
    RCA_ORD_ANOMALIES,
    RC_PAYMENT_GATEWAY, RC_STOCK_AT_CHECKOUT, RC_PAYMENT_DECLINED,
    RC_STATE_MACHINE_STUCK, RC_CONCURRENT_OVERSELL, RC_UNKNOWN,
)
from tools.rca_tools import get_order_lifecycle_trace, get_payment_failure_pattern

_TOOLS = [
    {"type": "function", "function": {
        "name": "get_order_lifecycle_trace",
        "description": "Full status history for an order: backwards transitions, stuck detection, gap timing.",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_payment_failure_pattern",
        "description": "Detect if a payment failure is systemic (many similar failures) or isolated.",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]},
    }},
]


class OrderAnalyzerAgent(BaseReroutingAgent):
    AGENT_NAME = "order_analyzer"

    def system_prompt(self, incoming: AgentMessage) -> str:
        evidence     = incoming.payload.get("evidence", {})
        order_detail = evidence.get("order_details", {})
        target_type  = incoming.payload.get("target_type", "order")

        if target_type == "batch":
            batch_patterns = evidence.get("batch_patterns", {})
            statuses = list(batch_patterns.keys())
            return f"""You are the OrderAnalyzerAgent analyzing a batch of failed orders.

Available batch data covers statuses: {statuses}.
You do NOT have a specific order_id to trace. Instead, summarize the overall failure patterns
from the batch data already provided in evidence — do not call any tools.

Output a JSON block EXACTLY like:
```json
{{
  "order_failures": [
    {{
      "failure_pattern": "...",
      "root_cause_code": "...",
      "severity": "critical|warning|info",
      "affected_count": 0,
      "evidence_summary": "one sentence"
    }}
  ],
  "has_order_failures": true,
  "order_summary": "one paragraph"
}}
```
"""

        order_id = order_detail.get("order_id") or incoming.payload.get("target_id", "")
        order_status = order_detail.get("status", "unknown")
        payment_status = order_detail.get("payment_status", "unknown")
        is_stuck = order_detail.get("is_stuck", False)

        return f"""You are the OrderAnalyzerAgent investigating order {order_id}.

Order status: {order_status}, Payment status: {payment_status}, Stuck: {is_stuck}

Steps:
1. Call get_order_lifecycle_trace(order_id="{order_id}") — check for backwards transitions,
   duplicate statuses, and long gaps between transitions.
2. If payment_status is "failed" or "refund_pending":
   Call get_payment_failure_pattern(order_id="{order_id}") — determine if gateway or card issue.

Classify the primary failure using EXACTLY one of:
  PAYMENT_GATEWAY_TIMEOUT   — payment_failure_category="timeout" or is_systemic=True
  PAYMENT_DECLINED          — payment declined, not systemic
  STATE_MACHINE_STUCK       — stuck_for_hours > 6 or backwards_transitions detected
  INSUFFICIENT_STOCK_AT_CHECKOUT — cancelled with "stockout" or "insufficient stock" notes
  CONCURRENT_OVERSELL       — cancelled immediately after confirmed with stock reason
  UNKNOWN                   — cannot classify

Output a JSON block EXACTLY like:
```json
{{
  "order_failures": [
    {{
      "order_id": "{order_id}",
      "root_cause_code": "...",
      "severity": "critical|warning|info",
      "stuck_for_hours": null,
      "is_systemic_payment_issue": false,
      "backwards_transitions_found": false,
      "evidence_summary": "one sentence"
    }}
  ],
  "has_order_failures": true,
  "order_summary": "one paragraph"
}}
```
If the order has no problems, set has_order_failures=false and order_failures=[].
"""

    def tools_schema(self) -> List[Dict]:
        return _TOOLS

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        if tool_name == "get_order_lifecycle_trace":
            return get_order_lifecycle_trace(args["order_id"], db)
        if tool_name == "get_payment_failure_pattern":
            return get_payment_failure_pattern(args["order_id"], db)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        parsed = _extract_json_block(llm_reasoning)

        if not parsed:
            parsed = _build_from_tool_results(
                tool_calls_made,
                incoming.payload.get("evidence", {}),
                incoming.payload.get("target_id", ""),
            )

        return AgentMessage(
            message_type=RCA_ORD_ANOMALIES,
            from_agent="order_analyzer",
            to_agent="root_cause",
            payload={
                "target_type": incoming.payload.get("target_type"),
                "target_id":   incoming.payload.get("target_id"),
                "order_failures":     parsed.get("order_failures", []),
                "has_order_failures": parsed.get("has_order_failures", False),
                "order_summary":      parsed.get("order_summary", ""),
                "tools_used":         [t[0] for t in tool_calls_made],
                "reasoning":          llm_reasoning,
            },
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> dict:
    import re
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{[^{}]*\"has_order_failures\"[^{}]*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _build_from_tool_results(
    tool_calls_made: List[Tuple[str, Dict, str]],
    evidence: dict,
    target_id: str,
) -> dict:
    """Deterministic order failure classification from raw tool results."""
    lifecycle_data: dict = {}
    payment_data: dict   = {}

    for name, args, result_json in tool_calls_made:
        try:
            data = json.loads(result_json)
        except json.JSONDecodeError:
            continue
        if name == "get_order_lifecycle_trace":
            lifecycle_data = data
        elif name == "get_payment_failure_pattern":
            payment_data = data

    order_details = evidence.get("order_details", {})
    order_id      = lifecycle_data.get("order_id") or target_id
    order_status  = order_details.get("status", "")
    pay_status    = order_details.get("payment_status", "")

    if not order_id and not lifecycle_data:
        return {"order_failures": [], "has_order_failures": False, "order_summary": "No order data."}

    failures = []

    stuck_hours = lifecycle_data.get("stuck_for_hours")
    backwards   = lifecycle_data.get("backwards_transitions", [])
    is_systemic = payment_data.get("is_systemic", False)
    pay_category = payment_data.get("payment_failure_category", "")

    if stuck_hours and stuck_hours > 6:
        code = RC_STATE_MACHINE_STUCK
        sev  = "critical"
    elif is_systemic or pay_category == "timeout":
        code = RC_PAYMENT_GATEWAY
        sev  = "critical"
    elif pay_status in ("failed",) and not is_systemic:
        code = RC_PAYMENT_DECLINED
        sev  = "warning"
    elif backwards:
        code = RC_STATE_MACHINE_STUCK
        sev  = "warning"
    elif order_status == "cancelled":
        notes = " ".join(
            h.get("notes", "") or ""
            for h in order_details.get("status_history", [])
        ).lower()
        if "stock" in notes or "inventory" in notes:
            code = RC_STOCK_AT_CHECKOUT
        else:
            code = RC_UNKNOWN
        sev  = "warning"
    else:
        code = RC_UNKNOWN
        sev  = "info"

    failures.append({
        "order_id":                    order_id,
        "root_cause_code":             code,
        "severity":                    sev,
        "stuck_for_hours":             stuck_hours,
        "is_systemic_payment_issue":   is_systemic,
        "backwards_transitions_found": bool(backwards),
        "evidence_summary": (
            f"Order {order_id} classified as {code}. "
            f"{'Stuck for ' + str(stuck_hours) + ' hours. ' if stuck_hours else ''}"
            f"{'Systemic payment issue detected.' if is_systemic else ''}"
        ),
    })

    return {
        "order_failures":     failures,
        "has_order_failures": len(failures) > 0,
        "order_summary": (
            f"Order {order_id} has a classified failure: {code} (severity={sev})."
            if failures else f"Order {order_id} shows no detectable failures."
        ),
    }
