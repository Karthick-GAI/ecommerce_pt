"""System metrics and agent performance analytics."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from database import get_db
from models import (
    MASSession, MASMessage, MASHandoff, SupportTicket,
    AgentAnalyticsLog, AgentType, SessionStatus, TicketStatus,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def analytics_overview(db: Session = Depends(get_db)):
    total_sessions  = db.query(func.count(MASSession.id)).scalar() or 0
    active_sessions = db.query(func.count(MASSession.id)).filter(
        MASSession.status == SessionStatus.active
    ).scalar() or 0
    total_messages  = db.query(func.count(MASMessage.id)).scalar() or 0
    total_handoffs  = db.query(func.count(MASHandoff.id)).scalar() or 0
    open_tickets    = db.query(func.count(SupportTicket.id)).filter(
        SupportTicket.status.in_([TicketStatus.open, TicketStatus.in_progress])
    ).scalar() or 0
    escalated_tickets = db.query(func.count(SupportTicket.id)).filter(
        SupportTicket.status == TicketStatus.escalated
    ).scalar() or 0

    # Per-agent stats
    agent_stats = []
    for agent_type in [a for a in AgentType if a != AgentType.orchestrator]:
        rows = db.query(AgentAnalyticsLog).filter(
            AgentAnalyticsLog.agent_type == agent_type
        ).all()
        total        = len(rows)
        resolved_cnt = sum(1 for r in rows if r.resolved)
        handoff_cnt  = sum(1 for r in rows if r.handoff_to is not None)
        avg_rt       = (
            round(sum(r.response_time_ms for r in rows if r.response_time_ms) / total, 1)
            if total > 0 else None
        )

        # Top intents (frequency count)
        intent_counts: dict = {}
        for r in rows:
            if r.intent:
                intent_counts[r.intent] = intent_counts.get(r.intent, 0) + 1
        top_intents = sorted(intent_counts, key=lambda k: intent_counts[k], reverse=True)[:3]

        agent_stats.append({
            "agent_type":        agent_type.value,
            "total_invocations": total,
            "avg_response_time_ms": avg_rt,
            "resolution_rate":   round(resolved_cnt / total, 2) if total > 0 else 0.0,
            "handoff_rate":      round(handoff_cnt / total, 2) if total > 0 else 0.0,
            "top_intents":       top_intents,
        })

    return {
        "sessions": {
            "total":    total_sessions,
            "active":   active_sessions,
        },
        "messages":         total_messages,
        "handoffs":         total_handoffs,
        "support_tickets": {
            "open":      open_tickets,
            "escalated": escalated_tickets,
        },
        "agents": agent_stats,
    }


@router.get("/support-tickets")
def support_ticket_analytics(db: Session = Depends(get_db)):
    try:
        rows = db.execute(text("""
            SELECT
                issue_type,
                status,
                priority,
                COUNT(*) AS count,
                AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - created_at)) / 3600) AS avg_resolution_hours
            FROM mas_support_tickets
            GROUP BY issue_type, status, priority
            ORDER BY count DESC
        """)).fetchall()
    except Exception:
        rows = []

    by_issue_type: dict = {}
    by_status: dict     = {}
    by_priority: dict   = {}

    for r in rows:
        by_issue_type[r.issue_type] = by_issue_type.get(r.issue_type, 0) + r.count
        by_status[r.status]         = by_status.get(r.status, 0) + r.count
        by_priority[r.priority]     = by_priority.get(r.priority, 0) + r.count

    total = sum(by_status.values())
    return {
        "total_tickets":     total,
        "by_status":         by_status,
        "by_issue_type":     by_issue_type,
        "by_priority":       by_priority,
    }


@router.get("/inventory-forecasts")
def forecast_analytics(db: Session = Depends(get_db)):
    from models import InventoryForecast
    from sqlalchemy import func as sqlfunc

    forecasts = (
        db.query(InventoryForecast)
        .order_by(InventoryForecast.created_at.desc())
        .limit(50)
        .all()
    )

    critical = [f for f in forecasts if f.days_until_stockout is not None and f.days_until_stockout <= 7]

    return {
        "total_forecasts_generated": len(forecasts),
        "critical_stockout_risk":    len(critical),
        "critical_products": [
            {
                "product_id":          f.product_id,
                "product_name":        f.product_name,
                "days_until_stockout": f.days_until_stockout,
                "recommended_restock": f.recommended_restock_qty,
                "trend":               f.trend,
            }
            for f in sorted(critical, key=lambda x: x.days_until_stockout or 0)[:10]
        ],
        "recent_forecasts": [
            {
                "product_id":          f.product_id,
                "product_name":        f.product_name,
                "avg_daily_demand":    f.avg_daily_demand,
                "predicted_demand":    f.predicted_demand,
                "trend":               f.trend,
                "confidence":          f.confidence_score,
                "recommended_restock": f.recommended_restock_qty,
            }
            for f in forecasts[:10]
        ],
    }
