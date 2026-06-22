"""
Customer memory builder.

Aggregates signals from five sources:
  1. orders.cart_activity      — purchase history (weight: highest)
  2. browsing_events           — views, add_to_cart, wishlist, purchase signals
  3. wishlists                 — explicit save signals
  4. search_logs               — search intent
  5. sess_events               — real-time session events (this service)

Computes:
  - Preference profiles (categories, brands, price range)
  - Behavioral counts (sessions, events, searches, purchases)
  - Conversion metrics (view-to-cart rate, cart-to-purchase rate)
  - Intent signals (recent searches, recently viewed)
  - Lifecycle stage (new → exploring → engaged → repeat_buyer → loyal / at_risk)
"""
from collections import Counter
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import (
    Customer, Product, BrowsingEvent, Wishlist, SearchLog,
    SessionEvent, CustomerMemory,
)


# ── Lifecycle stage thresholds ────────────────────────────────────────────────
# at_risk overrides all if last_seen > AT_RISK_DAYS and total_purchases > 0
AT_RISK_DAYS     = 45
LOYAL_PURCHASES  = 16
REPEAT_PURCHASES = 6
ENGAGED_MIN      = 2


def _lifecycle(
    total_purchases: int,
    total_events: int,
    days_since_last: int | None,
) -> str:
    if days_since_last is not None and days_since_last > AT_RISK_DAYS and total_purchases > 0:
        return "at_risk"
    if total_purchases >= LOYAL_PURCHASES:
        return "loyal"
    if total_purchases >= REPEAT_PURCHASES:
        return "repeat_buyer"
    if total_purchases >= ENGAGED_MIN:
        return "engaged"
    if total_events >= 10:
        return "exploring"
    return "new"


