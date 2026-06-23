# embeddings.py — Azure OpenAI embedding client
#
# WHY AZURE OPENAI EMBEDDINGS?
#   text-embedding-3-small produces 1536-dim vectors at low cost.
#   We embed: product name + brand + category + description + tags
#   At search time we embed the query and find nearest neighbours in ChromaDB.
#   This lets "lightweight laptop for college" find MacBook Air even if the
#   product description never uses those exact words.

import os
from typing import List
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)

EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_SMALL", "text-embedding-3-small")
GPT_MINI_MODEL  = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")


def embed_text(text: str) -> List[float]:
    """Embed a single text string. Truncates at 8000 chars to stay within token limit."""
    text = text.replace("\n", " ").strip()[:8000]
    resp = _client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return resp.data[0].embedding


def embed_batch(texts: List[str]) -> List[List[float]]:
    """
    Embed a batch of texts in one API call (max 100 per call for text-embedding-3-small).
    Much cheaper than calling embed_text() in a loop.
    """
    cleaned = [t.replace("\n", " ").strip()[:8000] for t in texts]
    resp = _client.embeddings.create(input=cleaned, model=EMBEDDING_MODEL)
    # API returns items sorted by index, so order is preserved
    return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]


def parse_nl_query(query: str) -> dict:
    """
    Use GPT-5.4-mini to extract structured filters from a natural language search query.
    Example input:  "lightweight laptop under Rs.50000 with good battery life"
    Example output: {"keywords": "lightweight laptop", "category": "Electronics",
                     "max_price": 50000, "features": ["lightweight", "battery life"]}
    """
    system_prompt = """You are a product search assistant for an Indian e-commerce platform.
Extract search filters from the user's query and return ONLY a valid JSON object with these keys:
- keywords: main search terms (string, required)
- category: one of [Electronics, Clothing, Home & Kitchen, Sports & Fitness, Books, Beauty] or null
- subcategory: specific subcategory like Laptop, Smartphone, etc. or null
- brand: brand name if mentioned or null
- max_price: maximum price in INR as integer or null
- min_price: minimum price in INR as integer or null
- features: list of required features/attributes (array of strings)
Return only the JSON, no explanation."""

    resp = _client.chat.completions.create(
        model=GPT_MINI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": query},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    import json
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {"keywords": query, "features": []}


def build_product_text(product) -> str:
    """
    Construct the text we embed for a product.
    Richer text = better semantic search results.
    """
    parts = [
        product.name,
        product.brand,
        product.category,
        product.subcategory or "",
        product.description,
        " ".join(product.tags or []),
    ]
    return " ".join(p for p in parts if p).strip()
