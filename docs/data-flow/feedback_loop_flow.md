# Data Flow — Recommendation Feedback Loop

## Purpose
Adapt recommendation ranking in real-time by recording explicit user feedback (thumbs_up / thumbs_down / not_interested) and applying per-user category and brand boost multipliers to scored product lists.

---

## Flow Diagram

```
User clicks 👍 👎 or ✕ on a recommendation card
                │
                ▼
POST /feedback { customer_id, product_id, feedback_type,
                 product_name, category, brand, rec_strategy }
                │
                ▼
┌───────────────────────────────────────────────────────────┐
│  record_explicit_feedback()                               │
│                                                           │
│  1. INSERT into rec_explicit_feedback                     │
│  2. UPSERT FeedbackAdaptation row for customer            │
│     (INSERT ... ON CONFLICT (customer_id) DO UPDATE)      │
│  3. Update JSONB fields in place:                         │
│                                                           │
│     thumbs_up:                                            │
│       category_boosts[cat]  = min(old × 1.25, 2.5)       │
│       brand_boosts[brand]   = min(old × 1.25, 2.5)       │
│       strategy_weights[strat]+= 0.05 (clamped 0.05–0.9)  │
│                                                           │
│     thumbs_down:                                          │
│       category_boosts[cat]  = max(old × 0.80, 0.25)      │
│       brand_boosts[brand]   = max(old × 0.80, 0.25)      │
│       strategy_weights[strat]-= 0.05                      │
│                                                           │
│     not_interested:                                       │
│       blocked_products[product_id] = true                 │
│       category_boosts[cat]  = max(old × 0.92, 0.25)      │
└───────────────────────────────────────────────────────────┘
                │
                ▼
        PostgreSQL committed

— — — next recommendation request — — —

GET /recommendations/for/{customer_id}?limit=20
                │
                ▼
┌───────────────────────────────────────────────────────────┐
│  STEP 1 — FETCH CANDIDATES (2× buffer)                    │
│                                                           │
│  get_personalized(db, customer_id, limit=limit*2)         │
│  Returns 40 scored candidates from hybrid CF pipeline     │
└───────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────┐
│  STEP 2 — LOAD ADAPTATION STATE                           │
│                                                           │
│  get_adaptation(db, customer_id)                          │
│  → FeedbackAdaptation row (JSONB fields loaded)           │
│  Returns None if no feedback recorded yet                 │
└───────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────┐
│  STEP 3 — APPLY ADAPTATION                               │
│                                                           │
│  For each candidate product:                              │
│    1. Remove if product_id in blocked_products            │
│    2. cat_m  = category_boosts.get(category, 1.0)         │
│    3. brand_m = brand_boosts.get(brand, 1.0)              │
│    4. multiplier = (cat_m × brand_m) ** 0.5  ← geom mean  │
│    5. score = original_score × multiplier                 │
│                                                           │
│  Re-sort by adapted score descending                      │
│  Slice [:limit]   ← returns exactly N items              │
└───────────────────────────────────────────────────────────┘
                │
                ▼
        Response: { recommendations, feedback_adapted: true }
```

---

## Database Schema

```sql
-- Stores every feedback event (full audit trail)
CREATE TABLE rec_explicit_feedback (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   TEXT NOT NULL,
    product_id    TEXT NOT NULL,
    product_name  TEXT,
    category      TEXT,
    brand         TEXT,
    feedback_type TEXT NOT NULL,   -- thumbs_up | thumbs_down | not_interested
    rec_strategy  TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- One row per customer — JSONB fields updated in-place
CREATE TABLE rec_feedback_adaptations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id      TEXT UNIQUE NOT NULL,
    category_boosts  JSONB DEFAULT '{}',   -- {"Electronics": 1.5625, ...}
    brand_boosts     JSONB DEFAULT '{}',   -- {"Sony": 0.64, ...}
    blocked_products JSONB DEFAULT '{}',   -- {"prod_abc": true}
    strategy_weights JSONB DEFAULT '{}',   -- {"collaborative": 0.6, ...}
    total_thumbs_up   INT DEFAULT 0,
    total_thumbs_down INT DEFAULT 0,
    last_updated      TIMESTAMPTZ DEFAULT now()
);
```

---

## Multiplier Behaviour

| Feedback events | Category multiplier | Brand multiplier | Combined (geom mean) |
|----------------|--------------------|--------------------|----------------------|
| 0 (no feedback) | 1.0 | 1.0 | 1.0 (no change) |
| 1 thumbs_up | 1.25 | 1.25 | 1.25 |
| 2 thumbs_up | 1.5625 | 1.5625 | 1.5625 |
| 1 thumbs_up + 1 down | 1.0 | 1.0 | 1.0 |
| 1 thumbs_up category, thumbs_down brand | 1.25 | 0.80 | 1.0 (sqrt(1.25×0.80)) |

**Why geometric mean?** It requires *both* category AND brand affinity to be strong for maximum boost. A category boost alone gives √1.25 ≈ 1.12×, not the full 1.25×. This prevents runaway amplification from a single signal and keeps adaptation balanced.

---

## Route Ordering Note

`GET /feedback/loop/stats` is registered **before** `GET /feedback/{customer_id}` in `feedback_routes.py`. Without this ordering, FastAPI interprets the literal string "loop" as a customer_id parameter value, silently routing the wrong handler.
