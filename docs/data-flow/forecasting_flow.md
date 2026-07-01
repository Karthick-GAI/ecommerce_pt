# Data Flow — Demand Forecasting

## Purpose
Predict 30-day category-level product demand using Ridge Regression with Fourier feature engineering, and automatically generate restock alerts when cumulative forecast exceeds current stock.

---

## Flow Diagram

```
POST /forecast/train
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  STEP 1 — DATA COLLECTION                              │
│                                                        │
│  inventory_service queries the shared PostgreSQL DB    │
│  SELECT category, created_at, quantity                 │
│  FROM dataset_orders                                   │
│  WHERE created_at >= NOW() - INTERVAL '90 days'        │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  STEP 2 — DAILY AGGREGATION                            │
│                                                        │
│  Group by (category, date) → daily_units_sold          │
│  Fill missing days with 0 (complete time series)       │
│  Result: 90-row series per category                    │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  STEP 3 — FEATURE ENGINEERING (Fourier)                │
│                                                        │
│  X = [t, sin(2πt/7), cos(2πt/7),                      │
│           sin(2πt/30), cos(2πt/30),                    │
│           sin(2πt/90), cos(2πt/90)]                    │
│                                                        │
│  7 features per day:                                   │
│    t           — linear trend (day index)              │
│    7-day cycle — captures weekly seasonality           │
│    30-day cycle— captures monthly patterns             │
│    90-day cycle— captures quarterly trend              │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  STEP 4 — MODEL TRAINING                              │
│                                                        │
│  Ridge Regression (alpha=1.0) fitted per category      │
│  RMSE computed on training window                      │
│  Confidence interval = ±1.5 × RMSE                    │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  STEP 5 — 30-DAY FORECAST GENERATION                  │
│                                                        │
│  Generate t = [91, 92, ..., 120]                       │
│  Apply Fourier transform to future t values            │
│  Predict with trained Ridge model                      │
│  Clip to max(0, prediction) — no negative demand       │
│  Attach lower = pred - 1.5×RMSE                        │
│         upper = pred + 1.5×RMSE                        │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  STEP 6 — RESTOCK ALERT GENERATION                    │
│                                                        │
│  cumulative_30d = SUM(forecast[0:30].predicted)        │
│  current_stock  = Product.inventory_count              │
│                                                        │
│  if cumulative_30d > current_stock:                    │
│      days_until_stockout = argmin where                │
│                            running_sum >= stock        │
│      severity = "critical" if days < 7 else "warning"  │
└────────────────────────────────────────────────────────┘
        │
        ▼
  PostgreSQL: forecast_models, demand_history,
              restock_alerts tables
```

---

## Endpoints and Response Shapes

| Endpoint | Description |
|----------|-------------|
| `POST /forecast/train` | Trains models for all categories with ≥30 data points |
| `GET /forecast/summary` | Category count, total restock alerts, avg RMSE |
| `GET /forecast/categories` | Per-category RMSE, status, last_trained |
| `GET /forecast/category/{cat}` | Full 30-day forecast array with confidence bands |
| `GET /forecast/restock-alerts` | All open restock alerts with days_until_stockout |
| `POST /forecast/restock-alerts/{id}/acknowledge` | Mark alert reviewed by ops team |
| `POST /forecast/refresh-alerts` | Re-run alert detection against latest forecasts |

---

## Key Design Decisions

**Why Ridge Regression over ARIMA/Prophet?**
Ridge was chosen for interpretability, speed (<100ms inference), and zero external dependencies. The Fourier feature engineering replicates what Prophet does internally but in a form that Ridge can consume directly. At 5,000 products × 50 categories, Prophet's per-series fitting time (~10s/series) would be prohibitively slow.

**Why cumulative demand vs. per-day comparison?**
Cumulative demand accounts for seasonality: a product might have low daily demand most days but spike predictably on weekends. Comparing cumulative 30-day demand against stock gives a more accurate "will we run out this month" signal than checking the peak single-day prediction.

**Why ±1.5×RMSE for confidence bands?**
1.5× RMSE ≈ 86th percentile coverage under Gaussian residuals — intentionally wider than a ±1σ (68%) band to give ops teams conservative planning margins.
