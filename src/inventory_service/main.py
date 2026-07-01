from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import inventory_routes, alert_routes, alert_rule_routes, forecast_routes

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import SessionLocal
    from alert_engine import seed_default_rules, run_initial_alert_scan
    db = SessionLocal()
    try:
        seed_default_rules(db)
        run_initial_alert_scan(db)
        from forecast_engine import init_forecast_service
        init_forecast_service(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Inventory Service",
    version="1.0.0",
    description=(
        "Real-time inventory tracking with full movement audit trail, "
        "configurable low-stock alert rules, Server-Sent Events (SSE) stream, "
        "and an ops dashboard. Port 8005."
    ),
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(inventory_routes.router)
app.include_router(alert_routes.router)
app.include_router(alert_rule_routes.router)
app.include_router(forecast_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import Product, InventoryMovement, Alert, AlertRule
    db = SessionLocal()
    try:
        out_of_stock = db.query(Product).filter(
            Product.is_active == True, Product.inventory_count == 0
        ).count()
        return {
            "status":           "ok",
            "total_products":   db.query(Product).filter(Product.is_active == True).count(),
            "out_of_stock":     out_of_stock,
            "open_alerts":      db.query(Alert).filter(Alert.status == "open").count(),
            "total_movements":  db.query(InventoryMovement).count(),
            "active_rules":     db.query(AlertRule).filter(AlertRule.is_active == True).count(),
        }
    finally:
        db.close()
