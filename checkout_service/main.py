from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import cart_routes, checkout_routes, order_routes

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Shopping Cart & Checkout Service",
    version="1.0.0",
    description="Cart management, checkout workflow, and payment processing (Card / Wallet / UPI)",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(cart_routes.router)
app.include_router(checkout_routes.router)
app.include_router(order_routes.router)


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
            "status":        "ok",
            "active_carts":  db.query(Cart).filter(Cart.status == "active").count(),
            "total_orders":  db.query(Order).count(),
            "payment_methods": ["card", "wallet", "upi"],
        }
    finally:
        db.close()
