# routes/auth_routes.py — Registration, Login, Token Refresh
#
# ENDPOINTS:
#   POST /auth/register  → create a new account
#   POST /auth/login     → validate credentials, return JWT tokens
#   POST /auth/refresh   → swap a refresh token for new access + refresh tokens

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import UserRegister, UserLogin, Token, TokenRefresh
from auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """
    Create a new user account.
    Steps:
      1. Check if email is already taken
      2. Hash the password (never store plain text)
      3. Save the user to the database
    """
    # Reject duplicate emails before trying to insert — gives a clear error message
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),  # hash here, never store raw
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # refresh loads the generated id back into the object

    return {"message": "Account created successfully", "user_id": user.id}


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """
    Validate credentials and return JWT tokens.

    SECURITY NOTE: We return the same error message whether the email doesn't exist
    or the password is wrong. This prevents "email enumeration" — an attacker probing
    which emails are registered by seeing different error messages.
    """
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",  # intentionally vague — see note above
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
def refresh(payload: TokenRefresh, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new pair of tokens.
    Used when the access token expires (after 30 minutes) — the user stays logged in
    without having to re-enter their password.
    """
    decoded = decode_token(payload.refresh_token)

    # Reject access tokens used as refresh tokens (type check prevents token misuse)
    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.query(User).filter(User.id == decoded["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Issue brand new tokens — this also implicitly rotates the refresh token
    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
