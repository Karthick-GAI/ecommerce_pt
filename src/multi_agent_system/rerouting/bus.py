"""
Agent-to-agent message bus for the rerouting workflow.

Each inter-agent message is a typed AgentMessage that travels through the bus.
The bus keeps an ordered audit log so every decision made during a rerouting
run can be replayed or inspected.

In production, replace the in-process list with Redis Streams, RabbitMQ, or
an ARQ task queue.  The interface stays the same — only `AgentBus` changes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

# All message types used in the rerouting protocol
MessageType = Literal[
    "REROUTE_REQUESTED",   # Coordinator → OrderMgmt   (entry)
    "STOCKOUT_DETECTED",   # OrderMgmt  → Inventory    (step 1 → 2)
    "ALTERNATIVES_READY",  # Inventory  → Logistics    (step 2 → 3)
    "REROUTE_PLAN",        # Logistics  → OrderMgmt    (step 3 → 4)
    "REROUTE_APPLIED",     # OrderMgmt  → Coordinator  (success)
    "ORDER_CANCELLED",     # OrderMgmt  → Coordinator  (last resort)
    "REROUTE_FAILED",      # any        → Coordinator  (error)
    "NO_ACTION_NEEDED",    # OrderMgmt  → Coordinator  (order healthy)
]


@dataclass
class AgentMessage:
    """
    Typed, immutable message between rerouting agents.

    payload carries structured data extracted from tool results — not LLM prose.
    This ensures the next agent always receives machine-readable inputs even if
    the LLM reasoning text was imprecise.
    """
    message_type: MessageType
    from_agent:   str
    to_agent:     str
    payload:      Dict[str, Any] = field(default_factory=dict)
    message_id:   str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp:    datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "message_id":   self.message_id,
            "message_type": self.message_type,
            "from_agent":   self.from_agent,
            "to_agent":     self.to_agent,
            "payload":      self.payload,
            "timestamp":    self.timestamp.isoformat(),
        }


class AgentBus:
    """
    Ordered audit log for all inter-agent messages in one rerouting run.
    Each run gets its own bus instance — no shared state between runs.
    """

    def __init__(self) -> None:
        self._log: List[AgentMessage] = []

    def post(self, message: AgentMessage) -> None:
        """Append a message to the audit log."""
        self._log.append(message)

    @property
    def log(self) -> List[AgentMessage]:
        return list(self._log)

    def summary(self) -> List[dict]:
        """Serialisable snapshot of the full message log."""
        return [m.to_dict() for m in self._log]
