# routes/payment_routes.py — Saved payment methods (card / UPI / wallet)

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import PaymentMethod, User
from schemas import PaymentMethodCreate, PaymentMethodResponse
from dependencies import get_current_user

router = APIRouter(prefix="/users/me/payment-methods", tags=["Payment Methods"])


@router.get("/", response_model=List[PaymentMethodResponse])
def list_payment_methods(current_user: User = Depends(get_current_user)):
    return current_user.payment_methods


@router.post("/", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
def add_payment_method(
    payload: PaymentMethodCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_first = len(current_user.payment_methods) == 0
    method = PaymentMethod(user_id=current_user.id, is_default=is_first)

    for field, value in payload.model_dump().items():
        if hasattr(method, field) and value is not None:
            setattr(method, field, value)

    db.add(method)
    db.commit()
    db.refresh(method)
    return method


@router.delete("/{method_id}")
def delete_payment_method(
    method_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    method = db.query(PaymentMethod).filter(
        PaymentMethod.id == method_id,
        PaymentMethod.user_id == current_user.id,
    ).first()
    if not method:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found")

    was_default = method.is_default
    db.delete(method)
    db.flush()  # apply delete before querying for the next method

    # Promote the next available method to default so checkout always has a selection
    if was_default:
        next_method = db.query(PaymentMethod).filter(
            PaymentMethod.user_id == current_user.id
        ).first()
        if next_method:
            next_method.is_default = True

    db.commit()
    return {"message": "Payment method removed"}


@router.put("/{method_id}/default", response_model=PaymentMethodResponse)
def set_default_payment(
    method_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    method = db.query(PaymentMethod).filter(
        PaymentMethod.id == method_id,
        PaymentMethod.user_id == current_user.id,
    ).first()
    if not method:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found")

    db.query(PaymentMethod).filter(
        PaymentMethod.user_id == current_user.id,
        PaymentMethod.is_default == True,
    ).update({"is_default": False})

    method.is_default = True
    db.commit()
    db.refresh(method)
    return method
