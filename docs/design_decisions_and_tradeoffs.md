# System Design Decisions and Trade-offs

## Overview

This document articulates every significant design decision made during the build of the AI-powered e-commerce platform, along with the alternatives that were considered and the trade-offs that drove each choice.

---

## 1. Vector Store — pgvector (PostgreSQL) vs Dedicated Vector Database

### Decision
We embedded product vectors directly into the PostgreSQL `products` table using the `pgvector` extension (`Vector(1536)` column). There is no separate vector database.

### Alternatives Considered
| Option | Pros | Cons |
|--------|------|------|
| **pgvector** ✓ | One DB for everything; transactional consistency; SQL filters compose naturally with ANN search | Not optimised for >10M vectors; fewer index types than dedicated DBs |
| Pinecone | Fully managed; excellent at scale; rich metadata filtering | External paid service; data leaves PostgreSQL; adds network hop |
| Weaviate | Open-source; multi-modal; GraphQL | Separate infrastructure; more ops overhead |
| Qdrant | Fast, Rust-based; good local-dev story | Another process to run; no SQL composability |

### Why pgvector Won
The killer advantage is **query composability**. Our semantic search applies hard SQL filters (price cap, category, in-stock flag) _in the same query_ as the vector ranking:

```sql
SELECT id, name, price,
       1 - (embedding <=> $1) AS score
FROM products
WHERE price * (1 - discount_pct / 100) <= 5000   -- hard filter
  AND is_active = true
ORDER BY embedding <=> $1                          -- ANN ranking
LIMIT 5;
```

With a dedicated vector DB, this requires a two-phase approach: pre-filter in PostgreSQL → pass IDs to vector DB → re-rank. That's two network hops, two transactions, and no guarantee of consistency.

### Trade-off Accepted
At 5,000 products and capstone scale, pgvector is fine. A production system with 500K+ products and multi-region deployment would likely migrate to a managed vector service. The migration path is well-defined — the embedding generation code doesn't change, only the storage backend.

---

## 2. AI Model Selection

### 2a. Chat / Reasoning Model — GPT-5.4-mini

#### Decision
All LLM tasks (RAG generation, query parsing, multi-agent reasoning, guardrail judging) use `gpt-5.4-mini` deployed on Azure OpenAI.

#### Alternatives Considered
| Option | Latency | Cost | Quality | Notes |
|--------|---------|------|---------|-------|
| **GPT-5.4-mini** ✓ | ~800ms | Low | High | Best cost/quality; 128K context |
| GPT-4o | ~1.5s | 5× higher | Marginal gain for this task | Overkill for structured extraction and short-form generation |
| GPT-3.5-turbo | ~400ms | Lowest | Noticeably weaker on structured JSON | Would need more prompt engineering to match output quality |
| Self-hosted (Ollama / Llama 3) | ~2–4s on CPU | Free (infra cost) | Lower quality | No GPU in capstone; cold start latency unacceptable |

#### Why GPT-5.4-mini Won
- P95 RAG response < 2.3s with GPT-5.4-mini, meeting the NFR target of < 3s
- Structured JSON extraction (query parsing) is reliable without brittle post-processing
- Azure deployment provides enterprise SLA and keeps data in-region (no data residency issue)

#### Trade-off Accepted
Vendor lock-in. Every AI call depends on Azure OpenAI availability. Mitigated by the circuit breaker — if Azure is unavailable, the shopping assistant returns the raw vector-search results without GPT augmentation.

### 2b. Embedding Model — text-embedding-3-small (1536-dim)

#### Decision
All product embeddings use `text-embedding-3-small` at 1536 dimensions.

#### Alternatives Considered
| Model | Dimensions | Cost per 1M tokens | Quality (MTEB) |
|-------|-----------|-------------------|----------------|
| **text-embedding-3-small** ✓ | 1536 | $0.02 | 62.3% |
| text-embedding-3-large | 3072 | $0.13 | 64.6% |
| text-embedding-ada-002 | 1536 | $0.10 | 61.0% |

#### Why text-embedding-3-small Won
6.5× cheaper than `ada-002` for slightly better quality. The 2.3% quality gap between small and large (on MTEB) does not justify a 6.5× cost increase for product search — retrieval quality in user testing was indistinguishable. Generating embeddings for 5,000 products cost ~$0.01.

---

## 3. Synchronous vs Asynchronous Inter-Service Communication

### Decision
All inter-service calls are **synchronous HTTP** (`httpx`). There is no message broker.

