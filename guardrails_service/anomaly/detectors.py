"""
Anomaly detectors.

Each detector function:
  - Accepts a SQLAlchemy session and optional parameters
  - Queries shared tables (read-only access)
  - Returns a list of AnomalyAlert ORM objects (NOT yet committed)

Callers commit after collecting results from multiple detectors.

Statistical methods used:
  - Z-score for amount anomalies (3σ / 4σ rule)
  - IQR for robust outlier detection on small datasets
  - Rate windows for velocity anomalies
  - Pattern matching for injection anomalies
"""
import os
import re
import math
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from models import (
    SearchLog, CheckoutOrder, BrowsingEvent, Product,
    PayTransaction, PayOrder, AnomalyAlert,
)
from validators.security import _COMPILED_SQL, _COMPILED_XSS


# ── Thresholds from environment ───────────────────────────────────────────────

ORDER_RATE_WINDOW  = int(os.getenv("ORDER_RATE_WINDOW_MINUTES", "60"))
ORDER_RATE_MAX     = int(os.getenv("ORDER_RATE_MAX", "10"))
PAYMENT_FAIL_WINDOW = int(os.getenv("PAYMENT_FAILURE_WINDOW_HOURS", "24"))
PAYMENT_FAIL_MAX   = int(os.getenv("PAYMENT_FAILURE_MAX", "3"))
ZSCORE_THRESHOLD   = float(os.getenv("AMOUNT_ZSCORE_THRESHOLD", "4.0"))
SEARCH_SCAN_HOURS  = int(os.getenv("SEARCH_INJECTION_SCAN_HOURS", "24"))
MAX_DISCOUNT       = float(os.getenv("MAX_DISCOUNT_PCT", "95.0"))
MIN_PRICE          = float(os.getenv("INVENTORY_MIN_PRICE", "1.0"))


# ── Statistics helpers ────────────────────────────────────────────────────────

