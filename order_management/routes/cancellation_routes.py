from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import CheckoutOrder, CheckoutOrderItem, OrderStatusHistory, Refund, Product
from schemas import CancellationRequest
from notifications import ensure_registered, send_order_notification

router = APIRouter(prefix="/orders", tags=["Cancellation"])


@router.post("/{order_id}/cancel")
def cancel_order(order_id: str, payload: CancellationRequest, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in ("pending", "confirmed", "processing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order with status '{order.status}'. "
                   "Only pending, confirmed, or processing orders can be cancelled.",
        )

    existing_refund = db.query(Refund).filter(Refund.order_id == order_id).first()
    if existing_refund and existing_refund.status in ("pending", "approved", "completed"):
        raise HTTPException(status_code=400, detail="A refund is already in progress for this order")

    ensure_registered(db, order)

    # Restore inventory for confirmed / processing orders
    if order.status in ("confirmed", "processing"):
        items = db.query(CheckoutOrderItem).filter(
            CheckoutOrderItem.order_id == order_id
        ).all()
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory_count += item.quantity

    old_status   = order.status
    order.status = "cancelled"

    db.add(OrderStatusHistory(
        order_id=order_id,
        from_status=old_status,
        to_status="cancelled",
        changed_by=payload.cancelled_by,
        reason=payload.reason,
    ))

    send_order_notification(db, order, "order_cancelled")

    # Auto-initiate refund if payment was successful
    refund_initiated = False
    if order.payment_status == "success":
        refund = Refund(
            order_id=order_id,
            amount=order.total,
            reason=f"Order cancelled: {payload.reason}",
            status="pending",
            original_payment_method=order.payment_method,
        )
        db.add(refund)
        refund_initiated = True
        send_order_notification(db, order, "refund_initiated", {"amount": order.total})

    db.commit()

    return {
        "message":          "Order cancelled successfully",
        "order_id":         order_id,
        "refund_initiated": refund_initiated,
        "refund_amount":    order.total if refund_initiated else None,
        "note": (
            "A refund has been automatically initiated and is pending approval."
            if refund_initiated
            else "No payment was collected so no refund is needed."
        ),
    }


@router.get("/{order_id}/cancellation")
def get_cancellation(order_id: str, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "cancelled":
        return {
            "order_id": order_id,
            "cancelled": False,
            "message": f"Order is not cancelled (current status: {order.status})",
        }

    cancellation_entry = (
        db.query(OrderStatusHistory)
        .filter(
            OrderStatusHistory.order_id == order_id,
            OrderStatusHistory.to_status == "cancelled",
        )
        .order_by(OrderStatusHistory.created_at.desc())
        .first()
    )

    refund = db.query(Refund).filter(Refund.order_id == order_id).first()

    return {
        "order_id":     order_id,
        "cancelled":    True,
        "cancelled_at": str(cancellation_entry.created_at) if cancellation_entry else None,
        "cancelled_by": cancellation_entry.changed_by if cancellation_entry else None,
        "reason":       cancellation_entry.reason if cancellation_entry else None,
        "refund": {
            "refund_id":    refund.id,
            "amount":       refund.amount,
            "status":       refund.status,
            "txn_id":       refund.refund_txn_id,
            "processed_at": str(refund.processed_at) if refund.processed_at else None,
        } if refund else None,
    }