### Alternatives Considered
| Pattern | Latency | Complexity | Failure handling |
|---------|---------|------------|-----------------|
| **Sync HTTP (httpx)** ✓ | Lowest for request-response | Simple | Caller gets immediate error; circuit breaker applies |
| Kafka / RabbitMQ | Higher (async delivery) | High (broker to operate) | At-least-once delivery; consumer lag monitoring needed |
| Celery + Redis | Medium | Medium | Task queue with retries; visibility via Flower |
| gRPC | Lowest | Medium | Protobuf typing; streaming support |

### Why Synchronous HTTP Won
The primary user journeys (checkout, product search, recommendation) are **inherently request-response** — the UI is waiting for a result. Async messaging adds latency and complexity without reducing it for these flows.

The one place async _would_ add value is the **payment confirmation flow**: Razorpay calls our webhook, which then triggers order state transitions and Shiprocket booking. This flow is already naturally async (webhook push model), so it does not need a message broker.

### Trade-off Accepted
Tight coupling. If `inventory_service` is slow, the checkout endpoint is slow. This is mitigated by:
- Circuit breaker fast-fails after 5 consecutive timeouts (prevents cascade)
- `httpx` timeout of 2s per call

In production, the order-payment-fulfilment flow would be refactored onto a message queue (Kafka topic per event type: `order.created`, `payment.confirmed`, `order.shipped`) to decouple services and guarantee delivery.

---

## 4. Caching Strategy

### Decision
**No distributed cache (Redis) was introduced.** Three targeted caching patterns are used instead:

| Cache Type | Implementation | What It Caches |
|------------|---------------|----------------|
| Idempotency cache | `checkout_idempotency_keys` table (PostgreSQL) | Completed checkout responses |
| Circuit breaker state | In-process `threading.Lock` (memory) | Downstream service health |
| Product embeddings | `products.embedding` column (PostgreSQL) | Computed vectors (reused at query time) |

### Why No Redis
Adding Redis would require a fifth infrastructure component (PostgreSQL, SQLite × 2, Azure OpenAI, Razorpay/Shiprocket are already four). For capstone scale and a local-run demo, the complexity cost outweighed the benefit.

Specifically:
- **Session caching**: Sessions are stored in PostgreSQL (`session_service`). At 10K users, PostgreSQL handles session reads comfortably.
- **Response caching**: Product lists change infrequently, but without Redis there is no L2 cache in front of PostgreSQL. Under load testing (100 users), PostgreSQL query times stayed under 50ms P95 — within NFR targets without caching.
- **Rate limit counters**: `slowapi` uses in-process memory. This means limits don't aggregate across replicas in a multi-instance deployment.

