import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database import Base


def new_uuid():
    return str(uuid.uuid4())


# ── Read-only: existing products table ───────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id              = Column(String,  primary_key=True)
    name            = Column(String,  nullable=False)
    description     = Column(Text,    nullable=False)
    category        = Column(String,  nullable=False)
    subcategory     = Column(String,  nullable=True)
    brand           = Column(String,  nullable=False)
    price           = Column(Float,   nullable=False)
    discount_pct    = Column(Float,   default=0.0)
    inventory_count = Column(Integer, default=0)
    rating_avg      = Column(Float,   default=0.0)
    primary_image   = Column(String,  nullable=True)
    tags            = Column(JSONB,   nullable=True)
    specifications  = Column(JSONB,   nullable=True)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)


# ── Cart ──────────────────────────────────────────────────────────────────────
class Cart(Base):
    __tablename__ = "checkout_carts"

    id          = Column(String,   primary_key=True, default=new_uuid)
    customer_id = Column(String,   nullable=True)       # None = guest cart
    status      = Column(String,   default="active")    # active | checked_out | abandoned
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow)

    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "checkout_cart_items"

    id           = Column(String,  primary_key=True, default=new_uuid)
    cart_id      = Column(String,  ForeignKey("checkout_carts.id"), nullable=False, index=True)
    product_id   = Column(String,  nullable=False)
    quantity     = Column(Integer, nullable=False, default=1)
    price_at_add = Column(Float,   nullable=False)  # price snapshot at time of add

    cart = relationship("Cart", back_populates="items")


# ── Order ─────────────────────────────────────────────────────────────────────
class Order(Base):
    __tablename__ = "checkout_orders"

    id              = Column(String,   primary_key=True, default=new_uuid)
    customer_id     = Column(String,   nullable=True)
    cart_id         = Column(String,   nullable=True)
    # pending → confirmed → processing → shipped → delivered | cancelled | payment_failed
    status          = Column(String,   default="pending")
    subtotal        = Column(Float,    nullable=False)
    discount        = Column(Float,    default=0.0)
    coupon_code     = Column(String,   nullable=True)
    tax             = Column(Float,    default=0.0)
    shipping_charge = Column(Float,    default=0.0)
    total           = Column(Float,    nullable=False)
    shipping_name    = Column(String,  nullable=True)
    shipping_phone   = Column(String,  nullable=True)
    shipping_address = Column(Text,    nullable=True)
    shipping_city    = Column(String,  nullable=True)
    shipping_state   = Column(String,  nullable=True)
    shipping_pincode = Column(String,  nullable=True)
    payment_method  = Column(String,   nullable=True)   # card | wallet | upi
    payment_status  = Column(String,   default="pending")
    created_at      = Column(DateTime, default=datetime.utcnow)

    items   = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment = relationship("Payment",   back_populates="order", uselist=False)


class OrderItem(Base):
    __tablename__ = "checkout_order_items"

    id           = Column(String,  primary_key=True, default=new_uuid)
    order_id     = Column(String,  ForeignKey("checkout_orders.id"), nullable=False, index=True)
    product_id   = Column(String,  nullable=False)
    product_name = Column(String,  nullable=False)
    brand        = Column(String,  nullable=False)
    quantity     = Column(Integer, nullable=False)
    unit_price   = Column(Float,   nullable=False)
    total_price  = Column(Float,   nullable=False)

    order = relationship("Order", back_populates="items")


# ── Payment ───────────────────────────────────────────────────────────────────
class Payment(Base):
    __tablename__ = "checkout_payments"

    id             = Column(String,   primary_key=True, default=new_uuid)
    order_id       = Column(String,   ForeignKey("checkout_orders.id"), nullable=False, unique=True)
    method         = Column(String,   nullable=False)    # card | wallet | upi
    status         = Column(String,   default="pending") # pending | success | failed
    amount         = Column(Float,    nullable=False)
    transaction_id = Column(String,   nullable=True)
    gateway_ref    = Column(String,   nullable=True)
    failure_reason = Column(String,   nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="payment")
