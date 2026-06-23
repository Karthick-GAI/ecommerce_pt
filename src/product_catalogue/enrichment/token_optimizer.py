"""
Token Optimizer — five complementary strategies for cost-efficient large-scale LLM processing.

Strategy           What it does                                     Typical saving
─────────────────────────────────────────────────────────────────────────────────
1. Text compression  Strip boilerplate, truncate low-signal text       15–30 %
2. Batch packing     N products per LLM call sharing a cached prompt   60–80 %
3. Prompt caching    Stable system prompt → provider cache hit         40–50 % on input
4. Differential hash Skip products whose content hasn't changed        up to 100 % on re-runs
5. Token budget      Hard ceiling; prioritise highest-value products   prevents runaway cost

Token counting uses a conservative char-based approximation (1 token ≈ 3.5 chars for
multilingual/mixed content).  This avoids the tiktoken dependency while staying within
±15 % of actual token counts — good enough for budget decisions.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

CHARS_PER_TOKEN = 3.5   # conservative estimate for mixed English/Indian-brand names

# Pricing reference (USD per 1 M tokens) — update to match your Azure deployment
PRICE_INPUT_PER_M  = 0.15   # gpt-4o-mini input
PRICE_OUTPUT_PER_M = 0.60   # gpt-4o-mini output
CACHE_DISCOUNT     = 0.50   # cached tokens cost 50 % less (Azure OpenAI prompt caching)

# Marketing boilerplate that adds tokens but zero semantic value
_BOILERPLATE = re.compile(
    r"\b(best in class|industry.leading|revolutionary|state.of.the.art"
    r"|cutting.edge|world.class|next.generation|ultimate|premium quality"
    r"|unmatched|unparalleled|seamlessly|effortlessly)\b",
    re.IGNORECASE,
)

# Sentence patterns that contain high information density (keep these)
_HIGH_SIGNAL = re.compile(
    r"(\d[\d.,]*\s*(gb|mb|tb|mah|hz|inch|mm|kg|w|v|rpm|mp|fps|nm|ms|hr|dpi|nits|inch|cm))",
    re.IGNORECASE,
)


# ── Token counting ────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Approximate token count from character length."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Estimate USD cost for one LLM call."""
    non_cached_input = input_tokens - cached_input_tokens
    cost = (
        (non_cached_input * PRICE_INPUT_PER_M / 1_000_000)
        + (cached_input_tokens * PRICE_INPUT_PER_M * CACHE_DISCOUNT / 1_000_000)
        + (output_tokens * PRICE_OUTPUT_PER_M / 1_000_000)
    )
    return round(cost, 8)


# ── Strategy 1: Text compression ─────────────────────────────────────────────

def compress_description(text: str, max_tokens: int = 180) -> str:
    """
    Reduce a product description to its highest-signal content.

    Steps:
      1. Strip marketing boilerplate (saves ~10 % tokens on average)
      2. Split into sentences; score each by information density
      3. Keep highest-scoring sentences until token budget is reached
      4. Always keep the first sentence (usually the most descriptive)
    """
    if not text:
        return ""

    # Step 1: remove boilerplate
    text = _BOILERPLATE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Step 2: split and score sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not sentences:
        return text

    def _score(s: str) -> float:
        spec_hits  = len(_HIGH_SIGNAL.findall(s))      # spec-like numbers
        num_hits   = len(re.findall(r"\d", s))          # any digit
        word_count = len(s.split())
        return (spec_hits * 3 + num_hits * 0.5) / max(word_count, 1)

    scored = sorted(
        enumerate(sentences),
        key=lambda idx_s: _score(idx_s[1]),
        reverse=True,
    )

    # Step 3: greedily pick sentences within budget; always keep sentence 0
    kept: set[int] = {0}
    budget = max_tokens - estimate_tokens(sentences[0])

    for orig_idx, sentence in scored:
        if orig_idx == 0:
            continue
        cost = estimate_tokens(sentence)
        if budget - cost < 0:
            break
        kept.add(orig_idx)
        budget -= cost

    # Step 4: rebuild in original order
    result = " ".join(sentences[i] for i in sorted(kept))
    return result.strip()


def build_compressed_product_text(product) -> str:
    """
    Build a compact product representation for LLM input.
    Name + brand + category carry the most signal per token.
    """
    parts = [
        f"Name: {product.name}",
        f"Brand: {product.brand}",
        f"Category: {product.category}",
    ]
    if product.subcategory:
        parts.append(f"Subcategory: {product.subcategory}")
    if product.description:
        parts.append(f"Description: {compress_description(product.description)}")
    if product.specifications:
        specs_str = "; ".join(f"{k}: {v}" for k, v in list(product.specifications.items())[:8])
        parts.append(f"Existing specs: {specs_str}")
    if product.tags:
        parts.append(f"Existing tags: {', '.join((product.tags or [])[:6])}")
    return "\n".join(parts)


# ── Strategy 2: Batch packing ─────────────────────────────────────────────────

@dataclass
class ProductBatch:
    """A group of products packed into one LLM call."""
    products: list  # list of Product ORM objects
    estimated_input_tokens: int
    estimated_output_tokens: int

    @property
    def product_ids(self) -> list[str]:
        return [p.id for p in self.products]

    @property
    def estimated_total_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens


