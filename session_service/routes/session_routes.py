"""
Session management routes.

POST   /sessions                        — create new session
GET    /sessions/{id}                   — get session with state
POST   /sessions/{id}/heartbeat         — refresh TTL
POST   /sessions/{id}/end               — end session gracefully
GET    /sessions/customer/{customer_id} — customer's session history
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import ShoppingSession, SessionEvent, SessionCartItem, Customer
from schemas import SessionCreate, SessionUpdate

router = APIRouter(prefix="/sessions", tags=["Sessions"])

TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))


def _check_expiry(session: ShoppingSession) -> ShoppingSession:
    """Mark session expired if inactive beyond TTL."""
    if session.status != "active":
        return session
    if session.last_activity_at:
        last = session.last_activity_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last > timedelta(minutes=TTL_MINUTES):
            session.status = "expired"
    return session


def _fmt(s: ShoppingSession, db: Session) -> dict:
    cart_count = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == s.id,
        SessionCartItem.saved_for_later == False,
    ).count()
    return {
        "session_id":      s.id,
        "customer_id":     s.customer_id,
        "status":          s.status,
        "device_type":     s.device_type,
        "referrer":        s.referrer,
        "entry_page":      s.entry_page,
        "page_count":      s.page_count,
        "event_count":     s.event_count,
        "cart_items":      cart_count,
        "converted":       s.converted,
        "started_at":      str(s.started_at),
        "last_activity_at": str(s.last_activity_at),
        "ended_at":        str(s.ended_at) if s.ended_at else None,
        "duration_mins":   _duration(s),
    }


def _duration(s: ShoppingSession) -> float | None:
    if not s.started_at:
        return None
    end = s.ended_at or s.last_activity_at or datetime.now(timezone.utc)
    start = s.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return round((end - start).total_seconds() / 60, 2)


# ── POST /sessions ────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    """Start a new shopping session. customer_id is optional for anonymous browsing."""
    if payload.customer_id:
        customer = db.query(Customer).filter(
            Customer.user_id == payload.customer_id
        ).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

    session = ShoppingSession(
        customer_id = payload.customer_id,
        device_type = payload.device_type,
        referrer    = payload.referrer,
        entry_page  = payload.entry_page,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "message":    "Session started",
        "session_id": session.id,
        "customer_id": session.customer_id,
        "started_at": str(session.started_at),
        "ttl_minutes": TTL_MINUTES,
    }


# ── GET /sessions/customer/{customer_id} ─────────────────────────────────────
# Defined BEFORE /{session_id} to prevent "customer" being treated as a session_id.

@router.get("/customer/{customer_id}")
def customer_sessions(
    customer_id: str,
    status:  Optional[Literal["active", "expired", "completed", "abandoned"]] = Query(None),
    limit:   int = Query(20, ge=1, le=100),
    page:    int = Query(1, ge=1),
    db: Session  = Depends(get_db),
):
    """All sessions for a customer, most recent first."""
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    q = db.query(ShoppingSession).filter(ShoppingSession.customer_id == customer_id)
    if status:
        q = q.filter(ShoppingSession.status == status)

    total    = q.count()
    sessions = q.order_by(ShoppingSession.started_at.desc()).offset((page - 1) * limit).limit(limit).all()

    # Auto-expire stale sessions
    changed = False
    for s in sessions:
        old_status = s.status
        _check_expiry(s)
        if s.status != old_status:
            changed = True
    if changed:
        db.commit()

    converted_count = sum(1 for s in sessions if s.converted)

    return {
        "customer_id":   customer_id,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "total":         total,
        "page":          page,
        "converted":     converted_count,
        "sessions":      [_fmt(s, db) for s in sessions],
    }


# ── GET /sessions/{session_id} ────────────────────────────────────────────────

@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Full session detail including recent events and cart summary."""
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    _check_expiry(session)
    db.commit()

    # Last 10 events
    recent_events = (
        db.query(SessionEvent)
        .filter(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.created_at.desc())
        .limit(10)
        .all()
    )

    # Cart summary
    cart_items = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id,
        SessionCartItem.saved_for_later == False,
    ).all()

    cart_total = sum((item.unit_price or 0) * (1 - (item.discount_pct or 0) / 100) * item.quantity
                     for item in cart_items)

    return {
        **_fmt(session, db),
        "recent_events": [
            {
                "event_type":  e.event_type,
                "product_name": e.product_name,
                "search_query": e.search_query,
                "page_path":   e.page_path,
                "created_at":  str(e.created_at),
            }
            for e in recent_events
        ],
        "cart_summary": {
            "item_count": len(cart_items),
            "total":      round(cart_total, 2),
            "products":   [i.product_name for i in cart_items[:3]],
        },
    }


# ── POST /sessions/{session_id}/heartbeat ────────────────────────────────────

@router.post("/{session_id}/heartbeat")
def heartbeat(session_id: str, payload: SessionUpdate, db: Session = Depends(get_db)):
    """Update last_activity_at to keep the session alive. Call every 60–120s."""
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed")

    _check_expiry(session)
    if session.status == "expired":
        db.commit()
        raise HTTPException(status_code=410, detail="Session has expired. Please start a new session.")

    session.last_activity_at = datetime.now(timezone.utc)
    if payload.page_path:
        session.page_count = (session.page_count or 0) + 1
    db.commit()

    return {
        "alive":            True,
        "session_id":       session_id,
        "last_activity_at": str(session.last_activity_at),
        "expires_at":       str(
            datetime.now(timezone.utc) + timedelta(minutes=TTL_MINUTES)
        ),
    }


# ── POST /sessions/{session_id}/end ──────────────────────────────────────────

@router.post("/{session_id}/end")
def end_session(
    session_id: str,
    converted:  bool = Query(False, description="True if session ended with a purchase"),
    db: Session      = Depends(get_db),
):
    """Gracefully end a session."""
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status in ("completed", "abandoned"):
        return {"message": f"Session already {session.status}", "session_id": session_id}

    session.status    = "completed" if converted else "abandoned"
    session.converted = converted
    session.ended_at  = datetime.now(timezone.utc)
    db.commit()

    return {
        "message":      f"Session {session.status}",
        "session_id":   session_id,
        "converted":    converted,
        "duration_mins": _duration(session),
        "event_count":  session.event_count,
    }
