from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import chat_routes, session_routes

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    required = [
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[WARNING] Missing env vars: {missing}. Chat endpoints will fail.")
    else:
        print(f"[startup] Azure OpenAI ready — deployment: {os.environ['AZURE_OPENAI_DEPLOYMENT']}")
    yield


app = FastAPI(
    title="Tool-Calling Agent",
    version="1.0.0",
    description=(
        "AI agent with tool-calling support for order lookup, inventory checks, "
        "and personalised recommendations. Uses Azure OpenAI function calling with "
        "10 tools across order, inventory, and recommendation domains. Port 8007."
    ),
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(chat_routes.router)
app.include_router(session_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import AgentSession, AgentMessage
    import os
    db = SessionLocal()
    try:
        return {
            "status":           "ok",
            "azure_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", "not set"),
            "total_sessions":   db.query(AgentSession).count(),
            "total_messages":   db.query(AgentMessage).count(),
            "tools_available":  10,
        }
    finally:
        db.close()


@app.get("/tools", tags=["System"])
def list_tools():
    """List all available tools with their descriptions."""
    from tools.registry import TOOL_SCHEMAS
    return {
        "count": len(TOOL_SCHEMAS),
        "tools": [
            {
                "name":        t["function"]["name"],
                "description": t["function"]["description"],
                "parameters":  list(t["function"]["parameters"].get("properties", {}).keys()),
                "required":    t["function"]["parameters"].get("required", []),
            }
            for t in TOOL_SCHEMAS
        ],
    }
