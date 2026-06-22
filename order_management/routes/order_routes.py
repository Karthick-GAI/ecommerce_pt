import random
import string
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import CheckoutOrder, CheckoutOrderItem, CheckoutPayment, OrderStatusHistory, Refund
from schemas import StatusUpdateRequest, OrderDetailOut, OrderItemOut, StatusHistoryItem, RefundOut
from notifications import ensure_registered, send_order_notification

router = APIRouter(prefix="/orders", tags=["Order Tracking"])

# Valid forward-only status transitions
ALLOWED_TRANSITIONS = {
    "pending":          ["confirmed", "cancelled"],
    "confirmed":        ["processing", "cancelled"],
    "processing":       ["shipped", "cancelled"],
    "shipped":          ["out_for_delivery"],
    "out_for_delivery": ["delivered"],
    "delivered":        [],
    "cancelled":        [],
    "payment_failed":   [],
}


def _tracking_number():
    return "TRCK-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def _estimated_delivery(days: int = 5) -> str:
    return (datetime.utcnow() + timedelta(days=days)).strftime("%d %b %Y")


def _build_order_detail(order: CheckoutOrder, db: Session) -> OrderDetailOut:
    items = db.query(CheckoutOrderItem).filter(
        CheckoutOrderItem.order_id == order.id
    ).all()

    payment = db.query(CheckoutPayment).filter(
        CheckoutPayment.order_id == order.id
    ).first()

    timeline = db.query(OrderStatusHistory).filter(
        OrderStatusHistory.order_id == order.id
    ).order_by(OrderStatusHistory.created_at).all()

    refund = db.query(Refund).filter(Refund.order_id == order.id).first()

    # Latest tracking number from shipped entries
    tracking_number = None
    for entry in reversed(timeline):
        if entry.tracking_number:
            tracking_number = entry.tracking_number
            break

    return OrderDetailOut(
        order_id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        transaction_id=payment.transaction_id if payment else None,
        items=[
            OrderItemOut(
                product_id=i.product_id,
                product_name=i.product_name,
                brand=i.brand,
                quantity=i.quantity,
                unit_price=i.unit_price,
                total_price=i.total_price,
            )
            for i in items
        ],
        subtotal=order.subtotal,
        discount=order.discount,
        coupon_code=order.coupon_code,
        tax=order.tax,
        shipping_charge=order.shipping_charge,
        total=order.total,
        shipping_name=order.shipping_name,
        shipping_phone=order.shipping_phone,
        shipping_address=order.shipping_address,
        shipping_city=order.shipping_city,
        shipping_state=order.shipping_state,
        shipping_pincode=order.shipping_pincode,
        created_at=str(order.created_at),
        timeline=[
            StatusHistoryItem(
                id=t.id,
                from_status=t.from_status,
                to_status=t.to_status,
                changed_by=t.changed_by,
                reason=t.reason,
                tracking_number=t.tracking_number,
                estimated_delivery=t.estimated_delivery,
                created_at=str(t.created_at),
            )
            for t in timeline
        ],
        refund=RefundOut(
            refund_id=refund.id,
            amount=refund.amount,
            status=refund.status,
            reason=refund.reason,
            original_payment_method=refund.original_payment_method,
            refund_txn_id=refund.refund_txn_id,
            rejection_reason=refund.rejection_reason,
            processed_at=str(refund.processed_at) if refund.processed_at else None,
            created_at=str(refund.created_at),
        ) if refund else None,
        tracking_number=tracking_number,
    )


# ── GET /orders/customer/{customer_id} — list orders ─────────────────────────
# Defined BEFORE /{order_id} to prevent "customer" being treated as an order_id

@router.get("/customer/{customer_id}")
def customer_orders(customer_id: str, db: Session = Depends(get_db)):
    orders = (
        db.query(CheckoutOrder)
        .filter(CheckoutOrder.customer_id == customer_id)
        .order_by(CheckoutOrder.created_at.desc())
        .all()
    )
    return {
        "customer_id":  customer_id,
        "total_orders": len(orders),
        "orders": [
            {
                "order_id":       o.id,
                "status":         o.status,
                "payment_status": o.payment_status,
                "total":          o.total,
                "item_count":     db.query(CheckoutOrderItem).filter(
                                      CheckoutOrderItem.order_id == o.id
                                  ).count(),
                "created_at": str(o.created_at),
            }
            for o in orders
        ],
    }


# ── GET /orders/{order_id} — full detail with timeline ───────────────────────

@router.get("/{order_id}", response_model=OrderDetailOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    ensure_registered(db, order)
    db.commit()

    return _build_order_detail(order, db)


# ── GET /orders/{order_id}/timeline — status history ─────────────────────────

@router.get("/{order_id}/timeline")
def get_timeline(order_id: str, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    ensure_registered(db, order)
    db.commit()

    timeline = db.query(OrderStatusHistory).filter(
        OrderStatusHistory.order_id == order_id
    ).order_by(OrderStatusHistory.created_at).all()

    return {
        "order_id":       order_id,
        "current_status": order.status,
        "timeline": [
            {
                "from_status":        t.from_status,
                "to_status":          t.to_status,
                "changed_by":         t.changed_by,
                "reason":             t.reason,
                "tracking_number":    t.tracking_number,
                "estimated_delivery": t.estimated_delivery,
                "timestamp":          str(t.created_at),
            }
            for t in timeline
        ],
    }


# ── POST /orders/{order_id}/register — register in tracking ──────────────────

@router.post("/{order_id}/register", status_code=201)
def register_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    ensure_registered(db, order)
    db.commit()

    return {
        "message":  "Order registered in tracking system",
        "order_id": order_id,
        "status":   order.status,
    }


# ── POST /orders/{order_id}/status — admin: update status ────────────────────

@router.post("/{order_id}/status")
def update_status(order_id: str, payload: StatusUpdateRequest, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    allowed = ALLOWED_TRANSITIONS.get(order.status, [])
    if payload.to_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{order.status}' to '{payload.to_status}'. "
                   f"Allowed next statuses: {allowed}",
        )

    ensure_registered(db, order)

    tracking_number    = None
    estimated_delivery = None

    if payload.to_status == "shipped":
        tracking_number    = _tracking_number()
        estimated_delivery = _estimated_delivery(days=5)

    history = OrderStatusHistory(
        order_id=order_id,
        from_status=order.status,
        to_status=payload.to_status,
        changed_by=payload.changed_by,
        reason=payload.reason,
        tracking_number=tracking_number,
        estimated_delivery=estimated_delivery,
    )
    db.add(history)

    old_status   = order.status
    order.status = payload.to_status

    event_map = {
        "confirmed":        "order_confirmed",
        "processing":       "order_processing",
        "shipped":          "order_shipped",
        "out_for_delivery": "order_out_for_delivery",
        "delivered":        "order_delivered",
    }
    event = event_map.get(payload.to_status)
    if event and order.customer_id:
        extra = {}
        if tracking_number:
            extra["tracking_number"]    = tracking_number
            extra["estimated_delivery"] = estimated_delivery
        send_order_notification(db, order, event, extra)

    db.commit()

    return {
        "message":          f"Order status updated: {old_status} → {payload.to_status}",
        "order_id":         order_id,
        "status":           order.status,
        "tracking_number":  tracking_number,
        "estimated_delivery": estimated_delivery,
    }
