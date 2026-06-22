"""
User preference profile endpoints.

A profile captures a customer's inferred interests: top categories, brands,
price range — derived from purchase history (orders) + browsing signals.
Used internally by the hybrid recommender to personalise results.
"""
from collections import Counter
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from models import Product, Customer, UserPreferenceProfile, BrowsingEvent, Wishlist

router = APIRouter(prefix="/recommendations/profile", tags=["User Profile"])


# ── GET /{customer_id} ────────────────────────────────────────────────────────

@router.get("/{customer_id}")
def get_profile(customer_id: str, db: Session = Depends(get_db)):
    """
    Return the stored preference profile.
    If none exists yet, compute and save it on-the-fly.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    profile = db.query(UserPreferenceProfile).filter(
        UserPreferenceProfile.customer_id == customer_id
    ).first()

    if not profile:
        profile = _compute_and_save(db, customer_id)

    if not profile:
        return {
            "customer_id":   customer_id,
            "customer_name": f"{customer.first_name} {customer.last_name}",
            "message":       "No interaction history found. Profile will build as you shop.",
            "profile":       None,
        }

    return {
        "customer_id":   customer_id,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "profile": {
            "top_categories":    profile.top_categories,
            "top_brands":        profile.top_brands,
            "top_subcategories": profile.top_subcategories,
            "price_range": {
                "min": profile.price_min,
                "max": profile.price_max,
                "avg": profile.avg_price,
            },
            "total_purchases":    profile.total_purchases,
            "total_interactions": profile.total_interactions,
            "last_computed_at":   str(profile.last_computed_at),
        },
    }


# ── POST /{customer_id}/refresh ───────────────────────────────────────────────

@router.post("/{customer_id}/refresh")
def refresh_profile(customer_id: str, db: Session = Depends(get_db)):
    """Recompute the preference profile from latest history."""
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    profile = _compute_and_save(db, customer_id)
    if not profile:
        return {"message": "No history to build profile from", "customer_id": customer_id}

    return {
        "message":       "Profile refreshed",
        "customer_id":   customer_id,
        "top_categories": profile.top_categories,
        "total_purchases": profile.total_purchases,
        "last_computed_at": str(profile.last_computed_at),
    }


# ── GET /{customer_id}/history ────────────────────────────────────────────────

@router.get("/{customer_id}/history")
def purchase_history(
    customer_id: str,
    limit:       int = Query(20, ge=1, le=200),
    db: Session      = Depends(get_db),
):
    """
    Summary of this customer's purchase history from the dataset orders.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    sql = text("""
        SELECT
            item.product_id,
            item.quantity,
            item.unit_price,
            o.order_id,
            o.order_status,
            o.created_at
        FROM orders o,
        LATERAL jsonb_to_recordset(o.cart_activity)
            AS item(product_id text, quantity int, unit_price float)
        WHERE o.user_id = :cid
        ORDER BY o.created_at DESC
        LIMIT :limit
    """)
    rows = db.execute(sql, {"cid": customer_id, "limit": limit}).fetchall()

    # Enrich with product names
    pids    = list({r.product_id for r in rows})
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}

    items = []
    for r in rows:
        p = products.get(r.product_id)
        items.append({
            "order_id":   r.order_id,
            "product_id": r.product_id,
            "name":       p.name     if p else "Unknown",
            "category":   p.category if p else None,
            "brand":      p.brand    if p else None,
            "quantity":   r.quantity,
            "unit_price": r.unit_price,
            "status":     r.order_status,
            "ordered_at": str(r.created_at),
        })

    return {
        "customer_id":   customer_id,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "total_items":   len(items),
        "history":       items,
    }


# ── GET /summary — aggregate stats ───────────────────────────────────────────

@router.get("")
def profiles_summary(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Summary of all computed user preference profiles."""
    total    = db.query(UserPreferenceProfile).count()
    profiles = (
        db.query(UserPreferenceProfile)
        .order_by(UserPreferenceProfile.total_purchases.desc())
        .limit(limit)
        .all()
    )
    return {
        "total_profiles": total,
        "top_buyers": [
            {
                "customer_id":     p.customer_id,
                "total_purchases": p.total_purchases,
                "top_category":    (
                    max(p.top_categories, key=p.top_categories.get)
                    if p.top_categories else None
                ),
                "avg_price":       p.avg_price,
            }
            for p in profiles
        ],
    }


