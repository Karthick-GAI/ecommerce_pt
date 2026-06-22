from pydantic import BaseModel, Field
from typing import Optional, List


class StatusUpdateRequest(BaseModel):
    to_status: str          # processing | shipped | out_for_delivery | delivered
    reason: Optional[str] = None
    changed_by: str = "admin"


class CancellationRequest(BaseModel):
    reason: str
    cancelled_by: str = "customer"


class RefundRequest(BaseModel):
    amount: Optional[float] = Field(None, gt=0)   # None = full refund; must be > 0 if provided
    reason: Optional[str] = "Customer requested refund"


class RefundActionRequest(BaseModel):
    reason: Optional[str] = None


# ── Response models ───────────────────────────────────────────────────────────

class StatusHistoryItem(BaseModel):
    id: str
    from_status: Optional[str]
    to_status: str
    changed_by: str
    reason: Optional[str]
    tracking_number: Optional[str]
    estimated_delivery: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class OrderItemOut(BaseModel):
    product_id: str
    product_name: str
    brand: str
    quantity: int
    unit_price: float
    total_price: float

    model_config = {"from_attributes": True}


class RefundOut(BaseModel):
    refund_id: str
    amount: float
    status: str
    reason: Optional[str]
    original_payment_method: Optional[str]
    refund_txn_id: Optional[str]
    rejection_reason: Optional[str]
    processed_at: Optional[str]
    created_at: str


class OrderDetailOut(BaseModel):
    order_id: str
    customer_id: Optional[str]
    status: str
    payment_status: str
    payment_method: Optional[str]
    transaction_id: Optional[str]
    items: List[OrderItemOut]
    subtotal: float
    discount: float
    coupon_code: Optional[str]
    tax: float
    shipping_charge: float
    total: float
    shipping_name: Optional[str]
    shipping_phone: Optional[str]
    shipping_address: Optional[str]
    shipping_city: Optional[str]
    shipping_state: Optional[str]
    shipping_pincode: Optional[str]
    created_at: str
    timeline: List[StatusHistoryItem]
    refund: Optional[RefundOut]
    tracking_number: Optional[str]


class NotificationOut(BaseModel):
    id: str
    order_id: Optional[str]
    channel: str
    event: str
    title: str
    message: str
    is_read: bool
    sent_at: str

    model_config = {"from_attributes": True}
