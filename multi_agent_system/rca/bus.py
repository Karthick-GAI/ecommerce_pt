"""
RCA message bus — typed inter-agent messages for root cause analysis.

Reuses the AgentBus infrastructure from the rerouting package.
RCA message types are distinct string constants (not mixed into rerouting).
"""
from __future__ import annotations

from rerouting.bus import AgentBus, AgentMessage  # noqa: re-export

# ── RCA message type constants ─────────────────────────────────────────────────
RCA_ANALYSIS_REQUESTED = "RCA_ANALYSIS_REQUESTED"  # Coordinator → DataCollector
RCA_DATA_COLLECTED     = "RCA_DATA_COLLECTED"       # DataCollector → Analyzers
RCA_INV_ANOMALIES      = "RCA_INV_ANOMALIES"        # InventoryAnalyzer → RootCause
RCA_ORD_ANOMALIES      = "RCA_ORD_ANOMALIES"        # OrderAnalyzer → RootCause
RCA_COMPLETE           = "RCA_COMPLETE"             # RootCause → Coordinator
RCA_FAILED             = "RCA_FAILED"               # any → Coordinator

# Root cause taxonomy — used in RCAReport.root_cause_type
RC_OVERSELL_RACE          = "OVERSELL_RACE_CONDITION"
RC_DOUBLE_DEDUCTION       = "DOUBLE_DEDUCTION"
RC_MISSING_MOVEMENT       = "MISSING_MOVEMENT_RECORD"
RC_MANUAL_ADJUSTMENT      = "MANUAL_ADJUSTMENT_WITHOUT_AUDIT"
RC_RETURN_NOT_RESTOCKED   = "RETURN_NOT_RESTOCKED"
RC_DATA_CORRUPTION        = "DATA_CORRUPTION"
RC_PAYMENT_GATEWAY        = "PAYMENT_GATEWAY_TIMEOUT"
RC_STOCK_AT_CHECKOUT      = "INSUFFICIENT_STOCK_AT_CHECKOUT"
RC_PAYMENT_DECLINED       = "PAYMENT_DECLINED"
RC_STATE_MACHINE_STUCK    = "STATE_MACHINE_STUCK"
RC_CONCURRENT_OVERSELL    = "CONCURRENT_OVERSELL"
RC_UNKNOWN                = "UNKNOWN"

__all__ = [
    "AgentMessage", "AgentBus",
    "RCA_ANALYSIS_REQUESTED", "RCA_DATA_COLLECTED",
    "RCA_INV_ANOMALIES", "RCA_ORD_ANOMALIES",
    "RCA_COMPLETE", "RCA_FAILED",
]
