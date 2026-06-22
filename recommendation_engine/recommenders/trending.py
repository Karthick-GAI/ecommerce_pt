"""
Trending and discovery recommenders.

Trending      — most purchased in last N days from orders + browsing_events.
Top-viewed    — most viewed products from browsing_events.
New arrivals  — most recently added active products.
Deals         — highest discount_pct with good stock.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Product
from .utils import fmt_product, normalize_scores


def get_trending(
    db: Session,
    days: int = 30,
    limit: int = 20,
    category: str | None = None,
    exclude_ids: list[str] | None = None,
) -> list[dict]:
    """
    Most purchased products in the last `days` days (from orders.cart_activity).
    """
    excl = list(exclude_ids or [])
    cat_filter = "AND p.category = :category" if category else ""

    sql = text(f"""
        WITH recent_purchases AS (
            SELECT item.product_id, SUM(item.quantity) AS purchase_count
            FROM orders o,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE o.created_at >= NOW() - INTERVAL '{days} days'
            GROUP BY item.product_id
        )
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            rp.purchase_count::float AS raw_score
        FROM recent_purchases rp
        JOIN products p ON p.id = rp.product_id
        WHERE p.is_active = true
          AND p.inventory_count > 0
          AND p.id != ALL(:excl)
          {cat_filter}
        ORDER BY rp.purchase_count DESC
        LIMIT :limit
    """)
    params = {"excl": excl, "limit": limit}
    if category:
        params["category"] = category
    rows = db.execute(sql, params).fetchall()
    if not rows:
        return []
    scores = normalize_scores([r.raw_score for r in rows])
    period = f"last {days} days"
    return [
        fmt_product(r, scores[i], "trending",
                    f"Trending — popular in the {period}")
        for i, r in enumerate(rows)
    ]


def get_top_viewed(
    db: Session,
    days: int = 7,
    limit: int = 20,
    exclude_ids: list[str] | None = None,
) -> list[dict]:
    """
    Most viewed products from browsing_events in last `days` days.
    Weighted: purchase=3, add_to_cart=2, wishlist=1.5, view=1
    """
    excl = list(exclude_ids or [])
    sql = text(f"""
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            SUM(CASE be.event_type
                WHEN 'purchase'    THEN 3
                WHEN 'add_to_cart' THEN 2
                WHEN 'wishlist'    THEN 1.5
                ELSE 1
            END) AS engagement_score
        FROM browsing_events be
        JOIN products p ON p.id = be.product_id
        WHERE be.created_at >= NOW() - INTERVAL '{days} days'
          AND p.is_active = true
          AND p.inventory_count > 0
          AND p.id != ALL(:excl)
        GROUP BY p.id, p.name, p.category, p.subcategory, p.brand,
                 p.price, p.discount_pct, p.inventory_count, p.rating_avg
        ORDER BY engagement_score DESC
        LIMIT :limit
    """)
    rows = db.execute(sql, {"excl": excl, "limit": limit}).fetchall()
    if not rows:
        return []
    scores = normalize_scores([r.engagement_score for r in rows])
    return [
        fmt_product(r, scores[i], "trending_views",
                    "Highly engaged with by shoppers this week")
        for i, r in enumerate(rows)
    ]


def get_new_arrivals(
    db: Session,
    limit: int = 20,
    category: str | None = None,
    exclude_ids: list[str] | None = None,
) -> list[dict]:
    """Most recently added active products with available stock."""
    excl = set(exclude_ids or [])
    q = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.inventory_count > 0,
            ~Product.id.in_(excl),
        )
    )
    if category:
        q = q.filter(Product.category == category)

    products = (
        q.order_by(Product.created_at.desc().nulls_last())
        .limit(limit)
        .all()
    )
    return [
        fmt_product(p, round(max(1.0 - i * 0.03, 0.01), 4), "new_arrival",
                    "Just arrived — freshly added to our catalogue")
        for i, p in enumerate(products)
    ]


def get_top_deals(
    db: Session,
    limit: int = 20,
    exclude_ids: list[str] | None = None,
) -> list[dict]:
    """Highest discount products with good stock and strong ratings."""
    excl = set(exclude_ids or [])
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.inventory_count > 5,
            Product.discount_pct > 0,
            ~Product.id.in_(excl),
        )
        .order_by(Product.discount_pct.desc(), Product.rating_avg.desc().nulls_last())
        .limit(limit)
        .all()
    )
    return [
        fmt_product(
            p,
            round(max(min((p.discount_pct or 0) / 100, 1.0) * 0.9 - i * 0.005, 0.001), 4),
            "deals",
            f"Save {int(p.discount_pct or 0)}% — top deal",
        )
        for i, p in enumerate(products)
    ]
