from typing import Optional, Literal, List
from pydantic import BaseModel, Field


class InteractionRequest(BaseModel):
    customer_id:      str
    product_id:       str
    interaction_type: Literal["view", "click", "add_to_cart", "purchase", "wishlist", "rating"]
    rating:           Optional[int] = Field(None, ge=1, le=5)
    session_id:       Optional[str] = None
    source:           Optional[Literal["homepage", "search", "recommendation", "direct", "category"]] = None


class ProductRecommendation(BaseModel):
    product_id:   str
    name:         str
    category:     str
    subcategory:  Optional[str]   = None
    brand:        str
    price:        float
    discount_pct: Optional[float] = None
    stock:        int
    health:       str
    rating_avg:   Optional[float] = None
    score:        float
    strategy:     str
    reason:       str


class RecommendationSection(BaseModel):
    title:    str
    strategy: str
    products: List[ProductRecommendation]


class HomepageFeed(BaseModel):
    customer_id:   str
    customer_name: Optional[str]  = None
    sections:      List[RecommendationSection]
    generated_at:  str
