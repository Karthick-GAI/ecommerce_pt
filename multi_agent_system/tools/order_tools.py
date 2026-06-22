"""Order lookup, tracking, and cancellation tools."""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from tools.shared_models import (
    CheckoutOrder, CheckoutOrderItem, CheckoutPayment,
    OrderStatusHistory, Refund, Shipment,
)


def lookup_order(order_id: str, db: Session) -> str:
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    items = db.query(CheckoutOrderItem).filter(CheckoutOrderItem.order_id == order_id).all()
    payment = db.query(CheckoutPayment).filter(CheckoutPayment.order_id == order_id).first()

    return json.dumps({
        "order_id":       order.id,
        "status":         order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total":          order.total,
        "subtotal":       order.subtotal,
        "tax":            order.tax,
        "shipping_charge": order.shipping_charge,
        "discount":       order.discount,
        "items": [
            {
                "product_name": i.product_name,
                "quantity":     i.quantity,
                "unit_price":   i.unit_price,
                "total_price":  i.total_price,
            }
            for i in items
        ],
        "shipping_address": {
            "name":    order.shipping_name,
            "phone":   order.shipping_phone,
            "address": order.shipping_address,
            "city":    order.shipping_city,
            "state":   order.shipping_state,
            "pincode": order.shipping_pincode,
        },
        "payment_transaction_id": payment.transaction_id if payment else None,
        "created_at": str(order.created_at),
    })


def get_customer_orders(customer_id: str, db: Session, limit: int = 5) -> str:
    orders = (
        db.query(CheckoutOrder)
        .filter(CheckoutOrder.customer_id == customer_id)
        .order_by(CheckoutOrder.created_at.desc())
        .limit(min(limit, 10))
        .all()
    )
    if not orders:
        return json.dumps({"orders": [], "message": "No orders found for this customer."})

    return json.dumps({
        "orders": [
            {
                "order_id":       o.id,
                "status":         o.status,
                "payment_status": o.payment_status,
                "total":          o.total,
                "created_at":     str(o.created_at),
            }
            for o in orders
        ],
        "total_found": len(orders),
    })


def get_order_timeline(order_id: str, db: Session) -> str:
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    history = (
        db.query(OrderStatusHistory)
        .filter(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at.asc())
        .all()
    )

    shipment = db.query(Shipment).filter(Shipment.checkout_order_id == order_id).first()

    return json.dumps({
        "order_id":        order.id,
        "current_status":  order.status,
        "timeline": [
            {
                "status":          h.status,
                "note":            h.note,
                "tracking_number": h.tracking_number,
                "timestamp":       str(h.created_at),
            }
            for h in history
        ],
        "shipment": {
            "provider_shipment_id": shipment.provider_shipment_id,
            "tracking_number":      shipment.tracking_number,
            "status":               shipment.status,
            "expected_delivery":    str(shipment.expected_delivery) if shipment.expected_delivery else None,
        } if shipment else None,
    })


def check_refund_eligibility(order_id: str, db: Session) -> str:
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    non_refundable_statuses = {"pending", "payment_failed", "cancelled"}
    if order.status in non_refundable_statuses:
        return json.dumps({
            "eligible": False,
            "reason": f"Orders with status '{order.status}' are not eligible for refund.",
        })

    if order.payment_status != "paid":
        return json.dumps({
            "eligible": False,
            "reason": "Order has not been paid.",
        })

    existing_refund = db.query(Refund).filter(Refund.order_id == order_id).first()
    if existing_refund:
        return json.dumps({
            "eligible": False,
            "reason":  f"A refund already exists with status '{existing_refund.status}'.",
            "refund_id": existing_refund.id,
        })

    return json.dumps({
        "eligible":   True,
        "order_id":   order_id,
        "amount":     order.total,
        "status":     order.status,
        "reason":     "Order qualifies for refund under our 7-day return policy.",
    })


def get_refund_status(order_id: str, db: Session) -> str:
    refund = db.query(Refund).filter(Refund.order_id == order_id).first()
    if not refund:
        return json.dumps({"message": "No refund found for this order.", "order_id": order_id})

    return json.dumps({
        "refund_id":    refund.id,
        "order_id":     order_id,
        "amount":       refund.amount,
        "status":       refund.status,
        "reason":       refund.reason,
        "created_at":   str(refund.created_at),
        "processed_at": str(refund.processed_at) if refund.processed_at else None,
    })