def build_memory(db: Session, customer_id: str) -> CustomerMemory | None:
    """
    Compute and upsert CustomerMemory for a customer.
    Returns the saved CustomerMemory object, or None if no data exists.
    """
    now = datetime.now(timezone.utc)

    # ── 1. Purchase history from dataset orders ───────────────────────────
    purchase_sql = text("""
        SELECT item.product_id, item.unit_price, item.quantity,
               o.created_at AS order_date
        FROM orders o,
        LATERAL jsonb_to_recordset(o.cart_activity)
            AS item(product_id text, quantity int, unit_price float)
        WHERE o.user_id = :cid
    """)
    purchase_rows = db.execute(purchase_sql, {"cid": customer_id}).fetchall()

    # ── 2. Browsing events ────────────────────────────────────────────────
    browsing = (
        db.query(BrowsingEvent)
        .filter(BrowsingEvent.user_id == customer_id)
        .order_by(BrowsingEvent.created_at.desc())
        .all()
    )

    # ── 3. Wishlists ──────────────────────────────────────────────────────
    wishlisted = db.query(Wishlist).filter(Wishlist.user_id == customer_id).all()

    # ── 4. Search logs ────────────────────────────────────────────────────
    searches = (
        db.query(SearchLog)
        .filter(SearchLog.user_id == customer_id)
        .order_by(SearchLog.created_at.desc())
        .all()
    )

    # ── 5. Session events (this service) ──────────────────────────────────
    sess_events = (
        db.query(SessionEvent)
        .filter(SessionEvent.customer_id == customer_id)
        .order_by(SessionEvent.created_at.desc())
        .all()
    )

    # No data at all → skip
    if not purchase_rows and not browsing and not wishlisted and not searches:
        return None

    # ── Build product ID → weight map ─────────────────────────────────────
    product_weight: Counter = Counter()

    for p in purchase_rows:
        product_weight[p.product_id] += (p.quantity or 1) * 5   # purchase = highest signal

    for b in browsing:
        w = {"purchase": 4, "add_to_cart": 3, "wishlist": 2, "view": 1}.get(b.event_type, 1)
        product_weight[b.product_id] += w

    for w in wishlisted:
        product_weight[w.product_id] += 2

    for e in sess_events:
        if e.product_id:
            w = {"purchase": 5, "add_to_cart": 3, "product_view": 2,
                 "wishlist_add": 2, "recommendation_click": 1}.get(e.event_type, 1)
            product_weight[e.product_id] += w

    # ── Enrich with product attributes ───────────────────────────────────
    pids     = list(product_weight.keys())
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(pids)).all()}

    cat_counter:   Counter = Counter()
    brand_counter: Counter = Counter()
    subcat_counter: Counter = Counter()
    prices: list[float] = []

    for pid, weight in product_weight.items():
        prod = products.get(pid)
        if not prod:
            continue
        cat_counter[prod.category]        += weight
        brand_counter[prod.brand]         += weight
        subcat_counter[prod.subcategory]  += weight

    for p in purchase_rows:
        if p.unit_price and p.unit_price > 0:
            prices.append(float(p.unit_price))

    if not prices:
        for pid in product_weight:
            prod = products.get(pid)
            if prod and prod.price:
                prices.append(prod.price)

    # ── Behavioral counts ─────────────────────────────────────────────────
    total_events    = len(browsing) + len(sess_events)
    total_searches  = len(searches)
    total_wishlisted = len(wishlisted)
    total_purchases = len(purchase_rows)
    total_cart_adds = sum(1 for b in browsing if b.event_type == "add_to_cart") + \
                      sum(1 for e in sess_events if e.event_type == "add_to_cart")
    total_views     = sum(1 for b in browsing if b.event_type == "view") + \
                      sum(1 for e in sess_events if e.event_type == "product_view")

    from models import ShoppingSession
    total_sessions = db.query(ShoppingSession).filter(
        ShoppingSession.customer_id == customer_id
    ).count()

    # ── Conversion metrics ────────────────────────────────────────────────
    view_to_cart   = round(total_cart_adds / total_views, 4) if total_views > 0 else None
    cart_to_buy    = round(total_purchases / total_cart_adds, 4) if total_cart_adds > 0 else None

    # ── Temporal ──────────────────────────────────────────────────────────
    all_dates = (
        [b.created_at for b in browsing] +
        [s.created_at for s in searches] +
        [e.created_at for e in sess_events]
    )
    all_dates = [d for d in all_dates if d is not None]
    first_seen = min(all_dates).replace(tzinfo=timezone.utc) if all_dates else None
    last_seen  = max(all_dates).replace(tzinfo=timezone.utc) if all_dates else None
    days_since = (now - last_seen).days if last_seen else None

    # ── Intent signals ────────────────────────────────────────────────────
    # Recent searches (last 10, deduped, most recent first)
    seen_queries: set[str] = set()
    recent_queries: list[str] = []
    for s in searches[:20]:
        q = (s.query or "").strip().lower()
        if q and q not in seen_queries:
            seen_queries.add(q)
            recent_queries.append(s.query)
        if len(recent_queries) >= 10:
            break

    # Recently viewed categories (from browsing events, last 30 days)
    cutoff = now - timedelta(days=30)
    recent_cats: list[str] = []
    seen_cats: set[str] = set()
    for b in browsing:
        if b.created_at and b.created_at.replace(tzinfo=timezone.utc) < cutoff:
            break
        prod = products.get(b.product_id)
        if prod and prod.category not in seen_cats:
            seen_cats.add(prod.category)
            recent_cats.append(prod.category)
        if len(recent_cats) >= 10:
            break

    # Recently viewed products (last 5 distinct product_ids)
    recent_products: list[str] = []
    seen_pids: set[str] = set()
    for b in browsing:
        if b.product_id and b.product_id not in seen_pids:
            seen_pids.add(b.product_id)
            recent_products.append(b.product_id)
        if len(recent_products) >= 5:
            break

    # ── Lifecycle stage ───────────────────────────────────────────────────
    stage = _lifecycle(total_purchases, total_events, days_since)

    # ── Upsert CustomerMemory ─────────────────────────────────────────────
    mem = db.query(CustomerMemory).filter(
        CustomerMemory.customer_id == customer_id
    ).first()

    data = dict(
        top_categories            = dict(cat_counter.most_common(10)),
        top_brands                = dict(brand_counter.most_common(10)),
        top_subcategories         = dict(subcat_counter.most_common(10)),
        price_min                 = round(min(prices), 2) if prices else None,
        price_max                 = round(max(prices), 2) if prices else None,
        avg_order_value           = round(sum(prices) / len(prices), 2) if prices else None,
        total_sessions            = total_sessions,
        total_events              = total_events,
        total_searches            = total_searches,
        total_purchases           = total_purchases,
        total_wishlisted          = total_wishlisted,
        total_cart_adds           = total_cart_adds,
        view_to_cart_rate         = view_to_cart,
        cart_to_purchase_rate     = cart_to_buy,
        recent_searches           = recent_queries,
        recently_viewed_categories = recent_cats,
        recently_viewed_products  = recent_products,
        lifecycle_stage           = stage,
        first_seen_at             = first_seen,
        last_seen_at              = last_seen,
        days_since_last_visit     = days_since,
        last_computed_at          = now,
    )

    if mem:
        for k, v in data.items():
            setattr(mem, k, v)
    else:
        mem = CustomerMemory(customer_id=customer_id, **data)
        db.add(mem)

    db.commit()
    db.refresh(mem)
    return mem
