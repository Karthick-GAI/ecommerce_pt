"""
Database models for the Guardrails & Anomaly Detection Service.

Read-only (shared tables):
  products, customers, search_logs, browsing_events,
  checkout_orders, orders (dataset)

Owned by this service (guard_ prefix):
  guard_rules, guard_validation_logs, guard_anomaly_alerts
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base
import uuid


def _gen_id():
    return str(uuid.uuid4())


# ── Read-only: shared tables ──────────────────────────────────────────────────

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
    is_active       = Column(Boolean)
    created_at      = Column(DateTime)


class Customer(Base):
    __tablename__ = "customers"
    user_id    = Column(String, primary_key=True)
    email      = Column(String)
    first_name = Column(String)
    last_name  = Column(String)
    phone      = Column(String)
    created_at = Column(DateTime)


class SearchLog(Base):
    __tablename__ = "search_logs"
    id                 = Column(String, primary_key=True)
    user_id            = Column(String, index=True)
    query              = Column(String)
    results_count      = Column(Integer)
    clicked_product_id = Column(String)
    search_type        = Column(String)
    created_at         = Column(DateTime)


class BrowsingEvent(Base):
    __tablename__ = "browsing_events"
    id         = Column(String, primary_key=True)
    user_id    = Column(String, index=True)
    product_id = Column(String)
    event_type = Column(String)
    session_id = Column(String)
    created_at = Column(DateTime)


class CheckoutOrder(Base):
    __tablename__ = "checkout_orders"
    id               = Column(String, primary_key=True)
    customer_id      = Column(String, index=True)
    status           = Column(String)
    total            = Column(Float)
    subtotal         = Column(Float)
    discount         = Column(Float)
    tax              = Column(Float)
    shipping_charge  = Column(Float)
    payment_method   = Column(String)
    payment_status   = Column(String)
    shipping_pincode = Column(String)
    created_at       = Column(DateTime)


class DatasetOrder(Base):
    __tablename__ = "orders"
    order_id      = Column(String, primary_key=True)
    user_id       = Column(String, index=True)
    order_status  = Column(String)
    total_amount  = Column(Float)
    cart_activity = Column(JSONB)
    created_at    = Column(DateTime)


# Shared payment tables (read to detect anomalies)
class PayOrder(Base):
    __tablename__ = "pay_orders"
    id                = Column(String, primary_key=True)
    checkout_order_id = Column(String)
    customer_id       = Column(String, index=True)
    amount            = Column(Float)
    status            = Column(String)
    attempts          = Column(Integer)
    created_at        = Column(DateTime)


class PayTransaction(Base):
    __tablename__ = "pay_transactions"
    id                  = Column(String, primary_key=True)
    pay_order_id        = Column(String)
    checkout_order_id   = Column(String)
    customer_id         = Column(String, index=True)
    provider_payment_id = Column(String)
    method              = Column(String)
    amount              = Column(Float)
    status              = Column(String)  # captured | failed | refunded
    error_code          = Column(String)
    created_at          = Column(DateTime)


# ── guard_rules ───────────────────────────────────────────────────────────────

class GuardRule(Base):
    """
    Runtime-configurable validation rules.
    Seeded with sensible defaults on startup; editable via API.
    """
    __tablename__ = "guard_rules"
    id            = Column(String, primary_key=True, default=_gen_id)
    name          = Column(String, nullable=False, unique=True)
    description   = Column(String, nullable=True)
    # order | user | payment | search | input | product | all
    target_type   = Column(String, nullable=False)
    # regex | threshold | rate_limit | range | zscore
    rule_type     = Column(String, nullable=False)
    # JSON structure depends on rule_type:
    #   regex:      {"pattern": "...", "field": "query"}
    #   threshold:  {"field": "amount", "operator": ">", "value": 100000}
    #   rate_limit: {"window_minutes": 60, "max_count": 10}
    #   range:      {"field": "quantity", "min": 1, "max": 100}
    #   zscore:     {"window_days": 30, "threshold": 4.0}
    condition     = Column(JSON, nullable=False)
    # flag | block | alert
    action        = Column(String, default="flag")
    # low | medium | high | critical
    severity      = Column(String, default="medium")
    is_active     = Column(Boolean, default=True)
    trigger_count = Column(Integer, default=0)
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ── guard_validation_logs ─────────────────────────────────────────────────────

class ValidationLog(Base):
    """
    Audit trail for every validation request.
    Raw input is never stored — only a SHA-256 hash for deduplication.
    """
    __tablename__ = "guard_validation_logs"
    id              = Column(String, primary_key=True, default=_gen_id)
    # order | payment | search | text | contact | amount | batch
    request_type    = Column(String, nullable=False)
    # SHA-256 of the raw input (no PII stored)
    input_hash      = Column(String, nullable=True)
    customer_id     = Column(String, nullable=True, index=True)
    session_id      = Column(String, nullable=True)
    ip_address      = Column(String, nullable=True)
    violations      = Column(JSON, nullable=True)   # list of violation dicts
    risk_score      = Column(Integer, default=0)    # 0-100
    # pass | flag | block
    action          = Column(String, default="pass")
    rules_triggered = Column(JSON, nullable=True)   # list of rule names
    created_at      = Column(DateTime, server_default=func.now())


# ── guard_anomaly_alerts ──────────────────────────────────────────────────────

class AnomalyAlert(Base):
    """
    Detected anomalies from the continuous scanning engine.
    Each row represents one anomalous pattern for one entity.
    """
    __tablename__ = "guard_anomaly_alerts"
    id              = Column(String, primary_key=True, default=_gen_id)
    # order_amount | rapid_ordering | payment_failure | search_injection |
    # inventory_price | inventory_stock | bot_behavior | bulk_purchase | replay_attack
    anomaly_type    = Column(String, nullable=False, index=True)
    # customer | order | product | payment | session
    entity_type     = Column(String, nullable=False)
    entity_id       = Column(String, nullable=False, index=True)
    severity        = Column(String, nullable=False)   # low | medium | high | critical
    title           = Column(String, nullable=False)
    description     = Column(Text, nullable=True)
    evidence        = Column(JSON, nullable=True)      # data that triggered the anomaly
    risk_score      = Column(Integer, default=0)       # 0-100
    # open | acknowledged | resolved | false_positive
    status          = Column(String, default="open", index=True)
    rule_name       = Column(String, nullable=True)    # which rule triggered this
    detected_at     = Column(DateTime, server_default=func.now(), index=True)
    resolved_at     = Column(DateTime, nullable=True)
    resolved_by     = Column(String, nullable=True)
    resolution_note = Column(String, nullable=True)
