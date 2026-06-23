"""
InventoryAnalyzerAgent — Step 2a of the RCA workflow.

Receives the evidence payload from DataCollectorAgent and performs deep
inventory-specific analysis:
  • Stock discrepancy reconciliation (system count vs movement audit)
  • Negative-stock event detection (oversell)
  • Concurrent order pressure (race condition signal)
  • Chain inconsistency classification (missing movement, double deduction)
  • Alert timeline correlation

Emits RCA_INV_ANOMALIES with a structured list of classified anomalies
and their severity (critical / warning / info).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rca.bus import (
    AgentMessage,
    RCA_INV_ANOMALIES, RCA_FAILED,
    RC_OVERSELL_RACE, RC_DOUBLE_DEDUCTION, RC_MISSING_MOVEMENT,
    RC_MANUAL_ADJUSTMENT, RC_RETURN_NOT_RESTOCKED, RC_DATA_CORRUPTION,
    RC_CONCURRENT_OVERSELL, RC_UNKNOWN,
)
from tools.rca_tools import detect_stock_discrepancy, get_concurrent_order_pressure

_TOOLS = [
    {"type": "function", "function": {
        "name": "detect_stock_discrepancy",
        "description": "Reconcile current inventory_count against recorded movements. Returns discrepancy size and direction.",
        "parameters": {"type": "object",
                       "properties": {"product_id": {"type": "string"}},
                       "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_concurrent_order_pressure",
        "description": "Find clusters of orders placed within a short window for the same product. Signals race conditions.",
        "parameters": {"type": "object",
                       "properties": {
                           "product_id":      {"type": "string"},
                           "window_minutes":  {"type": "integer", "default": 10},
                       },
                       "required": ["product_id"]},
    }},
]


class InventoryAnalyzerAgent(BaseReroutingAgent):
    AGENT_NAME = "inventory_analyzer"

    def system_prompt(self, incoming: AgentMessage) -> str:
        evidence     = incoming.payload.get("evidence", {})
        discrepancies = evidence.get("discrepancies", {})
        audits        = evidence.get("movement_audits", {})
        product_ids   = list(set(list(discrepancies.keys()) + list(audits.keys())))

        if not product_ids:
            return """You are the InventoryAnalyzerAgent.
No product evidence was provided. Return immediately with:
{"anomalies": [], "summary": "No inventory data to analyze.", "has_inventory_issues": false}
"""

        pid_list = ", ".join(f'"{p}"' for p in product_ids)
        return f"""You are the InventoryAnalyzerAgent. Analyze inventory health for products: {pid_list}

For EACH product_id:
1. Call detect_stock_discrepancy(product_id) — check if recorded movements reconcile with current stock.
2. If discrepancy_detected=true OR there are inconsistency_count > 0:
   Call get_concurrent_order_pressure(product_id) to check for race conditions.

Classify each finding using EXACTLY one of these root cause codes:
  OVERSELL_RACE_CONDITION       — negative stock events + concurrent order clusters
  DOUBLE_DEDUCTION              — large discrepancy + duplicate movement types in same period
  MISSING_MOVEMENT_RECORD       — discrepancy with no chain inconsistencies (gap unexplained)
  MANUAL_ADJUSTMENT_WITHOUT_AUDIT — large_restock_events with unknown/system performed_by
  RETURN_NOT_RESTOCKED          — return movements without matching +qty restock
  DATA_CORRUPTION               — chain_inconsistencies > 2, non-explainable gaps
  UNKNOWN                       — cannot classify from available data

