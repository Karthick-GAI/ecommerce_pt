from typing import Optional, Literal, List, Any
from pydantic import BaseModel, Field


# ── Payment ───────────────────────────────────────────────────────────────────

class CreatePaymentOrderRequest(BaseModel):
    checkout_order_id: str
    provider: Optional[Literal["razorpay"]] = "razorpay"


class VerifyPaymentRequest(BaseModel):
    """Payload sent by the frontend after the Razorpay checkout modal closes."""
    razorpay_order_id:   str
    razorpay_payment_id: str
    razorpay_signature:  str


class RefundRequest(BaseModel):
    amount:  Optional[float] = None    # None = full refund
    reason:  Optional[str]  = "Customer requested"
    notes:   Optional[str]  = None


class PaymentOrderOut(BaseModel):
    id:                str
    checkout_order_id: str
    provider:          str
    provider_order_id: Optional[str] = None
    provider_key_id:   Optional[str] = None
    amount:            float
    currency:          str
    status:            str
    attempts:          int
    created_at:        str
    expires_at:        Optional[str] = None
    paid_at:           Optional[str] = None


class TransactionOut(BaseModel):
    id:                  str
    pay_order_id:        str
    checkout_order_id:   str
    provider_payment_id: Optional[str] = None
    method:              Optional[str] = None
    card_last4:          Optional[str] = None
    card_network:        Optional[str] = None
    upi_vpa:             Optional[str] = None
    amount:              Optional[float] = None
    status:              str
    error_code:          Optional[str] = None
    error_description:   Optional[str] = None
    created_at:          str


class RefundOut(BaseModel):
    id:                 str
    transaction_id:     str
    checkout_order_id:  str
    provider_refund_id: Optional[str] = None
    amount:             float
    reason:             Optional[str] = None
    status:             str
    initiated_at:       str
    processed_at:       Optional[str] = None


# ── Shipping ──────────────────────────────────────────────────────────────────

class ShippingRateRequest(BaseModel):
    origin_pincode:      str = Field(..., min_length=6, max_length=6)
    destination_pincode: str = Field(..., min_length=6, max_length=6)
    weight_kg:           float = Field(..., gt=0, le=100)
    length_cm:           Optional[float] = None
    breadth_cm:          Optional[float] = None
    height_cm:           Optional[float] = None
    cod:                 Optional[bool] = False


class RateOptionOut(BaseModel):
    courier_name:    str
    service_type:    str
    rate_amount:     float
    estimated_days:  int
    cod_available:   bool
    courier_id:      Optional[str] = None


class CreateShipmentRequest(BaseModel):
    checkout_order_id:   str
    # If omitted, pulled from checkout_orders.shipping_pincode / warehouse
    origin_pincode:      Optional[str] = None
    destination_pincode: Optional[str] = None  # auto-populated from checkout_orders
    destination_address: Optional[str] = None  # auto-populated from checkout_orders
    destination_name:    Optional[str] = None  # auto-populated from checkout_orders
    destination_phone:   Optional[str] = None  # auto-populated from checkout_orders
    weight_kg:           float = Field(0.5, gt=0, le=100)
    length_cm:           Optional[float] = None
    breadth_cm:          Optional[float] = None
    height_cm:           Optional[float] = None
    service_type:        Optional[Literal["standard", "express", "overnight"]] = "standard"
    courier_id:          Optional[str] = None   # from rate quote; service picks best if omitted
    cod:                 Optional[bool] = False
    cod_amount:          Optional[float] = None


class ShipmentOut(BaseModel):
    id:                   str
    checkout_order_id:    str
    provider:             str
    provider_shipment_id: Optional[str] = None
    awb_number:           Optional[str] = None
    courier_name:         Optional[str] = None
    label_url:            Optional[str] = None
    origin_pincode:       str
    destination_pincode:  str
    weight_kg:            float
    service_type:         str
    rate_amount:          Optional[float] = None
    estimated_days:       Optional[int]  = None
    status:               str
    created_at:           str
    estimated_delivery:   Optional[str] = None
    actual_delivery:      Optional[str] = None


class TrackingEventOut(BaseModel):
    status:      str
    description: Optional[str] = None
    location:    Optional[str] = None
    timestamp:   Optional[str] = None


class TrackingOut(BaseModel):
    shipment_id:       str
    awb_number:        Optional[str] = None
    current_status:    str
    estimated_delivery: Optional[str] = None
    events:            List[TrackingEventOut]


# ── Webhooks ──────────────────────────────────────────────────────────────────

class WebhookEventOut(BaseModel):
    id:          str
    provider:    str
    event_type:  Optional[str] = None
    entity_id:   Optional[str] = None
    status:      str
    received_at: str
    processed_at: Optional[str] = None
