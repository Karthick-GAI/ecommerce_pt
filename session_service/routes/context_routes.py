"""
Context routes — compiled AI-ready context payloads.

These endpoints aggregate everything known about a customer or session
into a single JSON object suitable for injection into an LLM system
prompt or tool response.

GET /context/{customer_id}          — full customer context (memory + live session)
GET /context/session/{session_id}   — session-scoped context
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import (
    Customer, CustomerMemory, ShoppingSession,
    SessionEvent, SessionCartItem,
)

router = APIRouter(prefix="/context", tags=["Context"])


def _active_session(customer_id: str, db: Session) -> ShoppingSession | None:
    return (
        db.query(ShoppingSession)
        .filter(
            ShoppingSession.customer_id == customer_id,
            ShoppingSession.status == "active",
        )
        .order_by(ShoppingSession.last_activity_at.desc())
        .first()
    )


def _session_context(session: ShoppingSession, db: Session) -> dict:
    events = (
        db.query(SessionEvent)
        .filter(SessionEvent.session_id == session.id)
        .order_by(SessionEvent.created_at.desc())
        .limit(20)
        .all()
    )

    cart_items = (
        db.query(SessionCartItem)
        .filter(
            SessionCartItem.session_id == session.id,
            SessionCartItem.saved_for_later == False,
        )
        .all()
    )

    cart_total = sum(
        (i.unit_price or 0) * (1 - (i.discount_pct or 0) / 100) * i.quantity
        for i in cart_items
    )

    # Recent searches
    searches = [
        e.search_query for e in events
        if e.event_type == "search" and e.search_query
    ][:5]

    # Recently viewed products
    viewed = [
        {"product_id": e.product_id, "product_name": e.product_name, "category": e.category}
        for e in events if e.event_type in ("product_view", "recommendation_click") and e.product_id
    ][:5]

    # Deduplicate viewed by product_id
    seen: set[str] = set()
    deduped_viewed = []
    for v in viewed:
        if v["product_id"] not in seen:
            seen.add(v["product_id"])
            deduped_viewed.append(v)

    start = session.started_at
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    duration = round((datetime.now(timezone.utc) - start).total_seconds() / 60, 1) if start else None

    return {
        "session_id":      session.id,
        "device_type":     session.device_type,
        "duration_mins":   duration,
        "page_count":      session.page_count,
        "event_count":     session.event_count,
        "recent_searches": searches,
        "recently_viewed": deduped_viewed,
        "cart": {
            "item_count": len(cart_items),
            "subtotal":   round(cart_total, 2),
            "products": [
                {
                    "product_name": i.product_name,
                    "quantity":     i.quantity,
                    "unit_price":   i.unit_price,
                }
                for i in cart_items
            ],
        },
    }


def _memory_context(mem: CustomerMemory) -> dict:
    return {
        "lifecycle_stage":        mem.lifecycle_stage,
        "top_categories":         list((mem.top_categories or {}).keys())[:5],
        "top_brands":             list((mem.top_brands or {}).keys())[:5],
        "price_range":            {"min": mem.price_min, "max": mem.price_max},
        "avg_order_value":        mem.avg_order_value,
        "total_purchases":        mem.total_purchases,
        "cart_to_purchase_rate":  mem.cart_to_purchase_rate,
        "recent_searches":        (mem.recent_searches or [])[:5],
        "recently_viewed_cats":   (mem.recently_viewed_categories or [])[:5],
        "days_since_last_visit":  mem.days_since_last_visit,
    }


# ── GET /context/{customer_id} ────────────────────────────────────────────────

@router.get("/{customer_id}")
def get_customer_context(customer_id: str, db: Session = Depends(get_db)):
    """
    Full AI context for a customer.

    Combines:
    - Customer profile (name, email, registration date)
    - Long-term memory (preferences, lifecycle, conversion rates)
    - Active session snapshot (cart, recent views, current searches)

    Use as a system prompt prefix or tool response payload.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    mem = db.query(CustomerMemory).filter(
        CustomerMemory.customer_id == customer_id
    ).first()

    active_session = _active_session(customer_id, db)

    context: dict = {
        "customer": {
            "customer_id":    customer_id,
            "name":           f"{customer.first_name} {customer.last_name}",
            "email":          customer.email,
            "member_since":   str(customer.created_at) if customer.created_at else None,
        },
        "memory":          _memory_context(mem) if mem else None,
        "active_session":  _session_context(active_session, db) if active_session else None,
        "has_memory":      mem is not None,
        "has_active_session": active_session is not None,
    }

    # Derive a natural-language summary for direct LLM injection
    summary_parts: list[str] = [
        f"{customer.first_name} is a {mem.lifecycle_stage} customer." if mem else f"{customer.first_name} is a new customer.",
    ]
    if mem and mem.top_categories:
        top_cat = next(iter(mem.top_categories))
        summary_parts.append(f"Their top category is {top_cat}.")
    if mem and mem.total_purchases:
        summary_parts.append(f"They have made {mem.total_purchases} purchases.")
    if active_session:
        cart_count = context["active_session"]["cart"]["item_count"]
        if cart_count:
            summary_parts.append(f"They currently have {cart_count} item(s) in their cart.")
        if context["active_session"]["recent_searches"]:
            q = context["active_session"]["recent_searches"][0]
            summary_parts.append(f"Most recent search: \"{q}\".")

    context["summary"] = " ".join(summary_parts)

    return context


# ── GET /context/session/{session_id} ────────────────────────────────────────
# Must be declared AFTER /{customer_id} would shadow it if both were /{id}
# — they use different prefixes so order here doesn't matter, but we keep
# the note for clarity.

@router.get("/session/{session_id}")
def get_session_context(session_id: str, db: Session = Depends(get_db)):
    """
    Lightweight context payload for a specific session.
    Includes customer memory if the session is authenticated.
    """
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    ctx = {
        "session": _session_context(session, db),
        "memory":  None,
        "customer": None,
    }

    if session.customer_id:
        customer = db.query(Customer).filter(
            Customer.user_id == session.customer_id
        ).first()
        if customer:
            ctx["customer"] = {
                "customer_id": session.customer_id,
                "name":  f"{customer.first_name} {customer.last_name}",
                "email": customer.email,
            }

        mem = db.query(CustomerMemory).filter(
            CustomerMemory.customer_id == session.customer_id
        ).first()
        if mem:
            ctx["memory"] = _memory_context(mem)

    return ctx
