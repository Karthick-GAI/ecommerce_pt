"""
Hybrid recommender — orchestrates all strategies with adaptive weights.

Cold start  (no history)       : trending + new arrivals + deals
Warm start  (browsing only)    : CF-browsing + content-profile + trending
Active user (purchase history) : user-CF + content-profile + trending (weighted)
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Product, UserPreferenceProfile
from .collaborative import (
    get_user_based_cf, get_cf_from_browsing, get_user_purchase_count,
)
from .content_based import get_similar_for_profile, get_category_picks
from .trending import get_trending, get_top_viewed, get_new_arrivals, get_top_deals
from .utils import merge_ranked, deduplicate, fmt_product


# ── Profile helpers ───────────────────────────────────────────────────────────

def _get_profile(db: Session, customer_id: str) -> UserPreferenceProfile | None:
    return db.query(UserPreferenceProfile).filter(
        UserPreferenceProfile.customer_id == customer_id
    ).first()


def _browsing_count(db: Session, customer_id: str) -> int:
    sql = text("""
        SELECT COUNT(*) FROM browsing_events
        WHERE user_id = :cid
          AND event_type IN ('purchase', 'add_to_cart', 'wishlist')
    """)
    return int(db.execute(sql, {"cid": customer_id}).scalar() or 0)


def _purchased_ids(db: Session, customer_id: str) -> list[str]:
    sql = text("""
        SELECT DISTINCT item.product_id
        FROM orders o,
        LATERAL jsonb_to_recordset(o.cart_activity)
            AS item(product_id text, quantity int, unit_price float)
        WHERE o.user_id = :cid
    """)
    return [r[0] for r in db.execute(sql, {"cid": customer_id}).fetchall()]


# ── Personalized recommendations ─────────────────────────────────────────────

def get_personalized(
    db: Session,
    customer_id: str,
    limit: int = 20,
    exclude_purchased: bool = True,
) -> list[dict]:
    purchase_count  = get_user_purchase_count(db, customer_id)
    browsing_count  = _browsing_count(db, customer_id)
    profile         = _get_profile(db, customer_id)
    exclude_ids     = _purchased_ids(db, customer_id) if exclude_purchased else []

    # ── Active user: rich purchase history ───────────────────────────────────
    if purchase_count >= 5:
        cf_recs      = get_user_based_cf(db, customer_id, limit=limit * 2)
        content_recs = (
            get_similar_for_profile(
                db, profile.top_categories or {}, profile.avg_price or 500,
                exclude_ids=exclude_ids, limit=limit,
            )
            if profile and profile.top_categories
            else []
        )
        trend_recs = get_trending(db, days=30, limit=limit // 2, exclude_ids=exclude_ids)

        return merge_ranked(
            cf_recs, content_recs, trend_recs,
            weights=[0.5, 0.3, 0.2],
            limit=limit,
        )

    # ── Warm user: browsing history, few/no purchases ────────────────────────
    if browsing_count >= 3 or purchase_count >= 1:
        cf_recs = get_cf_from_browsing(db, customer_id, limit=limit * 2)
        content_recs = (
            get_similar_for_profile(
                db, profile.top_categories or {}, profile.avg_price or 500,
                exclude_ids=exclude_ids, limit=limit,
            )
            if profile and profile.top_categories
            else []
        )
        trend_recs = get_trending(db, days=14, limit=limit // 2, exclude_ids=exclude_ids)

        return merge_ranked(
            cf_recs, content_recs, trend_recs,
            weights=[0.4, 0.35, 0.25],
            limit=limit,
        )

    # ── Cold start ───────────────────────────────────────────────────────────
    trend_recs   = get_trending(db, days=30, limit=limit // 2)
    viewed_recs  = get_top_viewed(db, days=7, limit=limit // 2)
    new_recs     = get_new_arrivals(db, limit=limit // 4)

    return merge_ranked(trend_recs, viewed_recs, new_recs,
                        weights=[0.5, 0.35, 0.15], limit=limit)


# ── Homepage multi-section feed ───────────────────────────────────────────────

def get_homepage_feed(db: Session, customer_id: str) -> list[dict]:
    """
    Returns a list of section dicts, each with title + products.
    Sections adapt based on user's history depth.
    """
    purchase_count = get_user_purchase_count(db, customer_id)
    browsing_count = _browsing_count(db, customer_id)
    profile        = _get_profile(db, customer_id)
    exclude_ids    = _purchased_ids(db, customer_id)

    sections = []
    global_seen: set[str] = set(exclude_ids)

    def _excl():
        return list(global_seen)

    def _add_section(title: str, strategy: str, recs: list[dict]):
        unique = [r for r in recs if r["product_id"] not in global_seen]
        if unique:
            for r in unique:
                global_seen.add(r["product_id"])
            sections.append({"title": title, "strategy": strategy, "products": unique})

    # Section 1: Personalised
    if purchase_count >= 5:
        cf_recs = get_user_based_cf(db, customer_id, limit=30)
        _add_section("Recommended For You", "personalized", cf_recs[:10])
    elif browsing_count >= 3 or purchase_count >= 1:
        cf_recs = get_cf_from_browsing(db, customer_id, limit=30)
        _add_section("Based on Your Activity", "personalized", cf_recs[:10])

    # Section 2: Trending
    trend = get_trending(db, days=30, limit=15, exclude_ids=_excl())
    _add_section("Trending Now", "trending", trend)

    # Section 3: Category picks from profile
    if profile and profile.top_categories:
        top_cat = max(profile.top_categories, key=profile.top_categories.get)
        cat_picks = get_category_picks(db, top_cat, exclude_ids=_excl(), limit=10)
        _add_section(f"More in {top_cat}", "category", cat_picks)

    # Section 4: Most engaged this week
    viewed = get_top_viewed(db, days=7, limit=12, exclude_ids=_excl())
    _add_section("Popular This Week", "trending_views", viewed)

    # Section 5: New arrivals
    new_recs = get_new_arrivals(db, limit=10, exclude_ids=_excl())
    _add_section("New Arrivals", "new_arrival", new_recs)

    # Section 6: Top deals
    deals = get_top_deals(db, limit=10, exclude_ids=_excl())
    _add_section("Top Deals", "deals", deals)

    return sections