def _mean_std(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    return mean, math.sqrt(variance)


def _iqr_bounds(values: list[float]) -> tuple[float, float]:
    """Return (lower, upper) bounds using 1.5×IQR rule."""
    if len(values) < 4:
        return float("-inf"), float("inf")
    s = sorted(values)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def _zscore(value: float, mean: float, std: float) -> float:
    return (value - mean) / std if std > 0 else 0.0


def _risk_from_zscore(z: float) -> int:
    """Map Z-score to risk score 0-100."""
    if z < 3:   return 0
    if z < 4:   return 30
    if z < 5:   return 55
    if z < 6:   return 75
    return 90


def _severity_from_risk(score: int) -> str:
    if score >= 75: return "critical"
    if score >= 55: return "high"
    if score >= 30: return "medium"
    return "low"


# ── 1. Order amount anomalies ─────────────────────────────────────────────────

def detect_order_amount_anomalies(db: Session, lookback_days: int = 90) -> list[AnomalyAlert]:
    """
    Compares each recent order's total to the historical distribution.
    Uses Z-score with a fallback to IQR for datasets < 30 rows.
    Only scans orders from the last 7 days.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    recent_cutoff = now - timedelta(days=7)

    # Historical baseline
    hist_rows = db.query(CheckoutOrder.total).filter(
        CheckoutOrder.total != None,
        CheckoutOrder.total > 0,
        CheckoutOrder.created_at >= cutoff,
        CheckoutOrder.created_at <  recent_cutoff,
    ).all()
    baseline = [r.total for r in hist_rows if r.total]

    # Current window to check
    check_rows = db.query(CheckoutOrder).filter(
        CheckoutOrder.total != None,
        CheckoutOrder.total > 0,
        CheckoutOrder.created_at >= recent_cutoff,
    ).all()

    if not check_rows:
        return []

    alerts = []

    if len(baseline) >= 30:
        mean, std = _mean_std(baseline)
        for order in check_rows:
            z = _zscore(order.total, mean, std)
            if abs(z) >= ZSCORE_THRESHOLD:
                risk = _risk_from_zscore(abs(z))
                alerts.append(AnomalyAlert(
                    anomaly_type = "order_amount",
                    entity_type  = "order",
                    entity_id    = order.id,
                    severity     = _severity_from_risk(risk),
                    title        = f"Unusual order amount: ₹{order.total:,.2f}",
                    description  = (
                        f"Order total ₹{order.total:,.2f} is {abs(z):.1f}σ away from "
                        f"historical mean ₹{mean:,.2f} (σ=₹{std:,.2f})."
                    ),
                    evidence     = {
                        "order_id":   order.id,
                        "amount":     order.total,
                        "z_score":    round(z, 2),
                        "hist_mean":  round(mean, 2),
                        "hist_std":   round(std, 2),
                        "sample_n":   len(baseline),
                    },
                    risk_score   = risk,
                    rule_name    = "amount_zscore",
                ))
    elif len(baseline) >= 4:
        lo, hi = _iqr_bounds(baseline)
        for order in check_rows:
            if order.total < lo or order.total > hi:
                risk = 40
                alerts.append(AnomalyAlert(
                    anomaly_type = "order_amount",
                    entity_type  = "order",
                    entity_id    = order.id,
                    severity     = "medium",
                    title        = f"Order amount outside expected range: ₹{order.total:,.2f}",
                    description  = (
                        f"Order total ₹{order.total:,.2f} is outside IQR bounds "
                        f"[₹{lo:,.2f}, ₹{hi:,.2f}]."
                    ),
                    evidence     = {
                        "order_id": order.id,
                        "amount":   order.total,
                        "iqr_low":  round(lo, 2),
                        "iqr_high": round(hi, 2),
                    },
                    risk_score   = risk,
                    rule_name    = "amount_iqr",
                ))

    return alerts


# ── 2. Rapid-fire ordering ────────────────────────────────────────────────────

def detect_rapid_ordering(db: Session) -> list[AnomalyAlert]:
    """
    Customers who placed more than ORDER_RATE_MAX orders in ORDER_RATE_WINDOW minutes.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=ORDER_RATE_WINDOW)

    rows = (
        db.query(CheckoutOrder.customer_id, func.count(CheckoutOrder.id).label("n"))
        .filter(
            CheckoutOrder.created_at >= cutoff,
            CheckoutOrder.customer_id != None,
        )
        .group_by(CheckoutOrder.customer_id)
        .having(func.count(CheckoutOrder.id) > ORDER_RATE_MAX)
        .all()
    )

    alerts = []
    for r in rows:
        excess = r.n - ORDER_RATE_MAX
        risk   = min(100, 40 + excess * 10)
        alerts.append(AnomalyAlert(
            anomaly_type = "rapid_ordering",
            entity_type  = "customer",
            entity_id    = r.customer_id,
            severity     = _severity_from_risk(risk),
            title        = f"Rapid-fire ordering: {r.n} orders in {ORDER_RATE_WINDOW} minutes",
            description  = (
                f"Customer placed {r.n} orders in a {ORDER_RATE_WINDOW}-minute window "
                f"(limit: {ORDER_RATE_MAX}). Possible bot or card testing."
            ),
            evidence     = {
                "customer_id":   r.customer_id,
                "order_count":   r.n,
                "window_minutes": ORDER_RATE_WINDOW,
                "threshold":     ORDER_RATE_MAX,
            },
            risk_score   = risk,
            rule_name    = "order_rate_limit",
        ))
    return alerts


# ── 3. Payment failure spree ──────────────────────────────────────────────────

