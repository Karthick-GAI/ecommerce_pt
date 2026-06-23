"""
RootCauseAgent — Step 3 of the RCA workflow.

Receives anomaly reports from both InventoryAnalyzerAgent (RCA_INV_ANOMALIES)
and OrderAnalyzerAgent (RCA_ORD_ANOMALIES) — or just one if the target type
only produces one — and synthesizes a single authoritative root cause with:
  • A root_cause_type from the taxonomy
  • A confidence score (0.0 – 1.0)
  • A one-paragraph narrative summary
  • Concrete remediation steps (list of strings)

This agent has NO tools — it reasons purely over the evidence payloads.
Emits RCA_COMPLETE.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rca.bus import (
    AgentMessage,
    RCA_COMPLETE, RCA_FAILED,
    RC_OVERSELL_RACE, RC_DOUBLE_DEDUCTION, RC_MISSING_MOVEMENT,
    RC_MANUAL_ADJUSTMENT, RC_RETURN_NOT_RESTOCKED, RC_DATA_CORRUPTION,
    RC_PAYMENT_GATEWAY, RC_STOCK_AT_CHECKOUT, RC_PAYMENT_DECLINED,
    RC_STATE_MACHINE_STUCK, RC_CONCURRENT_OVERSELL, RC_UNKNOWN,
)

_REMEDIATION_MAP: Dict[str, List[str]] = {
    RC_OVERSELL_RACE: [
        "Add a database-level advisory lock or SELECT FOR UPDATE on inventory deduction during checkout.",
        "Implement a distributed queue (e.g., Redis BLPOP) for concurrent purchase requests for the same product.",
        "Re-run stock reconciliation nightly and alert if inventory_count < 0.",
    ],
    RC_DOUBLE_DEDUCTION: [
        "Audit the checkout flow for idempotency — ensure each order only deducts inventory once.",
        "Add a unique constraint on (order_id, product_id) in inventory_movements.",
        "Review payment retry logic that may re-trigger the fulfillment pipeline.",
    ],
    RC_MISSING_MOVEMENT: [
        "Enable mandatory movement recording for all stock changes (admin UI, returns, adjustments).",
        "Add a DB trigger or application hook that prevents inventory_count updates without a matching movement row.",
        "Reconcile the gap by comparing WMS export with recorded movements.",
    ],
    RC_MANUAL_ADJUSTMENT: [
        "Require a reason and approver for all manual inventory adjustments above a threshold (e.g., >10 units).",
        "Add an audit log table specifically for manual adjustments with before/after snapshots.",
        "Send an alert to the inventory manager for any manual adjustment exceeding 50 units.",
    ],
    RC_RETURN_NOT_RESTOCKED: [
        "Automate restock movement creation when a return is marked 'received' in the returns portal.",
        "Add a daily report of returns received but not restocked older than 24 hours.",
        "Review the returns-to-inventory workflow for the affected product category.",
    ],
    RC_DATA_CORRUPTION: [
        "Halt further inventory mutations for affected products until a full audit is complete.",
        "Restore inventory_count from the movement chain (sum of quantity_change from oldest baseline).",
        "Investigate application deployment history for the period of corruption.",
    ],
    RC_PAYMENT_GATEWAY: [
        "Check payment gateway status page and recent incident history.",
        "Implement an exponential-backoff retry with idempotency key for timed-out payment requests.",
        "Notify the payments team; consider switching to backup gateway if failure rate > 5%.",
    ],
    RC_STOCK_AT_CHECKOUT: [
        "Reserve inventory at the time of add-to-cart (soft reservation with TTL).",
        "Display real-time stock counts on the product page.",
        "Trigger a restock alert for the product if demand exceeds supply consistently.",
    ],
    RC_PAYMENT_DECLINED: [
        "Prompt the customer to update their payment method or try an alternative.",
        "Review if the decline is due to card velocity limits; advise the customer accordingly.",
        "Offer EMI or wallet-based alternative payment options at checkout.",
    ],
    RC_STATE_MACHINE_STUCK: [
        "Add a background job that detects and auto-escalates orders stuck > 6 hours.",
        "Implement a dead-letter mechanism for orders that fail to advance through the state machine.",
        "Review the event/message queue for missed status transition events.",
    ],
    RC_CONCURRENT_OVERSELL: [
        "Enforce pessimistic locking on stock reservation during high-traffic periods.",
        "Implement a queue-based purchase flow to serialize concurrent requests.",
        "Set maximum concurrency limits per product for flash-sale events.",
    ],
    RC_UNKNOWN: [
        "Collect more diagnostic data: enable verbose logging for this product/order.",
        "Escalate to the engineering team for manual investigation.",
        "Check for recent deployments or infrastructure changes that may have introduced a regression.",
    ],
}


class RootCauseAgent(BaseReroutingAgent):
    AGENT_NAME = "root_cause"

    def system_prompt(self, incoming: AgentMessage) -> str:
        inv_anomalies  = incoming.payload.get("anomalies", [])
        ord_failures   = incoming.payload.get("order_failures", [])
        inv_summary    = incoming.payload.get("inventory_summary", "")
        ord_summary    = incoming.payload.get("order_summary", "")
        target_type    = incoming.payload.get("target_type", "order")
        target_id      = incoming.payload.get("target_id", "")

        inv_block = json.dumps(inv_anomalies, indent=2) if inv_anomalies else "[]"
        ord_block = json.dumps(ord_failures, indent=2) if ord_failures else "[]"

        taxonomy = "\n".join(f"  {k}" for k in _REMEDIATION_MAP)

        return f"""You are the RootCauseAgent synthesizing findings for target: {target_type} / {target_id}

