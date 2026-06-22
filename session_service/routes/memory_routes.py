"""
Customer memory routes.

GET  /memory/{customer_id}         — retrieve computed memory
POST /memory/{customer_id}/refresh — recompute memory on-demand
GET  /memory                       — list all customer memories (analytics)
"""
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import CustomerMemory, Customer
from memory.builder import build_memory

router = APIRouter(prefix="/memory", tags=["Memory"])


def _fmt(m: CustomerMemory) -> dict:
    return {
        "customer_id":              m.customer_id,
        "lifecycle_stage":          m.lifecycle_stage,
        "top_categories":           m.top_categories,
        "top_brands":               m.top_brands,
        "top_subcategories":        m.top_subcategories,
        "price_min":                m.price_min,
        "price_max":                m.price_max,
        "avg_order_value":          m.avg_order_value,
        "total_sessions":           m.total_sessions,
        "total_events":             m.total_events,
        "total_searches":           m.total_searches,
        "total_purchases":          m.total_purchases,
        "total_wishlisted":         m.total_wishlisted,
        "total_cart_adds":          m.total_cart_adds,
        "view_to_cart_rate":        m.view_to_cart_rate,
        "cart_to_purchase_rate":    m.cart_to_purchase_rate,
        "recent_searches":          m.recent_searches,
        "recently_viewed_categories": m.recently_viewed_categories,
        "recently_viewed_products": m.recently_viewed_products,
        "first_seen_at":            str(m.first_seen_at) if m.first_seen_at else None,
        "last_seen_at":             str(m.last_seen_at)  if m.last_seen_at  else None,
        "days_since_last_visit":    m.days_since_last_visit,
        "last_computed_at":         str(m.last_computed_at) if m.last_computed_at else None,
    }


# ── GET /memory/{customer_id} ─────────────────────────────────────────────────

@router.get("/{customer_id}")
def get_memory(customer_id: str, db: Session = Depends(get_db)):
    """
    Return the cached customer memory.
    If no memory exists yet, computes it on-demand (first visit).
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    mem = db.query(CustomerMemory).filter(
        CustomerMemory.customer_id == customer_id
    ).first()

    if not mem:
        # Build on first access
        mem = build_memory(db, customer_id)
        if not mem:
            return {
                "customer_id":   customer_id,
                "lifecycle_stage": "new",
                "message":       "No interaction data yet. Memory will be built once events are recorded.",
            }

    return _fmt(mem)


# ── POST /memory/{customer_id}/refresh ───────────────────────────────────────

@router.post("/{customer_id}/refresh")
def refresh_memory(customer_id: str, db: Session = Depends(get_db)):
    """
    Force-recompute customer memory from all signals.
    Use after bulk imports or when memory may be stale.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    mem = build_memory(db, customer_id)
    if not mem:
        raise HTTPException(
            status_code=422,
            detail="No interaction data found for this customer. Cannot build memory.",
        )

    return {
        "message":         "Memory refreshed",
        "customer_id":     customer_id,
        "lifecycle_stage": mem.lifecycle_stage,
        "last_computed_at": str(mem.last_computed_at),
    }


# ── GET /memory ───────────────────────────────────────────────────────────────

@router.get("")
def list_memories(
    lifecycle_stage: Optional[Literal[
        "new", "exploring", "engaged", "repeat_buyer", "loyal", "at_risk"
    ]] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    page:  int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """
    Analytics view — list all customer memories, optionally filtered by lifecycle stage.
    Returns aggregate summary + per-customer list.
    """
    q = db.query(CustomerMemory)
    if lifecycle_stage:
        q = q.filter(CustomerMemory.lifecycle_stage == lifecycle_stage)

    total    = q.count()
    memories = q.order_by(CustomerMemory.last_computed_at.desc()) \
                .offset((page - 1) * limit).limit(limit).all()

    # Stage distribution across entire table (not just this page)
    from sqlalchemy import func
    stage_counts = dict(
        db.query(CustomerMemory.lifecycle_stage, func.count(CustomerMemory.id))
        .group_by(CustomerMemory.lifecycle_stage)
        .all()
    )

    return {
        "total":           total,
        "page":            page,
        "stage_filter":    lifecycle_stage,
        "stage_distribution": stage_counts,
        "customers": [
            {
                "customer_id":     m.customer_id,
                "lifecycle_stage": m.lifecycle_stage,
                "total_purchases": m.total_purchases,
                "avg_order_value": m.avg_order_value,
                "days_since_last_visit": m.days_since_last_visit,
                "top_category":    next(iter(m.top_categories or {}), None),
                "last_computed_at": str(m.last_computed_at) if m.last_computed_at else None,
            }
            for m in memories
        ],
    }
