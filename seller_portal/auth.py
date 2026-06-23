"""Seller JWT authentication — mirrors user_management/auth.py but for seller accounts."""

import os
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY  = os.getenv("SELLER_JWT_SECRET", "seller-poc-secret-change-in-production-32ch!")
ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = 8   # Seller sessions are longer-lived than consumer sessions

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_seller_token(seller_id: str) -> str:
    payload = {
        "sub":  seller_id,
        "type": "seller_access",
        "exp":  datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_seller_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
