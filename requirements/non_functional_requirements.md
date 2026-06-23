# Non-Functional Requirements

## 1. Performance

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-PERF-01 | Page load < 2 seconds (P95) | Async FastAPI endpoints, Vite-bundled frontend assets, pgvector ANN index |
| NFR-PERF-02 | Checkout flow < 5 seconds end-to-end (P95) | Async Razorpay call, DB-persisted idempotency cache, pre-validated cart |
| NFR-PERF-03 | Semantic search < 500 ms | IVFFlat/HNSW pgvector index on 1536-dim embeddings |
| NFR-PERF-04 | RAG response < 3 seconds | Streaming response from Azure OpenAI, top-5 chunk retrieval |

---

## 2. Scalability

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-SCALE-01 | Support 50,000 concurrent users (design target) | Stateless FastAPI services; horizontal scaling via adding replicas |
| NFR-SCALE-02 | Recommendation engine handles 10K requests/min | Pre-computed similarity matrices; lazy recompute on schedule |
| NFR-SCALE-03 | Independent service scaling | Each of the 13 services is independently deployable with its own `requirements.txt` |

---

## 3. Availability

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-AVAIL-01 | 99.99% uptime target | Circuit breaker prevents cascade failures across service boundaries |
| NFR-AVAIL-02 | Graceful degradation | Services return partial/cached responses when downstream is unavailable |
| NFR-AVAIL-03 | Circuit breaker pattern | `nfr/circuit_breaker.py`: CLOSED → OPEN (after `failure_threshold` failures) → HALF_OPEN (after `recovery_timeout` seconds) → CLOSED on success |
| NFR-AVAIL-04 | Health check endpoints | Every service exposes `GET /health` returning `{"status": "ok", "service": "..."}` |

---

## 4. Security

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-SEC-01 | Password security | bcrypt hashing via `passlib`; plaintext passwords never persisted |
| NFR-SEC-02 | Authentication | JWT access tokens (15 min) + refresh tokens (7 days) via `python-jose` |
| NFR-SEC-03 | Account takeover prevention | `slowapi` rate limiting: register 3/min, login 5/min, refresh 20/min per IP |
| NFR-SEC-04 | PII protection | Payment card tokens only (no raw PANs); PII anonymised on GDPR erasure |
| NFR-SEC-05 | Input validation | Pydantic schemas enforce type, length, and format constraints on all API inputs |
| NFR-SEC-06 | Content moderation | `guardrails_service` validates AI inputs/outputs before surfacing to users |
| NFR-SEC-07 | HTTPS | All external endpoints served over TLS (deployment-level; nginx/cloud LB) |

---

## 5. Compliance

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-COMP-01 | GDPR Art. 17 — Right to Erasure | `DELETE /users/me/gdpr-erasure`: anonymises email/name, hard-deletes addresses and payment methods, retains order rows (Art. 17(3)(b) legal obligation exception) |
| NFR-COMP-02 | GDPR Art. 20 — Data Portability | `GET /users/me/data-export`: returns all user PII as machine-readable JSON |
| NFR-COMP-03 | PCI-DSS alignment | Raw card numbers never stored; Razorpay tokenisation used for card storage |
| NFR-COMP-04 | Audit trail | Structured logs with `X-Trace-ID` provide tamper-evident request audit trail |

---

## 6. Reliability

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-REL-01 | Idempotent order placement | `Idempotency-Key` header: DB-persisted key → endpoint → cached response; duplicate requests return original response, no second order created |
| NFR-REL-02 | No overselling | Atomic stock decrement in `inventory_service`; checkout rejected if stock < requested quantity |
| NFR-REL-03 | Idempotent payment confirmation | Razorpay webhook uses payment ID as natural idempotency key; duplicate webhooks are no-ops |
| NFR-REL-04 | Order state machine integrity | Backward state transitions are rejected with HTTP 400 |

---

## 7. Observability

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-OBS-01 | Structured logging | `nfr/structured_logging.py`: every log line is single-line JSON with `timestamp`, `level`, `service`, `message`, and context fields |
| NFR-OBS-02 | Distributed tracing | `RequestLoggingMiddleware` injects `X-Trace-ID` (UUID) per request; propagated downstream via headers |
| NFR-OBS-03 | Prometheus metrics | `nfr/metrics.py` via `prometheus_fastapi_instrumentator`: request count, latency histograms, error rates per endpoint |
| NFR-OBS-04 | Metrics endpoint | Every service exposes `GET /metrics` in Prometheus exposition format |
| NFR-OBS-05 | Per-request logging | Each request logs: `method`, `path`, `status_code`, `duration_ms`, `user_id`, `client_ip`, `trace_id` |

---

## 8. Maintainability

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-MAINT-01 | Modular microservices | 13 independent services; each has its own `main.py`, `models.py`, `routes/`, `requirements.txt` |
| NFR-MAINT-02 | Shared NFR utilities | `src/nfr/` package: circuit_breaker, structured_logging, metrics — imported by all services |
| NFR-MAINT-03 | Dependency management | Each service has an isolated `requirements.txt`; no shared virtualenv |
| NFR-MAINT-04 | API documentation | FastAPI auto-generates OpenAPI 3.0 specs; Swagger UI at `/docs`, ReDoc at `/redoc` |
| NFR-MAINT-05 | Environment configuration | All secrets and config via environment variables; `.env.example` committed for reference |

---

## 9. B2B / B2C Dual Mode

| ID | Requirement | Implementation |
|----|-------------|---------------|
| NFR-B2B-01 | Consumer storefront (B2C) | React 18 + Vite frontend; user auth via `user_management`; RAG shopping assistant |
| NFR-B2B-02 | Seller portal (B2B) | `seller_portal` service (port 8011): KYC onboarding, product submission, order fulfilment, commission dashboard |
| NFR-B2B-03 | Seller approval workflow | New sellers start `pending_verification`; admin activates; product listings require admin approval |
| NFR-B2B-04 | Isolated seller auth | Separate JWT namespace for sellers (`seller_portal/auth.py`); sellers cannot access buyer APIs |
