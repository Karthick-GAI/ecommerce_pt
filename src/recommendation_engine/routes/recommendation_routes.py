from datetime import datetime, timezone
from typing import Optional, Literal
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

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# ── GET /recommendations/homepage/{customer_id} ───────────────────────────────

@router.get("/homepage/{customer_id}", tags=["Personalised"])
def homepage_feed(customer_id: str, db: Session = Depends(get_db)):
    """
    Full personalised homepage with multiple recommendation sections.
    Section count and strategy adapt to the customer's interaction depth.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    sections = get_homepage_feed(db, customer_id)

    return {
        "customer_id":   customer_id,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "sections":      sections,
        "total_sections": len(sections),
        "generated_at":  str(datetime.now(timezone.utc)),
    }


# ── GET /recommendations/for/{customer_id} ────────────────────────────────────

@router.get("/for/{customer_id}", tags=["Personalised"])
def personalized(
    customer_id:       str,
    limit:             int  = Query(20, ge=1, le=100),
    exclude_purchased: bool = Query(True, description="Exclude already-purchased products"),
    db: Session             = Depends(get_db),
):
    """Flat ranked list of personalised recommendations for a customer."""
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    recs = get_personalized(db, customer_id, limit=limit,
                            exclude_purchased=exclude_purchased)
    return {
        "customer_id":   customer_id,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "count":         len(recs),
        "recommendations": recs,
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
    """Most purchased products in the last N days."""
    recs = get_trending(db, days=days, limit=limit, category=category)
    return {
        "period_days": days,
        "category":    category,
        "count":       len(recs),
        "trending":    recs,
    }


# ── GET /recommendations/top-viewed ───────────────────────────────────────────

@router.get("/top-viewed", tags=["Discovery"])
def top_viewed(
    days:  int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Most engaged-with products from browsing activity (weighted by event type)."""
    recs = get_top_viewed(db, days=days, limit=limit)
    return {
        "period_days": days,
        "count":       len(recs),
        "top_viewed":  recs,
    }


# ── GET /recommendations/new-arrivals ─────────────────────────────────────────

@router.get("/new-arrivals", tags=["Discovery"])
def new_arrivals(
    category: Optional[str] = Query(None),
    limit:    int           = Query(20, ge=1, le=100),
    db: Session             = Depends(get_db),
):
    """Most recently added products with available stock."""
    recs = get_new_arrivals(db, limit=limit, category=category)
    return {
        "category": category,
        "count":    len(recs),
        "products": recs,
    }


# ── GET /recommendations/deals ────────────────────────────────────────────────

@router.get("/deals", tags=["Discovery"])
def top_deals(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Highest-discount products with strong ratings and healthy stock."""
    recs = get_top_deals(db, limit=limit)
    return {
        "count":   len(recs),
        "deals":   recs,
    }


# ── GET /recommendations/categories ───────────────────────────────────────────

@router.get("/categories", tags=["Discovery"])
def list_categories(db: Session = Depends(get_db)):
    """All product categories available for filtering recommendations."""
    from sqlalchemy import func
    rows = (
        db.query(Product.category, func.count(Product.id).label("count"))
        .filter(Product.is_active == True)
        .group_by(Product.category)
        .order_by(Product.category)
        .all()
    )
    return {
        "total":      len(rows),
        "categories": [{"category": r.category, "product_count": r.count} for r in rows],
    }
