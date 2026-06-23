# Data Ingestion Flow

## Overview

The synthetic dataset is generated offline and loaded into PostgreSQL before services start.
The ingestion pipeline runs once at setup time and is re-run whenever the dataset is refreshed.

---

## Dataset Volumes

| Entity | Count | Source |
|--------|-------|--------|
| Products | 5,000 | Synthetic JSON (Faker + domain templates) |
| Customers | 10,000 | Synthetic (realistic Indian names, addresses, emails) |
| Orders | 50,000 | Synthetic (distributed across customers + products) |
| Order items | ~125,000 | Derived from orders (avg 2.5 items/order) |
| Browsing events | 150,000 | Simulated user sessions (view, search, wishlist) |
| Wishlists | 30,000 | Subset of browsing events |
| Search logs | 15,000 | NL queries and result click-through |
| Inventory records | 5,000 | One-to-one with products |

---

## Ingestion Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                  SYNTHETIC DATA GENERATION               │
│  scripts/generate_dataset.py                             │
│                                                          │
│  Faker library + domain templates                        │
│  → products.json (5K rows)                              │
│  → customers.json (10K rows)                            │
│  → orders.json (50K rows)                               │
│  → browsing_events.json (150K rows)                     │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    DATABASE SEED                         │
│  scripts/seed_data.py                                    │
│                                                          │
│  Reads JSON → SQLAlchemy bulk_insert_mappings            │
│  → PostgreSQL: products, customers, orders,             │
│                order_items, browsing_events              │
│  → inventory rows (qty = 100–500 per product)           │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                  EMBEDDING GENERATION                    │
│  scripts/generate_embeddings.py                          │
│                                                          │
│  For each product:                                       │
│    text = f"{name} {description} {category} {brand}"    │
│    → Azure OpenAI text-embedding-3-small                │
│    ← vector[1536] (float32)                             │
│    → UPDATE products SET embedding = ? WHERE id = ?     │
│                                                          │
│  Batched 100 at a time; ~50 API calls for 5K products   │
│  Estimated: ~3 min at 10 req/s                          │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                   INDEX CREATION                         │
│  scripts/create_vector_index.py                          │
│                                                          │
│  CREATE INDEX ON products                                │
│  USING ivfflat (embedding vector_cosine_ops)            │
│  WITH (lists = 100);                                     │
│                                                          │
│  Enables ANN search in pgvector                         │
└─────────────────────────────────────────────────────────┘
```

---

## Product Text Representation

The text field used for embedding is constructed as:

```python
def product_to_text(product: Product) -> str:
    parts = [
        product.name,
        product.description,
        product.category,
        product.brand,
        " ".join(product.tags or []),
        " ".join(f"{k}: {v}" for k, v in (product.specifications or {}).items()),
    ]
    return " | ".join(filter(None, parts))
```

This composite text ensures semantic search matches on product attributes, not just name keywords.

---

## Embedding Update Policy

| Event | Action |
|-------|--------|
| New product created | Embedding generated immediately (async background task) |
| Product name/description/category edited | Re-embedding triggered on save |
| Seller product approved | Embedding generated if not present |
| Bulk re-indexing | `scripts/regenerate_embeddings.py --all` re-embeds all products |

---

## Data Quality Checks

Run after seeding to verify data integrity:

```bash
python scripts/validate_dataset.py
```

Checks performed:
- All `order_items` reference valid `product_id` and `order_id`
- All `browsing_events` reference valid `user_id` and `product_id`
- No negative stock values in `inventory`
- No products with NULL embeddings (after embedding script completes)
- Order totals match sum of item prices × quantities
