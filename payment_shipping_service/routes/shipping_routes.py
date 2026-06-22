"""
Shipping routes.

POST /shipping/rates                              — get live rate quotes
POST /shipping/shipments                          — create shipment
GET  /shipping/shipments/{shipment_id}            — shipment detail
GET  /shipping/shipments/by-checkout/{order_id}  — by checkout order
GET  /shipping/shipments/{shipment_id}/track      — tracking timeline
POST /shipping/shipments/{shipment_id}/cancel     — cancel shipment
"""
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import (
    CheckoutOrder, CheckoutOrderItem, Shipment, TrackingEvent, ShippingRateCache,
)
from schemas import ShippingRateRequest, CreateShipmentRequest
from providers.shipping.shiprocket import get_shiprocket

router = APIRouter(prefix="/shipping", tags=["Shipping"])

RATE_CACHE_TTL_HOURS = 6
WAREHOUSE_PINCODE = os.getenv("WAREHOUSE_PINCODE", "400069")
WAREHOUSE_CITY    = os.getenv("WAREHOUSE_CITY",    "Mumbai")


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_shipment(s: Shipment) -> dict:
    return {
        "id":                   s.id,
        "checkout_order_id":    s.checkout_order_id,
        "provider":             s.provider,
        "provider_shipment_id": s.provider_shipment_id,
        "awb_number":           s.awb_number,
        "courier_name":         s.courier_name,
        "label_url":            s.label_url,
        "origin_pincode":       s.origin_pincode,
        "destination_pincode":  s.destination_pincode,
        "destination_name":     s.destination_name,
        "weight_kg":            s.weight_kg,
        "service_type":         s.service_type,
        "rate_amount":          s.rate_amount,
        "estimated_days":       s.estimated_days,
        "status":               s.status,
        "cod":                  s.cod,
        "cod_amount":           s.cod_amount,
        "created_at":           str(s.created_at),
        "estimated_delivery":   str(s.estimated_delivery) if s.estimated_delivery else None,
        "actual_delivery":      str(s.actual_delivery)    if s.actual_delivery    else None,
    }


def _fmt_event(e: TrackingEvent) -> dict:
    return {
        "status":      e.status,
        "description": e.description,
        "location":    e.location,
        "timestamp":   str(e.timestamp) if e.timestamp else None,
    }


def _cache_key(origin: str, destination: str, weight: float, cod: bool) -> tuple:
    return (origin, destination, round(weight, 2), cod)


# ── POST /shipping/rates ──────────────────────────────────────────────────────

@router.post("/rates")
def get_shipping_rates(payload: ShippingRateRequest, db: Session = Depends(get_db)):
    """
    Returns available couriers with rates and estimated delivery days.
    Results are cached for RATE_CACHE_TTL_HOURS to avoid hammering Shiprocket.
    """
    now = datetime.now(timezone.utc)

    # Check cache
    cached = (
        db.query(ShippingRateCache)
        .filter(
            ShippingRateCache.origin_pincode      == payload.origin_pincode,
            ShippingRateCache.destination_pincode == payload.destination_pincode,
            ShippingRateCache.weight_kg           == round(payload.weight_kg, 2),
            ShippingRateCache.cod                 == (payload.cod or False),
            ShippingRateCache.valid_until         >  now,
        )
        .order_by(ShippingRateCache.created_at.desc())
        .first()
    )
    if cached:
        return {
            "origin_pincode":      payload.origin_pincode,
            "destination_pincode": payload.destination_pincode,
            "weight_kg":           payload.weight_kg,
            "cached":              True,
            "rates":               cached.rates,
        }

    sr      = get_shiprocket()
    options = sr.get_rates(
        origin_pincode=payload.origin_pincode,
        destination_pincode=payload.destination_pincode,
        weight_kg=payload.weight_kg,
        cod=payload.cod or False,
    )
    if not options:
        raise HTTPException(
            status_code=422,
            detail="No courier services available for this route. Check pincode validity.",
        )

    rates_json = [
        {
            "courier_name":   o.courier_name,
            "service_type":   o.service_type,
            "rate_amount":    o.rate_amount,
            "estimated_days": o.estimated_days,
            "cod_available":  o.cod_available,
            "courier_id":     o.courier_id,
        }
        for o in options
    ]

    # Store in cache
    db.add(ShippingRateCache(
        origin_pincode=payload.origin_pincode,
        destination_pincode=payload.destination_pincode,
        weight_kg=round(payload.weight_kg, 2),
        cod=payload.cod or False,
        rates=rates_json,
        valid_until=now + timedelta(hours=RATE_CACHE_TTL_HOURS),
    ))
    db.commit()

    return {
        "origin_pincode":      payload.origin_pincode,
        "destination_pincode": payload.destination_pincode,
        "weight_kg":           payload.weight_kg,
        "cached":              False,
        "rates":               rates_json,
    }


