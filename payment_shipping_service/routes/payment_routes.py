"""
Payment routes.

POST   /payments/orders                              — initiate Razorpay order
GET    /payments/orders/{pay_order_id}               — status + key for frontend
GET    /payments/orders/by-checkout/{checkout_id}    — lookup by checkout order
POST   /payments/orders/{pay_order_id}/verify        — verify signature + capture
GET    /payments/transactions/{transaction_id}       — transaction detail
POST   /payments/transactions/{transaction_id}/refund — initiate refund
GET    /payments/refunds/{refund_id}                 — refund status
GET    /payments/refunds/by-checkout/{checkout_id}   — all refunds for an order
"""
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import (
    CheckoutOrder, PaymentOrder, PaymentTransaction, PaymentRefund,
)
from schemas import (
    CreatePaymentOrderRequest, VerifyPaymentRequest, RefundRequest,
)
from providers.payment.razorpay import get_razorpay

router = APIRouter(prefix="/payments", tags=["Payments"])

ORDER_EXPIRY_MINUTES = 15


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_order(o: PaymentOrder) -> dict:
    return {
        "id":                o.id,
        "checkout_order_id": o.checkout_order_id,
        "provider":          o.provider,
        "provider_order_id": o.provider_order_id,
        "provider_key_id":   o.provider_key_id,
        "amount":            o.amount,
        "currency":          o.currency,
        "status":            o.status,
        "attempts":          o.attempts,
        "created_at":        str(o.created_at),
        "expires_at":        str(o.expires_at)  if o.expires_at  else None,
        "paid_at":           str(o.paid_at)     if o.paid_at     else None,
    }


def _fmt_txn(t: PaymentTransaction) -> dict:
    return {
        "id":                  t.id,
        "pay_order_id":        t.pay_order_id,
        "checkout_order_id":   t.checkout_order_id,
        "provider_payment_id": t.provider_payment_id,
        "method":              t.method,
        "card_last4":          t.card_last4,
        "card_network":        t.card_network,
        "upi_vpa":             t.upi_vpa,
        "amount":              t.amount,
        "status":              t.status,
        "error_code":          t.error_code,
        "error_description":   t.error_description,
        "created_at":          str(t.created_at),
    }


def _fmt_refund(r: PaymentRefund) -> dict:
    return {
        "id":                 r.id,
        "transaction_id":     r.transaction_id,
        "checkout_order_id":  r.checkout_order_id,
        "provider_refund_id": r.provider_refund_id,
        "amount":             r.amount,
        "reason":             r.reason,
        "status":             r.status,
        "initiated_at":       str(r.initiated_at),
        "processed_at":       str(r.processed_at) if r.processed_at else None,
    }


# ── POST /payments/orders ─────────────────────────────────────────────────────

@router.post("/orders", status_code=201)
def create_payment_order(
    payload: CreatePaymentOrderRequest,
    db: Session = Depends(get_db),
):
    """
    Creates a Razorpay order linked to a checkout_order.
    Returns provider_order_id + provider_key_id for the frontend checkout modal.

    Flow:
      1. Client calls this → gets {provider_order_id, provider_key_id, amount}
      2. Client opens Razorpay SDK modal with these values
      3. User completes payment → Razorpay SDK returns {payment_id, signature}
      4. Client calls POST /payments/orders/{id}/verify with those values
    """
    order = db.query(CheckoutOrder).filter(
        CheckoutOrder.id == payload.checkout_order_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Checkout order not found")
    if (order.total or 0) <= 0:
        raise HTTPException(status_code=422, detail="Order amount must be positive")

    receipt = f"rcpt_{payload.checkout_order_id[:8]}_{int(datetime.now(timezone.utc).timestamp())}"
    rp = get_razorpay()
    result = rp.create_order(
        amount_inr=order.total,
        receipt=receipt,
        notes={"checkout_order_id": payload.checkout_order_id},
    )

    pay_order = PaymentOrder(
        checkout_order_id = payload.checkout_order_id,
        customer_id       = order.customer_id,
        provider          = "razorpay",
        provider_order_id = result.provider_order_id,
        provider_key_id   = rp.key_id,
        amount            = order.total,
        currency          = result.currency,
        receipt           = receipt,
        status            = result.status,
        expires_at        = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MINUTES),
        provider_raw      = result.provider_raw,
    )
    db.add(pay_order)
    db.commit()
    db.refresh(pay_order)

    return {
        **_fmt_order(pay_order),
        "frontend_config": {
            "key":      rp.key_id,
            "amount":   result.amount_paise,
            "currency": result.currency,
            "name":     "ECommerce Store",
            "order_id": result.provider_order_id,
            "receipt":  receipt,
        },
    }


