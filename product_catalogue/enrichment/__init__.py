"""
Token-optimised LLM attribute enrichment for the product catalogue.

Quick start:
    from enrichment import CatalogueAnalyzer, EnrichmentPipeline

    # 1. Analyse without any LLM calls
    report = CatalogueAnalyzer().analyse(db)
    print(report.summary())

    # 2. Estimate cost before spending tokens
    pipeline = EnrichmentPipeline(db)
    estimate = pipeline.estimate(priority_threshold="high", token_budget=50_000)

    # 3. Run enrichment
    job_id = pipeline.start_batch(priority_threshold="high", token_budget=50_000)
    status = EnrichmentPipeline.get_job(job_id)
"""
from enrichment.token_optimizer import (
    TokenBudget,
    estimate_tokens,
    estimate_cost,
    estimate_batch_run,
    compress_description,
    compute_content_hash,
    pack_batches,
)
from enrichment.attribute_enricher import AttributeEnricher, EnrichedProduct, SYSTEM_PROMPT
from enrichment.catalogue_analyzer import CatalogueAnalyzer, CatalogueReport, ProductQuality
from enrichment.pipeline import EnrichmentPipeline, EnrichmentJob

__all__ = [
    # Token optimizer
    "TokenBudget",
    "estimate_tokens",
    "estimate_cost",
    "estimate_batch_run",
    "compress_description",
    "compute_content_hash",
    "pack_batches",
    # Enricher
    "AttributeEnricher",
    "EnrichedProduct",
    "SYSTEM_PROMPT",
    # Analyzer
    "CatalogueAnalyzer",
    "CatalogueReport",
    "ProductQuality",
    # Pipeline
    "EnrichmentPipeline",
    "EnrichmentJob",
]
