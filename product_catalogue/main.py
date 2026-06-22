# main.py — Product Catalogue API
#
# SETUP:
#   1. python3 -m pip install -r requirements.txt --break-system-packages
#   2. python3 seed_data.py              # seed 100 products with embeddings
#   3. python3 -m uvicorn main:app --reload --port 8001
#   4. Open http://localhost:8001/docs

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
from routes import product_routes, search_routes, review_routes, category_routes

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="E-Commerce — Product Catalogue API",
    description=(
        "Product search, filtering, detail pages, reviews, and ratings. "
        "Semantic NLP search powered by Azure OpenAI + pgvector on PostgreSQL."
    ),
    version="2.0.0",
    redirect_slashes=False,     # prevents 307 redirects on /categories vs /categories/
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(product_routes.router)
app.include_router(search_routes.router)
app.include_router(review_routes.router)
app.include_router(category_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health(db=None):
    from database import SessionLocal
    from vector_store import indexed_count
    db = SessionLocal()
    try:
        count = indexed_count(db)
    finally:
        db.close()
    return {"status": "ok", "indexed_products": count, "vector_store": "pgvector"}
