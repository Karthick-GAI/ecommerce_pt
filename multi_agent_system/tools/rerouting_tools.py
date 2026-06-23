"""
Rerouting tools — read/write operations used by the three rerouting agents.

All tools return JSON strings consistent with the existing tool pattern.
The two write tools (apply_reroute_decision, cancel_order_and_refund) are
only called after the full 3-agent analysis validates feasibility.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text

from tools.shared_models import (
    Product, CheckoutOrder, CheckoutOrderItem,
    OrderStatusHistory, Refund,
)


# ── ASSESSMENT ─────────────────────────────────────────────────────────────────

def assess_order_stockout(order_id: str, db: Session) -> str:
    """
    Inspect every line item of an order and identify stock shortfalls.
    Returns a full picture: which items are fine and which are blocked.
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    items = (
        db.query(CheckoutOrderItem)
        .filter(CheckoutOrderItem.order_id == order_id)
        .all()
    )

    stockout_items: list[dict] = []
    ok_items:       list[dict] = []

    for item in items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            stockout_items.append({
                "product_id":      item.product_id,
                "product_name":    item.product_name,
                "category":        "",
                "brand":           "",
                "requested_qty":   item.quantity,
                "available_stock": 0,
                "unit_price":      item.unit_price,
                "reason":          "product_not_found",
            })
        elif (product.inventory_count or 0) < item.quantity:
            stockout_items.append({
                "product_id":      product.id,
                "product_name":    product.name,
                "category":        product.category,
                "brand":           product.brand,
                "requested_qty":   item.quantity,
                "available_stock": product.inventory_count or 0,
                "unit_price":      product.price,
                "reason":          "insufficient_stock",
            })
        else:
            ok_items.append({
                "product_id":      product.id,
                "product_name":    product.name,
                "requested_qty":   item.quantity,
                "available_stock": product.inventory_count or 0,
            })

    return json.dumps({
        "order_id":          order_id,
        "order_status":      order.status,
        "customer_id":       order.customer_id,
        "order_total":       order.total,
        "shipping_pincode":  order.shipping_pincode,
        "stockout_detected": len(stockout_items) > 0,
        "stockout_items":    stockout_items,
        "ok_items":          ok_items,
    })


# ── INVENTORY SEARCH ───────────────────────────────────────────────────────────

def find_alternative_products(
    product_id: str,
    db: Session,
    category: str | None = None,
    max_price_premium_pct: float = 20.0,
    required_qty: int = 1,
) -> str:
    """
    Find in-stock substitutes for an out-of-stock product.

    Searches within the same category, within ±20% of the original price by
    default. Results are sorted by rating and stock depth to surface the best
    substitute first.
    """
    original = db.query(Product).filter(Product.id == product_id).first()
    if not original:
        return json.dumps({"error": f"Product {product_id} not found."})

    search_category = category or original.category
    max_price = original.price * (1 + max_price_premium_pct / 100)
    min_price = original.price * 0.70  # allow up to 30% cheaper

    alternatives = (
        db.query(Product)
        .filter(
            Product.category == search_category,
            Product.id != product_id,
            Product.is_active == True,
            Product.inventory_count >= required_qty,
            Product.price.between(min_price, max_price),
        )
        .order_by(Product.rating_avg.desc(), Product.inventory_count.desc())
        .limit(5)
        .all()
    )

    return json.dumps({
        "original_product_id": product_id,
        "original_name":       original.name,
        "original_price":      original.price,
        "required_qty":        required_qty,
        "alternatives": [
            {
                "product_id":      alt.id,
                "name":            alt.name,
                "brand":           alt.brand,
                "price":           alt.price,
                "price_diff_pct":  round((alt.price - original.price) / original.price * 100, 1),
                "stock_count":     alt.inventory_count,
                "rating":          alt.rating_avg,
                "is_recommended":  (alt.rating_avg or 0) >= 4.0 and alt.inventory_count >= 5,
            }
            for alt in alternatives
        ],
        "alternatives_count": len(alternatives),
        "has_alternatives":   len(alternatives) > 0,
    })


