from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base
import uuid


def _gen_id():
    return str(uuid.uuid4())


# ── Read-only: shared dataset tables ─────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"
    id              = Column(String, primary_key=True)
    name            = Column(String)
    category        = Column(String)
    subcategory     = Column(String)
    brand           = Column(String)
    price           = Column(Float)
    discount_pct    = Column(Float)
    inventory_count = Column(Integer)
    rating_avg      = Column(Float)
    rating_count    = Column(Integer)
    description     = Column(Text)
    tags            = Column(JSONB)
    is_active       = Column(Boolean)
    created_at      = Column(DateTime)


class Customer(Base):
    __tablename__ = "customers"
    user_id    = Column(String, primary_key=True)
    email      = Column(String)
    first_name = Column(String)
    last_name  = Column(String)
    phone      = Column(String)
    city       = Column(String)
    state      = Column(String)
    segment    = Column(String)
    created_at = Column(DateTime)


class DatasetOrder(Base):
    __tablename__ = "orders"
    order_id      = Column(String, primary_key=True)
    user_id       = Column(String, index=True)
    order_status  = Column(String)
    payment_status = Column(String)
    shipment_status = Column(String)
    total_amount  = Column(Float)
    cart_activity = Column(JSONB)
    created_at    = Column(DateTime)


# ── Read-only: checkout service tables ───────────────────────────────────────

class CheckoutOrder(Base):
    __tablename__ = "checkout_orders"
    id             = Column(String, primary_key=True)
    customer_id    = Column(String, index=True)
    status         = Column(String)
    subtotal       = Column(Float)
    discount       = Column(Float)
    tax            = Column(Float)
    shipping_charge = Column(Float)
    total          = Column(Float)
    payment_method = Column(String)
    payment_status = Column(String)
    shipping_city  = Column(String)
    shipping_state = Column(String)
    created_at     = Column(DateTime)


class CheckoutOrderItem(Base):
    __tablename__ = "checkout_order_items"
    id           = Column(String, primary_key=True)
    order_id     = Column(String, index=True)
    product_id   = Column(String)
    product_name = Column(String)
    brand        = Column(String)
    quantity     = Column(Integer)
    unit_price   = Column(Float)
    total_price  = Column(Float)


class CheckoutPayment(Base):
    __tablename__ = "checkout_payments"
    id             = Column(String, primary_key=True)
    order_id       = Column(String, index=True)
    method         = Column(String)
    status         = Column(String)
    amount         = Column(Float)
    transaction_id = Column(String)
    gateway_ref    = Column(String)
    failure_reason = Column(String)
    created_at     = Column(DateTime)


# ── Read-only: order management tables ───────────────────────────────────────

class OrderStatusHistory(Base):
    __tablename__ = "orders_status_history"
    id                = Column(String, primary_key=True)
    order_id          = Column(String, index=True)
    from_status       = Column(String)
    to_status         = Column(String)
    changed_by        = Column(String)
    reason            = Column(String)
    tracking_number   = Column(String)
    estimated_delivery = Column(String)
    created_at        = Column(DateTime)


class OrderRefund(Base):
    __tablename__ = "orders_refunds"
    id                     = Column(String, primary_key=True)
    order_id               = Column(String, index=True)
    amount                 = Column(Float)
    reason                 = Column(String)
    status                 = Column(String)
    original_payment_method = Column(String)
    refund_txn_id          = Column(String)
    processed_at           = Column(DateTime)
    created_at             = Column(DateTime)


# ── Read-only: inventory tables ───────────────────────────────────────────────

class InventoryAlert(Base):
    __tablename__ = "inventory_alerts"
    id            = Column(String, primary_key=True)
    product_id    = Column(String, index=True)
    product_name  = Column(String)
    category      = Column(String)
    current_stock = Column(Integer)
    threshold     = Column(Integer)
    severity      = Column(String)
    status        = Column(String)
    created_at    = Column(DateTime)


# ── New: agent service tables ─────────────────────────────────────────────────

class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id          = Column(String, primary_key=True, default=_gen_id)
    customer_id = Column(String, nullable=True, index=True)
    title       = Column(String)
    created_at  = Column(DateTime, server_default=func.now())
    updated_at  = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id           = Column(String, primary_key=True, default=_gen_id)
    session_id   = Column(String, nullable=False, index=True)
    role         = Column(String, nullable=False)   # user | assistant | tool
    content      = Column(Text)
    tool_calls   = Column(JSON)    # list[dict] — populated when role=assistant + tool calls
    tool_call_id = Column(String)  # populated when role=tool
    tool_name    = Column(String)  # populated when role=tool
    created_at   = Column(DateTime, server_default=func.now())
