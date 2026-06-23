import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import cart_routes, checkout_routes, order_routes
from nfr.structured_logging import setup_logging, RequestLoggingMiddleware
from nfr.metrics import instrument_app

setup_logging(service_name="checkout_service")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Shopping Cart & Checkout Service",
    version="2.0.0",
    description=(
        "Cart management, checkout workflow, and payment processing (Card / Wallet / UPI).\n\n"
        "**NFR highlights**: idempotency keys on checkout + pay endpoints, "
        "structured logging, Prometheus metrics."
    ),
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware, service_name="checkout_service")

app.include_router(cart_routes.router)
app.include_router(checkout_routes.router)
app.include_router(order_routes.router)

instrument_app(app, service_name="checkout_service")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import Cart, Order
    db = SessionLocal()
    try:
        return {
            "status":          "ok",
            "service":         "checkout_service",
            "active_carts":    db.query(Cart).filter(Cart.status == "active").count(),
            "total_orders":    db.query(Order).count(),
            "payment_methods": ["card", "wallet", "upi"],
        }
    finally:
        db.close()
