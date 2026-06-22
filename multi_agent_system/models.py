import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer, Float,
    ForeignKey, JSON, Enum as SAEnum,
)
from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────

class AgentType(str, enum.Enum):
    orchestrator       = "orchestrator"
    customer_support   = "customer_support"
    recommendation     = "recommendation"
    fulfillment        = "fulfillment"
    inventory_planning = "inventory_planning"


class SessionStatus(str, enum.Enum):
    active    = "active"
    completed = "completed"
    escalated = "escalated"
    abandoned = "abandoned"


class TicketStatus(str, enum.Enum):
    open        = "open"
    in_progress = "in_progress"
    resolved    = "resolved"
    escalated   = "escalated"
    closed      = "closed"


class TicketPriority(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


# ── Multi-Agent Session ───────────────────────────────────────────────────────

class MASSession(Base):
    __tablename__ = "mas_sessions"

    id              = Column(String, primary_key=True, default=_uuid)
    customer_id     = Column(String, nullable=True, index=True)
    status          = Column(SAEnum(SessionStatus), default=SessionStatus.active, nullable=False)
    current_agent   = Column(SAEnum(AgentType), default=AgentType.orchestrator, nullable=False)
    context_json    = Column(JSON, default=dict)   # shared cross-agent state
    total_messages  = Column(Integer, default=0)
    total_handoffs  = Column(Integer, default=0)
    total_tool_calls = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_activity   = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    ended_at        = Column(DateTime(timezone=True), nullable=True)


# ── Agent Messages ────────────────────────────────────────────────────────────

class MASMessage(Base):
    __tablename__ = "mas_messages"

    id          = Column(String, primary_key=True, default=_uuid)
    session_id  = Column(String, ForeignKey("mas_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role        = Column(String, nullable=False)          # user | assistant | tool
    content     = Column(Text, nullable=False)
    agent_type  = Column(SAEnum(AgentType), nullable=True)
    tools_used  = Column(JSON, default=list)
    created_at  = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ── Agent Handoffs ────────────────────────────────────────────────────────────

class MASHandoff(Base):
    __tablename__ = "mas_handoffs"

    id                = Column(String, primary_key=True, default=_uuid)
    session_id        = Column(String, ForeignKey("mas_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    from_agent        = Column(SAEnum(AgentType), nullable=False)
    to_agent          = Column(SAEnum(AgentType), nullable=False)
    reason            = Column(Text, nullable=True)
    context_snapshot  = Column(JSON, default=dict)
    created_at        = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ── Support Tickets ───────────────────────────────────────────────────────────

class SupportTicket(Base):
    __tablename__ = "mas_support_tickets"

    id          = Column(String, primary_key=True, default=_uuid)
    session_id  = Column(String, ForeignKey("mas_sessions.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(String, nullable=False, index=True)
    issue_type  = Column(String, nullable=False)  # order_issue | payment | return | account | product | other
    description = Column(Text, nullable=False)
    status      = Column(SAEnum(TicketStatus), default=TicketStatus.open, nullable=False)
    priority    = Column(SAEnum(TicketPriority), default=TicketPriority.medium, nullable=False)
    resolution  = Column(Text, nullable=True)
    order_id    = Column(String, nullable=True)
    product_id  = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)
    created_at  = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at  = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


# ── Inventory Demand Forecasts (cached) ───────────────────────────────────────

class InventoryForecast(Base):
    __tablename__ = "mas_inventory_forecasts"

    id                      = Column(String, primary_key=True, default=_uuid)
    product_id              = Column(String, nullable=False, index=True)
    product_name            = Column(String, nullable=True)
    forecast_horizon_days   = Column(Integer, default=30)
    avg_daily_demand        = Column(Float, default=0.0)
    predicted_demand        = Column(Float, default=0.0)   # over horizon
    current_stock           = Column(Integer, default=0)
    reorder_point           = Column(Integer, default=0)
    recommended_restock_qty = Column(Integer, default=0)
    days_until_stockout     = Column(Float, nullable=True)
    confidence_score        = Column(Float, default=0.0)   # 0-1
    trend                   = Column(String, default="stable")  # rising | stable | falling
    created_at              = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ── Agent Analytics Log ───────────────────────────────────────────────────────

class AgentAnalyticsLog(Base):
    __tablename__ = "mas_analytics_logs"

    id               = Column(String, primary_key=True, default=_uuid)
    session_id       = Column(String, nullable=True)
    agent_type       = Column(SAEnum(AgentType), nullable=False, index=True)
    intent           = Column(String, nullable=True)
    tools_called     = Column(JSON, default=list)
    response_time_ms = Column(Integer, nullable=True)
    handoff_to       = Column(SAEnum(AgentType), nullable=True)
    resolved         = Column(Boolean, default=False)
    created_at       = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
