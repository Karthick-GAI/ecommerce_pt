"""
Read-only SQLAlchemy model mirrors for tables owned by other services.
This service never writes to these tables directly.
"""
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class Product(Base):
    __tablename__ = "products"

    id               = Column(String, primary_key=True)
    name             = Column(String)
    description      = Column(Text)
    category         = Column(String)
    subcategory      = Column(String)
    brand            = Column(String)
    price            = Column(Float)
    discount_pct     = Column(Float, default=0.0)
    inventory_count  = Column(Integer, default=0)
    rating_avg       = Column(Float, default=0.0)
    rating_count     = Column(Integer, default=0)
    primary_image    = Column(String)
    tags             = Column(JSONB)
    specifications   = Column(JSONB)
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime(timezone=True))


class CheckoutOrder(Base):
    __tablename__ = "checkout_orders"

    id               = Column(String, primary_key=True)
    customer_id      = Column(String)
    cart_id          = Column(String)
    status           = Column(String)
    subtotal         = Column(Float)
    discount         = Column(Float, default=0.0)
    coupon_code      = Column(String)
    tax              = Column(Float)
    shipping_charge  = Column(Float)
    total            = Column(Float)
    shipping_name    = Column(String)
    shipping_phone   = Column(String)
    shipping_address = Column(String)
    shipping_city    = Column(String)
    shipping_state   = Column(String)
    shipping_pincode = Column(String)
    payment_method   = Column(String)
    payment_status   = Column(String)
    created_at       = Column(DateTime(timezone=True))


class CheckoutOrderItem(Base):
    __tablename__ = "checkout_order_items"

    id           = Column(String, primary_key=True)
    order_id     = Column(String, ForeignKey("checkout_orders.id"))
    product_id   = Column(String)
    product_name = Column(String)
    quantity     = Column(Integer)
    unit_price   = Column(Float)
    total_price  = Column(Float)


class CheckoutPayment(Base):
    __tablename__ = "checkout_payments"

    id             = Column(String, primary_key=True)
    order_id       = Column(String, ForeignKey("checkout_orders.id"))
    method         = Column(String)
    status         = Column(String)
    transaction_id = Column(String)
    paid_at        = Column(DateTime(timezone=True))


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id              = Column(String, primary_key=True)
    order_id        = Column(String)
    status          = Column(String)
    note            = Column(Text)
    tracking_number = Column(String)
    created_at      = Column(DateTime(timezone=True))


class Refund(Base):
    __tablename__ = "refunds"

    id           = Column(String, primary_key=True)
    order_id     = Column(String)
    amount       = Column(Float)
    reason       = Column(Text)
    status       = Column(String)
    approved_by  = Column(String)
    created_at   = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id               = Column(String, primary_key=True)
    product_id       = Column(String)
    movement_type    = Column(String)
    quantity_before  = Column(Integer)
    quantity_after   = Column(Integer)
    quantity_change  = Column(Integer)
    reason           = Column(String)
    performed_by     = Column(String)
    created_at       = Column(DateTime(timezone=True))


class InventoryAlert(Base):
    __tablename__ = "alerts"

    id               = Column(String, primary_key=True)
    product_id       = Column(String)
    alert_type       = Column(String)
    message          = Column(Text)
    severity         = Column(String)
    is_acknowledged  = Column(Boolean, default=False)
    is_resolved      = Column(Boolean, default=False)
    created_at       = Column(DateTime(timezone=True))


class UserPreferenceProfile(Base):
    __tablename__ = "user_preference_profiles"

    id              = Column(String, primary_key=True)
    user_id         = Column(String)
    top_categories  = Column(JSONB)
    top_brands      = Column(JSONB)
    price_min       = Column(Float)
    price_max       = Column(Float)
    updated_at      = Column(DateTime(timezone=True))


class CustomerMemory(Base):
    __tablename__ = "customer_memory"

    id                   = Column(String, primary_key=True)
    customer_id          = Column(String)
    top_categories       = Column(JSONB)
    top_brands           = Column(JSONB)
    lifecycle_stage      = Column(String)
    recent_searches      = Column(JSONB)
    total_purchases      = Column(Integer, default=0)
    avg_order_value      = Column(Float, default=0.0)
    cart_to_purchase_rate = Column(Float, default=0.0)
    last_seen_at         = Column(DateTime(timezone=True))


class Cart(Base):
    __tablename__ = "checkout_carts"

    id          = Column(String, primary_key=True)
    customer_id = Column(String)
    status      = Column(String)
    created_at  = Column(DateTime(timezone=True))
    updated_at  = Column(DateTime(timezone=True))


class CartItem(Base):
    __tablename__ = "checkout_cart_items"

    id             = Column(String, primary_key=True)
    cart_id        = Column(String, ForeignKey("checkout_carts.id"))
    product_id     = Column(String)
    product_name   = Column(String)
    quantity       = Column(Integer)
    unit_price     = Column(Float)
    price_at_add   = Column(Float)


class Shipment(Base):
    __tablename__ = "ship_shipments"

    id                   = Column(String, primary_key=True)
    checkout_order_id    = Column(String)
    provider_shipment_id = Column(String)
    status               = Column(String)
    tracking_number      = Column(String)
    expected_delivery    = Column(DateTime(timezone=True))
    actual_delivery      = Column(DateTime(timezone=True))
    created_at           = Column(DateTime(timezone=True))