### Trade-off Accepted
In a scaled deployment (50K concurrent users), Redis would be mandatory for:
1. Distributed rate limit counters (current in-process counters don't aggregate)
2. Circuit breaker state shared across replicas
3. L2 query cache for hot catalogue pages
4. Session token storage for stateful flows

The code is structured so Redis can be dropped in as a backend for `slowapi` (`storage_uri=redis://...`) and for the circuit breaker state (replace `threading.Lock` with Redis `SETNX`).

### Idempotency Cache Specifically — DB vs Redis
We deliberately chose **PostgreSQL for idempotency keys**, not Redis.

The reason: if the service crashes between creating the order and persisting the idempotency record, a Redis-backed approach could lose the record on restart (if not using AOF persistence). A PostgreSQL row in the same DB transaction as the `Order` row means both are committed atomically or neither is. This is the correct guarantee for financial operations.

---

## 5. Message Broker Decision

### Decision
**No message broker deployed.** The checkout → payment → logistics flow uses Razorpay and Shiprocket webhooks as the async delivery mechanism (they push HTTP POST to our endpoints on state change).

### Alternatives Considered
| Option | Use Case | Why Not Chosen |
|--------|---------|----------------|
| Kafka | High-throughput event streaming; durable replay | Zookeeper/KRaft overhead; overkill for 50K order/day throughput |
| RabbitMQ | Task queues; routing; fan-out | Another service to operate; AMQP complexity |
| Celery + Redis | Async task execution (email, logistics booking) | Reasonable choice but adds Redis dependency |
| AWS SQS / Azure Service Bus | Managed, no ops | Cloud lock-in; not accessible in local demo |

### Trade-off Accepted
Synchronous logistics booking means the `POST /webhook/payment-confirmed` handler makes a blocking call to Shiprocket. If Shiprocket is slow, the webhook response is slow, which could cause Razorpay to retry. The `payment_id` acts as a natural idempotency key on the webhook endpoint, so retries are safe.

In a production system, the webhook handler would publish an `order.paid` event to Kafka and return 200 immediately; a separate consumer would handle Shiprocket booking with retries.

---

## 6. Database Architecture — Shared PostgreSQL vs Isolated Stores

### Decision
Services use **two database tiers**:

| Tier | Services | Rationale |
|------|---------|-----------|
| Shared PostgreSQL (`ecommerce`) | product_catalogue, checkout, inventory, orders, recommendations, session, payment | Need cross-service joins for analytics; pgvector only works on PostgreSQL |
| Isolated SQLite | user_management, seller_portal | Auth data isolated from business data; simpler local-dev story; no multi-writer contention |

### Why Not One DB for Everything
Combining all 13 services on one PostgreSQL schema would create a distributed monolith — shared schema changes would require coordinating all services. The SQLite isolation for auth services means credential data never mixes with product/order tables.

### Why Not Each Service Its Own PostgreSQL
At capstone scale, operating 13 separate PostgreSQL instances is unnecessary overhead. In production, each service would have its own schema within a shared PostgreSQL cluster, or its own RDS instance.

### Trade-off Accepted
SQLite does not support multiple concurrent writers well. For `user_management`, the registration/login pattern (many concurrent short writes) would hit SQLite's write lock under high load. Production fix: migrate auth stores to PostgreSQL with connection pooling (PgBouncer).

---

## 7. Microservices Granularity — 13 Services vs Monolith vs Fewer Services

### Decision
13 independent FastAPI services, one per domain, each with its own port and `requirements.txt`.

### Alternatives Considered
| Option | Deployment Simplicity | Independent Scaling | Development Speed |
|--------|-----------------------|--------------------|--------------------|
| Monolith | Highest | Impossible | Fastest initially |
| **13 microservices** ✓ | Low | Per-service | Moderate |
| 4–5 coarse services (auth, catalogue+AI, orders+inventory, frontend) | Medium | Coarse | Good |

### Why 13 Services
Each service maps to a distinct business capability with its own data store ownership and scaling profile. This lets the AI services (`shopping_assistant`, `multi_agent_system`) be scaled independently from the transactional services (`checkout_service`, `inventory_service`) — important because AI inference is CPU/memory heavy while checkout is IO-bound.

### Trade-off Accepted
Operational complexity. Running 13 `uvicorn` processes locally is awkward. In a demo, this is managed via a `start_all.sh` script. The lack of an API gateway means there is no single entry point for auth enforcement, rate limiting, or TLS termination — each service reimplements these via the shared `nfr/` module.

---

## 8. Circuit Breaker — In-Process vs Redis-Backed State

### Decision
Circuit breaker state is maintained **in-process** using `threading.Lock` and module-level singletons.

```python
# nfr/circuit_breaker.py
class CircuitBreaker:
    def __init__(self, ...):
        self._state         = CircuitState.CLOSED
        self._failure_count = 0
        self._lock          = threading.Lock()   # in-process only
```

### Trade-off
This design is correct for a **single-instance deployment** (which the capstone runs as). Each uvicorn worker process has its own breaker state — if two replicas of `checkout_service` were running, one could be OPEN while the other is CLOSED.

In production with Kubernetes HPA auto-scaling, circuit breaker state must be externalised to Redis (`pybreaker` with a Redis backend, or `resilience4j` for JVM). We accepted this limitation for the capstone since we run one process per service.

---

## 9. Authentication — Stateless JWT vs Session-Based

### Decision
**Stateless JWT** with short-lived access tokens (15 min) and long-lived refresh tokens (7 days). No server-side session store.

### Why Stateless
- No Redis/DB lookup on every authenticated request — token is verified locally using the secret key
- Horizontally scalable by default — any replica can verify any token
- Works naturally with the microservices model (each service independently validates the token without calling `user_management`)

### Trade-off Accepted
**Token revocation is hard.** If a user's token is stolen, it remains valid until expiry (15 min). True immediate revocation requires a token denylist (Redis `SET`) — which reintroduces state. The 15-minute TTL is a deliberate risk tradeoff: short enough to limit exposure, long enough to avoid excessive refresh calls.

Separate JWT namespaces for B2C users and B2B sellers (different `iss` claims, different secrets) ensure a seller token cannot be used to access consumer APIs and vice versa.

---

## 10. Recommendation Engine — Hybrid Adaptive Weights vs Fixed Weights

### Decision
The hybrid recommender uses **adaptive weights** that shift based on user history maturity:

| User State | CF Weight | Content Weight | Trending Weight |
|------------|-----------|----------------|-----------------|
| Cold (0–2 purchases) | 0.0 | 0.4 | 0.6 |
| Warm (browsing only) | 0.3 | 0.4 | 0.3 |
| Active (5+ purchases) | 0.5 | 0.3 | 0.2 |

### Why Adaptive
Pure collaborative filtering produces an empty result set for cold-start users (no purchase history → no similar users). Fixed-weight blending would produce low-quality recommendations because CF produces no signal to blend. Adaptive weights switch to trending and content-based signals exactly when CF has nothing to offer, and shift toward CF as user history accumulates.

Evaluation on leave-one-out cross-validation confirmed this: adaptive hybrid Hit Rate@10 = **0.78** vs fixed-weight = **0.74** vs CF-only = **0.67**.

### Trade-off Accepted
Weight thresholds (5+ purchases = "active") were set heuristically. A production system would learn optimal thresholds via A/B testing or bandit algorithms. The batch pre-computation of item-similarity matrices runs manually (no scheduler), so recommendation quality degrades as the purchase graph grows stale between runs.

---

## 11. Rate Limiting — In-Process (slowapi) vs API Gateway

### Decision
**Per-service in-process rate limiting** using `slowapi` (a Starlette/FastAPI wrapper over `limits`).

```python
# Limits keyed per client IP
limiter.limit("5/minute")(login_endpoint)
limiter.limit("3/minute")(register_endpoint)
```

### Why Not API Gateway
An API gateway (Kong, AWS API Gateway, nginx-lua) would be the production-correct approach — centralised policy, distributed counters, JWT validation at the edge. For a local capstone demo with no cloud deployment, operating a gateway adds a service with no practical benefit.

### Trade-off Accepted
In-process counters do not aggregate across service replicas (same problem as the circuit breaker). Two replicas of `user_management` each allow 5 login attempts per minute from the same IP, effectively doubling the limit. Production fix: configure `slowapi` with `storage_uri="redis://..."` to use a shared Redis counter store.

---

## 12. Guardrails Design — Separate Service vs Inline Middleware

### Decision
Content safety and output validation run in a **dedicated `guardrails_service`** (port 8009), called by `shopping_assistant` and `tool_calling_agent` before and after LLM calls.

### Why a Separate Service
- Reusable across all AI-facing services without code duplication
- Independently deployable and tunable (change rules without deploying the shopping assistant)
- Clear audit boundary — all AI I/O passes through one choke point

### Trade-off Accepted
Two extra HTTP round-trips per RAG request (input validation + output validation). At ~5–10ms per guardrail call, this adds ~20ms to a 2.3s request — acceptable. However, if Azure OpenAI latency is already at the NFR limit, guardrail calls could push P95 over budget. In production, the input guardrail could be inlined as a synchronous middleware step to eliminate the network hop.

---

## 13. Summary: Decision Matrix

| Decision | Chosen Approach | Production Alternative | Key Reason for Capstone Choice |
|----------|----------------|----------------------|-------------------------------|
| Vector store | pgvector | Pinecone / Qdrant | SQL composability; one less infrastructure component |
| LLM model | GPT-5.4-mini | Fine-tuned smaller model | Best quality/cost; meets P95 latency target |
| Embedding model | text-embedding-3-small | text-embedding-3-large | 6.5× cheaper; <3% quality difference |
| Inter-service comms | Sync HTTP | Kafka event bus | Request-response UX; simpler failure model |
| Cache | None (DB-backed only) | Redis | Fewer moving parts; DB P95 within targets |
| Message broker | None (webhook push) | Kafka / RabbitMQ | Razorpay/Shiprocket webhooks handle async naturally |
| Database | Shared PostgreSQL + SQLite | Per-service PostgreSQL | pgvector requirement; auth isolation |
| Circuit breaker state | In-process threading | Redis-backed | Single instance per service in capstone |
| Auth | Stateless JWT | JWT + Redis denylist | Horizontally scalable; no session store |
| Rate limiting | slowapi (in-process) | API gateway | No cloud deployment; no Redis dependency |
| Recommendation | Hybrid adaptive | ML-trained meta-learner weights | Interpretable; no training pipeline required |
| Guardrails | Separate service | Inline middleware | Reusability across AI services |
| Service count | 13 microservices | 4–5 coarse services | Domain alignment; independent AI scaling |
