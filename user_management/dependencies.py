# dependencies.py — reusable FastAPI dependencies
#
# HOW FastAPI DEPENDENCIES WORK:
#   When a route declares `current_user: User = Depends(get_current_user)`,
#   FastAPI runs get_current_user() before the route handler, and injects
#   its return value. If get_current_user() raises an HTTPException, the
#   route never runs — the error is returned directly.
#
# This pattern means authentication logic is written once here
# and applied to any route just by adding Depends(get_current_user).

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models import User
from auth import decode_token

# HTTPBearer extracts the token from the "Authorization: Bearer <token>" header
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the Bearer token and return the authenticated User.
    Raises 401 if the token is missing, expired, tampered, or the user no longer exists.
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated",
        )

    return user
