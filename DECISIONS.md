# Architecture Decision Records (ADRs)

This file documents every significant architectural decision made in this project, the alternatives considered, and the trade-offs accepted. For the full narrative with detailed analysis see [docs/design_decisions_and_tradeoffs.md](docs/design_decisions_and_tradeoffs.md).

---

## ADR-001 — Vector Store: pgvector (PostgreSQL) vs Dedicated Vector DB

**Status**: Accepted  
**Date**: 2026-06-01

### Context
Product semantic search requires a vector store to run cosine similarity queries against 1536-dimensional embeddings for 5,000+ products.

### Decision
Embed vectors directly into PostgreSQL using the `pgvector` extension (`Vector(1536)` column). No separate vector database service.

### Alternatives Considered
| Option | Reason Rejected |
|--------|----------------|
| Pinecone | External paid service; data leaves PostgreSQL; two-phase query required |
| Weaviate | Separate infra to operate; no SQL composability |
| Qdrant | Another process; cannot co-filter with SQL in one query |

### Rationale
SQL filter + ANN ranking in a single query:
```sql
SELECT id, 1 - (embedding <=> $1) AS score
FROM products
WHERE price <= 5000 AND is_active = true
ORDER BY embedding <=> $1 LIMIT 5;
```
Dedicated vector DBs require two network hops (PostgreSQL → vector DB → re-rank), losing transactional consistency.

### Trade-off
At 500K+ products a managed vector service (Pinecone, Qdrant) would outperform pgvector. Migration path is defined: embedding generation code is unchanged; only the storage backend swaps. See ADR-002 for the abstraction layer.

### Decoupling Guarantee
The `vector_store.py` module exposes a `semantic_search()` interface. Swapping pgvector for Milvus/Qdrant requires changes only in `vector_store.py`; the RAG pipeline and API layer are unaffected.

---

## ADR-002 — Vector DB Abstraction Layer

**Status**: Accepted  
**Date**: 2026-06-01

### Context
Future migration from pgvector to a dedicated vector DB should not require rewriting the RAG pipeline or the shopping assistant API.

### Decision
Isolate all vector DB interactions behind `src/shopping_assistant/vector_store.py` (and `src/product_catalogue/vector_store.py`). No other module calls pgvector directly.

### Interface
```python
def semantic_search(db, query_embedding, n_results, category=None, brand=None,
                    max_price=None, min_price=None) -> list[tuple[Product, float]]:
    ...
```

### Trade-off
Slight abstraction overhead. Benefit: swapping to Milvus/Qdrant requires editing only `vector_store.py`.

---

## ADR-003 — Chat/Reasoning Model: GPT-5.4-mini via Azure OpenAI

**Status**: Accepted  
**Date**: 2026-06-01

### Context
RAG generation, query parsing, multi-agent reasoning, and guardrail judging all need an LLM.

### Decision
Use `gpt-5.4-mini` deployed on Azure OpenAI.

### Alternatives Considered
| Option | Latency | Cost | Reason Rejected |
|--------|---------|------|----------------|
| GPT-4o | ~1.5s | 5× higher | Marginal quality gain; overkill for structured extraction |
| GPT-3.5-turbo | ~400ms | Lowest | Weaker structured JSON; more brittle prompt engineering |
| Self-hosted Llama 3 (CPU) | 2–4s | Free (infra) | No GPU; cold start latency violates NFR < 3s P95 |

### Rationale
P95 RAG response < 2.3s. Structured JSON extraction is reliable without post-processing. Azure deployment provides enterprise SLA and data residency.

### Trade-off
Vendor lock-in on Azure OpenAI. Mitigated by:
1. Circuit breaker in `src/nfr/circuit_breaker.py` — trips if Azure is unavailable.
2. Local Flan-T5 fallback in `src/shopping_assistant/local_fallback.py` — activates on timeout/circuit open.
3. Keyword-only search fallback — returns un-augmented vector results if GPT generation fails.

---

## ADR-004 — Embedding Model: text-embedding-3-small (1536-dim)

**Status**: Accepted  
**Date**: 2026-06-01

### Context
Product descriptions must be encoded into a fixed-dimension vector space for cosine similarity search.

### Decision
Use Azure OpenAI `text-embedding-3-small` at 1536 dimensions.

### Alternatives Considered
| Model | Dims | Cost/1M tokens | MTEB |
|-------|------|---------------|------|
| text-embedding-3-small ✓ | 1536 | $0.02 | 62.3% |
| text-embedding-3-large | 3072 | $0.13 | 64.6% |
| text-embedding-ada-002 | 1536 | $0.10 | 61.0% |

