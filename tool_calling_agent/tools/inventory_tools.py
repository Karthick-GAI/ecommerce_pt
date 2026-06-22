"""
Inventory check tools.

search_products        — find products by name/brand/category with stock info
check_product_stock    — detailed stock status for a specific product
get_category_summary   — inventory health overview for a product category
"""
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from models import Product, InventoryAlert


def _stock_health(count: int) -> str:
    if count == 0:  return "out_of_stock"
    if count <= 5:  return "critical"
    if count <= 20: return "low"
    return "healthy"


def search_products(
    db: Session,
    query: str,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    in_stock_only: bool = False,
    limit: int = 5,
) -> dict:
    """
    Search for products by name or brand. Optionally filter by category,
    price range, and stock availability.
    Returns stock level, price, discount, and rating for each result.
    """
    safe_q = query.replace("%", "\\%").replace("_", "\\_")
    q = db.query(Product).filter(
        Product.is_active == True,
        (Product.name.ilike(f"%{safe_q}%", escape="\\")) |
        (Product.brand.ilike(f"%{safe_q}%", escape="\\")) |
        (Product.category.ilike(f"%{safe_q}%", escape="\\"))
    )
    if category:
        q = q.filter(Product.category == category)
    if min_price is not None:
        q = q.filter(Product.price >= min_price)
    if max_price is not None:
        q = q.filter(Product.price <= max_price)
    if in_stock_only:
        q = q.filter(Product.inventory_count > 0)

    total   = q.count()
    results = q.order_by(Product.rating_avg.desc().nulls_last()).limit(limit).all()

    return {
        "query":       query,
        "total_found": total,
        "showing":     len(results),
        "products": [
            {
                "product_id":   p.id,
                "name":         p.name,
                "category":     p.category,
                "subcategory":  p.subcategory,
                "brand":        p.brand,
                "price":        p.price,
                "discount_pct": p.discount_pct,
                "effective_price": round(p.price * (1 - (p.discount_pct or 0) / 100), 2),
                "stock":        p.inventory_count,
                "stock_health": _stock_health(p.inventory_count),
                "rating_avg":   p.rating_avg,
                "rating_count": p.rating_count,
            }
            for p in results
        ],
    }


def check_product_stock(db: Session, product_id: str) -> dict:
    """
    Get current stock level, health status, and any active low-stock alert
    for a specific product.
    """
    product = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()

    if not product:
        return {"found": False, "product_id": product_id,
                "message": "Product not found or inactive."}

    alert = db.query(InventoryAlert).filter(
        InventoryAlert.product_id == product_id,
        InventoryAlert.status.in_(["open", "acknowledged"]),
    ).first()

    return {
        "found": True,
        "product_id":    product.id,
        "name":          product.name,
        "category":      product.category,
        "subcategory":   product.subcategory,
        "brand":         product.brand,
        "price":         product.price,
        "discount_pct":  product.discount_pct,
        "effective_price": round(product.price * (1 - (product.discount_pct or 0) / 100), 2),
        "stock":         product.inventory_count,
        "stock_health":  _stock_health(product.inventory_count),
        "rating_avg":    product.rating_avg,
        "description":   (product.description or "")[:300],
        "alert": {
            "severity": alert.severity,
            "threshold": alert.threshold,
            "status":   alert.status,
        } if alert else None,
        "availability_message": (
            "In stock — available for purchase"       if product.inventory_count > 20 else
            f"Low stock — only {product.inventory_count} left" if product.inventory_count > 0 else
            "Currently out of stock"
        ),
    }


def get_category_summary(db: Session, category: str) -> dict:
    """
    Get a stock health overview for all products in a category.
    Useful for operations teams checking category-level inventory.
    """
    products = db.query(Product).filter(
        Product.is_active == True,
        Product.category == category,
    ).all()

    if not products:
        sql = text("""
            SELECT DISTINCT category FROM products
            WHERE is_active = true AND category ILIKE :cat
            LIMIT 5
        """)
        suggestions = [r[0] for r in db.execute(sql, {"cat": f"%{category}%"}).fetchall()]
        return {
            "found": False,
            "category": category,
            "message": f"Category '{category}' not found.",
            "did_you_mean": suggestions,
        }

    out_of_stock = sum(1 for p in products if p.inventory_count == 0)
    critical     = sum(1 for p in products if 1 <= p.inventory_count <= 5)
    low          = sum(1 for p in products if 6 <= p.inventory_count <= 20)
    healthy      = sum(1 for p in products if p.inventory_count > 20)

    open_alerts = db.query(InventoryAlert).filter(
        InventoryAlert.category == category,
        InventoryAlert.status == "open",
    ).count()

    # Subcategory breakdown
    subcat_counts: dict = {}
    for p in products:
        subcat_counts[p.subcategory] = subcat_counts.get(p.subcategory, 0) + 1

    worst_stock = sorted(
        [p for p in products if p.inventory_count <= 5],
        key=lambda p: p.inventory_count
    )[:5]

    return {
        "found": True,
        "category":       category,
        "total_products": len(products),
        "stock_health": {
            "healthy":      healthy,
            "low":          low,
            "critical":     critical,
            "out_of_stock": out_of_stock,
        },
        "open_alerts": open_alerts,
        "subcategories": subcat_counts,
        "critical_products": [
            {
                "name":   p.name,
                "brand":  p.brand,
                "stock":  p.inventory_count,
                "health": _stock_health(p.inventory_count),
            }
            for p in worst_stock
        ],
    }
