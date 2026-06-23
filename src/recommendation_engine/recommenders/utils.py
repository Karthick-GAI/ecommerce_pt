"""Shared utility functions for all recommenders."""


def stock_health(count: int) -> str:
    if count == 0:   return "out_of_stock"
    if count <= 5:   return "critical"
    if count <= 20:  return "low"
    return "healthy"


def normalize_scores(raw: list[float]) -> list[float]:
    """Min-max normalize a list of raw scores to [0, 1]."""
    if not raw:
        return []
    mn, mx = min(raw), max(raw)
    if mx == mn:
        return [1.0] * len(raw)
    return [(v - mn) / (mx - mn) for v in raw]


def fmt_product(row, score: float, strategy: str, reason: str) -> dict:
    """
    Unified formatter for recommendation results.
    Accepts either a SQLAlchemy ORM object or a Row returned by text() queries.
    Both expose attributes by name.
    """
    return {
        "product_id":   row.id,
        "name":         row.name,
        "category":     row.category,
        "subcategory":  getattr(row, "subcategory", None),
        "brand":        row.brand,
        "price":        row.price,
        "discount_pct": getattr(row, "discount_pct", None),
        "stock":        row.inventory_count,
        "health":       stock_health(row.inventory_count),
        "rating_avg":   getattr(row, "rating_avg", None),
        "score":        round(float(score), 4),
        "strategy":     strategy,
        "reason":       reason,
    }


def deduplicate(recs: list[dict], keep: int | None = None) -> list[dict]:
    """Remove duplicate product_ids, keeping first occurrence (highest score)."""
    seen = set()
    result = []
    for r in recs:
        pid = r["product_id"]
        if pid not in seen:
            seen.add(pid)
            result.append(r)
    return result[:keep] if keep is not None else result


def merge_ranked(
    *rec_lists: list[dict],
    weights: list[float] | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Merge multiple recommendation lists by weighted score.
    Deduplicates and re-ranks by final weighted score.
    """
    if not weights:
        weights = [1.0] * len(rec_lists)

    score_map: dict[str, float] = {}
    meta_map:  dict[str, dict]  = {}

    for recs, w in zip(rec_lists, weights):
        for item in recs:
            pid = item["product_id"]
            score_map[pid] = score_map.get(pid, 0.0) + item["score"] * w
            if pid not in meta_map:
                meta_map[pid] = item

    ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [
        {**meta_map[pid], "score": round(combined_score, 4)}
        for pid, combined_score in ranked
    ]
