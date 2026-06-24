# Production-Scale Architecture

This document describes the **target production deployment** of the AI-powered e-commerce platform on Kubernetes. It is distinct from the local POC setup described in the [README](../../README.md).

---

## POC vs Production Distinction

| Dimension | POC (Current) | Production Target |
|-----------|--------------|------------------|
| Deployment | 13 uvicorn processes on one VM | Kubernetes cluster (3+ nodes) |
| Entry point | Direct service ports (8001–8013) | API Gateway + Load Balancer |
| Scaling | Manual (one process per service) | HPA — auto-scales on CPU/RPS |
| DB | Shared PostgreSQL + SQLite on localhost | RDS PostgreSQL per service domain + PgBouncer |
| Vector store | pgvector on shared PostgreSQL | Managed Qdrant / Pinecone at scale |
| Circuit breaker state | In-process (single replica) | Redis-backed (shared across replicas) |
| Rate limiting | In-process slowapi counters | API Gateway policies + Redis counters |
| Secrets | `.env` file | Kubernetes Secrets / AWS Secrets Manager |
| Observability | Stdout JSON logs + /metrics endpoint | Centralised Prometheus + Grafana + ELK |
| ML model serving | Inline in FastAPI (cold start on request) | Torchserve / Triton sidecar (warm at startup) |
| CI/CD | Manual `docker-compose up` | GitLab CI → ArgoCD GitOps |

---

## Production Architecture Diagram

```
                         ┌──────────────────────────────────────┐
                         │           INTERNET / CDN              │
                         │     (Cloudflare / AWS CloudFront)     │
                         └────────────────┬─────────────────────┘
                                          │ HTTPS
                                          ▼
                  ┌────────────────────────────────────────────┐
                  │             API GATEWAY (Kong / AWS APIGW)  │
                  │                                              │
                  │  • TLS termination                          │
                  │  • JWT validation (edge)                    │
                  │  • Rate limiting (Redis-backed counters)    │
                  │  • Request routing by path prefix           │
                  │  • DDoS protection                          │
                  └──────────────────┬─────────────────────────┘
                                     │
                         ┌───────────▼───────────┐
                         │   LOAD BALANCER (L7)   │
                         │   (AWS ALB / nginx)     │
                         │                         │
                         │  • Health checks        │
                         │  • Sticky sessions      │
                         │  • SSL offload          │
                         └───────────┬─────────────┘
                                     │
            ┌────────────────────────▼────────────────────────┐
            │            KUBERNETES CLUSTER (EKS / GKE)        │
            │                                                    │
            │  ┌──────────────────────────────────────────────┐ │
            │  │               SERVICE MESH (Istio)            │ │
            │  │  • mTLS between microservices                │ │
            │  │  • Circuit breaker (Envoy sidecar)           │ │
            │  │  • Distributed tracing (Jaeger)              │ │
            │  └──────────────────────────────────────────────┘ │
            │                                                    │
            │  ┌────────────────────────────────────────────┐   │
            │  │           MICROSERVICE PODS                  │   │
            │  │                                              │   │
            │  │  user_management    (3 replicas, HPA)       │   │
            │  │  product_catalogue  (3 replicas, HPA)       │   │
            │  │  shopping_assistant (2 replicas, HPA)       │   │
            │  │  checkout_service   (3 replicas, HPA)       │   │
            │  │  recommendation_engine (2 replicas, HPA)    │   │
            │  │  inventory_service  (3 replicas, HPA)       │   │
            │  │  order_management   (2 replicas, HPA)       │   │
            │  │  payment_shipping   (2 replicas, HPA)       │   │
            │  │  guardrails_service (2 replicas, HPA)       │   │
            │  │  multi_agent_system (1 replica, HPA)        │   │
            │  │  seller_portal      (2 replicas, HPA)       │   │
            │  │  tool_calling_agent (1 replica, HPA)        │   │
            │  │  session_service    (2 replicas, HPA)       │   │
            │  └────────────────────────────────────────────┘   │
            │                                                    │
            │  ┌────────────────────────────────────────────┐   │
            │  │            HORIZONTAL POD AUTOSCALER        │   │
            │  │  Scale triggers: CPU > 70%, RPS > 500/pod  │   │
            │  │  Min: 2 replicas   Max: 10 replicas         │   │
            │  └────────────────────────────────────────────┘   │
            └────────────────────────────────────────────────────┘
                              │                    │
               ┌──────────────▼──────┐   ┌────────▼───────────┐
               │   DATA LAYER         │   │    AI / ML LAYER    │
               │                      │   │                      │
               │  RDS PostgreSQL      │   │  Azure OpenAI        │
               │  (Multi-AZ, HA)      │   │  (GPT-5.4-mini,      │
               │                      │   │   embedding-3-small) │
               │  PgBouncer           │   │                      │
               │  (connection pool)   │   │  Torchserve sidecar  │
               │                      │   │  (Flan-T5-base,      │
               │  ElastiCache Redis   │   │   local fallback)    │
               │  (cache, sessions,   │   │                      │
               │   rate limit state,  │   │  Qdrant (vector DB   │
               │   circuit breakers)  │   │  at 500K+ products)  │
               └──────────────────────┘   └────────────────────┘
```

