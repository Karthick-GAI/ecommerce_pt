from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base
import uuid


def _gen_id():
    return str(uuid.uuid4())


# ── Read-only: dataset tables ─────────────────────────────────────────────────
# No default= on primary keys to prevent accidental INSERT.

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
    tags            = Column(JSONB)
    description     = Column(Text)
    is_active       = Column(Boolean)
    created_at      = Column(DateTime)
    # embedding column is USER-DEFINED (pgvector); accessed only via raw SQL


class Customer(Base):
    __tablename__ = "customers"
    user_id    = Column(String, primary_key=True)
    email      = Column(String)
    first_name = Column(String)
    last_name  = Column(String)
    city       = Column(String)
    state      = Column(String)
    segment    = Column(String)
    created_at = Column(DateTime)


class DatasetOrder(Base):
    __tablename__ = "orders"
    order_id      = Column(String, primary_key=True)
    user_id       = Column(String, index=True)
    order_status  = Column(String)
    total_amount  = Column(Float)
    cart_activity = Column(JSONB)   # [{product_id, quantity, unit_price}, ...]
    created_at    = Column(DateTime)


class BrowsingEvent(Base):
    __tablename__ = "browsing_events"
    id          = Column(String, primary_key=True)
    user_id     = Column(String, index=True)
    product_id  = Column(String, index=True)
    event_type  = Column(String)   # view | add_to_cart | wishlist | purchase
    session_id  = Column(String)
    created_at  = Column(DateTime)


class Wishlist(Base):
    __tablename__ = "wishlists"
    id         = Column(String, primary_key=True)
    user_id    = Column(String, index=True)
    product_id = Column(String, index=True)
    created_at = Column(DateTime)


class SearchLog(Base):
    __tablename__ = "search_logs"
    id                = Column(String, primary_key=True)
    user_id           = Column(String, index=True)
    query             = Column(String)
    clicked_product_id = Column(String)
    search_type       = Column(String)
    created_at        = Column(DateTime)


# ── Read-only: checkout service tables ───────────────────────────────────────

class CheckoutOrder(Base):
    __tablename__ = "checkout_orders"
    id             = Column(String, primary_key=True)
    customer_id    = Column(String, index=True)
    status         = Column(String)
    total          = Column(Float)
    payment_status = Column(String)
    created_at     = Column(DateTime)


class CheckoutOrderItem(Base):
    __tablename__ = "checkout_order_items"
    id           = Column(String, primary_key=True)
    order_id     = Column(String, index=True)
    product_id   = Column(String, index=True)
    product_name = Column(String)
    brand        = Column(String)
    quantity     = Column(Integer)
    unit_price   = Column(Float)


# ── New: recommendation service tables ───────────────────────────────────────

class RecInteraction(Base):
    __tablename__ = "rec_interactions"
    id               = Column(String, primary_key=True, default=_gen_id)
    customer_id      = Column(String, nullable=False, index=True)
    product_id       = Column(String, nullable=False, index=True)
    product_name     = Column(String)
    category         = Column(String)
    brand            = Column(String)
    interaction_type = Column(String, nullable=False)  # view|click|add_to_cart|purchase|wishlist|rating
    rating           = Column(Integer)                 # 1–5, used when interaction_type = "rating"
    session_id       = Column(String)
    source           = Column(String)   # homepage|search|recommendation|direct|category
    created_at       = Column(DateTime, server_default=func.now())


class UserPreferenceProfile(Base):
    __tablename__ = "rec_user_profiles"
    id               = Column(String, primary_key=True, default=_gen_id)
    customer_id      = Column(String, nullable=False, unique=True, index=True)
    top_categories   = Column(JSON)    # {"Electronics": 12, "Books": 5, ...}
    top_brands       = Column(JSON)    # {"Samsung": 8, "Apple": 3, ...}
    top_subcategories = Column(JSON)
    price_min        = Column(Float)
    price_max        = Column(Float)
    avg_price        = Column(Float)
    total_purchases  = Column(Integer, default=0)
    total_interactions = Column(Integer, default=0)
    last_computed_at = Column(DateTime, server_default=func.now())
    updated_at       = Column(DateTime, server_default=func.now(), onupdate=func.now())
