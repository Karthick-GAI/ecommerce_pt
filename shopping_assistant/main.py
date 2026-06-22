from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import chat_routes

# Creates chat_sessions and chat_messages tables.
# The existing products table is untouched (read-only for this service).
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="RAG Shopping Assistant",
    version="1.0.0",
    description="AI-powered shopping assistant using Retrieval-Augmented Generation (pgvector + GPT-5.4-mini)",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health():
    from database import SessionLocal
    from models import Product, ChatSession
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).count()
        sessions = db.query(ChatSession).count()
    finally:
        db.close()
    return {
        "status": "ok",
        "indexed_products": products,
        "active_sessions": sessions,
        "rag_backend": "pgvector + gpt-5.4-mini",
    }
