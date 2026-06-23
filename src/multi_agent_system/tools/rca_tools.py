"""
RCA tools — read-only diagnostic queries used by the three RCA agents.

All functions return JSON strings. None of them write to the database.
They pull from the same shared tables the rest of the multi-agent system uses.

Tools by responsibility
───────────────────────
Data collection    : get_order_failure_details, get_inventory_movement_audit,
                     get_failed_orders_batch, get_inventory_alert_history
Inventory analysis : detect_stock_discrepancy, get_concurrent_order_pressure
Order analysis     : get_order_lifecycle_trace, get_payment_failure_pattern
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text

from tools.shared_models import (
    Product, CheckoutOrder, CheckoutOrderItem, CheckoutPayment,
    InventoryMovement, InventoryAlert, OrderStatusHistory, Refund,
)


# ── Data collection tools ──────────────────────────────────────────────────────

def get_order_failure_details(order_id: str, db: Session) -> str:
    """
    Pull every piece of diagnostic data for a failed or stuck order:
    order row, payment row (including failure reason), line items,
    status history timeline, and refund status.
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    payment = db.query(CheckoutPayment).filter(CheckoutPayment.order_id == order_id).first()
    items   = db.query(CheckoutOrderItem).filter(CheckoutOrderItem.order_id == order_id).all()
    history = (
        db.query(OrderStatusHistory)
        .filter(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at.asc())
        .all()
    )
    refund  = db.query(Refund).filter(Refund.order_id == order_id).first()

    # Detect stuck state: last transition was > 6 hours ago and order is not terminal
    stuck = False
    terminal_statuses = {"delivered", "cancelled", "refunded"}
    if history and order.status not in terminal_statuses:
        last_ts = history[-1].created_at
        if last_ts:
            elapsed_h = (datetime.now(timezone.utc) - last_ts.replace(tzinfo=timezone.utc)).total_seconds() / 3600
            stuck = elapsed_h > 6

    return json.dumps({
        "order_id":       order_id,
        "status":         order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total":          order.total,
        "created_at":     str(order.created_at),
        "is_stuck":       stuck,
        "payment": {
            "status":          payment.status         if payment else None,
            "transaction_id":  payment.transaction_id if payment else None,
            "paid_at":         str(payment.paid_at)   if payment and payment.paid_at else None,
        } if payment else None,
        "items": [
            {
                "product_id":   i.product_id,
                "product_name": i.product_name,
                "quantity":     i.quantity,
                "unit_price":   i.unit_price,
            }
            for i in items
        ],
        "status_timeline": [
            {
                "status":    h.status,
                "note":      h.note,
                "timestamp": str(h.created_at),
            }
            for h in history
        ],
        "refund": {
            "status":     refund.status,
            "amount":     refund.amount,
            "reason":     refund.reason,
            "created_at": str(refund.created_at),
        } if refund else None,
    })


