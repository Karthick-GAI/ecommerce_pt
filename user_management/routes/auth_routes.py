# routes/auth_routes.py — Registration, Login, Token Refresh
#
# NFR: Rate limiting (slowapi)
#   /auth/login    → 5 attempts / minute per IP  (account takeover prevention)
#   /auth/register → 3 attempts / minute per IP  (prevents mass account creation)
#   /auth/refresh  → 20 / minute                 (normal token rotation)
#
# ENDPOINTS:
#   POST /auth/register  → create a new account
#   POST /auth/login     → validate credentials, return JWT tokens
#   POST /auth/refresh   → swap a refresh token for new access + refresh tokens

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from database import get_db
from models import User
from schemas import UserRegister, UserLogin, Token, TokenRefresh
from auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Limiter instance — same key_func as app.state.limiter
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def register(request: Request, payload: UserRegister, db: Session = Depends(get_db)):
    """
    Create a new user account.
    Rate-limited to 3 registrations/minute per IP to block scripted mass sign-ups.
    """
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "Account created successfully", "user_id": user.id}


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    """
    Validate credentials and return JWT tokens.
    Rate-limited to 5 attempts/minute per IP — prevents credential-stuffing attacks.

    SECURITY: Same error for wrong email and wrong password (prevents email enumeration).
    """
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=Token)
@limiter.limit("20/minute")
def refresh(request: Request, payload: TokenRefresh, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new pair of tokens.
    Rate-limited to 20/minute to allow normal client token rotation.
    """
    decoded = decode_token(payload.refresh_token)

    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.query(User).filter(User.id == decoded["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
