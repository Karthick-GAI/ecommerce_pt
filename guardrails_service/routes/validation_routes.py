"""
Input validation routes.

POST /validate/text       — generic text: SQLi, XSS, path traversal, cmd injection
POST /validate/search     — search query: security + length/format
POST /validate/order      — full order: items, amounts, business logic, duplicates
POST /validate/contact    — phone / email / pincode / name
POST /validate/amount     — monetary amount range + sanity
POST /validate/batch      — validate multiple text inputs in one call
"""
import hashlib
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from database import get_db
from models import ValidationLog
from schemas import (
    ValidateTextRequest, ValidateSearchRequest, ValidateOrderRequest,
    ValidateContactRequest, ValidateAmountRequest, ValidationResult, ViolationOut,
)
from validators.security import scan_input, compute_risk_score, Violation
from validators.format import (
    validate_search_query, validate_order_items, validate_amount,
    validate_phone, validate_email_address, validate_pincode, validate_name,
)
from validators.business import (
    validate_order_against_catalogue, validate_total_amount,
    validate_duplicate_order, validate_payment_method,
)

router = APIRouter(prefix="/validate", tags=["Validation"])

BLOCK_THRESHOLD = int(os.getenv("BLOCK_THRESHOLD", "80"))
FLAG_THRESHOLD  = int(os.getenv("FLAG_THRESHOLD",  "40"))


# ── helpers ───────────────────────────────────────────────────────────────────

def _action(score: int) -> str:
    if score >= BLOCK_THRESHOLD:
        return "block"
    if score >= FLAG_THRESHOLD:
        return "flag"
    return "pass"


def _to_out(v: Violation) -> ViolationOut:
    return ViolationOut(rule=v.rule, severity=v.severity, message=v.message, matched=v.matched or None)


def _build_result(violations: list[Violation], extra_rules: list[str] = None) -> ValidationResult:
    score = compute_risk_score(violations)
    rules = list({v.rule for v in violations})
    if extra_rules:
        rules.extend(extra_rules)
    return ValidationResult(
        is_valid        = score < FLAG_THRESHOLD,
        risk_score      = score,
        action          = _action(score),
        violations      = [_to_out(v) for v in violations],
        rules_triggered = rules,
        summary         = (
            f"{len(violations)} violation(s) found — risk score {score}/100 → {_action(score)}"
            if violations else "No violations detected"
        ),
    )


def _log(request_type: str, violations: list[Violation], score: int,
         customer_id: str | None, session_id: str | None,
         raw_input: str | None, db: Session):
    """Persist an audit record. Stores a SHA-256 hash of raw input — never the input itself."""
    input_hash = hashlib.sha256(raw_input.encode()).hexdigest() if raw_input else None
    db.add(ValidationLog(
        request_type    = request_type,
        input_hash      = input_hash,
        customer_id     = customer_id,
        session_id      = session_id,
        violations      = [{"rule": v.rule, "severity": v.severity, "message": v.message} for v in violations],
        risk_score      = score,
        action          = _action(score),
        rules_triggered = list({v.rule for v in violations}),
    ))
    db.commit()


# ── POST /validate/text ───────────────────────────────────────────────────────

@router.post("/text")
def validate_text(payload: ValidateTextRequest, db: Session = Depends(get_db)):
    """
    Scans any text for security threats.
    Suitable for sanitising user-supplied content before storing or rendering.
    """
    violations = scan_input(payload.text, context=payload.context or "any")
    result     = _build_result(violations)
    _log("text", violations, result.risk_score,
         payload.customer_id, payload.session_id, payload.text, db)
    return result


# ── POST /validate/search ─────────────────────────────────────────────────────

@router.post("/search")
def validate_search(payload: ValidateSearchRequest, db: Session = Depends(get_db)):
    """
    Validates a search query: security threats + format checks.
    Call this before executing search queries against the product catalogue.
    """
    violations: list[Violation] = []
    violations.extend(scan_input(payload.query, context="search"))
    violations.extend(validate_search_query(payload.query))
    result = _build_result(violations)
    _log("search", violations, result.risk_score,
         payload.customer_id, payload.session_id, payload.query, db)
    return result


# ── POST /validate/order ──────────────────────────────────────────────────────

@router.post("/order")
def validate_order(payload: ValidateOrderRequest, db: Session = Depends(get_db)):
    """
    Full order validation pipeline:
      1. Format: item quantities, prices
      2. Business: catalogue existence, price tampering, total mismatch
      3. Duplicate: same customer ordering same items within 5 min
      4. Payment method whitelist
    """
    violations: list[Violation] = []

    # Format checks
    violations.extend(validate_order_items(payload.items))
    violations.extend(validate_amount(payload.total_amount, context="order"))

    # Business logic (requires DB)
    violations.extend(validate_order_against_catalogue(payload.items, db))
    violations.extend(validate_total_amount(payload.items, payload.total_amount, db))

    if payload.customer_id:
        violations.extend(validate_duplicate_order(payload.customer_id, payload.items, db))

    if payload.payment_method:
        violations.extend(validate_payment_method(payload.payment_method))

    result = _build_result(violations)
    _log("order", violations, result.risk_score,
         payload.customer_id, None, payload.checkout_order_id, db)
    return result


# ── POST /validate/contact ────────────────────────────────────────────────────

@router.post("/contact")
def validate_contact(payload: ValidateContactRequest, db: Session = Depends(get_db)):
    """
    Validates contact details: email, phone, Indian pincode, and name.
    Returns a unified result with violations per field.
    """
    violations: list[Violation] = []
    if payload.phone:
        violations.extend(validate_phone(payload.phone))
    if payload.email:
        violations.extend(validate_email_address(payload.email))
        violations.extend(scan_input(payload.email, context="any"))
    if payload.pincode:
        violations.extend(validate_pincode(payload.pincode))
    if payload.name:
        violations.extend(validate_name(payload.name))
        violations.extend(scan_input(payload.name, context="name"))

    result = _build_result(violations)
    _log("contact", violations, result.risk_score, None, None,
         payload.email or payload.phone, db)
    return result


# ── POST /validate/amount ─────────────────────────────────────────────────────

@router.post("/amount")
def validate_amount_endpoint(
    payload: ValidateAmountRequest,
    db: Session = Depends(get_db),
):
    """Validates a monetary amount for a given context (order / refund / price)."""
    violations = validate_amount(payload.amount, context=payload.context or "order")
    result     = _build_result(violations)
    _log("amount", violations, result.risk_score, None, None, str(payload.amount), db)
    return result


# ── POST /validate/batch ──────────────────────────────────────────────────────

@router.post("/batch")
def validate_batch(
    items: list[str],
    context: str = "any",
    db: Session = Depends(get_db),
):
    """
    Validate multiple text strings in one call.
    Returns a list of results in the same order as the input.
    Useful for bulk validation of imported data.
    """
    if len(items) > 100:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Batch size limited to 100 items")

    results = []
    for text in items:
        violations = scan_input(text, context=context)
        results.append(_build_result(violations))
    return {
        "total":    len(results),
        "blocked":  sum(1 for r in results if r.action == "block"),
        "flagged":  sum(1 for r in results if r.action == "flag"),
        "passed":   sum(1 for r in results if r.action == "pass"),
        "results":  results,
    }
