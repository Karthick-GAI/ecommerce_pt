import random
import string


def _txn_id():
    return "RFD_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


REFUND_TIMELINE = {
    "card":   "5–7 business days to your card",
    "wallet": "immediately to your wallet",
    "upi":    "2–3 business days to your UPI account",
}


def process_refund_simulation(amount: float, payment_method: str) -> dict:
    """
    Simulate refund processing.
    Returns status, txn_id, and a human-readable message.
    """
    if amount > 200000:
        return {
            "status": "rejected",
            "reason": "Amount exceeds refund simulation limit of ₹2,00,000",
        }

    timeline = REFUND_TIMELINE.get(payment_method, "3–5 business days")
    txn      = _txn_id()

    return {
        "status":  "completed",
        "txn_id":  txn,
        "message": f"Refund of ₹{amount} will be credited {timeline}. Transaction: {txn}",
    }
