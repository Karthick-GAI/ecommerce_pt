from datetime import datetime
from models import AlertRule, Alert


def check_and_create_alerts(db, product_id: str, product_name: str,
                             category: str, brand: str, current_stock: int):
    """
    Evaluate active rules against current_stock and create/update/auto-resolve alerts.
    Rule priority: product-specific > category > global (most restrictive global wins).
    Called after every inventory write — caller must commit.
    """
    # 1. Product-specific rule (highest priority)
    rule = db.query(AlertRule).filter(
        AlertRule.is_active     == True,
        AlertRule.rule_type     == "product",
        AlertRule.target_id     == product_id,
    ).first()

    # 2. Category rule
    if not rule:
        rule = db.query(AlertRule).filter(
            AlertRule.is_active  == True,
            AlertRule.rule_type  == "category",
            AlertRule.target_id  == category,
        ).first()

    # 3. Global rules — smallest threshold that still fires (most restrictive)
    if not rule:
        rule = (
            db.query(AlertRule)
            .filter(
                AlertRule.is_active       == True,
                AlertRule.rule_type       == "global",
                AlertRule.threshold_value >= current_stock,
            )
            .order_by(AlertRule.threshold_value)   # ascending → most restrictive first
            .first()
        )

    existing = db.query(Alert).filter(
        Alert.product_id == product_id,
        Alert.status.in_(["open", "acknowledged"]),
    ).first()

    if rule and current_stock <= rule.threshold_value:
        if existing:
            existing.current_stock = current_stock
            existing.severity      = rule.alert_severity
            existing.threshold     = rule.threshold_value
            existing.updated_at    = datetime.utcnow()
        else:
            db.add(Alert(
                product_id   = product_id,
                product_name = product_name,
                category     = category,
                brand        = brand,
                current_stock= current_stock,
                threshold    = rule.threshold_value,
                severity     = rule.alert_severity,
                rule_id      = rule.id,
            ))
    elif existing:
        # Stock restored above all thresholds — auto-resolve
        existing.status      = "resolved"
        existing.resolved_at = datetime.utcnow()
        existing.updated_at  = datetime.utcnow()


def stock_health(count: int) -> str:
    if count == 0:
        return "out_of_stock"
    if count <= 5:
        return "critical"
    if count <= 20:
        return "low"
    return "healthy"


def seed_default_rules(db):
    """Insert the three baseline global thresholds if no rules exist."""
    if db.query(AlertRule).count() > 0:
        return
    db.add_all([
        AlertRule(
            rule_type="global", target_id="*",
            label="Out of Stock",
            threshold_value=0, alert_severity="critical",
        ),
        AlertRule(
            rule_type="global", target_id="*",
            label="Critical Stock (≤5 units)",
            threshold_value=5, alert_severity="critical",
        ),
        AlertRule(
            rule_type="global", target_id="*",
            label="Low Stock (≤20 units)",
            threshold_value=20, alert_severity="warning",
        ),
    ])
    db.commit()
    print("[inventory] Default alert rules seeded.")


def run_initial_alert_scan(db):
    """
    On startup, generate alerts for all products already below threshold.
    Skips products that already have an open alert.
    """
    from sqlalchemy import func
    max_threshold = (
        db.query(func.max(AlertRule.threshold_value))
        .filter(AlertRule.rule_type == "global", AlertRule.is_active == True)
        .scalar()
    ) or 20

    from models import Product
    products = (
        db.query(Product)
        .filter(Product.is_active == True, Product.inventory_count <= max_threshold)
        .all()
    )

    for p in products:
        existing = db.query(Alert).filter(
            Alert.product_id == p.id,
            Alert.status.in_(["open", "acknowledged"]),
        ).first()
        if not existing:
            check_and_create_alerts(db, p.id, p.name, p.category, p.brand, p.inventory_count)

    db.commit()
    open_count = db.query(Alert).filter(Alert.status == "open").count()
    print(f"[inventory] Initial scan complete — {open_count} open alerts.")
