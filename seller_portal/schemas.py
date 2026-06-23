"""Pydantic schemas for Seller Portal API."""

import re
from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator, model_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class SellerRegister(BaseModel):
    business_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    gst_number: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Must contain an uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Must contain a digit")
        return v

    @field_validator("business_name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Business name cannot be blank")
        return v.strip()


class SellerLogin(BaseModel):
    email: str
    password: str


class SellerToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    seller_id: str
    business_name: str


# ── Seller profile ────────────────────────────────────────────────────────────

class SellerProfileResponse(BaseModel):
    id: str
    business_name: str
    email: str
    phone: Optional[str]
    gst_number: Optional[str]
    pan_number: Optional[str]
    address: Optional[str]
    status: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SellerProfileUpdate(BaseModel):
    phone: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None


# ── Products ──────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    description: str
    category: str
    subcategory: Optional[str] = None
    brand: str
    sku: str
    mrp: float
    selling_price: float
    inventory_count: int = 0
    primary_image: Optional[str] = None

    @field_validator("mrp", "selling_price")
    @classmethod
    def positive_price(cls, v):
        if v <= 0:
            raise ValueError("Price must be greater than zero")
        return round(v, 2)

    @field_validator("inventory_count")
    @classmethod
    def non_negative_stock(cls, v):
        if v < 0:
            raise ValueError("Inventory count cannot be negative")
        return v

    @model_validator(mode="after")
    def selling_below_mrp(self):
        if self.selling_price > self.mrp:
            raise ValueError("Selling price cannot exceed MRP")
        return self


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    selling_price: Optional[float] = None
    inventory_count: Optional[int] = None
    primary_image: Optional[str] = None

    @field_validator("selling_price")
    @classmethod
    def positive_price(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Price must be greater than zero")
        return v

    @field_validator("inventory_count")
    @classmethod
    def non_negative_stock(cls, v):
        if v is not None and v < 0:
            raise ValueError("Inventory count cannot be negative")
        return v


class ProductResponse(BaseModel):
    id: str
    seller_id: str
    name: str
    description: str
    category: str
    brand: str
    sku: str
    mrp: float
    selling_price: float
    discount_pct: float
    inventory_count: int
    approval_status: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Orders ────────────────────────────────────────────────────────────────────

class SellerOrderResponse(BaseModel):
    id: str
    order_id: str
    product_name: str
    quantity: int
    unit_price: float
    total_price: float
    commission_rate: float
    commission_amt: Optional[float]
    payout_amount: Optional[float]
    fulfillment_status: str
    payout_status: str
    customer_city: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class FulfillmentUpdate(BaseModel):
    status: Literal["processing", "shipped", "delivered", "returned", "cancelled"]


# ── Dashboard analytics ───────────────────────────────────────────────────────

class SellerDashboard(BaseModel):
    seller_id: str
    business_name: str
    total_products: int
    active_products: int
    pending_review: int
    total_orders: int
    pending_orders: int
    total_revenue: float
    pending_payout: float
    last_30_days_revenue: float
