# database.py — sets up the database connection and session factory
#
# HOW IT WORKS:
#   1. create_engine()  → connects Python to the database file
#   2. SessionLocal()   → a factory that creates one DB session per request
#   3. Base             → parent class for all ORM models (models.py inherits from this)
#   4. get_db()         → a FastAPI dependency injected into every route that needs the DB

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Default to SQLite for zero-setup local dev; override USER_DB_URL for PostgreSQL or
# a Docker volume-backed absolute path (sqlite:////data/ecommerce.db).
SQLALCHEMY_DATABASE_URL = os.getenv("USER_DB_URL", "sqlite:///./ecommerce.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency — yields a DB session for a request, then closes it.
    Using 'yield' ensures the session is always closed even if the route throws.
    Usage in routes:  db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
