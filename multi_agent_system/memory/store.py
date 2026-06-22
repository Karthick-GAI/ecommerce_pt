"""Conversation history and cross-agent shared state management."""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import MASSession, MASMessage, MASHandoff, AgentType


def get_or_create_session(
    db: Session,
    session_id: Optional[str],
    customer_id: Optional[str],
) -> MASSession:
    if session_id:
        session = db.query(MASSession).filter(MASSession.id == session_id).first()
        if session:
            session.last_activity = datetime.now(timezone.utc)
            db.commit()
            return session

    session = MASSession(customer_id=customer_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def load_history(session_id: str, db: Session, limit: int = 20) -> List[Dict]:
    messages = (
        db.query(MASMessage)
        .filter(MASMessage.session_id == session_id)
        .order_by(MASMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(messages)]


def save_message(
    session_id: str,
    role: str,
    content: str,
    db: Session,
    agent_type: Optional[AgentType] = None,
    tools_used: Optional[List[str]] = None,
) -> None:
    msg = MASMessage(
        session_id = session_id,
        role       = role,
        content    = content,
        agent_type = agent_type,
        tools_used = tools_used or [],
    )
    db.add(msg)

    session = db.query(MASSession).filter(MASSession.id == session_id).first()
    if session:
        session.total_messages += 1
        session.last_activity   = datetime.now(timezone.utc)

    db.commit()


def record_handoff(
    session_id: str,
    from_agent: AgentType,
    to_agent: AgentType,
    reason: str,
    db: Session,
    context_snapshot: Dict = None,
) -> None:
    handoff = MASHandoff(
        session_id       = session_id,
        from_agent       = from_agent,
        to_agent         = to_agent,
        reason           = reason,
        context_snapshot = context_snapshot or {},
    )
    db.add(handoff)

    session = db.query(MASSession).filter(MASSession.id == session_id).first()
    if session:
        session.current_agent  = to_agent
        session.total_handoffs += 1

    db.commit()


def update_shared_context(session_id: str, updates: Dict[str, Any], db: Session) -> None:
    session = db.query(MASSession).filter(MASSession.id == session_id).first()
    if session:
        ctx = dict(session.context_json or {})
        ctx.update(updates)
        session.context_json = ctx
        db.commit()


def get_shared_context(session_id: str, db: Session) -> Dict[str, Any]:
    session = db.query(MASSession).filter(MASSession.id == session_id).first()
    return dict(session.context_json or {}) if session else {}
