"""
Locust load test for the E-Commerce AI Platform.

Usage:
    pip install locust
    locust -f load_test.py --host http://localhost:8002

    # Headless (CI mode):
    locust -f load_test.py --host http://localhost:8002 \
        --users 100 --spawn-rate 10 --run-time 60s --headless
"""

import random
from locust import HttpUser, task, between, events


SAMPLE_QUERIES = [
    "wireless headphones",
    "running shoes size 10",
    "waterproof jacket for monsoon",
    "laptop under 50000",
    "bluetooth speaker portable",
    "yoga mat anti-slip",
    "coffee maker automatic",
    "gaming mouse rgb",
    "sunglasses uv protection",
    "formal shirt white",
]

SAMPLE_NL_QUERIES = [
    "I need comfortable shoes for daily office use",
    "best headphones for gym workouts under 3000",
    "gifts for my mom who likes gardening",
    "lightweight laptop for college student",
    "waterproof hiking boots for trekking in Himalayas",
]


class ProductBrowseUser(HttpUser):
    """Simulates a user browsing products and performing semantic search."""
    wait_time = between(1, 3)
    weight = 3  # 3x more browse users than checkout users

    def on_start(self):
        self.product_ids = []
        resp = self.client.get("/products?limit=50", name="/products (browse)")
        if resp.status_code == 200:
            body = resp.json()
            items = body.get("items", body.get("products", body if isinstance(body, list) else []))
            self.product_ids = [p["id"] for p in items if "id" in p]

    @task(5)
    def browse_products(self):
        self.client.get("/products?limit=20", name="/products (list)")

    @task(3)
    def search_keyword(self):
        query = random.choice(SAMPLE_QUERIES)
        self.client.get(f"/products/search?q={query}", name="/products/search")

    @task(2)
    def semantic_search(self):
        query = random.choice(SAMPLE_NL_QUERIES)
        self.client.post(
            "/products/semantic-search",
            json={"query": query, "top_k": 5},
            name="/products/semantic-search",
        )

    @task(2)
    def view_product_detail(self):
        if self.product_ids:
            pid = random.choice(self.product_ids)
            self.client.get(f"/products/{pid}", name="/products/{id}")

    @task(1)
    def filter_by_category(self):
        categories = ["Electronics", "Fashion", "Books", "Home", "Sports"]
        cat = random.choice(categories)
        self.client.get(f"/products?category={cat}", name="/products?category=")

    @task(1)
    def health_check(self):
        self.client.get("/health", name="/health")


class CheckoutUser(HttpUser):
    """Simulates authenticated users adding items and checking out."""
    wait_time = between(2, 5)
    weight = 1

    def on_start(self):
        self.token = None
        self.product_ids = []

        # Register and login
        import uuid
        email = f"loadtest_{uuid.uuid4().hex[:8]}@example.com"
        self.client.post("/auth/register", json={
            "email": email,
            "password": "LoadTest@2024",
            "full_name": "Load Test User",
            "phone": "9000000000",
        }, name="/auth/register")

        resp = self.client.post("/auth/login", json={
            "email": email,
            "password": "LoadTest@2024",
        }, name="/auth/login")

        if resp.status_code == 200:
            self.token = resp.json().get("access_token")

        # Get product IDs (from product catalogue service)
        # In a real load test, these would come from the product catalogue
        self.product_ids = [f"prod_{i}" for i in range(1, 21)]

    def auth_headers(self):
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @task(3)
    def view_cart(self):
        self.client.get("/cart", headers=self.auth_headers(), name="/cart (view)")

    @task(2)
    def add_to_cart(self):
        if self.product_ids:
            pid = random.choice(self.product_ids)
            self.client.post(
                "/cart/items",
                json={"product_id": pid, "quantity": random.randint(1, 3)},
                headers=self.auth_headers(),
                name="/cart/items (add)",
            )

    @task(1)
    def view_orders(self):
        self.client.get("/orders", headers=self.auth_headers(), name="/orders (list)")


class MetricsCollector(HttpUser):
    """Low-frequency scraper simulating Prometheus scraping /metrics."""
    wait_time = between(15, 30)
    weight = 1

    @task
    def scrape_metrics(self):
        self.client.get("/metrics", name="/metrics")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("Load test starting...")
    print(f"Target host: {environment.host}")
    print("User types: ProductBrowseUser (3x), CheckoutUser (1x), MetricsCollector (1x)")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats
    print(f"\nLoad test complete.")
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Total failures: {stats.total.num_failures}")
    print(f"Failure rate: {stats.total.fail_ratio:.1%}")
    print(f"Avg response time: {stats.total.avg_response_time:.0f}ms")
    print(f"P95 response time: {stats.total.get_response_time_percentile(0.95):.0f}ms")
    print(f"P99 response time: {stats.total.get_response_time_percentile(0.99):.0f}ms")
