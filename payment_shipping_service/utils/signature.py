"""
HMAC utilities for verifying provider signatures.

All comparisons use hmac.compare_digest to prevent timing-based attacks.
"""
import hmac
import hashlib


def verify_razorpay_payment_signature(
    order_id:   str,
    payment_id: str,
    signature:  str,
    secret:     str,
) -> bool:
    """
    Razorpay post-payment verification.
    Signature = HMAC-SHA256("{order_id}|{payment_id}", key_secret)
    """
    msg = f"{order_id}|{payment_id}"
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(
    body:      bytes,
    signature: str,
    secret:    str,
) -> bool:
    """
    Generic webhook payload verification.
    Razorpay: header X-Razorpay-Signature = HMAC-SHA256(raw_body, webhook_secret)
    """
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def mask_upi(vpa: str) -> str:
    """ab****@okicici from user@okicici"""
    if "@" not in vpa:
        return vpa[:2] + "****"
    local, domain = vpa.split("@", 1)
    masked_local = local[:2] + "****" if len(local) > 2 else "****"
    return f"{masked_local}@{domain}"
