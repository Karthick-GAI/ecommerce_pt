# E-Commerce AI Platform — Capstone Project

An end-to-end AI-powered e-commerce platform demonstrating microservices architecture, RAG-based shopping assistance, multi-agent order management, and hybrid recommendation systems. Built as a capstone project integrating Azure OpenAI, pgvector semantic search, and a React frontend.

---

## Quick Start

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| PostgreSQL | 15+ with `pgvector` extension |
| Azure OpenAI | Account with `gpt-4o-mini` + `text-embedding-3-small` deployed |

### 1. Clone & Configure

```bash
git clone https://github.com/Karthick-GAI/ecommerce_pt.git
cd ecommerce_pt
```

Copy and fill environment variables for each service:

```bash
cp src/user_management/.env.example src/user_management/.env
# Repeat for each service that has a .env.example
```

Key variables (required):

```
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
DATABASE_URL=postgresql://postgres:password@localhost:5432/ecommerce
JWT_SECRET_KEY=<random-256-bit-secret>
```

### 2. PostgreSQL Setup

```bash
# Enable pgvector extension (run once as superuser)
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -U postgres -c "CREATE DATABASE ecommerce;"
```

### 3. Ingest Synthetic Dataset

```bash
cd src/product_catalogue
pip install -r requirements.txt
python scripts/seed_data.py          # 5K products, 10K customers
python scripts/generate_embeddings.py # 1536-dim vectors via text-embedding-3-small
```

### 4. Start All Services

Each service runs on its own port. Open 13 terminal tabs or use the provided helper:

```bash
# Option A: start all with one command (requires tmux)
bash scripts/start_all.sh

# Option B: start individually
cd src/user_management    && uvicorn main:app --port 8001 --reload &
cd src/product_catalogue  && uvicorn main:app --port 8002 --reload &
cd src/checkout_service   && uvicorn main:app --port 8003 --reload &
cd src/recommendation_engine && uvicorn main:app --port 8004 --reload &
cd src/inventory_service  && uvicorn main:app --port 8005 --reload &
cd src/order_management   && uvicorn main:app --port 8006 --reload &
cd src/session_service    && uvicorn main:app --port 8007 --reload &
cd src/payment_shipping_service && uvicorn main:app --port 8008 --reload &
cd src/guardrails_service && uvicorn main:app --port 8009 --reload &
cd src/multi_agent_system && uvicorn main:app --port 8010 --reload &
cd src/shopping_assistant && uvicorn main:app --port 8012 --reload &
cd src/tool_calling_agent && uvicorn main:app --port 8013 --reload &
cd src/seller_portal      && uvicorn main:app --port 8011 --reload &
```

### 5. Start Frontend

```bash
cd src/frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173
```

---

## Service Catalog

| Service | Port | Description |
|---------|------|-------------|
| `user_management` | 8001 | JWT auth, GDPR erasure/export, bcrypt passwords |
| `product_catalogue` | 8002 | Product CRUD, pgvector semantic search, embeddings |
| `checkout_service` | 8003 | Cart, idempotent order placement, Razorpay payment |
| `recommendation_engine` | 8004 | Collaborative filtering + content-based hybrid |
| `inventory_service` | 8005 | Stock levels, reservation, oversell prevention |
| `order_management` | 8006 | Order lifecycle, status transitions |
| `session_service` | 8007 | Browsing session tracking, event stream |
| `payment_shipping_service` | 8008 | Razorpay webhook handler, Shiprocket integration |
| `guardrails_service` | 8009 | Input/output content moderation |
| `multi_agent_system` | 8010 | Orchestrator + 4 specialist agents for escalations |
| `seller_portal` | 8011 | B2B KYC onboarding, product approval workflow |
| `shopping_assistant` | 8012 | RAG pipeline: NL query → pgvector → GPT augment |
| `tool_calling_agent` | 8013 | Function-calling agent for structured operations |
| `frontend` | 5173 | React 18 + Vite SPA (B2C storefront + B2B portal) |

---

## API Reference

Each FastAPI service auto-generates interactive docs. After starting:

- **Swagger UI**: `http://localhost:<port>/docs`
- **ReDoc**: `http://localhost:<port>/redoc`
- **Metrics**: `http://localhost:<port>/metrics` (Prometheus format)
- **Health**: `http://localhost:<port>/health`

---

## Architecture

See [docs/architecture/architecture_diagram.html](docs/architecture/architecture_diagram.html) for the full interactive system diagram.

High-level layers:

```
[React 18 + Vite Frontend]
         ↓
[FastAPI Microservices — 13 services across ports 8001–8013]
         ↓
[AI/ML Layer: Azure OpenAI GPT-4o-mini, text-embedding-3-small]
         ↓
[Data Layer: PostgreSQL + pgvector, SQLite (users/sellers)]
         ↓
[External: Razorpay Payments, Shiprocket Logistics]
```

---

## Synthetic Dataset

| Entity | Volume |
|--------|--------|
| Products | 5,000 |
| Customers | 10,000 |
| Orders | 50,000 |
| Browsing events | 150,000 |
| Wishlists | 30,000 |
| Search logs | 15,000 |

---

## Non-Functional Requirements

| Dimension | Implementation |
|-----------|---------------|
| Performance | Async FastAPI, pgvector ANN index, response caching |
| Security | JWT + bcrypt, slowapi rate limiting (3/min register, 5/min login) |
| Reliability | Idempotency keys on checkout, circuit breaker pattern |
| Observability | Prometheus metrics, structured JSON logging, X-Trace-ID |
| GDPR | Art.17 erasure endpoint, Art.20 data-export endpoint |
| Availability | Circuit breaker with CLOSED→OPEN→HALF_OPEN transitions |
| B2B/B2C | Seller portal (port 8011) with KYC onboarding + product approval |

---

## Running Tests

```bash
# API tests
cd tests/api
pip install pytest httpx
pytest -v

# Performance / load tests
cd tests/performance
pip install locust
locust -f load_test.py --host http://localhost:8002
```

---

## Project Structure

```
ecommerce_pt/
├── src/                    # All 13 microservices + shared NFR module + frontend
│   ├── nfr/               # Shared: circuit_breaker, structured_logging, metrics
│   ├── user_management/   # Auth, GDPR
│   ├── product_catalogue/ # Catalogue, embeddings, semantic search
│   ├── checkout_service/  # Cart, idempotent checkout
│   ├── recommendation_engine/
│   ├── inventory_service/
│   ├── order_management/
│   ├── session_service/
│   ├── payment_shipping_service/
│   ├── guardrails_service/
│   ├── multi_agent_system/
│   ├── shopping_assistant/
│   ├── tool_calling_agent/
│   ├── seller_portal/
│   └── frontend/
├── docs/
│   ├── architecture/      # System diagram, service map
│   └── data-flow/         # Ingestion, RAG retrieval, recommendation flows
├── requirements/          # Functional + non-functional requirements specs
├── tests/
│   ├── api/              # Pytest integration tests
│   └── performance/      # Locust load tests
└── README.md
```

---

## Team & Context

Capstone project demonstrating AI integration patterns for e-commerce:
- **RAG pipeline** for conversational product discovery
- **Multi-agent system** for automated order issue resolution
- **Hybrid recommender** combining collaborative filtering + content signals
- **B2B seller portal** with approval workflow and commission tracking