After analyzing all products, output a JSON block EXACTLY like:
```json
{{
  "anomalies": [
    {{
      "product_id": "...",
      "root_cause_code": "...",
      "severity": "critical|warning|info",
      "discrepancy_units": 0,
      "evidence_summary": "one sentence",
      "concurrent_oversell_risk": false
    }}
  ],
  "has_inventory_issues": true,
  "summary": "one paragraph overall finding"
}}
```
If no products have issues, set has_inventory_issues=false and anomalies=[].
"""

    def tools_schema(self) -> List[Dict]:
        return _TOOLS

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        if tool_name == "detect_stock_discrepancy":
            return detect_stock_discrepancy(args["product_id"], db)
        if tool_name == "get_concurrent_order_pressure":
            return get_concurrent_order_pressure(
                args["product_id"], db,
                window_minutes=args.get("window_minutes", 10),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        # Try LLM JSON block first
        parsed = _extract_json_block(llm_reasoning)

        # Deterministic fallback from tool results
        if not parsed:
            parsed = _build_from_tool_results(tool_calls_made)

        return AgentMessage(
            message_type=RCA_INV_ANOMALIES,
            from_agent="inventory_analyzer",
            to_agent="root_cause",
            payload={
                "target_type": incoming.payload.get("target_type"),
                "target_id":   incoming.payload.get("target_id"),
                "anomalies":             parsed.get("anomalies", []),
                "has_inventory_issues":  parsed.get("has_inventory_issues", False),
                "inventory_summary":     parsed.get("summary", ""),
                "tools_used":            [t[0] for t in tool_calls_made],
                "reasoning":             llm_reasoning,
            },
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> dict:
    import re
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{[^{}]*\"has_inventory_issues\"[^{}]*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _build_from_tool_results(tool_calls_made: List[Tuple[str, Dict, str]]) -> dict:
    """Deterministic anomaly classification from raw tool results."""
    anomalies: list[dict] = []

    # Collect discrepancy results keyed by product_id
    disc_map: Dict[str, dict] = {}
    pressure_map: Dict[str, dict] = {}
    for name, args, result_json in tool_calls_made:
        try:
            data = json.loads(result_json)
        except json.JSONDecodeError:
            continue
        if name == "detect_stock_discrepancy":
            pid = data.get("product_id") or args.get("product_id", "")
            if pid:
                disc_map[pid] = data
        elif name == "get_concurrent_order_pressure":
            pid = data.get("product_id") or args.get("product_id", "")
            if pid:
                pressure_map[pid] = data

    for pid, disc in disc_map.items():
        if not disc.get("discrepancy_detected"):
            continue

        disc_val = disc.get("discrepancy", 0)
        neg_events = disc.get("negative_stock_events", [])
        large_restocks = disc.get("large_restock_events", [])
        chain_issues = disc.get("chain_inconsistencies", [])
        pressure = pressure_map.get(pid, {})
        has_concurrent = pressure.get("oversell_risk", False)

        # Classify
        if neg_events and has_concurrent:
            code = RC_OVERSELL_RACE
            sev  = "critical"
        elif len(chain_issues) >= 2:
            code = RC_DATA_CORRUPTION
            sev  = "critical"
        elif large_restocks and any(r.get("by") in ("system", None, "") for r in large_restocks):
            code = RC_MANUAL_ADJUSTMENT
            sev  = "warning"
        elif neg_events:
            code = RC_CONCURRENT_OVERSELL
            sev  = "critical"
        elif disc_val != 0 and not chain_issues:
            code = RC_MISSING_MOVEMENT
            sev  = "warning"
        else:
            code = RC_UNKNOWN
            sev  = "info"

        anomalies.append({
            "product_id":             pid,
            "root_cause_code":        code,
            "severity":               sev,
            "discrepancy_units":      abs(disc_val),
            "evidence_summary":       (
                f"Stock discrepancy of {abs(disc_val)} units detected. "
                f"{'Negative stock events found. ' if neg_events else ''}"
                f"{'Concurrent order pressure detected.' if has_concurrent else ''}"
            ),
            "concurrent_oversell_risk": has_concurrent,
        })

    return {
        "anomalies":             anomalies,
        "has_inventory_issues":  len(anomalies) > 0,
        "summary":               (
            f"{len(anomalies)} inventory anomaly/anomalies detected across "
            f"{len(disc_map)} product(s) analyzed."
            if anomalies else "No inventory discrepancies detected."
        ),
    }
