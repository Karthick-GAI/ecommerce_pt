"""
Feedback loop routes — explicit feedback ingestion and adaptation management.

POST /feedback                  — record a thumbs-up / thumbs-down / not-interested event
GET  /feedback/loop/stats       — service-wide loop performance metrics
GET  /feedback/{customer_id}            — customer's full feedback history
GET  /feedback/{customer_id}/stats      — customer's adaptation weights + recent history
POST /feedback/{customer_id}/reset      — wipe all learned adaptation for a customer
"""
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ExplicitFeedback
from feedback_engine import (
    record_explicit_feedback,
    get_feedback_stats,
    reset_adaptation,
    get_loop_performance,
)

router = APIRouter(prefix="/feedback", tags=["Feedback Loop"])


# ── Request schema ────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    customer_id:   str
    product_id:    str
    feedback_type: Literal["thumbs_up", "thumbs_down", "not_interested"]
    rec_strategy:  Optional[str] = None   # which recommender surfaced this item


# ── POST /feedback ─────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def give_explicit_feedback(
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
):
    """
    Record explicit feedback on a recommendation.
    Immediately updates the customer's FeedbackAdaptation weights so the next
    call to /recommendations/for/{customer_id} reflects the change.
    """
    adaptation = record_explicit_feedback(
        db,
        customer_id   = payload.customer_id,
        product_id    = payload.product_id,
        feedback_type = payload.feedback_type,
        rec_strategy  = payload.rec_strategy,
    )

    _msgs = {
        "thumbs_up":      "Great! We'll show you more recommendations like this.",
        "thumbs_down":    "Got it — we'll reduce similar items in your feed.",
        "not_interested": "Removed. This product won't appear in your recommendations again.",
    }

    return {
        "message":       _msgs[payload.feedback_type],
        "customer_id":   payload.customer_id,
        "product_id":    payload.product_id,
        "feedback_type": payload.feedback_type,
        "adaptation_summary": {
            "total_thumbs_up":   adaptation.total_thumbs_up,
            "total_thumbs_down": adaptation.total_thumbs_down,
            "blocked_count":     len(adaptation.blocked_products or []),
            "category_boosts":   {
                k: round(v, 3)
                for k, v in (adaptation.category_boosts or {}).items()
            },
        },
    }


# ── GET /feedback/loop/stats ──────────────────────────────────────────────────
# IMPORTANT: this must be defined BEFORE /{customer_id} to avoid route shadowing.

@router.get("/loop/stats")
def loop_performance(
    days: int = Query(30, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
):
    """
    Service-wide feedback loop performance over the last N days:
    total events, acceptance rate, top liked categories, top strategies.
    """
    return get_loop_performance(db, days=days)


# ── GET /feedback/{customer_id}/stats ─────────────────────────────────────────

@router.get("/{customer_id}/stats")
def customer_adaptation_stats(customer_id: str, db: Session = Depends(get_db)):
    """
    Current adaptation weights for a customer:
    category/brand boosts, blocked count, thumbs ratio, recent feedback events.
    """
    return {"customer_id": customer_id, **get_feedback_stats(db, customer_id)}


# ── GET /feedback/{customer_id} ───────────────────────────────────────────────

@router.get("/{customer_id}")
def customer_feedback_history(
    customer_id:   str,
    feedback_type: Optional[Literal["thumbs_up", "thumbs_down", "not_interested"]] = Query(None),
    limit:         int = Query(50, ge=1, le=500),
    page:          int = Query(1,  ge=1),
    db: Session        = Depends(get_db),
):
    """All explicit feedback events for a customer, most recent first."""
    q = db.query(ExplicitFeedback).filter(
        ExplicitFeedback.customer_id == customer_id
    )
    if feedback_type:
        q = q.filter(ExplicitFeedback.feedback_type == feedback_type)

    total  = q.count()
    events = (
        q.order_by(ExplicitFeedback.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "customer_id": customer_id,
        "total":       total,
        "page":        page,
        "feedback":    [_fmt(f) for f in events],
    }


# ── POST /feedback/{customer_id}/reset ───────────────────────────────────────

@router.post("/{customer_id}/reset")
def reset_customer_adaptation(customer_id: str, db: Session = Depends(get_db)):
    """
    Clear all learned adaptation weights for this customer.
    Recommendations revert to pure collaborative/content/trending signals.
    """
    return reset_adaptation(db, customer_id)


# ── Internal formatter ────────────────────────────────────────────────────────

def _fmt(f: ExplicitFeedback) -> dict:
    return {
        "feedback_id":   f.id,
        "product_id":    f.product_id,
        "product_name":  f.product_name,
        "category":      f.category,
        "brand":         f.brand,
        "feedback_type": f.feedback_type,
        "rec_strategy":  f.rec_strategy,
        "created_at":    str(f.created_at),
    }
