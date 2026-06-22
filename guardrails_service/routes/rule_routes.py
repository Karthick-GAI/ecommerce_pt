"""
Guard rule management routes.

GET    /rules              — list all rules (with pagination)
POST   /rules              — create a custom rule
PUT    /rules/{id}         — update an existing rule
DELETE /rules/{id}         — soft-delete (set is_active=False)
POST   /rules/{id}/test    — test a rule against sample input
POST   /rules/{id}/toggle  — toggle is_active on/off
GET    /rules/stats        — trigger count stats
"""
import re
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import GuardRule
from schemas import GuardRuleCreate, GuardRuleUpdate, RuleTestRequest

router = APIRouter(prefix="/rules", tags=["Rules"])


def _fmt(r: GuardRule) -> dict:
    return {
        "id":            r.id,
        "name":          r.name,
        "description":   r.description,
        "target_type":   r.target_type,
        "rule_type":     r.rule_type,
        "condition":     r.condition,
        "action":        r.action,
        "severity":      r.severity,
        "is_active":     r.is_active,
        "trigger_count": r.trigger_count,
        "created_at":    str(r.created_at),
        "updated_at":    str(r.updated_at) if r.updated_at else None,
    }


# ── GET /rules/stats — before /{id} ──────────────────────────────────────────

@router.get("/stats")
def rule_stats(db: Session = Depends(get_db)):
    """How many times each rule has been triggered (most fired first)."""
    rules = db.query(GuardRule).order_by(GuardRule.trigger_count.desc()).all()
    return {
        "total_rules":  len(rules),
        "active_rules": sum(1 for r in rules if r.is_active),
        "rules": [
            {"name": r.name, "target_type": r.target_type,
             "trigger_count": r.trigger_count, "severity": r.severity,
             "is_active": r.is_active}
            for r in rules
        ],
    }


# ── GET /rules ────────────────────────────────────────────────────────────────

@router.get("")
def list_rules(
    target_type: Optional[str] = Query(None),
    is_active:   Optional[bool] = Query(None),
    limit:       int = Query(50, ge=1, le=200),
    page:        int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    q = db.query(GuardRule)
    if target_type:
        q = q.filter(GuardRule.target_type == target_type)
    if is_active is not None:
        q = q.filter(GuardRule.is_active == is_active)
    total = q.count()
    rules = q.order_by(GuardRule.created_at).offset((page - 1) * limit).limit(limit).all()
    return {"total": total, "page": page, "rules": [_fmt(r) for r in rules]}


# ── POST /rules ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_rule(payload: GuardRuleCreate, db: Session = Depends(get_db)):
    existing = db.query(GuardRule).filter(GuardRule.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Rule '{payload.name}' already exists")

    rule = GuardRule(
        name        = payload.name,
        description = payload.description,
        target_type = payload.target_type,
        rule_type   = payload.rule_type,
        condition   = payload.condition,
        action      = payload.action or "flag",
        severity    = payload.severity or "medium",
        is_active   = payload.is_active if payload.is_active is not None else True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"message": "Rule created", "rule": _fmt(rule)}


# ── PUT /rules/{rule_id} ──────────────────────────────────────────────────────

@router.put("/{rule_id}")
def update_rule(rule_id: str, payload: GuardRuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(GuardRule).filter(GuardRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if payload.description is not None: rule.description = payload.description
    if payload.condition   is not None: rule.condition   = payload.condition
    if payload.action      is not None: rule.action      = payload.action
    if payload.severity    is not None: rule.severity    = payload.severity
    if payload.is_active   is not None: rule.is_active   = payload.is_active

    db.commit()
    return {"message": "Rule updated", "rule": _fmt(rule)}


# ── DELETE /rules/{rule_id} ───────────────────────────────────────────────────

@router.delete("/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(GuardRule).filter(GuardRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    _SEED_NAMES = {
        "sql_injection", "xss_injection", "path_traversal", "command_injection",
        "order_rate_limit", "payment_failure_limit", "amount_zscore",
        "search_query_length", "bulk_order_qty", "inventory_discount",
    }
    if rule.name in _SEED_NAMES:
        # Soft-deactivate built-in rules rather than deleting them
        rule.is_active = False
        db.commit()
        return {"message": f"Built-in rule '{rule.name}' deactivated (cannot be deleted)", "rule": _fmt(rule)}

    db.delete(rule)
    db.commit()
    return {"message": f"Rule '{rule.name}' deleted"}


# ── POST /rules/{rule_id}/toggle ──────────────────────────────────────────────

@router.post("/{rule_id}/toggle")
def toggle_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(GuardRule).filter(GuardRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_active = not rule.is_active
    db.commit()
    return {
        "message":   f"Rule {'activated' if rule.is_active else 'deactivated'}",
        "is_active": rule.is_active,
        "rule":      _fmt(rule),
    }


# ── POST /rules/{rule_id}/test ────────────────────────────────────────────────

@router.post("/{rule_id}/test")
def test_rule(rule_id: str, payload: RuleTestRequest, db: Session = Depends(get_db)):
    """
    Test a rule against a sample input without persisting anything.
    Returns whether the rule would trigger and why.
    """
    rule = db.query(GuardRule).filter(GuardRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    triggered = False
    reason    = ""
    value     = payload.input_value

    if rule.rule_type == "regex":
        pattern = rule.condition.get("pattern", "")
        try:
            m = re.search(pattern, str(value), re.IGNORECASE)
            triggered = m is not None
            reason    = f"Pattern matched: '{m.group()[:50]}'" if m else "Pattern did not match"
        except re.error as e:
            reason = f"Invalid regex pattern: {e}"

    elif rule.rule_type == "threshold":
        field    = rule.condition.get("field", "value")
        operator = rule.condition.get("operator", ">")
        threshold = float(rule.condition.get("value", 0))
        try:
            v = float(value)
            triggered = eval(f"{v} {operator} {threshold}")  # safe: controlled input
            reason = f"{v} {operator} {threshold} → {'triggered' if triggered else 'not triggered'}"
        except (ValueError, TypeError):
            reason = f"Could not compare {value!r} to threshold {threshold}"

    elif rule.rule_type == "range":
        mn = rule.condition.get("min")
        mx = rule.condition.get("max")
        try:
            v         = float(value)
            in_range  = (mn is None or v >= mn) and (mx is None or v <= mx)
            triggered = not in_range
            reason    = f"{v} {'is' if in_range else 'is NOT'} in range [{mn}, {mx}]"
        except (ValueError, TypeError):
            reason = f"Could not evaluate range for {value!r}"

    elif rule.rule_type == "rate_limit":
        reason = "rate_limit rules require live session context — cannot test statically"

    elif rule.rule_type == "zscore":
        reason = "zscore rules require a historical dataset — cannot test statically"

    else:
        reason = f"Unknown rule_type: {rule.rule_type}"

    if triggered:
        rule.trigger_count = (rule.trigger_count or 0) + 1
        db.commit()

    return {
        "rule_id":   rule_id,
        "rule_name": rule.name,
        "rule_type": rule.rule_type,
        "triggered": triggered,
        "would_action": rule.action if triggered else "pass",
        "reason":    reason,
    }
