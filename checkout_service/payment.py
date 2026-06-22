import re
import random
import string
from datetime import datetime


def _txn_id(prefix: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return f"{prefix}{suffix}"


# ── Luhn algorithm (card number validation) ───────────────────────────────────

def _luhn_check(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ── Card payment ──────────────────────────────────────────────────────────────

def process_card(data: dict, amount: float) -> dict:
    card_number = re.sub(r"[\s-]", "", data.get("card_number", ""))

    if not _luhn_check(card_number):
        return {"status": "failed", "reason": "Invalid card number"}

    try:
        month = int(data.get("expiry_month", 0))
        year  = int(data.get("expiry_year", 0))
        now   = datetime.utcnow()
        if year < now.year or (year == now.year and month < now.month):
            return {"status": "failed", "reason": "Card has expired"}
        if not (1 <= month <= 12):
            return {"status": "failed", "reason": "Invalid expiry month"}
    except (ValueError, TypeError):
        return {"status": "failed", "reason": "Invalid expiry date"}

    cvv = str(data.get("cvv", ""))
    if not re.match(r"^\d{3,4}$", cvv):
        return {"status": "failed", "reason": "Invalid CVV"}

    # Test decline card
    if card_number == "4000000000000002":
        return {"status": "failed", "reason": "Card declined by issuing bank"}

    return {
        "status":         "success",
        "transaction_id": _txn_id("TXN_CARD_"),
        "gateway_ref":    _txn_id("AUTH_"),
    }


# ── Wallet payment ────────────────────────────────────────────────────────────

SUPPORTED_WALLETS = ["paytm", "phonepe", "googlepay", "amazonpay", "mobikwik"]


def process_wallet(data: dict, amount: float) -> dict:
    wallet_type = data.get("wallet_type", "").lower().strip()
    if wallet_type not in SUPPORTED_WALLETS:
        return {
            "status": "failed",
            "reason": f"Unsupported wallet. Choose: {', '.join(SUPPORTED_WALLETS)}",
        }

    mobile = str(data.get("wallet_mobile", "")).strip()
    if not re.match(r"^[6-9]\d{9}$", mobile):
        return {"status": "failed", "reason": "Invalid Indian mobile number (must be 10 digits starting 6-9)"}

    # Test fail mobile
    if mobile == "9000000000":
        return {"status": "failed", "reason": "Insufficient wallet balance"}

    return {
        "status":         "success",
        "transaction_id": _txn_id(f"WAL_{wallet_type.upper()}_"),
        "gateway_ref":    _txn_id("WREF_"),
    }


# ── UPI payment ───────────────────────────────────────────────────────────────

def process_upi(data: dict, amount: float) -> dict:
    upi_id = data.get("upi_id", "").strip()

    if not re.match(r"^[a-zA-Z0-9._-]+@[a-zA-Z]{3,}$", upi_id):
        return {
            "status": "failed",
            "reason": "Invalid UPI ID format. Expected: username@bank (e.g. karthick@paytm)",
        }

    # Test fail UPI
    if upi_id.lower() == "fail@upi":
        return {"status": "failed", "reason": "UPI transaction declined by bank"}

    return {
        "status":         "success",
        "transaction_id": _txn_id("UPI_"),
        "gateway_ref":    _txn_id("UREF_"),
    }


# ── Dispatcher ────────────────────────────────────────────────────────────────

def process_payment(method: str, payment_data: dict, amount: float) -> dict:
    if method == "card":
        return process_card(payment_data, amount)
    elif method == "wallet":
        return process_wallet(payment_data, amount)
    elif method == "upi":
        return process_upi(payment_data, amount)
    return {"status": "failed", "reason": f"Unknown payment method: {method}"}