def pack_batches(
    products: list,
    system_prompt: str,
    batch_size: int = 5,
    max_input_tokens_per_call: int = 4000,
    output_tokens_per_product: int = 200,
) -> list[ProductBatch]:
    """
    Pack products into batches that fit within the per-call token budget.

    Strategy:
      - System prompt tokens are paid once per call (cached after first call)
      - Group products by category so they share implicit context
      - Never exceed max_input_tokens_per_call
    """
    system_tokens = estimate_tokens(system_prompt)
    per_product_overhead = 30  # JSON structure tokens per product slot

    # Sort by category to maximise context sharing across consecutive calls
    sorted_products = sorted(products, key=lambda p: (p.category, p.brand))

    batches: list[ProductBatch] = []
    current: list = []
    current_input_tokens = system_tokens

    for product in sorted_products:
        product_tokens = (
            estimate_tokens(build_compressed_product_text(product))
            + per_product_overhead
        )

        would_exceed_size  = len(current) >= batch_size
        would_exceed_tokens = (current_input_tokens + product_tokens) > max_input_tokens_per_call

        if current and (would_exceed_size or would_exceed_tokens):
            batches.append(
                ProductBatch(
                    products=list(current),
                    estimated_input_tokens=current_input_tokens,
                    estimated_output_tokens=len(current) * output_tokens_per_product,
                )
            )
            current = []
            current_input_tokens = system_tokens

        current.append(product)
        current_input_tokens += product_tokens

    if current:
        batches.append(
            ProductBatch(
                products=list(current),
                estimated_input_tokens=current_input_tokens,
                estimated_output_tokens=len(current) * output_tokens_per_product,
            )
        )

    return batches


# ── Strategy 4: Differential hashing ─────────────────────────────────────────

def compute_content_hash(product) -> str:
    """
    SHA-256 of the product fields that enrichment depends on.
    If this hash matches the stored hash, enrichment can be skipped entirely.
    """
    specs_str = str(sorted(product.specifications.items())) if product.specifications else ""
    tags_str  = str(sorted(product.tags or []))
    content   = f"{product.name}|{product.description or ''}|{specs_str}|{tags_str}"
    return hashlib.sha256(content.encode()).hexdigest()


def needs_enrichment(product, stored_hash: Optional[str]) -> bool:
    """Return True if product content has changed since last enrichment."""
    if stored_hash is None:
        return True
    return compute_content_hash(product) != stored_hash


# ── Strategy 5: Token budget ─────────────────────────────────────────────────

@dataclass
class TokenBudget:
    """
    Hard ceiling on total tokens for a batch run.
    Tracks actual usage and refuses calls that would exceed the limit.
    """
    total_limit: int
    _used_input: int = field(default=0, init=False)
    _used_output: int = field(default=0, init=False)

    @property
    def used_input(self) -> int:
        return self._used_input

    @property
    def used_output(self) -> int:
        return self._used_output

    @property
    def used_total(self) -> int:
        return self._used_input + self._used_output

    @property
    def remaining(self) -> int:
        return max(0, self.total_limit - self.used_total)

    def can_afford(self, input_tokens: int, output_tokens: int) -> bool:
        return (self.used_total + input_tokens + output_tokens) <= self.total_limit

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self._used_input  += input_tokens
        self._used_output += output_tokens

    def estimated_cost_usd(self, cached_input_tokens: int = 0) -> float:
        return estimate_cost(self._used_input, self._used_output, cached_input_tokens)

    def summary(self) -> dict:
        return {
            "budget_tokens":  self.total_limit,
            "used_tokens":    self.used_total,
            "used_input":     self._used_input,
            "used_output":    self._used_output,
            "remaining":      self.remaining,
            "utilisation_pct": round(self.used_total / self.total_limit * 100, 1),
            "estimated_cost_usd": self.estimated_cost_usd(),
        }


# ── Estimation helpers ────────────────────────────────────────────────────────

def estimate_batch_run(
    products: list,
    system_prompt: str,
    batch_size: int = 5,
    output_tokens_per_product: int = 200,
) -> dict:
    """
    Estimate total tokens and cost for enriching a list of products
    before any API call is made.
    """
    batches = pack_batches(
        products, system_prompt,
        batch_size=batch_size,
        output_tokens_per_product=output_tokens_per_product,
    )

    system_tokens = estimate_tokens(system_prompt)
    total_input  = sum(b.estimated_input_tokens for b in batches)
    total_output = sum(b.estimated_output_tokens for b in batches)

    # First call pays full system prompt; subsequent calls hit the prompt cache
    cached_input = system_tokens * max(0, len(batches) - 1)

    return {
        "products":           len(products),
        "batches":            len(batches),
        "batch_size":         batch_size,
        "estimated_input_tokens":  total_input,
        "estimated_output_tokens": total_output,
        "estimated_total_tokens":  total_input + total_output,
        "cached_input_tokens": cached_input,
        "estimated_cost_usd":  round(estimate_cost(total_input, total_output, cached_input), 6),
        "estimated_cost_inr":  round(estimate_cost(total_input, total_output, cached_input) * 83, 4),
    }
