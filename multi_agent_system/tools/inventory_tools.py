"""Inventory status, demand forecasting, and restock tools for the Inventory Planning Agent."""
import json
import math
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from models import InventoryForecast
from tools.shared_models import Product, InventoryMovement, InventoryAlert

_LEAD_TIME_DAYS      = 7    # supplier lead time assumption
_SAFETY_STOCK_WEEKS  = 1.5  # weeks of safety stock
_HOLDING_COST_RATE   = 0.25  # 25% of product value per year (for EOQ)
_ORDERING_COST       = 500   # ₹500 per order placed


def _stock_health(count: int) -> str:
    if count == 0:
        return "out_of_stock"
    if count <= 5:
        return "critical"
    if count <= 20:
        return "low"
    return "healthy"


def get_inventory_dashboard(db: Session) -> str:
    try:
        summary = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE inventory_count = 0)     AS out_of_stock,
                COUNT(*) FILTER (WHERE inventory_count BETWEEN 1 AND 5)  AS critical,
                COUNT(*) FILTER (WHERE inventory_count BETWEEN 6 AND 20) AS low,
                COUNT(*) FILTER (WHERE inventory_count > 20)    AS healthy,
                COUNT(*)                                         AS total_active,
                SUM(inventory_count)                            AS total_units,
                AVG(inventory_count)                            AS avg_units
            FROM products
            WHERE is_active = true
        """)).fetchone()

        open_alerts = db.execute(text("""
            SELECT COUNT(*) AS cnt FROM alerts WHERE is_resolved = false
        """)).fetchone()

        by_category = db.execute(text("""
            SELECT category,
                   COUNT(*) AS total_skus,
                   SUM(inventory_count) AS total_units,
                   COUNT(*) FILTER (WHERE inventory_count = 0) AS out_of_stock_skus
            FROM products
            WHERE is_active = true
            GROUP BY category
            ORDER BY out_of_stock_skus DESC, total_units ASC
            LIMIT 10
        """)).fetchall()

        return json.dumps({
            "stock_health": {
                "out_of_stock": summary.out_of_stock,
                "critical":     summary.critical,
                "low":          summary.low,
                "healthy":      summary.healthy,
                "total_active": summary.total_active,
                "total_units":  summary.total_units,
                "avg_units_per_sku": round(float(summary.avg_units or 0), 1),
            },
            "open_alerts": open_alerts.cnt,
            "by_category": [
                {
                    "category":        r.category,
                    "total_skus":      r.total_skus,
                    "total_units":     r.total_units,
                    "out_of_stock_skus": r.out_of_stock_skus,
                }
                for r in by_category
            ],
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_low_stock_products(db: Session, severity: str = None, limit: int = 20) -> str:
    q = db.query(Product).filter(Product.is_active == True)

    if severity == "out_of_stock":
        q = q.filter(Product.inventory_count == 0)
    elif severity == "critical":
        q = q.filter(Product.inventory_count.between(1, 5))
    elif severity == "low":
        q = q.filter(Product.inventory_count.between(6, 20))
    else:
        q = q.filter(Product.inventory_count <= 20)

    products = q.order_by(Product.inventory_count.asc()).limit(min(limit, 50)).all()

    return json.dumps({
        "products": [
            {
                "product_id":   p.id,
                "name":         p.name,
                "brand":        p.brand,
                "category":     p.category,
                "stock_count":  p.inventory_count,
                "stock_health": _stock_health(p.inventory_count),
                "price":        p.price,
            }
            for p in products
        ],
        "count":    len(products),
        "severity": severity or "all",
    })


def get_stock_movements(product_id: str, db: Session, days: int = 30) -> str:
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        return json.dumps({"error": f"Product {product_id} not found."})

    since = datetime.now(timezone.utc) - timedelta(days=days)
    movements = (
        db.query(InventoryMovement)
        .filter(
            InventoryMovement.product_id == product_id,
            InventoryMovement.created_at >= since,
        )
        .order_by(InventoryMovement.created_at.desc())
        .limit(50)
        .all()
    )

    return json.dumps({
        "product_id":     product_id,
        "product_name":   p.name,
        "current_stock":  p.inventory_count,
        "stock_health":   _stock_health(p.inventory_count),
        "period_days":    days,
        "movements": [
            {
                "type":     m.movement_type,
                "change":   m.quantity_change,
                "before":   m.quantity_before,
                "after":    m.quantity_after,
                "reason":   m.reason,
                "operator": m.performed_by,
                "at":       str(m.created_at),
            }
            for m in movements
        ],
    })


def forecast_demand(product_id: str, db: Session, horizon_days: int = 30) -> str:
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        return json.dumps({"error": f"Product {product_id} not found."})

    # Get daily sales over last 90 days
    try:
        rows = db.execute(text("""
            SELECT DATE(o.created_at) AS sale_date,
                   SUM(oi.quantity)   AS units_sold
            FROM checkout_order_items oi
            JOIN checkout_orders o ON o.id = oi.order_id
            WHERE oi.product_id = :pid
              AND o.created_at >= NOW() - INTERVAL '90 days'
              AND o.status NOT IN ('cancelled', 'payment_failed')
            GROUP BY DATE(o.created_at)
            ORDER BY sale_date
        """), {"pid": product_id}).fetchall()
    except Exception:
        rows = []

    if not rows:
        # No sales data — use conservative estimate
        avg_daily     = 0.0
        trend         = "stable"
        confidence    = 0.2
    else:
        daily_sales  = [float(r.units_sold) for r in rows]
        n            = len(daily_sales)
        avg_daily    = sum(daily_sales) / n

        # Trend: compare last 30 vs first 30 days
        if n >= 10:
            first_half  = daily_sales[:n // 2]
            second_half = daily_sales[n // 2:]
            avg_first   = sum(first_half) / len(first_half)
            avg_second  = sum(second_half) / len(second_half)
            if avg_first == 0:
                trend = "stable"
            elif (avg_second - avg_first) / avg_first > 0.15:
                trend = "rising"
            elif (avg_first - avg_second) / avg_first > 0.15:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Variance-based confidence
        variance  = sum((x - avg_daily) ** 2 for x in daily_sales) / n
        cv        = math.sqrt(variance) / max(avg_daily, 0.01)  # coefficient of variation
        confidence = max(0.3, min(0.95, 1.0 - min(cv, 1.0)))

    # Apply trend adjustment for forecast
    trend_multiplier = {"rising": 1.15, "stable": 1.0, "falling": 0.90}[trend]
    adjusted_daily   = avg_daily * trend_multiplier
    predicted        = round(adjusted_daily * horizon_days, 1)

    current_stock    = p.inventory_count or 0
    safety_stock     = round(adjusted_daily * _LEAD_TIME_DAYS * _SAFETY_STOCK_WEEKS)
    reorder_point    = round(adjusted_daily * _LEAD_TIME_DAYS + safety_stock)
    days_until_out   = round(current_stock / adjusted_daily, 1) if adjusted_daily > 0 else None

    # EOQ calculation
    annual_demand    = adjusted_daily * 365
    eoq = (
        round(math.sqrt(2 * annual_demand * _ORDERING_COST / (p.price * _HOLDING_COST_RATE)))
        if annual_demand > 0 and p.price > 0 else 0
    )
    recommended_qty  = max(eoq, reorder_point, 10)

    # Persist forecast
    forecast = InventoryForecast(
        product_id              = product_id,
        product_name            = p.name,
        forecast_horizon_days   = horizon_days,
        avg_daily_demand        = round(avg_daily, 3),
        predicted_demand        = predicted,
        current_stock           = current_stock,
        reorder_point           = reorder_point,
        recommended_restock_qty = recommended_qty,
        days_until_stockout     = days_until_out,
        confidence_score        = round(confidence, 2),
        trend                   = trend,
    )
    db.add(forecast)
    db.commit()

    return json.dumps({
        "product_id":            product_id,
        "product_name":          p.name,
        "current_stock":         current_stock,
        "forecast": {
            "horizon_days":          horizon_days,
            "avg_daily_demand":      round(avg_daily, 2),
            "predicted_demand":      predicted,
            "trend":                 trend,
            "confidence":            round(confidence, 2),
        },
        "reorder_signals": {
            "reorder_point":         reorder_point,
            "safety_stock":          safety_stock,
            "days_until_stockout":   days_until_out,
            "action_required":       current_stock <= reorder_point,
        },
        "recommendation": {
            "restock_qty":           recommended_qty,
            "eoq":                   eoq,
            "rationale": (
                f"Based on {round(avg_daily, 2)} units/day avg demand ({trend} trend), "
                f"EOQ={eoq}, lead time={_LEAD_TIME_DAYS} days."
            ),
        },
    })


def get_restock_recommendations(db: Session, top_n: int = 20) -> str:
    try:
        rows = db.execute(text("""
            WITH daily_sales AS (
                SELECT oi.product_id,
                       SUM(oi.quantity)::float / 30.0 AS avg_daily
                FROM checkout_order_items oi
                JOIN checkout_orders o ON o.id = oi.order_id
                WHERE o.created_at >= NOW() - INTERVAL '30 days'
                  AND o.status NOT IN ('cancelled', 'payment_failed')
                GROUP BY oi.product_id
            )
            SELECT p.id, p.name, p.brand, p.category, p.price,
                   p.inventory_count,
                   COALESCE(ds.avg_daily, 0) AS avg_daily_sales,
                   CASE
                       WHEN COALESCE(ds.avg_daily, 0) > 0
                       THEN p.inventory_count / ds.avg_daily
                       ELSE NULL
                   END AS days_of_stock
            FROM products p
            LEFT JOIN daily_sales ds ON ds.product_id = p.id
            WHERE p.is_active = true AND p.inventory_count <= 20
            ORDER BY days_of_stock ASC NULLS FIRST, p.inventory_count ASC
            LIMIT :top_n
        """), {"top_n": min(top_n, 50)}).fetchall()

        recommendations = []
        for r in rows:
            avg_d   = float(r.avg_daily_sales or 0)
            safety  = round(avg_d * _LEAD_TIME_DAYS * 1.5)
            eoq     = (
                round(math.sqrt(2 * avg_d * 365 * _ORDERING_COST / max(r.price * _HOLDING_COST_RATE, 1)))
                if avg_d > 0 and r.price else 0
            )
            restock = max(eoq, safety, 10)

            recommendations.append({
                "product_id":       r.id,
                "name":             r.name,
                "brand":            r.brand,
                "category":         r.category,
                "current_stock":    r.inventory_count,
                "stock_health":     _stock_health(r.inventory_count),
                "avg_daily_sales":  round(avg_d, 2),
                "days_of_stock":    round(float(r.days_of_stock), 1) if r.days_of_stock else None,
                "recommended_restock_qty": restock,
                "urgency":          "immediate" if (r.inventory_count <= 5) else "soon",
            })

        return json.dumps({"recommendations": recommendations, "count": len(recommendations)})

    except Exception as e:
        return json.dumps({"error": str(e)})


def get_sales_velocity(db: Session, product_id: str = None, category: str = None, days: int = 30) -> str:
    params: dict = {"days": days}
    where = ["o.created_at >= NOW() - INTERVAL '1 day' * :days",
             "o.status NOT IN ('cancelled', 'payment_failed')"]

    if product_id:
        where.append("oi.product_id = :product_id")
        params["product_id"] = product_id
    if category:
        where.append("LOWER(p.category) = LOWER(:category)")
        params["category"] = category

    where_clause = " AND ".join(where)

    try:
        rows = db.execute(text(f"""
            SELECT p.id, p.name, p.category, p.brand,
                   SUM(oi.quantity) AS total_sold,
                   COUNT(DISTINCT o.id) AS order_count,
                   SUM(oi.quantity)::float / :days AS daily_velocity
            FROM checkout_order_items oi
            JOIN checkout_orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE {where_clause}
            GROUP BY p.id, p.name, p.category, p.brand
            ORDER BY total_sold DESC
            LIMIT 20
        """), params).fetchall()

        return json.dumps({
            "period_days": days,
            "products": [
                {
                    "product_id":     r.id,
                    "name":           r.name,
                    "category":       r.category,
                    "brand":          r.brand,
                    "total_sold":     r.total_sold,
                    "order_count":    r.order_count,
                    "daily_velocity": round(float(r.daily_velocity), 2),
                }
                for r in rows
            ],
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_open_inventory_alerts(db: Session) -> str:
    alerts = (
        db.query(InventoryAlert)
        .filter(InventoryAlert.is_resolved == False)
        .order_by(InventoryAlert.created_at.desc())
        .limit(50)
        .all()
    )

    return json.dumps({
        "alerts": [
            {
                "alert_id":        a.id,
                "product_id":      a.product_id,
                "type":            a.alert_type,
                "message":         a.message,
                "severity":        a.severity,
                "is_acknowledged": a.is_acknowledged,
                "created_at":      str(a.created_at),
            }
            for a in alerts
        ],
        "total_open": len(alerts),
    })


def acknowledge_alert(alert_id: str, db: Session) -> str:
    alert = db.query(InventoryAlert).filter(InventoryAlert.id == alert_id).first()
    if not alert:
        return json.dumps({"error": f"Alert {alert_id} not found."})

    alert.is_acknowledged = True
    db.commit()
    return json.dumps({"alert_id": alert_id, "status": "acknowledged"})
