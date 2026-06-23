"""
RCACoordinator — drives the 4-step RCA workflow.

Protocol:
  Step 1  DataCollectorAgent   → gathers raw evidence
  Step 2a InventoryAnalyzerAgent → inventory anomaly classification
  Step 2b OrderAnalyzerAgent   → order failure classification  (parallel with 2a)
  Step 3  RootCauseAgent       → synthesizes both reports → single root cause + remediation

Writes an RCAReport row and returns an RCAResult dataclass.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from rca.bus import (
    AgentBus, AgentMessage,
    RCA_ANALYSIS_REQUESTED, RCA_DATA_COLLECTED,
    RCA_INV_ANOMALIES, RCA_ORD_ANOMALIES,
    RCA_COMPLETE, RCA_FAILED,
)
from rca.data_collector  import DataCollectorAgent
from rca.inventory_analyzer import InventoryAnalyzerAgent
from rca.order_analyzer  import OrderAnalyzerAgent
from rca.root_cause_agent import RootCauseAgent
from models import RCAReport


@dataclass
class RCAResult:
    analysis_id:       str
    target_type:       str
    target_id:         str
    root_cause_type:   str
    confidence:        float
    summary:           str
    remediation_steps: List[str]
    anomalies_found:   int
    message_log:       List[Dict[str, Any]]
    duration_ms:       int
    status:            str  # completed | failed


class RCACoordinator:
    def __init__(self) -> None:
        self._data_collector   = DataCollectorAgent()
        self._inv_analyzer     = InventoryAnalyzerAgent()
        self._ord_analyzer     = OrderAnalyzerAgent()
        self._root_cause_agent = RootCauseAgent()

    async def analyze(
        self,
        target_id: str,
        target_type: str,   # "order" | "product" | "batch"
        db: Session,
    ) -> RCAResult:
        analysis_id = str(uuid.uuid4())[:8]
        bus         = AgentBus()
        t0          = time.monotonic()

        # ── Kick-off message ───────────────────────────────────────────────────
        initial = AgentMessage(
            message_type=RCA_ANALYSIS_REQUESTED,
            from_agent="coordinator",
            to_agent="data_collector",
            payload={"target_type": target_type, "target_id": target_id},
        )
        bus.post(initial)

        try:
            # Step 1 — collect evidence
            collected = await self._data_collector.run(initial, db)
            bus.post(collected)

            # Step 2 — parallel analysis (inventory + order)
            inv_msg, ord_msg = await asyncio.gather(
                self._inv_analyzer.run(collected, db),
                self._ord_analyzer.run(collected, db),
            )
            bus.post(inv_msg)
            bus.post(ord_msg)

            # Merge anomaly payloads for the RootCauseAgent
            merged = AgentMessage(
                message_type=RCA_ORD_ANOMALIES,  # marker for root_cause input
                from_agent="coordinator",
                to_agent="root_cause",
                payload={
                    "target_type":       target_type,
                    "target_id":         target_id,
                    "anomalies":         inv_msg.payload.get("anomalies", []),
                    "inventory_summary": inv_msg.payload.get("inventory_summary", ""),
                    "order_failures":    ord_msg.payload.get("order_failures", []),
                    "order_summary":     ord_msg.payload.get("order_summary", ""),
                },
            )

            # Step 3 — root cause synthesis
            final = await self._root_cause_agent.run(merged, db)
            bus.post(final)

            root_cause_type   = final.payload.get("root_cause_type", "UNKNOWN")
            confidence        = float(final.payload.get("confidence", 0.0))
            summary           = final.payload.get("summary", "")
            remediation_steps = final.payload.get("remediation_steps", [])
            all_anomalies     = (
                inv_msg.payload.get("anomalies", [])
                + ord_msg.payload.get("order_failures", [])
            )

            self._persist_report(
                db=db,
                analysis_id=analysis_id,
                target_type=target_type,
                target_id=target_id,
                root_cause_type=root_cause_type,
                confidence=confidence,
                summary=summary,
                anomalies_found=len(all_anomalies),
                agent_messages=[m.to_dict() for m in bus.log],
                remediation=remediation_steps,
            )

            return RCAResult(
                analysis_id=analysis_id,
                target_type=target_type,
                target_id=target_id,
                root_cause_type=root_cause_type,
                confidence=confidence,
                summary=summary,
                remediation_steps=remediation_steps,
                anomalies_found=len(all_anomalies),
                message_log=[m.to_dict() for m in bus.log],
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="completed",
            )

        except Exception as exc:  # noqa: BLE001
            err_msg = AgentMessage(
                message_type=RCA_FAILED,
                from_agent="coordinator",
                to_agent="coordinator",
                payload={"error": str(exc), "target_id": target_id},
            )
            bus.post(err_msg)

            self._persist_report(
                db=db,
                analysis_id=analysis_id,
                target_type=target_type,
                target_id=target_id,
                root_cause_type="FAILED",
                confidence=0.0,
                summary=f"RCA failed: {exc}",
                anomalies_found=0,
                agent_messages=[m.to_dict() for m in bus.log],
                remediation=[],
            )

            return RCAResult(
                analysis_id=analysis_id,
                target_type=target_type,
                target_id=target_id,
                root_cause_type="FAILED",
                confidence=0.0,
                summary=f"RCA failed: {exc}",
                remediation_steps=[],
                anomalies_found=0,
                message_log=[m.to_dict() for m in bus.log],
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failed",
            )

    # ── Persistence ────────────────────────────────────────────────────────────

    def _persist_report(
        self,
        db: Session,
        analysis_id: str,
        target_type: str,
        target_id: str,
        root_cause_type: str,
        confidence: float,
        summary: str,
        anomalies_found: int,
        agent_messages: list,
        remediation: list,
    ) -> None:
        try:
            report = RCAReport(
                analysis_id=analysis_id,
                target_type=target_type,
                target_id=target_id,
                root_cause_type=root_cause_type,
                confidence=confidence,
                summary=summary,
                anomalies_found=anomalies_found,
                agent_messages=agent_messages,
                remediation=remediation,
            )
            db.add(report)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