INVENTORY ANOMALIES:
{inv_block}
Inventory summary: {inv_summary}

ORDER FAILURES:
{ord_block}
Order summary: {ord_summary}

Your job:
1. Select the SINGLE most impactful root cause from the taxonomy below.
2. Assign a confidence score from 0.0 to 1.0.
3. Write a concise narrative summary (2-3 sentences).
4. List 3 concrete remediation steps.

Taxonomy:
{taxonomy}

If inventory anomalies exist, prioritize them unless a payment gateway issue is systemic.
If multiple anomalies exist, pick the highest-severity one.
If all anomalies are UNKNOWN, root_cause_type should be UNKNOWN.

Output a JSON block EXACTLY like:
```json
{{
  "root_cause_type": "...",
  "confidence": 0.0,
  "summary": "...",
  "remediation_steps": ["...", "...", "..."],
  "supporting_evidence": ["...", "..."]
}}
```
"""

    def tools_schema(self) -> List[Dict]:
        return []  # No tools — pure reasoning

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        return json.dumps({"error": f"RootCauseAgent has no tools"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        parsed = _extract_json_block(llm_reasoning)

        if not parsed:
            parsed = _build_deterministic(incoming)

        return AgentMessage(
            message_type=RCA_COMPLETE,
            from_agent="root_cause",
            to_agent="coordinator",
            payload={
                "target_type":       incoming.payload.get("target_type"),
                "target_id":         incoming.payload.get("target_id"),
                "root_cause_type":   parsed.get("root_cause_type", RC_UNKNOWN),
                "confidence":        float(parsed.get("confidence", 0.0)),
                "summary":           parsed.get("summary", ""),
                "remediation_steps": parsed.get("remediation_steps")
                                     or _REMEDIATION_MAP.get(parsed.get("root_cause_type", RC_UNKNOWN), []),
                "supporting_evidence": parsed.get("supporting_evidence", []),
                "inventory_anomalies": incoming.payload.get("anomalies", []),
                "order_failures":      incoming.payload.get("order_failures", []),
                "reasoning":           llm_reasoning,
            },
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> dict:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{[^{}]*\"root_cause_type\"[^{}]*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _build_deterministic(incoming: AgentMessage) -> dict:
    """Pick highest-severity anomaly as root cause without LLM."""
    severity_rank = {"critical": 2, "warning": 1, "info": 0}

    inv_anomalies = incoming.payload.get("anomalies", [])
    ord_failures  = incoming.payload.get("order_failures", [])

    all_findings = [
        (f.get("severity", "info"), f.get("root_cause_code", RC_UNKNOWN), "inventory")
        for f in inv_anomalies
    ] + [
        (f.get("severity", "info"), f.get("root_cause_code", RC_UNKNOWN), "order")
        for f in ord_failures
    ]

    if not all_findings:
        return {
            "root_cause_type":   RC_UNKNOWN,
            "confidence":        0.1,
            "summary":           "No anomalies detected. Root cause could not be determined.",
            "remediation_steps": _REMEDIATION_MAP[RC_UNKNOWN],
            "supporting_evidence": [],
        }

    # Sort by severity desc
    all_findings.sort(key=lambda x: severity_rank.get(x[0], 0), reverse=True)
    top_sev, top_code, top_source = all_findings[0]

    # Confidence heuristic: critical = 0.7, warning = 0.5, info = 0.3
    conf = {"critical": 0.7, "warning": 0.5, "info": 0.3}.get(top_sev, 0.3)

    return {
        "root_cause_type":   top_code,
        "confidence":        conf,
        "summary":           f"Primary root cause identified as {top_code} ({top_sev} severity) from {top_source} analysis.",
        "remediation_steps": _REMEDIATION_MAP.get(top_code, _REMEDIATION_MAP[RC_UNKNOWN]),
        "supporting_evidence": [
            f"{s}: {c} ({sv})" for sv, c, s in all_findings
        ],
    }
