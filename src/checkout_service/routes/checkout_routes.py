import json

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import Cart, Order, OrderItem, Payment, Product, IdempotencyRecord
from schemas import (CheckoutRequest, OrderSummaryResponse,
                     PaymentRequest, PaymentResponse, OrderItemResponse)
from checkout import calculate_order_totals
from payment import process_payment

router = APIRouter(prefix="/checkout", tags=["Checkout & Payment"])


# ── POST /checkout — initiate checkout ───────────────────────────────────────

@router.post("", response_model=OrderSummaryResponse, status_code=201)
def initiate_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        description=(
            "UUID supplied by the client to make this request idempotent. "
            "If the server has already processed a request with this key, "
            "it returns the original response without creating a new order. "
            "Clients MUST send a fresh UUID for each genuinely new checkout attempt."
        ),
    ),
):
    """
    Step 1 of checkout.
    - Validates cart + stock
    - Calculates subtotal, coupon discount, 18% GST, shipping
    - Creates an Order (status=pending) — no payment yet
    - Returns order_id + full price breakdown

    **NFR — Reliability (idempotency)**: send `Idempotency-Key: <uuid>` to prevent
    duplicate orders on retried requests (network errors, double-taps, etc.).
    """
    # ── Idempotency check ─────────────────────────────────────────────────────
    if idempotency_key:
        existing = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.key == idempotency_key,
            IdempotencyRecord.endpoint == "POST /checkout",
        ).first()
        if existing and existing.response_body:
            # Return cached response — no new order created
            return OrderSummaryResponse(**json.loads(existing.response_body))

    # ── Cart validation ───────────────────────────────────────────────────────
    cart = db.query(Cart).filter(
        Cart.id == payload.cart_id, Cart.status == "active"
    ).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Active cart not found")
    if not cart.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Validate stock for every item before creating the order
    for item in cart.items:
        product = db.query(Product).filter(
            Product.id == item.product_id, Product.is_active == True
        ).first()
        if not product:
            raise HTTPException(status_code=400, detail=f"Product {item.product_id} no longer available")
        if product.inventory_count < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Only {product.inventory_count} units of '{product.name}' available (you need {item.quantity})",
            )

    totals = calculate_order_totals(cart.items, payload.coupon_code)

    # ── Create order ──────────────────────────────────────────────────────────
    order = Order(
        customer_id=payload.customer_id,
        cart_id=payload.cart_id,
        subtotal=totals["subtotal"],
        discount=totals["discount"],
        coupon_code=payload.coupon_code,
        tax=totals["tax"],
        shipping_charge=totals["shipping_charge"],
        total=totals["total"],
        shipping_name=payload.shipping.name,
        shipping_phone=payload.shipping.phone,
        shipping_address=payload.shipping.address_line,
        shipping_city=payload.shipping.city,
        shipping_state=payload.shipping.state,
        shipping_pincode=payload.shipping.pincode,
    )
    db.add(order)
    db.flush()

    order_items = []
    for item in cart.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        oi = OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            product_name=product.name,
            brand=product.brand,
            quantity=item.quantity,
            unit_price=item.price_at_add,
            total_price=round(item.price_at_add * item.quantity, 2),
        )
        db.add(oi)
        order_items.append(oi)

    db.commit()
    db.refresh(order)

    response_obj = OrderSummaryResponse(
        order_id=order.id,
        status=order.status,
        items=[
            OrderItemResponse(
                product_id=oi.product_id,
                product_name=oi.product_name,
                brand=oi.brand,
                quantity=oi.quantity,
                unit_price=oi.unit_price,
                total_price=oi.total_price,
            )
            for oi in order_items
        ],
        subtotal=totals["subtotal"],
        discount=totals["discount"],
        coupon_message=totals["coupon_message"],
        tax=totals["tax"],
        shipping_charge=totals["shipping_charge"],
        total=totals["total"],
        payment_methods=["card", "wallet", "upi"],
    )

    # ── Persist idempotency record ────────────────────────────────────────────
    if idempotency_key:
        record = IdempotencyRecord(
            key=idempotency_key,
            endpoint="POST /checkout",
            order_id=order.id,
            status_code=201,
            response_body=response_obj.model_dump_json(),
        )
        db.add(record)
        db.commit()

    return response_obj


# ── POST /checkout/{order_id}/pay — process payment ──────────────────────────

@router.post("/{order_id}/pay", response_model=PaymentResponse)
def pay_order(
    order_id: str,
    payload: PaymentRequest,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        description="UUID to make this payment attempt idempotent.",
    ),
):
    """
    Step 2 of checkout.
    On success: order → confirmed, inventory reduced, cart → checked_out.
    On failure: order → payment_failed (can retry with same order_id).

    **NFR — Reliability**: send `Idempotency-Key` to prevent double-charging on retries.
    """
    if idempotency_key:
        existing = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.key == idempotency_key,
            IdempotencyRecord.endpoint == f"POST /checkout/{order_id}/pay",
        ).first()
        if existing and existing.response_body:
            return PaymentResponse(**json.loads(existing.response_body))

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in ("pending", "payment_failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Order cannot be paid (current status: {order.status})",
        )

    payment_data = payload.model_dump(exclude={"method"})
    result = process_payment(payload.method, payment_data, order.total)

    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not payment:
        payment = Payment(order_id=order_id, method=payload.method, amount=order.total)
        db.add(payment)

    payment.method         = payload.method
    payment.status         = result["status"]
    payment.transaction_id = result.get("transaction_id")
    payment.gateway_ref    = result.get("gateway_ref")
    payment.failure_reason = result.get("reason")

    if result["status"] == "success":
        order.status         = "confirmed"
        order.payment_status = "success"
        order.payment_method = payload.method

        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory_count = max(0, product.inventory_count - item.quantity)

        if order.cart_id:
            cart = db.query(Cart).filter(Cart.id == order.cart_id).first()
            if cart:
                cart.status = "checked_out"

        message = f"Payment successful! Order confirmed. Transaction ID: {result['transaction_id']}"
    else:
        order.status         = "payment_failed"
        order.payment_status = "failed"
        message = f"Payment failed: {result.get('reason', 'Please try again')}"

    db.commit()

    response_obj = PaymentResponse(
        order_id=order_id,
        payment_status=result["status"],
        transaction_id=result.get("transaction_id"),
        amount=order.total,
        message=message,
    )

    if idempotency_key:
        record = IdempotencyRecord(
            key=idempotency_key,
            endpoint=f"POST /checkout/{order_id}/pay",
            order_id=order_id,
            status_code=200,
            response_body=response_obj.model_dump_json(),
        )
        db.add(record)
        db.commit()

    return response_obj


# ── GET /checkout/{order_id}/status ──────────────────────────────────────────

@router.get("/{order_id}/status")
def order_status(order_id: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment = db.query(Payment).filter(Payment.order_id == order_id).first()

    return {
        "order_id":       order.id,
        "order_status":   order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "transaction_id": payment.transaction_id if payment else None,
        "total":          order.total,
    }
