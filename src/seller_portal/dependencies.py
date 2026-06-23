"""FastAPI dependency: get_current_seller — extracts and verifies seller JWT."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models import Seller
from auth import decode_seller_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/seller/auth/login")


def get_current_seller(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Seller:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired seller token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_seller_token(token)
    if not payload or payload.get("type") != "seller_access":
        raise credentials_exc

    seller = db.query(Seller).filter(Seller.id == payload["sub"]).first()
    if not seller:
        raise credentials_exc
    if not seller.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seller account is not active. Please complete KYC verification.",
        )
    return seller
