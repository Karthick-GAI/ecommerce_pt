from models import Customer, CheckoutOrder, OrderStatusHistory, Notification

# ── Notification templates ────────────────────────────────────────────────────
# Keys: order_placed | order_confirmed | order_processing | order_shipped |
#       order_out_for_delivery | order_delivered | order_cancelled |
#       refund_initiated | refund_completed | refund_rejected

TEMPLATES = {
    "order_placed": {
        "title": "Order Placed Successfully",
        "email": "Hi {name}, your order #{short_id} for ₹{total} has been placed. We will confirm it once payment is verified.",
        "sms":   "Order #{short_id} placed for ₹{total}. You will receive a confirmation shortly.",
        "push":  "Order #{short_id} placed! Total: ₹{total}",
    },
    "order_confirmed": {
        "title": "Payment Confirmed — Order in Queue",
        "email": "Hi {name}, payment of ₹{total} via {payment_method} is confirmed for order #{short_id}. We are now preparing your order.",
        "sms":   "Payment ₹{total} confirmed. Order #{short_id} is being prepared.",
        "push":  "Payment confirmed! Order #{short_id} is being prepared.",
    },
    "order_processing": {
        "title": "Order is Being Packed",
        "email": "Hi {name}, order #{short_id} is being packed and will be shipped soon. Stay tuned!",
        "sms":   "Your order #{short_id} is being packed. Shipment update coming soon.",
        "push":  "Order #{short_id} is being packed for you.",
    },
    "order_shipped": {
        "title": "Order Shipped",
        "email": "Hi {name}, order #{short_id} has been shipped! Tracking ID: {tracking_number}. Estimated delivery: {estimated_delivery}.",
        "sms":   "Shipped! Order #{short_id} | Track: {tracking_number} | Est. delivery: {estimated_delivery}.",
        "push":  "Your order is on its way! Tracking: {tracking_number}",
    },
    "order_out_for_delivery": {
        "title": "Out for Delivery Today!",
        "email": "Hi {name}, great news! Order #{short_id} is out for delivery and will reach you today. Please keep your phone handy.",
        "sms":   "Out for delivery! Order #{short_id} arriving today. Keep your phone handy.",
        "push":  "Out for delivery! Order #{short_id} arriving today.",
    },
    "order_delivered": {
        "title": "Order Delivered",
        "email": "Hi {name}, order #{short_id} has been delivered successfully. We hope you love your purchase! Please rate your experience.",
        "sms":   "Order #{short_id} delivered. Thank you for shopping with us!",
        "push":  "Order #{short_id} delivered. Enjoy your purchase!",
    },
    "order_cancelled": {
        "title": "Order Cancelled",
        "email": "Hi {name}, order #{short_id} has been cancelled as requested. If a payment was made, a refund will be processed automatically.",
        "sms":   "Order #{short_id} cancelled. Refund (if applicable) will be processed in 3–5 business days.",
        "push":  "Order #{short_id} has been cancelled.",
    },
    "refund_initiated": {
        "title": "Refund Initiated",
        "email": "Hi {name}, a refund of ₹{amount} for order #{short_id} has been initiated. It will be credited to your {payment_method} account in 3–5 business days.",
        "sms":   "Refund ₹{amount} initiated for order #{short_id}. Credit in 3–5 business days.",
        "push":  "Refund of ₹{amount} initiated for order #{short_id}.",
    },
    "refund_completed": {
        "title": "Refund Processed Successfully",
        "email": "Hi {name}, your refund of ₹{amount} for order #{short_id} has been processed. Transaction ID: {refund_txn}.",
        "sms":   "Refund ₹{amount} processed for order #{short_id}. TXN: {refund_txn}.",
        "push":  "₹{amount} refunded for order #{short_id}!",
    },
    "refund_rejected": {
        "title": "Refund Request Rejected",
        "email": "Hi {name}, your refund request for order #{short_id} has been rejected. Reason: {reason}. Please contact support for assistance.",
        "sms":   "Refund for order #{short_id} rejected. Reason: {reason}. Contact support.",
        "push":  "Refund request for order #{short_id} was rejected.",
    },
}


def _safe_format(template: str, ctx: dict) -> str:
    try:
        return template.format(**ctx)
    except KeyError:
        return template


def send_order_notification(db, order: CheckoutOrder, event: str, extra: dict = None):
    """
    Create Notification records for all 3 channels (email, sms, push).
    Does NOT commit — caller must commit.
    """
    if not order.customer_id:
        return

    customer = db.query(Customer).filter(Customer.user_id == order.customer_id).first()
    if not customer:
        return

    tmpl = TEMPLATES.get(event)
    if not tmpl:
        return

    name = f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer"
    ctx = {
        "name":            name,
        "short_id":        order.id[:8].upper(),
        "total":           order.total,
        "payment_method":  order.payment_method or "card",
        "tracking_number": "",
        "estimated_delivery": "",
        "amount":          order.total,
        "refund_txn":      "",
        "reason":          "",
        **(extra or {}),
    }

    title = _safe_format(tmpl["title"], ctx)

    for channel in ("email", "sms", "push"):
        message = _safe_format(tmpl.get(channel, title), ctx)
        db.add(Notification(
            customer_id=order.customer_id,
            order_id=order.id,
            channel=channel,
            event=event,
            title=title,
            message=message,
        ))

    # Console simulation
    print(f"\n[EMAIL → {customer.email}] {title}")
    print(f"[SMS   → {customer.phone}] {_safe_format(tmpl['sms'], ctx)}")
    print(f"[PUSH] {_safe_format(tmpl['push'], ctx)}\n")


def ensure_registered(db, order: CheckoutOrder):
    """
    Auto-register an order in status history on first access.
    Creates the initial history entry and sends order_placed / order_confirmed
    notification if not already present.
    Does NOT commit — caller must commit.
    """
    existing = db.query(OrderStatusHistory).filter(
        OrderStatusHistory.order_id == order.id
    ).first()
    if existing:
        return

    db.add(OrderStatusHistory(
        order_id=order.id,
        from_status=None,
        to_status=order.status,
        changed_by="system",
        reason="Order registered in tracking system",
    ))

    event_map = {
        "pending":        "order_placed",
        "confirmed":      "order_confirmed",
        "processing":     "order_processing",
        "shipped":        "order_shipped",
        "out_for_delivery": "order_out_for_delivery",
        "delivered":      "order_delivered",
        "cancelled":      "order_cancelled",
    }
    event = event_map.get(order.status)
    if event and order.customer_id:
        send_order_notification(db, order, event)
