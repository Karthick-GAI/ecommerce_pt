"""
Catalogue analyser — rule-based quality scoring and gap detection.

No LLM calls here.  The analyser runs in milliseconds over thousands of products
and produces a ranked enrichment queue so the pipeline can tackle the worst-quality
products first (maximising quality improvement per token spent).

Quality score breakdown (0–100):
  description_score   0–30  richness of the description text
  specs_score         0–30  structured specification coverage
  tags_score          0–20  searchable tag coverage
  category_score      0–20  category + subcategory completeness
  ──────────────────────────
  total               0–100
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Per-product scoring ───────────────────────────────────────────────────────

@dataclass
class ProductQuality:
    """Quality assessment for a single product."""
    product_id: str
    name: str
    category: str
    subcategory: Optional[str]

    description_score: int = 0    # 0-30
    specs_score: int = 0          # 0-30
    tags_score: int = 0           # 0-20
    category_score: int = 0       # 0-20
    total_score: int = 0          # 0-100

    description_length: int = 0
    spec_count: int = 0
    tag_count: int = 0
    missing_fields: list[str] = field(default_factory=list)
    enrichment_priority: str = "low"   # critical | high | medium | low

    def to_dict(self) -> dict:
        return {
            "product_id":        self.product_id,
            "name":              self.name,
            "category":          self.category,
            "subcategory":       self.subcategory,
            "total_score":       self.total_score,
            "breakdown": {
                "description":   self.description_score,
                "specifications": self.specs_score,
                "tags":          self.tags_score,
                "category":      self.category_score,
            },
            "description_length": self.description_length,
            "spec_count":        self.spec_count,
            "tag_count":         self.tag_count,
            "missing_fields":    self.missing_fields,
            "enrichment_priority": self.enrichment_priority,
        }


# ── Catalogue-level report ────────────────────────────────────────────────────

@dataclass
class CatalogueReport:
    """Aggregated quality report across the full catalogue."""
    total_products: int = 0
    avg_quality_score: float = 0.0
    score_distribution: dict[str, int] = field(default_factory=dict)
    # {0-24: N, 25-49: N, 50-74: N, 75-100: N}
    priority_breakdown: dict[str, int] = field(default_factory=dict)
    # {critical: N, high: N, medium: N, low: N}
    coverage: dict[str, float] = field(default_factory=dict)
    # {has_description: %, has_specs: %, has_tags: %, has_subcategory: %}
    top_missing_fields: list[dict] = field(default_factory=list)
    enrichment_queue: list[ProductQuality] = field(default_factory=list)
    # sorted worst-first; these products benefit most from enrichment
    category_quality: dict[str, float] = field(default_factory=dict)
    # {category_name: avg_quality}

    def summary(self) -> dict:
        return {
            "total_products":    self.total_products,
            "avg_quality_score": round(self.avg_quality_score, 1),
            "score_distribution": self.score_distribution,
            "priority_breakdown": self.priority_breakdown,
            "coverage":          {k: round(v, 3) for k, v in self.coverage.items()},
            "top_missing_fields": self.top_missing_fields,
            "category_quality":  {k: round(v, 1) for k, v in self.category_quality.items()},
            "products_needing_enrichment": sum(
                1 for p in self.enrichment_queue
                if p.enrichment_priority in ("critical", "high")
            ),
        }


# ── Analyser ──────────────────────────────────────────────────────────────────

class CatalogueAnalyzer:
    """
    Scores every active product in the catalogue and builds an enrichment queue.

    Usage:
        from sqlalchemy.orm import Session
        analyzer = CatalogueAnalyzer()
        report = analyzer.analyse(db)
        logging.getLogger(__name__).info(report.summary())
    """

    def analyse(
        self,
        db,
        category: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> CatalogueReport:
        """
        Score all active products and return a CatalogueReport.

        Args:
            db       : SQLAlchemy session
            category : optional filter to one category
            limit    : optional cap on products scanned (for quick previews)
        """
        from models import Product
        q = db.query(Product).filter(Product.is_active == True)
        if category:
            q = q.filter(Product.category == category)
        if limit:
            q = q.limit(limit)

        products = q.all()

        quality_list: list[ProductQuality] = [
            self._score_product(p) for p in products
        ]

        return self._build_report(quality_list)

    def score_product(self, product) -> ProductQuality:
        """Score a single product — useful for inline quality checks."""
        return self._score_product(product)

    # ── Scoring logic ─────────────────────────────────────────────────────────

    @staticmethod
    def _score_product(p) -> ProductQuality:
        missing: list[str] = []

        # ── Description score (0–30) ─────────────────────────────────────
        desc = p.description or ""
        desc_len = len(desc)
        if desc_len == 0:
            desc_score = 0
            missing.append("description")
        elif desc_len < 80:
            desc_score = 8
        elif desc_len < 200:
            desc_score = 16
        elif desc_len < 400:
            desc_score = 22
        else:
            desc_score = 30

        # Bonus: description contains measurable specs (e.g. "8GB", "15.6-inch")
        spec_pattern = re.compile(
            r"\d[\d.,]*\s*(gb|mb|tb|mah|hz|inch|mm|kg|w|v|rpm|mp|fps|nm|ms|hr|dpi|nits|cm)",
            re.IGNORECASE,
        )
        if spec_pattern.search(desc):
            desc_score = min(30, desc_score + 4)

        # ── Specifications score (0–30) ──────────────────────────────────
        specs = p.specifications or {}
        spec_count = len(specs)
        if spec_count == 0:
            specs_score = 0
            missing.append("specifications")
        else:
            # 5 pts per key, capped at 30
            specs_score = min(30, spec_count * 5)

        # ── Tags score (0–20) ────────────────────────────────────────────
        tags = p.tags or []
        tag_count = len(tags)
        if tag_count == 0:
            tags_score = 0
            missing.append("tags")
        else:
            # 4 pts per tag, capped at 20
            tags_score = min(20, tag_count * 4)

        # ── Category score (0–20) ────────────────────────────────────────
        cat_score = 10  # base: category always exists
        if p.subcategory:
            cat_score = 20
        else:
            missing.append("subcategory")

        total = desc_score + specs_score + tags_score + cat_score

        # ── Priority tier ────────────────────────────────────────────────
        if total < 25:
            priority = "critical"
        elif total < 50:
            priority = "high"
        elif total < 75:
            priority = "medium"
        else:
            priority = "low"

        return ProductQuality(
            product_id=p.id,
            name=p.name,
            category=p.category,
            subcategory=p.subcategory,
            description_score=desc_score,
            specs_score=specs_score,
            tags_score=tags_score,
            category_score=cat_score,
            total_score=total,
            description_length=desc_len,
            spec_count=spec_count,
            tag_count=tag_count,
            missing_fields=missing,
            enrichment_priority=priority,
        )

    # ── Report assembly ───────────────────────────────────────────────────────

    @staticmethod
    def _build_report(quality_list: list[ProductQuality]) -> CatalogueReport:
        if not quality_list:
            return CatalogueReport()

        total = len(quality_list)
        avg_score = sum(q.total_score for q in quality_list) / total

        # Score distribution
        dist = {"0–24": 0, "25–49": 0, "50–74": 0, "75–100": 0}
        for q in quality_list:
            if q.total_score < 25:
                dist["0–24"] += 1
            elif q.total_score < 50:
                dist["25–49"] += 1
            elif q.total_score < 75:
                dist["50–74"] += 1
            else:
                dist["75–100"] += 1

        # Priority breakdown
        priority_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for q in quality_list:
            priority_counts[q.enrichment_priority] += 1

        # Coverage rates
        coverage = {
            "has_description":  sum(1 for q in quality_list if q.description_length > 0) / total,
            "has_specs":        sum(1 for q in quality_list if q.spec_count > 0) / total,
            "has_tags":         sum(1 for q in quality_list if q.tag_count > 0) / total,
            "has_subcategory":  sum(1 for q in quality_list if q.subcategory) / total,
        }

        # Top missing fields
        field_counts: dict[str, int] = {}
        for q in quality_list:
            for f in q.missing_fields:
                field_counts[f] = field_counts.get(f, 0) + 1
        top_missing = [
            {"field": f, "missing_count": c, "missing_pct": round(c / total * 100, 1)}
            for f, c in sorted(field_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        # Category quality
        cat_groups: dict[str, list[int]] = {}
        for q in quality_list:
            cat_groups.setdefault(q.category, []).append(q.total_score)
        cat_quality = {
            cat: sum(scores) / len(scores)
            for cat, scores in cat_groups.items()
        }

        # Enrichment queue: worst quality first (most benefit per token)
        queue = sorted(quality_list, key=lambda q: q.total_score)

        return CatalogueReport(
            total_products=total,
            avg_quality_score=avg_score,
            score_distribution=dist,
            priority_breakdown=priority_counts,
            coverage=coverage,
            top_missing_fields=top_missing,
            enrichment_queue=queue,
            category_quality=cat_quality,
        )
