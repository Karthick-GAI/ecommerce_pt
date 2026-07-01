"""
API tests for Recommendation Feedback Loop feature.
Service: recommendation_engine  Port: 8006
Routes: /feedback/*, /recommendations/for/{id}

Run:
    cd tests/api && pytest test_feedback_loop.py -v
"""
import httpx
import pytest

BASE = "http://localhost:8006"

TEST_CUSTOMER = "cust_pytest_001"
TEST_PRODUCT = "prod_pytest_001"


class TestFeedbackSubmit:
    def test_submit_thumbs_up_returns_200(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "customer_id": TEST_CUSTOMER,
            "product_id": TEST_PRODUCT,
            "feedback_type": "thumbs_up",
            "product_name": "Test Widget",
            "category": "Electronics",
            "brand": "TestBrand",
            "rec_strategy": "collaborative",
        })
        assert resp.status_code == 200, resp.text

    def test_submit_thumbs_down_returns_200(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "customer_id": TEST_CUSTOMER,
            "product_id": "prod_pytest_002",
            "feedback_type": "thumbs_down",
            "category": "Books",
            "brand": "PubHouse",
        })
        assert resp.status_code == 200, resp.text

    def test_submit_not_interested_returns_200(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "customer_id": TEST_CUSTOMER,
            "product_id": "prod_pytest_003",
            "feedback_type": "not_interested",
            "category": "Clothing",
            "brand": "FashionCo",
        })
        assert resp.status_code == 200, resp.text

    def test_invalid_feedback_type_rejected(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "customer_id": TEST_CUSTOMER,
            "product_id": TEST_PRODUCT,
            "feedback_type": "invalid_type",
        })
        assert resp.status_code in (400, 422), \
            f"Expected 400 or 422, got {resp.status_code}"

    def test_missing_customer_id_rejected(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "product_id": TEST_PRODUCT,
            "feedback_type": "thumbs_up",
        })
        assert resp.status_code == 422, resp.text

    def test_missing_product_id_rejected(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "customer_id": TEST_CUSTOMER,
            "feedback_type": "thumbs_up",
        })
        assert resp.status_code == 422, resp.text

    def test_submit_response_has_id(self):
        resp = httpx.post(f"{BASE}/feedback", json={
            "customer_id": TEST_CUSTOMER,
            "product_id": TEST_PRODUCT,
            "feedback_type": "thumbs_up",
            "category": "Electronics",
            "brand": "TestBrand",
        })
        data = resp.json()
        assert "id" in data, f"Response missing 'id': {data}"


class TestFeedbackHistory:
    def test_feedback_history_returns_200(self):
        resp = httpx.get(f"{BASE}/feedback/{TEST_CUSTOMER}")
        assert resp.status_code == 200, resp.text

    def test_feedback_history_returns_list(self):
        resp = httpx.get(f"{BASE}/feedback/{TEST_CUSTOMER}")
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    def test_feedback_history_entries_have_required_fields(self):
        resp = httpx.get(f"{BASE}/feedback/{TEST_CUSTOMER}")
        history = resp.json()
        for entry in history:
            assert "customer_id" in entry, f"Missing customer_id: {entry}"
            assert "product_id" in entry, f"Missing product_id: {entry}"
            assert "feedback_type" in entry, f"Missing feedback_type: {entry}"

    def test_feedback_history_belongs_to_customer(self):
        resp = httpx.get(f"{BASE}/feedback/{TEST_CUSTOMER}")
        for entry in resp.json():
            assert entry["customer_id"] == TEST_CUSTOMER, \
                f"Entry belongs to wrong customer: {entry['customer_id']}"

    def test_unknown_customer_returns_empty_list(self):
        resp = httpx.get(f"{BASE}/feedback/no_such_customer_xyz_123")
        assert resp.status_code == 200
        assert resp.json() == [], \
            f"Expected empty list for unknown customer, got {resp.json()}"