### Rationale
6.5× cheaper than ada-002 for better quality. The 2.3% MTEB gap between small and large does not justify 6.5× cost for product search. Generating 5,000 product embeddings cost ~$0.01.

### Trade-off
Not the highest-quality embedding model. Acceptable for capstone scope; upgrade to `text-embedding-3-large` for production with >100K products.

---

## ADR-005 — Inter-Service Communication: Synchronous HTTP (httpx)

**Status**: Accepted  
**Date**: 2026-06-01

### Context
13 microservices need to communicate. Options: sync HTTP, async message broker (Kafka/RabbitMQ), gRPC, or Celery.

### Decision
All inter-service calls use synchronous HTTP via `httpx`.

### Rationale
Primary user journeys (search, checkout, recommendations) are inherently request-response. The UI blocks waiting for a result. Async messaging adds latency without reducing it for these flows.

### Trade-off
No at-least-once delivery guarantee. In production, the payment confirmation flow (Razorpay webhook → order confirmed → Shiprocket) would move to Kafka for decoupling and guaranteed delivery.

---

## ADR-006 — Database Strategy: Shared PostgreSQL + Two SQLite

**Status**: Accepted  
**Date**: 2026-06-01

### Context
13 services need persistent storage. Options: one DB per service (microservice orthodoxy) or shared DB.

### Decision
One shared PostgreSQL instance for 11 services. SQLite for `user_management` and `seller_portal` (no PostgreSQL dependency for auth-only services).

### Rationale
Operating 13 separate PostgreSQL instances at capstone scale is unnecessary overhead. Schema-per-service within one PostgreSQL instance gives logical isolation.

### Trade-off
Schema coupling risk. Mitigated by ensuring each service's tables are owned exclusively by that service (documented in `docs/architecture/service_map.md`).

### Production Path
Each service gets its own RDS instance or PostgreSQL schema in a shared cluster. `user_management` migrates to PostgreSQL with PgBouncer for concurrent writes.

---

## ADR-007 — Recommendation Strategy: Hybrid CF + Content + Trending

**Status**: Accepted  
**Date**: 2026-06-01

### Context
Pure collaborative filtering (CF) fails for cold-start users and new products.

### Decision
Hybrid recommender combining:
1. **Collaborative Filtering** — item-item cosine similarity on purchase history
2. **Content-based** — product embedding similarity to browsed items
3. **Trending** — recent purchase velocity for zero-history users

Weights adapt dynamically: cold-start users get content + trending; active users get CF-dominant.

### Trade-off
Weight thresholds (≥5 purchases = "active") are heuristic. Production system would A/B test or use bandit algorithms to optimise weights.

---

## ADR-008 — Caching: In-Process TTLCache (capstone) → Redis (production)

**Status**: Implemented  
**Date**: 2026-06-24

### Context
Semantic search for popular queries is expensive (~120ms embedding + vector search). Discovery endpoints (trending, categories) are expensive DB aggregations. Personalised recommendations must not be cached across users.

### Decision
In-process `cachetools.TTLCache` with `threading.Lock` per cache instance. Deployed across 3 services:

| Service · Cache | TTL | maxsize |
|---|---|---|
| shopping_assistant · `embed_text` | 5 min | 512 |
| shopping_assistant · `parse_nl_query` | 5 min | 512 |
| product_catalogue · categories | 1 hour | 4 |
| product_catalogue · brands | 1 hour | 16 |
| recommendation_engine · trending / deals | 30 min | 32 / 16 |
| recommendation_engine · top-viewed / new-arrivals | 15 min | 16 |
| recommendation_engine · homepage (per customer) | 5 min | 500 |
| recommendation_engine · categories | 1 hour | 4 |

Cache hit stats are exposed on each service's `/health` endpoint (`embedding_cache` key).  
Personalised recommendations (`/recommendations/for/{id}`) are intentionally excluded — always computed fresh.

### Trade-off
In-process counters do not aggregate across service replicas. Production fix: swap `storage_uri` to `redis://...` — one-line change per service. Redis Cluster on ElastiCache for cross-replica shared cache in K8s.

### Implementation files
- `src/shopping_assistant/embeddings.py` — `_embed_cache`, `_parse_cache`
- `src/product_catalogue/routes/category_routes.py` — `_cat_cache`, `_brand_cache`
- `src/recommendation_engine/routes/recommendation_routes.py` — 6 cache instances

