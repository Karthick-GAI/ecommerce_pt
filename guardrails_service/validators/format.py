"""
Format and domain-specific validators.

Validates Indian-specific formats (mobile, pincode), generic formats
(email, name), and monetary amounts without external dependencies.
"""
import re
from .security import Violation


# ── Regex constants ───────────────────────────────────────────────────────────

_INDIAN_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
_INDIAN_PINCODE_RE = re.compile(r"^\d{6}$")
# RFC5322-simplified: covers 99.9% of real-world addresses
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{1,255}\.[a-zA-Z]{2,}$"
)
# Safe name characters: letters, spaces, hyphens, apostrophes, dots
_SAFE_NAME_RE = re.compile(r"^[a-zA-ZÀ-ɏ\s'\-\.]+$")


# ── Phone ─────────────────────────────────────────────────────────────────────

def validate_phone(phone: str) -> list[Violation]:
    if not phone:
        return []
    # Strip common formatting chars
    clean = re.sub(r"[\s\-\(\)\+]", "", phone)
    # Strip country code 91
    if clean.startswith("91") and len(clean) == 12:
        clean = clean[2:]
    if not _INDIAN_MOBILE_RE.match(clean):
        return [Violation(
            "phone_format", "medium",
            f"Not a valid Indian mobile number (must be 10 digits, start with 6-9): {phone}"
        )]
    return []


# ── Email ─────────────────────────────────────────────────────────────────────

def validate_email_address(email: str) -> list[Violation]:
    if not email:
        return []
    violations = []
    if len(email) > 320:
        violations.append(Violation("email_length", "low", "Email address exceeds 320 characters"))
    if not _EMAIL_RE.match(email):
        violations.append(Violation("email_format", "medium", f"Invalid email format: {email}"))
    # Detect throwaway domain patterns (heuristic)
    domain = email.split("@")[-1].lower() if "@" in email else ""
    DISPOSABLE_DOMAINS = {
        "mailinator.com", "guerrillamail.com", "tempmail.com", "throwam.com",
        "yopmail.com", "10minutemail.com", "fakeinbox.com", "sharklasers.com",
    }
    if domain in DISPOSABLE_DOMAINS:
        violations.append(Violation(
            "disposable_email", "low",
            f"Disposable / throwaway email domain: {domain}",
        ))
    return violations


# ── Pincode ───────────────────────────────────────────────────────────────────

def validate_pincode(pincode: str) -> list[Violation]:
    if not pincode:
        return []
    if not _INDIAN_PINCODE_RE.match(pincode.strip()):
        return [Violation("pincode_format", "medium",
                          f"Invalid Indian PIN code (must be 6 digits): {pincode}")]
    # Block obviously invalid pincodes
    if pincode in ("000000", "999999", "111111", "123456"):
        return [Violation("pincode_invalid", "medium", f"PIN code is not a real PIN: {pincode}")]
    return []


# ── Name ──────────────────────────────────────────────────────────────────────

def validate_name(name: str) -> list[Violation]:
    if not name:
        return []
    violations = []
    stripped = name.strip()
    if len(stripped) < 2:
        violations.append(Violation("name_too_short", "low", "Name must be at least 2 characters"))
    if len(stripped) > 100:
        violations.append(Violation("name_too_long", "low", "Name exceeds 100 characters"))
    if not _SAFE_NAME_RE.match(stripped):
        violations.append(Violation(
            "name_chars", "medium",
            f"Name contains invalid characters (only letters, spaces, hyphens, apostrophes allowed)",
        ))
    return violations


# ── Amount ────────────────────────────────────────────────────────────────────

MAX_AMOUNT_INR = 10_000_000   # 1 crore
MAX_REFUND_INR = 1_000_000    # 10 lakh
MAX_PRICE_INR  = 10_000_000

def validate_amount(amount: float, context: str = "order") -> list[Violation]:
    violations = []
    if amount < 0:
        violations.append(Violation("amount_negative", "critical",
                                    f"Amount cannot be negative: {amount}"))
        return violations  # no further checks on negative amounts

    if amount == 0 and context in ("order", "payment"):
        violations.append(Violation("amount_zero", "high",
                                    f"Order/payment amount cannot be zero"))

    limit = MAX_REFUND_INR if context == "refund" else MAX_AMOUNT_INR
    if amount > limit:
        violations.append(Violation(
            "amount_too_large", "high",
            f"Amount ₹{amount:,.2f} exceeds maximum allowed ₹{limit:,.0f} for context '{context}'",
        ))

    # Sanity check: amounts > 1 crore get extra scrutiny
    if amount > 1_000_000 and context == "order":
        violations.append(Violation(
            "amount_unusually_large", "medium",
            f"Order amount ₹{amount:,.2f} is unusually large — please review",
        ))

    return violations


# ── Search query ──────────────────────────────────────────────────────────────

def validate_search_query(query: str) -> list[Violation]:
    violations = []
    if not query:
        violations.append(Violation("search_empty", "low", "Search query is empty"))
        return violations
    if len(query) > 500:
        violations.append(Violation("search_too_long", "medium",
                                    f"Search query exceeds 500 characters ({len(query)})"))
    if len(query.strip()) < 2:
        violations.append(Violation("search_too_short", "low", "Search query is too short"))
    # Detect keyword stuffing
    words = query.split()
    if len(words) > 30:
        violations.append(Violation("search_keyword_stuffing", "low",
                                    f"Search query contains too many words ({len(words)})"))
    return violations


# ── Order items ───────────────────────────────────────────────────────────────

def validate_order_items(items: list[dict]) -> list[Violation]:
    violations = []
    if not items:
        violations.append(Violation("order_empty", "high", "Order has no items"))
        return violations

    if len(items) > 50:
        violations.append(Violation("order_too_many_items", "medium",
                                    f"Order contains {len(items)} items (max 50)"))

    for i, item in enumerate(items):
        qty = item.get("quantity", 0)
        price = item.get("unit_price", 0)

        if not isinstance(qty, (int, float)) or qty <= 0:
            violations.append(Violation("order_qty_invalid", "high",
                                        f"Item {i+1}: quantity must be positive (got {qty})"))
        elif qty > 100:
            violations.append(Violation("order_qty_excessive", "medium",
                                        f"Item {i+1}: quantity {qty} is unusually large (max 100)"))

        if not isinstance(price, (int, float)) or price < 0:
            violations.append(Violation("order_price_invalid", "high",
                                        f"Item {i+1}: unit_price cannot be negative (got {price})"))
        elif price == 0:
            violations.append(Violation("order_price_zero", "medium",
                                        f"Item {i+1}: unit_price is zero"))

    return violations
