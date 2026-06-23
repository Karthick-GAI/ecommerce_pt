"""
LLM-based attribute enricher for the product catalogue.

For each product batch, Claude / GPT-mini is asked to produce:
  • specifications  — structured key-value dict extracted from description
  • tags            — normalised, search-optimised keyword list
  • enriched_description — clean, SEO-friendly rewrite (≤ 3 sentences)
  • inferred_subcategory — inferred if the field is currently blank
  • quality_score   — 0-100 completeness score for the enriched output

Design decisions for token efficiency
──────────────────────────────────────
• Single shared SYSTEM_PROMPT constant → identical on every call → prompt cache hit
• 5 products per call (batch packing) — one system prompt pays for 5 enrichments
• Compressed product text (name + key sentences + existing specs only)
• Structured JSON output with an explicit schema sent in the prompt →
  model produces compact, parseable output, not verbose prose
• Output schema is minimal: no redundant fields, no explanations asked
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ── LLM client (Azure OpenAI, consistent with rest of the service) ─────────────
try:
    from openai import AzureOpenAI as _AzureOpenAI
    _llm_client = _AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
    )
    _GPT_MODEL = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-4o-mini")
    LLM_AVAILABLE = bool(os.getenv("AZURE_OPENAI_API_KEY"))
except Exception:
    _llm_client = None
    _GPT_MODEL = "gpt-4o-mini"
    LLM_AVAILABLE = False


from enrichment.token_optimizer import (
    build_compressed_product_text,
    estimate_tokens,
    TokenBudget,
)


# ── System prompt — kept byte-identical for prompt cache hits ─────────────────
# Do NOT modify the whitespace or wording between calls.

SYSTEM_PROMPT = """You are a product data enrichment engine for an Indian e-commerce platform.
Given a batch of products, extract and infer structured attributes for each.

Return ONLY a valid JSON object with this exact schema (no extra keys, no prose):
{
  "results": [
    {
      "product_id": "<string>",
      "specifications": {"<key>": "<value>"},
      "tags": ["<keyword>"],
      "enriched_description": "<string, max 3 sentences, keyword-rich>",
      "inferred_subcategory": "<string or null>",
      "quality_score": <integer 0-100>
    }
  ]
}

Rules:
- specifications: extract measurable attributes (RAM, Storage, Display size, Color,
  Material, Weight, Battery, Connectivity, etc.). Use concise values ("8GB" not "8 gigabytes").
- tags: 5-10 lowercase keywords a shopper would search for. Include brand, category keywords.
- enriched_description: rewrite using original facts only. Include 2-3 key specs inline.
- inferred_subcategory: infer from name/description (e.g. "Laptop", "Moisturiser", "Treadmill").
  Return null if already provided and correct.
