from datetime import date
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Product, DemandHistory, DemandForecast, RestockingAlert
from forecast_engine import retrain, CATEGORY_PARAMS, evaluate_restock_needs

router = APIRouter(prefix="/forecast", tags=["Demand Forecasting"])


class AckRequest(BaseModel):
    acknowledged_by: str


def _risk(days_until: Optional[int], days_stock: float) -> str:
    if days_until is not None and days_until <= 7:  return "critical"
    if days_until is not None and days_until <= 30: return "warning"
    if days_stock < 14:                             return "warning"
    if days_stock < 30:                             return "low"
    return "healthy"


# ── GET /forecast/summary ─────────────────────────────────────────────────────

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    alerts   = db.query(RestockingAlert).filter(RestockingAlert.status.in_(["open","acknowledged"])).all()
    open_a   = [a for a in alerts if a.status == "open"]
    critical = sum(1 for a in open_a if a.severity == "critical")
    warning  = sum(1 for a in open_a if a.severity == "warning")

    last_gen = db.query(func.max(DemandForecast.generated_at)).scalar()

    metrics_rows = (db.query(DemandForecast.category, DemandForecast.rmse)
                      .filter(DemandForecast.rmse.isnot(None))
                      .distinct(DemandForecast.category).all())

    return {
        "categories_tracked":  len(CATEGORY_PARAMS),
        "categories_at_risk":  len(open_a),
        "open_critical":       critical,
        "open_warning":        warning,
        "stockout_within_7d":  sum(1 for a in open_a if a.days_until_stockout and a.days_until_stockout <= 7),
        "stockout_within_30d": sum(1 for a in open_a if a.days_until_stockout and a.days_until_stockout <= 30),
        "last_trained_at":     str(last_gen) if last_gen else None,
        "model_metrics":       [{"category": r.category, "rmse": round(r.rmse, 3)} for r in metrics_rows],
    }


# ── GET /forecast/categories ──────────────────────────────────────────────────

@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    today   = date.today()
    results = []
    for cat in sorted(CATEGORY_PARAMS.keys()):
        stock = int(db.query(func.sum(Product.inventory_count))
                      .filter(Product.category == cat, Product.is_active == True)
                      .scalar() or 0)

        forecasts = (db.query(DemandForecast)
                       .filter(DemandForecast.category == cat,
                               DemandForecast.forecast_date > today)
                       .order_by(DemandForecast.forecast_date).limit(30).all())
        if not forecasts:
            continue

        daily      = [f.predicted_units for f in forecasts]
        avg_daily  = sum(daily) / len(daily)
        total_30d  = sum(daily)
        days_stock = stock / avg_daily if avg_daily > 0 else 999.0

        alert = db.query(RestockingAlert).filter(
            RestockingAlert.category == cat,
            RestockingAlert.status   == "open"
        ).first()

        trend = "stable"
        if len(daily) >= 14:
            f7, l7 = sum(daily[:7]) / 7, sum(daily[-7:]) / 7
            if l7 > f7 * 1.05:    trend = "increasing"
            elif l7 < f7 * 0.95:  trend = "decreasing"

        results.append({
            "category":            cat,
            "current_stock":       stock,
            "avg_daily_demand":    round(avg_daily, 1),
            "forecast_30d_units":  int(round(total_30d)),
            "days_of_stock":       round(min(days_stock, 999.0), 1),
            "days_until_stockout": alert.days_until_stockout if alert else None,
            "recommended_reorder": alert.recommended_reorder_qty if alert else 0,
            "risk_level":          alert.severity if alert else _risk(None, days_stock),
            "trend":               trend,
            "has_alert":           alert is not None,
        })

    return {"total": len(results), "categories": results}


# ── GET /forecast/category/{category} ────────────────────────────────────────

