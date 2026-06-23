"""
Custom evaluation metrics for recommendation quality.

Each metric follows the DeepEval pattern:
  - Instantiate with thresholds/config
  - Call .measure(case) -> MetricResult
  - Check .passed and .score on the result

Metric   | What it measures
---------|------------------------------------------------------------------
CartConversionMetric         | Predicted probability a rec leads to a cart-add
RecommendationAccuracyMetric | NDCG@K / P@K / Recall@K vs. real interaction history
PersonalizationMetric        | Category overlap between recs and user's preference profile
DiversityMetric              | Intra-list diversity (distinct categories / brands)
NoveltyCoverageMetric        | Non-obvious recs — low popularity, not in user's history
StrategyEffectivenessMetric  | Which retrieval strategy (CF/content/trending) drives hits
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evaluation.dataset import EvaluationCase


# ── Shared result type (mirrors DeepEval's MetricResult) ─────────────────────

@dataclass
class MetricResult:
    """Return value for every metric's .measure() call."""
    metric_name: str
    score: float          # 0.0 – 1.0
    passed: bool
    reason: str
    details: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.metric_name}: {self.score:.3f} — {self.reason}"


# ── 1. CartConversionMetric ───────────────────────────────────────────────────

class CartConversionMetric:
    """
    Predicts the likelihood that a recommended product will be added to cart.

    Score is a weighted heuristic (0-1) based on observable product and user
    features — no trained model needed for this POC.

    Feature weights:
      category_match   0.30  — rec category ∈ user's top categories
      price_in_range   0.20  — price within user's historical price range
      high_discount    0.15  — discount_pct > threshold (default 15 %)
      high_rating      0.15  — rating_avg > threshold (default 4.0)
      low_stock_urgency 0.10 — inventory_count < urgency_threshold (default 5)
      trending_signal  0.10  — strategy is "trending" or "trending_views"
    """

    WEIGHTS = {
        "category_match":    0.30,
        "price_in_range":    0.20,
        "high_discount":     0.15,
        "high_rating":       0.15,
        "low_stock_urgency": 0.10,
        "trending_signal":   0.10,
    }

    def __init__(
        self,
        threshold: float = 0.40,
        discount_floor: float = 15.0,
        rating_floor: float = 4.0,
        stock_urgency: int = 5,
    ) -> None:
        self.threshold = threshold
        self.discount_floor = discount_floor
        self.rating_floor = rating_floor
        self.stock_urgency = stock_urgency

    def measure(self, case: "EvaluationCase") -> MetricResult:
        scores_per_item: list[dict] = []
        item_scores: list[float] = []

        profile = case.user_profile or {}
        top_cats = set(profile.get("top_categories", {}).keys())
        price_min = profile.get("price_min", 0)
        price_max = profile.get("price_max", float("inf"))

        for rec in case.recommendations:
            feats = self._features(rec, top_cats, price_min, price_max)
            item_score = sum(self.WEIGHTS[k] * v for k, v in feats.items())
            item_scores.append(item_score)
            scores_per_item.append({
                "product_id": rec.get("product_id"),
                "name": rec.get("name", ""),
                "predicted_conversion": round(item_score, 4),
                "features": {k: round(v, 2) for k, v in feats.items()},
            })

        avg_score = sum(item_scores) / len(item_scores) if item_scores else 0.0
        top3_avg = (
            sum(sorted(item_scores, reverse=True)[:3]) / 3
            if len(item_scores) >= 3
            else avg_score
        )

        # Primary score is average of top-3 conversion probability
        score = top3_avg
        passed = score >= self.threshold

        return MetricResult(
            metric_name="CartConversionMetric",
            score=round(score, 4),
            passed=passed,
            reason=(
                f"Mean top-3 predicted cart-conversion = {score:.3f} "
                f"({'≥' if passed else '<'} threshold {self.threshold})"
            ),
            details={
                "avg_conversion": round(avg_score, 4),
                "top3_conversion": round(top3_avg, 4),
                "per_item": scores_per_item,
            },
        )

    def _features(
        self,
        rec: dict,
        top_cats: set,
        price_min: float,
        price_max: float,
    ) -> dict[str, float]:
        category = rec.get("category", "")
        price = rec.get("price", 0) or 0
        discount = rec.get("discount_pct") or 0
        rating = rec.get("rating_avg") or 0
        stock = rec.get("stock", 999)
        strategy = rec.get("strategy", "")

        effective_price = price * (1 - discount / 100) if discount else price

        return {
            "category_match":    1.0 if category in top_cats else 0.0,
            "price_in_range":    1.0 if price_min <= effective_price <= price_max else (
                0.5 if effective_price <= price_max * 1.3 else 0.0
            ),
            "high_discount":     min(discount / 30, 1.0) if discount >= self.discount_floor else 0.0,
            "high_rating":       min((rating - self.rating_floor) / 1.0, 1.0) if rating >= self.rating_floor else 0.0,
            "low_stock_urgency": 1.0 if 0 < stock <= self.stock_urgency else 0.0,
            "trending_signal":   1.0 if strategy in ("trending", "trending_views", "deals") else 0.0,
        }


