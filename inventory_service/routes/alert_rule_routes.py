from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import AlertRule
from schemas import AlertRuleCreate, AlertRuleUpdate

router = APIRouter(prefix="/alert-rules", tags=["Alert Rules"])


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    rules = db.query(AlertRule).order_by(
        AlertRule.rule_type, AlertRule.threshold_value
    ).all()
    return {
        "total": len(rules),
        "rules": [_fmt(r) for r in rules],
    }


@router.post("", status_code=201)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db)):
    rule = AlertRule(
        rule_type       = payload.rule_type,
        target_id       = payload.target_id,
        label           = payload.label or f"{payload.rule_type}:{payload.target_id} ≤ {payload.threshold_value}",
        threshold_value = payload.threshold_value,
        alert_severity  = payload.alert_severity,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"message": "Alert rule created", "rule": _fmt(rule)}


@router.put("/{rule_id}")
def update_rule(rule_id: str, payload: AlertRuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if payload.label           is not None: rule.label           = payload.label
    if payload.threshold_value is not None: rule.threshold_value = payload.threshold_value
    if payload.alert_severity  is not None: rule.alert_severity  = payload.alert_severity
    if payload.is_active       is not None: rule.is_active        = payload.is_active

    db.commit()
    return {"message": "Rule updated", "rule": _fmt(rule)}


@router.delete("/{rule_id}")
def deactivate_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.is_active = False
    db.commit()
    return {"message": "Rule deactivated", "rule_id": rule_id}


def _fmt(r: AlertRule) -> dict:
    return {
        "rule_id":        r.id,
        "rule_type":      r.rule_type,
        "target_id":      r.target_id,
        "label":          r.label,
        "threshold_value": r.threshold_value,
        "alert_severity": r.alert_severity,
        "is_active":      r.is_active,
        "created_at":     str(r.created_at),
    }
