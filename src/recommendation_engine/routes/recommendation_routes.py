import threading
from datetime import datetime, timezone
from typing import Optional, Literal

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import Product, Customer
from recommenders.collaborative import (
    get_bought_together, get_also_bought_checkout, get_user_based_cf,
)
from recommenders.content_based import get_similar_by_vector, get_similar_by_attributes
from recommenders.trending import get_trending, get_top_viewed, get_new_arrivals, get_top_deals
from recommenders.hybrid import get_personalized, get_homepage_feed
from recommenders.utils import merge_ranked, deduplicate
from feedback_engine import apply_adaptation, get_adaptation

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

# ── In-process TTL caches (ADR-008) ──────────────────────────────────────────
# Discovery endpoints (trending, deals, top-viewed, new-arrivals) are global —
# same result for any user, stable for 30 minutes.
# Homepage feed is per-customer, stable for 5 minutes before re-personalisation.
_trending_cache:   TTLCache = TTLCache(maxsize=32,  ttl=1800)  # 30 min
_deals_cache:      TTLCache = TTLCache(maxsize=16,  ttl=1800)  # 30 min
_topviewed_cache:  TTLCache = TTLCache(maxsize=16,  ttl=900)   # 15 min
_arrivals_cache:   TTLCache = TTLCache(maxsize=16,  ttl=900)   # 15 min
_homepage_cache:   TTLCache = TTLCache(maxsize=500, ttl=300)   # 5 min, keyed on customer_id
_reccats_cache:    TTLCache = TTLCache(maxsize=4,   ttl=3600)  # 1 h, category list

_trending_lock  = threading.Lock()
_deals_lock     = threading.Lock()
_topviewed_lock = threading.Lock()
_arrivals_lock  = threading.Lock()
_homepage_lock  = threading.Lock()
_reccats_lock   = threading.Lock()


# ── GET /recommendations/homepage/{customer_id} ───────────────────────────────

@router.get("/homepage/{customer_id}", tags=["Personalised"])
def homepage_feed(customer_id: str, db: Session = Depends(get_db)):
    """
    Full personalised homepage with multiple recommendation sections.
    Works for both dataset customers and app-registered users.
    Cached per customer for 5 minutes.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    # Don't 404 for app-registered users — fall through to interaction-based personalization.
    customer_name = f"{customer.first_name} {customer.last_name}" if customer else "there"

    with _homepage_lock:
        if customer_id in _homepage_cache:
            return _homepage_cache[customer_id]

    sections = get_homepage_feed(db, customer_id)
    result = {
        "customer_id":    customer_id,
        "customer_name":  customer_name,
        "sections":       sections,
        "total_sections": len(sections),
        "generated_at":   str(datetime.now(timezone.utc)),
    }

    with _homepage_lock:
        _homepage_cache[customer_id] = result
    return result


# ── GET /recommendations/for/{customer_id} ────────────────────────────────────

@router.get("/for/{customer_id}", tags=["Personalised"])
def personalized(
    customer_id:       str,
    limit:             int  = Query(20, ge=1, le=100),
    exclude_purchased: bool = Query(True, description="Exclude already-purchased products"),
    db: Session             = Depends(get_db),
):
    """
    Flat ranked list of personalised recommendations for a customer.
    Results are post-processed by the customer's FeedbackAdaptation weights:
    thumbed-up categories rise, thumbed-down categories fall, blocked products are removed.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    customer_name = f"{customer.first_name} {customer.last_name}" if customer else "there"

    # Generate 2× the requested limit so blocking/filtering still returns enough items
    recs = get_personalized(db, customer_id, limit=limit * 2,
                            exclude_purchased=exclude_purchased)

    # Apply feedback adaptation (re-rank + remove blocked products)
    adaptation = get_adaptation(db, customer_id)
    recs = apply_adaptation(recs, adaptation)[:limit]

    adapted = adaptation is not None and (
        bool(adaptation.category_boosts) or bool(adaptation.blocked_products)
    )

    return {
        "customer_id":      customer_id,
        "customer_name":    customer_name,
        "count":            len(recs),
        "feedback_adapted": adapted,
        "recommendations":  recs,
    }


# ── GET /recommendations/similar/{product_id} ─────────────────────────────────

