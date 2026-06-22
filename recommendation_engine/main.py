from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import recommendation_routes, interaction_routes, profile_routes

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm: compute profiles for top buyers so first requests are fast
    from database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        top_customers = db.execute(text("""
            SELECT user_id, COUNT(*) AS order_count
            FROM orders
            GROUP BY user_id
            ORDER BY order_count DESC
            LIMIT 20
        """)).fetchall()

        from routes.profile_routes import _compute_and_save
        computed = 0
        for row in top_customers:
            try:
                _compute_and_save(db, row.user_id)
                computed += 1
            except Exception:
                pass
        print(f"[startup] Pre-warmed {computed} user preference profiles")
    finally:
        db.close()
    yield


app = FastAPI(
    title="Recommendation Engine",
    version="1.0.0",
    description=(
        "Personalised product discovery using hybrid collaborative filtering "
        "(item-based & user-based), pgvector semantic similarity, trending signals, "
        "and adaptive homepage feeds. Port 8006."
    ),
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(recommendation_routes.router)
app.include_router(interaction_routes.router)
app.include_router(profile_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import Product, RecInteraction, UserPreferenceProfile, BrowsingEvent
    from sqlalchemy import text
    db = SessionLocal()
    try:
        order_count = db.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        return {
            "status":            "ok",
            "total_products":    db.query(Product).filter(Product.is_active == True).count(),
            "dataset_orders":    int(order_count or 0),
            "browsing_events":   db.query(BrowsingEvent).count(),
            "user_profiles":     db.query(UserPreferenceProfile).count(),
            "rec_interactions":  db.query(RecInteraction).count(),
        }
    finally:
        db.close()
