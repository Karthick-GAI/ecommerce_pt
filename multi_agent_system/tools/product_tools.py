"""Product search and detail tools for the Recommendation Agent."""
import os
import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import AzureOpenAI
from dotenv import load_dotenv
from tools.shared_models import Product

load_dotenv()

_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
)
_EMBED_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_SMALL", "text-embedding-3-small")


def _embed(text_input: str) -> list:
    resp = _client.embeddings.create(model=_EMBED_MODEL, input=text_input)
    return resp.data[0].embedding


def _product_to_dict(p: Product) -> dict:
    effective_price = round(p.price * (1 - (p.discount_pct or 0) / 100), 2)
    return {
        "product_id":      p.id,
        "name":            p.name,
        "brand":           p.brand,
        "category":        p.category,
        "subcategory":     p.subcategory,
        "price":           p.price,
        "discount_pct":    p.discount_pct or 0,
        "effective_price": effective_price,
        "rating":          round(p.rating_avg or 0, 1),
        "review_count":    p.rating_count or 0,
        "in_stock":        (p.inventory_count or 0) > 0,
        "stock_count":     p.inventory_count or 0,
        "image":           p.primary_image,
        "specifications":  p.specifications,
    }


def search_products(
    query: str,
    db: Session,
    category: str = None,
    brand: str = None,
    min_price: float = None,
    max_price: float = None,
    in_stock_only: bool = False,
    limit: int = 8,
) -> str:
    try:
        vector = _embed(query)
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"

        filters = ["p.is_active = true"]
        params: dict = {"limit": min(limit, 20)}

        if category:
            filters.append("LOWER(p.category) = LOWER(:category)")
            params["category"] = category
        if brand:
            filters.append("LOWER(p.brand) = LOWER(:brand)")
            params["brand"] = brand
        if min_price is not None:
            filters.append("p.price >= :min_price")
            params["min_price"] = min_price
        if max_price is not None:
            filters.append("p.price <= :max_price")
            params["max_price"] = max_price
        if in_stock_only:
            filters.append("p.inventory_count > 0")

        where_clause = " AND ".join(filters)

        sql = text(f"""
            SELECT p.id, p.name, p.brand, p.category, p.subcategory,
                   p.price, p.discount_pct, p.inventory_count,
                   p.rating_avg, p.rating_count, p.primary_image,
                   p.specifications,
                   1 - (p.embedding <=> '{vector_str}'::vector) AS similarity
            FROM products p
            WHERE {where_clause} AND p.embedding IS NOT NULL
            ORDER BY p.embedding <=> '{vector_str}'::vector
            LIMIT :limit
        """)

        rows = db.execute(sql, params).fetchall()
        products = []
        for r in rows:
            ep = round(r.price * (1 - (r.discount_pct or 0) / 100), 2)
            products.append({
                "product_id":      r.id,
                "name":            r.name,
                "brand":           r.brand,
                "category":        r.category,
                "price":           r.price,
                "discount_pct":    r.discount_pct or 0,
                "effective_price": ep,
                "rating":          round(r.rating_avg or 0, 1),
                "in_stock":        (r.inventory_count or 0) > 0,
                "image":           r.primary_image,
                "specifications":  r.specifications,
                "similarity":      round(r.similarity, 3),
            })
        return json.dumps({"products": products, "count": len(products), "query": query})

    except Exception as e:
        # Fallback to keyword search
        q_filter = f"%{query}%"
        base = db.query(Product).filter(
            Product.is_active == True,
            (Product.name.ilike(q_filter)) | (Product.description.ilike(q_filter)) | (Product.brand.ilike(q_filter)),
        )
        if category:
            base = base.filter(Product.category.ilike(f"%{category}%"))
        if min_price:
            base = base.filter(Product.price >= min_price)
        if max_price:
            base = base.filter(Product.price <= max_price)
        if in_stock_only:
            base = base.filter(Product.inventory_count > 0)

        products = base.limit(min(limit, 20)).all()
        return json.dumps({"products": [_product_to_dict(p) for p in products], "count": len(products)})


def get_product_detail(product_id: str, db: Session) -> str:
    p = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not p:
        return json.dumps({"error": f"Product {product_id} not found."})

    d = _product_to_dict(p)
    d["description"] = p.description
    d["tags"] = p.tags
    return json.dumps(d)


def get_similar_products(product_id: str, db: Session, limit: int = 6) -> str:
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        return json.dumps({"error": f"Product {product_id} not found."})

    if p.embedding is None:
        # fallback: same category
        similars = (
            db.query(Product)
            .filter(Product.category == p.category, Product.id != product_id, Product.is_active == True)
            .limit(limit)
            .all()
        )
        return json.dumps({"products": [_product_to_dict(s) for s in similars]})

    sql = text("""
        SELECT id, name, brand, category, price, discount_pct,
               inventory_count, rating_avg, rating_count, primary_image, specifications
        FROM products
        WHERE id != :pid AND is_active = true AND embedding IS NOT NULL
        ORDER BY embedding <=> (SELECT embedding FROM products WHERE id = :pid)
        LIMIT :limit
    """)
    rows = db.execute(sql, {"pid": product_id, "limit": min(limit, 20)}).fetchall()
    products = []
    for r in rows:
        ep = round(r.price * (1 - (r.discount_pct or 0) / 100), 2)
        products.append({
            "product_id":      r.id,
            "name":            r.name,
            "brand":           r.brand,
            "category":        r.category,
            "price":           r.price,
            "effective_price": ep,
            "discount_pct":    r.discount_pct or 0,
            "rating":          round(r.rating_avg or 0, 1),
            "in_stock":        (r.inventory_count or 0) > 0,
            "image":           r.primary_image,
        })
    return json.dumps({"products": products, "base_product": p.name})


def compare_products(product_ids: list, db: Session) -> str:
    if len(product_ids) > 4:
        product_ids = product_ids[:4]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    if not products:
        return json.dumps({"error": "No products found for the given IDs."})

    return json.dumps({
        "comparison": [_product_to_dict(p) for p in products],
        "count": len(products),
    })


def get_products_by_category(category: str, db: Session, subcategory: str = None, limit: int = 12) -> str:
    q = db.query(Product).filter(
        Product.is_active == True,
        Product.category.ilike(f"%{category}%"),
    )
    if subcategory:
        q = q.filter(Product.subcategory.ilike(f"%{subcategory}%"))
    products = q.order_by(Product.rating_avg.desc()).limit(min(limit, 30)).all()
    return json.dumps({
        "products": [_product_to_dict(p) for p in products],
        "category": category,
        "count": len(products),
    })
