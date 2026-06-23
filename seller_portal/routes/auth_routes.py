"""Seller authentication: register, login."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from database import get_db
from models import Seller
from schemas import SellerRegister, SellerLogin, SellerToken
from auth import hash_password, verify_password, create_seller_token

router  = APIRouter(prefix="/seller/auth", tags=["Seller Auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def register(request: Request, payload: SellerRegister, db: Session = Depends(get_db)):
    """
    Onboard a new merchant.
    Account starts in **pending_verification** — an admin must approve before login is allowed.
    """
    if db.query(Seller).filter(Seller.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(Seller).filter(Seller.business_name == payload.business_name).first():
        raise HTTPException(status_code=400, detail="Business name already taken")

    seller = Seller(
        business_name=payload.business_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        phone=payload.phone,
        gst_number=payload.gst_number,
        status="pending_verification",
        is_active=False,
    )
    db.add(seller)
    db.commit()
    db.refresh(seller)

    return {
        "message":   "Seller account created. Pending KYC verification by admin.",
        "seller_id": seller.id,
        "status":    seller.status,
    }


@router.post("/login", response_model=SellerToken)
@limiter.limit("5/minute")
def login(request: Request, payload: SellerLogin, db: Session = Depends(get_db)):
    """Login for approved merchant accounts. Rate-limited to prevent brute force."""
    seller = db.query(Seller).filter(Seller.email == payload.email).first()
    if not seller or not verify_password(payload.password, seller.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if seller.status == "pending_verification":
        raise HTTPException(status_code=403, detail="Account pending KYC verification")
    if seller.status == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended — contact support")
    if not seller.is_active:
        raise HTTPException(status_code=403, detail="Account not active")

    return SellerToken(
        access_token=create_seller_token(seller.id),
        seller_id=seller.id,
        business_name=seller.business_name,
    )


@router.post("/approve/{seller_id}", tags=["Seller Admin"])
def approve_seller(seller_id: str, db: Session = Depends(get_db)):
    """
    Admin endpoint — approve a seller's KYC and activate their account.
    In production this would be protected by an admin role check.
    """
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    seller.status    = "active"
    seller.is_active = True
    db.commit()
    return {"message": f"Seller '{seller.business_name}' approved and activated."}
