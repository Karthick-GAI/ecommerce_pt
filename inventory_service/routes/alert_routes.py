from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case
from sqlalchemy.orm import Session
from database import get_db
from models import Alert
from schemas import AcknowledgeRequest

router = APIRouter(prefix="/alerts", tags=["Alerts"])

# Severity sort: critical (1) before warning (2) — string sort is backwards
_SEVERITY_ORDER = case(
    (Alert.severity == "critical", 1),
    (Alert.severity == "warning",  2),
    else_=3,
)


# ── GET /alerts — list with filters ──────────────────────────────────────────

@router.get("")
def list_alerts(
    status:   Optional[Literal["open", "acknowledged", "resolved"]] = Query(None),
    severity: Optional[Literal["critical", "warning"]]              = Query(None),
    category: Optional[str]                                         = Query(None),
    page:     int = Query(1,   ge=1),
    limit:    int = Query(50,  ge=1, le=200),
    db: Session   = Depends(get_db),
):
    q = db.query(Alert)
    if status:
        q = q.filter(Alert.status == status)
    if severity:
        q = q.filter(Alert.severity == severity)
    if category:
        q = q.filter(Alert.category == category)

    total  = q.count()
    alerts = (
        q.order_by(_SEVERITY_ORDER, Alert.current_stock, Alert.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "total":  total,
        "page":   page,
        "limit":  limit,
        "alerts": [_fmt(a) for a in alerts],
    }


# ── POST /alerts/bulk-acknowledge — acknowledge all open alerts ───────────────
# Defined BEFORE /{alert_id} to prevent "bulk-acknowledge" being matched as alert_id.

@router.post("/bulk-acknowledge")
def bulk_acknowledge(payload: AcknowledgeRequest, db: Session = Depends(get_db)):
    open_alerts = db.query(Alert).filter(Alert.status == "open").all()
    if not open_alerts:
        return {"message": "No open alerts to acknowledge", "updated": 0}

    now = datetime.utcnow()
    for a in open_alerts:
        a.status          = "acknowledged"
        a.acknowledged_by = payload.acknowledged_by
        a.acknowledged_at = now
        a.updated_at      = now

    db.commit()
    return {
        "message":          f"Acknowledged {len(open_alerts)} open alert(s)",
        "updated":          len(open_alerts),
        "acknowledged_by":  payload.acknowledged_by,
    }


# ── GET /alerts/{alert_id} ────────────────────────────────────────────────────

@router.get("/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _fmt(alert)


# ── POST /alerts/{alert_id}/acknowledge ──────────────────────────────────────

@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: str, payload: AcknowledgeRequest, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status == "resolved":
        raise HTTPException(status_code=400, detail="Alert is already resolved")

    alert.status          = "acknowledged"
    alert.acknowledged_by = payload.acknowledged_by
    alert.acknowledged_at = datetime.utcnow()
    alert.updated_at      = datetime.utcnow()
    db.commit()

    return {
        "message":         "Alert acknowledged",
        "alert_id":        alert_id,
        "acknowledged_by": payload.acknowledged_by,
        "product_name":    alert.product_name,
        "current_stock":   alert.current_stock,
    }


# ── POST /alerts/{alert_id}/resolve ──────────────────────────────────────────

@router.post("/{alert_id}/resolve")
def resolve(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status == "resolved":
        raise HTTPException(status_code=400, detail="Alert is already resolved")

    alert.status      = "resolved"
    alert.resolved_at = datetime.utcnow()
    alert.updated_at  = datetime.utcnow()
    db.commit()

    return {
        "message":      "Alert resolved",
        "alert_id":     alert_id,
        "product_name": alert.product_name,
    }


def _fmt(a: Alert) -> dict:
    return {
        "alert_id":        a.id,
        "product_id":      a.product_id,
        "product_name":    a.product_name,
        "category":        a.category,
        "brand":           a.brand,
        "current_stock":   a.current_stock,
        "threshold":       a.threshold,
        "severity":        a.severity,
        "status":          a.status,
        "acknowledged_by": a.acknowledged_by,
        "acknowledged_at": str(a.acknowledged_at) if a.acknowledged_at else None,
        "resolved_at":     str(a.resolved_at)     if a.resolved_at     else None,
        "created_at":      str(a.created_at),
    }
