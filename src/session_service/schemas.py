from typing import Optional, Literal, List, Any
from pydantic import BaseModel, Field


# ── Session ───────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    customer_id: Optional[str]  = None
    device_type: Optional[Literal["web", "mobile", "app"]] = "web"
    referrer:    Optional[str]  = None
    entry_page:  Optional[str]  = None


class SessionUpdate(BaseModel):
    page_path:  Optional[str] = None   # current page being visited


# ── Events ────────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    event_type:   Literal[
        "page_view", "product_view", "search",
        "add_to_cart", "remove_from_cart",
        "wishlist_add", "wishlist_remove",
        "checkout_start", "checkout_abandon", "purchase",
        "recommendation_click", "filter_apply", "sort_change", "review_view"
    ]
    product_id:   Optional[str]  = None
    search_query: Optional[str]  = None
    page_path:    Optional[str]  = None
    metadata:     Optional[dict] = None


# ── Cart ──────────────────────────────────────────────────────────────────────

class CartItemAdd(BaseModel):
    product_id: str
    quantity:   int = Field(1, ge=1, le=50)


class CartItemUpdate(BaseModel):
    quantity: int = Field(..., ge=0, le=50)   # 0 = remove


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryOut(BaseModel):
    customer_id:          str
    lifecycle_stage:      Optional[str]   = None
    top_categories:       Optional[dict]  = None
    top_brands:           Optional[dict]  = None
    price_range:          Optional[dict]  = None
    total_purchases:      Optional[int]   = None
    total_sessions:       Optional[int]   = None
    recent_searches:      Optional[list]  = None
    recently_viewed_categories: Optional[list] = None
    view_to_cart_rate:    Optional[float] = None
    cart_to_purchase_rate: Optional[float] = None
    days_since_last_visit: Optional[int]  = None
    last_computed_at:     Optional[str]   = None
