"""
Retrieval accuracy evaluation for the AI-powered e-commerce platform.

Measures:
  - NDCG@5, MRR, Precision@5, Recall@5 for semantic search
  - LLM-as-Judge composite score for the RAG shopping assistant

Usage:
    # Run against live services (requires Azure OpenAI for RAG mode)
    cd tests/accuracy
    python test_retrieval_accuracy.py --service semantic_search
    python test_retrieval_accuracy.py --service rag_pipeline
    python test_retrieval_accuracy.py --ablation all

    # Run via pytest (offline check — validates metric computation only)
    pytest test_retrieval_accuracy.py -v
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Optional

import httpx

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from ground_truth import GROUND_TRUTH, get_all_queries, get_relevance

PRODUCT_CAT_URL = os.getenv("PRODUCT_CAT_URL", "http://localhost:8002")
SHOPPING_ASST_URL = os.getenv("SHOPPING_ASSISTANT_URL", "http://localhost:8012")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
GPT_MODEL = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")


# ── IR Metrics ─────────────────────────────────────────────────────────────────

def _relevance_score(product_name: str, relevance_map: dict[str, int]) -> int:
    """Match product name to relevance map using substring matching (case-insensitive)."""
    name_lower = product_name.lower()
    for substring, score in relevance_map.items():
        if substring.lower() in name_lower:
            return score
    return 0


def ndcg_at_k(ranked_names: list[str], relevance_map: dict[str, int], k: int = 5) -> float:
    scores = [_relevance_score(n, relevance_map) for n in ranked_names[:k]]
    dcg = sum(s / math.log2(i + 2) for i, s in enumerate(scores))
    ideal_scores = sorted(relevance_map.values(), reverse=True)[:k]
    idcg = sum(s / math.log2(i + 2) for i, s in enumerate(ideal_scores))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(ranked_names: list[str], relevance_map: dict[str, int]) -> float:
    for i, name in enumerate(ranked_names, 1):
        if _relevance_score(name, relevance_map) > 0:
            return 1.0 / i
    return 0.0


def precision_at_k(ranked_names: list[str], relevance_map: dict[str, int], k: int = 5) -> float:
    hits = sum(1 for n in ranked_names[:k] if _relevance_score(n, relevance_map) > 0)
    return hits / k if k > 0 else 0.0


def recall_at_k(ranked_names: list[str], relevance_map: dict[str, int], k: int = 5) -> float:
    total_relevant = sum(1 for s in relevance_map.values() if s > 0)
    if total_relevant == 0:
        return 0.0
    hits = sum(1 for n in ranked_names[:k] if _relevance_score(n, relevance_map) > 0)
    return hits / total_relevant


# ── Semantic Search Evaluation ─────────────────────────────────────────────────

def evaluate_semantic_search(queries: list[str], k: int = 5) -> dict:
    results = []
    for query in queries:
        relevance_map = get_relevance(query)
        try:
            resp = httpx.get(
                f"{PRODUCT_CAT_URL}/products/semantic-search",
                params={"query": query, "top_k": k},
                timeout=30,
            )
            if resp.status_code != 200:
                # Try alternate endpoint path
                resp = httpx.post(
                    f"{PRODUCT_CAT_URL}/search/semantic",
                    json={"query": query, "n": k},
                    timeout=30,
                )
            if resp.status_code != 200:
                print(f"  [SKIP] semantic search returned {resp.status_code} for: {query[:50]}")
                continue
            body = resp.json()
            items = body.get("results", body.get("products", body if isinstance(body, list) else []))
            ranked_names = [item.get("name", "") for item in items[:k]]
        except Exception as exc:
            print(f"  [ERROR] {query[:50]}: {exc}")
            continue

        result = {
            "query": query,
            "ndcg_at_5": ndcg_at_k(ranked_names, relevance_map),
            "mrr": mrr(ranked_names, relevance_map),
            "precision_at_5": precision_at_k(ranked_names, relevance_map),
            "recall_at_5": recall_at_k(ranked_names, relevance_map),
            "ranked_names": ranked_names,
        }
        results.append(result)
        print(f"  NDCG@5={result['ndcg_at_5']:.3f}  MRR={result['mrr']:.3f}  {query[:60]}")

    if not results:
        return {"error": "no results — is the product catalogue service running?"}

    return {
        "service": "semantic_search",
        "num_queries": len(results),
        "avg_ndcg_at_5": sum(r["ndcg_at_5"] for r in results) / len(results),
        "avg_mrr": sum(r["mrr"] for r in results) / len(results),
        "avg_precision_at_5": sum(r["precision_at_5"] for r in results) / len(results),
        "avg_recall_at_5": sum(r["recall_at_5"] for r in results) / len(results),
        "per_query": results,
    }


# ── LLM-as-Judge ──────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are evaluating a shopping assistant response for an Indian e-commerce platform.

USER QUERY:
{query}

ASSISTANT RESPONSE:
{response}

Score the response on each dimension from 1 to 5:
1. Relevance (1-5): Are the products/recommendations relevant to the query?
2. Grounding (1-5): Does it avoid hallucinating product details not in its context?
3. Completeness (1-5): Does it fully address the user's need?
4. Helpfulness (1-5): Would a shopper find this actionable?
5. Conciseness (1-5): Is it appropriately concise (not padded)?

Respond ONLY as JSON with no other text:
{{
  "relevance": <int 1-5>,
  "grounding": <int 1-5>,
  "completeness": <int 1-5>,
  "helpfulness": <int 1-5>,
  "conciseness": <int 1-5>,
  "reasoning": "<one sentence>"
}}"""

