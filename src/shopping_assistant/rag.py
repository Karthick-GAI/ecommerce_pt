import logging
import os
from typing import List, Optional, Tuple

from openai import AzureOpenAI, APITimeoutError, APIConnectionError, RateLimitError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)

GPT_MODEL = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")

# Azure OpenAI call timeout — triggers local fallback if exceeded
_AZURE_TIMEOUT_SECS = float(os.getenv("AZURE_TIMEOUT_SECS", "5.0"))


# ── Step 1: Retrieve ──────────────────────────────────────────────────────────

def retrieve_products(db, query: str, n: int = 8):
    """
    Parse the natural-language query → embed → pgvector cosine search.
    Returns (results, parsed_filters, fallback_mode).
      results        = list of (Product ORM object, similarity_score)
      parsed_filters = dict extracted by GPT (category, brand, price, keywords)
      fallback_mode  = "vector" | "keyword" — indicates which path was used

    Graceful degradation:
      - Primary: full semantic pipeline (parse → embed → pgvector)
      - Fallback: keyword search if embedding fails (vector indexing unavailable)
    """
    from embeddings import embed_text, parse_nl_query
    from vector_store import semantic_search

    # Try full semantic pipeline
    try:
        parsed   = parse_nl_query(query)
        keywords = parsed.get("keywords") or query
        embedding = embed_text(keywords)

        results = semantic_search(
            db=db,
            query_embedding=embedding,
            n_results=n,
            category=parsed.get("category"),
            brand=parsed.get("brand"),
            max_price=parsed.get("max_price"),
            min_price=parsed.get("min_price"),
        )
        return results, parsed, "vector"

    except Exception as embed_err:
        # Graceful degradation: vector indexing failed → keyword search fallback
        logger.warning(
            "retrieve_products: semantic pipeline failed (%s) — falling back to keyword search",
            embed_err,
        )
        results = _keyword_search_fallback(db, query, n)
        return results, {"keywords": query}, "keyword"


def _keyword_search_fallback(db, query: str, n: int):
    """Simple ILIKE keyword search used when vector pipeline is unavailable."""
    from models import Product

    terms = query.lower().split()[:4]   # use first 4 words to avoid over-filtering
    q = db.query(Product).filter(Product.is_active == True)
    for term in terms:
        q = q.filter(Product.name.ilike(f"%{term}%"))
    products = q.limit(n).all()

    if not products:
        # Broaden: search only on first keyword
        products = (
            db.query(Product)
            .filter(Product.is_active == True)
            .filter(Product.name.ilike(f"%{terms[0]}%"))
            .limit(n)
            .all()
        )

    # Wrap in (product, score) tuples to match semantic_search return type
    return [(p, 0.0) for p in products]


# ── Step 1b: Fetch purchase history ──────────────────────────────────────────