# ── 2. RecommendationAccuracyMetric ──────────────────────────────────────────

class RecommendationAccuracyMetric:
    """
    Measures recommendation accuracy using real interaction history as ground truth.

    Ground truth = products the user actually interacted with (add_to_cart,
    purchase, wishlist) AFTER the recommendation snapshot was taken.

    Computes:
      - NDCG@K : Normalised Discounted Cumulative Gain
      - Precision@K : fraction of top-K recs that are in ground truth
      - Recall@K    : fraction of ground truth covered by top-K recs

    Final score = weighted mean of the three.
    """

    def __init__(
        self,
        k: int = 10,
        threshold: float = 0.30,
        weights: tuple[float, float, float] = (0.5, 0.3, 0.2),
    ) -> None:
        self.k = k
        self.threshold = threshold
        self.ndcg_w, self.prec_w, self.rec_w = weights

    def measure(self, case: "EvaluationCase") -> MetricResult:
        gt_ids = set(case.ground_truth_interactions)
        ranked_ids = [r["product_id"] for r in case.recommendations]

        # Build relevance grades: purchase/add_to_cart = 2, wishlist/view = 1
        # For this POC, all ground truth interactions get grade 2
        relevance = {pid: 2 for pid in gt_ids}

        ndcg = self._ndcg_at_k(ranked_ids, relevance)
        prec = self._precision_at_k(ranked_ids, gt_ids)
        recall = self._recall_at_k(ranked_ids, gt_ids)

        score = self.ndcg_w * ndcg + self.prec_w * prec + self.rec_w * recall
        passed = score >= self.threshold

        return MetricResult(
            metric_name="RecommendationAccuracyMetric",
            score=round(score, 4),
            passed=passed,
            reason=(
                f"NDCG@{self.k}={ndcg:.3f} | P@{self.k}={prec:.3f} | R@{self.k}={recall:.3f} → "
                f"weighted={score:.3f} ({'≥' if passed else '<'} {self.threshold})"
            ),
            details={
                f"ndcg_at_{self.k}": round(ndcg, 4),
                f"precision_at_{self.k}": round(prec, 4),
                f"recall_at_{self.k}": round(recall, 4),
                "ground_truth_size": len(gt_ids),
                "recommended_size": len(ranked_ids),
                "hits": [pid for pid in ranked_ids[:self.k] if pid in gt_ids],
            },
        )

    def _ndcg_at_k(self, ranked_ids: list[str], relevance: dict[str, int]) -> float:
        def dcg(ids: list[str]) -> float:
            return sum(
                relevance.get(pid, 0) / math.log2(i + 2)
                for i, pid in enumerate(ids[:self.k])
            )

        ideal_rels = sorted(relevance.values(), reverse=True)
        idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal_rels[:self.k]))
        return dcg(ranked_ids) / idcg if idcg > 0 else 0.0

    def _precision_at_k(self, ranked_ids: list[str], gt: set) -> float:
        hits = sum(1 for pid in ranked_ids[:self.k] if pid in gt)
        return hits / self.k if self.k > 0 else 0.0

    def _recall_at_k(self, ranked_ids: list[str], gt: set) -> float:
        if not gt:
            return 0.0
        hits = sum(1 for pid in ranked_ids[:self.k] if pid in gt)
        return hits / len(gt)