# ── Internal: compute & persist a profile ────────────────────────────────────

def _compute_and_save(db: Session, customer_id: str) -> UserPreferenceProfile | None:
    """
    Build preference profile from:
      - orders.cart_activity  (purchase signals, weighted highest)
      - browsing_events       (view / add_to_cart / wishlist)
      - wishlists
    """
    # ── Purchase data from dataset orders ─────────────────────────────────
    sql = text("""
        SELECT item.product_id, item.quantity, item.unit_price
        FROM orders o,
        LATERAL jsonb_to_recordset(o.cart_activity)
            AS item(product_id text, quantity int, unit_price float)
        WHERE o.user_id = :cid
    """)
    purchases = db.execute(sql, {"cid": customer_id}).fetchall()

    # ── Browsing signals ──────────────────────────────────────────────────
    browsing = (
        db.query(BrowsingEvent)
        .filter(
            BrowsingEvent.user_id == customer_id,
            BrowsingEvent.event_type.in_(["add_to_cart", "wishlist", "purchase"]),
        )
        .all()
    )

    # ── Wishlists ─────────────────────────────────────────────────────────
    wishlist_items = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == customer_id)
        .all()
    )

    if not purchases and not browsing and not wishlist_items:
        return None

    # ── Aggregate product signals ─────────────────────────────────────────
    product_weight: Counter = Counter()
    for p in purchases:
        product_weight[p.product_id] += p.quantity * 3   # purchase = highest weight
    for b in browsing:
        w = 2 if b.event_type in ("purchase", "add_to_cart") else 1
        product_weight[b.product_id] += w
    for w in wishlist_items:
        product_weight[w.product_id] += 1

    if not product_weight:
        return None

    # ── Enrich with product attributes ───────────────────────────────────
    pids     = list(product_weight.keys())
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}

    cat_counter:    Counter = Counter()
    brand_counter:  Counter = Counter()
    subcat_counter: Counter = Counter()
    prices:         list[float] = []

    for pid, weight in product_weight.items():
        prod = products.get(pid)
        if not prod:
            continue
        cat_counter[prod.category]       += weight
        brand_counter[prod.brand]        += weight
        subcat_counter[prod.subcategory] += weight

    # Price range from purchase history only
    for p in purchases:
        if p.unit_price and p.unit_price > 0:
            prices.append(float(p.unit_price))

    if not prices:
        # Fall back to product list prices if no purchase prices available
        for pid in product_weight:
            prod = products.get(pid)
            if prod and prod.price:
                prices.append(prod.price)

    now = datetime.now(timezone.utc)

    # ── Upsert the profile ────────────────────────────────────────────────
    profile = db.query(UserPreferenceProfile).filter(
        UserPreferenceProfile.customer_id == customer_id
    ).first()

    data = {
        "top_categories":    dict(cat_counter.most_common(10)),
        "top_brands":        dict(brand_counter.most_common(10)),
        "top_subcategories": dict(subcat_counter.most_common(10)),
        "price_min":         round(min(prices), 2) if prices else None,
        "price_max":         round(max(prices), 2) if prices else None,
        "avg_price":         round(sum(prices) / len(prices), 2) if prices else None,
        "total_purchases":   len(purchases),
        "total_interactions": len(browsing) + len(wishlist_items),
        "last_computed_at":  now,
    }

    if profile:
        for k, v in data.items():
            setattr(profile, k, v)
    else:
        profile = UserPreferenceProfile(customer_id=customer_id, **data)
        db.add(profile)

    db.commit()
    db.refresh(profile)
    return profile
