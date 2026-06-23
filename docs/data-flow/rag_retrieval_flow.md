# RAG Retrieval Flow

## Overview

The Shopping Assistant uses Retrieval-Augmented Generation (RAG) to answer natural language product queries.
The pipeline combines semantic vector search (pgvector) with Azure OpenAI GPT-4o-mini to return contextually relevant, conversational responses.

---

## End-to-End Flow

```
User Query: "I need waterproof hiking boots under ₹5000"
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 1 — INPUT GUARDRAIL                               │
│  guardrails_service POST /validate/input                 │
│                                                          │
│  LLM Judge checks:                                       │
│  • Is query product-related?                            │
│  • Does it contain harmful/off-topic content?           │
│                                                          │
│  → PASS: continue   → FAIL: return 400 with reason      │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 2 — QUERY PARSING                                 │
│  shopping_assistant internal: parse_query()              │
│                                                          │
│  GPT-4o-mini extracts structured filters:               │
│  {                                                       │
│    "intent": "product_search",                          │
│    "keywords": ["waterproof", "hiking", "boots"],       │
│    "max_price": 5000,                                   │
│    "category": "footwear",                              │
│    "attributes": {"waterproof": true}                   │
│  }                                                       │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 3 — QUERY EMBEDDING                               │
│  Azure OpenAI text-embedding-3-small                     │
│                                                          │
│  embed("waterproof hiking boots under ₹5000")           │
│  → vector[1536] (float32)                               │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 4 — VECTOR SEARCH                                 │
│  product_catalogue: pgvector cosine similarity           │
│                                                          │
│  SELECT id, name, price, description,                   │
│         1 - (embedding <=> $1) AS score                 │
│  FROM products                                           │
│  WHERE price <= 5000                                     │
│    AND category = 'footwear'   -- optional pre-filter   │
│  ORDER BY embedding <=> $1                               │
│  LIMIT 5;                                               │
│                                                          │
│  Returns top-5 products ranked by cosine similarity     │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 5 — AUGMENTED GENERATION                          │
│  Azure OpenAI GPT-4o-mini                                │
│                                                          │
│  System prompt:                                          │
│    "You are a helpful shopping assistant. Use only the  │
│     provided product context to answer the query.       │
│     Be concise, factual, and recommend the best match." │
│                                                          │
│  User message:                                           │
│    Query: "waterproof hiking boots under ₹5000"         │
│    Context: [product 1 JSON, product 2 JSON, ...]       │
│                                                          │
│  → GPT generates: "Here are the best options I found…" │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 6 — OUTPUT GUARDRAIL                              │
│  guardrails_service POST /validate/output                │
│                                                          │
│  LLM Judge checks:                                       │
│  • Does response contain only products from context?    │
│  • Is it free of hallucinated prices or names?          │
│  • Is it safe / non-harmful?                            │
│                                                          │
│  → PASS: return to user  → FAIL: return fallback message│
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
Response: "I found 3 great waterproof hiking boots under ₹5000.
           The TrailMaster Pro (₹4,499) is your best bet — ..."
```

---

## Hybrid Search Strategy

The system uses a two-phase retrieval to balance semantic accuracy with structured filtering:

| Phase | Type | Purpose |
|-------|------|---------|
| Pre-filter | SQL `WHERE` | Hard constraints (price cap, category, in-stock) |
| Ranking | pgvector cosine | Semantic relevance ranking within the filtered set |

This prevents a semantically perfect but price-violating product from appearing in results.

---

## Context Window Budget

The top-k products are serialised as compact JSON before being passed to GPT. Each product is limited to:

```json
{
  "id": "prod_123",
  "name": "TrailMaster Pro Waterproof Hiking Boot",
  "price": 4499,
  "brand": "Wildcraft",
  "description": "Gore-Tex waterproof upper, Vibram outsole...",
  "rating": 4.3,
  "in_stock": true
}
```

With k=5 and ~200 tokens/product, the context uses ~1,000 tokens, well within GPT-4o-mini's 128K limit.

---

## Fallback Behaviour

| Condition | Fallback |
|-----------|---------|
| pgvector returns 0 results | Return "No products matched your query. Try different keywords." |
| Azure OpenAI timeout | Return the raw product list without GPT augmentation |
| Guardrail rejects input | Return 400 with `"Query not related to products"` |
| Guardrail rejects output | Return `"I couldn't find a suitable answer. Here are the top matches:"` + raw product cards |
