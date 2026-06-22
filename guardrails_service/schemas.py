from typing import Optional, Literal, List, Any
from pydantic import BaseModel, Field


# ── Violation ─────────────────────────────────────────────────────────────────

class ViolationOut(BaseModel):
    rule:     str
    severity: str
    message:  str
    matched:  Optional[str] = None


# ── Validation requests ───────────────────────────────────────────────────────

class ValidateTextRequest(BaseModel):
    text:        str
    context:     Optional[Literal["search", "name", "address", "comment", "any"]] = "any"
    customer_id: Optional[str] = None
    session_id:  Optional[str] = None


class ValidateOrderRequest(BaseModel):
    checkout_order_id: Optional[str] = None
    customer_id:       Optional[str] = None
    items: List[dict]          # [{product_id, quantity, unit_price}]
    total_amount:       float
    payment_method:    Optional[str] = None


class ValidateSearchRequest(BaseModel):
    query:       str
    customer_id: Optional[str] = None
    session_id:  Optional[str] = None


class ValidateContactRequest(BaseModel):
    email:       Optional[str] = None
    phone:       Optional[str] = None
    pincode:     Optional[str] = None
    name:        Optional[str] = None


class ValidateAmountRequest(BaseModel):
    amount:      float
    context:     Optional[Literal["order", "refund", "discount", "price"]] = "order"
    currency:    Optional[str] = "INR"


# ── Validation response ───────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    is_valid:        bool
    risk_score:      int        # 0-100
    action:          str        # pass | flag | block
    violations:      List[ViolationOut]
    rules_triggered: List[str]
    summary:         Optional[str] = None


# ── Anomaly alert ─────────────────────────────────────────────────────────────

class AnomalyAlertOut(BaseModel):
    id:           str
    anomaly_type: str
    entity_type:  str
    entity_id:    str
    severity:     str
    title:        str
    description:  Optional[str] = None
    evidence:     Optional[dict] = None
    risk_score:   int
    status:       str
    rule_name:    Optional[str] = None
    detected_at:  str
    resolved_at:  Optional[str] = None


class ResolveAlertRequest(BaseModel):
    resolution_note: Optional[str] = None
    resolved_by:     Optional[str] = "system"


# ── Anomaly check ─────────────────────────────────────────────────────────────

class CheckOrderRequest(BaseModel):
    checkout_order_id: str
    customer_id:       Optional[str] = None
    amount:            Optional[float] = None   # if None, looked up from DB


class CheckUserRequest(BaseModel):
    customer_id:    str
    window_hours:   Optional[int] = 24


class CheckPaymentRequest(BaseModel):
    customer_id:    str
    window_hours:   Optional[int] = 24


# ── Rules ─────────────────────────────────────────────────────────────────────

class GuardRuleCreate(BaseModel):
    name:        str
    description: Optional[str] = None
    target_type: Literal["order", "user", "payment", "search", "input", "product", "all"]
    rule_type:   Literal["regex", "threshold", "rate_limit", "range", "zscore"]
    condition:   dict
    action:      Optional[Literal["flag", "block", "alert"]] = "flag"
    severity:    Optional[Literal["low", "medium", "high", "critical"]] = "medium"
    is_active:   Optional[bool] = True


class GuardRuleUpdate(BaseModel):
    description: Optional[str]  = None
    condition:   Optional[dict] = None
    action:      Optional[Literal["flag", "block", "alert"]] = None
    severity:    Optional[Literal["low", "medium", "high", "critical"]] = None
    is_active:   Optional[bool] = None


class GuardRuleOut(BaseModel):
    id:            str
    name:          str
    description:   Optional[str] = None
    target_type:   str
    rule_type:     str
    condition:     dict
    action:        str
    severity:      str
    is_active:     bool
    trigger_count: int
    created_at:    str


class RuleTestRequest(BaseModel):
    input_value: Any     # the value to test the rule against
    field:       Optional[str] = None


# ── Scan ─────────────────────────────────────────────────────────────────────

class ScanResult(BaseModel):
    scan_type:         str
    duration_ms:       int
    alerts_created:    int
    alerts_by_severity: dict
    summary:           str
