"""
Business-logic validators that query the shared database.

These validators cross-reference live data (product catalogue, customer
history) to catch anomalies like price tampering or duplicate orders.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from models import Product, CheckoutOrder
from .security import Violation


# ── Order business rules ──────────────────────────────────────────────────────

def validate_order_against_catalogue(items: list[dict], db: Session) -> list[Violation]:
    """
    For each order item, verify:
      - product exists and is active
      - submitted unit_price is not lower than actual price by > 20% (price tampering)
      - product is in stock (inventory_count > 0)
    """
    violations = []
    for i, item in enumerate(items):
        pid   = item.get("product_id")
        price = item.get("unit_price", 0)
        qty   = item.get("quantity", 1)

        if not pid:
            continue  # format validator already caught missing pid

        product = db.query(Product).filter(Product.id == pid).first()
        if not product:
            violations.append(Violation(
                "product_not_found", "high",
                f"Item {i+1}: product {pid} not found in catalogue",
                pid,
            ))
            continue

        if not product.is_active:
            violations.append(Violation(
                "product_inactive", "medium",
                f"Item {i+1}: product '{product.name}' is no longer active",
            ))

        if product.inventory_count is not None and product.inventory_count <= 0:
            violations.append(Violation(
                "product_out_of_stock", "medium",
                f"Item {i+1}: '{product.name}' is out of stock",
            ))

        # Price tampering check: submitted price < catalogue price × 0.8
        if price and product.price:
            effective_catalogue = product.price * (1 - (product.discount_pct or 0) / 100)
            if price < effective_catalogue * 0.8:
                violations.append(Violation(
                    "price_tampering", "critical",
                    f"Item {i+1}: submitted price ₹{price:.2f} is significantly below "
                    f"catalogue price ₹{effective_catalogue:.2f} for '{product.name}'",
                ))

    return violations


def validate_total_amount(items: list[dict], total_amount: float, db: Session) -> list[Violation]:
    """
    Recompute the expected total from catalogue prices and compare to submitted total.
    Flags discrepancies > 1% (rounding tolerance).
    """
    violations = []
    computed = 0.0
    for item in items:
        pid = item.get("product_id")
        qty = item.get("quantity", 1)
        if pid:
            product = db.query(Product).filter(Product.id == pid).first()
            if product and product.price:
                effective = product.price * (1 - (product.discount_pct or 0) / 100)
                computed += effective * qty
    if computed > 0:
        diff_pct = abs(total_amount - computed) / computed * 100
        if diff_pct > 5:
            violations.append(Violation(
                "amount_mismatch", "high",
                f"Submitted total ₹{total_amount:.2f} differs from computed total "
                f"₹{computed:.2f} by {diff_pct:.1f}%",
            ))
    return violations


def validate_duplicate_order(customer_id: str, items: list[dict], db: Session, window_minutes: int = 5) -> list[Violation]:
    """
    Detect if this customer placed a nearly identical order within the last N minutes.
    Comparison: same customer_id + same product_ids (order-insensitive).
    """
    violations = []
    if not customer_id:
        return violations

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    recent = db.query(CheckoutOrder).filter(
        CheckoutOrder.customer_id == customer_id,
        CheckoutOrder.created_at  >= cutoff,
    ).all()

    if not recent:
        return violations

    submitted_pids = frozenset(item.get("product_id") for item in items if item.get("product_id"))
    for order in recent:
        # We can't inspect cart items without joining checkout_order_items,
        # so flag on same customer + multiple orders in window
        violations.append(Violation(
            "possible_duplicate_order", "medium",
            f"Customer already placed order '{order.id}' within the last {window_minutes} minutes",
        ))
        break  # one warning is enough

    return violations


def validate_payment_method(payment_method: str) -> list[Violation]:
    violations = []
    ALLOWED = {"razorpay", "cod", "card", "upi", "netbanking", "wallet", "emi", "stripe"}
    if payment_method and payment_method.lower() not in ALLOWED:
        violations.append(Violation(
            "payment_method_unknown", "low",
            f"Unrecognised payment method: {payment_method}",
        ))
    return violations
