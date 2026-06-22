import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text
from database import Base


def new_uuid():
    return str(uuid.uuid4())


# ── Read-only: customers ──────────────────────────────────────────────────────
class Customer(Base):
    __tablename__ = "customers"

    user_id    = Column(String, primary_key=True)
    first_name = Column(String, nullable=True)
    last_name  = Column(String, nullable=True)
    email      = Column(String, nullable=True)
    phone      = Column(String, nullable=True)
    city       = Column(String, nullable=True)
    state      = Column(String, nullable=True)


# ── Read-only: checkout_orders ────────────────────────────────────────────────
class CheckoutOrder(Base):
    __tablename__ = "checkout_orders"

    id               = Column(String,   primary_key=True)
    customer_id      = Column(String,   nullable=True)
    cart_id          = Column(String,   nullable=True)
    status           = Column(String,   nullable=False)
    subtotal         = Column(Float,    nullable=False)
    discount         = Column(Float,    default=0.0)
    coupon_code      = Column(String,   nullable=True)
    tax              = Column(Float,    default=0.0)
    shipping_charge  = Column(Float,    default=0.0)
    total            = Column(Float,    nullable=False)
    shipping_name    = Column(String,   nullable=True)
    shipping_phone   = Column(String,   nullable=True)
    shipping_address = Column(Text,     nullable=True)
    shipping_city    = Column(String,   nullable=True)
    shipping_state   = Column(String,   nullable=True)
    shipping_pincode = Column(String,   nullable=True)
    payment_method   = Column(String,   nullable=True)
    payment_status   = Column(String,   default="pending")
    created_at       = Column(DateTime, default=datetime.utcnow)


class CheckoutOrderItem(Base):
    __tablename__ = "checkout_order_items"

    id           = Column(String,  primary_key=True)
    order_id     = Column(String,  nullable=False, index=True)
    product_id   = Column(String,  nullable=False)
    product_name = Column(String,  nullable=False)
    brand        = Column(String,  nullable=False)
    quantity     = Column(Integer, nullable=False)
    unit_price   = Column(Float,   nullable=False)
    total_price  = Column(Float,   nullable=False)


class CheckoutPayment(Base):
    __tablename__ = "checkout_payments"

    id             = Column(String,   primary_key=True)
    order_id       = Column(String,   nullable=False, unique=True)
    method         = Column(String,   nullable=False)
    status         = Column(String,   nullable=False)
    amount         = Column(Float,    nullable=False)
    transaction_id = Column(String,   nullable=True)
    gateway_ref    = Column(String,   nullable=True)
    failure_reason = Column(String,   nullable=True)
    created_at     = Column(DateTime, nullable=True)


class Product(Base):
    __tablename__ = "products"

    id              = Column(String,  primary_key=True)
    name            = Column(String,  nullable=False)
    inventory_count = Column(Integer, default=0)
    is_active       = Column(Boolean, default=True)


# ── New tables ────────────────────────────────────────────────────────────────
class OrderStatusHistory(Base):
    __tablename__ = "orders_status_history"

    id                 = Column(String,   primary_key=True, default=new_uuid)
    order_id           = Column(String,   nullable=False, index=True)
    from_status        = Column(String,   nullable=True)
    to_status          = Column(String,   nullable=False)
    changed_by         = Column(String,   default="system")   # customer | admin | system
    reason             = Column(String,   nullable=True)
    tracking_number    = Column(String,   nullable=True)       # generated when shipped
    estimated_delivery = Column(String,   nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow)


class Refund(Base):
    __tablename__ = "orders_refunds"

    id                      = Column(String,   primary_key=True, default=new_uuid)
    order_id                = Column(String,   nullable=False, index=True)
    amount                  = Column(Float,    nullable=False)
    reason                  = Column(String,   nullable=True)
    # pending | approved | processing | completed | rejected
    status                  = Column(String,   default="pending")
    original_payment_method = Column(String,   nullable=True)
    refund_txn_id           = Column(String,   nullable=True)
    rejection_reason        = Column(String,   nullable=True)
    processed_at            = Column(DateTime, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "orders_notifications"

    id          = Column(String,   primary_key=True, default=new_uuid)
    customer_id = Column(String,   nullable=False, index=True)
    order_id    = Column(String,   nullable=True,  index=True)
    channel     = Column(String,   nullable=False)   # email | sms | push
    event       = Column(String,   nullable=False)
    title       = Column(String,   nullable=False)
    message     = Column(String,   nullable=False)
    is_read     = Column(Boolean,  default=False)
    sent_at     = Column(DateTime, default=datetime.utcnow)