@router.get("/category/{category}")
def category_detail(category: str, db: Session = Depends(get_db)):
    today = date.today()

    history = (db.query(DemandHistory)
                 .filter(DemandHistory.category == category)
                 .order_by(DemandHistory.date).all())
    if not history:
        raise HTTPException(404, f"No data for category '{category}'")

    forecasts = (db.query(DemandForecast)
                   .filter(DemandForecast.category == category,
                           DemandForecast.forecast_date > today)
                   .order_by(DemandForecast.forecast_date).limit(30).all())

    stock = int(db.query(func.sum(Product.inventory_count))
                  .filter(Product.category == category, Product.is_active == True)
                  .scalar() or 0)

    alert = db.query(RestockingAlert).filter(
        RestockingAlert.category == category,
        RestockingAlert.status   == "open"
    ).first()

    # First date when cumulative forecast exceeds current stock
    stockout_date = None
    if forecasts:
        cum = 0.0
        for f in forecasts:
            cum += f.predicted_units
            if cum >= stock:
                stockout_date = str(f.forecast_date)
                break

    rmse = forecasts[0].rmse if forecasts else None

    return {
        "category":      category,
        "current_stock": stock,
        "model_rmse":    round(rmse, 3) if rmse else None,
        "stockout_date": stockout_date,
        "restock_alert": {
            "severity":            alert.severity,
            "days_until_stockout": alert.days_until_stockout,
            "recommended_reorder": alert.recommended_reorder_qty,
            "avg_daily_demand":    alert.avg_daily_demand,
        } if alert else None,
        "history": [
            {"date": str(h.date), "units_sold": h.units_sold, "revenue": round(h.revenue, 2)}
            for h in history
        ],
        "forecast": [
            {
                "date":            str(f.forecast_date),
                "predicted_units": f.predicted_units,
                "lower_bound":     f.lower_bound,
                "upper_bound":     f.upper_bound,
                "confidence":      f.confidence_score,
            } for f in forecasts
        ],
    }


# ── GET /forecast/restock-alerts ─────────────────────────────────────────────

@router.get("/restock-alerts")
def restock_alerts(
    status:   Optional[Literal["open", "acknowledged"]] = None,
    severity: Optional[Literal["critical", "warning"]]  = None,
    db: Session = Depends(get_db),
):
    q = db.query(RestockingAlert)
    if status:
        q = q.filter(RestockingAlert.status == status)
    else:
        q = q.filter(RestockingAlert.status.in_(["open", "acknowledged"]))
    if severity:
        q = q.filter(RestockingAlert.severity == severity)

    alerts = q.order_by(
        RestockingAlert.days_until_stockout.asc().nullsfirst(),
        RestockingAlert.triggered_at.desc()
    ).all()
    return {"total": len(alerts), "alerts": [_fmt(a) for a in alerts]}


# ── POST /forecast/restock-alerts/{id}/acknowledge ────────────────────────────

@router.post("/restock-alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, payload: AckRequest, db: Session = Depends(get_db)):
    a = db.query(RestockingAlert).filter(RestockingAlert.id == alert_id).first()
    if not a:
        raise HTTPException(404, "Alert not found")
    from datetime import datetime
    a.status          = "acknowledged"
    a.acknowledged_by = payload.acknowledged_by
    a.acknowledged_at = datetime.utcnow()
    db.commit()
    return {"message": "Alert acknowledged", "alert_id": alert_id}


# ── POST /forecast/train ──────────────────────────────────────────────────────

@router.post("/train")
def train(db: Session = Depends(get_db)):
    metrics = retrain(db)
    trained = {k: v for k, v in metrics.items() if v is not None}
    return {
        "message":    f"Models retrained for {len(trained)} categories",
        "categories": list(trained.keys()),
        "metrics":    trained,
    }


# ── POST /forecast/refresh-alerts ─────────────────────────────────────────────

@router.post("/refresh-alerts")
def refresh_alerts(db: Session = Depends(get_db)):
    evaluate_restock_needs(db)
    n = db.query(RestockingAlert).filter(RestockingAlert.status == "open").count()
    return {"message": f"Alert evaluation complete", "open_alerts": n}


def _fmt(a: RestockingAlert) -> dict:
    return {
        "id":                      a.id,
        "category":                a.category,
        "current_stock":           a.current_stock,
        "avg_daily_demand":        a.avg_daily_demand,
        "forecasted_demand_30d":   a.forecasted_demand_30d,
        "days_until_stockout":     a.days_until_stockout,
        "recommended_reorder_qty": a.recommended_reorder_qty,
        "severity":                a.severity,
        "status":                  a.status,
        "acknowledged_by":         a.acknowledged_by,
        "acknowledged_at":         str(a.acknowledged_at) if a.acknowledged_at else None,
        "triggered_at":            str(a.triggered_at),
    }
