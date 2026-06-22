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
    is_active       = Column(Boolean)
    primary_image   = Column(String)
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


class BrowsingEvent(Base):
    __tablename__ = "browsing_events"
    id         = Column(String, primary_key=True)
    user_id    = Column(String, index=True)
    product_id = Column(String, index=True)
    event_type = Column(String)
    session_id = Column(String)
    created_at = Column(DateTime)


class Wishlist(Base):
    __tablename__ = "wishlists"
    id         = Column(String, primary_key=True)
    user_id    = Column(String, index=True)
    product_id = Column(String, index=True)
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


class DatasetOrder(Base):
    __tablename__ = "orders"
    order_id      = Column(String, primary_key=True)
    user_id       = Column(String, index=True)
    order_status  = Column(String)
    total_amount  = Column(Float)
    cart_activity = Column(JSONB)
    created_at    = Column(DateTime)


# ── New: session service tables (sess_ prefix) ───────────────────────────────

class ShoppingSession(Base):
    """
    A live shopping session — created when a customer opens the app/site.
    Expires automatically after SESSION_TTL_MINUTES of inactivity.
    """
    __tablename__ = "sess_sessions"
    id               = Column(String, primary_key=True, default=_gen_id)
    customer_id      = Column(String, nullable=True, index=True)   # null = anonymous
    status           = Column(String, default="active")  # active | expired | completed | abandoned
    device_type      = Column(String)       # web | mobile | app
    referrer         = Column(String)       # utm_source / previous page
    entry_page       = Column(String)       # first page visited
    page_count       = Column(Integer, default=0)
    event_count      = Column(Integer, default=0)
    started_at       = Column(DateTime, server_default=func.now())
    last_activity_at = Column(DateTime, server_default=func.now())
    ended_at         = Column(DateTime, nullable=True)
    converted        = Column(Boolean, default=False)  # True if session led to purchase


class SessionEvent(Base):
    """
    A single interaction event within a shopping session.
    Acts as the real-time event stream for the session.
    """
    __tablename__ = "sess_events"
    id           = Column(String, primary_key=True, default=_gen_id)
    session_id   = Column(String, nullable=False, index=True)
    customer_id  = Column(String, nullable=True, index=True)
    event_type   = Column(String, nullable=False)
    # event_type values:
    #   page_view | product_view | search | add_to_cart | remove_from_cart
    #   wishlist_add | wishlist_remove | checkout_start | checkout_abandon
    #   purchase | recommendation_click | filter_apply | sort_change | review_view
    product_id   = Column(String, nullable=True)
    product_name = Column(String, nullable=True)
    category     = Column(String, nullable=True)
    search_query   = Column(String, nullable=True)   # for 'search' events
    page_path      = Column(String, nullable=True)   # page URL/route
    event_metadata = Column(JSON, nullable=True)     # extra structured data
    created_at     = Column(DateTime, server_default=func.now())


class SessionCartItem(Base):
    """
    Session-level shopping cart — the pre-checkout cart.
    Separate from checkout_carts; this is the browsing/intent cart.
    """
    __tablename__ = "sess_cart"
    id            = Column(String, primary_key=True, default=_gen_id)
    session_id    = Column(String, nullable=False, index=True)
    customer_id   = Column(String, nullable=True, index=True)
    product_id    = Column(String, nullable=False)
    product_name  = Column(String)
    category      = Column(String)
    brand         = Column(String)
    quantity      = Column(Integer, default=1)
    unit_price    = Column(Float)
    discount_pct  = Column(Float)
    saved_for_later = Column(Boolean, default=False)
    added_at      = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CustomerMemory(Base):
    """
    Long-term customer memory — aggregated from all interaction sources.
    Richer than rec_user_profiles: includes lifecycle stage, behavioral
    patterns, recent intent, and conversion metrics.
    """
    __tablename__ = "customer_memory"
    id                        = Column(String, primary_key=True, default=_gen_id)
    customer_id               = Column(String, nullable=False, unique=True, index=True)

    # Preference signals
    top_categories            = Column(JSON)   # {"Clothing": 45, "Electronics": 20}
    top_brands                = Column(JSON)
    top_subcategories         = Column(JSON)
    price_min                 = Column(Float)
    price_max                 = Column(Float)
    avg_order_value           = Column(Float)

    # Behavioral counts
    total_sessions            = Column(Integer, default=0)   # sess_sessions count
    total_events              = Column(Integer, default=0)   # browsing_events count
    total_searches            = Column(Integer, default=0)   # search_logs count
    total_purchases           = Column(Integer, default=0)   # from orders
    total_wishlisted          = Column(Integer, default=0)   # wishlists count
    total_cart_adds           = Column(Integer, default=0)   # browsing add_to_cart

    # Conversion metrics
    view_to_cart_rate         = Column(Float)   # cart_adds / product_views
    cart_to_purchase_rate     = Column(Float)   # purchases / cart_adds

    # Intent signals (recent — last 30 days)
    recent_searches           = Column(JSON)    # last 10 queries
    recently_viewed_categories = Column(JSON)   # last 10 categories browsed
    recently_viewed_products  = Column(JSON)    # last 5 product IDs

    # Lifecycle
    lifecycle_stage           = Column(String)  # new|exploring|engaged|repeat_buyer|loyal|at_risk
    first_seen_at             = Column(DateTime)
    last_seen_at              = Column(DateTime)
    days_since_last_visit     = Column(Integer)

    last_computed_at          = Column(DateTime, server_default=func.now())
    updated_at                = Column(DateTime, server_default=func.now(), onupdate=func.now())
