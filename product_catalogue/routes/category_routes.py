from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Category, Product
from schemas import CategoryResponse, BrandResponse

router = APIRouter(prefix="/categories", tags=["Categories & Brands"])


@router.get("", response_model=List[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    """All subcategories with their parent category."""
    return db.query(Category).order_by(Category.parent_name, Category.name).all()


@router.get("/brands", response_model=List[BrandResponse])
def list_brands(
    category: str = None,
    db: Session = Depends(get_db),
):
    """All brands with product count, optionally filtered by category."""
    q = db.query(Product.brand, func.count(Product.id).label("product_count"))
    if category:
        q = q.filter(Product.category == category)
    rows = (
        q.filter(Product.is_active == True)
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    return [BrandResponse(brand=r.brand, product_count=r.product_count) for r in rows]