def detect_payment_failure_spree(db: Session) -> list[AnomalyAlert]:
    """
    Customers with ≥ PAYMENT_FAIL_MAX failed transactions in the last PAYMENT_FAIL_WINDOW hours.
    Indicates potential card testing or stolen-card attacks.
    """
    try:
        db.execute(text("SELECT 1 FROM pay_transactions LIMIT 1"))
    except Exception:
        return []   # pay_transactions table not yet created

    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=PAYMENT_FAIL_WINDOW)

    rows = (
        db.query(PayTransaction.customer_id, func.count(PayTransaction.id).label("n"))
        .filter(
            PayTransaction.status == "failed",
            PayTransaction.created_at >= cutoff,
            PayTransaction.customer_id != None,
        )
        .group_by(PayTransaction.customer_id)
        .having(func.count(PayTransaction.id) >= PAYMENT_FAIL_MAX)
        .all()
    )

    alerts = []
    for r in rows:
        risk = min(100, 35 + r.n * 12)
        alerts.append(AnomalyAlert(
            anomaly_type = "payment_failure",
            entity_type  = "customer",
            entity_id    = r.customer_id,
            severity     = _severity_from_risk(risk),
            title        = f"Multiple payment failures: {r.n} in {PAYMENT_FAIL_WINDOW}h",
            description  = (
                f"Customer had {r.n} failed payment transactions in {PAYMENT_FAIL_WINDOW} hours "
                f"(threshold: {PAYMENT_FAIL_MAX}). Possible card testing or stolen cards."
            ),
            evidence     = {
                "customer_id":   r.customer_id,
                "failure_count": r.n,
                "window_hours":  PAYMENT_FAIL_WINDOW,
                "threshold":     PAYMENT_FAIL_MAX,
            },
            risk_score   = risk,
            rule_name    = "payment_failure_limit",
        ))
    return alerts


# ── 4. Search injection patterns ─────────────────────────────────────────────

