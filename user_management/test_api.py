# test_api.py — End-to-end demo script that exercises every endpoint
#
# Run the server first:
#   uvicorn main:app --reload --port 8000
#
# Then in a second terminal:
#   python test_api.py
#
# This script walks through the full user journey:
#   Register → Login → View Profile → Update Profile → Change Password
#   → Add Address → Set Default Address → Update Address → Delete Address
#   → Add Card → Add UPI → Add Wallet → Set Default Payment → Delete Payment
#   → Refresh Token → Deactivate Account

import requests
import json

BASE = "http://localhost:8000"


def pretty(label, response):
    """Print a response in a readable format."""
    status_color = "\033[92m" if response.ok else "\033[91m"
    reset = "\033[0m"
    print(f"\n{status_color}[{response.status_code}] {label}{reset}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)


def headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── 1. REGISTER ──────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/auth/register", json={
    "email": "karthick@example.com",
    "password": "MyPass123",
    "first_name": "Karthick",
    "last_name": "Dharuman",
    "phone": "9876543210"
})
pretty("REGISTER", r)


# ── 2. LOGIN ─────────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/auth/login", json={
    "email": "karthick@example.com",
    "password": "MyPass123"
})
pretty("LOGIN", r)

tokens = r.json()
access_token  = tokens["access_token"]
refresh_token = tokens["refresh_token"]
print(f"\n  access_token : {access_token[:40]}...")
print(f"  refresh_token: {refresh_token[:40]}...")


# ── 3. GET PROFILE ───────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/users/me", headers=headers(access_token))
pretty("GET PROFILE", r)


# ── 4. UPDATE PROFILE ────────────────────────────────────────────────────────
r = requests.put(f"{BASE}/users/me", json={
    "first_name": "Karthick Kumar",
    "phone": "9123456789"
}, headers=headers(access_token))
pretty("UPDATE PROFILE", r)


# ── 5. CHANGE PASSWORD ───────────────────────────────────────────────────────
r = requests.post(f"{BASE}/users/me/change-password", json={
    "current_password": "MyPass123",
    "new_password": "NewPass456"
}, headers=headers(access_token))
pretty("CHANGE PASSWORD", r)

# Re-login with new password
r = requests.post(f"{BASE}/auth/login", json={
    "email": "karthick@example.com",
    "password": "NewPass456"
})
pretty("RE-LOGIN (new password)", r)
access_token  = r.json()["access_token"]
refresh_token = r.json()["refresh_token"]


# ── 6. ADD ADDRESS ───────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/users/me/addresses", json={
    "label": "Home",
    "full_name": "Karthick Dharuman",
    "phone": "9876543210",
    "line1": "42, Anna Nagar",
    "line2": "Near Metro Station",
    "city": "Chennai",
    "state": "Tamil Nadu",
    "pincode": "600040"
}, headers=headers(access_token))
pretty("ADD ADDRESS (Home)", r)
home_address_id = r.json()["id"]


# ── 7. ADD SECOND ADDRESS ────────────────────────────────────────────────────
r = requests.post(f"{BASE}/users/me/addresses", json={
    "label": "Office",
    "full_name": "Karthick Dharuman",
    "phone": "9876543210",
    "line1": "Prodapt Solutions, Guindy",
    "city": "Chennai",
    "state": "Tamil Nadu",
    "pincode": "600032"
}, headers=headers(access_token))
pretty("ADD ADDRESS (Office)", r)
office_address_id = r.json()["id"]


# ── 8. LIST ADDRESSES ────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/users/me/addresses", headers=headers(access_token))
pretty("LIST ADDRESSES", r)


# ── 9. SET DEFAULT ADDRESS ───────────────────────────────────────────────────
r = requests.put(f"{BASE}/users/me/addresses/{office_address_id}/default",
                 headers=headers(access_token))
pretty("SET DEFAULT ADDRESS (Office)", r)


# ── 10. UPDATE ADDRESS ───────────────────────────────────────────────────────
r = requests.put(f"{BASE}/users/me/addresses/{home_address_id}", json={
    "line2": "Flat 4B, 2nd Floor"
}, headers=headers(access_token))
pretty("UPDATE ADDRESS (Home - add flat number)", r)


# ── 11. DELETE ADDRESS ───────────────────────────────────────────────────────
r = requests.delete(f"{BASE}/users/me/addresses/{home_address_id}",
                    headers=headers(access_token))
pretty("DELETE ADDRESS (Home)", r)


# ── 12. ADD CARD PAYMENT METHOD ──────────────────────────────────────────────
r = requests.post(f"{BASE}/users/me/payment-methods", json={
    "type": "card",
    "label": "HDFC Savings",
    "card_last4": "4242",
    "card_brand": "Visa",
    "card_holder": "KARTHICK DHARUMAN",
    "card_expiry": "12/2027"
}, headers=headers(access_token))
pretty("ADD PAYMENT — Card (Visa ending 4242)", r)
card_id = r.json()["id"]


# ── 13. ADD UPI PAYMENT METHOD ───────────────────────────────────────────────
r = requests.post(f"{BASE}/users/me/payment-methods", json={
    "type": "upi",
    "label": "Karthick UPI",
    "upi_id": "karthick@paytm"
}, headers=headers(access_token))
pretty("ADD PAYMENT — UPI (karthick@paytm)", r)
upi_id = r.json()["id"]


# ── 14. ADD WALLET PAYMENT METHOD ────────────────────────────────────────────
r = requests.post(f"{BASE}/users/me/payment-methods", json={
    "type": "wallet",
    "label": "PhonePe",
    "wallet_provider": "PhonePe",
    "wallet_phone": "9876543210"
}, headers=headers(access_token))
pretty("ADD PAYMENT — Wallet (PhonePe)", r)
wallet_id = r.json()["id"]


# ── 15. LIST PAYMENT METHODS ─────────────────────────────────────────────────
r = requests.get(f"{BASE}/users/me/payment-methods", headers=headers(access_token))
pretty("LIST PAYMENT METHODS", r)


# ── 16. SET DEFAULT PAYMENT ──────────────────────────────────────────────────
r = requests.put(f"{BASE}/users/me/payment-methods/{upi_id}/default",
                 headers=headers(access_token))
pretty("SET DEFAULT PAYMENT (UPI)", r)


# ── 17. DELETE PAYMENT METHOD ────────────────────────────────────────────────
r = requests.delete(f"{BASE}/users/me/payment-methods/{wallet_id}",
                    headers=headers(access_token))
pretty("DELETE PAYMENT (Wallet)", r)


# ── 18. REFRESH TOKEN ────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": refresh_token})
pretty("REFRESH TOKEN", r)


# ── 19. DEACTIVATE ACCOUNT ───────────────────────────────────────────────────
r = requests.delete(f"{BASE}/users/me", headers=headers(access_token))
pretty("DEACTIVATE ACCOUNT", r)

# Confirm — login should now be blocked
r = requests.post(f"{BASE}/auth/login", json={
    "email": "karthick@example.com",
    "password": "NewPass456"
})
pretty("LOGIN AFTER DEACTIVATION (should fail)", r)

print("\n\n✓ All tests completed. Check http://localhost:8000/docs for interactive API explorer.")
