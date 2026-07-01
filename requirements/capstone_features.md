# Capstone AI Feature Requirements

These five features form the AI/ML intelligence layer built on top of the base e-commerce microservices platform.

---

## Feature 1 — Demand Forecasting (ML)

**Service**: `inventory_service` (port 8005)
**Frontend**: `/forecasting` route

### Functional Requirements
- Predict category-level product demand 30 days into the future.
- Train one Ridge Regression model per product category using 90 days of synthetic order history.
- Feature engineering: 7 features per observation — linear trend + sin/cos harmonics at 7-day, 30-day, and 90-day cycles (Fourier series).
- Generate ±1.5×RMSE confidence bands for every forecast point.
- Automatically detect restocking needs: alert when cumulative 30-day demand > current stock quantity.
- Expose restock alerts with severity (`critical` / `warning`) and days-until-stockout.

### Non-Functional Requirements
- `/forecast/train` completes in < 10 seconds for up to 50 categories.
- Forecast endpoints respond in < 200 ms (pre-computed, no on-demand ML inference).
- Models retrain on-demand via `POST /forecast/train`.

### Acceptance Criteria
| Criterion | Verification |
|-----------|-------------|
| Forecast covers 30 days forward | `GET /forecast/category/{cat}` returns 30 `forecast` entries |
| Confidence bands present | Each forecast entry has `lower` and `upper` fields |
| Restock alerts auto-generated | `GET /forecast/restock-alerts` returns alerts with `days_until_stockout` |
| RMSE exposed | `GET /forecast/categories` returns per-category `rmse` value |

---

## Feature 2 — Recommendation Feedback Loop

**Service**: `recommendation_engine` (port 8006)
**Frontend**: `/recommendations` route

### Functional Requirements
- Accept explicit feedback events: `thumbs_up`, `thumbs_down`, `not_interested`.
- Maintain per-user adaptation state: `category_boosts`, `brand_boosts`, `blocked_products`, `strategy_weights`.
- Apply geometric mean `(category_multiplier × brand_multiplier) ** 0.5` to recommendation scores.
- Adaptation constants:
  - `BOOST_FACTOR = 1.25` (thumbs_up)
  - `PENALTY_FACTOR = 0.80` (thumbs_down)
  - `MAX_BOOST = 2.5`, `MIN_BOOST = 0.25`
  - `not_interested` permanently blocks product + 0.92× category penalty.
- Strategy weights nudge ±0.05 per feedback event.
- `GET /recommendations/for/{customer_id}` returns `feedback_adapted: true` once adaptation is active.
- Deduplication: blocked products excluded before `limit` is applied (fetch `limit × 2` then filter).

### Non-Functional Requirements
- Feedback events stored immediately; adaptation visible on next recommendation request.
- No TTL cache on personalized endpoint (ensures real-time adaptation visibility).

### Acceptance Criteria
| Criterion | Verification |
|-----------|-------------|
| Feedback recorded | `POST /feedback` returns 200 with `adaptation_summary` |
| Boosts applied | `GET /feedback/{id}/stats` shows non-zero `category_boosts` |
| Blocked products hidden | `not_interested` product absent from subsequent recommendations |
| Reset clears state | `POST /feedback/{id}/reset` zeroes all boosts |
| Adapted flag | `GET /recommendations/for/{id}` shows `feedback_adapted: true` after any feedback |

---

## Feature 3 — Anomaly Detection with Real-Time Dashboard

**Service**: `guardrails_service` (port 8010)
**Frontend**: `/guardrails` route (Security Operations Center)

### Functional Requirements
- Run 10 statistical detectors on demand (`POST /anomaly/scan?scan_type=full`):
  1. `order_amount` — Z-score (≥4σ) on order totals
  2. `rapid_ordering` — >10 orders/customer/60 min
  3. `payment_failure` — ≥3 failed transactions/customer/24h
  4. `search_injection` — SQL/XSS regex on search_logs
  5. `inventory_price` — price ≤₹1 or discount ≥95%
  6. `bot_behavior` — >100 searches/user/hour
  7. `bulk_purchase` — >50 units in a single order line
  8. `replay_attack` — duplicate provider_payment_id with status=captured
  9. `new_account_high_value` *(new)* — <7-day accounts with orders >p75
  10. `inventory_drain` *(new)* — >50% stock consumed in 24h
- Deduplicate alerts: same (entity_id, anomaly_type) within 24h does not create duplicate.
- Alert lifecycle: `open` → `acknowledged` → `resolved` / `false_positive`.
- SSE stream (`GET /anomaly/stream`): push new alerts to merchant dashboard in real-time.
- Dashboard endpoint (`GET /anomaly/dashboard`): KPIs, 24-bar hourly trend, type breakdown, top risky entities.

### Non-Functional Requirements
- Full scan completes in < 500 ms on the test dataset.
- SSE heartbeat every 10 s; new-alert poll every 30 s.
- All endpoints CORS-enabled for frontend on port 3000.

### Acceptance Criteria
| Criterion | Verification |
|-----------|-------------|
| All 10 detectors run | Scan response shows `detectors_run: 10`, `detectors_errored: 0` |
| SSE stream connects | `curl -N .../anomaly/stream` returns `event: connected` |
| Dashboard KPIs accurate | Dashboard open count matches Alerts tab count |
| Alert lifecycle | Resolved alert no longer appears in `status=open` filter |
| Deduplication active | Running scan twice does not double alert count |

---

## Feature 4 — Real-Time Inventory Alerts (SSE)

**Service**: `inventory_service` (port 8005)
**Frontend**: `/inventory` route (Ops Dashboard)

### Functional Requirements
- SSE stream at `GET /inventory/stream` pushes `inventory_change` and `low_stock_alert` events.
- Configurable alert rules: threshold-based, reorder-quantity triggers.
- Restock action: `POST /inventory/{product_id}/restock` with quantity and reason.
- Adjustment action: `POST /inventory/{product_id}/adjust` with delta and reason.
- Inventory movements log (audit trail).

---

## Feature 5 — AI Shopping Assistant (RAG)

**Service**: `shopping_assistant` (port 8002)
**Frontend**: `/assistant` route

### Functional Requirements
- Multi-turn conversational product search grounded in the product catalogue.
- RAG pipeline: embed query → pgvector cosine search → build context → GPT-5.4-mini completion.
- Guardrail check on every response before returning to client.
- Session persistence: conversation history stored per `session_id`.
- Returns `sources[]` list of matched products alongside the natural-language reply.
