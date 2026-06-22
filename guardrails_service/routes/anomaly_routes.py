"""
Anomaly detection routes.

POST /anomaly/scan              — trigger full or targeted scan
POST /anomaly/check/order       — on-demand check for a specific order
POST /anomaly/check/user        — on-demand check for a specific user
POST /anomaly/check/payment     — on-demand check for a customer's payment pattern
GET  /anomaly/alerts            — list all alerts (filterable)
GET  /anomaly/alerts/stats      — severity + type distribution
GET  /anomaly/alerts/{id}       — single alert
POST /anomaly/alerts/{id}/acknowledge — acknowledge an alert
POST /anomaly/alerts/{id}/resolve     — resolve an alert
POST /anomaly/alerts/{id}/false-positive — mark as false positive
"""
from datetime import datetime, timezone
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import AnomalyAlert, CheckoutOrder, PayTransaction
from schemas import (
    CheckOrderRequest, CheckUserRequest, CheckPaymentRequest,
    ResolveAlertRequest,
)
from anomaly.scanner import run_full_scan, run_targeted_scan
from anomaly.detectors import (
    detect_order_amount_anomalies, detect_rapid_ordering,
    detect_payment_failure_spree, dedupe_alerts,
)

router = APIRouter(prefix="/anomaly", tags=["Anomaly Detection"])


def _fmt(a: AnomalyAlert) -> dict:
    return {
        "id":            a.id,
        "anomaly_type":  a.anomaly_type,
        "entity_type":   a.entity_type,
        "entity_id":     a.entity_id,
        "severity":      a.severity,
        "title":         a.title,
        "description":   a.description,
        "evidence":      a.evidence,
        "risk_score":    a.risk_score,
        "status":        a.status,
        "rule_name":     a.rule_name,
        "detected_at":   str(a.detected_at),
        "resolved_at":   str(a.resolved_at) if a.resolved_at else None,
        "resolved_by":   a.resolved_by,
        "resolution_note": a.resolution_note,
    }


# ── POST /anomaly/scan ────────────────────────────────────────────────────────

@router.post("/scan")
def trigger_scan(
    scan_type: Literal["full", "order", "payment", "search", "inventory", "user"] = "full",
    db: Session = Depends(get_db),
):
    """
    Trigger an anomaly scan.
    scan_type=full runs all detectors (~300-500ms on a typical dataset).
    Targeted scans are faster and useful for real-time checks.
    """
    if scan_type == "full":
        return run_full_scan(db, scan_type="full")
    return run_targeted_scan(db, target=scan_type)


# ── POST /anomaly/check/order ─────────────────────────────────────────────────

