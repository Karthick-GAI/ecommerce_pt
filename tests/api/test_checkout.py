import httpx
import pytest
import uuid
from conftest import BASE_URLS

CHECKOUT_BASE = BASE_URLS["checkout_service"]
PRODUCT_BASE = BASE_URLS["product_catalogue"]


def get_any_product_id(auth_headers):
    resp = httpx.get(f"{PRODUCT_BASE}/products?limit=1", headers=auth_headers)
    products = resp.json()
    if isinstance(products, dict):
        items = products.get("items", products.get("products", []))
    else:
        items = products
    assert len(items) > 0, "No products in catalogue — run seed_data.py first"
    return items[0]["id"]


class TestCart:
    def test_add_to_cart(self, auth_headers):
        product_id = get_any_product_id(auth_headers)
        resp = httpx.post(f"{CHECKOUT_BASE}/cart/items", json={
            "product_id": product_id,
            "quantity": 2,
        }, headers=auth_headers)
        assert resp.status_code in (200, 201)

    def test_view_cart(self, auth_headers):
        resp = httpx.get(f"{CHECKOUT_BASE}/cart", headers=auth_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_cart_requires_auth(self):
        resp = httpx.get(f"{CHECKOUT_BASE}/cart")
        assert resp.status_code == 401


class TestCheckoutIdempotency:
    def test_idempotent_order_placement(self, auth_headers):
        # Add item to cart first
        product_id = get_any_product_id(auth_headers)
        httpx.post(f"{CHECKOUT_BASE}/cart/items", json={
            "product_id": product_id, "quantity": 1,
        }, headers=auth_headers)

        idempotency_key = str(uuid.uuid4())
        headers = {**auth_headers, "Idempotency-Key": idempotency_key}

        resp1 = httpx.post(f"{CHECKOUT_BASE}/checkout", headers=headers)
        resp2 = httpx.post(f"{CHECKOUT_BASE}/checkout", headers=headers)

        assert resp1.status_code in (200, 201)
        assert resp2.status_code == resp1.status_code
        # Both responses must return the same order_id
        assert resp1.json().get("order_id") == resp2.json().get("order_id")

    def test_different_idempotency_keys_create_different_orders(self, auth_headers):
        product_id = get_any_product_id(auth_headers)
        httpx.post(f"{CHECKOUT_BASE}/cart/items", json={
            "product_id": product_id, "quantity": 1,
        }, headers=auth_headers)

        headers1 = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
        headers2 = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}

        resp1 = httpx.post(f"{CHECKOUT_BASE}/checkout", headers=headers1)
        resp2 = httpx.post(f"{CHECKOUT_BASE}/checkout", headers=headers2)

        if resp1.status_code in (200, 201) and resp2.status_code in (200, 201):
            assert resp1.json().get("order_id") != resp2.json().get("order_id")


class TestOrderRetrieval:
    def test_list_orders(self, auth_headers):
        resp = httpx.get(f"{CHECKOUT_BASE}/orders", headers=auth_headers)
        assert resp.status_code == 200

    def test_order_list_requires_auth(self):
        resp = httpx.get(f"{CHECKOUT_BASE}/orders")
        assert resp.status_code == 401


class TestObservability:
    def test_metrics_endpoint_returns_prometheus_format(self):
        resp = httpx.get(f"{CHECKOUT_BASE}/metrics")
        assert resp.status_code == 200
        # Prometheus format starts with # HELP or # TYPE lines
        assert "# HELP" in resp.text or "# TYPE" in resp.text

    def test_health_endpoint(self):
        resp = httpx.get(f"{CHECKOUT_BASE}/health")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"

    def test_trace_id_in_response_headers(self, auth_headers):
        resp = httpx.get(f"{CHECKOUT_BASE}/cart", headers=auth_headers)
        assert "x-trace-id" in resp.headers or "X-Trace-ID" in resp.headers