_JUDGE_WEIGHTS = {
    "relevance": 0.30,
    "grounding": 0.25,
    "completeness": 0.20,
    "helpfulness": 0.15,
    "conciseness": 0.10,
}


def llm_judge_score(query: str, response: str) -> Optional[dict]:
    """Call Azure OpenAI to score a RAG response. Returns None if unavailable."""
    if not AZURE_API_KEY or not AZURE_ENDPOINT:
        return None
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=AZURE_API_KEY,
            api_version=AZURE_API_VERSION,
            azure_endpoint=AZURE_ENDPOINT,
        )
        resp = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{
                "role": "user",
                "content": _JUDGE_PROMPT.format(query=query, response=response),
            }],
            temperature=0.0,
            max_completion_tokens=300,
            timeout=15,
        )
        raw = resp.choices[0].message.content or "{}"
        scores = json.loads(raw)
        composite = sum(
            scores.get(dim, 3) * weight for dim, weight in _JUDGE_WEIGHTS.items()
        )
        scores["composite"] = round(composite, 3)
        return scores
    except Exception as exc:
        print(f"    [judge error] {exc}")
        return None


def evaluate_rag_pipeline(queries: list[str]) -> dict:
    results = []
    for query in queries:
        relevance_map = get_relevance(query)
        try:
            resp = httpx.post(
                f"{SHOPPING_ASST_URL}/chat",
                json={"message": query},
                timeout=45,
            )
            if resp.status_code != 200:
                print(f"  [SKIP] RAG returned {resp.status_code} for: {query[:50]}")
                continue
            body = resp.json()
            reply = body.get("reply", "")
            sources = body.get("sources", [])
            ranked_names = [s.get("name", "") for s in sources]
            fallback = body.get("fallback_mode", False)
        except Exception as exc:
            print(f"  [ERROR] {query[:50]}: {exc}")
            continue

        ir = {
            "ndcg_at_5": ndcg_at_k(ranked_names, relevance_map),
            "mrr": mrr(ranked_names, relevance_map),
            "precision_at_5": precision_at_k(ranked_names, relevance_map),
        }
        judge = llm_judge_score(query, reply)
        result = {
            "query": query,
            **ir,
            "fallback_mode": fallback,
            "llm_judge": judge,
        }
        results.append(result)
        judge_str = f"judge={judge['composite']:.2f}" if judge else "judge=n/a"
        print(
            f"  NDCG@5={ir['ndcg_at_5']:.3f}  {judge_str}  "
            f"{'[FALLBACK]' if fallback else ''}  {query[:55]}"
        )

    if not results:
        return {"error": "no results — is the shopping assistant service running?"}

    avg_ndcg = sum(r["ndcg_at_5"] for r in results) / len(results)
    judge_scores = [r["llm_judge"]["composite"] for r in results if r.get("llm_judge")]
    avg_judge = sum(judge_scores) / len(judge_scores) if judge_scores else None

    return {
        "service": "rag_pipeline",
        "num_queries": len(results),
        "avg_ndcg_at_5": avg_ndcg,
        "avg_mrr": sum(r["mrr"] for r in results) / len(results),
        "avg_precision_at_5": sum(r["precision_at_5"] for r in results) / len(results),
        "avg_llm_judge_composite": avg_judge,
        "fallback_rate": sum(1 for r in results if r["fallback_mode"]) / len(results),
        "per_query": results,
    }


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(report: dict) -> None:
    print("\n" + "=" * 70)
    print(f"EVALUATION REPORT — {report.get('service', 'unknown').upper()}")
    print("=" * 70)
    if "error" in report:
        print(f"ERROR: {report['error']}")
        return

    print(f"Queries evaluated : {report['num_queries']}")
    print(f"NDCG@5            : {report['avg_ndcg_at_5']:.4f}  (target ≥ 0.75)")
    print(f"MRR               : {report['avg_mrr']:.4f}  (target ≥ 0.80)")
    print(f"Precision@5       : {report['avg_precision_at_5']:.4f}  (target ≥ 0.70)")
    if "avg_recall_at_5" in report:
        print(f"Recall@5          : {report['avg_recall_at_5']:.4f}  (target ≥ 0.60)")
    if report.get("avg_llm_judge_composite") is not None:
        print(f"LLM Judge (avg)   : {report['avg_llm_judge_composite']:.3f}/5.0  (target ≥ 3.8)")
    if "fallback_rate" in report:
        print(f"Fallback rate     : {report['fallback_rate']*100:.1f}%")

    # Pass/fail summary
    checks = [
        ("NDCG@5 ≥ 0.75", report["avg_ndcg_at_5"] >= 0.75),
        ("MRR ≥ 0.80", report["avg_mrr"] >= 0.80),
        ("P@5 ≥ 0.70", report["avg_precision_at_5"] >= 0.70),
    ]
    if report.get("avg_llm_judge_composite") is not None:
        checks.append(("Judge ≥ 3.8", report["avg_llm_judge_composite"] >= 3.8))
    print("\n--- Threshold checks ---")
    all_pass = True
    for label, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {label}")
        if not passed:
            all_pass = False
    print(f"\nOverall: {'✅ ALL PASS' if all_pass else '❌ SOME CHECKS FAILED'}")
    print("=" * 70)


