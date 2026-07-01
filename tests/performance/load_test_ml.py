"""
Locust load test for the three ML/AI capstone features.

Services under test:
  inventory_service      :8005  — demand forecasting
  recommendation_engine  :8006  — feedback loop + adapted recommendations
  guardrails_service     :8010  — anomaly detection scan + dashboard

Usage:
    # Interactive (browser at http://localhost:8089)
    locust -f load_test_ml.py

    # Headless: 20 users, 60s
    locust -f load_test_ml.py \
        --users 20 --spawn-rate 2 --run-time 60s --headless
"""
import random
from locust import HttpUser, task, between, events


# ── Sample data ──────────────────────────────────────────────────────────────

CATEGORIES = [
    "Electronics", "Books", "Clothing", "Sports", "Toys",
    "Furniture", "Appliances", "Groceries", "Beauty", "Automotive",
]
FEEDBACK_TYPES = ["thumbs_up", "thumbs_down", "not_interested"]
BRANDS = ["Sony", "Samsung", "Nike", "Adidas", "Philips", "Bosch", "LG", "boAt"]
CUSTOMER_IDS = [f"cust_load_{i:04d}" for i in range(1, 51)]
PRODUCT_IDS = [f"prod_load_{i:04d}" for i in range(1, 201)]
SCAN_TYPES = ["full", "user", "inventory", "payment"]


# ── Forecasting load tests ────────────────────────────────────────────────────

class ForecastingUser(HttpUser):
    host = "http://localhost:8005"
    wait_time = between(1, 3)
    weight = 3

    @task(5)
    def get_forecast_summary(self):
        self.client.get("/forecast/summary", name="/forecast/summary")

    @task(4)
    def list_forecast_categories(self):
        self.client.get("/forecast/categories", name="/forecast/categories")

    @task(6)
    def get_category_forecast(self):
        cat = random.choice(CATEGORIES)
        self.client.get(
            f"/forecast/category/{cat}",
            name="/forecast/category/[cat]",
        )

    @task(3)
    def get_restock_alerts(self):
        self.client.get("/forecast/restock-alerts", name="/forecast/restock-alerts")

    @task(2)
    def get_restock_alerts_critical(self):
        self.client.get(
            "/forecast/restock-alerts?severity=critical",
            name="/forecast/restock-alerts?severity=critical",
        )

    @task(1)
    def train_forecast_model(self):
        with self.client.post(
            "/forecast/train",
            catch_response=True,
            timeout=60,
            name="/forecast/train",
        ) as resp:
            if resp.status_code not in (200, 202):
                resp.failure(f"Unexpected status: {resp.status_code}")
            else:
                resp.success()


# ── Feedback loop load tests ──────────────────────────────────────────────────

class FeedbackLoopUser(HttpUser):
    host = "http://localhost:8006"
    wait_time = between(0.5, 2)
    weight = 5

    def on_start(self):
        self.customer_id = random.choice(CUSTOMER_IDS)

    @task(8)
    def submit_feedback(self):
        self.client.post(
            "/feedback",
            json={
                "customer_id": self.customer_id,
                "product_id": random.choice(PRODUCT_IDS),
                "feedback_type": random.choice(FEEDBACK_TYPES),
                "category": random.choice(CATEGORIES),
                "brand": random.choice(BRANDS),
                "rec_strategy": random.choice(["collaborative", "content", "trending"]),
            },
            name="/feedback",
        )

    @task(6)
    def get_adapted_recommendations(self):
        cid = random.choice(CUSTOMER_IDS)
        self.client.get(
            f"/recommendations/for/{cid}?limit=10",
            name="/recommendations/for/[id]",
        )

    @task(3)
    def get_feedback_history(self):
        self.client.get(
            f"/feedback/{self.customer_id}",
            name="/feedback/[customer_id]",
        )

    @task(2)
    def get_adaptation_state(self):
        self.client.get(
            f"/feedback/{self.customer_id}/adaptation",
            name="/feedback/[customer_id]/adaptation",
        )

    @task(1)
    def get_loop_stats(self):
        self.client.get("/feedback/loop/stats", name="/feedback/loop/stats")


# ── Anomaly detection load tests ──────────────────────────────────────────────

class AnomalyDetectionUser(HttpUser):
    host = "http://localhost:8010"
    wait_time = between(1, 4)
    weight = 2

    @task(7)
    def get_dashboard(self):
        self.client.get("/anomaly/dashboard", name="/anomaly/dashboard")

    @task(6)
    def list_alerts(self):
        status = random.choice(["open", "acknowledged", "resolved"])
        self.client.get(
            f"/anomaly/alerts?status={status}&limit=20",
            name="/anomaly/alerts?status=[status]",
        )

    @task(4)
    def list_alerts_by_severity(self):
        sev = random.choice(["critical", "high", "medium", "low"])
        self.client.get(
            f"/anomaly/alerts?severity={sev}",
            name="/anomaly/alerts?severity=[sev]",
        )

    @task(2)
    def get_alert_stats(self):
        self.client.get("/anomaly/alerts/stats", name="/anomaly/alerts/stats")

    @task(1)
    def run_targeted_scan(self):
        scan_type = random.choice(SCAN_TYPES)
        with self.client.post(
            f"/anomaly/scan?scan_type={scan_type}",
            catch_response=True,
            timeout=30,
            name="/anomaly/scan?scan_type=[type]",
        ) as resp:
            if resp.status_code not in (200, 202):
                resp.failure(f"Unexpected status: {resp.status_code}")
            else:
                resp.success()


# ── Event hooks ───────────────────────────────────────────────────────────────

@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    if environment.stats.total.fail_ratio > 0.05:
        environment.process_exit_code = 1
        print(f"\nFAIL: error rate {environment.stats.total.fail_ratio:.1%} exceeds 5% threshold")
    else:
        print(f"\nPASS: error rate {environment.stats.total.fail_ratio:.1%}")
