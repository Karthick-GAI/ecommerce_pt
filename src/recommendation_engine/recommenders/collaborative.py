"""
Collaborative filtering recommenders.

Item-based CF  — "Frequently bought together" using orders.cart_activity JSONB.
User-based CF  — "People like you also bought" using browsing_events purchase signals.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from .utils import fmt_product, normalize_scores


def get_bought_together(db: Session, product_id: str, limit: int = 10) -> list[dict]:
    """
    Products most frequently co-purchased in the same order.
    Uses cart_activity JSONB via PostgreSQL LATERAL to unnest items efficiently.
    """
    sql = text("""
        WITH target_orders AS (
            SELECT o.order_id
            FROM orders o,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE item.product_id = :pid
        ),
        co_items AS (
            SELECT item.product_id AS co_pid,
                   COUNT(*)        AS freq
            FROM target_orders t
            JOIN orders o ON o.order_id = t.order_id,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE item.product_id != :pid
            GROUP BY item.product_id
            ORDER BY freq DESC
            LIMIT :limit
        )
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            ci.freq::float AS raw_score
        FROM co_items ci
        JOIN products p ON p.id = ci.co_pid
        WHERE p.is_active = true
        ORDER BY ci.freq DESC
    """)
    rows = db.execute(sql, {"pid": product_id, "limit": limit}).fetchall()
    if not rows:
        return []
    scores = normalize_scores([r.raw_score for r in rows])
    return [
        fmt_product(r, scores[i], "collaborative_item",
                    "Frequently bought together")
        for i, r in enumerate(rows)
    ]


def get_also_bought_checkout(db: Session, product_id: str, limit: int = 10) -> list[dict]:
    """
    Co-purchase signal from checkout service orders (smaller but more recent dataset).
    """
    sql = text("""
        WITH target_orders AS (
            SELECT order_id FROM checkout_order_items WHERE product_id = :pid
        ),
        co_items AS (
            SELECT coi.product_id, COUNT(*) AS freq
            FROM target_orders t
            JOIN checkout_order_items coi ON coi.order_id = t.order_id
            WHERE coi.product_id != :pid
            GROUP BY coi.product_id
            ORDER BY freq DESC
            LIMIT :limit
        )
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            ci.freq::float AS raw_score
        FROM co_items ci
        JOIN products p ON p.id = ci.product_id
        WHERE p.is_active = true
        ORDER BY ci.freq DESC
    """)
    rows = db.execute(sql, {"pid": product_id, "limit": limit}).fetchall()
    if not rows:
        return []
    scores = normalize_scores([r.raw_score for r in rows])
    return [
        fmt_product(r, scores[i], "collaborative_item",
                    "Customers who bought this also bought")
        for i, r in enumerate(rows)
    ]


def get_user_based_cf(db: Session, customer_id: str, limit: int = 20) -> list[dict]:
    """
    User-based CF:
      1. Find products this customer has purchased (via orders.cart_activity).
      2. Find the top 100 most similar users by purchase overlap.
      3. Recommend products those users bought that this customer hasn't.
    Score = weighted sum of overlapping-user purchase frequency.
    """
    sql = text("""
        WITH my_products AS (
            SELECT DISTINCT item.product_id
            FROM orders o,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE o.user_id = :cid
        ),
        similar_users AS (
            SELECT o.user_id, COUNT(*) AS overlap
            FROM orders o,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE item.product_id IN (SELECT product_id FROM my_products)
              AND o.user_id != :cid
            GROUP BY o.user_id
            ORDER BY overlap DESC
            LIMIT 100
        ),
        candidate_scores AS (
            SELECT item.product_id, SUM(su.overlap) AS score
            FROM similar_users su
            JOIN orders o ON o.user_id = su.user_id,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE item.product_id NOT IN (SELECT product_id FROM my_products)
            GROUP BY item.product_id
            ORDER BY score DESC
            LIMIT :limit
        )
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            cs.score AS raw_score
        FROM candidate_scores cs
        JOIN products p ON p.id = cs.product_id
        WHERE p.is_active = true
        ORDER BY cs.score DESC
    """)
    rows = db.execute(sql, {"cid": customer_id, "limit": limit}).fetchall()
    if not rows:
        return []
    scores = normalize_scores([r.raw_score for r in rows])
    return [
        fmt_product(r, scores[i], "collaborative_user",
                    "People with similar taste also bought this")
        for i, r in enumerate(rows)
    ]


def get_cf_from_browsing(db: Session, customer_id: str, limit: int = 20) -> list[dict]:
    """
    Lightweight CF using browsing_events (purchase + add_to_cart signals).
    Used when a customer exists in browsing history but has no dataset orders.
    """
    sql = text("""
        WITH my_products AS (
            SELECT DISTINCT product_id
            FROM browsing_events
            WHERE user_id = :cid
              AND event_type IN ('purchase', 'add_to_cart', 'wishlist')
        ),
        similar_users AS (
            SELECT be.user_id, COUNT(*) AS overlap
            FROM browsing_events be
            WHERE be.product_id IN (SELECT product_id FROM my_products)
              AND be.event_type IN ('purchase', 'add_to_cart', 'wishlist')
              AND be.user_id != :cid
            GROUP BY be.user_id
            ORDER BY overlap DESC
            LIMIT 80
        ),
        candidate_scores AS (
            SELECT be.product_id, SUM(su.overlap) AS score
            FROM similar_users su
            JOIN browsing_events be ON be.user_id = su.user_id
            WHERE be.event_type IN ('purchase', 'add_to_cart')
              AND be.product_id NOT IN (SELECT product_id FROM my_products)
            GROUP BY be.product_id
            ORDER BY score DESC
            LIMIT :limit
        )
        SELECT
            p.id, p.name, p.category, p.subcategory, p.brand,
            p.price, p.discount_pct, p.inventory_count, p.rating_avg,
            cs.score AS raw_score
        FROM candidate_scores cs
        JOIN products p ON p.id = cs.product_id
        WHERE p.is_active = true
        ORDER BY cs.score DESC
    """)
    rows = db.execute(sql, {"cid": customer_id, "limit": limit}).fetchall()
    if not rows:
        return []
    scores = normalize_scores([r.raw_score for r in rows])
    return [
        fmt_product(r, scores[i], "collaborative_browsing",
                    "Based on what shoppers like you engage with")
        for i, r in enumerate(rows)
    ]


def get_user_purchase_count(db: Session, customer_id: str) -> int:
    """Number of unique products purchased by customer in dataset orders."""
    sql = text("""
        SELECT COUNT(DISTINCT item.product_id)
        FROM orders o,
        LATERAL jsonb_to_recordset(o.cart_activity)
            AS item(product_id text, quantity int, unit_price float)
        WHERE o.user_id = :cid
    """)
    result = db.execute(sql, {"cid": customer_id}).scalar()
    return int(result or 0)
