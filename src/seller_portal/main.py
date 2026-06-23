"""
Seller Portal — B2B Merchant Service  (port 8011)

Covers NFR dimension: B2B / B2C
  - Separate service for sellers/merchants (isolated from the consumer-facing services)
  - KYC-gated account activation (pending_verification → active)
  - Product catalogue management with admin approval workflow
  - Order fulfillment dashboard with payout tracking
  - Rate-limited auth, structured logging, Prometheus metrics

TO RUN:
  pip install -r requirements.txt
  uvicorn main:app --reload --port 8011

API DOCS:
  http://localhost:8011/docs
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database import engine, Base
from routes import auth_routes, catalogue_routes, order_routes, profile_routes
from nfr.structured_logging import setup_logging, RequestLoggingMiddleware
from nfr.metrics import instrument_app

setup_logging(service_name="seller_portal")

Base.metadata.create_all(bind=engine)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="E-Commerce — Seller Portal (B2B)",
    description=(
        "Merchant portal for product catalogue management and order fulfillment.\n\n"
        "**B2B flows**:\n"
        "1. Seller registers → admin approves (KYC)\n"
        "2. Seller adds products → submit for review → admin approves\n"
        "3. Seller monitors orders and updates fulfillment status\n"
        "4. Seller views payout dashboard\n\n"
        "**NFR highlights**: rate-limited auth, structured logging, Prometheus /metrics."
    ),
    version="1.0.0",
    redirect_slashes=False,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware, service_name="seller_portal")

app.include_router(auth_routes.router)
app.include_router(catalogue_routes.router)
app.include_router(order_routes.router)
app.include_router(profile_routes.router)

instrument_app(app, service_name="seller_portal")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import Seller, SellerProduct, SellerOrder
    from nfr.circuit_breaker import all_statuses
    db = SessionLocal()
    try:
        return {
            "status":           "ok",
            "service":          "seller_portal",
            "port":             8011,
            "total_sellers":    db.query(Seller).count(),
            "active_sellers":   db.query(Seller).filter(Seller.is_active == True).count(),
            "total_products":   db.query(SellerProduct).count(),
            "total_orders":     db.query(SellerOrder).count(),
            "circuit_breakers": all_statuses(),
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8011, reload=True)
