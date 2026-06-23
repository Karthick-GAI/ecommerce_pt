"""
Guardrails & Anomaly Detection Service — port 8010

Provides:
  /validate/*     — synchronous input validation (text, orders, contacts, amounts)
  /anomaly/*      — anomaly detection scans and alert management
  /rules/*        — runtime-configurable validation rules
  /health         — health check
  /analytics/overview — platform-wide security metrics
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text

from database import engine, Base, SessionLocal
from models import GuardRule, ValidationLog, AnomalyAlert

from routes.validation_routes import router as validation_router
from routes.anomaly_routes    import router as anomaly_router
from routes.rule_routes       import router as rule_router


# ── Default rules seeded on startup ──────────────────────────────────────────

DEFAULT_RULES = [
    {
        "name":        "sql_injection",
        "description": "Detect SQL injection patterns in any text input",
        "target_type": "input",
        "rule_type":   "regex",
        "condition":   {"pattern": r"(?i)(union\s+select|;\s*drop\s+|1\s*=\s*1|xp_cmdshell)"},
        "action":      "block",
        "severity":    "critical",
    },
    {
        "name":        "xss_injection",
        "description": "Detect XSS attack patterns in user input",
        "target_type": "input",
        "rule_type":   "regex",
        "condition":   {"pattern": r"(?i)(<script|javascript:|onerror\s*=)"},
        "action":      "block",
        "severity":    "high",
    },
    {
        "name":        "path_traversal",
        "description": "Detect directory traversal attempts",
        "target_type": "input",
        "rule_type":   "regex",
        "condition":   {"pattern": r"(\.\./|%2e%2e%2f|etc/passwd)"},
        "action":      "block",
        "severity":    "high",
    },
    {
        "name":        "command_injection",
        "description": "Detect OS command injection patterns",
        "target_type": "input",
        "rule_type":   "regex",
        "condition":   {"pattern": r"(`[^`]+`|\$\([^)]+\)|;\s*bash\s)"},
        "action":      "block",
        "severity":    "critical",
    },
    {
        "name":        "order_rate_limit",
        "description": "Flag customers placing too many orders in a short window",
        "target_type": "order",
        "rule_type":   "rate_limit",
        "condition":   {"window_minutes": 60, "max_count": 10},
        "action":      "alert",
        "severity":    "high",
    },
    {
        "name":        "payment_failure_limit",
        "description": "Alert on customers with multiple payment failures (card testing)",
        "target_type": "payment",
        "rule_type":   "threshold",
        "condition":   {"field": "failure_count", "operator": ">=", "value": 3,
                        "window_hours": 24},
        "action":      "alert",
        "severity":    "high",
    },
    {
        "name":        "amount_zscore",
        "description": "Flag orders whose amount is a statistical outlier (Z-score ≥ 4σ)",
        "target_type": "order",
        "rule_type":   "zscore",
        "condition":   {"window_days": 90, "threshold": 4.0},
        "action":      "flag",
        "severity":    "medium",
    },
    {
        "name":        "search_query_length",
        "description": "Flag search queries longer than 500 characters",
        "target_type": "search",
        "rule_type":   "range",
        "condition":   {"field": "query_length", "max": 500},
        "action":      "flag",
        "severity":    "low",
    },
    {
        "name":        "bulk_order_qty",
        "description": "Flag orders containing more than 50 units of a single item",
        "target_type": "order",
        "rule_type":   "threshold",
        "condition":   {"field": "item_quantity", "operator": ">", "value": 50},
        "action":      "flag",
        "severity":    "medium",
    },
    {
        "name":        "inventory_discount",
        "description": "Alert on products with discount >= 95%",
        "target_type": "product",
        "rule_type":   "range",
        "condition":   {"field": "discount_pct", "max": 95},
        "action":      "alert",
        "severity":    "high",
    },
]


def _seed_rules(db):
    existing = {r.name for r in db.query(GuardRule.name).all()}
    added = 0
    for rule in DEFAULT_RULES:
        if rule["name"] not in existing:
            db.add(GuardRule(**rule))
            added += 1
    if added:
        db.commit()
        print(f"[guardrails] Seeded {added} default rule(s).")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _seed_rules(db)

        if os.getenv("STARTUP_SCAN", "true").lower() == "true":
            from anomaly.scanner import run_full_scan
            result = run_full_scan(db)
            print(f"[guardrails] Startup scan: {result['summary']}")
    finally:
        db.close()

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Guardrails & Anomaly Detection Service",
    description="Input validation, injection detection, and statistical anomaly scanning",
    version="1.0.0",
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(validation_router)
app.include_router(anomaly_router)
app.include_router(rule_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()

    return {
        "service": "guardrails_service",
        "port":    8010,
        "status":  "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
    }


# ── Analytics overview ────────────────────────────────────────────────────────

@app.get("/analytics/overview", tags=["Analytics"])
def analytics_overview():
    db = SessionLocal()
    try:
        now      = datetime.now(timezone.utc)
        day_ago  = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)

        # Validation stats
        total_validations = db.query(ValidationLog).count()
        blocked_24h = db.query(ValidationLog).filter(
            ValidationLog.action == "block",
            ValidationLog.created_at >= day_ago,
        ).count()
        flagged_24h = db.query(ValidationLog).filter(
            ValidationLog.action == "flag",
            ValidationLog.created_at >= day_ago,
        ).count()
        val_by_type = dict(
            db.query(ValidationLog.request_type, func.count(ValidationLog.id))
            .filter(ValidationLog.created_at >= day_ago)
            .group_by(ValidationLog.request_type)
            .all()
        )

        # Anomaly stats
        open_critical = db.query(AnomalyAlert).filter(
            AnomalyAlert.status   == "open",
            AnomalyAlert.severity == "critical",
        ).count()
        open_high = db.query(AnomalyAlert).filter(
            AnomalyAlert.status   == "open",
            AnomalyAlert.severity == "high",
        ).count()
        new_alerts_7d = db.query(AnomalyAlert).filter(
            AnomalyAlert.detected_at >= week_ago
        ).count()
        alert_by_type = dict(
            db.query(AnomalyAlert.anomaly_type, func.count(AnomalyAlert.id))
            .filter(AnomalyAlert.status == "open")
            .group_by(AnomalyAlert.anomaly_type)
            .all()
        )

        # Rule stats
        active_rules = db.query(GuardRule).filter(GuardRule.is_active == True).count()
        top_rule = db.query(GuardRule).order_by(GuardRule.trigger_count.desc()).first()

        return {
            "timestamp": str(now),
            "validation": {
                "total_requests":    total_validations,
                "blocked_last_24h":  blocked_24h,
                "flagged_last_24h":  flagged_24h,
                "by_type_last_24h":  val_by_type,
            },
            "anomalies": {
                "open_critical":     open_critical,
                "open_high":         open_high,
                "new_last_7d":       new_alerts_7d,
                "open_by_type":      alert_by_type,
            },
            "rules": {
                "active_rules":      active_rules,
                "top_triggered":     top_rule.name if top_rule else None,
                "top_trigger_count": top_rule.trigger_count if top_rule else 0,
            },
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
