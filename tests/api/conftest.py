import os
import pytest
from fastapi.testclient import TestClient

BASE_URLS = {
    "user_management":          os.getenv("USER_MGMT_URL",         "http://localhost:8000"),
    "product_catalogue":        os.getenv("PRODUCT_CAT_URL",        "http://localhost:8001"),
    "shopping_assistant":       os.getenv("SHOPPING_ASSISTANT_URL", "http://localhost:8002"),
    "checkout_service":         os.getenv("CHECKOUT_URL",           "http://localhost:8003"),
    "order_management":         os.getenv("ORDER_MGMT_URL",         "http://localhost:8004"),
    "inventory_service":        os.getenv("INVENTORY_URL",          "http://localhost:8005"),
    "recommendation_engine":    os.getenv("RECOMMENDATION_URL",     "http://localhost:8006"),
    "tool_calling_agent":       os.getenv("TOOL_CALLING_URL",       "http://localhost:8007"),
    "session_service":          os.getenv("SESSION_URL",            "http://localhost:8008"),
    "payment_shipping_service": os.getenv("PAYMENT_URL",            "http://localhost:8009"),
    "guardrails_service":       os.getenv("GUARDRAILS_URL",         "http://localhost:8010"),
    "multi_agent_system":       os.getenv("MULTI_AGENT_URL",        "http://localhost:8011"),
    "seller_portal":            os.getenv("SELLER_PORTAL_URL",      "http://localhost:8012"),
}

TEST_USER = {
    "email": "test_capstone@example.com",
    "password": "TestPass@2024",
    "full_name": "Capstone Tester",
    "phone": "9876543210",
}

TEST_SELLER = {
    "business_name": "Test Traders Pvt Ltd",
    "email": "seller_capstone@example.com",
    "password": "SellerPass@2024",
    "gst_number": "29ABCDE1234F1Z5",
    "pan_number": "ABCDE1234F",
}


@pytest.fixture(scope="session")
def user_token():
    import httpx
    base = BASE_URLS["user_management"]
    # Register (may already exist from prior run — ignore 409)
    httpx.post(f"{base}/auth/register", json=TEST_USER)
    # Login
    resp = httpx.post(f"{base}/auth/login", json={
        "email": TEST_USER["email"],
        "password": TEST_USER["password"],
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}