def save_report(report: dict, path: str = "results/evaluation_report.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved to: {path}")


# ── pytest entry points (offline) ─────────────────────────────────────────────

def test_ndcg_computation():
    """Verify NDCG formula is correct on a known example."""
    rel = {"a": 3, "b": 2, "c": 1}
    ranked = ["a", "c", "b", "x", "y"]
    score = ndcg_at_k(ranked, rel, k=5)
    assert 0.0 < score <= 1.0


def test_mrr_first_hit():
    rel = {"good_product": 2}
    ranked = ["bad", "good_product", "another_bad"]
    assert abs(mrr(ranked, rel) - 0.5) < 1e-9


def test_mrr_no_hit():
    rel = {"missing": 1}
    ranked = ["a", "b", "c"]
    assert mrr(ranked, rel) == 0.0


def test_precision_at_k_all_relevant():
    rel = {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1}
    ranked = ["a", "b", "c", "d", "e"]
    assert precision_at_k(ranked, rel, k=5) == 1.0


def test_ground_truth_has_entries():
    queries = get_all_queries()
    assert len(queries) >= 20, "Ground truth should have at least 20 queries"
    for q in queries:
        relevance = get_relevance(q)
        assert len(relevance) >= 2, f"Query '{q}' has fewer than 2 relevant products"


def test_relevance_substring_matching():
    rel_map = {"airdopes 141": 3, "boult z40": 2}
    assert _relevance_score("boAt Airdopes 141 TWS Earbuds", rel_map) == 3
    assert _relevance_score("Boult Z40 True Wireless", rel_map) == 2
    assert _relevance_score("Sony WH-1000XM5", rel_map) == 0


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieval accuracy evaluation")
    parser.add_argument(
        "--service",
        choices=["semantic_search", "rag_pipeline"],
        default="semantic_search",
        help="Which pipeline to evaluate",
    )
    parser.add_argument(
        "--ablation",
        choices=["all"],
        help="Run ablation study across all modes",
    )
    parser.add_argument(
        "--queries",
        type=int,
        default=None,
        help="Limit to first N queries (useful for quick smoke test)",
    )
    args = parser.parse_args()

    queries = get_all_queries()
    if args.queries:
        queries = queries[: args.queries]

    print(f"Evaluating {len(queries)} queries…")

    if args.ablation == "all" or args.service == "semantic_search":
        print("\n[1/2] Semantic Search (pgvector)")
        sem_report = evaluate_semantic_search(queries)
        print_report(sem_report)
        save_report(sem_report, "results/semantic_search_report.json")

    if args.ablation == "all" or args.service == "rag_pipeline":
        print("\n[2/2] RAG Pipeline (shopping_assistant)")
        rag_report = evaluate_rag_pipeline(queries)
        print_report(rag_report)
        save_report(rag_report, "results/rag_pipeline_report.json")
