from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Cart, Order, OrderItem, Payment, Product
from schemas import (CheckoutRequest, OrderSummaryResponse,
                     PaymentRequest, PaymentResponse, OrderItemResponse)
from checkout import calculate_order_totals
from payment import process_payment

router = APIRouter(prefix="/checkout", tags=["Checkout & Payment"])


# ── POST /checkout — initiate checkout ───────────────────────────────────────

@router.post("", response_model=OrderSummaryResponse, status_code=201)
def initiate_checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    """
    Step 1 of checkout.
    - Validates cart + stock
    - Calculates subtotal, coupon discount, 18% GST, shipping
    - Creates an Order (status=pending) — no payment yet
    - Returns order_id + full price breakdown
    """
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

    # Create order record
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
    db.flush()   # get order.id before committing

    # Snapshot order items (denormalized: store name+brand at purchase time)
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

    return OrderSummaryResponse(
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


# ── POST /checkout/{order_id}/pay — process payment ──────────────────────────

@router.post("/{order_id}/pay", response_model=PaymentResponse)
def pay_order(order_id: str, payload: PaymentRequest, db: Session = Depends(get_db)):
    """
    Step 2 of checkout.
    Accepts card / wallet / UPI details and processes the payment.
    On success: order → confirmed, inventory reduced, cart → checked_out.
    On failure: order → payment_failed (can retry with same order_id).
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in ("pending", "payment_failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Order cannot be paid (current status: {order.status})",
        )

    # Process payment
    payment_data = payload.model_dump(exclude={"method"})
    result       = process_payment(payload.method, payment_data, order.total)

    # Upsert payment record
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

        # Reduce inventory for each ordered item
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory_count = max(0, product.inventory_count - item.quantity)

        # Mark cart as checked out
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

    return PaymentResponse(
        order_id=order_id,
        payment_status=result["status"],
        transaction_id=result.get("transaction_id"),
        amount=order.total,
        message=message,
    )


# ── GET /checkout/{order_id}/status — check order status ─────────────────────

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
