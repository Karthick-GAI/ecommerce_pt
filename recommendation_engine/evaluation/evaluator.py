"""
RecommendationEvaluator — orchestrates all metrics over a set of EvaluationCases.

Mirrors DeepEval's evaluate() function pattern:
  evaluator = RecommendationEvaluator()
  report = evaluator.run(cases)
  print(report.summary())

The evaluator runs all six metrics on each case and aggregates results into
an EvaluationReport with per-user and aggregate statistics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from evaluation.dataset import EvaluationCase
from evaluation.metrics import (
    CartConversionMetric,
    RecommendationAccuracyMetric,
    PersonalizationMetric,
    DiversityMetric,
    NoveltyCoverageMetric,
    StrategyEffectivenessMetric,
    MetricResult,
)


# ── Per-case result ───────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    """Evaluation results for a single user case."""
    user_id: str
    recommendation_count: int
    ground_truth_count: int
    metric_results: list[MetricResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for m in self.metric_results if m.passed)

    @property
    def total_metrics(self) -> int:
        return len(self.metric_results)

    @property
    def pass_rate(self) -> float:
        return self.passed_count / self.total_metrics if self.total_metrics else 0.0

    @property
    def avg_score(self) -> float:
        scores = [m.score for m in self.metric_results]
        return sum(scores) / len(scores) if scores else 0.0

    def metric_by_name(self, name: str) -> MetricResult | None:
        return next((m for m in self.metric_results if m.metric_name == name), None)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "recommendation_count": self.recommendation_count,
            "ground_truth_count": self.ground_truth_count,
            "pass_rate": round(self.pass_rate, 4),
            "avg_score": round(self.avg_score, 4),
            "metrics": {
                m.metric_name: {
                    "score": m.score,
                    "passed": m.passed,
                    "reason": m.reason,
                }
                for m in self.metric_results
            },
        }


# ── Aggregated report ─────────────────────────────────────────────────────────

@dataclass
class EvaluationReport:
    """
    Aggregated evaluation across all users.

    Attributes
    ----------
    case_results        : per-user CaseResult objects
    metric_pass_rates   : {metric_name: fraction of users that passed}
    metric_avg_scores   : {metric_name: mean score across all users}
    overall_pass_rate   : fraction of (user, metric) pairs that passed
    overall_avg_score   : mean score across all (user, metric) pairs
    failing_users       : user_ids where pass_rate < 0.5 (most metrics failed)
    """
    case_results: list[CaseResult]
    metric_pass_rates: dict[str, float] = field(default_factory=dict)
    metric_avg_scores: dict[str, float] = field(default_factory=dict)
    overall_pass_rate: float = 0.0
    overall_avg_score: float = 0.0
    failing_users: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "users_evaluated": len(self.case_results),
            "overall_pass_rate": round(self.overall_pass_rate, 4),
            "overall_avg_score": round(self.overall_avg_score, 4),
            "failing_users": self.failing_users,
            "metric_pass_rates": {k: round(v, 4) for k, v in self.metric_pass_rates.items()},
            "metric_avg_scores": {k: round(v, 4) for k, v in self.metric_avg_scores.items()},
        }

    def weakest_metric(self) -> str:
        if not self.metric_avg_scores:
            return "none"
        return min(self.metric_avg_scores, key=self.metric_avg_scores.get)

    def strongest_metric(self) -> str:
        if not self.metric_avg_scores:
            return "none"
        return max(self.metric_avg_scores, key=self.metric_avg_scores.get)

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "weakest_metric": self.weakest_metric(),
            "strongest_metric": self.strongest_metric(),
            "per_user": [c.to_dict() for c in self.case_results],
        }


# ── Evaluator ─────────────────────────────────────────────────────────────────

class RecommendationEvaluator:
    """
    Runs all recommendation quality metrics over a list of EvaluationCases.

    Usage:
        evaluator = RecommendationEvaluator()
        report = evaluator.run(cases)
        print(report.summary())

    Customise thresholds by passing metric instances:
        evaluator = RecommendationEvaluator(
            metrics=[
                CartConversionMetric(threshold=0.5),
                RecommendationAccuracyMetric(k=5, threshold=0.25),
            ]
        )
    """

    DEFAULT_METRICS = [
        CartConversionMetric,
        RecommendationAccuracyMetric,
        PersonalizationMetric,
        DiversityMetric,
        NoveltyCoverageMetric,
        StrategyEffectivenessMetric,
    ]

    def __init__(self, metrics: list | None = None) -> None:
        if metrics is not None:
            self._metrics = metrics
        else:
            self._metrics = [cls() for cls in self.DEFAULT_METRICS]

    def run(self, cases: list[EvaluationCase]) -> EvaluationReport:
        """Run all metrics on all cases and return an aggregated EvaluationReport."""
        case_results: list[CaseResult] = []

        for case in cases:
            metric_results = []
            for metric in self._metrics:
                try:
                    result = metric.measure(case)
                except Exception as exc:
                    result = MetricResult(
                        metric_name=type(metric).__name__,
                        score=0.0,
                        passed=False,
                        reason=f"Error during evaluation: {exc}",
                    )
                metric_results.append(result)

            case_results.append(
                CaseResult(
                    user_id=case.user_id,
                    recommendation_count=len(case.recommendations),
                    ground_truth_count=len(case.ground_truth_interactions),
                    metric_results=metric_results,
                )
            )

        return self._aggregate(case_results)

    def run_single(self, case: EvaluationCase) -> CaseResult:
        """Evaluate a single case — useful for real-time API evaluation."""
        metric_results = []
        for metric in self._metrics:
            try:
                result = metric.measure(case)
            except Exception as exc:
                result = MetricResult(
                    metric_name=type(metric).__name__,
                    score=0.0,
                    passed=False,
                    reason=f"Error: {exc}",
                )
            metric_results.append(result)

        return CaseResult(
            user_id=case.user_id,
            recommendation_count=len(case.recommendations),
            ground_truth_count=len(case.ground_truth_interactions),
            metric_results=metric_results,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(case_results: list[CaseResult]) -> EvaluationReport:
        if not case_results:
            return EvaluationReport(case_results=[])

        metric_names = [m.metric_name for m in case_results[0].metric_results]

        # Per-metric aggregation
        metric_pass_rates: dict[str, float] = {}
        metric_avg_scores: dict[str, float] = {}

        for name in metric_names:
            results_for_metric = [
                cr.metric_by_name(name)
                for cr in case_results
                if cr.metric_by_name(name) is not None
            ]
            if results_for_metric:
                metric_pass_rates[name] = sum(
                    1 for r in results_for_metric if r.passed
                ) / len(results_for_metric)
                metric_avg_scores[name] = sum(
                    r.score for r in results_for_metric
                ) / len(results_for_metric)

        # Overall stats
        all_scores = [m.score for cr in case_results for m in cr.metric_results]
        all_passed = [m.passed for cr in case_results for m in cr.metric_results]

        overall_avg = sum(all_scores) / len(all_scores) if all_scores else 0.0
        overall_pass = sum(all_passed) / len(all_passed) if all_passed else 0.0

        failing_users = [
            cr.user_id for cr in case_results if cr.pass_rate < 0.5
        ]

        return EvaluationReport(
            case_results=case_results,
            metric_pass_rates=metric_pass_rates,
            metric_avg_scores=metric_avg_scores,
            overall_pass_rate=round(overall_pass, 4),
            overall_avg_score=round(overall_avg, 4),
            failing_users=failing_users,
        )
