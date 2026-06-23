"""
Order lookup tools.

lookup_order         — full order detail by order_id (checkout service orders)
get_customer_orders  — recent orders for a customer
get_order_tracking   — status timeline with tracking numbers and refund info
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import (
    CheckoutOrder, CheckoutOrderItem, CheckoutPayment,
    OrderStatusHistory, OrderRefund, Customer, DatasetOrder,
)


def lookup_order(db: Session, order_id: str) -> dict:
    """
    Look up a checkout service order by its ID.
    Returns items, payment, status, and shipping details.
    Falls back to dataset orders if not found in checkout service.
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()

    if order:
        items = db.query(CheckoutOrderItem).filter(
            CheckoutOrderItem.order_id == order_id
        ).all()

        payment = db.query(CheckoutPayment).filter(
            CheckoutPayment.order_id == order_id
        ).order_by(CheckoutPayment.created_at.desc()).first()

        latest_history = db.query(OrderStatusHistory).filter(
            OrderStatusHistory.order_id == order_id
        ).order_by(OrderStatusHistory.created_at.desc()).first()

        return {
            "found": True,
            "source": "checkout_service",
            "order_id":       order.id,
            "status":         order.status,
            "payment_status": order.payment_status,
            "payment_method": order.payment_method,
            "total":          order.total,
            "shipping_city":  order.shipping_city,
            "shipping_state": order.shipping_state,
            "placed_at":      str(order.created_at),
            "tracking_number": latest_history.tracking_number if latest_history else None,
            "estimated_delivery": latest_history.estimated_delivery if latest_history else None,
            "items": [
                {
                    "product_name": i.product_name,
                    "brand":        i.brand,
                    "quantity":     i.quantity,
                    "unit_price":   i.unit_price,
                    "total_price":  i.total_price,
                }
                for i in items
            ],
            "payment": {
                "method":         payment.method,
                "status":         payment.status,
                "amount":         payment.amount,
                "transaction_id": payment.transaction_id,
            } if payment else None,
        }

    # Fallback: check dataset orders
    d_order = db.query(DatasetOrder).filter(DatasetOrder.order_id == order_id).first()
    if d_order:
        cart = d_order.cart_activity or []
        return {
            "found": True,
            "source": "dataset",
            "order_id":       d_order.order_id,
            "status":         d_order.order_status,
            "payment_status": d_order.payment_status,
            "shipment_status": d_order.shipment_status,
            "total":          d_order.total_amount,
            "placed_at":      str(d_order.created_at),
            "item_count":     len(cart),
            "items": [
                {
                    "product_id":  item.get("product_id"),
                    "quantity":    item.get("quantity"),
                    "unit_price":  item.get("unit_price"),
                }
                for item in cart
            ],
        }

    return {"found": False, "order_id": order_id,
            "message": "Order not found. Please verify the order ID."}


def get_customer_orders(db: Session, customer_id: str, limit: int = 5) -> dict:
    """
    Retrieve the most recent orders for a customer.
    Checks both checkout service orders and dataset orders.
    """
    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if not customer:
        return {"found": False,
                "message": f"Customer {customer_id} not found."}

    # Checkout service orders
    checkout_orders = (
        db.query(CheckoutOrder)
        .filter(CheckoutOrder.customer_id == customer_id)
        .order_by(CheckoutOrder.created_at.desc())
        .limit(limit)
        .all()
    )

    checkout_list = []
    for o in checkout_orders:
        items = db.query(CheckoutOrderItem).filter(
            CheckoutOrderItem.order_id == o.id
        ).all()
        checkout_list.append({
            "order_id":       o.id,
            "source":         "checkout_service",
            "status":         o.status,
            "payment_status": o.payment_status,
            "total":          o.total,
            "item_count":     len(items),
            "items_summary":  [i.product_name for i in items[:3]],
            "placed_at":      str(o.created_at),
        })

    # Dataset orders (for richer history)
    sql = text("""
        SELECT order_id, order_status, payment_status, total_amount,
               jsonb_array_length(cart_activity) AS item_count, created_at
        FROM orders
        WHERE user_id = :cid
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    dataset_rows = db.execute(sql, {"cid": customer_id, "limit": limit}).fetchall()
    dataset_list = [
        {
            "order_id":       r.order_id,
            "source":         "dataset",
            "status":         r.order_status,
            "payment_status": r.payment_status,
            "total":          r.total_amount,
            "item_count":     r.item_count,
            "placed_at":      str(r.created_at),
        }
        for r in dataset_rows
    ]

    all_orders = checkout_list + dataset_list
    all_orders.sort(key=lambda x: x["placed_at"], reverse=True)

    return {
        "found": True,
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "customer_id":   customer_id,
        "total_shown":   len(all_orders),
        "orders":        all_orders[:limit],
    }


def get_order_tracking(db: Session, order_id: str) -> dict:
    """
    Get the full status timeline for an order including tracking numbers,
    refund information, and estimated delivery.
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return {"found": False, "order_id": order_id,
                "message": "Order not found in checkout service."}

    timeline = (
        db.query(OrderStatusHistory)
        .filter(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at)
        .all()
    )

    refund = (
        db.query(OrderRefund)
        .filter(OrderRefund.order_id == order_id)
        .order_by(OrderRefund.created_at.desc())
        .first()
    )

    return {
        "found": True,
        "order_id":       order_id,
        "current_status": order.status,
        "placed_at":      str(order.created_at),
        "timeline": [
            {
                "from_status":       t.from_status,
                "to_status":         t.to_status,
                "tracking_number":   t.tracking_number,
                "estimated_delivery": t.estimated_delivery,
                "changed_by":        t.changed_by,
                "reason":            t.reason,
                "at":                str(t.created_at),
            }
            for t in timeline
        ],
        "refund": {
            "refund_id":     refund.id,
            "amount":        refund.amount,
            "status":        refund.status,
            "reason":        refund.reason,
            "txn_id":        refund.refund_txn_id,
            "processed_at":  str(refund.processed_at) if refund.processed_at else None,
        } if refund else None,
    }
