import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from database import Base


def new_uuid():
    return str(uuid.uuid4())


class Product(Base):
    __tablename__ = "products"

    id              = Column(String,  primary_key=True, default=new_uuid)
    name            = Column(String,  nullable=False, index=True)
    description     = Column(Text,    nullable=False)
    category        = Column(String,  nullable=False, index=True)
    subcategory     = Column(String,  nullable=True,  index=True)
    brand           = Column(String,  nullable=False, index=True)
    price           = Column(Float,   nullable=False)
    discount_pct    = Column(Float,   default=0.0)
    inventory_count = Column(Integer, default=0)
    rating_avg      = Column(Float,   default=0.0)
    rating_count    = Column(Integer, default=0)
    primary_image   = Column(String,  nullable=True)
    tags            = Column(JSONB,   nullable=True)           # ["wireless", "lightweight"]
    specifications  = Column(JSONB,   nullable=True)           # {"RAM":"8GB","Storage":"256GB"}
    embedding       = Column(Vector(1536), nullable=True)      # text-embedding-3-small vector
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    images  = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    reviews = relationship("Review",       back_populates="product", cascade="all, delete-orphan")


class ProductImage(Base):
    __tablename__ = "product_images"

    id         = Column(String,  primary_key=True, default=new_uuid)
    product_id = Column(String,  ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    url        = Column(String,  nullable=False)
    alt_text   = Column(String,  nullable=True)
    is_primary = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

    product = relationship("Product", back_populates="images")


class Review(Base):
    __tablename__ = "reviews"

    id                = Column(String,  primary_key=True, default=new_uuid)
    product_id        = Column(String,  ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    reviewer_name     = Column(String,  nullable=False)
    reviewer_email    = Column(String,  nullable=True)
    rating            = Column(Integer, nullable=False)
    title             = Column(String,  nullable=True)
    body              = Column(Text,    nullable=True)
    verified_purchase = Column(Boolean, default=False)
    helpful_votes     = Column(Integer, default=0)
    created_at        = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="reviews")


class Category(Base):
    __tablename__ = "categories"

    id          = Column(String, primary_key=True, default=new_uuid)
    name        = Column(String, nullable=False, unique=True)
    parent_name = Column(String, nullable=True)
    description = Column(String, nullable=True)
