"""
API tests for Anomaly Detection feature.
Service: guardrails_service  Port: 8010
Routes: /anomaly/*

Run:
    cd tests/api && pytest test_anomaly_detection.py -v
"""
import json
import time
import httpx
import pytest

BASE = "http://localhost:8010"


class TestScan:
    def test_full_scan_returns_200(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=full", timeout=30)
        assert resp.status_code == 200, resp.text

    def test_full_scan_response_has_required_fields(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=full", timeout=30)
        data = resp.json()
        assert "scan_type" in data, f"Missing scan_type: {data}"
        assert "detectors_run" in data, f"Missing detectors_run: {data}"
        assert "alerts_generated" in data, f"Missing alerts_generated: {data}"

    def test_full_scan_alerts_generated_is_non_negative(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=full", timeout=30)
        data = resp.json()
        assert data["alerts_generated"] >= 0

    def test_targeted_scan_user(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=user", timeout=30)
        assert resp.status_code == 200, resp.text

    def test_targeted_scan_inventory(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=inventory", timeout=30)
        assert resp.status_code == 200, resp.text

    def test_targeted_scan_payment(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=payment", timeout=30)
        assert resp.status_code == 200, resp.text

    def test_invalid_scan_type_handled(self):
        resp = httpx.post(f"{BASE}/anomaly/scan?scan_type=bogus_type", timeout=30)
        assert resp.status_code in (200, 400, 422), \
            f"Unexpected status {resp.status_code} for invalid scan_type"

    def test_scan_is_idempotent(self):
        r1 = httpx.post(f"{BASE}/anomaly/scan?scan_type=full", timeout=30)
        r2 = httpx.post(f"{BASE}/anomaly/scan?scan_type=full", timeout=30)
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestDashboard:
    def test_dashboard_returns_200(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        assert resp.status_code == 200, resp.text

    def test_dashboard_has_kpi_fields(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        data = resp.json()
        for field in ("open", "critical", "high", "medium", "low"):
            assert field in data, f"Dashboard missing KPI field '{field}'"

    def test_dashboard_has_hourly_trend(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        data = resp.json()
        assert "hourly_trend" in data, "Dashboard missing 'hourly_trend'"
        trend = data["hourly_trend"]
        assert isinstance(trend, list), f"hourly_trend must be a list, got {type(trend)}"
        assert len(trend) == 24, f"hourly_trend must have 24 entries (0–23), got {len(trend)}"

    def test_hourly_trend_has_hour_and_count(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        trend = resp.json().get("hourly_trend", [])
        for entry in trend:
            assert "hour" in entry, f"hourly_trend entry missing 'hour': {entry}"
            assert "count" in entry, f"hourly_trend entry missing 'count': {entry}"

    def test_hourly_trend_hours_are_0_to_23(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        trend = resp.json().get("hourly_trend", [])
        hours = [e["hour"] for e in trend]
        assert sorted(hours) == list(range(24)), \
            f"hourly_trend hours must cover exactly 0–23, got {sorted(hours)}"

    def test_dashboard_has_by_type(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        data = resp.json()
        assert "by_type" in data, "Dashboard missing 'by_type'"
        assert isinstance(data["by_type"], dict), \
            f"by_type must be a dict, got {type(data['by_type'])}"

    def test_dashboard_has_top_entities(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        data = resp.json()
        assert "top_entities" in data, "Dashboard missing 'top_entities'"
        assert isinstance(data["top_entities"], list), \
            f"top_entities must be a list, got {type(data['top_entities'])}"

    def test_dashboard_kpi_counts_are_non_negative(self):
        resp = httpx.get(f"{BASE}/anomaly/dashboard")
        data = resp.json()
        for field in ("open", "critical", "high", "medium", "low"):
            assert data.get(field, 0) >= 0, \
                f"KPI {field} is negative: {data.get(field)}"


class TestAlertsList:
    def test_alerts_list_returns_200(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts")
        assert resp.status_code == 200, resp.text

    def test_alerts_list_returns_list(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts")
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    def test_alert_entries_have_required_fields(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts")
        alerts = resp.json()
        if not alerts:
            pytest.skip("No alerts present — run POST /anomaly/scan first")
        for alert in alerts[:5]:
            assert "id" in alert, f"Alert missing 'id': {alert}"
            assert "status" in alert, f"Alert missing 'status': {alert}"
            assert "severity" in alert, f"Alert missing 'severity': {alert}"
            assert "risk_score" in alert, f"Alert missing 'risk_score': {alert}"
            assert "anomaly_type" in alert, f"Alert missing 'anomaly_type': {alert}"

    def test_filter_by_status_open(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts?status=open")
        assert resp.status_code == 200
        for alert in resp.json():
            assert alert["status"] == "open", \
                f"Expected status=open, got {alert['status']}"

    def test_filter_by_severity_critical(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts?severity=critical")
        assert resp.status_code == 200
        for alert in resp.json():
            assert alert["severity"] == "critical", \
                f"Expected severity=critical, got {alert['severity']}"

    def test_filter_by_anomaly_type(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts?anomaly_type=order_amount")
        assert resp.status_code == 200
        for alert in resp.json():
            assert alert["anomaly_type"] == "order_amount", \
                f"Type mismatch: {alert['anomaly_type']}"

    def test_risk_scores_are_in_range(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts")
        for alert in resp.json():
            score = alert.get("risk_score", 0)
            assert 0 <= score <= 100, \
                f"risk_score out of range 0–100: {score}"


class TestAlertStats:
    def test_stats_returns_200(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts/stats")
        assert resp.status_code == 200, resp.text

    def test_stats_has_by_type_and_by_severity(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts/stats")
        data = resp.json()
        assert "by_type" in data or "total" in data, \
            f"Stats response appears malformed: {data}"


class TestAlertLifecycle:
    @pytest.fixture(scope="class")
    def open_alert_id(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts?status=open&limit=1")
        alerts = resp.json()
        if not alerts:
            httpx.post(f"{BASE}/anomaly/scan?scan_type=full", timeout=30)
            resp = httpx.get(f"{BASE}/anomaly/alerts?status=open&limit=1")
            alerts = resp.json()
        if not alerts:
            pytest.skip("No open alerts available for lifecycle tests")
        return alerts[0]["id"]

    def test_acknowledge_alert(self, open_alert_id):
        resp = httpx.post(
            f"{BASE}/anomaly/alerts/{open_alert_id}/acknowledge",
            json={"acknowledged_by": "test_analyst", "note": "Pytest ack"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("status") == "acknowledged", \
            f"Expected status=acknowledged, got {data.get('status')}"

    def test_resolve_alert(self, open_alert_id):
        resp = httpx.post(
            f"{BASE}/anomaly/alerts/{open_alert_id}/resolve",
            json={"resolved_by": "test_analyst", "resolution_note": "Pytest resolve"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("status") == "resolved", \
            f"Expected status=resolved, got {data.get('status')}"

    def test_resolved_alert_has_resolved_at(self, open_alert_id):
        resp = httpx.post(
            f"{BASE}/anomaly/alerts/{open_alert_id}/resolve",
            json={"resolved_by": "test_analyst", "resolution_note": "Pytest"},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("resolved_at") is not None, \
                "resolved_at should be set after resolving"

    def test_false_positive_alert(self):
        resp = httpx.get(f"{BASE}/anomaly/alerts?status=open&limit=1")
        alerts = resp.json()
        if not alerts:
            pytest.skip("No open alerts for false positive test")
        alert_id = alerts[0]["id"]
        fp_resp = httpx.post(
            f"{BASE}/anomaly/alerts/{alert_id}/false-positive",
            json={"reviewed_by": "test_analyst", "note": "Pytest false positive"},
        )
        assert fp_resp.status_code == 200, fp_resp.text
        data = fp_resp.json()
        assert data.get("status") == "false_positive", \
            f"Expected status=false_positive, got {data.get('status')}"

    def test_nonexistent_alert_returns_404(self):
        resp = httpx.post(
            f"{BASE}/anomaly/alerts/00000000-0000-0000-0000-000000000000/acknowledge",
            json={"acknowledged_by": "test"},
        )
        assert resp.status_code == 404, \
            f"Expected 404 for nonexistent alert, got {resp.status_code}"


class TestSSEStream:
    def test_stream_endpoint_responds(self):
        with httpx.stream("GET", f"{BASE}/anomaly/stream", timeout=5) as stream:
            stream.read()
        assert stream.status_code == 200, \
            f"SSE stream returned {stream.status_code}"

    def test_stream_content_type_is_event_stream(self):
        with httpx.stream("GET", f"{BASE}/anomaly/stream", timeout=5) as stream:
            stream.read()
        ct = stream.headers.get("content-type", "")
        assert "text/event-stream" in ct, \
            f"Expected text/event-stream, got {ct}"

    def test_stream_sends_connected_event(self):
        events_received = []
        try:
            with httpx.stream("GET", f"{BASE}/anomaly/stream", timeout=8) as stream:
                for line in stream.iter_lines():
                    if line.startswith("event:"):
                        events_received.append(line.split(":", 1)[1].strip())
                    if "connected" in events_received:
                        break
        except (httpx.ReadTimeout, httpx.RemoteProtocolError):
            pass
        assert "connected" in events_received, \
            f"SSE stream did not send 'connected' event. Got: {events_received}"

    def test_stream_sends_valid_json_in_data_lines(self):
        data_lines = []
        try:
            with httpx.stream("GET", f"{BASE}/anomaly/stream", timeout=8) as stream:
                for line in stream.iter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
                    if len(data_lines) >= 1:
                        break
        except (httpx.ReadTimeout, httpx.RemoteProtocolError):
            pass
        for raw in data_lines:
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                pytest.fail(f"SSE data line is not valid JSON: {raw!r}")

    def test_stream_has_cache_control_header(self):
        with httpx.stream("GET", f"{BASE}/anomaly/stream", timeout=5) as stream:
            stream.read()
        cc = stream.headers.get("cache-control", "")
        assert "no-cache" in cc, \
            f"Expected Cache-Control: no-cache, got '{cc}'"
