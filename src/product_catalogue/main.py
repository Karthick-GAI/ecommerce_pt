# main.py — Product Catalogue API
#
# SETUP:
#   1. python3 -m pip install -r requirements.txt --break-system-packages
#   2. python3 seed_data.py              # seed 100 products with embeddings
#   3. python3 -m uvicorn main:app --reload --port 8001
#   4. Open http://localhost:8001/docs

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from dotenv import load_dotenv
import httpx

load_dotenv()

from database import engine, Base
from routes import product_routes, search_routes, review_routes, category_routes, enrichment_routes

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
app.include_router(enrichment_routes.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/imgproxy/{w}/{h}/{keywords}", tags=["System"], include_in_schema=False)
async def image_proxy(w: int, h: int, keywords: str, lock: int = 0):
    """Fetch loremflickr image server-side (follows redirects) so the browser
    never hits external CDNs directly — fixes images in firewalled environments."""
    url = f"https://loremflickr.com/{w}/{h}/{keywords}?lock={lock}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
            r = await client.get(url)
        content_type = r.headers.get("content-type", "image/jpeg")
        return Response(content=r.content, media_type=content_type)
    except Exception:
        return Response(status_code=502)


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
