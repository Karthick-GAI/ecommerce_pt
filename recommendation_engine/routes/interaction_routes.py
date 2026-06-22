from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import RecInteraction, Product, Customer
from schemas import InteractionRequest

router = APIRouter(prefix="/recommendations/interactions", tags=["Interactions"])


# ── POST — log a new interaction ──────────────────────────────────────────────

@router.post("", status_code=201)
def log_interaction(payload: InteractionRequest, db: Session = Depends(get_db)):
    """
    Track a user's interaction with a product recommendation.
    interaction_type: view | click | add_to_cart | purchase | wishlist | rating
    """
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if payload.interaction_type == "rating" and payload.rating is None:
        raise HTTPException(status_code=400,
                            detail="rating field is required when interaction_type is 'rating'")

    event = RecInteraction(
        customer_id      = payload.customer_id,
        product_id       = payload.product_id,
        product_name     = product.name,
        category         = product.category,
        brand            = product.brand,
        interaction_type = payload.interaction_type,
        rating           = payload.rating,
        session_id       = payload.session_id,
        source           = payload.source,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "message":          "Interaction recorded",
        "interaction_id":   event.id,
        "customer_id":      payload.customer_id,
        "product_id":       payload.product_id,
        "product_name":     product.name,
        "interaction_type": payload.interaction_type,
    }


# ── GET — customer's interaction history ─────────────────────────────────────

@router.get("/{customer_id}")
def get_interactions(
    customer_id:      str,
    interaction_type: Optional[Literal["view", "click", "add_to_cart",
                                       "purchase", "wishlist", "rating"]] = Query(None),
    limit:            int = Query(50,  ge=1, le=500),
    page:             int = Query(1,   ge=1),
    db: Session           = Depends(get_db),
):
    """All recommendation interactions for a customer, most recent first."""
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    q = db.query(RecInteraction).filter(RecInteraction.customer_id == customer_id)
    if interaction_type:
        q = q.filter(RecInteraction.interaction_type == interaction_type)

    total  = q.count()
    events = (
        q.order_by(RecInteraction.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "customer_id":   customer_id,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "total":         total,
        "page":          page,
        "interactions":  [_fmt(e) for e in events],
    }


# ── GET — product interaction summary ────────────────────────────────────────

@router.get("/product/{product_id}/summary")
def product_interaction_summary(product_id: str, db: Session = Depends(get_db)):
    """Aggregated interaction stats for a product across all customers."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    from sqlalchemy import func
    rows = (
        db.query(RecInteraction.interaction_type, func.count(RecInteraction.id))
        .filter(RecInteraction.product_id == product_id)
        .group_by(RecInteraction.interaction_type)
        .all()
    )
    stats = {r[0]: r[1] for r in rows}

    avg_rating = db.query(func.avg(RecInteraction.rating)).filter(
        RecInteraction.product_id == product_id,
        RecInteraction.interaction_type == "rating",
    ).scalar()

    return {
        "product_id":   product_id,
        "product_name": product.name,
        "interactions": stats,
        "avg_rating":   round(float(avg_rating), 2) if avg_rating else None,
        "total":        sum(stats.values()),
    }


def _fmt(e: RecInteraction) -> dict:
    return {
        "interaction_id":   e.id,
        "product_id":       e.product_id,
        "product_name":     e.product_name,
        "category":         e.category,
        "brand":            e.brand,
        "interaction_type": e.interaction_type,
        "rating":           e.rating,
        "source":           e.source,
        "session_id":       e.session_id,
        "created_at":       str(e.created_at),
    }