def get_inventory_movement_audit(product_id: str, db: Session, days: int = 60) -> str:
    """
    Pull the full movement history for a product and compute a running balance.
    Flags any gap where: quantity_before + quantity_change ≠ quantity_after.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return json.dumps({"error": f"Product {product_id} not found."})

    since = datetime.now(timezone.utc) - timedelta(days=days)
    movements = (
        db.query(InventoryMovement)
        .filter(
            InventoryMovement.product_id == product_id,
            InventoryMovement.created_at >= since,
        )
        .order_by(InventoryMovement.created_at.asc())
        .all()
    )

    inconsistencies: list[dict] = []
    net_change = 0
    for m in movements:
        net_change += (m.quantity_change or 0)
        # A chain gap: the 'before' of this movement should equal 'after' of previous
        expected_after = m.quantity_before + (m.quantity_change or 0)
        if m.quantity_after is not None and abs(expected_after - m.quantity_after) > 0:
            inconsistencies.append({
                "movement_id": m.id,
                "timestamp":   str(m.created_at),
                "type":        m.movement_type,
                "expected_after": expected_after,
                "recorded_after": m.quantity_after,
                "gap":            m.quantity_after - expected_after,
            })

    return json.dumps({
        "product_id":       product_id,
        "product_name":     product.name,
        "current_stock":    product.inventory_count,
        "period_days":      days,
        "movement_count":   len(movements),
        "net_change_in_period": net_change,
        "chain_inconsistencies": inconsistencies,
        "inconsistency_count":   len(inconsistencies),
        "movements": [
            {
                "id":       m.id,
                "type":     m.movement_type,
                "change":   m.quantity_change,
                "before":   m.quantity_before,
                "after":    m.quantity_after,
                "reason":   m.reason,
                "by":       m.performed_by,
                "at":       str(m.created_at),
            }
            for m in movements[-20:]  # last 20 for brevity
        ],
    })


def get_failed_orders_batch(db: Session, status_filter: str = None, limit: int = 20) -> str:
    """
    Return a batch of failed or stuck orders for pattern analysis.
    Groups results by status and payment_method to surface common failure modes.
    """
    terminal_ok = {"delivered", "refunded"}

    if status_filter:
        orders = (
            db.query(CheckoutOrder)
            .filter(CheckoutOrder.status == status_filter)
            .order_by(CheckoutOrder.created_at.desc())
            .limit(min(limit, 50))
            .all()
        )
    else:
        orders = (
            db.query(CheckoutOrder)
            .filter(
                CheckoutOrder.status.in_(
                    ["cancelled", "payment_failed", "processing", "confirmed"]
                )
            )
            .order_by(CheckoutOrder.created_at.desc())
            .limit(min(limit, 50))
            .all()
        )

    # Group by (status, payment_method)
    groups: dict[tuple, int] = {}
    for o in orders:
        key = (o.status, o.payment_method or "unknown")
        groups[key] = groups.get(key, 0) + 1

    return json.dumps({
        "total_found":   len(orders),
        "status_filter": status_filter or "all_non_terminal",
        "pattern_groups": [
            {"status": s, "payment_method": pm, "count": cnt}
            for (s, pm), cnt in sorted(groups.items(), key=lambda x: -x[1])
        ],
        "orders": [
            {
                "order_id":       o.id,
                "status":         o.status,
                "payment_status": o.payment_status,
                "payment_method": o.payment_method,
                "total":          o.total,
                "created_at":     str(o.created_at),
            }
            for o in orders[:20]
        ],
    })


def get_inventory_alert_history(product_id: str, db: Session) -> str:
    """
    Pull all inventory alerts for a product — useful context for understanding
    when stock problems first appeared and how they evolved.
    """
    alerts = (
        db.query(InventoryAlert)
        .filter(InventoryAlert.product_id == product_id)
        .order_by(InventoryAlert.created_at.desc())
        .limit(30)
        .all()
    )

    product = db.query(Product).filter(Product.id == product_id).first()

    return json.dumps({
        "product_id":    product_id,
        "product_name":  product.name if product else "unknown",
        "current_stock": product.inventory_count if product else None,
        "total_alerts":  len(alerts),
        "open_alerts":   sum(1 for a in alerts if not a.is_resolved),
        "alerts": [
            {
                "alert_id":      a.id,
                "type":          a.alert_type,
                "severity":      a.severity,
                "message":       a.message,
                "acknowledged":  a.is_acknowledged,
                "resolved":      a.is_resolved,
                "created_at":    str(a.created_at),
            }
            for a in alerts
        ],
    })


# ── Inventory analysis tools ───────────────────────────────────────────────────

def detect_stock_discrepancy(product_id: str, db: Session) -> str:
    """
    Reconcile the product's current inventory_count against the net sum of all
    recorded movement records.

    Method:
      1. Find oldest movement → take quantity_before as "baseline stock"
      2. Sum all quantity_change values
      3. Expected stock = baseline + sum_of_changes
      4. Discrepancy = expected − current
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return json.dumps({"error": f"Product {product_id} not found."})

    movements = (
        db.query(InventoryMovement)
        .filter(InventoryMovement.product_id == product_id)
        .order_by(InventoryMovement.created_at.asc())
        .all()
    )

    if not movements:
        return json.dumps({
            "product_id":    product_id,
            "product_name":  product.name,
            "current_stock": product.inventory_count,
            "movement_count": 0,
            "discrepancy_detected": False,
            "message": "No movement records found. Cannot reconcile.",
        })

    baseline    = movements[0].quantity_before or 0
    total_delta = sum(m.quantity_change or 0 for m in movements)
    expected    = baseline + total_delta
    current     = product.inventory_count or 0
    discrepancy = expected - current

    # Detect negative stock events
    running = baseline
    negative_events = []
    for m in movements:
        running += (m.quantity_change or 0)
        if running < 0:
            negative_events.append({
                "at":       str(m.created_at),
                "type":     m.movement_type,
                "change":   m.quantity_change,
                "running":  running,
            })

    # Detect suspicious restock spikes (change > 100 in one movement)
    large_restocks = [
        {
            "at":     str(m.created_at),
            "change": m.quantity_change,
            "reason": m.reason,
            "by":     m.performed_by,
        }
        for m in movements
        if (m.quantity_change or 0) > 100
    ]

    return json.dumps({
        "product_id":            product_id,
        "product_name":          product.name,
        "baseline_stock":        baseline,
        "total_recorded_change": total_delta,
        "expected_stock":        expected,
        "current_stock":         current,
        "discrepancy":           discrepancy,
        "discrepancy_detected":  discrepancy != 0,
        "discrepancy_direction": (
            "system_overstated" if discrepancy < 0
            else "system_understated" if discrepancy > 0
            else "balanced"
        ),
        "negative_stock_events": negative_events,
        "large_restock_events":  large_restocks,
        "total_movements":       len(movements),
    })


