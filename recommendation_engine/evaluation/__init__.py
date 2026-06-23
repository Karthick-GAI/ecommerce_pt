"""
Recommendation evaluation framework — DeepEval-equivalent for this POC.

Architecture mirrors DeepEval's metric-class pattern:
  - Each metric is a class with a .measure(case) -> MetricResult
  - EvaluationCase holds the recommendation input/output + ground truth
  - Evaluator runs all metrics and produces a structured report

Metrics implemented:
  CartConversionMetric          — predicted cart-add probability per recommendation
  RecommendationAccuracyMetric  — NDCG@K / Precision@K / Recall@K vs. real interactions
  PersonalizationMetric         — category overlap with user's actual preference profile
  DiversityMetric               — intra-list category diversity
  NoveltyCoverageMetric         — fraction of non-obvious / non-popular items
  StrategyEffectivenessMetric   — which strategy (CF/content/trending) drives hits
"""
from evaluation.metrics import (
    CartConversionMetric,
    RecommendationAccuracyMetric,
    PersonalizationMetric,
    DiversityMetric,
    NoveltyCoverageMetric,
    StrategyEffectivenessMetric,
)
from evaluation.dataset import EvaluationCase, build_evaluation_cases
from evaluation.evaluator import RecommendationEvaluator, EvaluationReport

__all__ = [
    "CartConversionMetric",
    "RecommendationAccuracyMetric",
    "PersonalizationMetric",
    "DiversityMetric",
    "NoveltyCoverageMetric",
    "StrategyEffectivenessMetric",
    "EvaluationCase",
    "build_evaluation_cases",
    "RecommendationEvaluator",
    "EvaluationReport",
]
