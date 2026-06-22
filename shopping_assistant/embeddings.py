import os
import json
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
    text = text.replace("\n", " ").strip()[:8000]
    resp = _client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return resp.data[0].embedding


def parse_nl_query(query: str) -> dict:
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

    resp = _client.chat.completions.create(
        model=GPT_MINI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": query},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {"keywords": query, "features": []}