# ── 3. PersonalizationMetric ─────────────────────────────────────────────────

class PersonalizationMetric:
    """
    Measures how well recommendations reflect the user's actual preference profile.

    Score = weighted category overlap between recommended items and the user's
    top categories (weighted by interaction frequency).
    """

    def __init__(self, threshold: float = 0.50) -> None:
        self.threshold = threshold

    def measure(self, case: "EvaluationCase") -> MetricResult:
        profile = case.user_profile or {}
        top_cats: dict[str, int] = profile.get("top_categories") or {}

        if not top_cats or not case.recommendations:
            return MetricResult(
                metric_name="PersonalizationMetric",
                score=0.0,
                passed=False,
                reason="No user profile or recommendations available.",
            )

        total_weight = sum(top_cats.values()) or 1
        score = 0.0
        category_hits: dict[str, int] = {}

        for rec in case.recommendations:
            cat = rec.get("category", "")
            if cat in top_cats:
                cat_weight = top_cats[cat] / total_weight
                score += cat_weight
                category_hits[cat] = category_hits.get(cat, 0) + 1

        # Normalise by number of recommendations
        score = min(score / len(case.recommendations), 1.0)
        passed = score >= self.threshold

        return MetricResult(
            metric_name="PersonalizationMetric",
            score=round(score, 4),
            passed=passed,
            reason=(
                f"Weighted category alignment = {score:.3f} "
                f"({'≥' if passed else '<'} {self.threshold})"
            ),
            details={
                "user_top_categories": top_cats,
                "category_hits_in_recs": category_hits,
                "recommendation_count": len(case.recommendations),
            },
        )


# ── 4. DiversityMetric ───────────────────────────────────────────────────────

class DiversityMetric:
    """
    Intra-list diversity — penalises filter bubbles where all recs are from
    the same category or brand.

    Score = (distinct_categories / total_recs) * 0.6
           + (distinct_brands / total_recs) * 0.4

    A diverse set should cover multiple categories and brands.
    """

    def __init__(self, threshold: float = 0.40) -> None:
        self.threshold = threshold

    def measure(self, case: "EvaluationCase") -> MetricResult:
        recs = case.recommendations
        if not recs:
            return MetricResult(
                metric_name="DiversityMetric",
                score=0.0,
                passed=False,
                reason="No recommendations to evaluate.",
            )

        categories = [r.get("category", "") for r in recs]
        brands = [r.get("brand", "") for r in recs]
        n = len(recs)

        cat_diversity = len(set(categories)) / n
        brand_diversity = len(set(brands)) / n
        score = cat_diversity * 0.6 + brand_diversity * 0.4

        passed = score >= self.threshold

        return MetricResult(
            metric_name="DiversityMetric",
            score=round(score, 4),
            passed=passed,
            reason=(
                f"Category diversity={cat_diversity:.3f} | Brand diversity={brand_diversity:.3f} → "
                f"combined={score:.3f} ({'≥' if passed else '<'} {self.threshold})"
            ),
            details={
                "distinct_categories": len(set(categories)),
                "distinct_brands": len(set(brands)),
                "total_recommendations": n,
                "category_distribution": {c: categories.count(c) for c in set(categories)},
                "brand_distribution": {b: brands.count(b) for b in set(brands)},
            },
        )


# ── 5. NoveltyCoverageMetric ─────────────────────────────────────────────────

