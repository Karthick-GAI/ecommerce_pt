"""
Evaluation API routes for the recommendation engine.

Endpoints:
  POST /evaluation/run           — run all metrics on top N active users
  POST /evaluation/user/{id}     — evaluate a specific user's recommendations
  POST /evaluation/live          — evaluate a recommendation list you pass in
  GET  /evaluation/metrics       — list available metrics and their descriptions
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from evaluation.dataset import build_evaluation_cases, build_case_from_recs
from evaluation.evaluator import RecommendationEvaluator
from evaluation.metrics import (
    CartConversionMetric,
    RecommendationAccuracyMetric,
    PersonalizationMetric,
    DiversityMetric,
    NoveltyCoverageMetric,
    StrategyEffectivenessMetric,
)

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


# ── Request / Response schemas ────────────────────────────────────────────────

class RunEvaluationRequest(BaseModel):
    customer_ids: Optional[list[str]] = Field(
        default=None,
        description="Specific customer IDs to evaluate. If omitted, picks top active users.",
    )
    limit_users: int = Field(default=10, ge=1, le=50, description="Max users to evaluate.")
    interaction_window_days: int = Field(
        default=30, ge=1, le=90,
        description="Days back to look for ground-truth interactions.",
    )
    min_ground_truth: int = Field(
        default=1, ge=0,
        description="Skip users with fewer than this many ground-truth interactions.",
    )


class LiveEvaluationRequest(BaseModel):
    user_id: str
    recommendations: list[dict] = Field(
        ...,
        description="Recommendation dicts in the same format as /recommendations/for/{id}.",
    )
    interaction_window_days: int = Field(default=30, ge=1, le=90)


class MetricThresholds(BaseModel):
    cart_conversion: float = Field(default=0.40, ge=0, le=1)
    accuracy: float = Field(default=0.30, ge=0, le=1)
    personalization: float = Field(default=0.50, ge=0, le=1)
    diversity: float = Field(default=0.40, ge=0, le=1)
    novelty: float = Field(default=0.35, ge=0, le=1)
    strategy_effectiveness: float = Field(default=0.20, ge=0, le=1)


# ── GET /evaluation/metrics ───────────────────────────────────────────────────

@router.get("/metrics")
def list_metrics():
    """List all available evaluation metrics with descriptions and default thresholds."""
    return {
        "metrics": [
            {
                "name": "CartConversionMetric",
                "description": (
                    "Predicts cart-add probability for each recommendation using "
                    "category match, price range, discount, rating, stock urgency, "
                    "and trending signal. Score = mean top-3 conversion probability."
                ),
                "default_threshold": 0.40,
                "score_range": "0.0 – 1.0",
            },
            {
                "name": "RecommendationAccuracyMetric",
                "description": (
                    "NDCG@10 / Precision@10 / Recall@10 against real user interactions "
                    "(add_to_cart, purchase, wishlist) as ground truth. "
                    "Score = weighted mean of the three IR metrics."
                ),
                "default_threshold": 0.30,
                "score_range": "0.0 – 1.0",
            },
            {
                "name": "PersonalizationMetric",
                "description": (
                    "Weighted category overlap between recommended items and the user's "
                    "actual top_categories profile. Reflects how personalised the list is."
                ),
                "default_threshold": 0.50,
                "score_range": "0.0 – 1.0",
            },
            {
                "name": "DiversityMetric",
                "description": (
                    "Intra-list diversity: distinct categories (60%) and brands (40%) "
                    "as a fraction of total recommendations. Penalises filter bubbles."
                ),
                "default_threshold": 0.40,
                "score_range": "0.0 – 1.0",
            },
            {
                "name": "NoveltyCoverageMetric",
                "description": (
                    "Fraction of recommendations that are NOT in the user's purchase "
                    "history AND come from non-trivial strategies (not pure trending)."
                ),
                "default_threshold": 0.35,
                "score_range": "0.0 – 1.0",
            },
            {
                "name": "StrategyEffectivenessMetric",
                "description": (
                    "Hit rate per retrieval strategy (personalized, trending, content, "
                    "deals, new_arrival) against ground truth. Surfaces which strategy "
                    "should carry more weight in the hybrid ranker."
                ),
                "default_threshold": 0.20,
                "score_range": "0.0 – 1.0",
            },
        ]
    }


# ── POST /evaluation/run ──────────────────────────────────────────────────────

@router.post("/run")
def run_evaluation(
    body: RunEvaluationRequest,
    thresholds: Optional[MetricThresholds] = None,
    db: Session = Depends(get_db),
):
    """
    Run all 6 recommendation quality metrics over a set of users.

    Fetches real interaction data from the DB to use as ground truth,
    generates fresh recommendations, and returns a full evaluation report.
    """
    t = thresholds or MetricThresholds()

    cases = build_evaluation_cases(
        db=db,
        customer_ids=body.customer_ids,
        limit_users=body.limit_users,
        interaction_window_days=body.interaction_window_days,
        min_ground_truth=body.min_ground_truth,
    )

    if not cases:
        raise HTTPException(
            status_code=404,
            detail=(
                "No evaluation cases could be built. Users may lack sufficient "
                "interaction history. Try lowering min_ground_truth."
            ),
        )

    evaluator = RecommendationEvaluator(
        metrics=[
            CartConversionMetric(threshold=t.cart_conversion),
            RecommendationAccuracyMetric(threshold=t.accuracy),
            PersonalizationMetric(threshold=t.personalization),
            DiversityMetric(threshold=t.diversity),
            NoveltyCoverageMetric(threshold=t.novelty),
            StrategyEffectivenessMetric(threshold=t.strategy_effectiveness),
        ]
    )

    report = evaluator.run(cases)
    return report.to_dict()


# ── POST /evaluation/user/{customer_id} ──────────────────────────────────────

@router.post("/user/{customer_id}")
def evaluate_user(
    customer_id: str,
    interaction_window_days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """
    Evaluate recommendation quality for a specific user.

    Generates a fresh recommendation list, fetches the user's recent
    interactions as ground truth, and runs all 6 metrics.
    """
    cases = build_evaluation_cases(
        db=db,
        customer_ids=[customer_id],
        interaction_window_days=interaction_window_days,
        min_ground_truth=0,  # include even users with no ground truth
    )

    if not cases:
        raise HTTPException(
            status_code=404,
            detail=f"Could not build evaluation case for user '{customer_id}'. "
                   "User may not exist or has no interaction history.",
        )

    evaluator = RecommendationEvaluator()
    case_result = evaluator.run_single(cases[0])
    return case_result.to_dict()


# ── POST /evaluation/live ─────────────────────────────────────────────────────

@router.post("/live")
def evaluate_live(
    body: LiveEvaluationRequest,
    db: Session = Depends(get_db),
):
    """
    Evaluate a recommendation list you provide directly.

    Useful for testing new recommendation algorithms: pass the user_id and
    the list of product dicts, get back quality metrics immediately.
    The ground truth is fetched from recent DB interactions for the user.

    Example request body:
    {
      "user_id": "CU-001",
      "recommendations": [
        {"product_id": "P-1", "name": "...", "category": "Electronics",
         "brand": "Samsung", "price": 29999, "discount_pct": 20,
         "stock": 8, "rating_avg": 4.3, "strategy": "personalized", "score": 0.9}
      ]
    }
    """
    case = build_case_from_recs(
        db=db,
        user_id=body.user_id,
        recommendations=body.recommendations,
        interaction_window_days=body.interaction_window_days,
    )

    evaluator = RecommendationEvaluator()
    case_result = evaluator.run_single(case)

    return {
        **case_result.to_dict(),
        "evaluation_mode": "live",
        "ground_truth_source": f"browsing_events last {body.interaction_window_days} days",
    }


# ── GET /evaluation/cart-conversion/{customer_id} ─────────────────────────────

@router.get("/cart-conversion/{customer_id}")
def cart_conversion_prediction(
    customer_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Predict cart conversion probability for each recommendation for a user.

    Returns the raw recommendation list annotated with predicted conversion
    scores — useful as a re-ranking signal or for A/B test design.
    """
    cases = build_evaluation_cases(
        db=db,
        customer_ids=[customer_id],
        min_ground_truth=0,
    )

    if not cases:
        raise HTTPException(
            status_code=404,
            detail=f"No profile found for user '{customer_id}'.",
        )

    case = cases[0]
    metric = CartConversionMetric()
    result = metric.measure(case)

    # Sort by predicted conversion descending for re-ranking use case
    per_item = sorted(
        result.details.get("per_item", []),
        key=lambda x: x["predicted_conversion"],
        reverse=True,
    )

    return {
        "customer_id": customer_id,
        "avg_conversion_score": result.details.get("avg_conversion"),
        "top3_conversion_score": result.details.get("top3_conversion"),
        "overall_passed": result.passed,
        "items_ranked_by_conversion": per_item[:limit],
    }
