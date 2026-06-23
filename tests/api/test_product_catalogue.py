import httpx
import pytest
from conftest import BASE_URLS

BASE = BASE_URLS["product_catalogue"]


class TestProductBrowsing:
    def test_list_products_returns_results(self):
        resp = httpx.get(f"{BASE}/products")
        assert resp.status_code == 200
        body = resp.json()
        items = body.get("items", body.get("products", body))
        assert len(items) > 0

    def test_list_products_with_category_filter(self):
        resp = httpx.get(f"{BASE}/products?category=Electronics")
        assert resp.status_code == 200

    def test_list_products_with_price_range(self):
        resp = httpx.get(f"{BASE}/products?min_price=100&max_price=5000")
        assert resp.status_code == 200

    def test_product_detail(self):
        resp = httpx.get(f"{BASE}/products?limit=1")
        body = resp.json()
        items = body.get("items", body.get("products", body))
        product_id = items[0]["id"]

        detail_resp = httpx.get(f"{BASE}/products/{product_id}")
        assert detail_resp.status_code == 200
        product = detail_resp.json()
        assert product["id"] == product_id
        assert "name" in product
        assert "price" in product

    def test_product_not_found(self):
        resp = httpx.get(f"{BASE}/products/nonexistent_id_999999")
        assert resp.status_code == 404


class TestKeywordSearch:
    def test_keyword_search_returns_results(self):
        resp = httpx.get(f"{BASE}/products/search?q=laptop")
        assert resp.status_code == 200

    def test_empty_search_query(self):
        resp = httpx.get(f"{BASE}/products/search?q=")
        assert resp.status_code in (200, 422)


class TestSemanticSearch:
    def test_semantic_search_natural_language(self):
        resp = httpx.post(f"{BASE}/products/semantic-search", json={
            "query": "comfortable running shoes for marathon training",
            "top_k": 5,
        })
        assert resp.status_code == 200
        body = resp.json()
        results = body.get("results", body.get("products", body))
        assert isinstance(results, list)

    def test_semantic_search_with_price_filter(self):
        resp = httpx.post(f"{BASE}/products/semantic-search", json={
            "query": "bluetooth headphones",
            "top_k": 5,
            "max_price": 3000,
        })
        assert resp.status_code == 200
        body = resp.json()
        results = body.get("results", body.get("products", []))
        for product in results:
            assert product.get("price", 0) <= 3000

    def test_semantic_search_returns_scores(self):
        resp = httpx.post(f"{BASE}/products/semantic-search", json={
            "query": "waterproof jacket",
            "top_k": 3,
        })
        assert resp.status_code == 200
        body = resp.json()
        results = body.get("results", body.get("products", []))
        if results:
            assert "score" in results[0] or "similarity" in results[0]


class TestObservability:
    def test_metrics_endpoint(self):
        resp = httpx.get(f"{BASE}/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text or "# HELP" in resp.text

    def test_health_endpoint(self):
        resp = httpx.get(f"{BASE}/health")
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"
