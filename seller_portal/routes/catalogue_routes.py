"""
Seller catalogue management.

Sellers can create, update, and manage their product listings.
Products go through a draft → pending_review → approved/rejected workflow
before becoming visible to consumers in the main product catalogue.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Seller, SellerProduct
from schemas import ProductCreate, ProductUpdate, ProductResponse
from dependencies import get_current_seller

router = APIRouter(prefix="/seller/catalogue", tags=["Seller Catalogue"])


@router.get("", response_model=list[ProductResponse])
def list_products(
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """List all products owned by the authenticated seller."""
    return db.query(SellerProduct).filter(SellerProduct.seller_id == seller.id).all()


@router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """
    Add a new product to the seller's catalogue.
    Status starts as **draft** — call /submit to send for admin review.
    """
    if db.query(SellerProduct).filter(SellerProduct.sku == payload.sku).first():
        raise HTTPException(status_code=400, detail=f"SKU '{payload.sku}' already exists")

    discount = round((1 - payload.selling_price / payload.mrp) * 100, 1) if payload.mrp > 0 else 0.0

    product = SellerProduct(
        seller_id=seller.id,
        discount_pct=discount,
        **payload.model_dump(),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    product = _get_owned(product_id, seller.id, db)
    return product


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """
    Update product details.
    Editing an approved product resets it to **pending_review** — changes must be
    re-approved before going live (prevents fraudulent post-approval edits).
    """
    product = _get_owned(product_id, seller.id, db)

    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(product, field, value)

    # Recalculate discount
    if "selling_price" in updates:
        product.discount_pct = round((1 - product.selling_price / product.mrp) * 100, 1)

    # Re-trigger review if product was live
    if product.approval_status == "approved":
        product.approval_status = "pending_review"
        product.is_active = False

    product.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/submit", response_model=ProductResponse)
def submit_for_review(
    product_id: str,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """Submit a draft product for admin review."""
    product = _get_owned(product_id, seller.id, db)

    if product.approval_status not in ("draft", "rejected"):
        raise HTTPException(
            status_code=400,
            detail=f"Product is already '{product.approval_status}' — only draft/rejected can be submitted",
        )

    product.approval_status  = "pending_review"
    product.rejection_reason = None
    product.updated_at       = datetime.utcnow()
    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/approve", tags=["Seller Admin"])
def approve_product(product_id: str, db: Session = Depends(get_db)):
    """Admin: approve a product for listing in the consumer catalogue."""
    product = db.query(SellerProduct).filter(SellerProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.approval_status = "approved"
    product.is_active       = True
    product.updated_at      = datetime.utcnow()
    db.commit()
    return {"message": "Product approved and now live.", "product_id": product_id}


@router.post("/{product_id}/reject", tags=["Seller Admin"])
def reject_product(product_id: str, reason: str, db: Session = Depends(get_db)):
    """Admin: reject a product with a reason so the seller can fix and resubmit."""
    product = db.query(SellerProduct).filter(SellerProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.approval_status  = "rejected"
    product.rejection_reason = reason
    product.is_active        = False
    product.updated_at       = datetime.utcnow()
    db.commit()
    return {"message": "Product rejected.", "reason": reason}


@router.patch("/{product_id}/stock")
def update_stock(
    product_id: str,
    delta: int,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """
    Adjust inventory count by `delta` (positive = restock, negative = correction).
    Prevents stock from going below zero.
    """
    product = _get_owned(product_id, seller.id, db)
    new_count = product.inventory_count + delta
    if new_count < 0:
        raise HTTPException(status_code=400, detail=f"Stock cannot go below zero (current: {product.inventory_count})")

    product.inventory_count = new_count
    product.updated_at      = datetime.utcnow()
    db.commit()
    return {"product_id": product_id, "new_stock": new_count, "delta_applied": delta}


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_owned(product_id: str, seller_id: str, db: Session) -> SellerProduct:
    product = db.query(SellerProduct).filter(
        SellerProduct.id == product_id,
        SellerProduct.seller_id == seller_id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
