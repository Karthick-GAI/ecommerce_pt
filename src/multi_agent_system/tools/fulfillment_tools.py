"""Cart, checkout, payment status, and shipping tools for the Fulfillment Agent."""
import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from tools.shared_models import (
    Cart, CartItem, Product, CheckoutOrder, CheckoutPayment, Shipment,
)

_GST_RATE          = 0.18
_FREE_SHIPPING_MIN = 500.0
_STANDARD_SHIPPING = 49.0
_EXPRESS_SHIPPING  = 99.0


def get_cart_summary(cart_id: str, db: Session) -> str:
    cart = db.query(Cart).filter(Cart.id == cart_id).first()
    if not cart:
        return json.dumps({"error": f"Cart {cart_id} not found."})

    items = db.query(CartItem).filter(CartItem.cart_id == cart_id).all()
    if not items:
        return json.dumps({"cart_id": cart_id, "items": [], "total": 0, "status": cart.status})

    subtotal = sum((i.price_at_add or i.unit_price) * i.quantity for i in items)
    tax      = round(subtotal * _GST_RATE, 2)
    shipping = 0.0 if subtotal >= _FREE_SHIPPING_MIN else _STANDARD_SHIPPING
    total    = round(subtotal + tax + shipping, 2)

    return json.dumps({
        "cart_id": cart_id,
        "status":  cart.status,
        "items": [
            {
                "product_id":   i.product_id,
                "product_name": i.product_name,
                "quantity":     i.quantity,
                "unit_price":   i.price_at_add or i.unit_price,
                "line_total":   round((i.price_at_add or i.unit_price) * i.quantity, 2),
            }
            for i in items
        ],
        "summary": {
            "subtotal":       round(subtotal, 2),
            "gst_18pct":      tax,
            "shipping":       shipping,
            "shipping_note":  "Free shipping" if shipping == 0 else f"Standard delivery ₹{shipping}",
            "total":          total,
        },
    })


def check_product_availability(product_id: str, quantity: int, db: Session) -> str:
    p = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not p:
        return json.dumps({"available": False, "error": "Product not found."})

    available = (p.inventory_count or 0) >= quantity
    return json.dumps({
        "product_id":    product_id,
        "product_name":  p.name,
        "requested_qty": quantity,
        "stock_count":   p.inventory_count or 0,
        "available":     available,
        "message": (
            f"Yes, {quantity} unit(s) of '{p.name}' are available."
            if available
            else f"Insufficient stock. Only {p.inventory_count} unit(s) available."
        ),
    })


def calculate_order_estimate(cart_id: str, pincode: str, db: Session, coupon_code: str = None) -> str:
    cart = db.query(Cart).filter(Cart.id == cart_id).first()
    if not cart:
        return json.dumps({"error": f"Cart {cart_id} not found."})

    items    = db.query(CartItem).filter(CartItem.cart_id == cart_id).all()
    subtotal = sum((i.price_at_add or i.unit_price) * i.quantity for i in items)

    discount = 0.0
    if coupon_code:
        # Placeholder coupon logic — real implementation would query a coupons table
        coupon_discounts = {"SAVE10": 0.10, "SAVE20": 0.20, "FLAT100": None}
        if coupon_code.upper() in coupon_discounts:
            rate = coupon_discounts[coupon_code.upper()]
            discount = round(subtotal * rate, 2) if rate else 100.0
        else:
            return json.dumps({"error": f"Coupon code '{coupon_code}' is invalid."})

    discounted = subtotal - discount
    tax        = round(discounted * _GST_RATE, 2)
    shipping   = 0.0 if discounted >= _FREE_SHIPPING_MIN else _STANDARD_SHIPPING
    total      = round(discounted + tax + shipping, 2)

    return json.dumps({
        "cart_id":        cart_id,
        "delivery_pincode": pincode,
        "breakdown": {
            "subtotal":          round(subtotal, 2),
            "coupon_discount":   discount,
            "taxable_amount":    round(discounted, 2),
            "gst_18pct":         tax,
            "shipping":          shipping,
            "total":             total,
        },
        "estimated_delivery": "3-5 business days (standard)",
        "payment_methods":    ["card", "upi", "wallet"],
    })


def get_payment_status(order_id: str, db: Session) -> str:
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    payment = db.query(CheckoutPayment).filter(CheckoutPayment.order_id == order_id).first()

    return json.dumps({
        "order_id":       order_id,
        "order_status":   order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total":          order.total,
        "transaction_id": payment.transaction_id if payment else None,
        "paid_at":        str(payment.paid_at) if payment and payment.paid_at else None,
    })


def track_active_shipment(order_id: str, db: Session) -> str:
    shipment = db.query(Shipment).filter(Shipment.checkout_order_id == order_id).first()
    if not shipment:
        order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
        if not order:
            return json.dumps({"error": f"Order {order_id} not found."})
        return json.dumps({
            "order_id":     order_id,
            "order_status": order.status,
            "message":      f"No shipment booked yet. Order is currently '{order.status}'.",
        })

    return json.dumps({
        "order_id":           order_id,
        "shipment_id":        shipment.id,
        "tracking_number":    shipment.tracking_number,
        "status":             shipment.status,
        "expected_delivery":  str(shipment.expected_delivery) if shipment.expected_delivery else None,
        "actual_delivery":    str(shipment.actual_delivery) if shipment.actual_delivery else None,
        "message":            f"Shipment is currently '{shipment.status}'.",
    })


def check_return_eligibility(order_id: str, db: Session) -> str:
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    non_returnable = {"pending", "confirmed", "processing", "cancelled", "payment_failed"}
    if order.status in non_returnable:
        return json.dumps({
            "eligible": False,
            "order_status": order.status,
            "reason": f"Returns can only be initiated for delivered orders. Current status: '{order.status}'.",
        })

    if order.status == "delivered":
        shipment = db.query(Shipment).filter(Shipment.checkout_order_id == order_id).first()
        if shipment and shipment.actual_delivery:
            from datetime import datetime, timezone, timedelta
            days_since = (datetime.now(timezone.utc) - shipment.actual_delivery.replace(tzinfo=timezone.utc)).days
            if days_since > 7:
                return json.dumps({
                    "eligible": False,
                    "reason": f"Return window expired. Order was delivered {days_since} days ago (7-day policy).",
                })

        return json.dumps({
            "eligible":     True,
            "order_id":     order_id,
            "total":        order.total,
            "return_window": "7 days from delivery",
            "instructions": "Please ensure items are unused and in original packaging. We will arrange a pickup.",
        })

    return json.dumps({
        "eligible": False,
        "order_status": order.status,
        "reason": f"Order is '{order.status}'. Returns can be initiated only after delivery.",
    })


def get_delivery_estimate(pincode: str, db: Session) -> str:
    """Simple rule-based delivery estimate by pincode prefix."""
    prefix = pincode[:3] if len(pincode) >= 3 else pincode
    metro_prefixes = {"110", "400", "560", "600", "700", "500", "380", "411"}

    if prefix in metro_prefixes:
        return json.dumps({
            "pincode":           pincode,
            "standard_delivery": "2-3 business days",
            "express_delivery":  "Next day delivery available",
            "standard_cost":     "Free above ₹500, else ₹49",
            "express_cost":      "₹99",
        })
    return json.dumps({
        "pincode":           pincode,
        "standard_delivery": "4-6 business days",
        "express_delivery":  "2-3 business days",
        "standard_cost":     "Free above ₹500, else ₹49",
        "express_cost":      "₹99",
    })