@router.get("/similar/{product_id}", tags=["Product Discovery"])
def similar_products(
    product_id: str,
    strategy:   Optional[Literal["vector", "attributes", "both"]] = Query("both"),
    limit:      int = Query(10, ge=1, le=50),
    db: Session     = Depends(get_db),
):
    """
    Products similar to a given product.
    strategy=vector    → pgvector cosine similarity on product embeddings
    strategy=attributes→ category / subcategory / price-range matching
    strategy=both      → merge of both (default)
    """
    product = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    recs = []
    if strategy in ("vector", "both"):
        recs += get_similar_by_vector(db, product_id, limit=limit)
    if strategy in ("attributes", "both"):
        excl = [r["product_id"] for r in recs]
        recs += get_similar_by_attributes(db, product, limit=limit,
                                          exclude_ids=excl)

    recs = deduplicate(recs, keep=limit)

    return {
        "product_id":   product_id,
        "product_name": product.name,
        "strategy":     strategy,
        "count":        len(recs),
        "similar":      recs,
    }


# ── GET /recommendations/bought-together/{product_id} ─────────────────────────

@router.get("/bought-together/{product_id}", tags=["Product Discovery"])
def bought_together(
    product_id: str,
    limit:      int = Query(10, ge=1, le=30),
    db: Session     = Depends(get_db),
):
    """Products most frequently co-purchased with this product."""
    product = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Merge dataset orders (JSONB) + checkout service orders
    dataset_recs  = get_bought_together(db, product_id, limit=limit * 2)
    checkout_recs = get_also_bought_checkout(db, product_id, limit=limit)

    recs = deduplicate(
        merge_ranked(dataset_recs, checkout_recs, weights=[0.7, 0.3], limit=limit)
    )

    return {
        "product_id":   product_id,
        "product_name": product.name,
        "count":        len(recs),
        "bought_together": recs,
    }


# ── GET /recommendations/trending ─────────────────────────────────────────────

@router.get("/trending", tags=["Discovery"])
def trending_products(
    days:     int           = Query(30, ge=1, le=90, description="Lookback window in days"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit:    int           = Query(20, ge=1, le=100),
    db: Session             = Depends(get_db),
):
    """Most purchased products in the last N days. Cached 30 minutes."""
    cache_key = (days, category, limit)
    with _trending_lock:
        if cache_key in _trending_cache:
            return _trending_cache[cache_key]

    recs = get_trending(db, days=days, limit=limit, category=category)
    result = {"period_days": days, "category": category, "count": len(recs), "trending": recs}

    with _trending_lock:
        _trending_cache[cache_key] = result
    return result


# ── GET /recommendations/top-viewed ───────────────────────────────────────────

@router.get("/top-viewed", tags=["Discovery"])
def top_viewed(
    days:  int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Most engaged-with products from browsing activity. Cached 15 minutes."""
    cache_key = (days, limit)
    with _topviewed_lock:
        if cache_key in _topviewed_cache:
            return _topviewed_cache[cache_key]

    recs = get_top_viewed(db, days=days, limit=limit)
    result = {"period_days": days, "count": len(recs), "top_viewed": recs}

    with _topviewed_lock:
        _topviewed_cache[cache_key] = result
    return result


# ── GET /recommendations/new-arrivals ─────────────────────────────────────────

@router.get("/new-arrivals", tags=["Discovery"])
def new_arrivals(
    category: Optional[str] = Query(None),
    limit:    int           = Query(20, ge=1, le=100),
    db: Session             = Depends(get_db),
):
    """Most recently added products with available stock. Cached 15 minutes."""
    cache_key = (category, limit)
    with _arrivals_lock:
        if cache_key in _arrivals_cache:
            return _arrivals_cache[cache_key]

    recs = get_new_arrivals(db, limit=limit, category=category)
    result = {"category": category, "count": len(recs), "products": recs}

    with _arrivals_lock:
        _arrivals_cache[cache_key] = result
    return result


# ── GET /recommendations/deals ────────────────────────────────────────────────

@router.get("/deals", tags=["Discovery"])
def top_deals(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Highest-discount products with strong ratings and healthy stock. Cached 30 minutes."""
    cache_key = limit
    with _deals_lock:
        if cache_key in _deals_cache:
            return _deals_cache[cache_key]

    recs = get_top_deals(db, limit=limit)
    result = {"count": len(recs), "deals": recs}

    with _deals_lock:
        _deals_cache[cache_key] = result
    return result


# ── GET /recommendations/categories ───────────────────────────────────────────

@router.get("/categories", tags=["Discovery"])
def list_categories(db: Session = Depends(get_db)):
    """All product categories available for filtering recommendations. Cached 1 hour."""
    from sqlalchemy import func

    cache_key = "all"
    with _reccats_lock:
        if cache_key in _reccats_cache:
            return _reccats_cache[cache_key]

    rows = (
        db.query(Product.category, func.count(Product.id).label("count"))
        .filter(Product.is_active == True)
        .group_by(Product.category)
        .order_by(Product.category)
        .all()
    )
    result = {
        "total":      len(rows),
        "categories": [{"category": r.category, "product_count": r.count} for r in rows],
    }

    with _reccats_lock:
        _reccats_cache[cache_key] = result
    return result
