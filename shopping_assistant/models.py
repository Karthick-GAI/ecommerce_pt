import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from database import Base


def new_uuid():
    return str(uuid.uuid4())


# ── Read-only Product model ───────────────────────────────────────────────────
# Maps to the existing products table created by product_catalogue.
# No default= on id so SQLAlchemy does not try to INSERT a new product.

class Product(Base):
    __tablename__ = "products"

    id              = Column(String,       primary_key=True)
    name            = Column(String,       nullable=False)
    description     = Column(Text,         nullable=False)
    category        = Column(String,       nullable=False)
    subcategory     = Column(String,       nullable=True)
    brand           = Column(String,       nullable=False)
    price           = Column(Float,        nullable=False)
    discount_pct    = Column(Float,        default=0.0)
    inventory_count = Column(Integer,      default=0)
    rating_avg      = Column(Float,        default=0.0)
    rating_count    = Column(Integer,      default=0)
    primary_image   = Column(String,       nullable=True)
    tags            = Column(JSONB,        nullable=True)
    specifications  = Column(JSONB,        nullable=True)
    embedding       = Column(Vector(1536), nullable=True)
    is_active       = Column(Boolean,      default=True)
    created_at      = Column(DateTime,     default=datetime.utcnow)


# ── Chat session tables ───────────────────────────────────────────────────────

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id         = Column(String,   primary_key=True, default=new_uuid)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        order_by="ChatMessage.created_at",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(String,   primary_key=True, default=new_uuid)
    session_id = Column(String,   ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role       = Column(String,   nullable=False)   # "user" | "assistant"
    content    = Column(Text,     nullable=False)
    sources    = Column(JSONB,    nullable=True)    # product refs used as RAG context
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")
