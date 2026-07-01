import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, Date
from database import Base


def new_uuid():
    return str(uuid.uuid4())


# ── Read-only: shared products table ─────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id              = Column(String,   primary_key=True)
    name            = Column(String,   nullable=False)
    description     = Column(Text,     nullable=True)
    category        = Column(String,   nullable=False)
    subcategory     = Column(String,   nullable=True)
    brand           = Column(String,   nullable=False)
    price           = Column(Float,    nullable=False)
    discount_pct    = Column(Float,    default=0.0)
    inventory_count = Column(Integer,  default=0)
    rating_avg      = Column(Float,    default=0.0)
    is_active       = Column(Boolean,  default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)


# ── New tables ────────────────────────────────────────────────────────────────

class InventoryMovement(Base):
    """Full audit trail of every stock change."""
    __tablename__ = "inventory_movements"

    id              = Column(String,   primary_key=True, default=new_uuid)
    product_id      = Column(String,   nullable=False, index=True)
    product_name    = Column(String,   nullable=False)
    category        = Column(String,   nullable=False)
    brand           = Column(String,   nullable=False)
    # restock | sale | adjustment | return | damage | audit
    change_type     = Column(String,   nullable=False)
    quantity_before = Column(Integer,  nullable=False)
    quantity_change = Column(Integer,  nullable=False)   # positive = add, negative = remove
    quantity_after  = Column(Integer,  nullable=False)
    reference_id    = Column(String,   nullable=True)    # PO number or order_id
    notes           = Column(String,   nullable=True)
    changed_by      = Column(String,   default="system")
    created_at      = Column(DateTime, default=datetime.utcnow)


class AlertRule(Base):
    """Configurable threshold rules for low-stock alerts."""
    __tablename__ = "inventory_alert_rules"

    id              = Column(String,   primary_key=True, default=new_uuid)
    # product | category | global
    rule_type       = Column(String,   nullable=False)
    # product_id, category name, or "*" for global
    target_id       = Column(String,   nullable=False)
    label           = Column(String,   nullable=True)
    threshold_value = Column(Integer,  nullable=False)   # trigger when stock <= this
    # critical | warning | info
    alert_severity  = Column(String,   nullable=False)
    is_active       = Column(Boolean,  default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    """Generated alerts when stock drops below a rule threshold."""
    __tablename__ = "inventory_alerts"

    id              = Column(String,   primary_key=True, default=new_uuid)
    product_id      = Column(String,   nullable=False, index=True)
    product_name    = Column(String,   nullable=False)
    category        = Column(String,   nullable=False)
    brand           = Column(String,   nullable=True)
    current_stock   = Column(Integer,  nullable=False)
    threshold       = Column(Integer,  nullable=False)
    # critical | warning
    severity        = Column(String,   nullable=False)
    # open | acknowledged | resolved
    status          = Column(String,   default="open")
    rule_id         = Column(String,   nullable=True)
    acknowledged_by = Column(String,   nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at     = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow)


class DemandHistory(Base):
    """Daily category-level demand — seeded synthetic + actual sales."""
    __tablename__ = "demand_history"
    id         = Column(String,   primary_key=True, default=new_uuid)
    category   = Column(String,   nullable=False, index=True)
    date       = Column(Date,     nullable=False)
    units_sold = Column(Integer,  nullable=False, default=0)
    num_orders = Column(Integer,  default=0)
    avg_price  = Column(Float,    default=0.0)
    revenue    = Column(Float,    default=0.0)
    source     = Column(String,   default="seeded")   # seeded | actual
    created_at = Column(DateTime, default=datetime.utcnow)


class DemandForecast(Base):
    """ML model 30-day forward predictions per category."""
    __tablename__ = "demand_forecasts"
    id               = Column(String,   primary_key=True, default=new_uuid)
    category         = Column(String,   nullable=False, index=True)
    forecast_date    = Column(Date,     nullable=False)
    predicted_units  = Column(Float,    nullable=False)
    lower_bound      = Column(Float,    nullable=True)
    upper_bound      = Column(Float,    nullable=True)
    model_name       = Column(String,   default="ridge_fourier_v1")
    rmse             = Column(Float,    nullable=True)
    confidence_score = Column(Float,    nullable=True)
    generated_at     = Column(DateTime, default=datetime.utcnow)


class RestockingAlert(Base):
    """Automated restocking alerts generated from demand forecasting."""
    __tablename__ = "restock_alerts"
    id                       = Column(String,   primary_key=True, default=new_uuid)
    category                 = Column(String,   nullable=False, index=True)
    current_stock            = Column(Integer,  nullable=False)
    avg_daily_demand         = Column(Float,    nullable=False)
    forecasted_demand_30d    = Column(Integer,  nullable=False)
    days_until_stockout      = Column(Integer,  nullable=True)
    recommended_reorder_qty  = Column(Integer,  nullable=False)
    severity                 = Column(String,   nullable=False)   # critical | warning
    status                   = Column(String,   default="open")   # open | acknowledged
    acknowledged_by          = Column(String,   nullable=True)
    acknowledged_at          = Column(DateTime, nullable=True)
    triggered_at             = Column(DateTime, default=datetime.utcnow)
    created_at               = Column(DateTime, default=datetime.utcnow)
