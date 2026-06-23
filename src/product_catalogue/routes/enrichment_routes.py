"""
Enrichment API — token-optimised LLM attribute enrichment for the product catalogue.

Endpoints
─────────
GET  /enrichment/analyse                 — catalogue quality report (no LLM, instant)
GET  /enrichment/estimate                — token & cost estimate before running
POST /enrichment/enrich/{product_id}     — enrich a single product right now
POST /enrichment/batch                   — start a batch enrichment job
GET  /enrichment/jobs/{job_id}           — check job progress
GET  /enrichment/jobs                    — list recent jobs
DELETE /enrichment/jobs/{job_id}         — cancel a running job
POST /enrichment/reindex/{product_id}    — re-embed a product after enrichment

All write operations respect the token budget and differential hash gate,
so it is safe to call them repeatedly without duplicate LLM spend.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from enrichment.attribute_enricher import AttributeEnricher
from enrichment.catalogue_analyzer import CatalogueAnalyzer
from enrichment.pipeline import EnrichmentPipeline
from enrichment.attribute_enricher import SYSTEM_PROMPT
from enrichment.token_optimizer import (
    estimate_batch_run,
    estimate_tokens,
)

router = APIRouter(prefix="/enrichment", tags=["Enrichment"])


# ── Request / response schemas ─────────────────────────────────────────────────

class BatchRequest(BaseModel):
    category: Optional[str] = Field(
        default=None,
        description="Limit enrichment to one category. Omit for all categories.",
    )
    priority_threshold: Literal["critical", "high", "medium", "low"] = Field(
        default="high",
        description=(
            "Only enrich products AT or BELOW this quality tier. "
            "'critical' = only the worst; 'low' = everything."
        ),
    )
    token_budget: int = Field(
        default=100_000,
        ge=1_000,
        le=1_000_000,
        description="Hard token ceiling for this job. The job stops when reached.",
    )
    product_ids: Optional[list[str]] = Field(
        default=None,
        description="Override automatic selection with specific product IDs.",
    )
    force_reenrich: bool = Field(
        default=False,
        description="Ignore differential hash and re-enrich all selected products.",
    )
    batch_size: int = Field(
        default=5, ge=1, le=10,
        description="Products per LLM call. Higher = cheaper per product, longer latency.",
    )


class EstimateRequest(BaseModel):
    category: Optional[str] = None
    priority_threshold: Literal["critical", "high", "medium", "low"] = "high"
    token_budget: Optional[int] = Field(default=None, ge=1_000)
    batch_size: int = Field(default=5, ge=1, le=10)


# ── GET /enrichment/analyse ───────────────────────────────────────────────────

@router.get("/analyse")
def analyse_catalogue(
    category: Optional[str] = Query(default=None),
    limit:    Optional[int] = Query(default=None, ge=1, le=5000,
                                    description="Cap on products scanned (for quick previews)"),
    db: Session = Depends(get_db),
):
    """
    Scan the catalogue and return a quality report with enrichment priorities.

    This is a pure DB scan — no LLM calls, no token spend.
    Use this to understand the catalogue's attribute health before deciding
    how much budget to allocate for enrichment.
    """
    analyzer = CatalogueAnalyzer()
    report = analyzer.analyse(db, category=category, limit=limit)

    return {
        **report.summary(),
        "enrichment_queue_preview": [
            q.to_dict() for q in report.enrichment_queue[:20]
        ],
    }


# ── GET /enrichment/estimate ──────────────────────────────────────────────────

@router.post("/estimate")
def estimate_enrichment(body: EstimateRequest, db: Session = Depends(get_db)):
    """
    Estimate token usage and cost for an enrichment run WITHOUT making any LLM calls.

    Returns the number of products selected, batches required, total tokens,
    and estimated cost in USD and INR — so you can decide the right budget
    before spending a single rupee.
    """
    pipeline = EnrichmentPipeline(db, batch_size=body.batch_size)
    return pipeline.estimate(
        category=body.category,
        priority_threshold=body.priority_threshold,
        token_budget=body.token_budget,
    )


# ── POST /enrichment/enrich/{product_id} ──────────────────────────────────────

@router.post("/enrich/{product_id}")
def enrich_single_product(
    product_id: str,
    force: bool = Query(default=False, description="Skip differential hash check."),
    db: Session = Depends(get_db),
):
    """
    Enrich a single product's attributes using the LLM right now.

    Checks the differential hash first — if the product content hasn't changed
    since the last enrichment, returns the cached result immediately (zero tokens spent).
    Pass ?force=true to override and re-enrich regardless.
    """
    from models import Product, EnrichmentRecord
    from enrichment.token_optimizer import compute_content_hash, needs_enrichment

    product = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Differential hash check
    record = db.query(EnrichmentRecord).filter(
        EnrichmentRecord.product_id == product_id
    ).first()
    stored_hash = record.content_hash if record else None

    if not force and not needs_enrichment(product, stored_hash):
        return {
            "product_id":   product_id,
            "status":       "skipped",
            "reason":       "Content unchanged since last enrichment (differential hash match).",
            "quality_score": record.quality_score if record else None,
            "tokens_used":  0,
        }

    # Single-product enrichment (still uses batch machinery internally)
    enricher = AttributeEnricher(batch_size=1)
    enriched = enricher.enrich_single(product)

    if not enriched.succeeded:
        raise HTTPException(
            status_code=502,
            detail=f"LLM enrichment failed: {enriched.error}",
        )

    # Write to DB
    _apply_enrichment(db, product, enriched)
    db.commit()

    return {
        "product_id":           product_id,
        "status":               "enriched",
        "specifications_added": len(enriched.specifications),
        "tags_generated":       len(enriched.tags),
        "subcategory_inferred": enriched.inferred_subcategory,
        "quality_score":        enriched.quality_score,
        "tokens": {
            "input":  enriched.tokens_input,
            "output": enriched.tokens_output,
            "cost_usd": enriched.cost_usd,
        },
        "preview": {
            "specifications": dict(list(enriched.specifications.items())[:5]),
            "tags":           enriched.tags[:8],
            "description_snippet": enriched.enriched_description[:120] + "..."
            if len(enriched.enriched_description) > 120
            else enriched.enriched_description,
        },
    }


# ── POST /enrichment/batch ────────────────────────────────────────────────────

@router.post("/batch", status_code=202)
def start_batch_enrichment(body: BatchRequest, db: Session = Depends(get_db)):
    """
    Start a batch enrichment job.

    Processes products in priority order (worst quality first) to maximise
    quality improvement per token spent. Returns a job_id immediately;
    check /enrichment/jobs/{job_id} for progress.

    Token optimisation applied automatically:
      • Text compression (15–30 % token reduction)
      • Batch packing ({batch_size} products per LLM call)
      • Prompt caching (stable system prompt shared across all calls)
      • Differential hashing (skips unchanged products)
      • Token budget ceiling (hard stop at {token_budget} tokens)
    """
    pipeline = EnrichmentPipeline(db, batch_size=body.batch_size)
    job_id = pipeline.start_batch(
        category=body.category,
        priority_threshold=body.priority_threshold,
        token_budget=body.token_budget,
        product_ids=body.product_ids,
        force_reenrich=body.force_reenrich,
    )
    return {
        "job_id":  job_id,
        "status":  "completed",   # synchronous in this POC
        "message": f"Enrichment job {job_id} completed. GET /enrichment/jobs/{job_id} for details.",
    }


# ── GET /enrichment/jobs/{job_id} ─────────────────────────────────────────────

@router.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    """Check the status and metrics of an enrichment job."""
    job = EnrichmentPipeline.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job.to_dict()


# ── GET /enrichment/jobs ──────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(limit: int = Query(default=20, ge=1, le=100)):
    """List recent enrichment jobs, newest first."""
    jobs = EnrichmentPipeline.list_jobs(limit=limit)
    return {
        "total": len(jobs),
        "jobs":  [j.to_dict() for j in jobs],
    }


# ── DELETE /enrichment/jobs/{job_id} ─────────────────────────────────────────

@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str):
    """Cancel a running enrichment job."""
    cancelled = EnrichmentPipeline.cancel_job(job_id)
    if not cancelled:
        job = EnrichmentPipeline.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is in status '{job.status}' and cannot be cancelled.",
        )
    return {"job_id": job_id, "status": "cancelled"}


# ── POST /enrichment/reindex/{product_id} ────────────────────────────────────

@router.post("/reindex/{product_id}")
def reindex_product(product_id: str, db: Session = Depends(get_db)):
    """
    Re-generate the semantic embedding for a product after enrichment.

    Call this after /enrich/{id} to ensure the vector store reflects the
    newly enriched description, tags, and specifications.
    """
    from models import Product
    from embeddings import embed_text, build_product_text

    product = db.query(Product).filter(
        Product.id == product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product_text = build_product_text(product)
    product.embedding = embed_text(product_text)
    db.commit()

    return {
        "product_id": product_id,
        "status":     "reindexed",
        "text_length": len(product_text),
        "tokens_estimated": estimate_tokens(product_text),
    }


# ── Helper ─────────────────────────────────────────────────────────────────────

def _apply_enrichment(db: Session, product, enriched) -> None:
    """Write enriched attributes to the Product row and upsert EnrichmentRecord."""
    from models import EnrichmentRecord
    from enrichment.token_optimizer import compute_content_hash
    from datetime import datetime

    # Merge specs (don't overwrite existing manual entries)
    existing = dict(product.specifications or {})
    for k, v in enriched.specifications.items():
        existing.setdefault(k, v)
    product.specifications = existing

    # Merge tags
    merged = list(dict.fromkeys((product.tags or []) + enriched.tags))[:15]
    product.tags = merged

    # Description: only update if current one is sparse
    if enriched.enriched_description and len(product.description or "") < 100:
        product.description = enriched.enriched_description

    # Subcategory: fill if missing
    if not product.subcategory and enriched.inferred_subcategory:
        product.subcategory = enriched.inferred_subcategory

    # Upsert enrichment record
    new_hash = compute_content_hash(product)
    record = db.query(EnrichmentRecord).filter(
        EnrichmentRecord.product_id == product.id
    ).first()

    if record:
        record.content_hash  = new_hash
        record.enriched_at   = datetime.utcnow()
        record.tokens_input  = enriched.tokens_input
        record.tokens_output = enriched.tokens_output
        record.quality_score = float(enriched.quality_score)
    else:
        db.add(EnrichmentRecord(
            product_id=product.id,
            content_hash=new_hash,
            tokens_input=enriched.tokens_input,
            tokens_output=enriched.tokens_output,
            quality_score=float(enriched.quality_score),
        ))
