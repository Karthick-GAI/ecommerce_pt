from pydantic import BaseModel, Field, model_validator
from typing import Optional


class RestockRequest(BaseModel):
    quantity:     int           = Field(..., gt=0, description="Units to add (must be > 0)")
    reference_id: Optional[str] = None   # PO number or supplier reference
    notes:        Optional[str] = None
    changed_by:   str           = "ops_team"


class AdjustmentRequest(BaseModel):
    quantity_change: int           # positive = add stock, negative = remove
    change_type:     str = "adjustment"   # adjustment | damage | return | audit
    reason:          str           # required for audit trail
    reference_id:    Optional[str] = None
    changed_by:      str = "ops_team"

    @model_validator(mode="after")
    def validate_fields(self):
        valid_types = {"adjustment", "damage", "return", "audit"}
        if self.change_type not in valid_types:
            raise ValueError(f"change_type must be one of: {', '.join(valid_types)}")
        if self.quantity_change == 0:
            raise ValueError("quantity_change cannot be zero")
        return self


class AlertRuleCreate(BaseModel):
    rule_type:       str           # product | category | global
    target_id:       str           # product_id, category name, or "*"
    label:           Optional[str] = None
    threshold_value: int           = Field(..., ge=0)
    alert_severity:  str           # critical | warning | info

    @model_validator(mode="after")
    def validate_fields(self):
        if self.rule_type not in {"product", "category", "global"}:
            raise ValueError("rule_type must be: product, category, or global")
        if self.alert_severity not in {"critical", "warning", "info"}:
            raise ValueError("alert_severity must be: critical, warning, or info")
        return self


class AlertRuleUpdate(BaseModel):
    label:           Optional[str]  = None
    threshold_value: Optional[int]  = Field(None, ge=0)
    alert_severity:  Optional[str]  = None
    is_active:       Optional[bool] = None


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str
    notes:           Optional[str] = None
