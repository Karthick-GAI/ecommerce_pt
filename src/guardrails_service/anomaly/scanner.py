"""
Full-platform anomaly scanner.

run_full_scan() runs all detectors in sequence, deduplicates results,
persists new AnomalyAlerts, and returns a summary.
"""
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from database import SessionLocal
from models import AnomalyAlert
from anomaly.detectors import (
    detect_order_amount_anomalies,
    detect_rapid_ordering,
    detect_payment_failure_spree,
    detect_search_injection,
    detect_inventory_anomalies,
    detect_bot_behavior,
    detect_bulk_purchases,
    detect_payment_replay,
    detect_new_account_high_value,
    detect_inventory_drain,
    dedupe_alerts,
)


DETECTORS = [
    ("order_amount",     detect_order_amount_anomalies),
    ("rapid_ordering",   detect_rapid_ordering),
    ("payment_failure",  detect_payment_failure_spree),
    ("search_injection", detect_search_injection),
    ("inventory",        detect_inventory_anomalies),
    ("bot_behavior",     detect_bot_behavior),
    ("bulk_purchase",    detect_bulk_purchases),
    ("payment_replay",   detect_payment_replay),
    ("new_account",      detect_new_account_high_value),
    ("inventory_drain",  detect_inventory_drain),
]


def run_full_scan(db: Session | None = None, scan_type: str = "full") -> dict:
    """
    Run all anomaly detectors, deduplicate against existing open alerts,
    and persist new ones. Returns a summary dict.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()

    t0 = time.time()
    all_new: list[AnomalyAlert] = []
    errors: dict[str, str] = {}

    try:
        for name, detector in DETECTORS:
            try:
                raw = detector(db)
                all_new.extend(raw)
            except Exception as exc:
                errors[name] = str(exc)

        # Deduplicate against existing open alerts (24h window)
        to_persist = dedupe_alerts(all_new, db)

        for alert in to_persist:
            db.add(alert)

        if to_persist:
            db.commit()

        duration_ms = int((time.time() - t0) * 1000)

        # Count by severity
        severity_counts: dict[str, int] = {}
        for a in to_persist:
            severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1

        summary = (
            f"Scan complete: {len(to_persist)} new alert(s) in {duration_ms}ms. "
            f"Detectors: {len(DETECTORS) - len(errors)}/{len(DETECTORS)} succeeded."
        )
        if errors:
            summary += f" Errors in: {', '.join(errors)}"

        return {
            "scan_type":          scan_type,
            "duration_ms":        duration_ms,
            "detectors_run":      len(DETECTORS) - len(errors),
            "detectors_errored":  len(errors),
            "raw_alerts_found":   len(all_new),
            "new_alerts_saved":   len(to_persist),
            "alerts_by_severity": severity_counts,
            "errors":             errors,
            "summary":            summary,
        }

    finally:
        if own_session:
            db.close()


def run_targeted_scan(
    db: Session,
    target: str,  # "order_amount" | "payment" | "search" | "inventory" | "user"
) -> dict:
    """Run only the detectors relevant to a specific target."""
    target_map = {
        "order":     [detect_order_amount_anomalies, detect_rapid_ordering, detect_bulk_purchases],
        "payment":   [detect_payment_failure_spree, detect_payment_replay],
        "search":    [detect_search_injection, detect_bot_behavior],
        "inventory": [detect_inventory_anomalies, detect_inventory_drain],
        "user":      [detect_rapid_ordering, detect_payment_failure_spree,
                      detect_bot_behavior, detect_new_account_high_value],
    }
    detectors = target_map.get(target, [])
    if not detectors:
        return {"error": f"Unknown scan target: {target}", "new_alerts_saved": 0}

    t0       = time.time()
    all_new  = []
    errors   = {}
    for fn in detectors:
        try:
            all_new.extend(fn(db))
        except Exception as exc:
            errors[fn.__name__] = str(exc)

    to_persist = dedupe_alerts(all_new, db)
    for alert in to_persist:
        db.add(alert)
    if to_persist:
        db.commit()

    sev_counts: dict[str, int] = {}
    for a in to_persist:
        sev_counts[a.severity] = sev_counts.get(a.severity, 0) + 1

    return {
        "scan_type":          target,
        "duration_ms":        int((time.time() - t0) * 1000),
        "new_alerts_saved":   len(to_persist),
        "alerts_by_severity": sev_counts,
        "errors":             errors,
        "summary":            f"Targeted scan ({target}): {len(to_persist)} new alert(s).",
    }
