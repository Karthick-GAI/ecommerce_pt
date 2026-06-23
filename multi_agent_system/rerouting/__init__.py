"""
Autonomous order rerouting via agent-to-agent (A2A) communication.

Entry point: RerouteCoordinator.handle(order_id, db)

Protocol:
  OrderManagementAgent → InventoryAgent → LogisticsAgent → OrderManagementAgent

Each step uses the LLM tool-calling loop. Structured data flows between agents
via typed AgentMessage objects on the AgentBus — never via raw LLM text.
"""
from rerouting.bus import AgentBus, AgentMessage
from rerouting.coordinator import RerouteCoordinator, RerouteResult

__all__ = [
    "AgentBus",
    "AgentMessage",
    "RerouteCoordinator",
    "RerouteResult",
]
