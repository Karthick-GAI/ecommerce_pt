"""
Webhook handlers for Razorpay and Shiprocket.

All webhooks:
  1. Verify HMAC signature immediately (reject invalid ones with 400).
  2. Store the raw payload in pay_webhook_events (for audit / replay).
  3. Apply the business logic (update order / shipment status).
  4. Return 200 quickly — providers will retry on non-200.

Idempotency: each event carries a unique entity_id; we skip duplicates.

Razorpay events handled:
  payment.captured    — mark order paid, record transaction
  payment.failed      — mark attempt failed
  refund.processed    — mark refund processed
  order.paid          — redundant but logged

Shiprocket events handled:
  SHIPMENT_PICKED_UP   — update shipment status
  IN_TRANSIT           — update shipment status
  OUT_FOR_DELIVERY     — update shipment status
  DELIVERED            — mark delivered, set actual_delivery
  RTO_INITIATED        — mark returned
  NDR                  — failed delivery attempt (logged)
"""
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session
from database import get_db
from models import (
    PaymentOrder, PaymentTransaction, PaymentRefund,
    Shipment, TrackingEvent, WebhookEvent,
)
from utils.signature import verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

RAZORPAY_WEBHOOK_SECRET  = os.getenv("RAZORPAY_WEBHOOK_SECRET",  "mock_webhook_secret")
SHIPROCKET_WEBHOOK_SECRET = os.getenv("SHIPROCKET_WEBHOOK_SECRET", "mock_webhook_secret")


# ── POST /webhooks/razorpay ───────────────────────────────────────────────────

@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db),
):
    """
    Razorpay sends signed POST requests for payment events.
    Signature: HMAC-SHA256(raw_body, webhook_secret) in X-Razorpay-Signature header.
    """
    body = await request.body()

    # Signature check (skip in mock mode for easy testing)
    mock_mode = os.getenv("MOCK_PROVIDERS", "true").lower() == "true"
    if not mock_mode:
        if not x_razorpay_signature:
            raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header")
        if not verify_webhook_signature(body, x_razorpay_signature, RAZORPAY_WEBHOOK_SECRET):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        import json
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = data.get("event", "unknown")
    entity     = data.get("payload", {})

    # Extract the relevant entity ID for idempotency
    entity_id = _extract_entity_id(event_type, entity)

    # Check for duplicate
    duplicate = db.query(WebhookEvent).filter(
        WebhookEvent.provider   == "razorpay",
        WebhookEvent.event_type == event_type,
        WebhookEvent.entity_id  == entity_id,
        WebhookEvent.status     == "processed",
    ).first()

    wh = WebhookEvent(
        provider    = "razorpay",
        event_type  = event_type,
        entity_id   = entity_id,
        payload     = data,
        status      = "duplicate" if duplicate else "received",
    )
    db.add(wh)
    db.commit()

    if duplicate:
        return {"status": "duplicate", "event": event_type}

    try:
        _handle_razorpay_event(event_type, entity, db)
        wh.status       = "processed"
        wh.processed_at = datetime.now(timezone.utc)
    except Exception as exc:
        wh.status       = "error"
        wh.error_detail = str(exc)

    db.commit()
    return {"status": "ok", "event": event_type}


def _extract_entity_id(event_type: str, entity: dict) -> str:
    if "payment" in event_type:
        return entity.get("payment", {}).get("entity", {}).get("id", "")
    if "refund" in event_type:
        return entity.get("refund", {}).get("entity", {}).get("id", "")
    if "order" in event_type:
        return entity.get("order", {}).get("entity", {}).get("id", "")
    return ""


def _handle_razorpay_event(event_type: str, entity: dict, db: Session):
    now = datetime.now(timezone.utc)

    if event_type == "payment.captured":
        payment = entity.get("payment", {}).get("entity", {})
        provider_order_id  = payment.get("order_id", "")
        provider_payment_id = payment.get("id", "")

        pay_order = db.query(PaymentOrder).filter(
            PaymentOrder.provider_order_id == provider_order_id
        ).first()
        if not pay_order:
            return

        # Avoid double-recording if verify endpoint already created the transaction
        exists = db.query(PaymentTransaction).filter(
            PaymentTransaction.provider_payment_id == provider_payment_id
        ).first()
        if not exists:
            txn = PaymentTransaction(
                pay_order_id        = pay_order.id,
                checkout_order_id   = pay_order.checkout_order_id,
                customer_id         = pay_order.customer_id,
                provider_payment_id = provider_payment_id,
                method              = payment.get("method", "unknown"),
                amount              = payment.get("amount", 0) / 100,
                status              = "captured",
                provider_raw        = payment,
            )
            db.add(txn)

        if pay_order.status != "paid":
            pay_order.status  = "paid"
            pay_order.paid_at = now

    elif event_type == "payment.failed":
        payment = entity.get("payment", {}).get("entity", {})
        provider_order_id   = payment.get("order_id", "")
        provider_payment_id = payment.get("id", "")

        pay_order = db.query(PaymentOrder).filter(
            PaymentOrder.provider_order_id == provider_order_id
        ).first()
        if pay_order and pay_order.status not in ("paid",):
            pay_order.status = "attempted"

        exists = db.query(PaymentTransaction).filter(
            PaymentTransaction.provider_payment_id == provider_payment_id
        ).first()
        if not exists:
            db.add(PaymentTransaction(
                pay_order_id        = pay_order.id if pay_order else "",
                checkout_order_id   = pay_order.checkout_order_id if pay_order else "",
                provider_payment_id = provider_payment_id,
                method              = payment.get("method", "unknown"),
                amount              = payment.get("amount", 0) / 100,
                status              = "failed",
                error_code          = payment.get("error_code", ""),
                error_description   = payment.get("error_description", ""),
                provider_raw        = payment,
            ))

    elif event_type == "refund.processed":
        refund  = entity.get("refund", {}).get("entity", {})
        refund_id = refund.get("id", "")

        r = db.query(PaymentRefund).filter(
            PaymentRefund.provider_refund_id == refund_id
        ).first()
        if r:
            r.status       = "processed"
            r.processed_at = now

    # order.paid is redundant with payment.captured — just log it (already stored)


