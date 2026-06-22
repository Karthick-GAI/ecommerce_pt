"""Personalised recommendation and preference tools."""
import json
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from tools.shared_models import Product, UserPreferenceProfile, CustomerMemory, CheckoutOrderItem, CheckoutOrder


def _product_summary(row) -> dict:
    ep = round(row.price * (1 - (row.discount_pct or 0) / 100), 2)
    return {
        "product_id":      row.id,
        "name":            row.name,
        "brand":           row.brand,
        "category":        row.category,
        "price":           row.price,
        "effective_price": ep,
        "discount_pct":    row.discount_pct or 0,
        "rating":          round(row.rating_avg or 0, 1),
        "in_stock":        (row.inventory_count or 0) > 0,
        "image":           row.primary_image,
    }


def get_personalized_recommendations(customer_id: str, db: Session, limit: int = 10) -> str:
    profile = db.query(UserPreferenceProfile).filter(
        UserPreferenceProfile.user_id == customer_id
    ).first()

    memory = db.query(CustomerMemory).filter(
        CustomerMemory.customer_id == customer_id
    ).first()

    if not profile and not memory:
        # Cold start: return top-rated products
        products = (
            db.query(Product)
            .filter(Product.is_active == True, Product.inventory_count > 0)
            .order_by(Product.rating_avg.desc())
            .limit(min(limit, 20))
            .all()
        )
        return json.dumps({
            "products":          [_product_summary(p) for p in products],
            "personalised":      False,
            "lifecycle_stage":   "new",
            "message":           "Showing top-rated products (new customer).",
        })

    # Use preferred categories/brands if available
    top_categories = []
    top_brands     = []
    price_max      = None

    if profile:
        top_categories = profile.top_categories or []
        top_brands     = profile.top_brands or []
        price_max      = profile.price_max

    if memory:
        top_categories = top_categories or (memory.top_categories or [])
        top_brands     = top_brands or (memory.top_brands or [])

    sql_parts = ["p.is_active = true", "p.inventory_count > 0"]
    params: dict = {"limit": min(limit, 20)}

    if top_categories:
        placeholders = ", ".join(f":cat{i}" for i in range(len(top_categories)))
        sql_parts.append(f"LOWER(p.category) IN ({placeholders})")
        for i, c in enumerate(top_categories[:5]):
            params[f"cat{i}"] = c.lower()

    if price_max:
        sql_parts.append("p.price <= :price_max")
        params["price_max"] = price_max

    where = " AND ".join(sql_parts)
    sql = text(f"""
        SELECT id, name, brand, category, price, discount_pct, inventory_count,
               rating_avg, rating_count, primary_image
        FROM products p
        WHERE {where}
        ORDER BY p.rating_avg DESC, p.rating_count DESC
        LIMIT :limit
    """)

    rows = db.execute(sql, params).fetchall()
    products = [_product_summary(r) for r in rows]

    if len(products) < 3:
        # Pad with top-rated
        fallback = (
            db.query(Product)
            .filter(Product.is_active == True, Product.inventory_count > 0)
            .order_by(Product.rating_avg.desc())
            .limit(min(limit, 20))
            .all()
        )
        seen_ids = {p["product_id"] for p in products}
        for f in fallback:
            if f.id not in seen_ids:
                products.append(_product_summary(f))
            if len(products) >= limit:
                break

    return json.dumps({
        "products":        products[:limit],
        "personalised":    True,
        "top_categories":  top_categories[:3],
        "lifecycle_stage": memory.lifecycle_stage if memory else "exploring",
    })


def get_trending_products(db: Session, category: str = None, limit: int = 10) -> str:
    sql_base = """
        SELECT p.id, p.name, p.brand, p.category, p.price, p.discount_pct,
               p.inventory_count, p.rating_avg, p.rating_count, p.primary_image,
               COUNT(oi.id) AS purchase_count
        FROM products p
        JOIN checkout_order_items oi ON oi.product_id = p.id
        JOIN checkout_orders o ON o.id = oi.order_id
        WHERE o.created_at >= NOW() - INTERVAL '30 days'
          AND o.status NOT IN ('cancelled', 'payment_failed')
          AND p.is_active = true
    """
    params: dict = {"limit": min(limit, 30)}

    if category:
        sql_base += " AND LOWER(p.category) = LOWER(:category)"
        params["category"] = category

    sql_base += " GROUP BY p.id ORDER BY purchase_count DESC LIMIT :limit"

    try:
        rows = db.execute(text(sql_base), params).fetchall()
        products = []
        for r in rows:
            d = _product_summary(r)
            d["purchase_count_30d"] = r.purchase_count
            products.append(d)

        if not products:
            raise Exception("no rows")

        return json.dumps({"products": products, "period": "last 30 days"})

    except Exception:
        fallback = (
            db.query(Product)
            .filter(Product.is_active == True)
            .order_by(Product.rating_count.desc())
            .limit(min(limit, 30))
            .all()
        )
        return json.dumps({"products": [_product_summary(p) for p in fallback], "period": "all time"})


def get_best_deals(db: Session, limit: int = 10) -> str:
    products = (
        db.query(Product)
        .filter(Product.is_active == True, Product.discount_pct > 0, Product.inventory_count > 0)
        .order_by(Product.discount_pct.desc(), Product.rating_avg.desc())
        .limit(min(limit, 30))
        .all()
    )
    return json.dumps({
        "products": [_product_summary(p) for p in products],
        "message":  "Products sorted by highest discount percentage.",
    })


def get_customer_preferences(customer_id: str, db: Session) -> str:
    memory = db.query(CustomerMemory).filter(CustomerMemory.customer_id == customer_id).first()
    profile = db.query(UserPreferenceProfile).filter(
        UserPreferenceProfile.user_id == customer_id
    ).first()

    if not memory and not profile:
        return json.dumps({
            "customer_id":    customer_id,
            "found":          False,
            "message":        "No preference data available yet. Customer may be new.",
        })

    return json.dumps({
        "customer_id":          customer_id,
        "found":                True,
        "top_categories":       (memory.top_categories if memory else []) or (profile.top_categories if profile else []),
        "top_brands":           (memory.top_brands if memory else []) or (profile.top_brands if profile else []),
        "price_range":          {
            "min": profile.price_min if profile else None,
            "max": profile.price_max if profile else None,
        },
        "lifecycle_stage":      memory.lifecycle_stage if memory else None,
        "total_purchases":      memory.total_purchases if memory else 0,
        "avg_order_value":      memory.avg_order_value if memory else 0,
        "cart_to_purchase_rate": memory.cart_to_purchase_rate if memory else 0,
        "recent_searches":      (memory.recent_searches or [])[:5] if memory else [],
        "last_active":          str(memory.last_seen_at) if memory and memory.last_seen_at else None,
    })
