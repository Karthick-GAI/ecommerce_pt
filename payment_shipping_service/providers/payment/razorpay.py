"""
Razorpay payment provider.

When MOCK_PROVIDERS=true: returns realistic mock data, nothing hits Razorpay.
When MOCK_PROVIDERS=false: makes real API calls using key_id / key_secret.

Razorpay API reference: https://razorpay.com/docs/api/
  - Amounts are always in paise (INR × 100).
  - Auth: HTTP Basic with key_id:key_secret.
"""
import os
import uuid
import requests
from .base import PaymentProvider, PaymentOrderResult, PaymentVerifyResult, RefundResult
from utils.signature import verify_razorpay_payment_signature, mask_upi

RAZORPAY_BASE = "https://api.razorpay.com/v1"
MOCK = os.getenv("MOCK_PROVIDERS", "true").lower() == "true"


class RazorpayProvider(PaymentProvider):
    def __init__(self):
        self.key_id     = os.getenv("RAZORPAY_KEY_ID",     "rzp_test_mock")
        self.key_secret = os.getenv("RAZORPAY_KEY_SECRET", "mock_secret")

    def _auth(self):
        return (self.key_id, self.key_secret)

    # ── Create order ──────────────────────────────────────────────────────────

    def create_order(
        self, amount_inr: float, receipt: str, notes: dict = None
    ) -> PaymentOrderResult:
        amount_paise = int(round(amount_inr * 100))

        if MOCK:
            order_id = f"order_{uuid.uuid4().hex[:16]}"
            raw = {
                "id":       order_id,
                "entity":   "order",
                "amount":   amount_paise,
                "currency": "INR",
                "receipt":  receipt,
                "status":   "created",
                "attempts": 0,
            }
            return PaymentOrderResult(
                provider_order_id=order_id,
                amount_paise=amount_paise,
                currency="INR",
                receipt=receipt,
                status="created",
                provider_raw=raw,
            )

        resp = requests.post(
            f"{RAZORPAY_BASE}/orders",
            json={
                "amount":   amount_paise,
                "currency": "INR",
                "receipt":  receipt,
                "notes":    notes or {},
            },
            auth=self._auth(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return PaymentOrderResult(
            provider_order_id=data["id"],
            amount_paise=data["amount"],
            currency=data["currency"],
            receipt=receipt,
            status=data["status"],
            provider_raw=data,
        )

    # ── Verify payment ────────────────────────────────────────────────────────

    def verify_payment(
        self, order_id: str, payment_id: str, signature: str
    ) -> PaymentVerifyResult:
        if MOCK:
            pid = payment_id or f"pay_{uuid.uuid4().hex[:16]}"
            # Simulate different payment methods probabilistically by payment_id hash
            method = "upi" if int(pid[-1], 16) % 2 == 0 else "card"
            raw = {
                "id":       pid,
                "order_id": order_id,
                "status":   "captured",
                "method":   method,
                "amount":   0,
            }
            return PaymentVerifyResult(
                is_valid=True,
                provider_payment_id=pid,
                method=method,
                amount_paise=0,
                captured=True,
                upi_vpa=mask_upi("user@okicici") if method == "upi" else "",
                card_last4="4242" if method == "card" else "",
                card_network="Visa" if method == "card" else "",
                provider_raw=raw,
            )

        is_valid = verify_razorpay_payment_signature(
            order_id, payment_id, signature, self.key_secret
        )
        if not is_valid:
            return PaymentVerifyResult(
                is_valid=False,
                provider_payment_id=payment_id,
                method="unknown",
                amount_paise=0,
                captured=False,
                provider_raw={"error": "signature_mismatch"},
            )

        payment = self.fetch_payment(payment_id)
        method  = payment.get("method", "unknown")
        raw_upi = payment.get("vpa", "")
        card    = payment.get("card", {}) or {}

        return PaymentVerifyResult(
            is_valid=True,
            provider_payment_id=payment_id,
            method=method,
            amount_paise=payment.get("amount", 0),
            captured=payment.get("status") == "captured",
            upi_vpa=mask_upi(raw_upi) if raw_upi else "",
            card_last4=card.get("last4", ""),
            card_network=card.get("network", ""),
            provider_raw=payment,
        )

    # ── Fetch single payment ──────────────────────────────────────────────────

    def fetch_payment(self, payment_id: str) -> dict:
        if MOCK:
            return {
                "id":     payment_id,
                "status": "captured",
                "method": "upi",
                "amount": 0,
            }

        resp = requests.get(
            f"{RAZORPAY_BASE}/payments/{payment_id}",
            auth=self._auth(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Refund ────────────────────────────────────────────────────────────────

    def refund(
        self, payment_id: str, amount_inr: float, reason: str = ""
    ) -> RefundResult:
        amount_paise = int(round(amount_inr * 100))

        if MOCK:
            refund_id = f"rfnd_{uuid.uuid4().hex[:16]}"
            raw = {
                "id":         refund_id,
                "entity":     "refund",
                "payment_id": payment_id,
                "amount":     amount_paise,
                "status":     "processed",
            }
            return RefundResult(
                provider_refund_id=refund_id,
                amount_paise=amount_paise,
                status="processed",
                provider_raw=raw,
            )

        resp = requests.post(
            f"{RAZORPAY_BASE}/payments/{payment_id}/refund",
            json={
                "amount": amount_paise,
                "notes":  {"reason": reason},
            },
            auth=self._auth(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return RefundResult(
            provider_refund_id=data["id"],
            amount_paise=data["amount"],
            status=data["status"],
            provider_raw=data,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: RazorpayProvider | None = None


def get_razorpay() -> RazorpayProvider:
    global _instance
    if _instance is None:
        _instance = RazorpayProvider()
    return _instance