class TestFeedbackAdaptations:
    def test_adaptation_returns_200(self):
        resp = httpx.get(f"{BASE}/feedback/{TEST_CUSTOMER}/adaptation")
        assert resp.status_code == 200, resp.text

    def test_adaptation_has_jsonb_fields(self):
        resp = httpx.get(f"{BASE}/feedback/{TEST_CUSTOMER}/adaptation")
        data = resp.json()
        assert "category_boosts" in data, f"Missing category_boosts: {data}"
        assert "brand_boosts" in data, f"Missing brand_boosts: {data}"
        assert "blocked_products" in data, f"Missing blocked_products: {data}"
        assert "strategy_weights" in data, f"Missing strategy_weights: {data}"

    def test_category_boost_after_thumbs_up(self):
        httpx.post(f"{BASE}/feedback", json={
            "customer_id": "cust_boost_test",
            "product_id": "prod_x",
            "feedback_type": "thumbs_up",
            "category": "Appliances",
            "brand": "BrandX",
        })
        resp = httpx.get(f"{BASE}/feedback/cust_boost_test/adaptation")
        data = resp.json()
        cat_boosts = data.get("category_boosts", {})
        assert "Appliances" in cat_boosts, \
            f"Expected Appliances in category_boosts after thumbs_up: {cat_boosts}"
        assert cat_boosts["Appliances"] > 1.0, \
            f"Boost should be > 1.0 after thumbs_up, got {cat_boosts['Appliances']}"

    def test_category_boost_max_cap(self):
        cid = "cust_cap_test"
        for _ in range(20):
            httpx.post(f"{BASE}/feedback", json={
                "customer_id": cid,
                "product_id": "prod_y",
                "feedback_type": "thumbs_up",
                "category": "Sports",
                "brand": "Nike",
            })
        resp = httpx.get(f"{BASE}/feedback/{cid}/adaptation")
        cat_boosts = resp.json().get("category_boosts", {})
        if "Sports" in cat_boosts:
            assert cat_boosts["Sports"] <= 2.5, \
                f"Category boost exceeded max cap 2.5: {cat_boosts['Sports']}"

    def test_category_boost_min_floor(self):
        cid = "cust_floor_test"
        for _ in range(20):
            httpx.post(f"{BASE}/feedback", json={
                "customer_id": cid,
                "product_id": "prod_z",
                "feedback_type": "thumbs_down",
                "category": "Furniture",
                "brand": "WoodCo",
            })
        resp = httpx.get(f"{BASE}/feedback/{cid}/adaptation")
        cat_boosts = resp.json().get("category_boosts", {})
        if "Furniture" in cat_boosts:
            assert cat_boosts["Furniture"] >= 0.25, \
                f"Category boost went below min floor 0.25: {cat_boosts['Furniture']}"

    def test_not_interested_blocks_product(self):
        cid = "cust_block_test"
        pid = "prod_blocked_001"
        httpx.post(f"{BASE}/feedback", json={
            "customer_id": cid,
            "product_id": pid,
            "feedback_type": "not_interested",
            "category": "Toys",
            "brand": "ToyCo",
        })
        resp = httpx.get(f"{BASE}/feedback/{cid}/adaptation")
        blocked = resp.json().get("blocked_products", {})
        assert pid in blocked, \
            f"Product {pid} not found in blocked_products after not_interested: {blocked}"


class TestFeedbackStats:
    def test_loop_stats_returns_200(self):
        resp = httpx.get(f"{BASE}/feedback/loop/stats")
        assert resp.status_code == 200, resp.text

    def test_loop_stats_has_required_fields(self):
        resp = httpx.get(f"{BASE}/feedback/loop/stats")
        data = resp.json()
        assert "total_thumbs_up" in data, f"Missing total_thumbs_up: {data}"
        assert "total_thumbs_down" in data, f"Missing total_thumbs_down: {data}"
        assert "customers_with_adaptations" in data, f"Missing customers_with_adaptations: {data}"

    def test_loop_stats_counts_are_non_negative(self):
        resp = httpx.get(f"{BASE}/feedback/loop/stats")
        data = resp.json()
        assert data["total_thumbs_up"] >= 0
        assert data["total_thumbs_down"] >= 0
        assert data["customers_with_adaptations"] >= 0


class TestAdaptedRecommendations:
    def test_recommendations_returns_200(self):
        resp = httpx.get(f"{BASE}/recommendations/for/{TEST_CUSTOMER}")
        assert resp.status_code in (200, 404), resp.text

    def test_recommendations_include_feedback_adapted_flag(self):
        resp = httpx.get(f"{BASE}/recommendations/for/{TEST_CUSTOMER}")
        if resp.status_code == 404:
            pytest.skip("Customer has no recommendation data")
        data = resp.json()
        assert "feedback_adapted" in data, \
            f"Response missing 'feedback_adapted' flag: {data.keys()}"

    def test_feedback_adapted_true_after_feedback(self):
        cid = "cust_adapted_test"
        httpx.post(f"{BASE}/feedback", json={
            "customer_id": cid,
            "product_id": "prod_w",
            "feedback_type": "thumbs_up",
            "category": "Electronics",
            "brand": "Sony",
        })
        resp = httpx.get(f"{BASE}/recommendations/for/{cid}")
        if resp.status_code == 404:
            pytest.skip(f"No recommendations for {cid}")
        data = resp.json()
        assert data.get("feedback_adapted") is True, \
            f"Expected feedback_adapted=True after submitting feedback, got {data.get('feedback_adapted')}"

    def test_blocked_product_excluded_from_recommendations(self):
        cid = "cust_excl_test"
        pid = "prod_to_exclude"
        httpx.post(f"{BASE}/feedback", json={
            "customer_id": cid,
            "product_id": pid,
            "feedback_type": "not_interested",
        })
        resp = httpx.get(f"{BASE}/recommendations/for/{cid}")
        if resp.status_code == 404:
            pytest.skip("No recommendations returned")
        recs = resp.json().get("recommendations", [])
        rec_ids = [r.get("product_id") for r in recs]
        assert pid not in rec_ids, \
            f"Blocked product {pid} appeared in recommendations: {rec_ids}"

    def test_recommendations_limit_parameter(self):
        resp = httpx.get(f"{BASE}/recommendations/for/{TEST_CUSTOMER}?limit=5")
        if resp.status_code == 404:
            pytest.skip("Customer has no recommendation data")
        recs = resp.json().get("recommendations", [])
        assert len(recs) <= 5, \
            f"Received {len(recs)} recommendations, expected ≤ 5"
