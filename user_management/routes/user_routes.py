# routes/user_routes.py — View and edit user profile, change password, deactivate account
#
# NFR: GDPR Compliance (Articles 17 & 20)
#   POST /users/me/data-export   → Right to portability — export all personal data as JSON
#   DELETE /users/me/gdpr-erasure → Right to erasure — anonymise all PII (soft-GDPR delete)
#
# ENDPOINTS:
#   GET    /users/me                    → get own profile
#   PUT    /users/me                    → update name / phone
#   POST   /users/me/change-password    → change password (requires current password)
#   DELETE /users/me                    → deactivate account (soft delete)
#   GET    /users/me/data-export        → GDPR Art.20: export all personal data
#   DELETE /users/me/gdpr-erasure       → GDPR Art.17: erase all PII

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User, Address, PaymentMethod
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
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(payload.new_password)
    current_user.updated_at    = datetime.utcnow()
    db.commit()
    return {"message": "Password changed successfully"}


@router.delete("/me")
def deactivate_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete — sets is_active=False. Order history is retained for legal/accounting reasons."""
    current_user.is_active  = False
    current_user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Account deactivated successfully"}


# ── GDPR: Right to Data Portability (Article 20) ─────────────────────────────

@router.get("/me/data-export", tags=["GDPR"])
def data_export(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    **GDPR Article 20 — Right to Data Portability**

    Returns all personal data held about the authenticated user in a
    machine-readable JSON format that can be transmitted to another controller.

    Includes: profile, addresses, saved payment method tokens (no full card numbers — PCI-DSS).
    """
    addresses = db.query(Address).filter(Address.user_id == current_user.id).all()
    payment_methods = db.query(PaymentMethod).filter(PaymentMethod.user_id == current_user.id).all()

    return {
        "gdpr_export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "subject": "data_subject_export",
        "profile": {
            "id":         current_user.id,
            "email":      current_user.email,
            "first_name": current_user.first_name,
            "last_name":  current_user.last_name,
            "phone":      current_user.phone,
            "is_active":  current_user.is_active,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        "addresses": [
            {
                "label":     a.label,
                "full_name": a.full_name,
                "phone":     a.phone,
                "line1":     a.line1,
                "line2":     a.line2,
                "city":      a.city,
                "state":     a.state,
                "pincode":   a.pincode,
            }
            for a in addresses
        ],
        "payment_methods": [
            {
                "type":             pm.type,
                "card_last4":       pm.card_last4,
                "card_brand":       pm.card_brand,
                "upi_id":           pm.upi_id,
                "wallet_provider":  pm.wallet_provider,
            }
            for pm in payment_methods
        ],
        "notice": (
            "Full card numbers are never stored (PCI-DSS). "
            "Order history resides in the order_management service and is "
            "available separately as required by consumer protection regulations."
        ),
    }


# ── GDPR: Right to Erasure (Article 17) ──────────────────────────────────────

@router.delete("/me/gdpr-erasure", tags=["GDPR"])
def gdpr_erasure(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    **GDPR Article 17 — Right to Erasure ("Right to be Forgotten")**

    Anonymises all PII associated with this account:
      - Email replaced with an irreversible anonymous token
      - Name replaced with "Deleted User"
      - Phone cleared
      - Addresses deleted
      - Payment method records deleted

    The user row is RETAINED (not hard-deleted) because:
      - Order history must be kept for accounting / legal obligations (lawful basis override)
      - The anonymous user_id is still referenced by order records

    Returns a confirmation token the user can keep as proof of erasure request.
    """
    erasure_token = str(uuid.uuid4())

    # Anonymise PII fields
    current_user.email        = f"deleted_{erasure_token[:8]}@erased.invalid"
    current_user.first_name   = "Deleted"
    current_user.last_name    = "User"
    current_user.phone        = None
    current_user.password_hash = hash_password(str(uuid.uuid4()))  # random unguessable hash
    current_user.is_active    = False
    current_user.updated_at   = datetime.utcnow()

    # Hard-delete addresses and saved payment tokens (no legal basis to retain)
    db.query(Address).filter(Address.user_id == current_user.id).delete()
    db.query(PaymentMethod).filter(PaymentMethod.user_id == current_user.id).delete()

    db.commit()

    return {
        "message":        "Personal data erased in accordance with GDPR Article 17.",
        "erasure_token":  erasure_token,
        "erased_at":      datetime.utcnow().isoformat(),
        "retained_data":  "Anonymised order history retained for legal/accounting obligations (GDPR Art.17(3)(b))",
    }
