# main.py — FastAPI application entry point
#
# NFR COVERAGE (added):
#   Performance:    /metrics endpoint (Prometheus)
#   Security:       Rate limiting on /auth/* via slowapi (prevents brute-force)
#   Observability:  Structured JSON logging + X-Trace-ID on every response
#   Compliance:     GDPR endpoints live in user_routes (/users/me/data-export, /gdpr-erasure)
#   Availability:   Circuit-breaker status surfaced in /health
#
# TO RUN:
#   pip install -r requirements.txt
#   uvicorn main:app --reload --port 8000

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))   # allow `from nfr.*`

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database import engine, Base
from routes import auth_routes, user_routes, address_routes, payment_routes
from nfr.structured_logging import setup_logging, RequestLoggingMiddleware
from nfr.metrics import instrument_app

# ── Structured logging ────────────────────────────────────────────────────────
setup_logging(service_name="user_management")

# Create all tables on startup
Base.metadata.create_all(bind=engine)

# ── Rate limiter (slowapi) ────────────────────────────────────────────────────
# Uses the client IP as the key. Limits are declared per-route in auth_routes.py.
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="E-Commerce — User Management API",
    description=(
        "Handles user registration, login (JWT), profile management, "
        "address book, saved payment methods, and GDPR data rights.\n\n"
        "**NFR highlights**: rate-limited auth, structured logging, Prometheus metrics, GDPR."
    ),
    version="2.0.0",
)

# Attach limiter so route decorators can reference it via request.app.state.limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Structured request/response logging (emits JSON + injects X-Trace-ID header)
app.add_middleware(RequestLoggingMiddleware, service_name="user_management")

# Register routers
app.include_router(auth_routes.router)     # /auth/*
app.include_router(user_routes.router)     # /users/me
app.include_router(address_routes.router)  # /users/me/addresses
app.include_router(payment_routes.router)  # /users/me/payment-methods

# Prometheus /metrics endpoint
instrument_app(app, service_name="user_management")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health_check():
    from nfr.circuit_breaker import all_statuses
    return {
        "status":          "ok",
        "service":         "user_management",
        "circuit_breakers": all_statuses(),
    }
