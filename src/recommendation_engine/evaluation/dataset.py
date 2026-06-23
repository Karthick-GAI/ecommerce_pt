"""
Evaluation dataset builder.

An EvaluationCase holds everything a metric needs:
  - user_id + user_profile
  - the recommendations that were served
  - ground truth: actual post-recommendation interactions (add_to_cart, purchase)
  - purchase history: what the user already bought (for novelty checking)

build_evaluation_cases() fetches from the DB and assembles cases ready for
metric .measure() calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text


@dataclass
class EvaluationCase:
    """
    Single evaluation case — one user's recommendation snapshot + ground truth.

    Attributes
    ----------
    user_id             : customer identifier
    user_profile        : dict from rec_user_profiles (top_categories, price range, etc.)
    recommendations     : list of recommendation dicts (product_id, name, category,
                          brand, price, discount_pct, stock, strategy, score, …)
    ground_truth_interactions : product_ids the user actually interacted with
                          (add_to_cart / purchase / wishlist) — used as accuracy ground truth
    purchase_history    : product_ids already purchased before this snapshot
                          — used for novelty scoring
    context             : arbitrary extra info (strategy name, section title, etc.)
    """
    user_id: str
    recommendations: list[dict]
    ground_truth_interactions: list[str] = field(default_factory=list)
    purchase_history: list[str] = field(default_factory=list)
    user_profile: Optional[dict] = None
    context: dict = field(default_factory=dict)


def build_evaluation_cases(
    db: Session,
    customer_ids: Optional[list[str]] = None,
    limit_users: int = 20,
    interaction_window_days: int = 30,
    min_ground_truth: int = 1,
) -> list[EvaluationCase]:
    """
    Build EvaluationCase objects by fetching real recommendation and interaction
    data from the database.

    For each user:
      1. Fetch their preference profile (top_categories, price range)
      2. Generate a recommendation list using the hybrid recommender
      3. Use recent high-intent events (add_to_cart, purchase, wishlist) as ground truth
      4. Fetch their purchase history for novelty scoring

    Args:
        customer_ids       : specific users to evaluate; if None, pick top active users
        limit_users        : max users when customer_ids is None
        interaction_window_days: days back for ground truth interactions
        min_ground_truth   : skip users with fewer than this many ground truth events

    Returns list[EvaluationCase] — ready for metric evaluation.
    """
    if customer_ids:
        users = customer_ids
    else:
        users = _top_active_users(db, limit=limit_users)

    cases: list[EvaluationCase] = []

    for uid in users:
        profile = _fetch_profile(db, uid)
        purchase_history = _fetch_purchase_history(db, uid)
        ground_truth = _fetch_ground_truth(db, uid, days=interaction_window_days)

        if len(ground_truth) < min_ground_truth:
            continue

        recommendations = _generate_recommendations(db, uid)
        if not recommendations:
            continue

        cases.append(
            EvaluationCase(
                user_id=uid,
                recommendations=recommendations,
                ground_truth_interactions=ground_truth,
                purchase_history=purchase_history,
                user_profile=profile,
                context={"interaction_window_days": interaction_window_days},
            )
        )

    return cases


def build_case_from_recs(
    db: Session,
    user_id: str,
    recommendations: list[dict],
    interaction_window_days: int = 30,
) -> EvaluationCase:
    """
    Build a single EvaluationCase for an already-generated recommendation list.
    Used by the API endpoint to evaluate a live recommendation response.
    """
    profile = _fetch_profile(db, user_id)
    purchase_history = _fetch_purchase_history(db, user_id)
    ground_truth = _fetch_ground_truth(db, user_id, days=interaction_window_days)

    return EvaluationCase(
        user_id=user_id,
        recommendations=recommendations,
        ground_truth_interactions=ground_truth,
        purchase_history=purchase_history,
        user_profile=profile,
        context={"interaction_window_days": interaction_window_days},
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _top_active_users(db: Session, limit: int) -> list[str]:
    """Users with the most recent browsing events — most likely to have ground truth."""
    sql = text("""
        SELECT user_id, COUNT(*) AS cnt
        FROM browsing_events
        WHERE event_type IN ('add_to_cart', 'purchase', 'wishlist')
          AND created_at >= NOW() - INTERVAL '60 days'
        GROUP BY user_id
        ORDER BY cnt DESC
        LIMIT :limit
    """)
    rows = db.execute(sql, {"limit": limit}).fetchall()
    return [r.user_id for r in rows]


def _fetch_profile(db: Session, user_id: str) -> Optional[dict]:
    sql = text("""
        SELECT top_categories, top_brands, top_subcategories,
               price_min, price_max, avg_price,
               total_purchases, total_interactions
        FROM rec_user_profiles
        WHERE customer_id = :uid
        LIMIT 1
    """)
    row = db.execute(sql, {"uid": user_id}).fetchone()
    if not row:
        return None
    return {
        "top_categories":     row.top_categories or {},
        "top_brands":         row.top_brands or {},
        "top_subcategories":  row.top_subcategories or {},
        "price_min":          row.price_min or 0,
        "price_max":          row.price_max or 999999,
        "avg_price":          row.avg_price or 0,
        "total_purchases":    row.total_purchases or 0,
        "total_interactions": row.total_interactions or 0,
    }


def _fetch_purchase_history(db: Session, user_id: str) -> list[str]:
    """Product IDs the user has already purchased (from both datasets)."""
    sql = text("""
        SELECT DISTINCT item.product_id
        FROM orders o,
        LATERAL jsonb_to_recordset(o.cart_activity)
            AS item(product_id text, quantity int, unit_price float)
        WHERE o.user_id = :uid
    """)
    rows = db.execute(sql, {"uid": user_id}).fetchall()
    return [r.product_id for r in rows]


def _fetch_ground_truth(db: Session, user_id: str, days: int) -> list[str]:
    """
    High-intent product interactions in the last N days — used as accuracy ground truth.
    Priority: purchase > add_to_cart > wishlist (we include all three for the POC).
    """
    sql = text("""
        SELECT DISTINCT product_id
        FROM browsing_events
        WHERE user_id = :uid
          AND event_type IN ('purchase', 'add_to_cart', 'wishlist')
          AND created_at >= NOW() - INTERVAL ':days days'
        ORDER BY product_id
    """)
    # SQLAlchemy text() doesn't interpolate inside strings, so use format
    sql = text(f"""
        SELECT DISTINCT product_id
        FROM browsing_events
        WHERE user_id = :uid
          AND event_type IN ('purchase', 'add_to_cart', 'wishlist')
          AND created_at >= NOW() - INTERVAL '{days} days'
        ORDER BY product_id
    """)
    rows = db.execute(sql, {"uid": user_id}).fetchall()
    return [r.product_id for r in rows]


def _generate_recommendations(db: Session, user_id: str, limit: int = 20) -> list[dict]:
    """Generate a fresh recommendation list using the hybrid recommender."""
    try:
        from recommenders.hybrid import get_personalized
        return get_personalized(db, user_id, limit=limit)
    except Exception:
        return []