# ── GET /payments/orders/by-checkout/{checkout_order_id} ─────────────────────
# Must be declared BEFORE /{pay_order_id} to prevent "by-checkout" being caught as an ID.

@router.get("/orders/by-checkout/{checkout_order_id}")
def get_payment_orders_by_checkout(checkout_order_id: str, db: Session = Depends(get_db)):
    """All payment orders for a checkout order, most recent first."""
    orders = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.checkout_order_id == checkout_order_id)
        .order_by(PaymentOrder.created_at.desc())
        .all()
    )
    if not orders:
        raise HTTPException(status_code=404, detail="No payment orders found for this checkout order")
    return {"checkout_order_id": checkout_order_id, "payment_orders": [_fmt_order(o) for o in orders]}


# ── GET /payments/orders/{pay_order_id} ──────────────────────────────────────

@router.get("/orders/{pay_order_id}")
def get_payment_order(pay_order_id: str, db: Session = Depends(get_db)):
    """Payment order status. Use provider_key_id + provider_order_id to open frontend modal."""
    o = db.query(PaymentOrder).filter(PaymentOrder.id == pay_order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Payment order not found")

    # Auto-expire if TTL passed
    if o.status == "created" and o.expires_at:
        exp = o.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            o.status = "expired"
            db.commit()

    txns = db.query(PaymentTransaction).filter(
        PaymentTransaction.pay_order_id == pay_order_id
    ).order_by(PaymentTransaction.created_at.desc()).all()

    return {
        **_fmt_order(o),
        "transactions": [_fmt_txn(t) for t in txns],
    }


# ── POST /payments/orders/{pay_order_id}/verify ───────────────────────────────

@router.post("/orders/{pay_order_id}/verify")
def verify_payment(
    pay_order_id: str,
    payload: VerifyPaymentRequest,
    db: Session = Depends(get_db),
):
    """
    Called by the frontend after the Razorpay modal completes.
    Verifies the HMAC signature, marks the order paid, and creates a transaction record.
    """
    o = db.query(PaymentOrder).filter(PaymentOrder.id == pay_order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Payment order not found")
    if o.status == "paid":
        return {"message": "Payment already verified", **_fmt_order(o)}
    if o.status == "expired":
        raise HTTPException(status_code=410, detail="Payment order has expired. Please create a new one.")

    rp     = get_razorpay()
    result = rp.verify_payment(
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature,
    )

    # Record the attempt
    o.attempts = (o.attempts or 0) + 1

    if not result.is_valid:
        # Record failed transaction
        txn = PaymentTransaction(
            pay_order_id=pay_order_id,
            checkout_order_id=o.checkout_order_id,
            customer_id=o.customer_id,
            provider_payment_id=payload.razorpay_payment_id,
            razorpay_signature=payload.razorpay_signature,
            amount=o.amount,
            status="failed",
            error_code="signature_mismatch",
            error_description="Payment signature verification failed",
        )
        db.add(txn)
        o.status = "attempted"
        db.commit()
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    # Success — create captured transaction
    txn = PaymentTransaction(
        pay_order_id         = pay_order_id,
        checkout_order_id    = o.checkout_order_id,
        customer_id          = o.customer_id,
        provider_payment_id  = result.provider_payment_id,
        razorpay_signature   = payload.razorpay_signature,
        method               = result.method,
        card_last4           = result.card_last4 or None,
        card_network         = result.card_network or None,
        upi_vpa              = result.upi_vpa or None,
        amount               = result.amount_paise / 100 if result.amount_paise else o.amount,
        status               = "captured",
        provider_raw         = result.provider_raw,
    )
    db.add(txn)

    o.status  = "paid"
    o.paid_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(txn)

    return {
        "message":       "Payment verified and captured",
        "payment_order": _fmt_order(o),
        "transaction":   _fmt_txn(txn),
    }


# ── GET /payments/transactions/{transaction_id} ───────────────────────────────

@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    t = db.query(PaymentTransaction).filter(
        PaymentTransaction.id == transaction_id
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _fmt_txn(t)


# ── POST /payments/transactions/{transaction_id}/refund ──────────────────────

@router.post("/transactions/{transaction_id}/refund", status_code=201)
def initiate_refund(
    transaction_id: str,
    payload: RefundRequest,
    db: Session = Depends(get_db),
):
    """
    Initiate a full or partial refund.
    amount=None → full refund of the transaction amount.
    """
    txn = db.query(PaymentTransaction).filter(
        PaymentTransaction.id == transaction_id
    ).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.status != "captured":
        raise HTTPException(status_code=400, detail=f"Cannot refund a {txn.status} transaction")

    refund_amount = payload.amount if payload.amount is not None else (txn.amount or 0)
    if refund_amount <= 0:
        raise HTTPException(status_code=422, detail="Refund amount must be positive")
    if txn.amount and refund_amount > txn.amount:
        raise HTTPException(status_code=422, detail="Refund amount exceeds transaction amount")

    # Check existing refunds don't exceed total
    existing_total = sum(
        r.amount for r in db.query(PaymentRefund)
        .filter(
            PaymentRefund.transaction_id == transaction_id,
            PaymentRefund.status != "failed",
        ).all()
    )
    if existing_total + refund_amount > (txn.amount or 0):
        raise HTTPException(
            status_code=422,
            detail=f"Total refunds ({existing_total + refund_amount:.2f}) would exceed transaction amount ({txn.amount:.2f})",
        )

    rp     = get_razorpay()
    result = rp.refund(
        payment_id=txn.provider_payment_id,
        amount_inr=refund_amount,
        reason=payload.reason or "Customer requested",
    )

    refund = PaymentRefund(
        transaction_id    = transaction_id,
        pay_order_id      = txn.pay_order_id,
        checkout_order_id = txn.checkout_order_id,
        customer_id       = txn.customer_id,
        provider_refund_id= result.provider_refund_id,
        amount            = refund_amount,
        reason            = payload.reason,
        notes             = payload.notes,
        status            = result.status,
        provider_raw      = result.provider_raw,
        processed_at      = datetime.now(timezone.utc) if result.status == "processed" else None,
    )
    db.add(refund)

    # If fully refunded, update transaction status
    new_total = existing_total + refund_amount
    if txn.amount and abs(new_total - txn.amount) < 0.01:
        txn.status = "refunded"

    db.commit()
    db.refresh(refund)

    return {"message": "Refund initiated", "refund": _fmt_refund(refund)}


# ── GET /payments/refunds/{refund_id} ─────────────────────────────────────────

@router.get("/refunds/{refund_id}")
def get_refund(refund_id: str, db: Session = Depends(get_db)):
    r = db.query(PaymentRefund).filter(PaymentRefund.id == refund_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Refund not found")
    return _fmt_refund(r)


# ── GET /payments/refunds/by-checkout/{checkout_order_id} ────────────────────

@router.get("/refunds/by-checkout/{checkout_order_id}")
def get_refunds_by_checkout(checkout_order_id: str, db: Session = Depends(get_db)):
    refunds = (
        db.query(PaymentRefund)
        .filter(PaymentRefund.checkout_order_id == checkout_order_id)
        .order_by(PaymentRefund.initiated_at.desc())
        .all()
    )
    total_refunded = sum(r.amount for r in refunds if r.status != "failed")
    return {
        "checkout_order_id": checkout_order_id,
        "total_refunded":    round(total_refunded, 2),
        "refunds":           [_fmt_refund(r) for r in refunds],
    }
