# Recommendation Flow

## Overview

The recommendation engine generates personalised product suggestions using a hybrid approach that blends collaborative filtering, content-based similarity, and trending signals. Weights adapt based on user data availability (cold-start vs. warm users).

---

## Signal Sources

| Signal | Service | Description |
|--------|---------|-------------|
| Purchase history | `order_management` | Products the user has bought |
| Browsing events | `session_service` | Views, category visits, time-on-page |
| Wishlist items | `session_service` | Explicitly saved products |
| Product attributes | `product_catalogue` | Category, brand, price tier, specifications |
| Aggregate ratings | `product_catalogue` | Average rating + review count |
| Trending score | Computed weekly | Purchase velocity across all users |

---

## Recommendation Pipeline

```
User ID → recommendation_engine GET /recommendations/{user_id}
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 1 — USER PROFILE FETCH                            │
│                                                          │
│  → order_management: GET /orders?user_id=X              │
│  → session_service: GET /events?user_id=X               │
│                                                          │
│  Profile:                                                │
│  {                                                       │
│    "purchased": [p1, p2, p3],                           │
│    "viewed": [p4, p5, p6, p7],                          │
│    "wishlisted": [p8],                                   │
│    "categories_affinity": {"shoes": 0.6, "bags": 0.3}  │
│  }                                                       │
└─────────────────────────────┬───────────────────────────┘
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
         ┌──────────┐ ┌──────────┐ ┌──────────────┐
         │  CF:     │ │  CF:     │ │  Content-    │
         │  User-   │ │  Item-   │ │  Based       │
         │  Based   │ │  Based   │ │  Filtering   │
         └────┬─────┘ └────┬─────┘ └──────┬───────┘
              │            │              │
              ▼            ▼              ▼
   Find users   Find items  Find products
   with similar frequently  similar in
   purchase     bought with  category/brand
   patterns     purchased    to past purchases
   → candidate  → candidate  → candidate
     list A       list B       list C
              │            │              │
              └────────────┴──────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 3 — SCORE FUSION (Hybrid Weighted Blend)          │
│                                                          │
│  final_score(p) =                                        │
│    w_user_cf  × user_cf_score(p)                        │
│  + w_item_cf  × item_cf_score(p)                        │
│  + w_content  × content_score(p)                        │
│  + w_trending × trending_score(p)                       │
│                                                          │
│  Default weights: [0.35, 0.30, 0.25, 0.10]             │
│  Cold-start (< 3 purchases): [0.0, 0.0, 0.4, 0.6]     │
│  Heavy buyer (> 20 purchases): [0.45, 0.35, 0.15, 0.05]│
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 4 — POST-FILTERING                                │
│                                                          │
│  • Remove already-purchased products                    │
│  • Remove out-of-stock items                            │
│  • Deduplicate by product_id                            │
│  • Apply diversity constraint (max 2 per category)      │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
Returns top-N products (default N=10) ranked by final_score
```

---

## Collaborative Filtering Details

### User-Based CF

```
1. Compute user-item purchase matrix M (users × products, binary)
2. For target user u, compute cosine similarity with all other users:
     sim(u, v) = M[u] · M[v] / (|M[u]| × |M[v]|)
3. Select top-K neighbours (K=20)
4. Score each unseen product p:
     score(p) = Σ sim(u, v) × M[v][p]  for v in neighbours
```

### Item-Based CF

```
1. For each product p in user's purchase history:
   SELECT correlated_product_id, co_purchase_count
   FROM item_similarity
   WHERE product_id = p
   ORDER BY co_purchase_count DESC
   LIMIT 10;
2. Score = co_purchase_count weighted by recency of p in user's history
```

The `item_similarity` table is pre-computed nightly via a batch job using association rule mining over order items.

---

## Content-Based Filtering

```
For each product p in user's purchase history:
  SELECT candidate.id, 1 - (candidate.embedding <=> p.embedding) AS sim
  FROM products candidate
  WHERE candidate.category = p.category
    AND candidate.id != p.id
  ORDER BY embedding <=> p.embedding
  LIMIT 20;
```

Reuses the same pgvector embeddings as the RAG pipeline — no extra embedding cost.

---

## Trending Score

Computed weekly by a batch job and stored in a `product_trending_scores` table:

```python
trending_score(p) = (
    purchases_last_7d(p) * 0.6 +
    views_last_7d(p) * 0.3 +
    wishlist_adds_last_7d(p) * 0.1
) / max_score_in_category(p.category)
```

Normalised per category to prevent popular categories from dominating.

---

## Cold-Start Strategy

| Data Available | Strategy |
|----------------|---------|
| No history at all | Return top-trending products globally |
| Only category views | Return top products in browsed categories |
| 1–2 purchases | Item-based CF + content-based for those products |
| 3+ purchases | Full hybrid with adaptive weights |