# ── POST /webhooks/shiprocket ─────────────────────────────────────────────────

@router.post("/shiprocket")
async def shiprocket_webhook(
    request: Request,
    x_shiprocket_signature: str = Header(None, alias="X-Shiprocket-Hmac-Sha256"),
    db: Session = Depends(get_db),
):
    """
    Shiprocket sends delivery status updates via webhook.
    Signature: HMAC-SHA256(raw_body, webhook_secret) in X-Shiprocket-Hmac-Sha256 header.
    """
    body = await request.body()

    mock_mode = os.getenv("MOCK_PROVIDERS", "true").lower() == "true"
    if not mock_mode:
        if not x_shiprocket_signature:
            raise HTTPException(status_code=400, detail="Missing X-Shiprocket-Hmac-Sha256 header")
        if not verify_webhook_signature(body, x_shiprocket_signature, SHIPROCKET_WEBHOOK_SECRET):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        import json
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = data.get("event", "TRACKING_UPDATE")
    awb        = data.get("awb", "") or data.get("awb_code", "")
    entity_id  = awb

    duplicate = db.query(WebhookEvent).filter(
        WebhookEvent.provider   == "shiprocket",
        WebhookEvent.event_type == event_type,
        WebhookEvent.entity_id  == entity_id,
        WebhookEvent.status     == "processed",
    ).first()

    wh = WebhookEvent(
        provider    = "shiprocket",
        event_type  = event_type,
        entity_id   = entity_id,
        payload     = data,
        status      = "duplicate" if duplicate else "received",
    )
    db.add(wh)
    db.commit()

    if duplicate:
        return {"status": "duplicate", "event": event_type}

    try:
        _handle_shiprocket_event(event_type, awb, data, db)
        wh.status       = "processed"
        wh.processed_at = datetime.now(timezone.utc)
    except Exception as exc:
        wh.status       = "error"
        wh.error_detail = str(exc)

    db.commit()
    return {"status": "ok", "event": event_type}


def _handle_shiprocket_event(event_type: str, awb: str, data: dict, db: Session):
    if not awb:
        return

    shipment = db.query(Shipment).filter(Shipment.awb_number == awb).first()
    if not shipment:
        return

    now = datetime.now(timezone.utc)
    status_map = {
        "SHIPMENT_PICKED_UP":   ("picked_up",        "Package picked up from seller"),
        "IN_TRANSIT":           ("in_transit",        "Package in transit"),
        "OUT_FOR_DELIVERY":     ("out_for_delivery",  "Out for delivery"),
        "DELIVERED":            ("delivered",         "Package delivered successfully"),
        "RTO_INITIATED":        ("returned",          "Return to origin initiated"),
        "RTO_DELIVERED":        ("returned",          "Returned to origin"),
        "NDR":                  ("in_transit",        "Delivery attempt failed — will retry"),
        "TRACKING_UPDATE":      (None,                data.get("current_status", "")),
    }

    mapped_status, description = status_map.get(event_type, (None, event_type))

    if mapped_status:
        shipment.status = mapped_status
        if mapped_status == "delivered":
            shipment.actual_delivery = now

    db.add(TrackingEvent(
        shipment_id = shipment.id,
        awb_number  = awb,
        status      = data.get("current_status", event_type),
        description = description or data.get("current_status", ""),
        location    = data.get("city", "") or data.get("location", ""),
        timestamp   = now,
        raw_status  = event_type,
    ))


# ── GET /webhooks/events ──────────────────────────────────────────────────────

@router.get("/events")
def list_webhook_events(
    provider:   str = None,
    event_type: str = None,
    status:     str = None,
    limit:      int = 50,
    db: Session = Depends(get_db),
):
    """Admin view of all received webhook events."""
    q = db.query(WebhookEvent)
    if provider:
        q = q.filter(WebhookEvent.provider == provider)
    if event_type:
        q = q.filter(WebhookEvent.event_type == event_type)
    if status:
        q = q.filter(WebhookEvent.status == status)

    events = q.order_by(WebhookEvent.received_at.desc()).limit(limit).all()
    return {
        "total":  q.count(),
        "events": [
            {
                "id":           e.id,
                "provider":     e.provider,
                "event_type":   e.event_type,
                "entity_id":    e.entity_id,
                "status":       e.status,
                "error_detail": e.error_detail,
                "received_at":  str(e.received_at),
                "processed_at": str(e.processed_at) if e.processed_at else None,
            }
            for e in events
        ],
    }
