# Service Map

## Overview

The platform is composed of 13 FastAPI microservices, 1 React frontend, and 1 shared NFR utility module.
Each service is independently runnable with its own database connection and port.

---

## Service Registry

| Service | Port | Database | Auth Required | Key Dependencies |
|---------|------|----------|---------------|-----------------|
| `user_management` | 8001 | SQLite (`user_management.db`) | No (auth endpoints public) | — |
| `product_catalogue` | 8002 | PostgreSQL (`ecommerce`) | Optional | `pgvector`, Azure OpenAI embeddings |
| `checkout_service` | 8003 | PostgreSQL (`ecommerce`) | Yes | `inventory_service`, `payment_shipping_service` |
| `recommendation_engine` | 8004 | PostgreSQL (`ecommerce`) | Yes | `session_service`, `order_management` |
| `inventory_service` | 8005 | PostgreSQL (`ecommerce`) | Yes | — |
| `order_management` | 8006 | PostgreSQL (`ecommerce`) | Yes | `inventory_service` |
| `session_service` | 8007 | PostgreSQL (`ecommerce`) | Optional | — |
| `payment_shipping_service` | 8008 | PostgreSQL (`ecommerce`) | Yes | Razorpay API, Shiprocket API |
| `guardrails_service` | 8009 | — (stateless) | No | Azure OpenAI |
| `multi_agent_system` | 8010 | PostgreSQL (`ecommerce`) | Yes | Azure OpenAI, all domain services |
| `seller_portal` | 8011 | SQLite (`seller_portal.db`) | Seller JWT | — |
| `shopping_assistant` | 8012 | PostgreSQL (`ecommerce`) | Optional | `product_catalogue`, `guardrails_service`, Azure OpenAI |
| `tool_calling_agent` | 8013 | — | Yes | Azure OpenAI, domain services |
| `frontend` | 5173 | — | — | All backend services via Axios |

---

## Shared Module: `nfr/`

Located at `src/nfr/`, imported by all services via `sys.path` injection at startup.

| Module | Purpose |
|--------|---------|
| `structured_logging.py` | JSON log formatter, `RequestLoggingMiddleware` with trace ID injection |
| `circuit_breaker.py` | Thread-safe circuit breaker with CLOSED/OPEN/HALF_OPEN states |
| `metrics.py` | Prometheus instrumentation via `prometheus_fastapi_instrumentator` |

---

## Inter-Service Communication

All inter-service calls are synchronous HTTP (httpx). The call graph for the two primary user journeys:

### Checkout Flow

```
Frontend
  → checkout_service (POST /checkout)
      → inventory_service (reserve stock)
      → payment_shipping_service (create Razorpay order)
  ← checkout_service returns order_id + payment_link

[User completes payment on Razorpay]
  → payment_shipping_service (Razorpay webhook)
      → order_management (advance to confirmed)
      → payment_shipping_service (submit to Shiprocket)
```

### RAG Shopping Assistant Flow

```
Frontend
  → shopping_assistant (POST /ask)
      → guardrails_service (validate input)
      → product_catalogue (embed query + pgvector search)
      ← top-k products returned
      → Azure OpenAI GPT-4o-mini (augment with product context)
      → guardrails_service (validate output)
  ← shopping_assistant returns conversational response
```

---

## Database Schema Summary

### PostgreSQL (`ecommerce`)

| Table | Owned By | Key Columns |
|-------|----------|-------------|
| `products` | product_catalogue | id, name, description, embedding (vector(1536)), category, brand, price, stock |
| `product_categories` | product_catalogue | id, name, parent_id |
| `customers` | user_management | id, email_hash, name |
| `orders` | order_management | id, user_id, status, total_amount, idempotency_key |
| `order_items` | order_management | id, order_id, product_id, quantity, unit_price |
| `cart_items` | checkout_service | id, user_id, product_id, quantity |
| `checkout_idempotency_keys` | checkout_service | key (PK), endpoint, order_id, status_code, response_body |
| `inventory` | inventory_service | product_id (PK), available_qty, reserved_qty |
| `browsing_events` | session_service | id, user_id, product_id, event_type, timestamp |
| `payments` | payment_shipping_service | id, order_id, razorpay_order_id, status |
| `shipments` | payment_shipping_service | id, order_id, shiprocket_id, tracking_url |

### SQLite (`user_management.db`)

| Table | Key Columns |
|-------|-------------|
| `users` | id, email, password_hash, full_name, phone, is_active |
| `addresses` | id, user_id, street, city, pincode, is_default |
| `payment_methods` | id, user_id, card_token, last_four, card_brand |

### SQLite (`seller_portal.db`)

| Table | Key Columns |
|-------|-------------|
| `sellers` | id, business_name, email, password_hash, gst_number, pan_number, status |
| `seller_products` | id, seller_id, name, mrp, selling_price, approval_status |
| `seller_orders` | id, seller_id, order_item_id, commission_rate, payout_status |

---

## External Integrations

| Integration | Service | Purpose |
|-------------|---------|---------|
| Azure OpenAI — `gpt-4o-mini` | shopping_assistant, multi_agent_system, guardrails_service | Chat completions, agent reasoning |
| Azure OpenAI — `text-embedding-3-small` | product_catalogue | 1536-dim product embeddings |
| Azure OpenAI — LLM Judge | guardrails_service | Evaluate output safety and relevance |
| Razorpay | payment_shipping_service | Payment order creation and webhook |
| Shiprocket | payment_shipping_service | Logistics booking and tracking |
