# routes/product_routes.py — Product catalogue CRUD + detail pages
#
# ENDPOINTS:
#   GET    /products              paginated list with filters & sort
#   GET    /products/{id}         full detail: images, specs, rating dist, reviews
#   POST   /products              create product (auto-embeds for semantic search)
#   PUT    /products/{id}         update product (re-embeds if name/desc/tags changed)
#   DELETE /products/{id}         soft-delete (is_active=False, nulls embedding)

from typing import Optional
import math
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Product, ProductImage, Review
from schemas import (
    ProductResponse, ProductDetailResponse, ProductCreate, ProductUpdate,
    ProductImageResponse, ReviewResponse, PaginatedProducts,
)
from embeddings import embed_text, build_product_text

router = APIRouter(prefix="/products", tags=["Products"])


SORT_MAP = {
    "price_asc":  Product.price.asc(),
    "price_desc": Product.price.desc(),
    "rating":     Product.rating_avg.desc(),
    "newest":     Product.created_at.desc(),
    "discount":   Product.discount_pct.desc(),
    "popularity": Product.rating_count.desc(),
}


def _apply_filters(q, category, subcategory, brand, price_min, price_max, rating_min, in_stock):
    if category:    q = q.filter(Product.category == category)
    if subcategory: q = q.filter(Product.subcategory == subcategory)
    if brand:       q = q.filter(Product.brand == brand)
    if price_min is not None:
        q = q.filter(Product.price * (1 - Product.discount_pct / 100) >= price_min)
    if price_max is not None:
        q = q.filter(Product.price * (1 - Product.discount_pct / 100) <= price_max)
    if rating_min is not None:
        q = q.filter(Product.rating_avg >= rating_min)
    if in_stock:
        q = q.filter(Product.inventory_count > 0)
    return q


# ── LIST ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedProducts)
def list_products(
    category:    Optional[str]   = None,
    subcategory: Optional[str]   = None,
    brand:       Optional[str]   = None,
    price_min:   Optional[float] = None,
    price_max:   Optional[float] = None,
    rating_min:  Optional[float] = Query(None, ge=1, le=5),
    in_stock:    bool            = False,
    sort_by:     str             = Query("newest", enum=list(SORT_MAP)),
    page:        int             = Query(1, ge=1),
    limit:       int             = Query(20, ge=1, le=100),
    db:          Session         = Depends(get_db),
):
    """
    Paginated product listing with filters.
    Example: /products?category=Electronics&brand=Apple&price_max=100000&sort_by=rating
    """
    q = db.query(Product).filter(Product.is_active == True)
    q = _apply_filters(q, category, subcategory, brand, price_min, price_max, rating_min, in_stock)
    total    = q.count()
    products = q.order_by(SORT_MAP[sort_by]).offset((page - 1) * limit).limit(limit).all()

    return PaginatedProducts(
        total=total,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total / limit)) if total else 1,
        results=[ProductResponse.from_orm_product(p) for p in products],
    )


# ── DETAIL PAGE ───────────────────────────────────────────────────────────────

@router.get("/{product_id}", response_model=ProductDetailResponse)
def get_product(product_id: str, db: Session = Depends(get_db)):
    """
    Full product detail page — all images, specs, rating breakdown, and top 10 reviews.
    """
    p = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    dist_rows = (
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.product_id == product_id)
        .group_by(Review.rating)
        .all()
    )
    rating_distribution = {str(i): 0 for i in range(1, 6)}
    for star, count in dist_rows:
        rating_distribution[str(star)] = count

    top_reviews = (
        db.query(Review)
        .filter(Review.product_id == product_id)
        .order_by(Review.helpful_votes.desc(), Review.created_at.desc())
        .limit(10)
        .all()
    )

    images = sorted(p.images, key=lambda i: i.sort_order)
    base   = ProductResponse.from_orm_product(p)

    return ProductDetailResponse(
        **base.model_dump(),
        description=p.description,
        specifications=p.specifications,
        inventory_count=p.inventory_count,
        images=[ProductImageResponse.model_validate(img) for img in images],
        rating_distribution=rating_distribution,
        top_reviews=[ReviewResponse.model_validate(r) for r in top_reviews],
        created_at=p.created_at,
    )


# ── CREATE ────────────────────────────────────────────────────────────────────

@router.post("", response_model=ProductDetailResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """Create a product and immediately embed it for semantic search."""
    product = Product(**payload.model_dump())
    db.add(product)
    db.flush()   # get the generated ID before embed

    product.embedding = embed_text(build_product_text(product))
    db.commit()
    db.refresh(product)
    return get_product(product.id, db)


# ── UPDATE ────────────────────────────────────────────────────────────────────

@router.put("/{product_id}", response_model=ProductDetailResponse)
def update_product(product_id: str, payload: ProductUpdate, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    changes = payload.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(p, field, value)

    if any(f in changes for f in ("name", "description", "tags")):
        p.embedding = embed_text(build_product_text(p))

    db.commit()
    db.refresh(p)
    return get_product(product_id, db)


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.delete("/{product_id}")
def delete_product(product_id: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    p.is_active  = False
    p.embedding  = None     # free vector storage; product stays in DB for order history
    db.commit()
    return {"message": "Product removed from catalogue"}