@router.post("/check/order")
def check_order(payload: CheckOrderRequest, db: Session = Depends(get_db)):
    """
    On-demand anomaly check for a single order.
    Checks amount (vs. historical distribution) and customer order velocity.
    """
    order = db.query(CheckoutOrder).filter(
        CheckoutOrder.id == payload.checkout_order_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Checkout order not found")

    amount = payload.amount or order.total or 0
    customer_id = payload.customer_id or order.customer_id

    # Quick amount check using IQR on last 90 days
    from anomaly.detectors import detect_order_amount_anomalies
    amount_alerts = detect_order_amount_anomalies(db)
    order_alerts  = [a for a in amount_alerts if a.entity_id == order.id]

    # Velocity check
    velocity_alerts = detect_rapid_ordering(db)
    cust_vel = [a for a in velocity_alerts if a.entity_id == customer_id]

    all_alerts = order_alerts + cust_vel
    new_alerts = dedupe_alerts(all_alerts, db)
    for a in new_alerts:
        db.add(a)
    if new_alerts:
        db.commit()

    highest_risk = max((a.risk_score for a in all_alerts), default=0)
    return {
        "checkout_order_id": payload.checkout_order_id,
        "amount":            amount,
        "is_anomalous":      len(all_alerts) > 0,
        "risk_score":        highest_risk,
        "alerts":            [_fmt(a) for a in all_alerts],
        "new_alerts_saved":  len(new_alerts),
    }


# ── POST /anomaly/check/user ──────────────────────────────────────────────────

@router.post("/check/user")
def check_user(payload: CheckUserRequest, db: Session = Depends(get_db)):
    """
    On-demand anomaly check for a customer.
    Checks order velocity, payment failures, and bot-like search behaviour.
    """
    from anomaly.detectors import detect_bot_behavior
    velocity_alerts = detect_rapid_ordering(db)
    payment_alerts  = detect_payment_failure_spree(db)
    bot_alerts      = detect_bot_behavior(db)

    cid  = payload.customer_id
    all_ = (
        [a for a in velocity_alerts if a.entity_id == cid] +
        [a for a in payment_alerts  if a.entity_id == cid] +
        [a for a in bot_alerts      if a.entity_id == cid]
    )
    new_alerts = dedupe_alerts(all_, db)
    for a in new_alerts:
        db.add(a)
    if new_alerts:
        db.commit()

    return {
        "customer_id":      cid,
        "is_anomalous":     len(all_) > 0,
        "risk_score":       max((a.risk_score for a in all_), default=0),
        "alerts":           [_fmt(a) for a in all_],
        "new_alerts_saved": len(new_alerts),
    }


# ── POST /anomaly/check/payment ───────────────────────────────────────────────

@router.post("/check/payment")
def check_payment(payload: CheckPaymentRequest, db: Session = Depends(get_db)):
    """Check a customer's recent payment behaviour for anomalies."""
    payment_alerts = detect_payment_failure_spree(db)
    from anomaly.detectors import detect_payment_replay
    replay_alerts  = detect_payment_replay(db)

    cid  = payload.customer_id
    all_ = [a for a in payment_alerts + replay_alerts if a.entity_id == cid]
    new_alerts = dedupe_alerts(all_, db)
    for a in new_alerts:
        db.add(a)
    if new_alerts:
        db.commit()

    return {
        "customer_id":      cid,
        "is_anomalous":     len(all_) > 0,
        "risk_score":       max((a.risk_score for a in all_), default=0),
        "alerts":           [_fmt(a) for a in all_],
        "new_alerts_saved": len(new_alerts),
    }


# ── GET /anomaly/alerts/stats — must be before /{id} ─────────────────────────

@router.get("/alerts/stats")
def alert_stats(db: Session = Depends(get_db)):
    """Aggregate statistics across all alerts."""
    total   = db.query(AnomalyAlert).count()
    open_   = db.query(AnomalyAlert).filter(AnomalyAlert.status == "open").count()

    by_sev  = dict(db.query(AnomalyAlert.severity, func.count(AnomalyAlert.id))
                   .group_by(AnomalyAlert.severity).all())
    by_type = dict(db.query(AnomalyAlert.anomaly_type, func.count(AnomalyAlert.id))
                   .group_by(AnomalyAlert.anomaly_type).all())
    by_status = dict(db.query(AnomalyAlert.status, func.count(AnomalyAlert.id))
                     .group_by(AnomalyAlert.status).all())

    avg_risk = db.query(func.avg(AnomalyAlert.risk_score)).scalar()
    top_entities = (
        db.query(AnomalyAlert.entity_id, func.count(AnomalyAlert.id).label("n"))
        .filter(AnomalyAlert.status == "open")
        .group_by(AnomalyAlert.entity_id)
        .order_by(func.count(AnomalyAlert.id).desc())
        .limit(5)
        .all()
    )

    return {
        "total_alerts":       total,
        "open_alerts":        open_,
        "avg_risk_score":     round(float(avg_risk or 0), 1),
        "by_severity":        by_sev,
        "by_type":            by_type,
        "by_status":          by_status,
        "top_flagged_entities": [{"entity_id": r.entity_id, "alert_count": r.n}
                                  for r in top_entities],
    }


# ── GET /anomaly/alerts ───────────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(
    status:       Optional[Literal["open", "acknowledged", "resolved", "false_positive"]] = Query(None),
    severity:     Optional[Literal["low", "medium", "high", "critical"]] = Query(None),
    anomaly_type: Optional[str] = Query(None),
    entity_type:  Optional[str] = Query(None),
    entity_id:    Optional[str] = Query(None),
    limit:        int = Query(50, ge=1, le=500),
    page:         int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    q = db.query(AnomalyAlert)
    if status:
        q = q.filter(AnomalyAlert.status == status)
    if severity:
        q = q.filter(AnomalyAlert.severity == severity)
    if anomaly_type:
        q = q.filter(AnomalyAlert.anomaly_type == anomaly_type)
    if entity_type:
        q = q.filter(AnomalyAlert.entity_type == entity_type)
    if entity_id:
        q = q.filter(AnomalyAlert.entity_id == entity_id)

    total  = q.count()
    alerts = q.order_by(AnomalyAlert.detected_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total":  total,
        "page":   page,
        "alerts": [_fmt(a) for a in alerts],
    }


# ── GET /anomaly/alerts/{alert_id} ────────────────────────────────────────────

@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    a = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _fmt(a)


# ── POST /anomaly/alerts/{id}/acknowledge ─────────────────────────────────────

@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)):
    a = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if a.status != "open":
        return {"message": f"Alert is already {a.status}", **_fmt(a)}
    a.status = "acknowledged"
    db.commit()
    return {"message": "Alert acknowledged", **_fmt(a)}


# ── POST /anomaly/alerts/{id}/resolve ─────────────────────────────────────────

@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    payload: ResolveAlertRequest,
    db: Session = Depends(get_db),
):
    a = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if a.status == "resolved":
        return {"message": "Alert already resolved", **_fmt(a)}

    a.status          = "resolved"
    a.resolved_at     = datetime.now(timezone.utc)
    a.resolved_by     = payload.resolved_by or "user"
    a.resolution_note = payload.resolution_note
    db.commit()
    return {"message": "Alert resolved", **_fmt(a)}


# ── POST /anomaly/alerts/{id}/false-positive ──────────────────────────────────

@router.post("/alerts/{alert_id}/false-positive")
def mark_false_positive(
    alert_id: str,
    payload: ResolveAlertRequest,
    db: Session = Depends(get_db),
):
    a = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    a.status          = "false_positive"
    a.resolved_at     = datetime.now(timezone.utc)
    a.resolved_by     = payload.resolved_by or "user"
    a.resolution_note = payload.resolution_note or "Marked as false positive"
    db.commit()
    return {"message": "Marked as false positive", **_fmt(a)}
