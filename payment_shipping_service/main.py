"""
Payment & Shipping Integration Service — port 8009

Integrates with:
  - Razorpay (payment gateway): order creation, signature verification, refunds
  - Shiprocket (shipping aggregator): rate quotes, shipment booking, tracking

Set MOCK_PROVIDERS=false in .env and supply real credentials to use live APIs.
MOCK_PROVIDERS=true (default) simulates all provider calls for local testing.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text

from database import engine, Base, SessionLocal
from models import PaymentOrder, Shipment, WebhookEvent

from routes.payment_routes  import router as payment_router
from routes.shipping_routes import router as shipping_router
from routes.webhook_routes  import router as webhook_router


# ── Startup / shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (skip existing)
    Base.metadata.create_all(bind=engine)

    mock = os.getenv("MOCK_PROVIDERS", "true").lower() == "true"
    print(f"[payment_shipping] Provider mode: {'MOCK' if mock else 'LIVE'}")

    # Expire payment orders whose TTL passed while the service was down
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        stale = (
            db.query(PaymentOrder)
            .filter(
                PaymentOrder.status == "created",
                PaymentOrder.expires_at < cutoff,
            )
            .all()
        )
        for o in stale:
            o.status = "expired"
        if stale:
            db.commit()
            print(f"[payment_shipping] Expired {len(stale)} stale payment order(s) on startup")
    finally:
        db.close()

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Payment & Shipping Integration Service",
    description="Razorpay payment gateway + Shiprocket logistics integration",
    version="1.0.0",
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(payment_router)
app.include_router(shipping_router)
app.include_router(webhook_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()

    mock = os.getenv("MOCK_PROVIDERS", "true").lower() == "true"
    return {
        "service":       "payment_shipping_service",
        "port":          8009,
        "status":        "healthy" if db_ok else "degraded",
        "database":      "connected" if db_ok else "error",
        "provider_mode": "mock" if mock else "live",
        "providers": {
            "payment":  "razorpay",
            "shipping": "shiprocket",
        },
    }


# ── Analytics overview ────────────────────────────────────────────────────────

@app.get("/analytics/overview", tags=["Analytics"])
def analytics_overview():
    """Operational metrics: payment success rates, shipment status distribution."""
    db = SessionLocal()
    try:
        now      = datetime.now(timezone.utc)
        day_ago  = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)

        # Payment metrics
        total_orders        = db.query(PaymentOrder).count()
        paid_orders         = db.query(PaymentOrder).filter(PaymentOrder.status == "paid").count()
        orders_24h          = db.query(PaymentOrder).filter(PaymentOrder.created_at >= day_ago).count()
        paid_24h            = db.query(PaymentOrder).filter(
            PaymentOrder.status == "paid", PaymentOrder.paid_at >= day_ago
        ).count()
        payment_success_rate = round(paid_24h / orders_24h * 100, 1) if orders_24h else 0

        total_revenue = db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM pay_orders WHERE status='paid'")
        ).scalar()
        revenue_24h = db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM pay_orders WHERE status='paid' AND paid_at >= :cutoff"),
            {"cutoff": day_ago},
        ).scalar()

        # Payment status distribution
        pay_status_counts = dict(
            db.query(PaymentOrder.status, func.count(PaymentOrder.id))
            .group_by(PaymentOrder.status)
            .all()
        )

        # Shipment metrics
        total_shipments  = db.query(Shipment).count()
        active_shipments = db.query(Shipment).filter(
            Shipment.status.notin_(["delivered", "cancelled", "returned", "failed"])
        ).count()
        ship_status_counts = dict(
            db.query(Shipment.status, func.count(Shipment.id))
            .group_by(Shipment.status)
            .all()
        )
        delivered_week = db.query(Shipment).filter(
            Shipment.status == "delivered",
            Shipment.actual_delivery >= week_ago,
        ).count()

        # Webhook health
        webhook_errors_24h = db.query(WebhookEvent).filter(
            WebhookEvent.status == "error",
            WebhookEvent.received_at >= day_ago,
        ).count()

        return {
            "timestamp": str(now),
            "payments": {
                "total_orders":           total_orders,
                "paid_orders":            paid_orders,
                "orders_last_24h":        orders_24h,
                "paid_last_24h":          paid_24h,
                "success_rate_24h_pct":   payment_success_rate,
                "total_revenue_inr":      round(float(total_revenue or 0), 2),
                "revenue_last_24h_inr":   round(float(revenue_24h or 0), 2),
                "status_distribution":    pay_status_counts,
            },
            "shipping": {
                "total_shipments":        total_shipments,
                "active_shipments":       active_shipments,
                "delivered_last_7d":      delivered_week,
                "status_distribution":    ship_status_counts,
            },
            "webhooks": {
                "errors_last_24h":        webhook_errors_24h,
            },
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8009, reload=True)
