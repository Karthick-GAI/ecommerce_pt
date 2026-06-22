from typing import Optional

TAX_RATE            = 0.18    # 18% GST
SHIPPING_FREE_ABOVE = 499.0
SHIPPING_CHARGE     = 49.0

# Valid coupon codes
COUPONS = {
    "SAVE10":  {"type": "percent", "value": 10,  "min_order": 0},
    "SAVE20":  {"type": "percent", "value": 20,  "min_order": 1000},
    "FLAT500": {"type": "flat",    "value": 500, "min_order": 2000},
    "WELCOME": {"type": "percent", "value": 15,  "min_order": 0},
    "FESTIVE": {"type": "flat",    "value": 250, "min_order": 1000},
}


def apply_coupon(subtotal: float, code: Optional[str]) -> tuple:
    """Returns (discount_amount, message)."""
    if not code:
        return 0.0, ""

    coupon = COUPONS.get(code.upper().strip())
    if not coupon:
        return 0.0, f"Invalid coupon code: {code}"

    if subtotal < coupon["min_order"]:
        return 0.0, f"Minimum order ₹{coupon['min_order']:,} required for this coupon"

    if coupon["type"] == "percent":
        discount = round(subtotal * coupon["value"] / 100, 2)
        return discount, f"{coupon['value']}% discount applied"
    else:
        return float(coupon["value"]), f"Flat ₹{coupon['value']} discount applied"


def calculate_order_totals(cart_items, coupon_code: Optional[str] = None) -> dict:
    """
    Calculate full order breakdown:
      subtotal → apply coupon → 18% GST → shipping (free above ₹499) → total
    """
    subtotal = sum(i.price_at_add * i.quantity for i in cart_items)
    discount, coupon_msg = apply_coupon(subtotal, coupon_code)

    taxable  = max(0.0, subtotal - discount)
    tax      = round(taxable * TAX_RATE, 2)
    shipping = 0.0 if subtotal >= SHIPPING_FREE_ABOVE else SHIPPING_CHARGE
    total    = round(taxable + tax + shipping, 2)

    return {
        "subtotal":       round(subtotal, 2),
        "discount":       round(discount, 2),
        "coupon_message": coupon_msg,
        "tax":            tax,
        "shipping_charge": shipping,
        "total":          total,
    }
