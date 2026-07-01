"""
forecast_engine.py — Category-level demand forecasting

Pipeline:
  seed_demand_history  → 90 days synthetic data per category
  generate_forecasts   → Ridge regression with Fourier features, 30-day horizon
  evaluate_restock     → stockout detection + RestockingAlert creation
  init_forecast_service → called once at startup
  retrain              → on-demand retraining from API
"""
import math
import numpy as np
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

from models import Product, DemandHistory, DemandForecast, RestockingAlert

# ── Per-category demand parameters ───────────────────────────────────────────
CATEGORY_PARAMS = {
    'Electronics':      {'base': 45,  'std': 0.22, 'growth': 0.003, 'weekend': 1.30},
    'Clothing':         {'base': 120, 'std': 0.28, 'growth': 0.005, 'weekend': 1.50},
    'Beauty':           {'base': 60,  'std': 0.20, 'growth': 0.004, 'weekend': 1.20},
    'Books':            {'base': 35,  'std': 0.15, 'growth': 0.001, 'weekend': 1.10},
    'Home & Kitchen':   {'base': 50,  'std': 0.20, 'growth': 0.002, 'weekend': 1.40},
    'Sports & Fitness': {'base': 40,  'std': 0.22, 'growth': 0.003, 'weekend': 1.30},
    'Grocery':          {'base': 80,  'std': 0.25, 'growth': 0.002, 'weekend': 1.10},
    'Toys & Games':     {'base': 30,  'std': 0.28, 'growth': 0.002, 'weekend': 1.60},
    'Automotive':       {'base': 15,  'std': 0.18, 'growth': 0.001, 'weekend': 1.00},
    'Baby Products':    {'base': 25,  'std': 0.15, 'growth': 0.002, 'weekend': 1.20},
    'Pet Supplies':     {'base': 20,  'std': 0.20, 'growth': 0.001, 'weekend': 1.10},
    'Stationery':       {'base': 18,  'std': 0.15, 'growth': 0.001, 'weekend': 0.80},
    'Furniture':        {'base': 12,  'std': 0.20, 'growth': 0.001, 'weekend': 1.40},
}

HISTORY_DAYS  = 90
FORECAST_DAYS = 30
SAFETY_DAYS   = 14   # alert when stock < 14 days of demand
RNG_SEED      = 42


# ── 1. Seed synthetic history ─────────────────────────────────────────────────

def seed_demand_history(db: Session):
    if db.query(DemandHistory).count() > 0:
        return

    rng   = np.random.default_rng(RNG_SEED)
    today = date.today()
    start = today - timedelta(days=HISTORY_DAYS - 1)

    price_map = {}
    for cat, avg_p in db.query(Product.category, func.avg(Product.price)).filter(Product.is_active == True).group_by(Product.category).all():
        price_map[cat] = float(avg_p or 50.0)

    records = []
    for cat, p in CATEGORY_PARAMS.items():
        avg_price = price_map.get(cat, 50.0)
        for i in range(HISTORY_DAYS):
            d       = start + timedelta(days=i)
            trend   = 1.0 + p['growth'] * i
            weekend = p['weekend'] if d.weekday() >= 5 else 1.0
            monthly = 1.0 + 0.15 * math.sin(2 * math.pi * d.day / 30)
            noise   = float(rng.lognormal(0, p['std']))
            units   = max(1, int(round(p['base'] * trend * weekend * monthly * noise)))
            orders  = max(1, int(round(units / rng.uniform(1.5, 3.5))))
            records.append(DemandHistory(
                category   = cat,
                date       = d,
                units_sold = units,
                num_orders = orders,
                avg_price  = round(avg_price, 2),
                revenue    = round(units * avg_price, 2),
                source     = 'seeded',
            ))

    db.bulk_save_objects(records)
    db.commit()
    print(f"[forecast] Seeded {len(records)} demand history records.")


# ── 2. Feature engineering ────────────────────────────────────────────────────

def _features(t: np.ndarray) -> np.ndarray:
    n = max(float(len(t)), 1.0)
    return np.column_stack([
        t / n,
        np.sin(2 * np.pi * t / 7),
        np.cos(2 * np.pi * t / 7),
        np.sin(2 * np.pi * t / 30),
        np.cos(2 * np.pi * t / 30),
        np.sin(2 * np.pi * t / 90),
        np.cos(2 * np.pi * t / 90),
    ])


# ── 3. Train + forecast one category ─────────────────────────────────────────

