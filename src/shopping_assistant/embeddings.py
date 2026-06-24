import json
import logging
import os
import threading
from typing import List

from cachetools import TTLCache
from openai import AzureOpenAI, APITimeoutError, APIConnectionError, RateLimitError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_AZURE_TIMEOUT_SECS = float(os.getenv("AZURE_TIMEOUT_SECS", "10.0"))

_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)

EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_SMALL", "text-embedding-3-small")
GPT_MINI_MODEL  = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")

# ── In-process caches (ADR-008: replaces Redis at capstone scale) ─────────────
# embed_text: 5-min TTL — same query string always produces the same vector
_embed_cache: TTLCache = TTLCache(maxsize=512, ttl=300)
_embed_lock  = threading.Lock()

# parse_nl_query: 5-min TTL — deterministic (temperature=0) for same query
_parse_cache: TTLCache = TTLCache(maxsize=512, ttl=300)
_parse_lock  = threading.Lock()


def embed_text(text: str) -> List[float]:
    """
    Embed a single text string with 5-minute in-process cache.
    Cache hit avoids an Azure API call (~120ms saved per hit).
    """
    text = text.replace("\n", " ").strip()[:8000]

    with _embed_lock:
        if text in _embed_cache:
            return _embed_cache[text]

    try:
        resp = _client.embeddings.create(
            input=[text], model=EMBEDDING_MODEL, timeout=_AZURE_TIMEOUT_SECS
        )
        embedding = resp.data[0].embedding
    except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
        logger.warning("embed_text: Azure unavailable (%s) — raising for caller fallback", type(exc).__name__)
        raise
    except Exception as exc:
        logger.error("embed_text: unexpected error: %s", exc)
        raise

    with _embed_lock:
        _embed_cache[text] = embedding
    return embedding


def parse_nl_query(query: str) -> dict:
    """
    Extract structured filters from a natural-language search query.
    Results cached for 5 minutes — same query always yields the same filters
    (temperature=0, deterministic).
    """
    with _parse_lock:
        if query in _parse_cache:
            return _parse_cache[query]

    system_prompt = """You are a product search assistant for an Indian e-commerce platform.
Extract search filters from the user's query and return ONLY a valid JSON object with:
- keywords: main search terms stripped of price/brand constraints (string, required)
- category: one of [Electronics, Clothing, Home & Kitchen, Sports & Fitness,
            Books, Beauty, Automotive, Baby Products, Furniture,
            Pet Supplies, Stationery, Toys & Games] or null
- subcategory: specific type like Laptop, Smartphone, T-Shirts, Running Shoes etc. or null
- brand: exact brand name if mentioned or null
- max_price: maximum price in INR as integer or null
- min_price: minimum price in INR as integer or null
- features: list of required features/attributes as strings (can be empty array)
Return only the JSON object, no explanation or markdown."""

    try:
        resp = _client.chat.completions.create(
            model=GPT_MINI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": query},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=_AZURE_TIMEOUT_SECS,
        )
        result = json.loads(resp.choices[0].message.content)
    except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
        logger.warning("parse_nl_query: Azure unavailable (%s) — keyword-only fallback", type(exc).__name__)
        result = {"keywords": query, "features": []}
    except Exception:
        result = {"keywords": query, "features": []}

    with _parse_lock:
        _parse_cache[query] = result
    return result


def cache_stats() -> dict:
    """Expose cache hit metrics for the /health endpoint."""
    with _embed_lock:
        embed_size = len(_embed_cache)
    with _parse_lock:
        parse_size = len(_parse_cache)
    return {
        "embed_cache":  {"size": embed_size, "maxsize": _embed_cache.maxsize, "ttl_secs": 300},
        "parse_cache":  {"size": parse_size, "maxsize": _parse_cache.maxsize, "ttl_secs": 300},
    }
