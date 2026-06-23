# routes/review_routes.py — Product reviews and ratings
#
# ENDPOINTS:
#   GET    /products/{id}/reviews   paginated reviews (sort: newest/helpful/highest/lowest)
#   POST   /products/{id}/reviews   add a review → recomputes product rating
#   PUT    /reviews/{id}            edit a review → recomputes product rating
#   DELETE /reviews/{id}            delete a review → recomputes product rating
#   POST   /reviews/{id}/helpful    upvote a review as helpful

import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Review, Product
from schemas import ReviewCreate, ReviewResponse

router = APIRouter(tags=["Reviews & Ratings"])


def _recalculate_rating(product_id: str, db: Session):
    avg, count = (
        db.query(func.avg(Review.rating), func.count(Review.id))
        .filter(Review.product_id == product_id)
        .first()
    )
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.rating_avg   = round(float(avg or 0), 2)
        product.rating_count = count or 0
        db.commit()


# ── LIST ──────────────────────────────────────────────────────────────────────

@router.get("/products/{product_id}/reviews")
def list_reviews(
    product_id: str,
    sort_by: str = Query("newest", enum=["newest", "helpful", "highest", "lowest"]),
    page:    int = Query(1, ge=1),
    limit:   int = Query(10, ge=1, le=50),
    db:      Session = Depends(get_db),
):
    if not db.query(Product).filter(Product.id == product_id).first():
        raise HTTPException(status_code=404, detail="Product not found")

    q = db.query(Review).filter(Review.product_id == product_id)
    order = {
        "newest":  Review.created_at.desc(),
        "helpful": Review.helpful_votes.desc(),
        "highest": Review.rating.desc(),
        "lowest":  Review.rating.asc(),
    }[sort_by]

    total   = q.count()
    reviews = q.order_by(order).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / limit)) if total else 1,
        "results": [ReviewResponse.model_validate(r) for r in reviews],
    }


# ── ADD ───────────────────────────────────────────────────────────────────────

@router.post("/products/{product_id}/reviews", response_model=ReviewResponse, status_code=201)
def add_review(product_id: str, payload: ReviewCreate, db: Session = Depends(get_db)):
    if not db.query(Product).filter(Product.id == product_id, Product.is_active == True).first():
        raise HTTPException(status_code=404, detail="Product not found")

    review = Review(product_id=product_id, **payload.model_dump())
    db.add(review)
    db.commit()
    db.refresh(review)
    _recalculate_rating(product_id, db)
    return ReviewResponse.model_validate(review)


# ── EDIT ──────────────────────────────────────────────────────────────────────

@router.put("/reviews/{review_id}", response_model=ReviewResponse)
def update_review(review_id: str, payload: ReviewCreate, db: Session = Depends(get_db)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(review, field, value)
    db.commit()
    db.refresh(review)
    _recalculate_rating(review.product_id, db)
    return ReviewResponse.model_validate(review)


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.delete("/reviews/{review_id}")
def delete_review(review_id: str, db: Session = Depends(get_db)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    product_id = review.product_id
    db.delete(review)
    db.commit()
    _recalculate_rating(product_id, db)
    return {"message": "Review deleted"}


# ── HELPFUL ───────────────────────────────────────────────────────────────────

@router.post("/reviews/{review_id}/helpful")
def mark_helpful(review_id: str, db: Session = Depends(get_db)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.helpful_votes += 1
    db.commit()
    return {"helpful_votes": review.helpful_votes}
