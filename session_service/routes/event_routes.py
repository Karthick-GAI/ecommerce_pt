"""
Session event routes.

POST /sessions/{id}/events — log a single interaction event
GET  /sessions/{id}/events — retrieve events with optional type filter
"""
from datetime import datetime, timezone
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import ShoppingSession, SessionEvent, Product
from schemas import EventCreate

router = APIRouter(prefix="/sessions", tags=["Events"])


# ── POST /sessions/{session_id}/events ───────────────────────────────────────

@router.post("/{session_id}/events", status_code=201)
def log_event(session_id: str, payload: EventCreate, db: Session = Depends(get_db)):
    """
    Log an interaction event to a session.
    Automatically increments session event_count and updates last_activity_at.
    For product events, product details are auto-populated from the products table.
    """
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status not in ("active",):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot log events to a {session.status} session.",
        )

    product_name = None
    category     = None

    if payload.product_id:
        product = db.query(Product).filter(Product.id == payload.product_id).first()
        if product:
            product_name = product.name
            category     = product.category

    event = SessionEvent(
        session_id   = session_id,
        customer_id  = session.customer_id,
        event_type   = payload.event_type,
        product_id   = payload.product_id,
        product_name = product_name,
        category     = category,
        search_query = payload.search_query,
        page_path    = payload.page_path,
        event_metadata = payload.metadata,
    )
    db.add(event)

    # Update session counters
    session.event_count      = (session.event_count or 0) + 1
    session.last_activity_at = datetime.now(timezone.utc)
    if payload.event_type == "page_view":
        session.page_count = (session.page_count or 0) + 1
    if payload.event_type == "purchase":
        session.converted = True

    db.commit()
    db.refresh(event)

    return {
        "event_id":   event.id,
        "session_id": session_id,
        "event_type": payload.event_type,
        "product_name": product_name,
        "created_at": str(event.created_at),
    }


# ── GET /sessions/{session_id}/events ────────────────────────────────────────

@router.get("/{session_id}/events")
def get_events(
    session_id: str,
    event_type: Optional[Literal[
        "page_view", "product_view", "search",
        "add_to_cart", "remove_from_cart",
        "wishlist_add", "wishlist_remove",
        "checkout_start", "checkout_abandon", "purchase",
        "recommendation_click", "filter_apply", "sort_change", "review_view"
    ]] = Query(None),
    limit:      int = Query(50, ge=1, le=500),
    page:       int = Query(1, ge=1),
    db: Session     = Depends(get_db),
):
    """All events for a session, most recent first."""
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    q = db.query(SessionEvent).filter(SessionEvent.session_id == session_id)
    if event_type:
        q = q.filter(SessionEvent.event_type == event_type)

    total  = q.count()
    events = q.order_by(SessionEvent.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    # Event type breakdown for this session
    from sqlalchemy import func
    breakdown = dict(
        db.query(SessionEvent.event_type, func.count(SessionEvent.id))
        .filter(SessionEvent.session_id == session_id)
        .group_by(SessionEvent.event_type)
        .all()
    )

    return {
        "session_id":  session_id,
        "total":       total,
        "page":        page,
        "breakdown":   breakdown,
        "events": [
            {
                "event_id":    e.id,
                "event_type":  e.event_type,
                "product_id":  e.product_id,
                "product_name": e.product_name,
                "category":    e.category,
                "search_query": e.search_query,
                "page_path":   e.page_path,
                "metadata":    e.event_metadata,
                "created_at":  str(e.created_at),
            }
            for e in events
        ],
    }
