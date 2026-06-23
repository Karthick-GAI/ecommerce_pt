"""
Recommendation tools.

get_recommendations    — personalised picks for a customer (hybrid CF + content)
get_similar_products   — products similar to a given product (pgvector)
get_trending_products  — most purchased recently, optionally filtered by category
get_deals              — best current discounts with strong ratings
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Product


def _stock_health(count: int) -> str:
    if count == 0:  return "out_of_stock"
    if count <= 5:  return "critical"
    if count <= 20: return "low"
    return "healthy"


def _fmt(p, score: float, reason: str) -> dict:
    return {
        "product_id":    p.id,
        "name":          p.name,
        "category":      p.category,
        "brand":         p.brand,
        "price":         p.price,
        "discount_pct":  p.discount_pct,
        "effective_price": round(p.price * (1 - (p.discount_pct or 0) / 100), 2),
        "stock":         p.inventory_count,
        "stock_health":  _stock_health(p.inventory_count),
        "rating_avg":    p.rating_avg,
        "score":         round(score, 3),
        "reason":        reason,
    }


def get_recommendations(db: Session, customer_id: str, limit: int = 5) -> dict:
    """
    Personalised product recommendations based on purchase history.
    Uses collaborative filtering on order history.
    Falls back to trending products for customers with no purchase history.
    """
    # User-based CF from dataset orders
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
            LIMIT 80
        ),
        candidates AS (
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
        SELECT p.id, p.name, p.category, p.subcategory, p.brand,
               p.price, p.discount_pct, p.inventory_count, p.rating_avg,
               c.score
        FROM candidates c
        JOIN products p ON p.id = c.product_id
        WHERE p.is_active = true AND p.inventory_count > 0
        ORDER BY c.score DESC
    """)
    rows = db.execute(sql, {"cid": customer_id, "limit": limit}).fetchall()

    if rows:
        mx = max(r.score for r in rows) or 1
        return {
            "strategy": "collaborative_filtering",
            "customer_id": customer_id,
            "count": len(rows),
            "recommendations": [
                {
                    "product_id":    r.id,
                    "name":          r.name,
                    "category":      r.category,
                    "brand":         r.brand,
                    "price":         r.price,
                    "discount_pct":  r.discount_pct,
                    "effective_price": round(r.price * (1 - (r.discount_pct or 0) / 100), 2),
                    "stock":         r.inventory_count,
                    "stock_health":  _stock_health(r.inventory_count),
                    "rating_avg":    r.rating_avg,
                    "score":         round(float(r.score) / mx, 3),
                    "reason":        "People with similar purchase history bought this",
                }
                for r in rows
            ],
        }

    # Cold-start fallback: trending
    trend = get_trending_products(db, limit=limit)
    trend["strategy"] = "trending_fallback"
    trend["note"] = "No purchase history found — showing trending products instead."
    return trend


def get_similar_products(db: Session, product_id: str, limit: int = 5) -> dict:
    """
    Find products similar to the given product using pgvector cosine similarity
    on pre-computed embeddings. Falls back to attribute matching if no embedding.
    """
    product = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()
    if not product:
        return {"found": False, "product_id": product_id,
                "message": "Product not found."}

    # pgvector similarity
    vec_sql = text("""
        SELECT p.id, p.name, p.category, p.subcategory, p.brand,
               p.price, p.discount_pct, p.inventory_count, p.rating_avg,
               1 - (p.embedding <=> ref.embedding) AS similarity
        FROM products p
        CROSS JOIN (
            SELECT embedding FROM products
            WHERE id = :pid AND embedding IS NOT NULL
        ) ref
        WHERE p.is_active = true
          AND p.id != :pid
          AND p.inventory_count > 0
          AND p.embedding IS NOT NULL
        ORDER BY p.embedding <=> ref.embedding
        LIMIT :limit
    """)
    rows = db.execute(vec_sql, {"pid": product_id, "limit": limit}).fetchall()
    strategy = "vector_similarity"

    if not rows:
        # Attribute fallback
        price_low  = product.price * 0.5
        price_high = product.price * 2.0
        fallback = (
            db.query(Product)
            .filter(
                Product.is_active == True,
                Product.category == product.category,
                Product.id != product_id,
                Product.inventory_count > 0,
                Product.price.between(price_low, price_high),
            )
            .order_by(Product.rating_avg.desc().nulls_last())
            .limit(limit)
            .all()
        )
        return {
            "found": True,
            "strategy": "attribute_matching",
            "base_product": product.name,
            "count": len(fallback),
            "similar": [_fmt(p, 0.7 - i * 0.05, f"Same category ({product.category}), similar price")
                        for i, p in enumerate(fallback)],
        }

    return {
        "found": True,
        "strategy": strategy,
        "base_product": product.name,
        "count": len(rows),
        "similar": [
            {
                "product_id":    r.id,
                "name":          r.name,
                "category":      r.category,
                "brand":         r.brand,
                "price":         r.price,
                "discount_pct":  r.discount_pct,
                "effective_price": round(r.price * (1 - (r.discount_pct or 0) / 100), 2),
                "stock":         r.inventory_count,
                "stock_health":  _stock_health(r.inventory_count),
                "rating_avg":    r.rating_avg,
                "similarity":    round(float(r.similarity), 3),
                "reason":        "Semantically similar product",
            }
            for r in rows
        ],
    }


