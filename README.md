# AI-Powered E-Commerce Platform

A capstone project demonstrating microservices architecture with AI integration. 13 independent FastAPI services covering the full e-commerce lifecycle — user auth, product catalogue with vector search, AI shopping assistant (RAG), hybrid recommendations, checkout with idempotency, and a B2B seller portal.

---

## Table of Contents

1. [Architecture at a Glance](#architecture-at-a-glance)
2. [Service Catalog](#service-catalog)
3. [Prerequisites](#prerequisites)
4. [Project Setup](#project-setup)
   - [Step 1 — Clone and configure environment](#step-1--clone-and-configure-environment)
   - [Step 2 — Database setup](#step-2--database-setup)
   - [Step 3 — Install dependencies](#step-3--install-dependencies)
   - [Step 4 — Seed product data](#step-4--seed-product-data)
   - [Step 5 — Start services](#step-5--start-services)
   - [Step 6 — Verify all services are healthy](#step-6--verify-all-services-are-healthy)
5. [Minimal Quick Start (no PostgreSQL needed)](#minimal-quick-start-no-postgresql-needed)
6. [End-to-End Usage Examples](#end-to-end-usage-examples)
   - [Example 1 — Register, login, and manage your profile](#example-1--register-login-and-manage-your-profile)
   - [Example 2 — Browse and search the product catalogue](#example-2--browse-and-search-the-product-catalogue)
   - [Example 3 — AI Shopping Assistant (RAG pipeline)](#example-3--ai-shopping-assistant-rag-pipeline)
   - [Example 4 — Checkout with idempotency](#example-4--checkout-with-idempotency)
7. [Running Tests](#running-tests)
8. [Project Structure](#project-structure)
9. [Troubleshooting](#troubleshooting)

---

## Architecture at a Glance

```
[React 18 + Vite  :5173]
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│                    FastAPI Microservices                        │
│  user_management :8001  │  product_catalogue :8002             │
│  checkout        :8003  │  recommendation    :8004             │
│  inventory       :8005  │  order_management  :8006             │
│  session         :8007  │  payment_shipping  :8008             │
│  guardrails      :8009  │  multi_agent       :8010             │
│  seller_portal   :8011  │  shopping_assistant:8012             │
│  tool_calling    :8013                                         │
└────────────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
  PostgreSQL + pgvector      Azure OpenAI
  (products, orders,         (gpt-5.4-mini + text-embedding-3-small)
   vectors, sessions)
         │
  SQLite (user auth,
          seller auth)
```

---

## Service Catalog

| Service | Port | Database | Requires Azure OpenAI | Description |
|---------|------|-----------|-----------------------|-------------|
| `user_management` | 8001 | SQLite | No | JWT auth, GDPR erasure/export |
| `product_catalogue` | 8002 | PostgreSQL + pgvector | Yes (embeddings) | Products, search, reviews |
| `checkout_service` | 8003 | PostgreSQL | No | Cart, idempotent order placement |
| `recommendation_engine` | 8004 | PostgreSQL | No | Hybrid CF + content + trending |
| `inventory_service` | 8005 | PostgreSQL | No | Stock levels, reservations |
| `order_management` | 8006 | PostgreSQL | No | Order lifecycle, refunds |
| `session_service` | 8007 | PostgreSQL | No | Browsing events, session tracking |
| `payment_shipping_service` | 8008 | PostgreSQL | No | Razorpay + Shiprocket integration |
| `guardrails_service` | 8009 | PostgreSQL | Yes (LLM judge) | AI input/output safety |
| `multi_agent_system` | 8010 | PostgreSQL | Yes (GPT agents) | Orchestrator + 4 specialist agents |
| `seller_portal` | 8011 | SQLite | No | B2B KYC onboarding, product approval |
| `shopping_assistant` | 8012 | PostgreSQL | Yes (RAG) | NL query → vector search → GPT |
| `tool_calling_agent` | 8013 | PostgreSQL | Yes (function calls) | Structured tool-call agent |

**Interactive API docs** for every service: `http://localhost:<port>/docs`

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | All backend services |
| pip | 23+ | Dependency management |
| PostgreSQL | 15+ | Product catalogue, orders, vectors |
| pgvector extension | 0.7+ | Semantic search in PostgreSQL |
| Node.js | 18+ | React frontend only |
| Azure OpenAI account | — | AI features (search, RAG, agents) |

> **Note**: `user_management` and `seller_portal` use SQLite and have **no PostgreSQL or Azure OpenAI dependency** — they can be started immediately after Python install.

---

## Project Setup

### Step 1 — Clone and configure environment

```bash
git clone https://github.com/Karthick-GAI/ecommerce_pt.git
cd ecommerce_pt

# Create your .env from the template
cp .env.example .env
```

Edit `.env` and fill in your values:

```bash
# Minimum required for AI features
AZURE_OPENAI_API_KEY=your_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2025-04-01-preview
AZURE_OPENAI_GPT54_MINI_DEPLOYMENT=gpt-5.4-mini
AZURE_OPENAI_EMBEDDING_SMALL=text-embedding-3-small

# PostgreSQL (default works if running PostgreSQL locally with default settings)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ecommerce
```

### Step 2 — Database setup

```bash
# Create the PostgreSQL database and enable pgvector
bash scripts/setup_db.sh
```

If you prefer to run the commands manually:

```sql
-- In psql as superuser:
CREATE DATABASE ecommerce;
\c ecommerce
CREATE EXTENSION IF NOT EXISTS vector;
```

### Step 3 — Install dependencies

Each service is independently installable. Install them all in one pass:

```bash
for svc in src/*/; do
  if [ -f "$svc/requirements.txt" ]; then
    echo "Installing $svc..."
    pip install -r "$svc/requirements.txt" -q
  fi
done
```

Or install just the service you need:

```bash
# Example: only user_management (no PostgreSQL needed)
pip install -r src/user_management/requirements.txt
```

### Step 4 — Seed product data

This step is required for product browsing, semantic search, and the AI shopping assistant.

```bash
bash scripts/seed_products.sh
```

What it does:
- Inserts 5,000 synthetic products into PostgreSQL
- Calls Azure OpenAI `text-embedding-3-small` to generate 1536-dim embeddings for each product
- Estimated time: 2–3 minutes at default API rate limits

### Step 5 — Start services

```bash
# Start all 13 services in the background (one uvicorn process each)
bash scripts/start_all.sh

# Or start a single service directly
cd src/user_management
PYTHONPATH=.. uvicorn main:app --port 8001 --reload
```

Service logs are written to `logs/<service_name>.log`.

To stop all services:

```bash
bash scripts/start_all.sh --stop
```

### Step 6 — Verify all services are healthy

```bash
for port in 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010 8011 8012 8013; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/health)
  echo "Port $port: $STATUS"
done
```

Expected output (all services running):

```
Port 8001: 200
Port 8002: 200
...
Port 8013: 200
```

---

## Minimal Quick Start (no PostgreSQL needed)

If you only want to verify auth and JWT flows without any external dependencies:

```bash
# 1. Install
pip install -r src/user_management/requirements.txt

# 2. Start (SQLite, no PostgreSQL)
cd src/user_management
PYTHONPATH=.. uvicorn main:app --port 8001 --reload

# 3. Open browser
open http://localhost:8001/docs
```

The Swagger UI lets you run every endpoint interactively. Continue to Example 1 below for the curl walkthrough.

---

## End-to-End Usage Examples

All examples use `curl`. Replace `localhost` with your server IP if running remotely.

---

### Example 1 — Register, login, and manage your profile

**Service**: `user_management` at `http://localhost:8001`
**Dependencies**: None (SQLite only)

#### 1a. Register a new account

```bash
curl -s -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "priya.sharma@example.com",
    "password": "Priya@2024",
    "first_name": "Priya",
    "last_name": "Sharma",
    "phone": "9876543210"
  }' | python3 -m json.tool
```

**Response** (`201 Created`):

```json
{
  "message": "Account created successfully",
  "user_id": "usr_3f8a2b1c4d5e6f7a"
}
```

**Validation rules enforced by the service:**
- Password: minimum 8 characters, 1 uppercase, 1 digit
- Phone: 10-digit Indian mobile number (starts with 6–9)
- Email: duplicate email returns `400 Bad Request`
- Rate limit: 3 registrations per minute per IP → `429 Too Many Requests`

#### 1b. Login and get JWT tokens

```bash
curl -s -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "priya.sharma@example.com",
    "password": "Priya@2024"
  }' | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfM2Y4YTJiMWM0ZDVlNmY3YSIsInR5cGUiOiJhY2Nlc3MiLCJleHAiOjE3NTAwMDAwMDB9.abc123",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3JfM2Y4YTJiMWM0ZDVlNmY3YSIsInR5cGUiOiJyZWZyZXNoIiwiZXhwIjoxNzUwNjAwMDAwfQ.xyz789",
  "token_type": "bearer"
}
```

Save the access token for authenticated requests:

```bash
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### 1c. View your profile

```bash
curl -s http://localhost:8001/users/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "id": "usr_3f8a2b1c4d5e6f7a",
  "email": "priya.sharma@example.com",
  "first_name": "Priya",
  "last_name": "Sharma",
  "phone": "9876543210",
  "is_active": true,
  "created_at": "2026-06-23T10:15:00",
  "updated_at": "2026-06-23T10:15:00"
}
```

#### 1d. Add a shipping address

```bash
curl -s -X POST http://localhost:8001/users/me/addresses \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "label": "Home",
    "full_name": "Priya Sharma",
    "phone": "9876543210",
    "line1": "42, MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "pincode": "560001"
  }' | python3 -m json.tool
```

**Response** (`201 Created`):

```json
{
  "id": "addr_7c9d2e1f3a4b5c6d",
  "label": "Home",
  "full_name": "Priya Sharma",
  "phone": "9876543210",
  "alternate_phone": null,
  "line1": "42, MG Road",
  "line2": null,
  "landmark": null,
  "city": "Bengaluru",
  "state": "Karnataka",
  "pincode": "560001",
  "is_default": true,
  "created_at": "2026-06-23T10:16:00"
}
```

#### 1e. GDPR — export all personal data

```bash
curl -s http://localhost:8001/users/me/data-export \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Response** (`200 OK` — Art. 20 data portability):

```json
{
  "email": "priya.sharma@example.com",
  "first_name": "Priya",
  "last_name": "Sharma",
  "phone": "9876543210",
  "created_at": "2026-06-23T10:15:00",
  "addresses": [
    {
      "label": "Home",
      "line1": "42, MG Road",
      "city": "Bengaluru",
      "pincode": "560001"
    }
  ],
  "payment_methods": []
}
```

#### 1f. Wrong password — observe account-takeover protection

```bash
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "Attempt $i: HTTP %{http_code}\n" \
    -X POST http://localhost:8001/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"priya.sharma@example.com","password":"Wrong123"}'
done
```

**Output**:

```
Attempt 1: HTTP 401
Attempt 2: HTTP 401
Attempt 3: HTTP 401
Attempt 4: HTTP 401
Attempt 5: HTTP 401
Attempt 6: HTTP 429    ← rate limit kicks in
```

---

### Example 2 — Browse and search the product catalogue

**Service**: `product_catalogue` at `http://localhost:8002`
**Dependencies**: PostgreSQL + pgvector (seed data required)

> Run `bash scripts/seed_products.sh` before this example.

#### 2a. List products with filters

```bash
curl -s "http://localhost:8002/products?category=Electronics&price_max=30000&sort_by=rating&limit=3" \
  | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "total": 243,
  "page": 1,
  "limit": 3,
  "pages": 81,
  "items": [
    {
      "id": "prod_a1b2c3d4e5f6",
      "name": "boAt Airdopes 141 TWS Earbuds",
      "brand": "boAt",
      "category": "Electronics",
      "subcategory": "Earbuds",
      "price": 1299.0,
      "discount_pct": 15.0,
      "effective_price": 1104.15,
      "rating_avg": 4.3,
      "rating_count": 8420,
      "inventory_count": 150,
      "in_stock": true
    },
    {
      "id": "prod_b2c3d4e5f6a1",
      "name": "Redmi Note 13 Pro (8GB RAM, 256GB)",
      "brand": "Redmi",
      "category": "Electronics",
      "subcategory": "Smartphones",
      "price": 24999.0,
      "discount_pct": 5.0,
      "effective_price": 23749.05,
      "rating_avg": 4.2,
      "rating_count": 5631,
      "inventory_count": 42,
      "in_stock": true
    },
    {
      "id": "prod_c3d4e5f6a1b2",
      "name": "Samsung Galaxy Buds2 Pro",
      "brand": "Samsung",
      "category": "Electronics",
      "subcategory": "Earbuds",
      "price": 9999.0,
      "discount_pct": 20.0,
      "effective_price": 7999.2,
      "rating_avg": 4.1,
      "rating_count": 2317,
      "inventory_count": 28,
      "in_stock": true
    }
  ]
}
```

#### 2b. Keyword search

```bash
curl -s "http://localhost:8002/search/keyword?q=wireless+headphones&price_max=5000&in_stock=true&limit=2" \
  | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "query": "wireless headphones",
  "total": 18,
  "results": [
    {
      "id": "prod_d4e5f6a1b2c3",
      "name": "JBL Tune 510BT Wireless Headphones",
      "brand": "JBL",
      "effective_price": 2099.0,
      "rating_avg": 4.4,
      "in_stock": true
    },
    {
      "id": "prod_e5f6a1b2c3d4",
      "name": "boAt Rockerz 450 Wireless Headphone",
      "brand": "boAt",
      "effective_price": 1299.0,
      "rating_avg": 4.2,
      "in_stock": true
    }
  ]
}
```

#### 2c. Semantic (natural language) search

This calls `text-embedding-3-small` to embed the query, then runs pgvector cosine similarity — no exact keyword matching needed.

```bash
curl -s "http://localhost:8002/search/semantic?q=noise+cancelling+headphones+for+office+calls&limit=3" \
  | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "query": "noise cancelling headphones for office calls",
  "parsed_filters": {
    "keywords": "noise cancelling headphones office calls",
    "category": "Electronics",
    "subcategory": "Headphones",
    "max_price": null,
    "features": ["noise cancelling", "microphone"]
  },
  "total": 3,
  "results": [
    {
      "id": "prod_f6a1b2c3d4e5",
      "name": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
      "brand": "Sony",
      "category": "Electronics",
      "effective_price": 24990.0,
      "rating_avg": 4.7,
      "similarity_score": 0.912,
      "in_stock": true
    },
    {
      "id": "prod_a1b2c3d4e5f7",
      "name": "Jabra Evolve2 55 UC Wireless Headset",
      "brand": "Jabra",
      "category": "Electronics",
      "effective_price": 19990.0,
      "rating_avg": 4.5,
      "similarity_score": 0.884,
      "in_stock": true
    },
    {
      "id": "prod_b2c3d4e5f6a2",
      "name": "Bose QuietComfort 45 Headphones",
      "brand": "Bose",
      "category": "Electronics",
      "effective_price": 22490.0,
      "rating_avg": 4.6,
      "similarity_score": 0.871,
      "in_stock": false
    }
  ]
}
```

**What makes this different from keyword search**: the query `"office calls"` has no exact keyword match in any product name — the semantic search found the Jabra headset by understanding that "office calls" semantically implies a headset with a microphone.

#### 2d. Get a product detail page

```bash
curl -s http://localhost:8002/products/prod_f6a1b2c3d4e5 \
  | python3 -m json.tool
```

**Response** (`200 OK`) — includes specs, images, review summary:

```json
{
  "id": "prod_f6a1b2c3d4e5",
  "name": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
  "brand": "Sony",
  "category": "Electronics",
  "subcategory": "Headphones",
  "description": "Industry-leading noise cancellation with Auto NC Optimizer...",
  "price": 29990.0,
  "discount_pct": 16.67,
  "effective_price": 24990.0,
  "rating_avg": 4.7,
  "rating_count": 1248,
  "inventory_count": 15,
  "in_stock": true,
  "specifications": {
    "Driver Size": "30mm",
    "Frequency Response": "4Hz–40kHz",
    "Battery Life": "30 hours",
    "Bluetooth": "5.2",
    "Weight": "250g"
  },
  "images": [
    { "url": "/images/sony-wh1000xm5-front.jpg", "is_primary": true }
  ],
  "reviews": []
}
```

---

### Example 3 — AI Shopping Assistant (RAG pipeline)

**Service**: `shopping_assistant` at `http://localhost:8012`
**Dependencies**: PostgreSQL + pgvector (seed data required) + Azure OpenAI

The assistant follows a 7-step pipeline per message:
`parse query → embed → pgvector cosine search → build context → GPT-5.4-mini augment → guardrail check → return`

#### 3a. Start a new conversation

```bash
curl -s -X POST http://localhost:8012/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I need wireless earbuds for running, budget under ₹3000"
  }' | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "session_id": "sess_9a8b7c6d5e4f3a2b",
  "reply": "Great choice for a running companion! Based on your ₹3,000 budget, here are the best wireless earbuds I found:\n\n1. **boAt Airdopes 141** (₹1,104) — IPX4 sweat resistance, 42-hour total playtime, secure ear hooks. Bestseller with 4.3★ from 8,400+ reviews.\n\n2. **Boult Audio Z40** (₹1,299) — True wireless, IPX5 water resistance, 40-hour battery. Good for longer runs.\n\n3. **JBL Tune 215TWS** (₹2,499) — JBL Pure Bass Sound, 6-hour earbud battery + 21 hours with case.\n\nFor running specifically, I'd recommend the **boAt Airdopes 141** — the ear hooks ensure they stay in place during movement, and the IPX4 rating handles sweat well.",
  "sources": [
    {
      "id": "prod_a1b2c3d4e5f6",
      "name": "boAt Airdopes 141 TWS Earbuds",
      "category": "Electronics",
      "effective_price": 1104.15,
      "in_stock": true
    },
    {
      "id": "prod_c3d4e5f7a1b2",
      "name": "Boult Audio Z40 True Wireless",
      "category": "Electronics",
      "effective_price": 1299.0,
      "in_stock": true
    },
    {
      "id": "prod_d4e5f6a2b3c4",
      "name": "JBL Tune 215TWS True Wireless Earbuds",
      "category": "Electronics",
      "effective_price": 2499.0,
      "in_stock": true
    }
  ],
  "parsed_filters": {
    "keywords": "wireless earbuds running",
    "category": "Electronics",
    "subcategory": "Earbuds",
    "max_price": 3000,
    "features": ["wireless", "sweat resistant", "secure fit"]
  }
}
```

#### 3b. Follow-up question in the same session

Pass the `session_id` from the previous response to continue the conversation:

```bash
curl -s -X POST http://localhost:8012/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess_9a8b7c6d5e4f3a2b",
    "message": "What is the battery life difference between the first two options?"
  }' | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "session_id": "sess_9a8b7c6d5e4f3a2b",
  "reply": "Comparing the battery life:\n\n- **boAt Airdopes 141**: 6 hours per charge from the earbuds, plus 36 hours from the charging case = **42 hours total**.\n- **Boult Audio Z40**: 8 hours per charge from the earbuds, plus 32 hours from the case = **40 hours total**.\n\nThe Airdopes 141 has a slight edge on total playtime (42h vs 40h), though the Z40 lasts longer per individual charge session (8h vs 6h). If you do runs longer than 6 hours without access to the case, the Z40 is the better pick.",
  "sources": [
    {
      "id": "prod_a1b2c3d4e5f6",
      "name": "boAt Airdopes 141 TWS Earbuds",
      "category": "Electronics",
      "effective_price": 1104.15,
      "in_stock": true
    }
  ],
  "parsed_filters": {
    "keywords": "wireless earbuds battery",
    "category": "Electronics",
    "subcategory": null,
    "max_price": null,
    "features": []
  }
}
```

The assistant remembered the context from the first message — it knew which two products were "the first two options" without the user restating them.

#### 3c. Retrieve conversation history

```bash
curl -s http://localhost:8012/chat/sess_9a8b7c6d5e4f3a2b/history \
  | python3 -m json.tool
```

**Response** (`200 OK`):

```json
{
  "session_id": "sess_9a8b7c6d5e4f3a2b",
  "messages": [
    {
      "role": "user",
      "content": "I need wireless earbuds for running, budget under ₹3000",
      "created_at": "2026-06-23T10:30:00"
    },
    {
      "role": "assistant",
      "content": "Great choice for a running companion! ...",
      "created_at": "2026-06-23T10:30:02"
    },
    {
      "role": "user",
      "content": "What is the battery life difference between the first two options?",
      "created_at": "2026-06-23T10:31:00"
    },
    {
      "role": "assistant",
      "content": "Comparing the battery life: ...",
      "created_at": "2026-06-23T10:31:01"
    }
  ]
}
```

---

### Example 4 — Checkout with idempotency

**Service**: `checkout_service` at `http://localhost:8003`
**Dependencies**: PostgreSQL

This example demonstrates the idempotency guarantee: sending the same `Idempotency-Key` twice never creates two orders.

#### 4a. Place an order

```bash
IDEM_KEY=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Idempotency key: $IDEM_KEY"

curl -s -X POST http://localhost:8003/checkout \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEM_KEY" \
  -d '{
    "cart_id": "cart_1a2b3c4d5e6f",
    "customer_id": "usr_3f8a2b1c4d5e6f7a",
    "coupon_code": null,
    "shipping": {
      "name": "Priya Sharma",
      "phone": "9876543210",
      "address_line": "42, MG Road",
      "city": "Bengaluru",
      "state": "Karnataka",
      "pincode": "560001"
    }
  }' | python3 -m json.tool
```

**Response** (`201 Created`):

```json
{
  "order_id": "ord_5e6f7a8b9c0d1e2f",
  "status": "pending",
  "subtotal": 24990.0,
  "discount": 0.0,
  "coupon_code": null,
  "tax": 4498.2,
  "shipping_charge": 0.0,
  "total": 29488.2,
  "items": [
    {
      "product_id": "prod_f6a1b2c3d4e5",
      "product_name": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
      "quantity": 1,
      "unit_price": 24990.0,
      "subtotal": 24990.0
    }
  ],
  "created_at": "2026-06-23T10:45:00"
}
```

#### 4b. Retry with the same key — no duplicate order

```bash
# Same Idempotency-Key, same request body
curl -s -X POST http://localhost:8003/checkout \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEM_KEY" \
  -d '{
    "cart_id": "cart_1a2b3c4d5e6f",
    "customer_id": "usr_3f8a2b1c4d5e6f7a",
    "coupon_code": null,
    "shipping": {
      "name": "Priya Sharma",
      "phone": "9876543210",
      "address_line": "42, MG Road",
      "city": "Bengaluru",
      "state": "Karnataka",
      "pincode": "560001"
    }
  }' | python3 -m json.tool
```

**Response** (`200 OK` — identical `order_id`, no new order created):

```json
{
  "order_id": "ord_5e6f7a8b9c0d1e2f",
  "status": "pending",
  "subtotal": 24990.0,
  "total": 29488.2,
  ...
}
```

The `order_id` is the same as in 4a. The service returned the cached response without creating a second order. This is verified by the `checkout_idempotency_keys` table:

```bash
# Confirm only one record exists for this key
psql -U postgres -d ecommerce -c \
  "SELECT key, endpoint, order_id, created_at FROM checkout_idempotency_keys ORDER BY created_at DESC LIMIT 5;"
```

---

## Running Tests

### API tests (pytest)

```bash
# Start the services first, then:
cd tests/api
pip install pytest httpx

# Run all API tests
pytest -v

# Run tests for a specific service
pytest test_user_management.py -v
pytest test_product_catalogue.py -v
pytest test_checkout.py -v
```

### Load / performance tests (Locust)

```bash
cd tests/performance
pip install locust

# Interactive mode (opens browser at http://localhost:8089)
locust -f load_test.py --host http://localhost:8002

# Headless (CI mode): 50 users, 60s run
locust -f load_test.py --host http://localhost:8002 \
  --users 50 --spawn-rate 5 --run-time 60s --headless
```

After a 60s run you will see:

```
Name                     # Reqs   Avg     Min    P95    P99   Failures
-------------------------------------------------------------------
GET /products (list)      2841    43ms    12ms   110ms  198ms  0 (0%)
POST /search/semantic      342  1241ms   890ms  2180ms 2890ms  0 (0%)
GET /health               410    4ms     2ms     8ms   12ms   0 (0%)
```

---

## Project Structure

```
ecommerce_pt/
├── .env.example              ← copy to .env and fill in credentials
├── README.md
├── scripts/
│   ├── setup_db.sh           ← create PostgreSQL DB + pgvector extension
│   ├── seed_products.sh      ← load 5K products + generate embeddings
│   └── start_all.sh          ← start / stop all 13 services
├── src/
│   ├── nfr/                  ← shared: circuit_breaker, structured_logging, metrics
│   ├── user_management/      ← port 8001: JWT auth, GDPR
│   ├── product_catalogue/    ← port 8002: products, pgvector search
│   ├── checkout_service/     ← port 8003: cart, idempotent checkout
│   ├── recommendation_engine/← port 8004: hybrid recommender
│   ├── inventory_service/    ← port 8005: stock management
│   ├── order_management/     ← port 8006: order lifecycle, refunds
│   ├── session_service/      ← port 8007: browsing events
│   ├── payment_shipping_service/ ← port 8008: Razorpay + Shiprocket
│   ├── guardrails_service/   ← port 8009: AI safety
│   ├── multi_agent_system/   ← port 8010: orchestrator + 4 agents
│   ├── seller_portal/        ← port 8011: B2B KYC + product approval
│   ├── shopping_assistant/   ← port 8012: RAG pipeline
│   ├── tool_calling_agent/   ← port 8013: function-calling agent
│   └── frontend/             ← port 5173: React 18 + Vite
├── docs/
│   ├── architecture/
│   ├── data-flow/
│   └── design_decisions_and_tradeoffs.md
├── requirements/
│   ├── functional_requirements.md
│   └── non_functional_requirements.md
└── tests/
    ├── api/                  ← pytest integration tests
    └── performance/          ← Locust load tests
```

---

## Troubleshooting

**`psycopg2.OperationalError: could not connect to server`**
- PostgreSQL is not running. Start it: `sudo service postgresql start` (Linux) or via the app (Mac).
- Check `DATABASE_URL` in your `.env` matches your PostgreSQL host, port, user, and password.

**`pgvector extension not found`**
- Run `bash scripts/setup_db.sh` again, or manually: `psql -U postgres -d ecommerce -c "CREATE EXTENSION vector;"`
- If pgvector is not installed: `sudo apt install postgresql-15-pgvector` (Ubuntu) or `brew install pgvector` (Mac).

**`openai.AuthenticationError`**
- Check `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` in `.env`.
- Verify the deployment names (`gpt-5.4-mini`, `text-embedding-3-small`) match what you created in Azure OpenAI Studio.

**`ModuleNotFoundError: No module named 'nfr'`**
- Start services with `PYTHONPATH=<repo_root>/src` set, or use `scripts/start_all.sh` which sets this automatically.

**`429 Too Many Requests` on login/register**
- This is the rate limiting working correctly (5/min on login, 3/min on register).
- Wait 60 seconds or restart the service to reset in-process counters.

**Service starts but `/health` returns 500**
- The service could not connect to its database. Check the service log: `tail -50 logs/<service>.log`
- For AI services, also check that Azure OpenAI credentials are set correctly.
