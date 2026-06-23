# models.py — SQLAlchemy ORM models (each class = one database table)

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from database import Base


def new_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id            = Column(String,   primary_key=True, default=new_uuid)
    email         = Column(String,   unique=True, index=True, nullable=False)
    password_hash = Column(String,   nullable=False)
    first_name    = Column(String,   nullable=False)
    last_name     = Column(String,   nullable=False)
    phone         = Column(String,   nullable=True)
    is_active     = Column(Boolean,  default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow)

    addresses       = relationship("Address",       back_populates="user", cascade="all, delete-orphan")
    payment_methods = relationship("PaymentMethod", back_populates="user", cascade="all, delete-orphan")


class Address(Base):
    __tablename__ = "addresses"

    id              = Column(String,   primary_key=True, default=new_uuid)
    user_id         = Column(String,   ForeignKey("users.id"), nullable=False)
    label           = Column(String,   nullable=False)        # "Home", "Office", "Other"
    full_name       = Column(String,   nullable=False)        # recipient name on the package
    phone           = Column(String,   nullable=False)        # delivery contact number
    alternate_phone = Column(String,   nullable=True)         # backup contact for delivery agent
    line1           = Column(String,   nullable=False)
    line2           = Column(String,   nullable=True)
    landmark        = Column(String,   nullable=True)         # e.g., "Near Big Bazaar" — common in India
    city            = Column(String,   nullable=False)
    state           = Column(String,   nullable=False)
    pincode         = Column(String,   nullable=False)
    is_default      = Column(Boolean,  default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="addresses")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id         = Column(String,  primary_key=True, default=new_uuid)
    user_id    = Column(String,  ForeignKey("users.id"), nullable=False)
    type       = Column(Enum("card", "upi", "wallet", name="payment_type"), nullable=False)
    label      = Column(String,  nullable=True)
    is_default = Column(Boolean, default=False)

    # Card fields — NEVER store full card number (PCI-DSS). Last 4 + brand for display only.
    card_last4  = Column(String(4), nullable=True)
    card_brand  = Column(String,    nullable=True)   # "Visa", "Mastercard", "RuPay", "Amex"
    card_holder = Column(String,    nullable=True)
    card_expiry = Column(String(7), nullable=True)   # "MM/YYYY"

    # UPI fields
    upi_id = Column(String, nullable=True)           # e.g., "karthick@paytm"

    # Wallet fields
    wallet_provider = Column(String, nullable=True)  # "Paytm", "PhonePe", "GPay"
    wallet_phone    = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payment_methods")
