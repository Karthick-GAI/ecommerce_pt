from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import order_routes, cancellation_routes, refund_routes, notification_routes

# Create only the 3 new tables — existing tables are skipped automatically
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Order Management Service",
    version="1.0.0",
    description=(
        "Order placement tracking, status updates, cancellation with auto-refund, "
        "refund workflows (approve / reject), and multi-channel notifications "
        "(email, SMS, push) for all order lifecycle events."
    ),
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(order_routes.router)
app.include_router(cancellation_routes.router)
app.include_router(refund_routes.router)
app.include_router(notification_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import CheckoutOrder, Refund, Notification, OrderStatusHistory
    db = SessionLocal()
    try:
        return {
            "status":                "ok",
            "total_orders_tracked":  db.query(
                                         func.count(func.distinct(OrderStatusHistory.order_id))
                                     ).scalar() or 0,
            "pending_refunds":       db.query(Refund).filter(Refund.status == "pending").count(),
            "total_notifications":   db.query(Notification).count(),
            "unread_notifications":  db.query(Notification).filter(
                                         Notification.is_read == False
                                     ).count(),
        }
    finally:
        db.close()