# ── POST /shipping/shipments ──────────────────────────────────────────────────

@router.post("/shipments", status_code=201)
def create_shipment(payload: CreateShipmentRequest, db: Session = Depends(get_db)):
    """
    Book a shipment with Shiprocket.

    If courier_id is provided, books that specific courier.
    Otherwise picks the cheapest standard-service courier.

    Call after payment is verified.
    """
    order = db.query(CheckoutOrder).filter(
        CheckoutOrder.id == payload.checkout_order_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Checkout order not found")

    # Prevent duplicate shipments (idempotency)
    existing = db.query(Shipment).filter(
        Shipment.checkout_order_id == payload.checkout_order_id,
        Shipment.status.notin_(["cancelled", "returned", "failed"]),
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A shipment already exists for this order (id={existing.id}, awb={existing.awb_number}). "
                   "Cancel it before creating a new one.",
        )

    # Auto-populate destination from checkout_orders if not provided
    dest_pincode = payload.destination_pincode or order.shipping_pincode or ""
    dest_name    = payload.destination_name    or order.shipping_name    or "Customer"
    dest_phone   = payload.destination_phone   or order.shipping_phone   or ""
    dest_address = payload.destination_address or order.shipping_address or ""

    if not dest_pincode or len(dest_pincode) != 6:
        raise HTTPException(
            status_code=422,
            detail="destination_pincode is required (or must be set on the checkout order)",
        )

    # Fetch items for the order
    items = db.query(CheckoutOrderItem).filter(
        CheckoutOrderItem.order_id == payload.checkout_order_id
    ).all()

    # Get rates to pick courier
    sr = get_shiprocket()
    origin = payload.origin_pincode or WAREHOUSE_PINCODE
    options = sr.get_rates(
        origin_pincode=origin,
        destination_pincode=dest_pincode,
        weight_kg=payload.weight_kg,
        cod=payload.cod or False,
    )

    selected_rate = None
    if payload.courier_id:
        selected_rate = next((o for o in options if o.courier_id == payload.courier_id), None)
    if selected_rate is None and options:
        # Default: cheapest standard service; fall back to cheapest overall
        standard = [o for o in options if o.service_type == (payload.service_type or "standard")]
        pool = standard if standard else options
        selected_rate = min(pool, key=lambda o: o.rate_amount)

    order_details = {
        "checkout_order_id": payload.checkout_order_id,
        "amount":            order.total,
        "weight_kg":         payload.weight_kg,
        "cod":               payload.cod or False,
        "destination": {
            "name":    dest_name,
            "address": dest_address,
            "city":    order.shipping_city  or "",
            "state":   order.shipping_state or "",
            "pincode": dest_pincode,
            "phone":   dest_phone,
        },
        "items": [
            {
                "product_id":   i.product_id,
                "product_name": i.product_name,
                "quantity":     i.quantity,
                "unit_price":   i.unit_price,
            }
            for i in items
        ],
    }

    result = sr.create_shipment(
        checkout_order_id=payload.checkout_order_id,
        order_details=order_details,
        rate=selected_rate,
    )

    now = datetime.now(timezone.utc)
    estimated_delivery = None
    if selected_rate:
        estimated_delivery = now + timedelta(days=selected_rate.estimated_days)

    shipment = Shipment(
        checkout_order_id    = payload.checkout_order_id,
        customer_id          = order.customer_id,
        provider             = "shiprocket",
        provider_shipment_id = result.provider_shipment_id,
        awb_number           = result.awb_number,
        courier_name         = result.courier_name,
        label_url            = result.label_url,
        origin_pincode       = origin,
        origin_city          = WAREHOUSE_CITY,
        destination_pincode  = dest_pincode,
        destination_address  = dest_address,
        destination_name     = dest_name,
        destination_phone    = dest_phone,
        weight_kg            = payload.weight_kg,
        length_cm            = payload.length_cm,
        breadth_cm           = payload.breadth_cm,
        height_cm            = payload.height_cm,
        service_type         = selected_rate.service_type if selected_rate else "standard",
        rate_amount          = selected_rate.rate_amount  if selected_rate else None,
        estimated_days       = selected_rate.estimated_days if selected_rate else None,
        status               = "created",
        cod                  = payload.cod or False,
        cod_amount           = payload.cod_amount if payload.cod else None,
        estimated_delivery   = estimated_delivery,
        provider_raw         = result.provider_raw,
    )
    db.add(shipment)
    db.flush()  # populate shipment.id before referencing it in TrackingEvent

    # Seed first tracking event
    db.add(TrackingEvent(
        shipment_id = shipment.id,
        awb_number  = result.awb_number,
        status      = "Shipment Created",
        description = "Shipment booked and label generated",
        location    = WAREHOUSE_CITY,
        timestamp   = now,
        raw_status  = "created",
    ))

    db.commit()
    db.refresh(shipment)

    return {
        "message":  "Shipment created successfully",
        "shipment": _fmt_shipment(shipment),
        "pickup_scheduled_at": result.pickup_scheduled_at,
    }


# ── GET /shipping/shipments/by-checkout/{checkout_order_id} ──────────────────
# Must be before /{shipment_id}

@router.get("/shipments/by-checkout/{checkout_order_id}")
def get_shipment_by_checkout(checkout_order_id: str, db: Session = Depends(get_db)):
    """Active shipment for a checkout order."""
    shipment = (
        db.query(Shipment)
        .filter(Shipment.checkout_order_id == checkout_order_id)
        .order_by(Shipment.created_at.desc())
        .first()
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="No shipment found for this order")
    return _fmt_shipment(shipment)


# ── GET /shipping/shipments/{shipment_id} ─────────────────────────────────────

@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str, db: Session = Depends(get_db)):
    s = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return _fmt_shipment(s)


