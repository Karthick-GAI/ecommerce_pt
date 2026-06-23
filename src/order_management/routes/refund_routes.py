from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import CheckoutOrder, Refund
from schemas import RefundRequest, RefundActionRequest
from notifications import send_order_notification
from refund import process_refund_simulation

router = APIRouter(tags=["Refunds"])


# ── POST /orders/{order_id}/refund — initiate refund ─────────────────────────

@router.post("/orders/{order_id}/refund", status_code=201)
def initiate_refund(order_id: str, payload: RefundRequest, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status != "success":
        raise HTTPException(status_code=400, detail="No successful payment found for this order to refund")

    if order.status not in ("cancelled", "delivered"):
        raise HTTPException(
            status_code=400,
            detail="Refunds can only be initiated for cancelled or delivered orders",
        )

    existing = db.query(Refund).filter(Refund.order_id == order_id).first()
    if existing and existing.status in ("pending", "approved", "completed"):
        raise HTTPException(
            status_code=409,
            detail=f"A refund already exists for this order (status: {existing.status})",
        )

    amount = payload.amount if payload.amount is not None and payload.amount <= order.total else order.total

    refund = Refund(
        order_id=order_id,
        amount=amount,
        reason=payload.reason or "Customer requested refund",
        status="pending",
        original_payment_method=order.payment_method,
    )
    db.add(refund)

    send_order_notification(db, order, "refund_initiated", {"amount": amount})

    db.commit()
    db.refresh(refund)

    return {
        "refund_id":        refund.id,
        "order_id":         order_id,
        "amount":           amount,
        "status":           refund.status,
        "payment_method":   order.payment_method,
        "message":          "Refund request submitted. Pending admin approval.",
    }


# ── GET /orders/{order_id}/refund — refund status ────────────────────────────

@router.get("/orders/{order_id}/refund")
def get_refund(order_id: str, db: Session = Depends(get_db)):
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    refund = db.query(Refund).filter(Refund.order_id == order_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="No refund found for this order")

    return {
        "refund_id":                refund.id,
        "order_id":                 order_id,
        "amount":                   refund.amount,
        "status":                   refund.status,
        "reason":                   refund.reason,
        "original_payment_method":  refund.original_payment_method,
        "refund_txn_id":            refund.refund_txn_id,
        "rejection_reason":         refund.rejection_reason,
        "processed_at":             str(refund.processed_at) if refund.processed_at else None,
        "created_at":               str(refund.created_at),
    }


# ── POST /refunds/{refund_id}/approve — admin: approve and process ────────────

@router.post("/refunds/{refund_id}/approve")
def approve_refund(refund_id: str, db: Session = Depends(get_db)):
    refund = db.query(Refund).filter(Refund.id == refund_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")

    if refund.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve refund with status '{refund.status}'. Only pending refunds can be approved.",
        )

    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == refund.order_id).first()

    result = process_refund_simulation(refund.amount, refund.original_payment_method or "card")

    if result["status"] == "completed":
        refund.status        = "completed"
        refund.refund_txn_id = result["txn_id"]
        refund.processed_at  = datetime.utcnow()

        if order:
            send_order_notification(db, order, "refund_completed", {
                "amount":    refund.amount,
                "refund_txn": result["txn_id"],
            })
    else:
        refund.status           = "rejected"
        refund.rejection_reason = result.get("reason", "Processing failed")
        refund.processed_at     = datetime.utcnow()

        if order:
            send_order_notification(db, order, "refund_rejected", {
                "reason": refund.rejection_reason,
            })

    db.commit()

    return {
        "refund_id":     refund_id,
        "status":        refund.status,
        "refund_txn_id": refund.refund_txn_id,
        "message":       result.get("message", "Refund processed"),
    }


# ── POST /refunds/{refund_id}/reject — admin: reject refund ──────────────────

@router.post("/refunds/{refund_id}/reject")
def reject_refund(refund_id: str, payload: RefundActionRequest, db: Session = Depends(get_db)):
    refund = db.query(Refund).filter(Refund.id == refund_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")

    if refund.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject refund with status '{refund.status}'. Only pending refunds can be rejected.",
        )

    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == refund.order_id).first()

    refund.status           = "rejected"
    refund.rejection_reason = payload.reason or "Rejected by admin"
    refund.processed_at     = datetime.utcnow()

    if order:
        send_order_notification(db, order, "refund_rejected", {
            "reason": refund.rejection_reason,
        })

    db.commit()

    return {
        "refund_id":        refund_id,
        "status":           "rejected",
        "rejection_reason": refund.rejection_reason,
    }