def get_concurrent_order_pressure(
    product_id: str,
    db: Session,
    window_minutes: int = 10,
) -> str:
    """
    Find orders containing a product that were placed within a time window.
    Clusters of orders for the same low-stock product within minutes of each other
    are a strong signal for oversell race conditions.
    """
    try:
        rows = db.execute(text("""
            SELECT
                o.id            AS order_id,
                o.status,
                o.payment_status,
                oi.quantity,
                o.created_at
            FROM checkout_order_items oi
            JOIN checkout_orders o ON o.id = oi.order_id
            WHERE oi.product_id = :pid
            ORDER BY o.created_at DESC
            LIMIT 50
        """), {"pid": product_id}).fetchall()
    except Exception as e:
        return json.dumps({"error": str(e)})

    if not rows:
        return json.dumps({"product_id": product_id, "concurrent_clusters": [], "total_orders": 0})

    # Build time-based clusters (orders within window_minutes of each other)
    clusters: list[list[dict]] = []
    current_cluster: list[dict] = []
    cluster_start = None

    for row in rows:
        ts = row.created_at
        if ts is None:
            continue
        if cluster_start is None:
            cluster_start = ts
            current_cluster = [row]
        else:
            diff_minutes = abs((ts - cluster_start).total_seconds()) / 60
            if diff_minutes <= window_minutes:
                current_cluster.append(row)
            else:
                if len(current_cluster) > 1:
                    clusters.append(current_cluster)
                current_cluster = [row]
                cluster_start = ts

    if len(current_cluster) > 1:
        clusters.append(current_cluster)

    product = db.query(Product).filter(Product.id == product_id).first()

    return json.dumps({
        "product_id":        product_id,
        "product_name":      product.name if product else "unknown",
        "current_stock":     product.inventory_count if product else None,
        "window_minutes":    window_minutes,
        "total_orders":      len(rows),
        "concurrent_clusters": [
            {
                "cluster_size": len(cluster),
                "total_qty_demanded": sum(r.quantity for r in cluster),
                "time_span_sec": abs(
                    (cluster[-1].created_at - cluster[0].created_at).total_seconds()
                ),
                "statuses": list({r.status for r in cluster}),
                "orders": [
                    {"order_id": r.order_id, "qty": r.quantity,
                     "status": r.status, "at": str(r.created_at)}
                    for r in cluster
                ],
            }
            for cluster in clusters
        ],
        "oversell_risk": len(clusters) > 0,
    })


# ── Order analysis tools ───────────────────────────────────────────────────────

