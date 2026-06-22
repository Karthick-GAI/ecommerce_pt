# routes/user_routes.py — View and edit user profile, change password, deactivate account
#
# ENDPOINTS:
#   GET    /users/me                → get own profile
#   PUT    /users/me                → update name / phone
#   POST   /users/me/change-password → change password (requires current password)
#   DELETE /users/me                → deactivate account (soft delete)
#
# All routes require a valid Bearer token (enforced by get_current_user dependency).

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import UserResponse, UserUpdate, ChangePassword
from auth import hash_password, verify_password
from dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["User Profile"])


@router.get("/me", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile data."""
    return current_user


@router.put("/me", response_model=UserResponse)
def update_profile(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update profile fields.
    Only the fields provided in the request body are updated (partial update).
    model_dump(exclude_none=True) drops fields the client didn't send.
    """
    updates = payload.model_dump(exclude_none=True)

    for field, value in updates.items():
        setattr(current_user, field, value)

    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/change-password")
def change_password(
    payload: ChangePassword,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change password.
    Requires the current password to prevent account takeover if
    a session token is stolen but the attacker doesn't know the password.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Password changed successfully"}


@router.delete("/me")
def deactivate_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft-delete the account by setting is_active=False.
    We don't hard-delete because order history and transaction records must be retained
    for accounting/legal reasons even after an account is closed.
    """
    current_user.is_active = False
    current_user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Account deactivated successfully"}
