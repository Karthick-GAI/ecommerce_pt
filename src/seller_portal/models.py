"""
Seller Portal ORM models.

Tables:
  sellers           — Merchant accounts (B2B)
  seller_products   — Product catalogue owned by a seller
  seller_orders     — Read-side view of orders containing this seller's products
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Float, Integer,
    Text, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from database import Base


def new_uuid():
    return str(uuid.uuid4())


# ── Seller (merchant account) ─────────────────────────────────────────────────

class Seller(Base):
    __tablename__ = "sellers"

    id            = Column(String,  primary_key=True, default=new_uuid)
    business_name = Column(String,  nullable=False, unique=True)
    email         = Column(String,  nullable=False, unique=True, index=True)
    password_hash = Column(String,  nullable=False)
    gst_number    = Column(String,  nullable=True)   # GST registration for compliance
    pan_number    = Column(String,  nullable=True)   # PAN for tax reporting
    phone         = Column(String,  nullable=True)
    address       = Column(Text,    nullable=True)
    bank_account  = Column(String,  nullable=True)   # masked: last 4 digits for display
    ifsc_code     = Column(String,  nullable=True)
    status        = Column(
        Enum("pending_verification", "active", "suspended", "deactivated", name="seller_status"),
        default="pending_verification",
    )
    is_active     = Column(Boolean, default=False)   # True only after KYC approval
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow)

    products = relationship("SellerProduct", back_populates="seller", cascade="all, delete-orphan")
    orders   = relationship("SellerOrder",   back_populates="seller")


# ── Seller Products (catalogue management) ───────────────────────────────────

class SellerProduct(Base):
    __tablename__ = "seller_products"

    id              = Column(String,  primary_key=True, default=new_uuid)
    seller_id       = Column(String,  ForeignKey("sellers.id"), nullable=False, index=True)
    name            = Column(String,  nullable=False)
    description     = Column(Text,    nullable=False)
    category        = Column(String,  nullable=False)
    subcategory     = Column(String,  nullable=True)
    brand           = Column(String,  nullable=False)
    sku             = Column(String,  nullable=False, unique=True)   # Stock Keeping Unit
    mrp             = Column(Float,   nullable=False)   # Maximum Retail Price
    selling_price   = Column(Float,   nullable=False)
    discount_pct    = Column(Float,   default=0.0)
    inventory_count = Column(Integer, default=0)
    primary_image   = Column(String,  nullable=True)
    # Approval workflow: seller submits → admin reviews → approved / rejected
    approval_status = Column(
        Enum("draft", "pending_review", "approved", "rejected", name="product_approval"),
        default="draft",
    )
    rejection_reason = Column(Text, nullable=True)
    is_active       = Column(Boolean, default=False)   # True only when approved
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow)

    seller = relationship("Seller", back_populates="products")


# ── Seller Orders (order line items belonging to this seller) ─────────────────

class SellerOrder(Base):
    """
    Lightweight projection of order data relevant to a seller.
    In a full system this would be populated by an event from order_management.
    For this capstone demo it is populated via the seller dashboard endpoint.
    """
    __tablename__ = "seller_orders"

    id              = Column(String,   primary_key=True, default=new_uuid)
    seller_id       = Column(String,   ForeignKey("sellers.id"), nullable=False, index=True)
    order_id        = Column(String,   nullable=False)   # references checkout_orders.id
    product_id      = Column(String,   nullable=False)   # references seller_products.id
    product_name    = Column(String,   nullable=False)
    quantity        = Column(Integer,  nullable=False)
    unit_price      = Column(Float,    nullable=False)
    total_price     = Column(Float,    nullable=False)
    commission_rate = Column(Float,    default=10.0)    # % platform commission
    commission_amt  = Column(Float,    nullable=True)
    payout_amount   = Column(Float,    nullable=True)
    fulfillment_status = Column(
        Enum("pending", "processing", "shipped", "delivered", "returned", "cancelled",
             name="fulfillment_status"),
        default="pending",
    )
    payout_status   = Column(
        Enum("pending", "processing", "paid", "on_hold", name="payout_status"),
        default="pending",
    )
    customer_city   = Column(String,   nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow)

    seller = relationship("Seller", back_populates="orders")
