# routes/search_routes.py — Semantic + keyword hybrid search
#
# TWO MODES:
#
# GET /search/keyword?q=laptop&category=Electronics&price_max=50000
#   → SQL ILIKE across name/brand/description/category/tags + filters + pagination
#
# GET /search/semantic?q=lightweight laptop for college under 50000
#   → GPT-5.4-mini parses the query into structured filters
#   → text-embedding-3-small embeds the cleaned keyword string
#   → pgvector cosine distance finds nearest products in PostgreSQL
#   → SQL filters (price, category, brand) applied in the same query
#   → Results ranked by similarity score

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, cast, String
from database import get_db
from models import Product
from schemas import ProductResponse, SearchResponse
from embeddings import embed_text, parse_nl_query
from vector_store import semantic_search, indexed_count

router = APIRouter(prefix="/search", tags=["Search"])


# ── KEYWORD SEARCH ────────────────────────────────────────────────────────────

@router.get("/keyword", response_model=SearchResponse)
def keyword_search(
    q:          str            = Query(..., min_length=1),
    category:   Optional[str] = None,
    brand:      Optional[str] = None,
    price_min:  Optional[float] = None,
    price_max:  Optional[float] = None,
    rating_min: Optional[float] = Query(None, ge=1, le=5),
    in_stock:   bool = False,
    sort_by:    str  = Query("relevance", enum=["relevance", "price_asc", "price_desc", "rating", "newest"]),
    page:       int  = Query(1, ge=1),
    limit:      int  = Query(20, ge=1, le=100),
    db:         Session = Depends(get_db),
):
    """Fast SQL ILIKE search across name, brand, description, category, and tags."""
    term = f"%{q}%"
    query = db.query(Product).filter(
        Product.is_active == True,
        or_(
            Product.name.ilike(term),
            Product.brand.ilike(term),
            Product.description.ilike(term),
            Product.category.ilike(term),
            Product.subcategory.ilike(term),
            cast(Product.tags, String).ilike(term),
        ),
    )

    if category:    query = query.filter(Product.category == category)
    if brand:       query = query.filter(Product.brand == brand)
    if price_min:   query = query.filter(Product.price * (1 - Product.discount_pct / 100) >= price_min)
    if price_max:   query = query.filter(Product.price * (1 - Product.discount_pct / 100) <= price_max)
    if rating_min:  query = query.filter(Product.rating_avg >= rating_min)
    if in_stock:    query = query.filter(Product.inventory_count > 0)

    ORDER = {
        "relevance":  Product.rating_count.desc(),
        "price_asc":  Product.price.asc(),
        "price_desc": Product.price.desc(),
        "rating":     Product.rating_avg.desc(),
        "newest":     Product.created_at.desc(),
    }
    total    = query.count()
    products = query.order_by(ORDER[sort_by]).offset((page - 1) * limit).limit(limit).all()

    return SearchResponse(
        query=q,
        total=total,
        page=page,
        pages=max(1, -(-total // limit)),
        results=[ProductResponse.from_orm_product(p) for p in products],
    )


# ── SEMANTIC / NLP SEARCH ─────────────────────────────────────────────────────

@router.get("/semantic", response_model=SearchResponse)
def semantic_search_route(
    q:     str     = Query(..., min_length=1, description="Natural language query"),
    page:  int     = Query(1, ge=1),
    limit: int     = Query(20, ge=1, le=100),
    db:    Session = Depends(get_db),
):
    """
    Natural-language search powered by Azure OpenAI + pgvector.

    Flow:
      1. GPT-5.4-mini extracts structured filters from the query
      2. text-embedding-3-small embeds the cleaned keyword string
      3. pgvector finds nearest products by cosine similarity
         (SQL filters for price/category applied in the same query)
      4. Results returned sorted by similarity score
    """
    if indexed_count(db) == 0:
        raise HTTPException(
            status_code=503,
            detail="Search index is empty — run python3 seed_data.py first.",
        )

    parsed   = parse_nl_query(q)
    keywords = parsed.get("keywords") or q

    query_embedding = embed_text(keywords)

    results = semantic_search(
        db=db,
        query_embedding=query_embedding,
        n_results=60,
        category=parsed.get("category"),
        brand=parsed.get("brand"),
        max_price=parsed.get("max_price"),
        min_price=parsed.get("min_price"),
    )

    total = len(results)
    start = (page - 1) * limit
    paged = results[start: start + limit]

    return SearchResponse(
        query=q,
        total=total,
        page=page,
        pages=max(1, -(-total // limit)),
        results=[ProductResponse.from_orm_product(p) for p, _ in paged],
        parsed_filters=parsed,
    )
