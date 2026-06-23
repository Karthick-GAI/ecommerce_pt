"""
RerouteCoordinator — orchestrates the 4-step A2A rerouting protocol.

Protocol:
  Step 1  OrderManagementAgent  assess_order_stockout
          ↓  STOCKOUT_DETECTED | NO_ACTION_NEEDED
  Step 2  InventoryAgent        find_alternative_products × N
          ↓  ALTERNATIVES_READY
  Step 3  LogisticsAgent        create_logistics_reroute_plan
          ↓  REROUTE_PLAN  (feasible=true or action=cancel)
  Step 4  OrderManagementAgent  apply_reroute_decision | cancel_order_and_refund
          ↓  REROUTE_APPLIED | ORDER_CANCELLED

The coordinator:
  • Creates a fresh AgentBus per run (no shared state between runs)
  • Posts every message to the bus for full audit trail
  • Persists a RerouteEvent record for dashboards
  • Returns a RerouteResult with outcome + full message log
"""
from __future__ import annotations

import json
import logging
import uuid
from time import monotonic
from dataclasses import dataclass
from typing import List

from sqlalchemy.orm import Session

from rerouting.bus import AgentBus, AgentMessage
from rerouting.order_agent import OrderManagementAgent
from rerouting.inventory_agent import InventoryAgent
from rerouting.logistics_agent import LogisticsAgent

logger = logging.getLogger(__name__)

# Outcome codes
OUTCOME_REROUTED        = "rerouted"
OUTCOME_CANCELLED       = "cancelled"
OUTCOME_NO_ACTION       = "no_action_needed"
OUTCOME_FAILED          = "failed"


@dataclass
class RerouteResult:
    run_id:        str
    order_id:      str
    outcome:       str          # rerouted | cancelled | no_action_needed | failed
    message_log:   List[dict]   # serialised AgentBus.summary()
    final_payload: dict
    duration_ms:   int

    def to_dict(self) -> dict:
        return {
            "run_id":        self.run_id,
            "order_id":      self.order_id,
            "outcome":       self.outcome,
            "duration_ms":   self.duration_ms,
            "message_count": len(self.message_log),
            "message_log":   self.message_log,
            "result":        self.final_payload,
        }


class RerouteCoordinator:
    """
    Drives the 4-step agent-to-agent rerouting workflow.
    One instance can handle many concurrent orders (no per-run state on self).
    """

    def __init__(self) -> None:
        self._order_agent     = OrderManagementAgent()
        self._inventory_agent = InventoryAgent()
        self._logistics_agent = LogisticsAgent()

    async def handle(self, order_id: str, db: Session) -> RerouteResult:
        run_id  = str(uuid.uuid4())[:8]
        bus     = AgentBus()
        t_start = monotonic()

        logger.info("[run=%s] Rerouting started for order=%s", run_id, order_id)

        # ── Step 1: OrderManagementAgent assesses the order ────────────────────
        assess_in = AgentMessage(
            message_type="REROUTE_REQUESTED",
            from_agent="coordinator",
            to_agent="order_management",
            payload={"order_id": order_id},
        )
        bus.post(assess_in)

        assess_out = await self._order_agent.run(assess_in, db)
        bus.post(assess_out)
        logger.info("[run=%s] Step 1 → %s", run_id, assess_out.message_type)

        if assess_out.message_type == "REROUTE_FAILED":
            return self._finish(run_id, order_id, OUTCOME_FAILED, bus, assess_out, t_start, db)

        if assess_out.message_type == "NO_ACTION_NEEDED":
            return self._finish(run_id, order_id, OUTCOME_NO_ACTION, bus, assess_out, t_start, db)

        # ── Step 2: InventoryAgent finds alternatives ──────────────────────────
        inv_out = await self._inventory_agent.run(assess_out, db)
        bus.post(inv_out)
        logger.info("[run=%s] Step 2 → %s | can_reroute=%s",
                    run_id, inv_out.message_type, inv_out.payload.get("can_reroute"))

        if inv_out.message_type == "REROUTE_FAILED":
            return self._finish(run_id, order_id, OUTCOME_FAILED, bus, inv_out, t_start, db)

        # ── Step 3: LogisticsAgent builds the reroute plan ─────────────────────
        log_out = await self._logistics_agent.run(inv_out, db)
        bus.post(log_out)
        logger.info("[run=%s] Step 3 → %s | action=%s",
                    run_id, log_out.message_type, log_out.payload.get("action", "reroute"))

        if log_out.message_type == "REROUTE_FAILED":
            return self._finish(run_id, order_id, OUTCOME_FAILED, bus, log_out, t_start, db)

        # ── Step 4: OrderManagementAgent applies or cancels ───────────────────
        if log_out.payload.get("action") == "cancel":
            # Logistics said no feasible plan → augment message for cancel path
            cancel_in = AgentMessage(
                message_type="REROUTE_PLAN",
                from_agent="logistics",
                to_agent="order_management",
                payload={
                    "order_id": order_id,
                    "action":   "cancel",
                    "reason":   log_out.payload.get("reason", "No feasible reroute"),
                },
            )
            bus.post(cancel_in)
            apply_out = await self._order_agent.run(cancel_in, db)
        else:
            apply_out = await self._order_agent.run(log_out, db)

        bus.post(apply_out)
        logger.info("[run=%s] Step 4 → %s", run_id, apply_out.message_type)

        outcome = (
            OUTCOME_REROUTED  if apply_out.message_type == "REROUTE_APPLIED"
            else OUTCOME_CANCELLED if apply_out.message_type == "ORDER_CANCELLED"
            else OUTCOME_FAILED
        )
        return self._finish(run_id, order_id, outcome, bus, apply_out, t_start, db)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _finish(
        self,
        run_id: str,
        order_id: str,
        outcome: str,
        bus: AgentBus,
        last_message: AgentMessage,
        t_start: float,
        db: Session,
    ) -> RerouteResult:
        duration = int((monotonic() - t_start) * 1000)
        _persist_event(run_id, order_id, outcome, len(bus.log), db)
        return RerouteResult(
            run_id=run_id,
            order_id=order_id,
            outcome=outcome,
            message_log=bus.summary(),
            final_payload=last_message.payload,
            duration_ms=duration,
        )


def _persist_event(run_id: str, order_id: str, outcome: str, msg_count: int, db: Session) -> None:
    """Write a RerouteEvent row for dashboards and analytics."""
    try:
        from models import RerouteEvent
        db.add(RerouteEvent(
            run_id=run_id,
            order_id=order_id,
            outcome=outcome,
            message_count=msg_count,
        ))
        db.commit()
    except Exception as exc:
        logger.warning("[%s] RerouteEvent persist failed: %s", run_id, exc)
        db.rollback()
