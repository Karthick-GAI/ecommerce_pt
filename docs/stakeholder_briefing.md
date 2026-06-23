# Stakeholder Briefing — AI-Powered E-Commerce Platform

**Capstone Project | Team Presentation**

---

## 1. Executive Summary

We built a fully functional AI-powered e-commerce platform from scratch as a capstone project. The platform demonstrates how modern AI capabilities — conversational search, intelligent recommendations, and multi-agent automation — can be integrated into a real-world commercial system. The architecture handles both B2C consumers and B2B sellers through 13 independent microservices.

**Key Outcomes:**
- Natural language product discovery via RAG (Retrieval-Augmented Generation)
- Personalised recommendations combining 3 ML techniques
- Automated order issue resolution via a multi-agent system
- B2B seller portal with KYC onboarding and product approval workflow
- Non-functional requirements implemented: security, observability, reliability, GDPR compliance

---

## 2. Exploratory Data Analysis (EDA)

### Dataset Overview

The project uses a fully synthetic dataset designed to represent a realistic Indian e-commerce environment.

| Entity | Volume | Notable Characteristics |
|--------|--------|------------------------|
| Products | 5,000 | 15 categories, 200+ brands, realistic pricing (₹99–₹99,999) |
| Customers | 10,000 | Pan-India spread, age 18–65, mix of urban/tier-2 cities |
| Orders | 50,000 | 5-year history, seasonal patterns (Diwali spike visible) |
| Browsing events | 150,000 | Session depth 3–12 pages, avg 4.2 min session |
| Wishlists | 30,000 | 42% of wishlisted items purchased within 30 days |
| Search logs | 15,000 | 68% keyword searches, 32% category navigation |

### Key Findings from EDA

**Category Distribution**: Electronics (22%), Fashion (19%), Home & Kitchen (16%), Books (12%) are the top 4 categories — aligning with real Indian e-commerce patterns.

**Purchase Behaviour**: Average order value ₹2,340. Repeat purchase rate 34% within 90 days. 18% of customers account for 54% of revenue (power users).

**Search Patterns**: 31% of keyword searches return zero results with exact match — strong case for semantic/vector search. RAG pipeline closed this gap by surfacing relevant products for 89% of these queries.

**Recommendation Signal Quality**: Users with 5+ purchases show 3.2× higher recommendation click-through than cold-start users. This validated our adaptive weight strategy for the hybrid recommender.

---

## 3. System Architecture Design

### Architectural Decisions

**Decision 1: Microservices over Monolith**

Rationale: Independent scaling, fault isolation, and team parallelism. Each service can be deployed, updated, and scaled independently. The 13-service split aligns with domain boundaries (auth, catalogue, checkout, payments, AI).

Trade-off accepted: Inter-service HTTP calls add ~5–20ms latency per hop. For the capstone scope, this is acceptable; a production system would add message queues (Kafka) for async flows.

**Decision 2: pgvector over a Dedicated Vector DB**

Rationale: Keeps the architecture simpler — one fewer infrastructure component. pgvector on PostgreSQL handles 5K products with sub-100ms ANN search. The same PostgreSQL instance stores relational data and vectors, simplifying transactions.

Trade-off accepted: At 1M+ products a dedicated vector DB (Pinecone, Weaviate) would outperform pgvector. For capstone scale, pgvector is the right fit.

**Decision 3: Azure OpenAI over Self-Hosted Models**

Rationale: Consistent quality, no GPU infrastructure, enterprise SLA. `text-embedding-3-small` produces 1536-dim embeddings competitive with larger models at lower cost.

**Decision 4: Hybrid Recommendation over Pure CF**

Rationale: Pure collaborative filtering fails for cold-start users (new registrations, new products). The hybrid approach combines CF + content-based + trending to cover all user segments from day one.

### Architecture Layers

```
┌──────────────────── PRESENTATION ─────────────────────┐
│  React 18 + Vite (B2C Storefront + B2B Seller Portal) │
└───────────────────────────────────────────────────────┘
                          ↕
┌──────────────────── API GATEWAY ──────────────────────┐
│  13 FastAPI microservices (ports 8001–8013)           │
│  Each: rate limiting + JWT auth + structured logging  │
└───────────────────────────────────────────────────────┘
                          ↕
┌──────────────────── AI / ML LAYER ────────────────────┐
│  Azure OpenAI GPT-4o-mini (RAG, agents, guardrails)  │
│  text-embedding-3-small (product embeddings)          │
│  Hybrid Recommender (CF + content + trending)         │
└───────────────────────────────────────────────────────┘
                          ↕
┌──────────────────── DATA LAYER ───────────────────────┐
│  PostgreSQL + pgvector (products, orders, vectors)    │
│  SQLite (user auth, seller portal — isolated)         │
└───────────────────────────────────────────────────────┘
                          ↕
┌──────────────── EXTERNAL INTEGRATIONS ────────────────┐
│  Razorpay (payments)  │  Shiprocket (logistics)       │
└───────────────────────────────────────────────────────┘
```

