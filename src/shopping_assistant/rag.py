import os
from typing import List, Tuple
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)

GPT_MODEL = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")


# ── Step 1: Retrieve ──────────────────────────────────────────────────────────

def retrieve_products(db, query: str, n: int = 8):
    """
    Parse the natural-language query → embed → pgvector cosine search.
    Returns (results, parsed_filters).
      results        = list of (Product ORM object, similarity_score)
      parsed_filters = dict extracted by GPT (category, brand, price, keywords)
    """
    from embeddings import embed_text, parse_nl_query
    from vector_store import semantic_search

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
    return results, parsed


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

Guidelines:
- Answer using ONLY the products listed above. Do not invent products or prices.
- Format all prices in Indian Rupees with commas: ₹12,999
- Always state availability (in stock / out of stock + units) when asked
- Recommendations: suggest 2-3 best options and explain WHY each is a good fit
- Comparisons: concise bullet points highlighting key differences
- If no suitable products found: say so honestly, suggest what to search for instead
- Keep replies concise (3-6 sentences) unless a detailed comparison is requested
- Be warm, knowledgeable, and helpful — like a trusted store assistant\
"""


def generate_reply(
    conversation_history: List[dict],
    context: str,
    user_message: str,
) -> str:
    """
    Call GPT-5.4-mini with:
      - system prompt containing the retrieved product context
      - last 6 turns of conversation history (3 exchanges)
      - the new user message
    Returns the assistant's reply string.
    """
    messages = [{"role": "system", "content": _SYSTEM_TEMPLATE.format(context=context)}]
    messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})

    resp = _client.chat.completions.create(
        model=GPT_MODEL,
        messages=messages,
        temperature=0.7,
        max_completion_tokens=700,
    )
    return resp.choices[0].message.content
