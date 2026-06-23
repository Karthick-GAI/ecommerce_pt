"""Seller profile management."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Seller
from schemas import SellerProfileResponse, SellerProfileUpdate
from dependencies import get_current_seller

router = APIRouter(prefix="/seller/profile", tags=["Seller Profile"])


@router.get("", response_model=SellerProfileResponse)
def get_profile(seller: Seller = Depends(get_current_seller)):
    """Return the authenticated seller's profile."""
    return seller


@router.put("", response_model=SellerProfileResponse)
def update_profile(
    payload: SellerProfileUpdate,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """Update contact details. GST/PAN changes trigger re-verification."""
    updates = payload.model_dump(exclude_none=True)

    # Changes to compliance identifiers require re-verification
    if "gst_number" in updates or "pan_number" in updates:
        seller.status    = "pending_verification"
        seller.is_active = False

    for field, value in updates.items():
        setattr(seller, field, value)

    seller.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(seller)
    return seller
