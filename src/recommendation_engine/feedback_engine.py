"""
Feedback loop engine — adaptive re-ranking based on explicit user feedback.

Adaptation model
────────────────
  category_boosts / brand_boosts:
    Each thumbs-up  multiplies the boost by BOOST_FACTOR   (capped at MAX_BOOST).
    Each thumbs-down multiplies the boost by PENALTY_FACTOR (floored at MIN_BOOST).
    "Not interested" permanently blocks the product and applies a mild category penalty.

  apply_adaptation():
    For every recommendation, the final score is multiplied by the geometric mean
    of that product's category and brand boost factors.  Blocked products are removed.
    Results are re-sorted by the adapted score so thumbs-up categories rise to the top.

  strategy_weights:
    Per-user, per-strategy score offset (±0.05 per event) that nudges the hybrid
    recommender's effective weights on the next retraining cycle.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import Product, ExplicitFeedback, FeedbackAdaptation

# ── Adaptation constants ──────────────────────────────────────────────────────

BOOST_FACTOR   = 1.25   # per thumbs-up multiplicative increase
PENALTY_FACTOR = 0.80   # per thumbs-down multiplicative decrease
MAX_BOOST      = 2.50   # ceiling for any single category/brand multiplier
MIN_BOOST      = 0.25   # floor  for any single category/brand multiplier
DEFAULT_BOOST  = 1.00   # starting neutral weight


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_or_create_adaptation(db: Session, customer_id: str) -> FeedbackAdaptation:
    obj = (
        db.query(FeedbackAdaptation)
        .filter(FeedbackAdaptation.customer_id == customer_id)
        .first()
    )
    if not obj:
        obj = FeedbackAdaptation(
            customer_id       = customer_id,
            category_boosts   = {},
            brand_boosts      = {},
            blocked_products  = [],
            strategy_weights  = {},
            total_thumbs_up   = 0,
            total_thumbs_down = 0,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
    return obj


# ── Public API ────────────────────────────────────────────────────────────────

def record_explicit_feedback(
    db: Session,
    customer_id: str,
    product_id: str,
    feedback_type: str,
    rec_strategy: str | None = None,
) -> FeedbackAdaptation:
    """
    Persist an explicit feedback event and update the customer's adaptation weights.
    Returns the updated FeedbackAdaptation object.
    """
    product = db.query(Product).filter(Product.id == product_id).first()

    # Persist the raw feedback event
    fb = ExplicitFeedback(
        customer_id   = customer_id,
        product_id    = product_id,
        product_name  = product.name     if product else None,
        category      = product.category if product else None,
        brand         = product.brand    if product else None,
        feedback_type = feedback_type,
        rec_strategy  = rec_strategy,
    )
    db.add(fb)

    # Load / create adaptation record
    adaptation   = _get_or_create_adaptation(db, customer_id)
    cat_boosts   = dict(adaptation.category_boosts  or {})
    brand_boosts = dict(adaptation.brand_boosts     or {})
    blocked      = list(adaptation.blocked_products or [])

    if product:
        cat   = product.category
        brand = product.brand

        if feedback_type == "thumbs_up":
            cat_boosts[cat]     = min(MAX_BOOST, cat_boosts.get(cat, DEFAULT_BOOST)     * BOOST_FACTOR)
            brand_boosts[brand] = min(MAX_BOOST, brand_boosts.get(brand, DEFAULT_BOOST) * BOOST_FACTOR)
            adaptation.total_thumbs_up = (adaptation.total_thumbs_up or 0) + 1

        elif feedback_type == "thumbs_down":
            cat_boosts[cat]     = max(MIN_BOOST, cat_boosts.get(cat, DEFAULT_BOOST)     * PENALTY_FACTOR)
            brand_boosts[brand] = max(MIN_BOOST, brand_boosts.get(brand, DEFAULT_BOOST) * PENALTY_FACTOR)
            adaptation.total_thumbs_down = (adaptation.total_thumbs_down or 0) + 1

        elif feedback_type == "not_interested":
            if product_id not in blocked:
                blocked.append(product_id)
            # Mild category penalty
            cat_boosts[cat] = max(MIN_BOOST, cat_boosts.get(cat, DEFAULT_BOOST) * 0.92)

    # Strategy weight nudge
    if rec_strategy and feedback_type in ("thumbs_up", "thumbs_down"):
        strat_w = dict(adaptation.strategy_weights or {})
        delta   = +0.05 if feedback_type == "thumbs_up" else -0.05
        strat_w[rec_strategy] = round(
            max(0.05, min(0.95, strat_w.get(rec_strategy, 0.50) + delta)), 3
        )
        adaptation.strategy_weights = strat_w

    adaptation.category_boosts  = cat_boosts
    adaptation.brand_boosts     = brand_boosts
    adaptation.blocked_products = blocked
    adaptation.last_updated     = datetime.utcnow()
    db.commit()
    db.refresh(adaptation)
    return adaptation


def apply_adaptation(
    recs: list[dict],
    adaptation: FeedbackAdaptation | None,
) -> list[dict]:
    """
    Post-process a recommendation list:
      1. Remove products blocked by the customer.
      2. Multiply each product's score by the geometric mean of its
         category and brand boost factors.
      3. Re-sort descending by the adapted score.
    """
    if not adaptation:
        return recs

    cat_boosts   = adaptation.category_boosts  or {}
    brand_boosts = adaptation.brand_boosts     or {}
    blocked      = set(adaptation.blocked_products or [])

    adapted = []
    for r in recs:
        if r.get("product_id") in blocked:
            continue
        cat     = r.get("category", "")
        brand   = r.get("brand", "")
        score   = max(float(r.get("score", 0.5)), 0.001)
        cat_m   = float(cat_boosts.get(cat, 1.0))
        brand_m = float(brand_boosts.get(brand, 1.0))
        # Geometric mean of the two multipliers
        combined = (cat_m * brand_m) ** 0.5
        adapted.append({**r, "score": round(score * combined, 4)})

    adapted.sort(key=lambda x: x["score"], reverse=True)
    return adapted


def get_adaptation(db: Session, customer_id: str) -> FeedbackAdaptation | None:
    return (
        db.query(FeedbackAdaptation)
        .filter(FeedbackAdaptation.customer_id == customer_id)
        .first()
    )


def get_feedback_stats(db: Session, customer_id: str) -> dict:
    """Return adaptation weights + most recent explicit feedback events."""
    adaptation = get_adaptation(db, customer_id)

    recent = (
        db.query(ExplicitFeedback)
        .filter(ExplicitFeedback.customer_id == customer_id)
        .order_by(ExplicitFeedback.created_at.desc())
        .limit(20)
        .all()
    )

    cat_boosts_rounded = (
        {cat: round(v, 3) for cat, v in (adaptation.category_boosts or {}).items()}
        if adaptation else {}
    )
    brand_boosts_rounded = (
        {b: round(v, 3) for b, v in (adaptation.brand_boosts or {}).items()}
        if adaptation else {}
    )

    return {
        "adaptation": {
            "category_boosts":    cat_boosts_rounded,
            "brand_boosts":       brand_boosts_rounded,
            "strategy_weights":   adaptation.strategy_weights   if adaptation else {},
            "blocked_count":      len(adaptation.blocked_products or []) if adaptation else 0,
            "total_thumbs_up":    adaptation.total_thumbs_up    if adaptation else 0,
            "total_thumbs_down":  adaptation.total_thumbs_down  if adaptation else 0,
            "last_updated":       str(adaptation.last_updated)  if adaptation else None,
        },
        "recent_feedback": [_fmt_fb(f) for f in recent],
    }


def reset_adaptation(db: Session, customer_id: str) -> dict:
    """Clear all learned weights for a customer (start fresh)."""
    adaptation = get_adaptation(db, customer_id)
    if adaptation:
        adaptation.category_boosts   = {}
        adaptation.brand_boosts      = {}
        adaptation.blocked_products  = []
        adaptation.strategy_weights  = {}
        adaptation.total_thumbs_up   = 0
        adaptation.total_thumbs_down = 0
        adaptation.last_updated      = datetime.utcnow()
        db.commit()
    return {"message": "Adaptation reset", "customer_id": customer_id}


def get_loop_performance(db: Session, days: int = 30) -> dict:
    """Service-wide feedback loop metrics across all customers."""
    since = datetime.utcnow() - timedelta(days=days)

    total    = db.query(ExplicitFeedback).filter(ExplicitFeedback.created_at >= since).count()
    positive = db.query(ExplicitFeedback).filter(
        ExplicitFeedback.created_at >= since,
        ExplicitFeedback.feedback_type == "thumbs_up",
    ).count()
    negative = db.query(ExplicitFeedback).filter(
        ExplicitFeedback.created_at >= since,
        ExplicitFeedback.feedback_type == "thumbs_down",
    ).count()
    hidden   = db.query(ExplicitFeedback).filter(
        ExplicitFeedback.created_at >= since,
        ExplicitFeedback.feedback_type == "not_interested",
    ).count()

    # Top liked categories
    liked_cats = (
        db.query(ExplicitFeedback.category, func.count(ExplicitFeedback.id).label("cnt"))
        .filter(
            ExplicitFeedback.feedback_type == "thumbs_up",
            ExplicitFeedback.created_at >= since,
        )
        .group_by(ExplicitFeedback.category)
        .order_by(func.count(ExplicitFeedback.id).desc())
        .limit(5)
        .all()
    )

    # Strategies with highest positive rate
    strat_pos = (
        db.query(ExplicitFeedback.rec_strategy, func.count(ExplicitFeedback.id).label("cnt"))
        .filter(
            ExplicitFeedback.feedback_type == "thumbs_up",
            ExplicitFeedback.created_at >= since,
            ExplicitFeedback.rec_strategy.isnot(None),
        )
        .group_by(ExplicitFeedback.rec_strategy)
        .order_by(func.count(ExplicitFeedback.id).desc())
        .limit(5)
        .all()
    )

    active_profiles = (
        db.query(FeedbackAdaptation)
        .filter(FeedbackAdaptation.total_thumbs_up > 0)
        .count()
    )

    return {
        "period_days":            days,
        "total_feedback":         total,
        "thumbs_up":              positive,
        "thumbs_down":            negative,
        "not_interested":         hidden,
        "acceptance_rate_pct":    round(positive / max(total, 1) * 100, 1),
        "active_profiles":        active_profiles,
        "top_liked_categories":   [{"category": r.category, "count": r.cnt} for r in liked_cats],
        "top_positive_strategies":[{"strategy": r.rec_strategy, "count": r.cnt} for r in strat_pos],
    }


def _fmt_fb(f: ExplicitFeedback) -> dict:
    return {
        "feedback_id":   f.id,
        "product_id":    f.product_id,
        "product_name":  f.product_name,
        "category":      f.category,
        "brand":         f.brand,
        "feedback_type": f.feedback_type,
        "rec_strategy":  f.rec_strategy,
        "created_at":    str(f.created_at),
    }
