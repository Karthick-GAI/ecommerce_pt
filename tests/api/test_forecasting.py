"""
API tests for Demand Forecasting feature.
Service: inventory_service  Port: 8005
Routes: /forecast/*

Run:
    cd tests/api && pytest test_forecasting.py -v
"""
import httpx
import pytest

BASE = "http://localhost:8005"


class TestForecastTrain:
    def test_train_returns_200(self):
        resp = httpx.post(f"{BASE}/forecast/train", timeout=30)
        assert resp.status_code == 200, resp.text

    def test_train_response_has_required_fields(self):
        resp = httpx.post(f"{BASE}/forecast/train", timeout=30)
        data = resp.json()
        assert "categories_trained" in data
        assert "categories_skipped" in data
        assert "duration_ms" in data

    def test_train_categories_trained_is_non_negative(self):
        resp = httpx.post(f"{BASE}/forecast/train", timeout=30)
        data = resp.json()
        assert data["categories_trained"] >= 0

    def test_train_is_idempotent(self):
        r1 = httpx.post(f"{BASE}/forecast/train", timeout=30)
        r2 = httpx.post(f"{BASE}/forecast/train", timeout=30)
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestForecastSummary:
    def test_summary_returns_200(self):
        resp = httpx.get(f"{BASE}/forecast/summary")
        assert resp.status_code == 200, resp.text

    def test_summary_has_required_fields(self):
        resp = httpx.get(f"{BASE}/forecast/summary")
        data = resp.json()
        assert "total_categories" in data
        assert "trained_categories" in data
        assert "restock_alerts" in data

    def test_summary_counts_are_non_negative(self):
        resp = httpx.get(f"{BASE}/forecast/summary")
        data = resp.json()
        assert data["total_categories"] >= 0
        assert data["trained_categories"] >= 0
        assert data["restock_alerts"] >= 0


class TestForecastCategories:
    def test_categories_returns_200(self):
        resp = httpx.get(f"{BASE}/forecast/categories")
        assert resp.status_code == 200, resp.text

    def test_categories_returns_list(self):
        resp = httpx.get(f"{BASE}/forecast/categories")
        data = resp.json()
        assert isinstance(data, list)

    def test_each_category_has_required_fields(self):
        resp = httpx.get(f"{BASE}/forecast/categories")
        categories = resp.json()
        if not categories:
            pytest.skip("No trained categories — run POST /forecast/train first")
        for cat in categories:
            assert "category" in cat, f"Missing 'category' in {cat}"
            assert "status" in cat, f"Missing 'status' in {cat}"

    def test_trained_categories_have_rmse(self):
        resp = httpx.get(f"{BASE}/forecast/categories")
        categories = resp.json()
        trained = [c for c in categories if c.get("status") == "trained"]
        if not trained:
            pytest.skip("No trained categories")
        for cat in trained:
            assert "rmse" in cat, f"Trained category missing rmse: {cat}"
            assert cat["rmse"] >= 0, f"RMSE cannot be negative: {cat['rmse']}"