---

## Component Responsibilities

### API Gateway (Kong / AWS API Gateway)
- **TLS termination** — all external traffic is HTTPS; internal is mTLS via Istio
- **JWT validation** — stateless token verification at the edge; backend services trust validated tokens
- **Rate limiting** — Redis-backed counters shared across all gateway replicas (eliminates the per-replica counter flaw of the POC)
- **Routing** — path-prefix routing (`/auth/*` → user_management, `/products/*` → product_catalogue, `/chat/*` → shopping_assistant)
- **DDoS protection** — rate limiting tiers (anonymous, authenticated, seller)

### Load Balancer (AWS ALB)
- Layer-7 routing to Kubernetes ingress controller
- Health check probes (`/health` endpoint) — routes only to healthy pods
- Sticky sessions for WebSocket connections (shopping assistant chat)

### Kubernetes (EKS / GKE)
- **Namespaces**: `ecommerce-prod`, `ecommerce-staging`, `monitoring`
- **HPA (Horizontal Pod Autoscaler)**: scales pods based on CPU and custom RPS metrics
- **VPA (Vertical Pod Autoscaler)**: right-sizes memory/CPU requests
- **PodDisruptionBudget**: ensures at least 1 replica is always available during rolling updates
- **Rolling deploys**: zero-downtime releases with readiness probes
- **ConfigMaps**: non-secret config (feature flags, model names)
- **Secrets**: encrypted secrets mounted as environment variables

### Service Mesh (Istio)
- **mTLS**: all pod-to-pod communication is mutually authenticated
- **Circuit breaker**: Envoy sidecar enforces timeout and retry policies (replaces in-process `nfr/circuit_breaker.py` at scale)
- **Distributed tracing**: every request tagged with a trace ID; spans visible in Jaeger/Zipkin
- **Traffic policies**: canary deployments (e.g., route 10% of `/chat` traffic to shopping_assistant v2)

---

## Observability & MLOps Layer

