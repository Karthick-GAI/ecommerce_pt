from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from models import AgentType, SessionStatus, TicketStatus, TicketPriority


# ── Chat Request / Response ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    target_agent: Optional[AgentType] = None  # force-route to a specific agent


class ChatResponse(BaseModel):
    session_id: str
    agent_type: AgentType
    content: str
    tools_used: List[str] = []
    handoff_occurred: bool = False
    ticket_id: Optional[str] = None


# ── Session ───────────────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    id: str
    customer_id: Optional[str]
    status: SessionStatus
    current_agent: AgentType
    total_messages: int
    total_handoffs: int
    created_at: str
    last_activity: str

    class Config:
        from_attributes = True


# ── Support Ticket ────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    customer_id: str
    issue_type: str
    description: str
    order_id: Optional[str] = None
    product_id: Optional[str] = None
    priority: TicketPriority = TicketPriority.medium


class TicketOut(BaseModel):
    id: str
    customer_id: str
    issue_type: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    resolution: Optional[str]
    order_id: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


# ── Routing Decision ──────────────────────────────────────────────────────────

class RoutingDecision(BaseModel):
    agent: AgentType
    confidence: float = Field(..., ge=0.0, le=1.0)
    intent: str
    entities: Dict[str, Any] = {}


# ── Agent Response (internal) ─────────────────────────────────────────────────

class HandoffRequest(BaseModel):
    to_agent: AgentType
    reason: str
    context_update: Dict[str, Any] = {}


class AgentResult(BaseModel):
    content: str
    agent_type: AgentType
    tools_used: List[str] = []
    handoff: Optional[HandoffRequest] = None
    ticket_id: Optional[str] = None


# ── Analytics ─────────────────────────────────────────────────────────────────

class AgentUsageStat(BaseModel):
    agent_type: str
    total_invocations: int
    avg_response_time_ms: Optional[float]
    resolution_rate: float
    handoff_rate: float
    top_intents: List[str]


class SystemAnalytics(BaseModel):
    total_sessions: int
    active_sessions: int
    total_messages: int
    total_handoffs: int
    open_tickets: int
    agents: List[AgentUsageStat]