class NoveltyCoverageMetric:
    """
    Measures novelty — how many recommendations go beyond obvious popularity.

    A novel item is one that:
      - Is NOT already in the user's purchase history
      - Has a relatively lower popularity score (not just top-sellers)
      - Comes from strategies other than pure "trending"

    Score = (non-obvious items / total_recs) where non-obvious means:
      not in purchase history AND (discount > 0 OR strategy not in trending_strategies)
    """

    TRENDING_STRATEGIES = {"trending", "trending_views"}

    def __init__(self, threshold: float = 0.35) -> None:
        self.threshold = threshold

    def measure(self, case: "EvaluationCase") -> MetricResult:
        recs = case.recommendations
        if not recs:
            return MetricResult(
                metric_name="NoveltyCoverageMetric",
                score=0.0,
                passed=False,
                reason="No recommendations to evaluate.",
            )

        purchased = set(case.purchase_history)
        novel_items = []

        for rec in recs:
            pid = rec.get("product_id", "")
            strategy = rec.get("strategy", "")
            discount = rec.get("discount_pct") or 0

            not_purchased = pid not in purchased
            non_obvious = strategy not in self.TRENDING_STRATEGIES or discount > 10

            if not_purchased and non_obvious:
                novel_items.append(pid)

        score = len(novel_items) / len(recs)
        passed = score >= self.threshold

        return MetricResult(
            metric_name="NoveltyCoverageMetric",
            score=round(score, 4),
            passed=passed,
            reason=(
                f"{len(novel_items)}/{len(recs)} items are novel "
                f"({'≥' if passed else '<'} threshold {self.threshold})"
            ),
            details={
                "novel_product_ids": novel_items,
                "already_purchased": [
                    r["product_id"] for r in recs if r.get("product_id") in purchased
                ],
                "total_recommendations": len(recs),
            },
        )


# ── 6. StrategyEffectivenessMetric ───────────────────────────────────────────

class StrategyEffectivenessMetric:
    """
    Measures which retrieval strategy drives the most accurate hits.

    Splits recommendations by strategy tag (personalized, trending, content,
    category, new_arrival, deals) and computes hit rate per strategy against
    the ground truth interaction set.

    This surfaces whether CF/content/trending is actually earning conversions
    — and which strategy should get more weight in the hybrid ranker.
    """

    def __init__(self, threshold: float = 0.20) -> None:
        self.threshold = threshold

    def measure(self, case: "EvaluationCase") -> MetricResult:
        gt_ids = set(case.ground_truth_interactions)
        recs = case.recommendations

        if not recs:
            return MetricResult(
                metric_name="StrategyEffectivenessMetric",
                score=0.0,
                passed=False,
                reason="No recommendations to evaluate.",
            )

        # Group by strategy
        strategy_map: dict[str, list[str]] = {}
        for rec in recs:
            strat = rec.get("strategy", "unknown")
            pid = rec.get("product_id", "")
            strategy_map.setdefault(strat, []).append(pid)

        strategy_hit_rates: dict[str, float] = {}
        for strat, pids in strategy_map.items():
            hits = sum(1 for p in pids if p in gt_ids)
            strategy_hit_rates[strat] = round(hits / len(pids), 4)

        best_strategy = max(strategy_hit_rates, key=strategy_hit_rates.get) if strategy_hit_rates else "none"
        best_rate = strategy_hit_rates.get(best_strategy, 0.0)

        # Overall score = weighted mean hit rate (weighted by item count per strategy)
        total_items = len(recs)
        overall_hit_rate = (
            sum(
                strategy_hit_rates[s] * len(strategy_map[s])
                for s in strategy_map
            ) / total_items
            if total_items > 0
            else 0.0
        )

        passed = overall_hit_rate >= self.threshold

        return MetricResult(
            metric_name="StrategyEffectivenessMetric",
            score=round(overall_hit_rate, 4),
            passed=passed,
            reason=(
                f"Overall hit rate={overall_hit_rate:.3f} | "
                f"Best strategy: {best_strategy} ({best_rate:.3f}) "
                f"({'≥' if passed else '<'} {self.threshold})"
            ),
            details={
                "strategy_hit_rates": strategy_hit_rates,
                "best_strategy": best_strategy,
                "best_hit_rate": best_rate,
                "strategy_item_counts": {s: len(pids) for s, pids in strategy_map.items()},
                "ground_truth_size": len(gt_ids),
            },
        )
