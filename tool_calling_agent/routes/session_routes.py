from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import AgentSession, AgentMessage

router = APIRouter(prefix="/agent/sessions", tags=["Sessions"])


# ── GET /agent/sessions — list all sessions ───────────────────────────────────

@router.get("")
def list_sessions(
    customer_id: Optional[str] = Query(None),
    limit:       int           = Query(20, ge=1, le=100),
    page:        int           = Query(1, ge=1),
    db: Session                = Depends(get_db),
):
    q = db.query(AgentSession)
    if customer_id:
        q = q.filter(AgentSession.customer_id == customer_id)

    total    = q.count()
    sessions = q.order_by(AgentSession.updated_at.desc()).offset((page - 1) * limit).limit(limit).all()

    result = []
    for s in sessions:
        msg_count = db.query(AgentMessage).filter(AgentMessage.session_id == s.id).count()
        result.append({
            "session_id":    s.id,
            "customer_id":   s.customer_id,
            "title":         s.title,
            "message_count": msg_count,
            "created_at":    str(s.created_at),
            "updated_at":    str(s.updated_at),
        })

    return {"total": total, "page": page, "sessions": result}


# ── GET /agent/sessions/{session_id} — session + full history ─────────────────

@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at)
        .all()
    )

    history = []
    for m in messages:
        if m.role in ("user", "assistant"):
            history.append({
                "role":       m.role,
                "content":    m.content,
                "tools_called": [tc["function"]["name"] for tc in (m.tool_calls or [])],
                "created_at": str(m.created_at),
            })
        # tool messages are internal — omit from the public view

    return {
        "session_id":  session.id,
        "customer_id": session.customer_id,
        "title":       session.title,
        "turn_count":  sum(1 for m in messages if m.role == "user"),
        "history":     history,
        "created_at":  str(session.created_at),
        "updated_at":  str(session.updated_at),
    }


# ── DELETE /agent/sessions/{session_id} — clear session ──────────────────────

@router.delete("/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.query(AgentMessage).filter(AgentMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"message": "Session deleted", "session_id": session_id}
