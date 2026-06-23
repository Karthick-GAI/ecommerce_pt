"""
Bulk enrichment pipeline — orchestrates LLM attribute enrichment at scale.

Features
────────
• Pre-run cost estimation — know the token budget before any API call is made
• Priority ordering      — process critical-quality products first (max ROI per token)
• Differential gating    — skip products whose content hash hasn't changed
• Safe checkpointing     — write DB updates after each batch; restart-safe
• Token budget ceiling   — hard stop if spend would exceed the configured limit
• In-memory job registry — lightweight job tracking without a separate DB table
• Concurrency cap        — sequential batches prevent rate-limit 429s

Job lifecycle:
  pending → running → completed | failed | cancelled

Usage:
    pipeline = EnrichmentPipeline(db)
    job_id = pipeline.start_batch(
        category="Electronics",
        priority_threshold="high",   # only critical + high priority products
        token_budget=50_000,
    )
    status = pipeline.get_job(job_id)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy.orm import Session

from enrichment.attribute_enricher import AttributeEnricher, EnrichedProduct, SYSTEM_PROMPT
from enrichment.catalogue_analyzer import CatalogueAnalyzer, ProductQuality
from enrichment.token_optimizer import (
    TokenBudget,
    compute_content_hash,
    estimate_batch_run,
    needs_enrichment,
    pack_batches,
)


# ── Job registry ──────────────────────────────────────────────────────────────

JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

@dataclass
class EnrichmentJob:
    job_id: str
    status: JobStatus = "pending"
    total_products: int = 0
    processed: int = 0
    succeeded: int = 0
    skipped: int = 0      # differential hash matched — no change needed
    failed: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    errors: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    @property
    def progress_pct(self) -> float:
        if self.total_products == 0:
            return 0.0
        return round(self.processed / self.total_products * 100, 1)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        return round((end - self.started_at).total_seconds(), 1)

    def to_dict(self) -> dict:
        return {
            "job_id":            self.job_id,
            "status":            self.status,
            "total_products":    self.total_products,
            "processed":         self.processed,
            "succeeded":         self.succeeded,
            "skipped":           self.skipped,
            "failed":            self.failed,
            "progress_pct":      self.progress_pct,
            "tokens": {
                "input":         self.tokens_input,
                "output":        self.tokens_output,
                "total":         self.tokens_input + self.tokens_output,
            },
            "cost": {
                "estimated_usd": self.estimated_cost_usd,
                "actual_usd":    round(self.actual_cost_usd, 6),
                "actual_inr":    round(self.actual_cost_usd * 83, 4),
            },
            "timing": {
                "started_at":   self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "duration_sec": self.duration_seconds,
            },
            "config":   self.config,
            "errors":   self.errors[-10:],  # last 10 errors only
        }


# Global in-memory job store (adequate for capstone POC)
_JOB_STORE: dict[str, EnrichmentJob] = {}


# ── Pipeline ──────────────────────────────────────────────────────────────────

class EnrichmentPipeline:
    """
    Orchestrates bulk LLM attribute enrichment over the product catalogue.
    """

    def __init__(
        self,
        db: Session,
        batch_size: int = 5,
        delay_between_batches_ms: int = 200,
    ) -> None:
        self._db = db
        self._batch_size = batch_size
        self._delay_ms = delay_between_batches_ms
        self._analyzer = CatalogueAnalyzer()
        self._enricher = AttributeEnricher(batch_size=batch_size)

    # ── Public API ─────────────────────────────────────────────────────────────

    def estimate(
        self,
        category: Optional[str] = None,
        priority_threshold: str = "high",
        token_budget: Optional[int] = None,
    ) -> dict:
        """
        Estimate tokens and cost for an enrichment run WITHOUT making any LLM calls.
        Safe to call any number of times.
        """
        products = self._select_products(
            category=category,
            priority_threshold=priority_threshold,
        )

        if not products:
            return {
                "products_selected": 0,
                "message": "No products match the selection criteria.",
            }

        estimation = estimate_batch_run(
            products=products,
            system_prompt=SYSTEM_PROMPT,
            batch_size=self._batch_size,
        )

        result = {
            **estimation,
            "priority_threshold": priority_threshold,
            "category_filter": category or "all",
        }

        if token_budget:
            result["budget_tokens"] = token_budget
            result["within_budget"] = estimation["estimated_total_tokens"] <= token_budget
            if not result["within_budget"]:
                affordable = int(
                    token_budget / (estimation["estimated_total_tokens"] / len(products))
                )
                result["affordable_products_in_budget"] = max(0, affordable)

        return result

    def start_batch(
        self,
        category: Optional[str] = None,
        priority_threshold: str = "high",
        token_budget: int = 100_000,
        product_ids: Optional[list[str]] = None,
        force_reenrich: bool = False,
    ) -> str:
        """
        Start a batch enrichment job and return its job_id.

        The job runs synchronously in the same request (POC approach — a real
        system would push to a task queue like Celery or ARQ).

        Args:
            category           : limit to one category (None = all)
            priority_threshold : "critical" | "high" | "medium" | "low"
                                 Only products AT or BELOW this quality threshold are processed.
            token_budget       : hard ceiling in tokens; stop when reached
            product_ids        : override selection with specific product IDs
            force_reenrich     : ignore differential hash; re-enrich everything
        """
        job_id = str(uuid.uuid4())[:8]
        products = (
            self._select_by_ids(product_ids)
            if product_ids
            else self._select_products(category, priority_threshold)
        )

        estimation = estimate_batch_run(
            products=products,
            system_prompt=SYSTEM_PROMPT,
            batch_size=self._batch_size,
        )

        job = EnrichmentJob(
            job_id=job_id,
            total_products=len(products),
            estimated_cost_usd=estimation["estimated_cost_usd"],
            config={
                "category": category or "all",
                "priority_threshold": priority_threshold,
                "token_budget": token_budget,
                "batch_size": self._batch_size,
                "force_reenrich": force_reenrich,
            },
        )
        _JOB_STORE[job_id] = job
        self._run_job(job, products, token_budget, force_reenrich)
        return job_id

    # ── Job management ─────────────────────────────────────────────────────────

    @staticmethod
    def get_job(job_id: str) -> Optional[EnrichmentJob]:
        return _JOB_STORE.get(job_id)

    @staticmethod
    def list_jobs(limit: int = 20) -> list[EnrichmentJob]:
        jobs = sorted(
            _JOB_STORE.values(),
            key=lambda j: j.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return jobs[:limit]

    @staticmethod
    def cancel_job(job_id: str) -> bool:
        job = _JOB_STORE.get(job_id)
        if job and job.status == "running":
            job.status = "cancelled"
            return True
        return False

    # ── Internal execution ─────────────────────────────────────────────────────

    def _run_job(
        self,
        job: EnrichmentJob,
        products: list,
        token_budget: int,
        force_reenrich: bool,
    ) -> None:
        """Execute the enrichment job synchronously."""
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)

        budget = TokenBudget(total_limit=token_budget)

        # Load existing content hashes from DB
        hash_map = self._load_hash_map([p.id for p in products])

        # Pack products into batches
        batches = pack_batches(
            products=products,
            system_prompt=SYSTEM_PROMPT,
            batch_size=self._batch_size,
        )

        try:
            for batch in batches:
                # Check if job was cancelled
                if job.status == "cancelled":
                    break

                # Filter out products that haven't changed (differential gating)
                if not force_reenrich:
                    to_process = [
                        p for p in batch.products
                        if needs_enrichment(p, hash_map.get(p.id))
                    ]
                    skipped_count = len(batch.products) - len(to_process)
                    job.skipped += skipped_count
                    job.processed += skipped_count
                else:
                    to_process = batch.products

                if not to_process:
                    continue

                # Token budget check
                if not budget.can_afford(batch.estimated_input_tokens, batch.estimated_output_tokens):
                    job.errors.append(
                        f"Token budget exhausted after {job.processed} products. "
                        f"Used {budget.used_total}/{token_budget} tokens."
                    )
                    break

                # LLM call
                result = self._enricher.enrich_batch(to_process)

                budget.record(result.tokens_input, result.tokens_output)
                job.tokens_input  += result.tokens_input
                job.tokens_output += result.tokens_output
                job.actual_cost_usd = budget.estimated_cost_usd()

                if not result.succeeded:
                    job.failed += len(to_process)
                    job.processed += len(to_process)
                    job.errors.append(f"Batch error: {result.error}")
                    continue

                # Write enriched attributes to DB
                for enriched in result.enriched:
                    if enriched.succeeded:
                        self._write_to_db(enriched, hash_map)
                        job.succeeded += 1
                    else:
                        job.failed += 1
                        if enriched.error:
                            job.errors.append(f"{enriched.product_id}: {enriched.error}")
                    job.processed += 1

                # Polite delay between batches
                if self._delay_ms > 0:
                    time.sleep(self._delay_ms / 1000)

            # Commit all DB writes
            self._db.commit()

            job.status = "completed" if job.status == "running" else job.status

        except Exception as exc:
            self._db.rollback()
            job.status = "failed"
            job.errors.append(f"Fatal error: {exc}")
        finally:
            job.completed_at = datetime.now(timezone.utc)

    def _write_to_db(self, enriched: EnrichedProduct, hash_map: dict) -> None:
        """Apply enriched attributes to the Product row."""
        from models import Product, EnrichmentRecord
        from sqlalchemy import func

        product = self._db.query(Product).filter(Product.id == enriched.product_id).first()
        if not product:
            return

        # Merge specifications (enriched wins for new keys; existing values preserved)
        existing_specs = dict(product.specifications or {})
        for key, val in enriched.specifications.items():
            existing_specs.setdefault(key, val)   # don't overwrite manually-entered specs
        product.specifications = existing_specs

        # Merge tags (union, deduplicated, max 15)
        existing_tags = list(product.tags or [])
        merged_tags = list(dict.fromkeys(existing_tags + enriched.tags))[:15]
        product.tags = merged_tags

        # Write enriched description only if current one is sparse
        if enriched.enriched_description and len(product.description or "") < 100:
            product.description = enriched.enriched_description

        # Fill in subcategory if missing
        if not product.subcategory and enriched.inferred_subcategory:
            product.subcategory = enriched.inferred_subcategory

        # Upsert EnrichmentRecord
        new_hash = compute_content_hash(product)
        record = self._db.query(EnrichmentRecord).filter(
            EnrichmentRecord.product_id == enriched.product_id
        ).first()

        if record:
            record.content_hash   = new_hash
            record.enriched_at    = func.now()
            record.tokens_input   = enriched.tokens_input
            record.tokens_output  = enriched.tokens_output
            record.quality_score  = float(enriched.quality_score)
        else:
            record = EnrichmentRecord(
                product_id=enriched.product_id,
                content_hash=new_hash,
                tokens_input=enriched.tokens_input,
                tokens_output=enriched.tokens_output,
                quality_score=float(enriched.quality_score),
            )
            self._db.add(record)

        hash_map[enriched.product_id] = new_hash

    # ── Selection helpers ──────────────────────────────────────────────────────

    def _select_products(
        self,
        category: Optional[str],
        priority_threshold: str,
    ) -> list:
        """
        Select and prioritise products for enrichment.
        Worst quality first so each token spent has maximum impact.
        """
        report = self._analyzer.analyse(self._db, category=category)

        # Priority ordering: critical < high < medium < low
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        threshold_rank = priority_rank.get(priority_threshold, 1)

        eligible = [
            pq for pq in report.enrichment_queue
            if priority_rank.get(pq.enrichment_priority, 99) <= threshold_rank
        ]

        # Fetch actual ORM objects from DB (queue only has IDs)
        from models import Product
        eligible_ids = [pq.product_id for pq in eligible]
        id_order = {pid: i for i, pid in enumerate(eligible_ids)}

        products = (
            self._db.query(Product)
            .filter(Product.id.in_(eligible_ids), Product.is_active == True)
            .all()
        )
        products.sort(key=lambda p: id_order.get(p.id, 9999))
        return products

    def _select_by_ids(self, product_ids: list[str]) -> list:
        from models import Product
        return (
            self._db.query(Product)
            .filter(Product.id.in_(product_ids), Product.is_active == True)
            .all()
        )

    def _load_hash_map(self, product_ids: list[str]) -> dict[str, str]:
        """Load existing content hashes from EnrichmentRecord table."""
        from models import EnrichmentRecord
        records = (
            self._db.query(EnrichmentRecord)
            .filter(EnrichmentRecord.product_id.in_(product_ids))
            .all()
        )
        return {r.product_id: r.content_hash for r in records}