# ── GET /shipping/shipments/{shipment_id}/track ───────────────────────────────

@router.get("/shipments/{shipment_id}/track")
def track_shipment(shipment_id: str, db: Session = Depends(get_db)):
    """
    Pull live tracking from Shiprocket and upsert new events into the DB.
    Returns the full event timeline.
    """
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if not shipment.awb_number:
        raise HTTPException(status_code=422, detail="Shipment has no AWB number yet")

    # Pull from provider
    sr = get_shiprocket()
    result = sr.track(shipment.awb_number)

    # Upsert tracking events — only add timestamps we haven't seen
    existing_timestamps = {
        str(e.timestamp) for e in
        db.query(TrackingEvent).filter(TrackingEvent.shipment_id == shipment_id).all()
    }
    for ev in result.events:
        ts_str = ev.timestamp
        if ts_str and ts_str not in existing_timestamps:
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                ts = None
            db.add(TrackingEvent(
                shipment_id = shipment_id,
                awb_number  = shipment.awb_number,
                status      = ev.status,
                description = ev.description,
                location    = ev.location,
                timestamp   = ts,
                raw_status  = ev.status,
            ))
            existing_timestamps.add(ts_str)

    # Update shipment status
    shipment.status = _map_tracking_status(result.current_status)
    if result.current_status.lower() in ("delivered",):
        shipment.actual_delivery = datetime.now(timezone.utc)

    db.commit()

    all_events = (
        db.query(TrackingEvent)
        .filter(TrackingEvent.shipment_id == shipment_id)
        .order_by(TrackingEvent.timestamp.desc())
        .all()
    )

    return {
        "shipment_id":       shipment_id,
        "awb_number":        shipment.awb_number,
        "courier_name":      shipment.courier_name,
        "current_status":    result.current_status,
        "estimated_delivery": str(shipment.estimated_delivery) if shipment.estimated_delivery else result.estimated_delivery,
        "events":            [_fmt_event(e) for e in all_events],
    }


# ── POST /shipping/shipments/{shipment_id}/cancel ────────────────────────────

@router.post("/shipments/{shipment_id}/cancel")
def cancel_shipment(shipment_id: str, db: Session = Depends(get_db)):
    """Cancel a shipment. Only possible before it is picked up."""
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    non_cancellable = {"delivered", "cancelled", "returned"}
    if shipment.status in non_cancellable:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel a shipment in status '{shipment.status}'",
        )

    sr = get_shiprocket()
    if shipment.awb_number:
        sr.cancel(shipment.awb_number)

    shipment.status = "cancelled"
    db.add(TrackingEvent(
        shipment_id = shipment_id,
        awb_number  = shipment.awb_number,
        status      = "Cancelled",
        description = "Shipment cancelled by seller",
        location    = "",
        timestamp   = datetime.now(timezone.utc),
        raw_status  = "cancelled",
    ))
    db.commit()

    return {"message": "Shipment cancelled", "shipment_id": shipment_id}


# ── Status normalisation ──────────────────────────────────────────────────────

_STATUS_MAP = {
    "shipment created": "created",
    "pickup scheduled": "created",
    "manifested":       "manifested",
    "picked up":        "picked_up",
    "in transit":       "in_transit",
    "out for delivery": "out_for_delivery",
    "delivered":        "delivered",
    "rto initiated":    "returned",
    "rto delivered":    "returned",
    "cancelled":        "cancelled",
    "lost":             "failed",
}


def _map_tracking_status(raw: str) -> str:
    return _STATUS_MAP.get(raw.lower(), "in_transit")