class TestForecastCategory:
    @pytest.fixture(scope="class")
    def first_trained_category(self):
        resp = httpx.get(f"{BASE}/forecast/categories")
        cats = [c for c in resp.json() if c.get("status") == "trained"]
        if not cats:
            pytest.skip("No trained categories — run POST /forecast/train first")
        return cats[0]["category"]

    def test_category_forecast_returns_200(self, first_trained_category):
        resp = httpx.get(f"{BASE}/forecast/category/{first_trained_category}")
        assert resp.status_code == 200, resp.text

    def test_category_forecast_has_forecast_array(self, first_trained_category):
        resp = httpx.get(f"{BASE}/forecast/category/{first_trained_category}")
        data = resp.json()
        assert "forecast" in data, "Response missing 'forecast' key"
        assert isinstance(data["forecast"], list)

    def test_category_forecast_covers_30_days(self, first_trained_category):
        resp = httpx.get(f"{BASE}/forecast/category/{first_trained_category}")
        forecast = resp.json().get("forecast", [])
        assert len(forecast) == 30, f"Expected 30 forecast days, got {len(forecast)}"

    def test_forecast_points_have_confidence_bands(self, first_trained_category):
        resp = httpx.get(f"{BASE}/forecast/category/{first_trained_category}")
        forecast = resp.json().get("forecast", [])
        if not forecast:
            pytest.skip("Empty forecast array")
        for point in forecast:
            assert "predicted" in point, f"Missing 'predicted' in {point}"
            assert "lower" in point, f"Missing 'lower' confidence bound in {point}"
            assert "upper" in point, f"Missing 'upper' confidence bound in {point}"

    def test_confidence_bands_bracket_prediction(self, first_trained_category):
        resp = httpx.get(f"{BASE}/forecast/category/{first_trained_category}")
        forecast = resp.json().get("forecast", [])
        for point in forecast:
            assert point["lower"] <= point["predicted"], \
                f"Lower bound {point['lower']} exceeds predicted {point['predicted']}"
            assert point["upper"] >= point["predicted"], \
                f"Upper bound {point['upper']} below predicted {point['predicted']}"

    def test_forecast_predictions_are_non_negative(self, first_trained_category):
        resp = httpx.get(f"{BASE}/forecast/category/{first_trained_category}")
        forecast = resp.json().get("forecast", [])
        for point in forecast:
            assert point["predicted"] >= 0, \
                f"Predicted demand cannot be negative: {point['predicted']}"

    def test_unknown_category_returns_404(self):
        resp = httpx.get(f"{BASE}/forecast/category/NonExistentCategoryXYZ")
        assert resp.status_code == 404, \
            f"Expected 404 for unknown category, got {resp.status_code}"


class TestRestockAlerts:
    def test_restock_alerts_returns_200(self):
        resp = httpx.get(f"{BASE}/forecast/restock-alerts")
        assert resp.status_code == 200, resp.text

    def test_restock_alerts_returns_list(self):
        resp = httpx.get(f"{BASE}/forecast/restock-alerts")
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    def test_restock_alerts_have_required_fields(self):
        resp = httpx.get(f"{BASE}/forecast/restock-alerts")
        alerts = resp.json()
        for alert in alerts:
            assert "category" in alert, f"Alert missing 'category': {alert}"
            assert "severity" in alert, f"Alert missing 'severity': {alert}"
            assert "days_until_stockout" in alert, f"Alert missing 'days_until_stockout': {alert}"

    def test_severity_values_are_valid(self):
        resp = httpx.get(f"{BASE}/forecast/restock-alerts")
        alerts = resp.json()
        valid_severities = {"critical", "warning"}
        for alert in alerts:
            assert alert["severity"] in valid_severities, \
                f"Invalid severity '{alert['severity']}', must be one of {valid_severities}"

    def test_days_until_stockout_is_positive(self):
        resp = httpx.get(f"{BASE}/forecast/restock-alerts")
        alerts = resp.json()
        for alert in alerts:
            assert alert["days_until_stockout"] > 0, \
                f"days_until_stockout must be > 0, got {alert['days_until_stockout']}"

    def test_restock_alerts_filter_by_severity(self):
        for sev in ("critical", "warning"):
            resp = httpx.get(f"{BASE}/forecast/restock-alerts?severity={sev}")
            assert resp.status_code == 200, f"severity filter failed for {sev}"
            for alert in resp.json():
                assert alert["severity"] == sev, \
                    f"Severity mismatch: expected {sev}, got {alert['severity']}"

    def test_acknowledge_restock_alert(self):
        resp = httpx.get(f"{BASE}/forecast/restock-alerts")
        alerts = resp.json()
        unacked = [a for a in alerts if not a.get("acknowledged")]
        if not unacked:
            pytest.skip("No unacknowledged restock alerts to test")
        alert_id = unacked[0]["id"]
        ack_resp = httpx.post(
            f"{BASE}/forecast/restock-alerts/{alert_id}/acknowledge",
            json={"acknowledged_by": "test_ops", "note": "Pytest ack"},
        )
        assert ack_resp.status_code == 200, ack_resp.text
        ack_data = ack_resp.json()
        assert ack_data.get("acknowledged") is True

    def test_refresh_alerts_returns_200(self):
        resp = httpx.post(f"{BASE}/forecast/refresh-alerts")
        assert resp.status_code == 200, resp.text