def fetch_purchase_history(db, user_id: Optional[str]) -> Optional[str]:
    """
    Return a formatted purchase-history string for the given user, or None.

    Process:
      1. Query last 5 orders for user_id, ordered by created_at DESC.
      2. Collect all unique product_ids from cart_activity JSONB items.
      3. JOIN products table to resolve names.
      4. Return a structured text block injected into the GPT system prompt.
    """
    if not user_id:
        return None

    try:
        from models import Order, Product

        orders = (
            db.query(Order)
            .filter(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(5)
            .all()
        )
        if not orders:
            return None

        # Collect product_ids from cart_activity across all recent orders
        product_ids: list[str] = []
        for order in orders:
            items = order.cart_activity or []
            for item in items:
                pid = item.get("product_id")
                if pid and pid not in product_ids:
                    product_ids.append(pid)

        if not product_ids:
            return None

        # Resolve names in one query
        products = (
            db.query(Product.id, Product.name, Product.category)
            .filter(Product.id.in_(product_ids))
            .all()
        )
        name_map = {p.id: (p.name, p.category) for p in products}

        lines = ["USER PURCHASE HISTORY (recent purchases — use to personalise recommendations):\n"]
        for order in orders:
            items = order.cart_activity or []
            for item in items:
                pid = item.get("product_id")
                qty = item.get("quantity", 1)
                if pid in name_map:
                    pname, pcat = name_map[pid]
                    lines.append(f"  - {pname} (Category: {pcat}, Qty: {qty})")

        return "\n".join(lines)

    except Exception as exc:
        logger.warning("fetch_purchase_history: failed for user %s: %s", user_id, exc)
        return None


# ── Step 2: Build context ─────────────────────────────────────────────────────

def build_context(results: List[Tuple]) -> str:
    """
    Format retrieved products as structured text context that GPT will read.
    Includes: name, brand, category, effective price, discount, rating, stock, top specs.
    """
    if not results:
        return "No relevant products found in the current catalogue."

    lines = ["RELEVANT PRODUCTS FROM THE CATALOGUE:\n"]
    for i, (p, score) in enumerate(results, 1):
        eff_price    = round(p.price * (1 - p.discount_pct / 100), 2)
        stock        = (
            f"In Stock ({p.inventory_count} units)"
            if p.inventory_count > 0
            else "Out of Stock"
        )
        discount_note = f" (after {p.discount_pct:.0f}% discount)" if p.discount_pct > 0 else ""

        specs_line = ""
        if p.specifications:
            top = dict(list(p.specifications.items())[:4])
            specs_line = "\n   Specs: " + " | ".join(f"{k}: {v}" for k, v in top.items())

        tags_line = ""
        if p.tags:
            tags_line = "\n   Tags: " + ", ".join((p.tags or [])[:6])

        lines.append(
            f"[{i}] {p.name}\n"
            f"   Brand: {p.brand}  |  Category: {p.category} > {p.subcategory or 'General'}\n"
            f"   Price: ₹{eff_price:,.0f}{discount_note}  |  MRP: ₹{p.price:,.0f}\n"
            f"   Rating: {p.rating_avg}/5 ({p.rating_count} reviews)  |  {stock}"
            + specs_line
            + tags_line
        )

    return "\n\n".join(lines)


# ── Step 3: Generate ──────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
You are a helpful shopping assistant for an Indian e-commerce platform.
Help customers find products, check availability, get recommendations, and compare options.

{context}
{purchase_history_section}
Guidelines:
- Answer using ONLY the products listed above. Do not invent products or prices.
- Format all prices in Indian Rupees with commas: ₹12,999
- Always state availability (in stock / out of stock + units) when asked
- Recommendations: suggest 2-3 best options and explain WHY each is a good fit
- Comparisons: concise bullet points highlighting key differences
- If no suitable products found: say so honestly, suggest what to search for instead
- Keep replies concise (3-6 sentences) unless a detailed comparison is requested
- Be warm, knowledgeable, and helpful — like a trusted store assistant
- When purchase history is provided, personalise suggestions based on the user's past choices\
"""


def generate_reply(
    conversation_history: List[dict],
    context: str,
    user_message: str,
    purchase_history: Optional[str] = None,
) -> tuple[str, bool]:
    """
    Call GPT-5.4-mini with:
      - system prompt containing the retrieved product context
      - last 6 turns of conversation history (3 exchanges)
      - the new user message

    Returns (reply_text, used_fallback).

    Graceful degradation:
      - Primary: Azure OpenAI GPT-5.4-mini
      - Tier-1 fallback: local Flan-T5-base (if Azure times out or is unavailable)
      - Tier-2 fallback: plain product list (if local model also fails)
    """
    from local_fallback import generate_reply_local

    ph_section = f"\n{purchase_history}\n" if purchase_history else ""
    system_prompt = _SYSTEM_TEMPLATE.format(
        context=context,
        purchase_history_section=ph_section,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})

    # Primary: Azure OpenAI
    try:
        resp = _client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            temperature=0.7,
            max_completion_tokens=700,
            timeout=_AZURE_TIMEOUT_SECS,
        )
        text = resp.choices[0].message.content or ""
        if text:
            return text, False
        raise ValueError("empty response from Azure OpenAI")

    except (APITimeoutError, APIConnectionError, RateLimitError) as azure_err:
        logger.warning(
            "generate_reply: Azure OpenAI unavailable (%s) — activating local fallback",
            type(azure_err).__name__,
        )
    except Exception as exc:
        logger.error("generate_reply: unexpected Azure error: %s", exc)

    # Tier-1 / Tier-2 fallback: local Flan-T5 or plain text
    reply = generate_reply_local(context, user_message)
    return reply, True   # used_fallback=True