def get_trending_products(
    db: Session,
    category: str | None = None,
    limit: int = 5,
) -> dict:
    """
    Most purchased products in the last 30 days.
    Optionally filtered by category.
    """
    cat_filter = "AND p.category = :category" if category else ""

    sql = text(f"""
        WITH recent AS (
            SELECT item.product_id, SUM(item.quantity) AS buy_count
            FROM orders o,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE o.created_at >= NOW() - INTERVAL '30 days'
            GROUP BY item.product_id
        )
        SELECT p.id, p.name, p.category, p.subcategory, p.brand,
               p.price, p.discount_pct, p.inventory_count, p.rating_avg,
               r.buy_count
        FROM recent r
        JOIN products p ON p.id = r.product_id
        WHERE p.is_active = true
          AND p.inventory_count > 0
          {cat_filter}
        ORDER BY r.buy_count DESC
        LIMIT :limit
    """)
    params = {"limit": limit}
    if category:
        params["category"] = category

    rows = db.execute(sql, params).fetchall()
    mx = max((r.buy_count for r in rows), default=1)

    return {
        "strategy": "trending",
        "category": category,
        "count": len(rows),
        "recommendations": [
            {
                "product_id":    r.id,
                "name":          r.name,
                "category":      r.category,
                "brand":         r.brand,
                "price":         r.price,
                "discount_pct":  r.discount_pct,
                "effective_price": round(r.price * (1 - (r.discount_pct or 0) / 100), 2),
                "stock":         r.inventory_count,
                "stock_health":  _stock_health(r.inventory_count),
                "rating_avg":    r.rating_avg,
                "buy_count":     int(r.buy_count),
                "score":         round(float(r.buy_count) / mx, 3),
                "reason":        f"Trending — {int(r.buy_count)} units sold in the last 30 days",
            }
            for r in rows
        ],
    }


def get_deals(db: Session, limit: int = 5) -> dict:
    """
    Best current deals: highest discount percentage with strong ratings
    and healthy stock.
    """
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.inventory_count > 5,
            Product.discount_pct > 0,
        )
        .order_by(Product.discount_pct.desc(), Product.rating_avg.desc().nulls_last())
        .limit(limit)
        .all()
    )

    return {
        "strategy": "deals",
        "count": len(products),
        "recommendations": [
            {
                "product_id":      p.id,
                "name":            p.name,
                "category":        p.category,
                "brand":           p.brand,
                "original_price":  p.price,
                "discount_pct":    p.discount_pct,
                "effective_price": round(p.price * (1 - (p.discount_pct or 0) / 100), 2),
                "savings":         round(p.price * (p.discount_pct or 0) / 100, 2),
                "stock":           p.inventory_count,
                "rating_avg":      p.rating_avg,
                "reason":          f"Save {int(p.discount_pct or 0)}% — limited time deal",
            }
            for p in products
        ],
    }
