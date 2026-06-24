import threading
from typing import List, Optional

from cachetools import TTLCache
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Category, Product
from schemas import CategoryResponse, BrandResponse

router = APIRouter(prefix="/categories", tags=["Categories & Brands"])

# ── In-process caches (ADR-008) ───────────────────────────────────────────────
# Categories and brands change only when new products are added/removed.
# 1-hour TTL keeps the list fresh without hammering the DB on every browse page load.
_cat_cache:   TTLCache = TTLCache(maxsize=4,   ttl=3600)   # one entry: all categories
_brand_cache: TTLCache = TTLCache(maxsize=16,  ttl=3600)   # keyed on category string
_cat_lock   = threading.Lock()
_brand_lock = threading.Lock()


@router.get("", response_model=List[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    """All subcategories with their parent category. Cached for 1 hour."""
    cache_key = "all"
    with _cat_lock:
        if cache_key in _cat_cache:
            return _cat_cache[cache_key]

    rows = db.query(Category).order_by(Category.parent_name, Category.name).all()

    with _cat_lock:
        _cat_cache[cache_key] = rows
    return rows


@router.get("/brands", response_model=List[BrandResponse])
def list_brands(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """All brands with product count, optionally filtered by category. Cached for 1 hour."""
    cache_key = category or "all"
    with _brand_lock:
        if cache_key in _brand_cache:
            return _brand_cache[cache_key]

    q = db.query(Product.brand, func.count(Product.id).label("product_count"))
    if category:
        q = q.filter(Product.category == category)
    rows = (
        q.filter(Product.is_active == True)
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    result = [BrandResponse(brand=r.brand, product_count=r.product_count) for r in rows]

    with _brand_lock:
        _brand_cache[cache_key] = result
    return result