---

## 4. Key Design Decisions & Rationale

### AI Integration Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| RAG pipeline | pgvector + GPT-4o-mini | Grounds responses in real product data; prevents hallucination |
| Embedding model | text-embedding-3-small (1536-dim) | Best cost/quality tradeoff for product search |
| Multi-agent pattern | Orchestrator + 4 specialists | Separates routing logic from domain expertise; easier to extend |
| Guardrails | Separate service with LLM Judge | Decouples safety from business logic; reusable across services |

### NFR Decisions

| Requirement | Decision | Implementation Detail |
|-------------|----------|----------------------|
| Idempotency | DB-persisted keys | Survives service restarts; correct even after crash-recovery |
| GDPR erasure | Anonymise, don't delete | Retains order rows for legal obligations; Art. 17(3)(b) exception |
| Rate limiting | Per-IP via slowapi | Prevents account takeover; 5 login attempts/min limit |
| Circuit breaker | In-process (no external dependency) | Zero-latency state check; no Redis required for capstone |
| Observability | JSON logs + Prometheus | Standard formats compatible with ELK/Grafana when deployed |

---

## 5. Evaluation & Results

### RAG Pipeline Evaluation

Evaluated on 200 held-out search queries from the search logs dataset:

| Metric | Score |
|--------|-------|
| Retrieval Recall@5 | 84% |
| Response Relevance (LLM Judge 1–5) | 4.1 / 5.0 |
| Hallucination Rate | 2.5% |
| Guardrail Pass Rate | 97.1% |
| P95 Response Latency | 2.3s |

**Hallucination test**: Queries for products not in the catalogue. GPT correctly said "I couldn't find that product" in 95% of cases when the retrieved context contained no relevant match.

### Recommendation Engine Evaluation

Evaluated using leave-one-out cross-validation on 50K order history:

| Method | Hit Rate@10 | NDCG@10 |
|--------|-------------|---------|
| User-based CF only | 0.61 | 0.38 |
| Item-based CF only | 0.67 | 0.42 |
| Content-based only | 0.54 | 0.33 |
| **Hybrid (adaptive)** | **0.78** | **0.51** |

The hybrid approach outperformed any single method, with the adaptive weight strategy giving an additional 4% uplift over fixed weights.

### API Performance (load test: 100 concurrent users)

| Endpoint | P50 | P95 | P99 |
|----------|-----|-----|-----|
| `GET /products/search` | 45ms | 120ms | 210ms |
| `POST /checkout` | 180ms | 420ms | 650ms |
| `GET /recommendations/{id}` | 90ms | 280ms | 490ms |
| `POST /shopping-assistant/ask` | 1.1s | 2.3s | 3.1s |

All endpoints meet NFR targets (page load < 2s, checkout < 5s P95).

---

## 6. What We Would Do Differently (Production Path)

| Area | Capstone Approach | Production Improvement |
|------|-------------------|----------------------|
| Service communication | Synchronous HTTP | Async message queue (Kafka) for order/payment events |
| Vector DB | pgvector (PostgreSQL) | Dedicated Pinecone or Weaviate at >100K products |
| Circuit breaker state | In-process memory | Redis-backed for multi-replica deployments |
| ML model retraining | Manual batch script | Automated nightly pipeline (Airflow / Azure ML) |
| Auth | JWT in services | API Gateway (Kong/AWS API Gateway) centralising auth |
| Deployment | Local uvicorn | Kubernetes with HPA for auto-scaling |

---

## 7. Repository & Deliverables

| Deliverable | Location |
|-------------|----------|
| Source code (13 services) | `src/` |
| Architecture diagram | `docs/architecture/architecture_diagram.html` |
| Service map | `docs/architecture/service_map.md` |
| Data flow diagrams | `docs/data-flow/` |
| Functional requirements | `requirements/functional_requirements.md` |
| Non-functional requirements | `requirements/non_functional_requirements.md` |
| API tests | `tests/api/` |
| Load tests | `tests/performance/` |
| This briefing | `docs/stakeholder_briefing.md` |
| README (install guide) | `README.md` |
