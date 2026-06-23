# schemas.py — Pydantic models for request validation and response shaping

import re
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator, model_validator


# ═══════════════════════════════════════════════════
#  AUTH SCHEMAS
# ═══════════════════════════════════════════════════

class UserRegister(BaseModel):
    email: EmailStr          # EmailStr validates format and normalises to lowercase
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Name cannot be blank")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v):
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Enter a valid 10-digit Indian mobile number (starts with 6–9)")
        return v


class UserLogin(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str    # short-lived (30 min) — sent with every API request
    refresh_token: str   # long-lived (7 days)  — only used to get a new access token
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


# ═══════════════════════════════════════════════════
#  USER PROFILE SCHEMAS
# ═══════════════════════════════════════════════════

class UserResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def name_not_empty(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name cannot be blank")
        return v.strip() if v else v

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v):
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return v


class ChangePassword(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


# ═══════════════════════════════════════════════════
#  ADDRESS SCHEMAS
# ═══════════════════════════════════════════════════

class AddressCreate(BaseModel):
    label: str                           # user-chosen nickname: "Home", "Office", etc.
    full_name: str                       # recipient name printed on the package
    phone: str                           # primary delivery contact
    alternate_phone: Optional[str] = None  # backup contact for delivery agent
    line1: str
    line2: Optional[str] = None
    landmark: Optional[str] = None      # e.g., "Near Big Bazaar" — helps delivery agents in India
    city: str
    state: str
    pincode: str

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v):
        if not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return v

    @field_validator("alternate_phone")
    @classmethod
    def alt_phone_format(cls, v):
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return v

    @field_validator("pincode")
    @classmethod
    def pincode_format(cls, v):
        if not re.match(r"^\d{6}$", v):
            raise ValueError("Pincode must be exactly 6 digits")
        return v

    @field_validator("label", "full_name", "line1", "city", "state")
    @classmethod
    def not_empty(cls, v):
        if not v.strip():
            raise ValueError("This field cannot be blank")
        return v.strip()


class AddressUpdate(BaseModel):
    # All optional — only provided fields are updated
    label: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    line1: Optional[str] = None
    line2: Optional[str] = None
    landmark: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v):
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return v

    @field_validator("alternate_phone")
    @classmethod
    def alt_phone_format(cls, v):
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return v

    @field_validator("pincode")
    @classmethod
    def pincode_format(cls, v):
        if v and not re.match(r"^\d{6}$", v):
            raise ValueError("Pincode must be exactly 6 digits")
        return v


class AddressResponse(BaseModel):
    id: str
    label: str
    full_name: str
    phone: str
    alternate_phone: Optional[str]
    line1: str
    line2: Optional[str]
    landmark: Optional[str]
    city: str
    state: str
    pincode: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════
#  PAYMENT METHOD SCHEMAS
# ═══════════════════════════════════════════════════

class PaymentMethodCreate(BaseModel):
    """
    Single schema for all three payment types.
    The `type` discriminator decides which fields are required — validated in @model_validator.
    """
    type: Literal["card", "upi", "wallet"]
    label: Optional[str] = None

    # Card fields
    card_last4:  Optional[str] = None   # last 4 digits only — full number never stored
    card_brand:  Optional[str] = None   # "Visa", "Mastercard", "RuPay", "Amex"
    card_holder: Optional[str] = None
    card_expiry: Optional[str] = None   # "MM/YYYY"

    # UPI fields
    upi_id: Optional[str] = None        # e.g., "karthick@paytm"

    # Wallet fields
    wallet_provider: Optional[str] = None   # "Paytm", "PhonePe", "GPay"
    wallet_phone:    Optional[str] = None

    @model_validator(mode="after")
    def validate_by_type(self):
        if self.type == "card":
            missing = [f for f in ["card_last4", "card_brand", "card_holder", "card_expiry"]
                       if not getattr(self, f)]
            if missing:
                raise ValueError(f"Card payment requires: {', '.join(missing)}")

            if self.card_last4 and not re.match(r"^\d{4}$", self.card_last4):
                raise ValueError("card_last4 must be exactly 4 digits")

            if self.card_expiry:
                if not re.match(r"^(0[1-9]|1[0-2])\/\d{4}$", self.card_expiry):
                    raise ValueError("card_expiry must be in MM/YYYY format")
                # Reject expired cards at registration time
                month, year = int(self.card_expiry[:2]), int(self.card_expiry[3:])
                now = datetime.utcnow()
                if year < now.year or (year == now.year and month < now.month):
                    raise ValueError("This card has already expired")

        elif self.type == "upi":
            if not self.upi_id:
                raise ValueError("UPI payment requires upi_id")
            if not re.match(r"^[a-zA-Z0-9._\-]+@[a-zA-Z]{3,}$", self.upi_id):
                raise ValueError("Enter a valid UPI ID (e.g., name@paytm)")

        elif self.type == "wallet":
            if not self.wallet_provider or not self.wallet_phone:
                raise ValueError("Wallet payment requires wallet_provider and wallet_phone")
            if not re.match(r"^[6-9]\d{9}$", self.wallet_phone):
                raise ValueError("Enter a valid 10-digit Indian mobile number")

        return self


class PaymentMethodResponse(BaseModel):
    id: str
    type: str
    label: Optional[str]
    is_default: bool
    card_last4:      Optional[str]
    card_brand:      Optional[str]
    card_holder:     Optional[str]
    card_expiry:     Optional[str]
    upi_id:          Optional[str]
    wallet_provider: Optional[str]
    wallet_phone:    Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
