# Multi-Agent Orchestration System — Port 8011
#
# SETUP:
#   1. pip install -r requirements.txt --break-system-packages
#   2. python -m uvicorn main:app --reload --port 8011
#   3. Open http://localhost:8011/docs
#
# AGENTS:
#   customer_support   — order issues, refunds, complaints, FAQs
#   recommendation     — product discovery, personalised suggestions
#   fulfillment        — checkout, payment, tracking, returns
#   inventory_planning — demand forecasting, restock (ops team)

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from database import engine, Base, SessionLocal
from models import (
    MASSession, MASMessage, MASHandoff,
    SupportTicket, InventoryForecast, AgentAnalyticsLog, RCAReport,
)
from routes.chat_routes       import router as chat_router
from routes.agent_routes      import router as agent_router
from routes.analytics_routes  import router as analytics_router
from routes.rerouting_routes  import router as rerouting_router
from routes.rca_routes        import router as rca_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        logging.getLogger(__name__).info("Database connection verified.")
    except Exception as e:
        logging.getLogger(__name__).error("Database connection failed: %s", e)
    finally:
        db.close()

    yield


app = FastAPI(
    title="Multi-Agent Orchestration System",
    description=(
        "AI-powered multi-agent platform for e-commerce: Customer Support, "
        "Product Recommendations, Order Fulfillment, and Inventory Planning. "
        "Each agent has dedicated tools, memory, and a GPT-backed reasoning loop. "
        "The orchestrator classifies intent and routes to the right specialist."
    ),
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(agent_router)
app.include_router(analytics_router)
app.include_router(rerouting_router)
app.include_router(rca_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health(db=None):
    from database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()

    from tools.registry import AGENT_TOOLS
    return {
        "service":    "multi-agent-orchestration",
        "status":     "healthy" if db_ok else "degraded",
        "port":       8011,
        "database":   "connected" if db_ok else "unreachable",
        "agents": {
            agent: len(tools)
            for agent, tools in AGENT_TOOLS.items()
        },
        "total_tools": sum(len(t) for t in AGENT_TOOLS.values()),
        "endpoints": {
            "orchestrated_chat":  "POST /chat",
            "streaming_chat":     "POST /chat/stream",
            "direct_agent_chat":  "POST /agents/{agent_type}/chat",
            "agent_tools":        "GET  /agents/{agent_type}/tools",
            "analytics":          "GET  /analytics/overview",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8011, reload=True)
