# auth.py — password hashing and JWT token utilities
#
# TWO CONCEPTS HERE:
#
# 1. PASSWORD HASHING (bcrypt)
#    - Never store plain passwords. Store a bcrypt hash.
#    - bcrypt is intentionally slow (~100ms per check) to make brute-force impractical.
#    - Each hash includes a random "salt" so two users with the same password get different hashes.
#
# 2. JWT TOKENS
#    - After login, we give the user two tokens:
#        access_token  → short-lived (30 min), sent with every API request in the Authorization header
#        refresh_token → long-lived (7 days), only used to get a new access token when it expires
#    - This way, if an access token is stolen, the attacker has 30 min max.
#    - The token is signed with SECRET_KEY — if tampered, signature verification fails.

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

# IMPORTANT: In production, set this as an environment variable — never hardcode in source control.
# Example: export JWT_SECRET="your-very-long-random-string-here"
SECRET_KEY = os.getenv("JWT_SECRET", "poc-dev-secret-change-this-in-production-min-32-chars!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# CryptContext wraps bcrypt — handles hashing and verification
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Convert a plain-text password into a bcrypt hash for safe storage."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if a plain-text password matches the stored hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    """
    Create a short-lived JWT access token.
    The payload contains:
      sub  → the user's ID (subject of the token)
      type → "access" so we can distinguish it from a refresh token
      exp  → expiry timestamp
    """
    payload = {
        "sub": user_id,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived JWT refresh token."""
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.
    Returns the payload dict if valid, or None if expired / tampered / malformed.
    Callers must then check payload["type"] to ensure they got the right kind of token.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