def get_order_lifecycle_trace(order_id: str, db: Session) -> str:
    """
    Reconstruct the full state machine trace for an order.
    Detects:
      • Stuck states (no transition for > 6 hours while non-terminal)
      • Backwards transitions (e.g., confirmed → pending)
      • Missing expected transitions (paid but never 'processing')
      • Duplicate status entries
    """
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    history = (
        db.query(OrderStatusHistory)
        .filter(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at.asc())
        .all()
    )

    expected_flow = [
        "pending", "confirmed", "processing", "shipped", "delivered"
    ]
    terminal = {"delivered", "cancelled", "refunded", "payment_failed"}

    # Detect stuck state
    stuck_for_hours = None
    if history and order.status not in terminal:
        last_ts = history[-1].created_at
        if last_ts:
            stuck_for_hours = round(
                (datetime.now(timezone.utc) - last_ts.replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1
            )

    # Detect backwards transitions
    backwards = []
    for i in range(1, len(history)):
        prev_idx = expected_flow.index(history[i-1].status) if history[i-1].status in expected_flow else -1
        curr_idx = expected_flow.index(history[i].status) if history[i].status in expected_flow else -1
        if prev_idx > curr_idx >= 0:
            backwards.append({
                "from": history[i-1].status,
                "to":   history[i].status,
                "at":   str(history[i].created_at),
            })

    # Detect duplicate statuses
    statuses_seen = [h.status for h in history]
    duplicates = [s for s in set(statuses_seen) if statuses_seen.count(s) > 1]

    # Time gaps between transitions
    gaps = []
    for i in range(1, len(history)):
        t1 = history[i-1].created_at
        t2 = history[i].created_at
        if t1 and t2:
            gap_h = (t2.replace(tzinfo=timezone.utc) - t1.replace(tzinfo=timezone.utc)).total_seconds() / 3600
            gaps.append({
                "from":     history[i-1].status,
                "to":       history[i].status,
                "gap_hours": round(gap_h, 2),
            })

    return json.dumps({
        "order_id":          order_id,
        "current_status":    order.status,
        "payment_status":    order.payment_status,
        "is_terminal":       order.status in terminal,
        "stuck_for_hours":   stuck_for_hours,
        "is_stuck":          (stuck_for_hours is not None and stuck_for_hours > 6),
        "backwards_transitions": backwards,
        "duplicate_statuses":    duplicates,
        "transition_gaps":       gaps,
        "timeline": [
            {"status": h.status, "note": h.note, "at": str(h.created_at)}
            for h in history
        ],
    })


def get_payment_failure_pattern(order_id: str, db: Session) -> str:
    """
    Analyse the payment failure for an order and look for similar failures
    from the same customer / payment method in the past 30 days.
    This surfaces systemic payment issues vs one-off user errors.
    """
    order   = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."})

    payment = db.query(CheckoutPayment).filter(CheckoutPayment.order_id == order_id).first()

    # Look for other failed payments in the last 30 days with the same method
    since = datetime.now(timezone.utc) - timedelta(days=30)
    similar_failures: list[dict] = []
    if order.payment_method:
        try:
            similar_orders = (
                db.query(CheckoutOrder)
                .filter(
                    CheckoutOrder.payment_method == order.payment_method,
                    CheckoutOrder.payment_status == "failed",
                    CheckoutOrder.created_at >= since,
                    CheckoutOrder.id != order_id,
                )
                .limit(20)
                .all()
            )
            similar_failures = [
                {"order_id": o.id, "total": o.total, "at": str(o.created_at)}
                for o in similar_orders
            ]
        except Exception:
            pass

    failure_category = _classify_payment_failure(
        payment_status=order.payment_status,
        payment=payment,
    )

    return json.dumps({
        "order_id":          order_id,
        "payment_method":    order.payment_method,
        "payment_status":    order.payment_status,
        "transaction_id":    payment.transaction_id if payment else None,
        "paid_at":           str(payment.paid_at) if payment and payment.paid_at else None,
        "failure_category":  failure_category,
        "similar_failures_30d": len(similar_failures),
        "similar_failure_samples": similar_failures[:5],
        "is_systemic":       len(similar_failures) >= 5,
    })


def _classify_payment_failure(payment_status: str, payment) -> str:
    if payment_status in ("paid", "captured"):
        return "payment_succeeded"
    if payment_status == "pending":
        return "payment_pending_not_completed"
    if payment_status == "failed":
        return "payment_failed"
    if payment_status == "refund_pending":
        return "refund_queued"
    return "unknown"