def generate_forecasts_for_category(db: Session, category: str):
    rows = (db.query(DemandHistory)
              .filter(DemandHistory.category == category)
              .order_by(DemandHistory.date)
              .all())
    if not rows:
        return None

    y      = np.array([r.units_sold for r in rows], dtype=float)
    t_hist = np.arange(len(y), dtype=float)
    X_hist = _features(t_hist)

    model = Pipeline([('sc', StandardScaler()), ('ridge', Ridge(alpha=2.0))])
    model.fit(X_hist, y)

    y_pred = np.maximum(model.predict(X_hist), 0)
    rmse   = float(np.sqrt(mean_squared_error(y, y_pred)))
    mae    = float(mean_absolute_error(y, y_pred))
    r2     = float(r2_score(y, y_pred))

    # Future features — extend the same index space
    n      = len(t_hist)
    t_fut  = np.arange(n, n + FORECAST_DAYS, dtype=float)
    # Rebuild combined feature space so normalization is consistent
    t_all  = np.arange(n + FORECAST_DAYS, dtype=float)
    X_all  = _features(t_all)
    preds  = np.maximum(model.predict(X_all[-FORECAST_DAYS:]), 0)
    ci     = 1.5 * rmse

    db.query(DemandForecast).filter(DemandForecast.category == category).delete()
    today = date.today()
    records = []
    for i, pred in enumerate(preds):
        p    = float(pred)
        conf = round(max(0.0, min(1.0, 1.0 - rmse / max(p, 1.0))), 3)
        records.append(DemandForecast(
            category         = category,
            forecast_date    = today + timedelta(days=i + 1),
            predicted_units  = round(p, 2),
            lower_bound      = round(max(0.0, p - ci), 2),
            upper_bound      = round(p + ci, 2),
            model_name       = 'ridge_fourier_v1',
            rmse             = round(rmse, 3),
            confidence_score = conf,
        ))
    db.bulk_save_objects(records)
    db.commit()
    return {'rmse': round(rmse, 3), 'mae': round(mae, 3), 'r2': round(r2, 4)}


# ── 4. Evaluate restocking needs ──────────────────────────────────────────────

def evaluate_restock_needs(db: Session):
    db.query(RestockingAlert).filter(RestockingAlert.status == 'open').delete()
    today = date.today()

    for cat in CATEGORY_PARAMS:
        stock = int(db.query(func.sum(Product.inventory_count))
                      .filter(Product.category == cat, Product.is_active == True)
                      .scalar() or 0)

        forecasts = (db.query(DemandForecast)
                       .filter(DemandForecast.category == cat,
                               DemandForecast.forecast_date > today)
                       .order_by(DemandForecast.forecast_date)
                       .limit(30).all())
        if not forecasts:
            continue

        daily = [f.predicted_units for f in forecasts]
        avg   = float(np.mean(daily))
        total = int(round(sum(daily)))

        if avg <= 0:
            continue

        # Days until cumulative demand exceeds current stock
        cumsum      = np.cumsum(daily)
        stockout_day = next((i + 1 for i, c in enumerate(cumsum) if c >= stock), None)
        days_stock   = stock / avg

        if stockout_day is not None and stockout_day <= 7:
            severity = 'critical'
        elif stockout_day is not None and stockout_day <= 30:
            severity = 'warning'
        elif days_stock < SAFETY_DAYS:
            severity = 'warning'
        else:
            continue

        recommended = max(0, int(round(avg * 60)) - stock)
        db.add(RestockingAlert(
            category                = cat,
            current_stock           = stock,
            avg_daily_demand        = round(avg, 2),
            forecasted_demand_30d   = total,
            days_until_stockout     = stockout_day,
            recommended_reorder_qty = recommended,
            severity                = severity,
            status                  = 'open',
            triggered_at            = datetime.utcnow(),
        ))

    db.commit()
    n = db.query(RestockingAlert).filter(RestockingAlert.status == 'open').count()
    print(f"[forecast] Restocking evaluation done — {n} alert(s).")


# ── 5. Full pipeline ──────────────────────────────────────────────────────────

def init_forecast_service(db: Session):
    seed_demand_history(db)
    for cat in CATEGORY_PARAMS:
        generate_forecasts_for_category(db, cat)
    evaluate_restock_needs(db)
    print("[forecast] Forecast service ready.")


def retrain(db: Session) -> dict:
    results = {}
    for cat in CATEGORY_PARAMS:
        results[cat] = generate_forecasts_for_category(db, cat)
    evaluate_restock_needs(db)
    return results