def detect_search_injection(db: Session) -> list[AnomalyAlert]:
    """
    Scans recent search_logs for SQL injection and XSS patterns.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=SEARCH_SCAN_HOURS)

    rows = db.query(SearchLog).filter(
        SearchLog.created_at >= cutoff,
        SearchLog.query != None,
    ).all()

    alerts = []
    for row in rows:
        q = row.query or ""
        for pattern, sev, msg in _COMPILED_SQL:
            m = pattern.search(q)
            if m:
                risk = {"critical": 90, "high": 70, "medium": 50, "low": 30}.get(sev, 50)
                alerts.append(AnomalyAlert(
                    anomaly_type = "search_injection",
                    entity_type  = "customer",
                    entity_id    = row.user_id or "anonymous",
                    severity     = sev,
                    title        = f"SQL injection attempt in search query",
                    description  = f"{msg}. Query: «{q[:200]}»",
                    evidence     = {
                        "log_id":    row.id,
                        "query":     q[:500],
                        "pattern":   msg,
                        "user_id":   row.user_id,
                        "timestamp": str(row.created_at),
                    },
                    risk_score   = risk,
                    rule_name    = "sql_injection",
                ))
                break

        for pattern, sev, msg in _COMPILED_XSS:
            m = pattern.search(q)
            if m:
                risk = {"critical": 85, "high": 65, "medium": 45, "low": 25}.get(sev, 45)
                alerts.append(AnomalyAlert(
                    anomaly_type = "search_injection",
                    entity_type  = "customer",
                    entity_id    = row.user_id or "anonymous",
                    severity     = sev,
                    title        = f"XSS attempt in search query",
                    description  = f"{msg}. Query: «{q[:200]}»",
                    evidence     = {
                        "log_id":  row.id,
                        "query":   q[:500],
                        "pattern": msg,
                        "user_id": row.user_id,
                    },
                    risk_score   = risk,
                    rule_name    = "xss_injection",
                ))
                break

    return alerts


# ── 5. Inventory / product anomalies ─────────────────────────────────────────

def detect_inventory_anomalies(db: Session) -> list[AnomalyAlert]:
    """
    Flags products with:
      - price ≤ MIN_PRICE (near-zero pricing)
      - discount_pct ≥ MAX_DISCOUNT (suspicious extreme discounts)
      - negative inventory_count (data integrity issue)
    """
    alerts = []

    # Near-zero price
    zero_price = db.query(Product).filter(
        Product.is_active == True,
        Product.price <= MIN_PRICE,
        Product.price > 0,
    ).all()
    for p in zero_price:
        alerts.append(AnomalyAlert(
            anomaly_type = "inventory_price",
            entity_type  = "product",
            entity_id    = p.id,
            severity     = "high",
            title        = f"Suspiciously low price: ₹{p.price} for '{p.name}'",
            description  = f"Product '{p.name}' ({p.category}) is priced at ₹{p.price:.2f}, "
                           f"which is at or below the minimum threshold of ₹{MIN_PRICE}.",
            evidence     = {"product_id": p.id, "name": p.name, "price": p.price,
                            "category": p.category},
            risk_score   = 65,
            rule_name    = "inventory_price",
        ))

    # Extreme discount
    extreme_discount = db.query(Product).filter(
        Product.is_active == True,
        Product.discount_pct >= MAX_DISCOUNT,
    ).all()
    for p in extreme_discount:
        alerts.append(AnomalyAlert(
            anomaly_type = "inventory_price",
            entity_type  = "product",
            entity_id    = p.id,
            severity     = "high",
            title        = f"Extreme discount: {p.discount_pct:.0f}% off for '{p.name}'",
            description  = f"Product '{p.name}' has a {p.discount_pct:.0f}% discount, "
                           f"exceeding the {MAX_DISCOUNT:.0f}% threshold.",
            evidence     = {"product_id": p.id, "name": p.name,
                            "price": p.price, "discount_pct": p.discount_pct},
            risk_score   = 60,
            rule_name    = "inventory_discount",
        ))

    # Negative inventory
    negative_stock = db.query(Product).filter(
        Product.is_active == True,
        Product.inventory_count < 0,
    ).all()
    for p in negative_stock:
        alerts.append(AnomalyAlert(
            anomaly_type = "inventory_stock",
            entity_type  = "product",
            entity_id    = p.id,
            severity     = "medium",
            title        = f"Negative inventory: {p.inventory_count} units for '{p.name}'",
            description  = f"Product '{p.name}' has negative inventory ({p.inventory_count}), "
                           f"indicating a data integrity issue.",
            evidence     = {"product_id": p.id, "name": p.name,
                            "inventory_count": p.inventory_count},
            risk_score   = 45,
            rule_name    = "negative_stock",
        ))

    return alerts


# ── 6. Bot / scraping behavior ────────────────────────────────────────────────

def detect_bot_behavior(db: Session) -> list[AnomalyAlert]:
    """
    Detects users with extremely high search volume in a short window — likely automated scraping.
    Threshold: > 100 searches in 1 hour.
    """
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)

    rows = (
        db.query(SearchLog.user_id, func.count(SearchLog.id).label("n"))
        .filter(
            SearchLog.created_at >= cutoff,
            SearchLog.user_id    != None,
        )
        .group_by(SearchLog.user_id)
        .having(func.count(SearchLog.id) > 100)
        .all()
    )

    alerts = []
    for r in rows:
        risk = min(100, 40 + (r.n - 100) // 10)
        alerts.append(AnomalyAlert(
            anomaly_type = "bot_behavior",
            entity_type  = "customer",
            entity_id    = r.user_id,
            severity     = _severity_from_risk(risk),
            title        = f"Possible bot / scraping: {r.n} searches in 1 hour",
            description  = (
                f"User made {r.n} search queries in the last hour. "
                f"Normal human rate is < 100/hour."
            ),
            evidence     = {"user_id": r.user_id, "search_count": r.n, "window": "1 hour"},
            risk_score   = risk,
            rule_name    = "search_rate_limit",
        ))
    return alerts


# ── 7. Bulk single-item purchase ──────────────────────────────────────────────

def detect_bulk_purchases(db: Session) -> list[AnomalyAlert]:
    """
    Scans dataset orders for items with unusually high single-item quantities.
    Uses JSONB lateral join on cart_activity.
    """
    try:
        rows = db.execute(text("""
            SELECT o.order_id, o.user_id, item.product_id,
                   item.quantity, item.unit_price
            FROM orders o,
            LATERAL jsonb_to_recordset(o.cart_activity)
                AS item(product_id text, quantity int, unit_price float)
            WHERE item.quantity > 50
              AND o.created_at >= NOW() - INTERVAL '7 days'
            LIMIT 200
        """)).fetchall()
    except Exception:
        return []

    alerts = []
    for r in rows:
        risk = min(100, 30 + (r.quantity - 50) // 5)
        alerts.append(AnomalyAlert(
            anomaly_type = "bulk_purchase",
            entity_type  = "order",
            entity_id    = r.order_id,
            severity     = _severity_from_risk(risk),
            title        = f"Bulk purchase: {r.quantity} units of product {r.product_id}",
            description  = (
                f"Order {r.order_id} contains {r.quantity} units of a single product, "
                f"which exceeds the expected threshold of 50."
            ),
            evidence     = {
                "order_id":   r.order_id,
                "user_id":    r.user_id,
                "product_id": r.product_id,
                "quantity":   r.quantity,
                "unit_price": r.unit_price,
            },
            risk_score   = risk,
            rule_name    = "bulk_order",
        ))
    return alerts


# ── 8. Duplicate / replay payment ────────────────────────────────────────────

def detect_payment_replay(db: Session) -> list[AnomalyAlert]:
    """
    Detects provider_payment_id values that appear more than once in pay_transactions.
    A repeated payment ID suggests a replay attack.
    """
    try:
        db.execute(text("SELECT 1 FROM pay_transactions LIMIT 1"))
    except Exception:
        return []

    rows = (
        db.query(PayTransaction.provider_payment_id, func.count(PayTransaction.id).label("n"))
        .filter(
            PayTransaction.provider_payment_id != None,
            PayTransaction.status == "captured",
        )
        .group_by(PayTransaction.provider_payment_id)
        .having(func.count(PayTransaction.id) > 1)
        .all()
    )

    alerts = []
    for r in rows:
        alerts.append(AnomalyAlert(
            anomaly_type = "replay_attack",
            entity_type  = "payment",
            entity_id    = r.provider_payment_id,
            severity     = "critical",
            title        = f"Payment replay: {r.provider_payment_id} captured {r.n} times",
            description  = (
                f"Payment ID {r.provider_payment_id} appears {r.n} times with status=captured. "
                f"This indicates a possible replay attack — the same payment is being applied "
                f"to multiple orders."
            ),
            evidence     = {
                "provider_payment_id": r.provider_payment_id,
                "capture_count":       r.n,
            },
            risk_score   = 95,
            rule_name    = "replay_attack",
        ))
    return alerts


# ── Deduplication helper ──────────────────────────────────────────────────────

def dedupe_alerts(
    new_alerts: list[AnomalyAlert],
    db: Session,
    lookback_hours: int = 24,
) -> list[AnomalyAlert]:
    """
    Filter out alerts for (entity_id, anomaly_type) pairs that already
    have an open alert in the last lookback_hours. Prevents alert storms.
    """
    if not new_alerts:
        return []

    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    existing = db.query(AnomalyAlert.entity_id, AnomalyAlert.anomaly_type).filter(
        AnomalyAlert.status.in_(("open", "acknowledged")),
        AnomalyAlert.detected_at >= cutoff,
    ).all()
    existing_keys = {(r.entity_id, r.anomaly_type) for r in existing}

    return [
        a for a in new_alerts
        if (a.entity_id, a.anomaly_type) not in existing_keys
    ]
