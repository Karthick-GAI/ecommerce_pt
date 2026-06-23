"""
Session Service — port 8008

Responsibilities:
  - Session lifecycle: create, heartbeat, expire, end
  - Event streaming: log interactions from frontend/mobile
  - Session cart: pre-checkout intent cart
  - Customer memory: long-term preference & behavior profiles
  - Context API: compiled AI-ready payloads for LLM injection
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func

from database import engine, Base, SessionLocal
from models import ShoppingSession, CustomerMemory

from routes.session_routes import router as session_router
from routes.event_routes   import router as event_router
from routes.cart_routes    import router as cart_router
from routes.memory_routes  import router as memory_router
from routes.context_routes import router as context_router


# ── Startup / shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables (skips existing)
    Base.metadata.create_all(bind=engine)

    # Expire any sessions that were active when the service last stopped
    db = SessionLocal()
    try:
        ttl_minutes = int(os.getenv("SESSION_TTL_MINUTES", "30"))
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
        expired = (
            db.query(ShoppingSession)
            .filter(
                ShoppingSession.status == "active",
                ShoppingSession.last_activity_at < stale_cutoff,
            )
            .all()
        )
        for s in expired:
            s.status = "expired"
        if expired:
            db.commit()
            print(f"[session_service] Marked {len(expired)} stale session(s) as expired on startup.")
    finally:
        db.close()

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Session Service",
    description="Memory and session management for customer shopping interactions",
    version="1.0.0",
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(session_router)
app.include_router(event_router)
app.include_router(cart_router)
app.include_router(memory_router)
app.include_router(context_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()

    return {
        "service": "session_service",
        "port":    8008,
        "status":  "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
    }


# ── Analytics overview ────────────────────────────────────────────────────────

@app.get("/analytics/overview", tags=["Analytics"])
def analytics_overview():
    """High-level operational metrics for monitoring dashboards."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        day_ago   = now - timedelta(hours=24)
        week_ago  = now - timedelta(days=7)

        total_sessions    = db.query(ShoppingSession).count()
        active_sessions   = db.query(ShoppingSession).filter(ShoppingSession.status == "active").count()
        sessions_24h      = db.query(ShoppingSession).filter(ShoppingSession.started_at >= day_ago).count()
        conversions_24h   = db.query(ShoppingSession).filter(
            ShoppingSession.started_at >= day_ago,
            ShoppingSession.converted == True,
        ).count()
        conversion_rate   = round(conversions_24h / sessions_24h * 100, 1) if sessions_24h else 0

        sessions_7d       = db.query(ShoppingSession).filter(ShoppingSession.started_at >= week_ago).count()
        conversions_7d    = db.query(ShoppingSession).filter(
            ShoppingSession.started_at >= week_ago,
            ShoppingSession.converted == True,
        ).count()

        total_memories    = db.query(CustomerMemory).count()
        stage_counts      = dict(
            db.query(CustomerMemory.lifecycle_stage, func.count(CustomerMemory.id))
            .group_by(CustomerMemory.lifecycle_stage)
            .all()
        )

        return {
            "timestamp": str(now),
            "sessions": {
                "total":          total_sessions,
                "active_now":     active_sessions,
                "last_24h":       sessions_24h,
                "last_7d":        sessions_7d,
                "conversion_rate_24h_pct": conversion_rate,
                "conversions_24h": conversions_24h,
                "conversions_7d":  conversions_7d,
            },
            "memory": {
                "total_profiles":     total_memories,
                "lifecycle_stages":   stage_counts,
            },
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