- quality_score: 0 = no useful attributes; 100 = all key specs present + rich tags + clear description.
- Never fabricate specs. If unsure, omit the key."""


# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class EnrichedProduct:
    """Enrichment output for a single product."""
    product_id: str
    specifications: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    enriched_description: str = ""
    inferred_subcategory: Optional[str] = None
    quality_score: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None

    @property
    def cost_usd(self) -> float:
        from enrichment.token_optimizer import estimate_cost
        return estimate_cost(self.tokens_input, self.tokens_output)


@dataclass
class BatchEnrichmentResult:
    """Result for one LLM batch call covering N products."""
    enriched: list[EnrichedProduct] = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and bool(self.enriched)


# ── Core enricher ─────────────────────────────────────────────────────────────

class AttributeEnricher:
    """
    Enriches product attributes using the LLM.

    Each call to enrich_batch() processes up to `batch_size` products in a
    single LLM request, using the stable SYSTEM_PROMPT for cache efficiency.
    """

    def __init__(self, batch_size: int = 5, retry_on_error: bool = True) -> None:
        self.batch_size = batch_size
        self.retry_on_error = retry_on_error

    # ── Public interface ───────────────────────────────────────────────────────

    def enrich_single(self, product) -> EnrichedProduct:
        """Enrich a single product (convenience wrapper around enrich_batch)."""
        result = self.enrich_batch([product])
        if result.enriched:
            return result.enriched[0]
        return EnrichedProduct(
            product_id=product.id,
            error=result.error or "No result returned",
        )

    def enrich_batch(self, products: list) -> BatchEnrichmentResult:
        """
        Call the LLM once to enrich up to `batch_size` products.

        Returns a BatchEnrichmentResult with one EnrichedProduct per input product.
        On API failure, returns an error result so the caller can skip and continue.
        """
        if not products:
            return BatchEnrichmentResult()

        if not LLM_AVAILABLE:
            return self._mock_enrichment(products)

        user_prompt = self._build_user_prompt(products)
        t0 = time.monotonic()

        try:
            response = _llm_client.chat.completions.create(
                model=_GPT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=self.batch_size * 250,  # cap output tokens
            )
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            return BatchEnrichmentResult(
                error=str(exc),
                latency_ms=latency,
            )

        latency = int((time.monotonic() - t0) * 1000)
        usage   = response.usage

        raw_text = response.choices[0].message.content or ""
        parsed   = self._parse_response(raw_text, products)

        # Distribute token counts equally across products in batch
        tokens_per_product_in = (usage.prompt_tokens // len(products)) if products else 0
        tokens_per_product_out = (usage.completion_tokens // len(products)) if products else 0
        for ep in parsed:
            ep.tokens_input  = tokens_per_product_in
            ep.tokens_output = tokens_per_product_out

        return BatchEnrichmentResult(
            enriched=parsed,
            tokens_input=usage.prompt_tokens,
            tokens_output=usage.completion_tokens,
            latency_ms=latency,
        )

    # ── Prompt construction ────────────────────────────────────────────────────

    @staticmethod
    def _build_user_prompt(products: list) -> str:
        """
        Build the user-turn message for a batch.
        Product ID is explicitly included so the model can map results back.
        """
        items: list[str] = []
        for p in products:
            compressed = build_compressed_product_text(p)
            items.append(f"[product_id: {p.id}]\n{compressed}")
        return "Enrich the following products:\n\n" + "\n\n---\n\n".join(items)

    # ── Response parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(raw: str, products: list) -> list[EnrichedProduct]:
        """
        Parse the LLM JSON response into EnrichedProduct objects.
        Falls back gracefully if the model produces partial or malformed JSON.
        """
        product_id_set = {p.id for p in products}

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON block if model added prose around it
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        results_raw: list[dict] = data.get("results", [])

        # Build a lookup by product_id for robust matching
        result_map: dict[str, dict] = {
            r.get("product_id", ""): r
            for r in results_raw
            if isinstance(r, dict)
        }

        enriched: list[EnrichedProduct] = []
        for product in products:
            raw_result = result_map.get(product.id, {})
            if not raw_result:
                enriched.append(
                    EnrichedProduct(
                        product_id=product.id,
                        error="No result in LLM response for this product_id",
                    )
                )
                continue

            specs = raw_result.get("specifications") or {}
            if not isinstance(specs, dict):
                specs = {}

            tags = raw_result.get("tags") or []
            if not isinstance(tags, list):
                tags = []
            # Normalise: lowercase, strip, deduplicate
            tags = list(dict.fromkeys(t.lower().strip() for t in tags if t))

            quality = raw_result.get("quality_score", 0)
            try:
                quality = max(0, min(100, int(quality)))
            except (ValueError, TypeError):
                quality = 0

            enriched.append(
                EnrichedProduct(
                    product_id=product.id,
                    specifications=specs,
                    tags=tags,
                    enriched_description=str(raw_result.get("enriched_description", "")).strip(),
                    inferred_subcategory=raw_result.get("inferred_subcategory") or None,
                    quality_score=quality,
                )
            )

        return enriched

    # ── Mock for offline / test use ────────────────────────────────────────────

    @staticmethod
    def _mock_enrichment(products: list) -> BatchEnrichmentResult:
        """
        Deterministic mock when no API key is configured.
        Useful for unit tests and CI without real LLM access.
        """
        enriched = []
        for p in products:
            existing_specs = dict(p.specifications or {})
            existing_tags  = list(p.tags or [])

            # Infer basic specs from the description heuristically
            desc = p.description or ""
            inferred_specs: dict = dict(existing_specs)

            for match in re.finditer(
                r"(\b\w[\w\s]*?)\s*[:–—]\s*([\w\s.,]+(?:gb|mb|tb|mah|hz|inch|mm|kg|w|v|rpm|mp|fps|nm|ms|hr|dpi|nits|cm)\b)",
                desc,
                re.IGNORECASE,
            ):
                key = match.group(1).strip().title()[:30]
                val = match.group(2).strip()[:30]
                if key and val:
                    inferred_specs.setdefault(key, val)

            keywords = list({
                w.lower() for w in re.findall(r"\b[a-zA-Z]{4,}\b", f"{p.name} {p.category}")
                if w.lower() not in ("with", "from", "that", "this", "have", "been")
            })[:8]
            merged_tags = list(dict.fromkeys(existing_tags + keywords))[:10]

            quality = min(
                100,
                len(inferred_specs) * 10
                + len(merged_tags) * 5
                + (20 if desc else 0)
            )

            enriched.append(
                EnrichedProduct(
                    product_id=p.id,
                    specifications=inferred_specs,
                    tags=merged_tags,
                    enriched_description=desc[:300] if desc else "",
                    inferred_subcategory=p.subcategory,
                    quality_score=quality,
                    tokens_input=estimate_tokens(SYSTEM_PROMPT) + estimate_tokens(build_compressed_product_text(p)),
                    tokens_output=120,
                )
            )

        total_in  = sum(e.tokens_input  for e in enriched)
        total_out = sum(e.tokens_output for e in enriched)
        return BatchEnrichmentResult(
            enriched=enriched,
            tokens_input=total_in,
            tokens_output=total_out,
            latency_ms=0,
        )
