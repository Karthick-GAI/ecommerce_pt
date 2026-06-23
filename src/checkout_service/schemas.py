from typing import Optional, List
from pydantic import BaseModel, Field, model_validator


# ── Cart ──────────────────────────────────────────────────────────────────────

class CreateCartRequest(BaseModel):
    customer_id: Optional[str] = None


class AddItemRequest(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=20)


class UpdateItemRequest(BaseModel):
    quantity: int = Field(ge=1, le=20)


class CartItemResponse(BaseModel):
    product_id:   str
    product_name: str
    brand:        str
    quantity:     int
    unit_price:   float
    total_price:  float
    in_stock:     bool


class CartResponse(BaseModel):
    cart_id:    str
    status:     str
    items:      List[CartItemResponse]
    item_count: int
    subtotal:   float
    created_at: str


# ── Checkout ──────────────────────────────────────────────────────────────────

class ShippingAddress(BaseModel):
    name:         str
    phone:        str
    address_line: str
    city:         str
    state:        str
    pincode:      str


class CheckoutRequest(BaseModel):
    cart_id:      str
    customer_id:  Optional[str] = None
    shipping:     ShippingAddress
    coupon_code:  Optional[str] = None


class OrderItemResponse(BaseModel):
    product_id:   str
    product_name: str
    brand:        str
    quantity:     int
    unit_price:   float
    total_price:  float


class OrderSummaryResponse(BaseModel):
    order_id:        str
    status:          str
    items:           List[OrderItemResponse]
    subtotal:        float
    discount:        float
    coupon_message:  Optional[str] = None
    tax:             float
    shipping_charge: float
    total:           float
    payment_methods: List[str]


# ── Payment ───────────────────────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    method: str   # card | wallet | upi

    # Card fields
    card_number:  Optional[str] = None
    card_holder:  Optional[str] = None
    expiry_month: Optional[str] = None
    expiry_year:  Optional[str] = None
    cvv:          Optional[str] = None

    # Wallet fields
    wallet_type:   Optional[str] = None   # paytm | phonepe | googlepay | amazonpay
    wallet_mobile: Optional[str] = None

    # UPI fields
    upi_id: Optional[str] = None

    @model_validator(mode="after")
    def check_required_fields(self):
        if self.method == "card":
            missing = [f for f in ["card_number", "card_holder", "expiry_month", "expiry_year", "cvv"]
                       if not getattr(self, f)]
            if missing:
                raise ValueError(f"Card payment requires: {', '.join(missing)}")
        elif self.method == "wallet":
            if not self.wallet_type:
                raise ValueError("wallet_type required (paytm/phonepe/googlepay/amazonpay)")
            if not self.wallet_mobile:
                raise ValueError("wallet_mobile required")
        elif self.method == "upi":
            if not self.upi_id:
                raise ValueError("upi_id required (e.g. name@paytm)")
        else:
            raise ValueError("method must be one of: card, wallet, upi")
        return self


class PaymentResponse(BaseModel):
    order_id:       str
    payment_status: str       # success | failed
    transaction_id: Optional[str] = None
    amount:         float
    message:        str


# ── Order ─────────────────────────────────────────────────────────────────────

class OrderDetailResponse(BaseModel):
    order_id:        str
    status:          str
    payment_status:  str
    payment_method:  Optional[str]
    transaction_id:  Optional[str]
    items:           List[OrderItemResponse]
    subtotal:        float
    discount:        float
    tax:             float
    shipping_charge: float
    total:           float
    shipping_name:    Optional[str]
    shipping_phone:   Optional[str]
    shipping_address: Optional[str]
    shipping_city:    Optional[str]
    shipping_state:   Optional[str]
    shipping_pincode: Optional[str]
    created_at:      str
