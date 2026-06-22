# vector_store.py — pgvector semantic search helpers
#
# Embeddings are stored as a Vector(1536) column directly on the products table.
# No separate vector database needed — PostgreSQL handles everything.
#
# Cosine distance (<=>) is used: 0 = identical, 2 = opposite.
# We convert to a similarity score: score = 1 - (distance / 2), range 0–1.

from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from models import Product


def semantic_search(
    db: Session,
    query_embedding: List[float],
    n_results: int = 60,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    max_price: Optional[float] = None,
    min_price: Optional[float] = None,
) -> List[Tuple[Product, float]]:
    """
    Find the n_results most semantically similar products using pgvector cosine distance.
    Optional SQL filters (category, brand, price) are applied in the same query.
    Returns a list of (Product, similarity_score) tuples, highest score first.
    """
    distance_col = Product.embedding.cosine_distance(query_embedding).label("distance")

    q = (
        db.query(Product, distance_col)
        .filter(
            Product.is_active == True,
            Product.embedding.isnot(None),
        )
    )

    if category:
        q = q.filter(Product.category == category)
    if brand:
        q = q.filter(Product.brand == brand)
    if max_price is not None:
        q = q.filter(Product.price * (1 - Product.discount_pct / 100) <= max_price)
    if min_price is not None:
        q = q.filter(Product.price * (1 - Product.discount_pct / 100) >= min_price)

    rows = q.order_by(distance_col).limit(n_results).all()

    return [
        (product, round(1.0 - float(distance) / 2, 4))
        for product, distance in rows
    ]


def indexed_count(db: Session) -> int:
    """Return how many products have embeddings stored."""
    return (
        db.query(Product)
        .filter(Product.is_active == True, Product.embedding.isnot(None))
        .count()
    )