```
┌─────────────────────────────────────────────────────────────┐
│                      OBSERVABILITY STACK                      │
│                                                               │
│  Metrics Pipeline:                                            │
│    Services ──→ /metrics (Prometheus format)                 │
│             ──→ Prometheus Operator (scrape every 15s)       │
│             ──→ Grafana dashboards                           │
│                  - Request rate, error rate, latency (RED)   │
│                  - Embedding call latency & cost             │
│                  - LLM token consumption per service         │
│                  - Vector search P50/P95/P99                  │
│                                                               │
│  Log Pipeline:                                                │
│    Services ──→ stdout JSON (nfr/structured_logging.py)      │
│             ──→ Fluent Bit (DaemonSet)                       │
│             ──→ Elasticsearch                                 │
│             ──→ Kibana dashboards                            │
│                  - Correlation by trace_id                   │
│                  - Error aggregation by service              │
│                                                               │
│  Tracing:                                                     │
│    Istio sidecar ──→ Jaeger / AWS X-Ray                      │
│                                                               │
│  Alerting:                                                    │
│    Prometheus AlertManager ──→ PagerDuty                     │
│    Thresholds: P99 > 3s, error rate > 1%, pod restarts > 3  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                        ML OPS LAYER                           │
│                                                               │
│  Model Registry (MLflow):                                     │
│    - Embedding model versions (text-embedding-3-small)       │
│    - Recommendation model weights (item-similarity matrix)   │
│    - Accuracy evaluation runs (NDCG, MRR, P@5)              │
│                                                               │
│  Model Serving:                                               │
│    - Azure OpenAI models: managed externally                 │
│    - Local fallback (Flan-T5): Torchserve sidecar in pod    │
│      → loaded at container startup (no cold start on request)│
│                                                               │
│  Drift Detection:                                             │
│    - Embedding drift: monitor cosine similarity distribution  │
│    - Recommendation quality: track CTR/conversion weekly     │
│    - Trigger re-embedding if avg similarity drops > 10%      │
│                                                               │
│  CI/CD for ML:                                                │
│    Code change → GitLab CI (unit tests, lint)                │
│               → Build Docker image                           │
│               → ArgoCD syncs Helm chart to staging           │
│               → Automated accuracy test gate (NDCG > 0.75)  │
│               → Manual approval → ArgoCD promotes to prod    │
└─────────────────────────────────────────────────────────────┘
```

---

## Scaling Strategy

### Shopping Assistant (RAG) — Latency-sensitive
- **Target**: P95 < 2.5s end-to-end
- **Bottleneck**: Azure OpenAI call (~1.2s). Can't be reduced; parallelise embedding + parse instead.
- **HPA trigger**: avg request duration > 1.5s OR CPU > 60%
- **Scale limit**: 6 replicas (Azure OpenAI rate limit is the ceiling, not compute)

### Product Catalogue — Throughput-sensitive
- **Target**: 1,000 RPS for browse/keyword; 100 RPS for semantic search
- **Bottleneck**: pgvector ANN scan at >500K products → migrate to Qdrant with HNSW index
- **HPA trigger**: RPS > 400/pod

### Checkout — Reliability-critical
- **Target**: 99.9% success rate, P99 < 800ms
- **PodDisruptionBudget**: max 1 pod unavailable (min 2 running always)
- **Idempotency keys**: stored in Redis (replaces PostgreSQL table for faster dedup at scale)

---

## Infrastructure as Code

All production infrastructure is defined in Terraform (see `infrastructure/` — not included in POC repository):

```
infrastructure/
├── eks/           — EKS cluster, node groups, IAM
├── rds/           — RDS PostgreSQL instances per domain
├── elasticache/   — Redis cluster (sessions, cache, rate limits)
├── api-gateway/   — AWS API Gateway + custom domain + WAF
├── monitoring/    — Prometheus Operator, Grafana, AlertManager
└── helm/          — Helm charts for each microservice
```

---

## POC Limitations (Explicitly Acknowledged)

The current repository is a **proof-of-concept**. The following production components are described above but not implemented:

| Component | POC State | Production Fix |
|-----------|-----------|----------------|
| API Gateway | None (direct ports) | Kong / AWS APIGW |
| Load Balancer | None | AWS ALB + K8s Ingress |
| Kubernetes | None (bare processes) | EKS with HPA + Istio |
| Redis | None | ElastiCache Redis Cluster |
| Distributed circuit breaker | In-process only | Redis-backed pybreaker |
| Distributed rate limiter | In-process only | Redis-backed slowapi |
| RDS per service | Shared PostgreSQL | RDS per domain |
| MLflow | None | MLflow tracking server |
| Helm charts | None | Per-service Helm chart |

These gaps are accepted for capstone scope. The code architecture is designed to make the transition straightforward (environment variables for all config, no hardcoded hostnames, connection pooling already in place).
