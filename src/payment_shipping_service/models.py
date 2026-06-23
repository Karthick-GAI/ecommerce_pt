"""
Database models for the Payment & Shipping Integration Service.

Read-only (shared tables owned by other services):
  customers, checkout_orders, checkout_order_items

Owned by this service (pay_ / ship_ prefix):
  pay_orders, pay_transactions, pay_refunds,
  pay_webhook_events,
  ship_shipments, ship_tracking_events, ship_rate_cache
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func
from database import Base
import uuid


def _gen_id():
    return str(uuid.uuid4())


# ── Read-only: shared tables ──────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"
    user_id    = Column(String, primary_key=True)
    email      = Column(String)
    first_name = Column(String)
    last_name  = Column(String)
    phone      = Column(String)
    city       = Column(String)
    state      = Column(String)
    created_at = Column(DateTime)


class CheckoutOrder(Base):
    __tablename__ = "checkout_orders"
    id               = Column(String, primary_key=True)
    customer_id      = Column(String, index=True)
    status           = Column(String)
    total            = Column(Float)
    subtotal         = Column(Float)
    tax              = Column(Float)
    shipping_charge  = Column(Float)
    payment_method   = Column(String)
    payment_status   = Column(String)
    # Shipping address fields (already on checkout_orders)
    shipping_name    = Column(String)
    shipping_phone   = Column(String)
    shipping_address = Column(String)
    shipping_city    = Column(String)
    shipping_state   = Column(String)
    shipping_pincode = Column(String)
    created_at       = Column(DateTime)


class CheckoutOrderItem(Base):
    """Note: checkout_order_items has no 'category' column."""
    __tablename__ = "checkout_order_items"
    id           = Column(String, primary_key=True)
    order_id     = Column(String, index=True)
    product_id   = Column(String)
    product_name = Column(String)
    brand        = Column(String)
    quantity     = Column(Integer)
    unit_price   = Column(Float)
    total_price  = Column(Float)


# ── pay_orders ────────────────────────────────────────────────────────────────

class PaymentOrder(Base):
    """
    One PaymentOrder per checkout attempt.
    Links a checkout_order to a Razorpay order.
    A checkout order may have multiple PaymentOrders (retries after failure).
    """
    __tablename__ = "pay_orders"
    id                 = Column(String, primary_key=True, default=_gen_id)
    checkout_order_id  = Column(String, nullable=False, index=True)
    customer_id        = Column(String, nullable=True,  index=True)

    provider           = Column(String, default="razorpay")  # razorpay | stripe | payu
    provider_order_id  = Column(String, nullable=True, index=True)  # e.g. order_xxx from Razorpay

    amount             = Column(Float, nullable=False)   # INR
    currency           = Column(String, default="INR")
    receipt            = Column(String)                  # unique receipt for Razorpay
    provider_key_id    = Column(String)                  # public key sent to frontend

    # created | attempted | paid | failed | expired | refunded
    status             = Column(String, default="created")
    attempts           = Column(Integer, default=0)

    provider_raw       = Column(JSON)      # raw provider response on creation

    created_at         = Column(DateTime, server_default=func.now())
    updated_at         = Column(DateTime, server_default=func.now(), onupdate=func.now())
    expires_at         = Column(DateTime, nullable=True)
    paid_at            = Column(DateTime, nullable=True)


# ── pay_transactions ──────────────────────────────────────────────────────────

class PaymentTransaction(Base):
    """
    One row per individual payment attempt (user swipe / UPI confirm).
    A PaymentOrder may have multiple PaymentTransactions (e.g., user switches method).
    """
    __tablename__ = "pay_transactions"
    id                    = Column(String, primary_key=True, default=_gen_id)
    pay_order_id          = Column(String, nullable=False, index=True)
    checkout_order_id     = Column(String, nullable=False, index=True)
    customer_id           = Column(String, nullable=True)

    provider_payment_id   = Column(String, nullable=True, index=True)  # pay_xxx from Razorpay
    razorpay_signature    = Column(String, nullable=True)

    # card | upi | netbanking | wallet | emi | cod
    method                = Column(String, nullable=True)
    card_last4            = Column(String, nullable=True)
    card_network          = Column(String, nullable=True)   # Visa | Mastercard | Rupay
    upi_vpa               = Column(String, nullable=True)   # masked, e.g. ab****@okicici

    amount                = Column(Float)
    currency              = Column(String, default="INR")

    # created | authorized | captured | failed | refunded
    status                = Column(String, default="created")
    error_code            = Column(String, nullable=True)
    error_description     = Column(String, nullable=True)

    provider_raw          = Column(JSON, nullable=True)

    created_at            = Column(DateTime, server_default=func.now())
    updated_at            = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ── pay_refunds ───────────────────────────────────────────────────────────────

class PaymentRefund(Base):
    __tablename__ = "pay_refunds"
    id                  = Column(String, primary_key=True, default=_gen_id)
    transaction_id      = Column(String, nullable=False, index=True)
    pay_order_id        = Column(String, nullable=False, index=True)
    checkout_order_id   = Column(String, nullable=False, index=True)
    customer_id         = Column(String, nullable=True)

    provider_refund_id  = Column(String, nullable=True, index=True)  # rfnd_xxx from Razorpay
    amount              = Column(Float, nullable=False)   # INR
    reason              = Column(String, nullable=True)
    notes               = Column(String, nullable=True)

    # initiated | pending | processed | failed
    status              = Column(String, default="initiated")
    provider_raw        = Column(JSON, nullable=True)

    initiated_at        = Column(DateTime, server_default=func.now())
    processed_at        = Column(DateTime, nullable=True)


# ── pay_webhook_events ────────────────────────────────────────────────────────

class WebhookEvent(Base):
    """Stores every incoming webhook for audit / replay / debugging."""
    __tablename__ = "pay_webhook_events"
    id           = Column(String, primary_key=True, default=_gen_id)
    provider     = Column(String, nullable=False)       # razorpay | shiprocket
    event_type   = Column(String, nullable=True)        # payment.captured etc.
    entity_id    = Column(String, nullable=True, index=True)  # order_id / shipment_id
    payload      = Column(JSON, nullable=True)
    # received | processed | duplicate | error
    status       = Column(String, default="received")
    error_detail = Column(String, nullable=True)
    received_at  = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)


# ── ship_shipments ────────────────────────────────────────────────────────────

class Shipment(Base):
    __tablename__ = "ship_shipments"
    id                  = Column(String, primary_key=True, default=_gen_id)
    checkout_order_id   = Column(String, nullable=False, index=True)
    customer_id         = Column(String, nullable=True,  index=True)

    provider            = Column(String, default="shiprocket")  # shiprocket | delhivery | fedex
    provider_shipment_id = Column(String, nullable=True, index=True)
    awb_number          = Column(String, nullable=True, index=True)  # Air Waybill tracking number
    courier_name        = Column(String, nullable=True)
    label_url           = Column(String, nullable=True)   # PDF shipping label

    # Origin
    origin_pincode      = Column(String, nullable=False)
    origin_city         = Column(String, nullable=True)

    # Destination
    destination_pincode = Column(String, nullable=False)
    destination_city    = Column(String, nullable=True)
    destination_address = Column(String, nullable=True)
    destination_name    = Column(String, nullable=True)
    destination_phone   = Column(String, nullable=True)

    # Package
    weight_kg           = Column(Float, default=0.5)
    length_cm           = Column(Float, nullable=True)
    breadth_cm          = Column(Float, nullable=True)
    height_cm           = Column(Float, nullable=True)

    service_type        = Column(String, default="standard")   # standard | express | overnight
    rate_amount         = Column(Float, nullable=True)
    estimated_days      = Column(Integer, nullable=True)

    # created | manifested | picked_up | in_transit |
    # out_for_delivery | delivered | failed | cancelled | returned
    status              = Column(String, default="created")
    cod                 = Column(Boolean, default=False)
    cod_amount          = Column(Float, nullable=True)

    provider_raw        = Column(JSON, nullable=True)

    created_at          = Column(DateTime, server_default=func.now())
    updated_at          = Column(DateTime, server_default=func.now(), onupdate=func.now())
    estimated_delivery  = Column(DateTime, nullable=True)
    actual_delivery     = Column(DateTime, nullable=True)


# ── ship_tracking_events ──────────────────────────────────────────────────────

class TrackingEvent(Base):
    __tablename__ = "ship_tracking_events"
    id          = Column(String, primary_key=True, default=_gen_id)
    shipment_id = Column(String, nullable=False, index=True)
    awb_number  = Column(String, nullable=True)
    status      = Column(String, nullable=False)
    description = Column(String, nullable=True)
    location    = Column(String, nullable=True)
    timestamp   = Column(DateTime, nullable=True)
    raw_status  = Column(String, nullable=True)  # provider's original status string
    created_at  = Column(DateTime, server_default=func.now())


# ── ship_rate_cache ───────────────────────────────────────────────────────────

class ShippingRateCache(Base):
    """Cache shipping rates for 6 hours to avoid hammering provider APIs."""
    __tablename__ = "ship_rate_cache"
    id                  = Column(String, primary_key=True, default=_gen_id)
    origin_pincode      = Column(String, nullable=False)
    destination_pincode = Column(String, nullable=False)
    weight_kg           = Column(Float, nullable=False)
    cod                 = Column(Boolean, default=False)
    rates               = Column(JSON, nullable=False)   # list of rate objects
    valid_until         = Column(DateTime, nullable=False)
    created_at          = Column(DateTime, server_default=func.now())