---

## ADR-009 — Rate Limiting: In-Process (slowapi) vs API Gateway

**Status**: Accepted  
**Date**: 2026-06-01

### Context
Auth endpoints need rate limiting to prevent brute-force attacks.

### Decision
In-process rate limiting with `slowapi` (5/min on login, 3/min on register).

### Trade-off
In-process counters do not aggregate across service replicas. Production fix: configure `slowapi` with `storage_uri="redis://..."`. In production K8s, an API Gateway (Kong/AWS API Gateway) centralises rate limiting at the edge.

---

## ADR-010 — Accuracy vs Performance Trade-off in RAG Pipeline

**Status**: Accepted  
**Date**: 2026-06-01

### Context
RAG pipeline has two levers: retrieval depth (top-k) and generation model size.

### Decision
- Retrieve top-8 products from pgvector (top-5 shown to user)
- Use GPT-5.4-mini (not GPT-4o)
- Apply SQL pre-filters before vector ranking

### Trade-off
| Setting | Accuracy | Latency |
|---------|---------|---------|
| top-3, GPT-3.5 | Lower recall | ~600ms |
| **top-8, GPT-5.4-mini** ✓ | 91.3% MRR@5 | ~1.8s |
| top-20, GPT-4o | Highest | ~3.5s (violates NFR) |

Evaluation results in `docs/evaluation/metrics_summary.md`.

---

## ADR-011 — Guardrails: LLM-as-Judge vs Rule-Based Filter

**Status**: Accepted  
**Date**: 2026-06-01

### Context
Shopping assistant inputs and outputs must be filtered for harmful/off-topic content.

### Decision
LLM-as-Judge via `guardrails_service` using GPT-5.4-mini with a structured JSON rubric.

### Alternatives Considered
| Option | Pros | Cons |
|--------|------|------|
| Rule-based (regex/wordlist) | Fast, deterministic | High false-positive rate; misses rephrasing |
| **LLM Judge** ✓ | Nuanced; handles rephrasing | +20ms latency; depends on Azure availability |
| Separate safety model | Potentially fastest | Extra model to serve; no GPU |

### Trade-off
~20ms per guardrail call (input + output) adds ~40ms to a RAG request. Acceptable given 3s P95 NFR target.

---

## ADR-012 — ML Resiliency: Graceful Degradation across All Azure-Dependent Services

**Status**: Implemented  
**Date**: 2026-06-24

### Context
If Azure OpenAI is unavailable or slow, every service that calls it must degrade gracefully rather than returning a 503 or hanging. Five services make direct Azure calls.

### Decision
Each Azure-dependent service has its own fallback chain triggered by `APITimeoutError`, `APIConnectionError`, or `RateLimitError`. All Azure calls are wrapped with a configurable timeout via `AZURE_TIMEOUT_SECS` env var.

| Service | Fallback chain | API signal |
|---|---|---|
| `shopping_assistant` | Azure → Flan-T5-base (CPU) → keyword ILIKE | `fallback_mode: true` |
| `product_catalogue` | Azure timeout → keyword-only NL parse; batch embed → per-item retry | graceful 200 |
| `multi_agent_system` router | Azure timeout → `_FALLBACK` RoutingDecision (customer_support) | graceful 200 |
| `multi_agent_system` tools | Azure timeout → keyword ILIKE product search | graceful 200 |
| `tool_calling_agent` | Azure timeout/error → `_UNAVAILABLE_MSG` saved to DB | graceful 200 |
| `checkout_service` | DB flush/commit failure → `db.rollback()` + HTTP 500 + detail | HTTP 500 |

### Implementation files
- `src/shopping_assistant/local_fallback.py` — Flan-T5 + keyword fallback
- `src/shopping_assistant/rag.py` — timeout + fallback routing
- `src/product_catalogue/embeddings.py` — timeout + per-item fallback
- `src/multi_agent_system/orchestrator/router.py` — timeout + `_FALLBACK`
- `src/multi_agent_system/tools/product_tools.py` — timeout + keyword search
- `src/tool_calling_agent/agent/loop.py` — timeout + graceful message
- `src/checkout_service/routes/checkout_routes.py` — rollback on DB failure

### Trade-off
Flan-T5-base quality is 3.2/5.0 vs GPT's 4.34/5.0. Cold load (~3s on CPU). Models loaded at startup to eliminate per-request cold start. The fallback is clearly labelled in API responses (`"fallback_mode": true`). All timeouts are environment-configurable — no code change required to tune per deployment.
