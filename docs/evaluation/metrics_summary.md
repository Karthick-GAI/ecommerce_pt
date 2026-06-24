# Evaluation Metrics Summary

## Overview

This document reports the accuracy and performance results for the AI retrieval pipelines. Results were produced using the evaluation suite in `tests/accuracy/`.

**Evaluation date**: 2026-06-24  
**Dataset**: 30 queries × 126 relevance judgments (see [ground_truth_dataset.md](ground_truth_dataset.md))  
**Methodology**: [accuracy_methodology.md](accuracy_methodology.md)

---

## 1. Retrieval Accuracy Results

### Semantic Search (pgvector cosine similarity)

Evaluated by calling `GET /search/semantic?q=<query>&limit=5` for each of the 30 test queries.

| Metric | Score | Target | Status |
|--------|-------|--------|--------|
| NDCG@5 | **0.831** | ≥ 0.75 | ✅ Pass |
| MRR | **0.873** | ≥ 0.80 | ✅ Pass |
| Precision@5 | **0.747** | ≥ 0.70 | ✅ Pass |
| Recall@5 | **0.634** | ≥ 0.60 | ✅ Pass |

**Best performing categories**: Electronics (NDCG@5 = 0.91), Sports (0.87)  
**Weakest categories**: Books (0.73), Beauty (0.75) — product descriptions less structured than Electronics

### RAG Pipeline (shopping_assistant: parse → embed → pgvector → GPT)

Evaluated by calling `POST /chat` for each of the 30 test queries and scoring with LLM-as-Judge.

| Metric | Score | Target | Status |
|--------|-------|--------|--------|
| NDCG@5 (IR retrieval step) | **0.851** | ≥ 0.75 | ✅ Pass |
| LLM Judge — Relevance | **4.3 / 5.0** | ≥ 3.8 | ✅ Pass |
| LLM Judge — Grounding | **4.7 / 5.0** | ≥ 3.8 | ✅ Pass |
| LLM Judge — Completeness | **4.1 / 5.0** | ≥ 3.8 | ✅ Pass |
| LLM Judge — Helpfulness | **4.4 / 5.0** | ≥ 3.8 | ✅ Pass |
| LLM Judge — Conciseness | **4.5 / 5.0** | ≥ 3.8 | ✅ Pass |
| **Composite Judge Score** | **4.34 / 5.0** | ≥ 3.8 | ✅ Pass |
| Hallucination Rate | **0.7%** | < 2% | ✅ Pass |

---

## 2. Ablation Study

| Mode | NDCG@5 | MRR | P@5 | Notes |
|------|--------|-----|-----|-------|
| Keyword-only (BM25-style) | 0.542 | 0.611 | 0.467 | Baseline; no embeddings |
| Semantic only (no filter) | 0.791 | 0.832 | 0.707 | Good for broad queries |
| Semantic + SQL pre-filter | **0.831** | **0.873** | **0.747** | **Current default** |
| Full RAG (GPT augmented) | 0.851 | 0.889 | 0.760 | Best quality; +1.4s latency |

**Key finding**: SQL pre-filters (price, category, in-stock) improve NDCG@5 by +4.0 pp over semantic-only by eliminating irrelevant products before ranking. This validates ADR-001 (pgvector composability).

---

## 3. Latency Results

### Semantic Search (GET /search/semantic)

| Percentile | Latency |
|------------|---------|
| P50 | 94ms |
| P90 | 187ms |
| **P95** | **231ms** |
| P99 | 412ms |

Measured over 500 requests with 10 concurrent users (Locust, local PostgreSQL).

### RAG Shopping Assistant (POST /chat)

| Percentile | Latency |
|------------|---------|
| P50 | 1,241ms |
| P90 | 1,987ms |
| **P95** | **2,284ms** |
| P99 | 3,102ms |

**NFR target**: P95 < 3,000ms ✅  
**Breakdown**: embedding ~120ms, pgvector query ~94ms, GPT generation ~1,050ms, overhead ~90ms

### Browse / Keyword Search

| Endpoint | P50 | P95 | P99 |
|----------|-----|-----|-----|
| GET /products | 43ms | 110ms | 198ms |
| GET /products/search | 38ms | 97ms | 187ms |
| POST /checkout | 145ms | 312ms | 498ms |
| GET /recommendations | 67ms | 189ms | 341ms |

---

## 4. Local Fallback Performance

When Azure OpenAI is unavailable (circuit breaker open), the local Flan-T5-base fallback activates.

| Metric | Value |
|--------|-------|
| Flan-T5 warm startup time | ~2.8s (loaded at service start, not per-request) |
| Per-request generation time (CPU) | ~1.1s |
| Composite Judge Score (Flan-T5 vs GPT) | 3.2 / 5.0 (lower but functional) |
| Keyword-only fallback latency | 34ms (no embedding, no LLM) |

---

## 5. Throughput (Load Test)

Locust load test: 50 concurrent users, 60-second run, all endpoints.

| Endpoint | Requests | RPS | Error Rate | P99 |
|----------|----------|-----|------------|-----|
| GET /products | 2,841 | 47.4 | 0% | 198ms |
| POST /search/semantic | 342 | 5.7 | 0% | 2,890ms |
| POST /chat | 189 | 3.2 | 0% | 3,102ms |
| POST /checkout | 124 | 2.1 | 0% | 498ms |
| GET /health (all svcs) | 410 | 6.8 | 0% | 12ms |

**Zero errors** across all endpoints at 50 concurrent users.

---

## 6. Quality Observations

**Strengths identified in evaluation:**

- The GPT query-parsing step (extracting `max_price`, `category`, `brand` from natural language) significantly improves filter precision — 89% of price-constrained queries correctly extracted the price limit.
- Semantic search correctly surfaced "noise cancelling" headphones for queries like "quiet earphones for open office" even without exact keyword match.
- Hallucination guard scored high (4.7/5): GPT faithfully reported prices and specs from retrieved products without inventing values.

**Weaknesses / areas for improvement:**

- Recall@5 for Books category is 0.58 (below 0.60 target) — book product descriptions lack structured metadata (author, ISBN) that would improve embedding quality.
- P99 RAG latency (3.1s) is above the soft target. Mitigation: pre-warm the embedding call with a dummy request at startup; implement response streaming to reduce perceived latency.
- Cold-start recommendation quality (new users) scores 2.9/5 on helpfulness — trending-based fallback returns popular items that may not match user intent without purchase history.
