# database.py — sets up the database connection and session factory
#
# HOW IT WORKS:
#   1. create_engine()  → connects Python to the database file
#   2. SessionLocal()   → a factory that creates one DB session per request
#   3. Base             → parent class for all ORM models (models.py inherits from this)
#   4. get_db()         → a FastAPI dependency injected into every route that needs the DB

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite stores everything in a local file — no server needed for POC.
# To switch to PostgreSQL in production, just change this URL to:
#   "postgresql://user:password@host:5432/dbname"
# Nothing else in the codebase needs to change.
SQLALCHEMY_DATABASE_URL = "sqlite:///./ecommerce.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # SQLite only allows one thread by default.
    # FastAPI uses multiple threads, so we must allow that here.
    connect_args={"check_same_thread": False},
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
