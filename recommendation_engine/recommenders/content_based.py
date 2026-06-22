"""
Content-based recommenders.

Vector similarity  — pgvector cosine distance on pre-computed product embeddings.
Attribute matching — category / subcategory / brand / price-range fallback.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Product
from .utils import fmt_product, normalize_scores


def get_similar_by_vector(db: Session, product_id: str, limit: int = 10) -> list[dict]:
    """
    Semantic similarity via pgvector cosine distance on products.embedding.
    Returns empty list if the source product has no embedding.
    """
    sql = text("""
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            1 - (p.embedding <=> ref.embedding) AS similarity
        FROM products p
        CROSS JOIN (
            SELECT embedding FROM products
            WHERE id = :pid AND embedding IS NOT NULL
        ) ref
        WHERE p.is_active = true
          AND p.id        != :pid
          AND p.embedding IS NOT NULL
        ORDER BY p.embedding <=> ref.embedding
        LIMIT :limit
    """)
    rows = db.execute(sql, {"pid": product_id, "limit": limit}).fetchall()
    if not rows:
        return []
    return [
        fmt_product(r, float(r.similarity), "content_vector",
                    "Semantically similar to your interest")
        for r in rows
    ]


def get_similar_by_attributes(
    db: Session,
    product: Product,
    limit: int = 10,
    exclude_ids: list[str] | None = None,
) -> list[dict]:
    """
    Attribute-based similarity: same subcategory first, then same category.
    Within each tier, ranks by rating_avg × (1 - price_deviation).
    """
    exclude = set(exclude_ids or [])
    exclude.add(product.id)

    price_low  = product.price * 0.5
    price_high = product.price * 2.0

    # Tier 1: same subcategory + similar price
    q = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.subcategory == product.subcategory,
            ~Product.id.in_(exclude),
            Product.price.between(price_low, price_high),
        )
        .order_by(Product.rating_avg.desc().nulls_last())
        .limit(limit)
        .all()
    )

    # Tier 2: fill with same category if not enough
    if len(q) < limit:
        more_ids = {p.id for p in q} | exclude
        extra = (
            db.query(Product)
            .filter(
                Product.is_active == True,
                Product.category == product.category,
                ~Product.id.in_(more_ids),
                Product.price.between(price_low, price_high),
            )
            .order_by(Product.rating_avg.desc().nulls_last())
            .limit(limit - len(q))
            .all()
        )
        q = q + extra

    if not q:
        return []

    results = []
    for i, p in enumerate(q):
        score = 0.9 if p.subcategory == product.subcategory else 0.6
        tier  = "Same subcategory, similar price" if p.subcategory == product.subcategory \
                else "Same category, similar price"
        results.append(fmt_product(p, round(score - i * 0.01, 4), "content_attribute", tier))
    return results


def get_category_picks(
    db: Session,
    category: str,
    exclude_ids: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Top-rated in-stock products in a category, excluding already-seen products."""
    excl = set(exclude_ids or [])
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.category == category,
            Product.inventory_count > 0,
            ~Product.id.in_(excl),
        )
        .order_by(Product.rating_avg.desc().nulls_last())
        .limit(limit)
        .all()
    )
    return [
        fmt_product(p, round(0.8 - i * 0.02, 4), "content_category",
                    f"Top rated in {category}")
        for i, p in enumerate(products)
    ]


def get_similar_for_profile(
    db: Session,
    top_categories: dict,
    avg_price: float,
    exclude_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Recommendations based on a user's category preference profile.
    Weighted by category affinity score (purchase count per category).
    """
    if not top_categories:
        return []

    excl = set(exclude_ids or [])
    categories = sorted(top_categories.items(), key=lambda x: x[1], reverse=True)[:3]
    if not categories:
        return []

    price_low  = avg_price * 0.4
    price_high = avg_price * 2.5

    results = []
    per_cat = max(limit // len(categories), 3)

    for cat, weight in categories:
        products = (
            db.query(Product)
            .filter(
                Product.is_active == True,
                Product.category == cat,
                Product.inventory_count > 0,
                ~Product.id.in_(excl | {r["product_id"] for r in results}),
                Product.price.between(price_low, price_high),
            )
            .order_by(Product.rating_avg.desc().nulls_last())
            .limit(per_cat)
            .all()
        )
        max_weight = max(v for _, v in categories)
        norm_w = weight / max_weight if max_weight else 0.5
        for i, p in enumerate(products):
            results.append(
                fmt_product(p, round(norm_w * 0.8 - i * 0.01, 4),
                            "content_profile",
                            f"Matches your interest in {cat}")
            )

    return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]
