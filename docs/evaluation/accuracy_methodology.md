# Retrieval Accuracy Validation Methodology

## Overview

This document describes the methodology used to validate the accuracy of the two AI retrieval pipelines in the platform:

1. **Semantic Product Search** — pgvector cosine similarity (product_catalogue service)
2. **RAG Shopping Assistant** — full pipeline: parse → embed → pgvector → GPT augment (shopping_assistant service)

Accuracy is measured using two complementary approaches:
- **Information Retrieval (IR) Metrics**: NDCG@5, MRR, Precision@5, Recall@5
- **LLM-as-Judge**: GPT-5.4-mini evaluates response quality against a rubric

---

## 1. Ground Truth Dataset

See [ground_truth_dataset.md](ground_truth_dataset.md) for the full dataset.

**Summary**:
- 30 query-relevant product pairs covering 8 product categories
- Each query has 3–6 relevant products labeled with relevance scores (0–3 scale: 3=highly relevant, 2=relevant, 1=marginally relevant)
- Queries span: natural language, brand-specific, price-constrained, feature-specific, and cross-category use cases

---

## 2. IR Metrics

### NDCG@5 (Normalised Discounted Cumulative Gain)

Measures ranking quality: are the most relevant products ranked highest?

```
DCG@5    = Σ  rel(i) / log₂(i+1)   for i = 1..5
IDCG@5   = DCG@5 of ideal (sorted by relevance) ranking
NDCG@5   = DCG@5 / IDCG@5          ∈ [0, 1]
```

**Target**: NDCG@5 ≥ 0.75

### MRR (Mean Reciprocal Rank)

Measures how quickly the first relevant result appears.

```
MRR = (1/|Q|) * Σ  1/rank(first relevant result)
```

**Target**: MRR ≥ 0.80

### Precision@5

Fraction of the top-5 results that are relevant (relevance ≥ 1).

**Target**: P@5 ≥ 0.70

### Recall@5

Fraction of all relevant products that appear in the top-5.

**Target**: Recall@5 ≥ 0.60

---

## 3. LLM-as-Judge Methodology

For the RAG Shopping Assistant, IR metrics alone are insufficient — the response must be **conversational, grounded, and helpful**. We use GPT-5.4-mini as a judge with a structured rubric.

### Rubric (Score 1–5 per dimension)

| Dimension | Description | Weight |
|-----------|-------------|--------|
| **Relevance** | Are the recommended products relevant to the query? | 30% |
| **Grounding** | Are all product names, prices, specs from the retrieved context (no hallucination)? | 25% |
| **Completeness** | Does the response address all aspects of the query? | 20% |
| **Helpfulness** | Is the reply actionable and clear for a shopper? | 15% |
| **Conciseness** | Is it free of unnecessary padding or repetition? | 10% |

**Composite score** = weighted average of 5 dimensions (1–5 scale). **Target**: ≥ 3.8 / 5.0

### Judge Prompt Template

```
You are evaluating a shopping assistant response. Score it on each dimension from 1 to 5.

USER QUERY:
{query}

RETRIEVED PRODUCTS (ground truth context):
{retrieved_products}

ASSISTANT RESPONSE:
{response}

Evaluate on these dimensions (1=poor, 3=acceptable, 5=excellent):
1. Relevance: Are the products recommended actually relevant to the query?
2. Grounding: Does the response use only facts from the retrieved products (no invented specs/prices)?
3. Completeness: Does it fully address the user's need?
4. Helpfulness: Would a shopper find this actionable?
5. Conciseness: Is it appropriately concise (not padded)?

Respond as JSON:
{
  "relevance": <1-5>,
  "grounding": <1-5>,
  "completeness": <1-5>,
  "helpfulness": <1-5>,
  "conciseness": <1-5>,
  "reasoning": "<one sentence>"
}
```

### Anti-Hallucination Check

A separate binary check verifies grounding: the judge is asked to flag any product name, price, or specification in the response that does NOT appear in the retrieved context.

**Target**: Hallucination rate < 2% of responses.

---

## 4. Evaluation Procedure

### Step 1 — Baseline IR Measurement (offline)

```bash
# Run semantic search evaluation against ground truth
cd tests/accuracy
python test_retrieval_accuracy.py --service semantic_search
```

This calls `GET /search/semantic?q=<query>` for each test query, collects the top-5 results, and computes NDCG@5, MRR, P@5, Recall@5 against the ground truth relevance judgments.

### Step 2 — RAG Pipeline Evaluation (online, requires Azure OpenAI)

```bash
python test_retrieval_accuracy.py --service rag_pipeline
```

This calls `POST /chat` for each query, captures the response, then calls the LLM judge to score each response.

### Step 3 — Ablation Study

The evaluation script supports ablation to understand contribution of each component:

| Mode | Description |
|------|-------------|
| `keyword_only` | BM25-style keyword match (no embeddings) |
| `semantic_only` | pgvector cosine similarity only |
| `rag_no_filter` | Embedding + GPT, no SQL pre-filters |
| `rag_full` | Full pipeline (embedding + SQL filter + GPT) |

```bash
python test_retrieval_accuracy.py --ablation all
```

### Step 4 — Results Report

The script writes results to `tests/accuracy/results/evaluation_report.json` and prints a summary table. See [metrics_summary.md](metrics_summary.md) for the actual results.

---

## 5. Continuous Evaluation

In production, evaluation runs as a scheduled Kubernetes CronJob:

```yaml
# Runs daily at 02:00 UTC
schedule: "0 2 * * *"
# Fails the job (triggers alert) if NDCG@5 drops below threshold
successCondition: ndcg_at_5 >= 0.70
```

A drop in NDCG can indicate:
- Product catalogue drifted (new categories not covered by existing embeddings)
- Embedding model version changed
- Query pattern shift (new customer segments)

Trigger: re-run `scripts/seed_products.sh` with `--re-embed` flag to regenerate all embeddings.
