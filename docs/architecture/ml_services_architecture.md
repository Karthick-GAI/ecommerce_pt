# ML Services Architecture

This document describes the software components, service boundaries, and data stores for the three AI/ML intelligence features. It is an **architecture** document — it shows *what components exist and how they connect*, not *how data moves through them* (see `/docs/data-flow/` for that).

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         React Frontend  :3000                           │
│   /forecasting     /recommendations     /guardrails (Security SOC)      │
└───────────┬─────────────────┬─────────────────────┬───────────────────┘
            │                 │                     │
            ▼                 ▼                     ▼
┌───────────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐
│ inventory_service │ │ recommendation_ │ │    guardrails_service        │
│   :8005           │ │ engine  :8006   │ │       :8010                 │
│                   │ │                 │ │                             │
│ Components:       │ │ Components:     │ │ Components:                 │
│  forecast_engine  │ │  recommenders/  │ │  anomaly/detectors.py       │
│  (Ridge Regression│ │  (CF, content,  │ │  anomaly/scanner.py         │
│   Fourier features│ │   trending)     │ │  routes/anomaly_routes.py   │
│   confidence bands│ │  feedback_engine│ │  validators/security.py     │
│   restock logic)  │ │  (boosts, JSONB │ │  routes/validation_routes   │
│                   │ │   adaptation)   │ │                             │
│ Routes:           │ │  routes/        │ │ Routes:                     │
│  /forecast/*      │ │  recommendations│ │  /anomaly/*                 │
│  /inventory/*     │ │  /feedback/*    │ │  /validate/*                │
│  /alerts/*        │ │  /interactions  │ │  /rules/*                   │
│  /alert-rules/*   │ │  /profiles/*    │ │  /analytics/*               │
└────────┬──────────┘ └────────┬────────┘ └──────────────┬──────────────┘
         │                     │                          │
         └─────────────────────┼──────────────────────────┘
                               ▼
         ┌─────────────────────────────────────────────────┐
         │           PostgreSQL  (shared database)         │
         │                                                 │
         │  Tables owned by inventory_service:             │
         │    inventory, inventory_movements               │
         │    inventory_alerts, alert_rules                │
         │    forecast_models, demand_history              │
         │    restock_alerts                               │
         │                                                 │
         │  Tables owned by recommendation_engine:         │
         │    rec_interactions, rec_browsing_events        │
         │    rec_user_preference_profiles                 │
         │    rec_explicit_feedback                        │
         │    rec_feedback_adaptations                     │
         │                                                 │
         │  Tables owned by guardrails_service:            │
         │    anomaly_alerts, guard_rules                  │
         │    validation_logs                              │
         │                                                 │
         │  Shared read-only tables (cross-service):       │
         │    products, customers, orders                  │
         │    checkout_orders, pay_transactions            │
         │    search_logs, browsing_events                 │
         └─────────────────────────────────────────────────┘
```

---

## Service Isolation Principle

Each ML service **owns its tables** and only writes to them. Cross-service reads are done directly via PostgreSQL (shared DB, no service-to-service HTTP calls on the read path). This keeps latency low and avoids circular dependency.

| ML Service | Owns (read+write) | Reads from (shared) |
|---|---|---|
| `inventory_service` | forecast_models, demand_history, restock_alerts, inventory, inventory_alerts | products, orders |
| `recommendation_engine` | rec_* tables | products, orders, browsing_events |
| `guardrails_service` | anomaly_alerts, guard_rules, validation_logs | products, customers, checkout_orders, pay_transactions, search_logs |

---

## SSE Architecture

Both `inventory_service` and `guardrails_service` expose Server-Sent Events (SSE) streams. The architecture is identical:

```
Browser EventSource(url)
        │
        ▼  HTTP/1.1 keep-alive
FastAPI StreamingResponse(generator(), media_type="text/event-stream")
        │
        ▼  async generator (asyncio.sleep intervals)
PostgreSQL queries (synchronous SQLAlchemy, blocking loop)
        │
        ▼  event: <type>\ndata: <json>\n\n
Browser EventSource.addEventListener('<type>', handler)
```

**Design note**: The async generators call synchronous SQLAlchemy queries inside `asyncio.sleep` intervals. This momentarily blocks the event loop during the query but is acceptable for low-frequency polling (every 10–30 s). A production upgrade would use `asyncpg` with `run_in_executor` to keep the loop fully non-blocking.

---

## Forecast Model Storage

Ridge Regression models are not serialised to files. They are re-trained from raw data on each `POST /forecast/train` call and their coefficients are stored in the `forecast_models` PostgreSQL table. This avoids file system state and makes horizontal scaling straightforward (any replica can rebuild models from the same DB).

```
forecast_models table:
  id, category, coefficients (JSONB), intercept (float),
  rmse, feature_names (JSONB), n_samples,
  trained_at, valid_from, valid_until
```

---

## Feedback Adaptation Storage

Per-user adaptation state is stored as JSONB in a single `rec_feedback_adaptations` row per customer. JSONB is used (rather than normalised rows) because the key space is variable (arbitrary category/brand names) and the update pattern is always "fetch one row, update a key, save".

```python
# Single UPSERT pattern — no row-level locking needed
INSERT INTO rec_feedback_adaptations (customer_id, category_boosts, ...)
VALUES (%s, %s, ...)
ON CONFLICT (customer_id) DO UPDATE
  SET category_boosts = EXCLUDED.category_boosts,
      last_updated    = now()
```
