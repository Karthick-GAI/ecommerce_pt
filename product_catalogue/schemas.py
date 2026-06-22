from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, field_validator


# ── PRODUCT IMAGE ─────────────────────────────────────────────────────────────

class ProductImageResponse(BaseModel):
    id: str
    url: str
    alt_text: Optional[str]
    is_primary: bool
    sort_order: int
    model_config = {"from_attributes": True}


# ── REVIEW ────────────────────────────────────────────────────────────────────

class ReviewCreate(BaseModel):
    reviewer_name: str
    reviewer_email: Optional[str] = None
    rating: int
    title: Optional[str] = None
    body: Optional[str] = None
    verified_purchase: bool = False

    @field_validator("rating")
    @classmethod
    def rating_range(cls, v):
        if not (1 <= v <= 5):
            raise ValueError("Rating must be 1–5")
        return v

    @field_validator("reviewer_name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Reviewer name cannot be blank")
        return v.strip()


class ReviewResponse(BaseModel):
    id: str
    reviewer_name: str
    rating: int
    title: Optional[str]
    body: Optional[str]
    verified_purchase: bool
    helpful_votes: int
    created_at: datetime
    model_config = {"from_attributes": True}


# ── PRODUCT — LIST VIEW (lightweight) ─────────────────────────────────────────

class ProductResponse(BaseModel):
    id: str
    name: str
    category: str
    subcategory: Optional[str]
    brand: str
    price: float
    discount_pct: float
    effective_price: float
    rating_avg: float
    rating_count: int
    primary_image: Optional[str]
    tags: Optional[List[str]]
    in_stock: bool
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_product(cls, p):
        return cls(
            id=p.id,
            name=p.name,
            category=p.category,
            subcategory=p.subcategory,
            brand=p.brand,
            price=p.price,
            discount_pct=p.discount_pct,
            effective_price=round(p.price * (1 - p.discount_pct / 100), 2),
            rating_avg=round(p.rating_avg, 1),
            rating_count=p.rating_count,
            primary_image=p.primary_image,
            tags=p.tags,
            in_stock=p.inventory_count > 0,
        )


# ── PRODUCT — DETAIL VIEW (full) ──────────────────────────────────────────────

class ProductDetailResponse(ProductResponse):
    description: str
    specifications: Optional[dict]
    inventory_count: int
    images: List[ProductImageResponse]
    rating_distribution: dict
    top_reviews: List[ReviewResponse]
    created_at: datetime


# ── PRODUCT — CREATE / UPDATE ─────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    description: str
    category: str
    subcategory: Optional[str] = None
    brand: str
    price: float
    discount_pct: float = 0.0
    inventory_count: int = 0
    tags: Optional[List[str]] = None
    specifications: Optional[dict] = None
    primary_image: Optional[str] = None

    @field_validator("price")
    @classmethod
    def price_positive(cls, v):
        if v <= 0:
            raise ValueError("Price must be > 0")
        return v

    @field_validator("discount_pct")
    @classmethod
    def discount_range(cls, v):
        if not (0 <= v <= 100):
            raise ValueError("Discount must be 0–100")
        return v


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    discount_pct: Optional[float] = None
    inventory_count: Optional[int] = None
    tags: Optional[List[str]] = None
    specifications: Optional[dict] = None
    is_active: Optional[bool] = None


# ── CATEGORY & BRAND ──────────────────────────────────────────────────────────

class CategoryResponse(BaseModel):
    id: str
    name: str
    parent_name: Optional[str]
    description: Optional[str]
    model_config = {"from_attributes": True}


class BrandResponse(BaseModel):
    brand: str
    product_count: int


# ── SEARCH ────────────────────────────────────────────────────────────────────

class SearchResponse(BaseModel):
    query: str
    total: int
    page: int = 1
    pages: int = 1
    results: List[ProductResponse]
    parsed_filters: Optional[dict] = None


class PaginatedProducts(BaseModel):
    total: int
    page: int
    limit: int
    pages: int
    results: List[ProductResponse]