def check_warehouse_stock(product_id: str, db: Session) -> str:
    """
    Return current stock depth and recent movement summary for a product.
    Used by the InventoryAgent to verify a candidate substitute is really available.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return json.dumps({"error": f"Product {product_id} not found."})

    try:
        row = db.execute(text("""
            SELECT
                SUM(CASE WHEN quantity_change > 0 THEN quantity_change ELSE 0 END) AS inbound_30d,
                SUM(CASE WHEN quantity_change < 0 THEN ABS(quantity_change) ELSE 0 END) AS outbound_30d
            FROM inventory_movements
            WHERE product_id = :pid
              AND created_at >= NOW() - INTERVAL '30 days'
        """), {"pid": product_id}).fetchone()
        inbound  = int(row.inbound_30d  or 0)
        outbound = int(row.outbound_30d or 0)
    except Exception:
        inbound, outbound = 0, 0

    current = product.inventory_count or 0
    health  = (
        "healthy"  if current > 20
        else "low" if current > 5
        else "critical"
    )

    return json.dumps({
        "product_id":            product_id,
        "product_name":          product.name,
        "category":              product.category,
        "total_available_stock": current,
        "fulfillment_ready":     current >= 1,
        "stock_health":          health,
        "inbound_30d":           inbound,
        "outbound_30d":          outbound,
    })


# ── LOGISTICS PLANNING ─────────────────────────────────────────────────────────

def create_logistics_reroute_plan(
    order_id: str,
    original_product_id: str,
    substitute_product_id: str,
    db: Session,
) -> str:
    """
    Validate feasibility and build the complete logistics plan for rerouting
    one line item to a substitute product.

    Checks stock sufficiency, computes price delta, and estimates delivery ETA.
    Does NOT modify any data — all writes happen in apply_reroute_decision.
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    original   = db.query(Product).filter(Product.id == original_product_id).first()
    substitute = db.query(Product).filter(Product.id == substitute_product_id).first()

    if not original or not substitute:
        return json.dumps({"feasible": False, "error": "One or both products not found."})

    item = (
        db.query(CheckoutOrderItem)
        .filter(
            CheckoutOrderItem.order_id == order_id,
            CheckoutOrderItem.product_id == original_product_id,
        )
        .first()
    )
    qty = item.quantity if item else 1

    if substitute.inventory_count < qty:
        return json.dumps({
            "feasible": False,
            "reason": (
                f"Substitute '{substitute.name}' has only {substitute.inventory_count} "
                f"units; order needs {qty}."
            ),
        })

    price_delta = round((substitute.price - original.price) * qty, 2)

    pincode = order.shipping_pincode or ""
    metro   = {"110", "400", "560", "600", "700", "500", "380", "411"}
    eta_days = 2 if pincode[:3] in metro else 5

    customer_impact = (
        "no_additional_charge" if price_delta <= 0
        else f"customer_billed_extra_inr_{price_delta}"
    )

    return json.dumps({
        "feasible": True,
        "order_id": order_id,
        "reroute_plan": {
            "original_product": {
                "product_id":    original_product_id,
                "name":          original.name,
                "price":         original.price,
            },
            "substitute_product": {
                "product_id":    substitute_product_id,
                "name":          substitute.name,
                "price":         substitute.price,
                "stock_count":   substitute.inventory_count,
            },
            "quantity":              qty,
            "price_delta_inr":       price_delta,
            "customer_impact":       customer_impact,
            "fulfillment_eta_days":  eta_days,
            "delivery_pincode":      pincode,
        },
    })


# ── WRITE OPERATIONS ───────────────────────────────────────────────────────────

def apply_reroute_decision(
    order_id: str,
    original_product_id: str,
    substitute_product_id: str,
    db: Session,
    reason: str = "Autonomous agent reroute — original item out of stock",
) -> str:
    """
    Apply the reroute: swap the order line item to the substitute product.

    Actions:
      • Update CheckoutOrderItem.product_id, name, unit_price, total_price
      • Deduct substitute product stock
      • Adjust order.total if price delta != 0
      • Append a timestamped note to OrderStatusHistory for full audit trail
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    original   = db.query(Product).filter(Product.id == original_product_id).first()
    substitute = db.query(Product).filter(Product.id == substitute_product_id).first()

    if not original or not substitute:
        return json.dumps({"applied": False, "error": "Product not found."})

    item = (
        db.query(CheckoutOrderItem)
        .filter(
            CheckoutOrderItem.order_id == order_id,
            CheckoutOrderItem.product_id == original_product_id,
        )
        .first()
    )
    if not item:
        return json.dumps({
            "applied": False,
            "error": f"No line item for product {original_product_id} in order {order_id}.",
        })

    qty = item.quantity
    if substitute.inventory_count < qty:
        return json.dumps({
            "applied": False,
            "error": f"Substitute has {substitute.inventory_count} units; need {qty}.",
        })

    # Swap line item
    old_unit_price = item.unit_price
    item.product_id   = substitute.id
    item.product_name = substitute.name
    item.unit_price   = substitute.price
    item.total_price  = round(substitute.price * qty, 2)

    # Deduct substitute stock
    substitute.inventory_count -= qty

    # Adjust order total
    price_delta = round((substitute.price - old_unit_price) * qty, 2)
    if price_delta != 0:
        order.total = round(order.total + price_delta, 2)

    # Audit trail
    note = (
        f"[A2A-REROUTE] {original.name} (stock: 0) → {substitute.name} "
        f"(stock: {substitute.inventory_count + qty}→{substitute.inventory_count}). "
        f"Qty: {qty}. Price delta: ₹{price_delta:+.2f}. Reason: {reason}"
    )
    db.add(OrderStatusHistory(
        id=str(uuid.uuid4()),
        order_id=order_id,
        status=order.status,
        note=note,
    ))

    db.commit()

    return json.dumps({
        "applied":            True,
        "order_id":           order_id,
        "original_product":   original.name,
        "substitute_product": substitute.name,
        "quantity":           qty,
        "price_delta_inr":    price_delta,
        "new_order_total":    order.total,
        "inventory_deducted": True,
        "audit_note":         note,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    })


def cancel_order_and_refund(
    order_id: str,
    db: Session,
    reason: str = "No viable substitute found — autonomous cancel",
) -> str:
    """
    Last-resort action: cancel the order and queue a full refund.
    Called only when no substitute product is available AND no warehouse
    alternative exists.
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    if order.status in ("delivered", "cancelled"):
        return json.dumps({
            "cancelled": False,
            "reason": f"Cannot cancel an order with status '{order.status}'.",
        })

    order.status = "cancelled"
    if order.payment_status == "paid":
        order.payment_status = "refund_pending"

    db.add(OrderStatusHistory(
        id=str(uuid.uuid4()),
        order_id=order_id,
        status="cancelled",
        note=f"[A2A-CANCEL] {reason}",
    ))

    refund_id = None
    if order.payment_status == "refund_pending":
        refund = Refund(
            id=str(uuid.uuid4()),
            order_id=order_id,
            amount=order.total,
            reason=f"Automatic refund — {reason}",
            status="pending",
        )
        db.add(refund)
        refund_id = refund.id

    db.commit()

    return json.dumps({
        "cancelled":     True,
        "order_id":      order_id,
        "reason":        reason,
        "refund_id":     refund_id,
        "refund_amount": order.total if refund_id else 0,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    })
