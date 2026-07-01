# Data Flow — Anomaly Detection

## Purpose
Detect suspicious purchasing and inventory activities using 10 statistical detectors, persist alerts with severity and evidence, and stream new alerts to a merchant-facing SSE dashboard in real-time.

---

## Scan Flow

```
POST /anomaly/scan?scan_type=full
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  run_full_scan(db)   — scanner.py                            │
│                                                              │
│  For each of 10 DETECTORS (run sequentially):                │
│    detector(db) → list[AnomalyAlert]  (uncommitted objects)  │
│  Errors in individual detectors do not abort the scan.       │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  dedupe_alerts(all_new, db)                                  │
│                                                              │
│  SELECT entity_id, anomaly_type                              │
│  FROM anomaly_alerts                                         │
│  WHERE status IN ('open','acknowledged')                     │
│    AND detected_at >= NOW() - INTERVAL '24 hours'            │
│                                                              │
│  Filter: drop new alerts whose (entity_id, anomaly_type)     │
│          already has an open alert in the 24h window.        │
│  Prevents alert storms from re-scanning.                     │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
        INSERT new alerts → PostgreSQL anomaly_alerts
        Return scan summary dict
```

---

## Detector Logic Summary

```
┌─────────────────────┬──────────────────────────────────────────────┐
│ Detector            │ Method                                        │
├─────────────────────┼──────────────────────────────────────────────┤
│ order_amount        │ Z-score (σ≥4) on 90-day baseline orders       │
│                     │ Fallback to IQR if baseline < 30 rows         │
├─────────────────────┼──────────────────────────────────────────────┤
│ rapid_ordering      │ COUNT(orders) per customer in 60-min window   │
│                     │ Alert if count > ORDER_RATE_MAX (default 10)  │
├─────────────────────┼──────────────────────────────────────────────┤
│ payment_failure     │ COUNT(failed txns) per customer in 24h        │
│                     │ Alert if count >= PAYMENT_FAIL_MAX (default 3)│
├─────────────────────┼──────────────────────────────────────────────┤
│ search_injection    │ Regex match: _COMPILED_SQL + _COMPILED_XSS    │
│                     │ Scans last SEARCH_SCAN_HOURS of SearchLog     │
├─────────────────────┼──────────────────────────────────────────────┤
│ inventory_price     │ price ≤ MIN_PRICE (₹1) → near-zero pricing    │
│                     │ discount_pct ≥ MAX_DISCOUNT (95%) → extreme   │
│                     │ inventory_count < 0 → data integrity issue    │
├─────────────────────┼──────────────────────────────────────────────┤
│ bot_behavior        │ COUNT(searches) per user_id in last 1 hour    │
│                     │ Alert if > 100 searches/hour                  │
├─────────────────────┼──────────────────────────────────────────────┤
│ bulk_purchase       │ JSONB lateral expand cart_activity            │
│                     │ Alert if any item.quantity > 50               │
├─────────────────────┼──────────────────────────────────────────────┤
│ replay_attack       │ GROUP BY provider_payment_id WHERE            │
│                     │ status='captured' HAVING count > 1            │
├─────────────────────┼──────────────────────────────────────────────┤
│ new_account_        │ JOIN customers + checkout_orders              │
│ high_value          │ account age < 7 days AND total > p75          │
│ (NEW)               │ p75 computed from historical order totals     │
├─────────────────────┼──────────────────────────────────────────────┤
│ inventory_drain     │ JSONB lateral: SUM units ordered per          │
│ (NEW)               │ product in last 24h via dataset orders        │
│                     │ Alert if units_ordered/stock_qty > 0.5        │
└─────────────────────┴──────────────────────────────────────────────┘
```

---

## SSE Stream Flow

```
Client connects: GET /anomaly/stream
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  INITIAL SNAPSHOT                                            │
│                                                              │
│  SELECT * FROM anomaly_alerts                                │
│  WHERE status = 'open'                                       │
│  ORDER BY detected_at DESC LIMIT 100                         │
│                                                              │
│  For each alert:                                             │
│    yield "event: alert\ndata: {json}\n\n"                    │
│                                                              │
│  yield "event: connected\ndata: {open_count}\n\n"            │
└──────────────────────────────────────────────────────────────┘
                │
                ▼  (loop)
┌──────────────────────────────────────────────────────────────┐
│  POLLING (every 30 s)                                        │
│                                                              │
│  db.expire_all()   ← refresh SQLAlchemy identity map        │
│  SELECT * FROM anomaly_alerts                                │
│  WHERE detected_at > last_check                              │
│                                                              │
│  For each new alert:                                         │
│    yield "event: alert\ndata: {json}\n\n"                    │
│                                                              │
│  last_check = now()                                          │
│                                                              │
│  HEARTBEAT (every 10 s between polls)                        │
│    yield "event: heartbeat\ndata: {tick}\n\n"                │
└──────────────────────────────────────────────────────────────┘
```

---

## Alert Lifecycle

```
detected → status: open
                │
    ┌───────────┴───────────┐
    ▼                       ▼
 acknowledge            (skip)
 status: acknowledged       │
    │                       │
    ▼                       ▼
 resolve              false_positive
 status: resolved     status: false_positive
 resolved_at = now()  resolved_at = now()
```

The `resolved_at`, `resolved_by`, and `resolution_note` fields are populated on resolve/false-positive. Dashboard "Resolved (24h)" KPI counts alerts resolved in the last 24 hours regardless of original severity.

---

## Dashboard Endpoint Data Sources

`GET /anomaly/dashboard` computes in a single DB round-trip:

| Dashboard Component | SQL Operation |
|---------------------|---------------|
| KPI counts (open/critical/high/medium/low) | 5× filtered COUNT on `anomaly_alerts` |
| New 24h / Resolved 24h | COUNT with `detected_at >= now()-24h` / `resolved_at >= now()-24h` |
| Hourly trend (24 bars) | Fetch recent 24h, group by `.hour` in Python |
| By-type donut | GROUP BY anomaly_type WHERE status='open' |
| Top risky entities | GROUP BY entity_id, MAX(risk_score), SUM(risk_score) |
