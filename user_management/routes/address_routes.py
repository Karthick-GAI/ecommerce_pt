# routes/address_routes.py — Address book management

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import Address, User
from schemas import AddressCreate, AddressUpdate, AddressResponse
from dependencies import get_current_user

router = APIRouter(prefix="/users/me/addresses", tags=["Address Book"])


@router.get("/", response_model=List[AddressResponse])
def list_addresses(current_user: User = Depends(get_current_user)):
    return current_user.addresses


@router.post("/", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def add_address(
    payload: AddressCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # First address added becomes default automatically so checkout always has a selection
    is_first = len(current_user.addresses) == 0
    address = Address(user_id=current_user.id, is_default=is_first, **payload.model_dump())
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.put("/{address_id}", response_model=AddressResponse)
def update_address(
    address_id: str,
    payload: AddressUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == current_user.id,   # ownership check
    ).first()
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(address, field, value)

    db.commit()
    db.refresh(address)
    return address


@router.delete("/{address_id}")
def delete_address(
    address_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == current_user.id,
    ).first()
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    was_default = address.is_default
    db.delete(address)
    db.flush()  # apply delete before the next query so the deleted row doesn't appear

    # Promote the next available address to default so the user is never left with none
    if was_default:
        next_addr = db.query(Address).filter(Address.user_id == current_user.id).first()
        if next_addr:
            next_addr.is_default = True

    db.commit()
    return {"message": "Address removed"}


@router.put("/{address_id}/default", response_model=AddressResponse)
def set_default_address(
    address_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    address = db.query(Address).filter(
        Address.id == address_id,
        Address.user_id == current_user.id,
    ).first()
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    # Clear existing default first — only one can be default at a time
    db.query(Address).filter(
        Address.user_id == current_user.id,
        Address.is_default == True,
    ).update({"is_default": False})

    address.is_default = True
    db.commit()
    db.refresh(address)
    return address
