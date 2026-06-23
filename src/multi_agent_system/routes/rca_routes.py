"""
RCA API routes — root cause analysis for inventory mismatches and failed orders.

Endpoints:
  POST /rca/order/{order_id}        — analyze a specific failed/stuck order
  POST /rca/inventory/{product_id}  — analyze a product with stock discrepancies
  POST /rca/batch                   — analyze the most recent batch of failed orders
  GET  /rca/reports                 — list recent RCA reports
  GET  /rca/reports/{analysis_id}   — fetch a specific report
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from rca import RCACoordinator
from models import RCAReport

router = APIRouter(prefix="/rca", tags=["rca"])


@router.post("/order/{order_id}", summary="Run RCA for a failed or stuck order")
async def analyze_order(order_id: str, db: Session = Depends(get_db)):
    coordinator = RCACoordinator()
    result = await coordinator.analyze(
        target_id=order_id,
        target_type="order",
        db=db,
    )
    return {
        "analysis_id":       result.analysis_id,
        "target_type":       result.target_type,
        "target_id":         result.target_id,
        "root_cause_type":   result.root_cause_type,
        "confidence":        result.confidence,
        "summary":           result.summary,
        "remediation_steps": result.remediation_steps,
        "anomalies_found":   result.anomalies_found,
        "status":            result.status,
        "duration_ms":       result.duration_ms,
        "agent_messages":    result.message_log,
    }


@router.post("/inventory/{product_id}", summary="Run RCA for a product with stock discrepancies")
async def analyze_inventory(product_id: str, db: Session = Depends(get_db)):
    coordinator = RCACoordinator()
    result = await coordinator.analyze(
        target_id=product_id,
        target_type="product",
        db=db,
    )
    return {
        "analysis_id":       result.analysis_id,
        "target_type":       result.target_type,
        "target_id":         result.target_id,
        "root_cause_type":   result.root_cause_type,
        "confidence":        result.confidence,
        "summary":           result.summary,
        "remediation_steps": result.remediation_steps,
        "anomalies_found":   result.anomalies_found,
        "status":            result.status,
        "duration_ms":       result.duration_ms,
        "agent_messages":    result.message_log,
    }


@router.post("/batch", summary="Run RCA across the most recent batch of failed orders")
async def analyze_batch(db: Session = Depends(get_db)):
    coordinator = RCACoordinator()
    result = await coordinator.analyze(
        target_id="batch",
        target_type="batch",
        db=db,
    )
    return {
        "analysis_id":       result.analysis_id,
        "target_type":       result.target_type,
        "target_id":         result.target_id,
        "root_cause_type":   result.root_cause_type,
        "confidence":        result.confidence,
        "summary":           result.summary,
        "remediation_steps": result.remediation_steps,
        "anomalies_found":   result.anomalies_found,
        "status":            result.status,
        "duration_ms":       result.duration_ms,
        "agent_messages":    result.message_log,
    }


@router.get("/reports", summary="List recent RCA reports")
def list_reports(limit: int = 20, db: Session = Depends(get_db)):
    reports = (
        db.query(RCAReport)
        .order_by(RCAReport.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return [
        {
            "analysis_id":     r.analysis_id,
            "target_type":     r.target_type,
            "target_id":       r.target_id,
            "root_cause_type": r.root_cause_type,
            "confidence":      r.confidence,
            "anomalies_found": r.anomalies_found,
            "status":          "completed" if r.root_cause_type != "FAILED" else "failed",
            "created_at":      r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]


@router.get("/reports/{analysis_id}", summary="Get a specific RCA report")
def get_report(analysis_id: str, db: Session = Depends(get_db)):
    report = (
        db.query(RCAReport)
        .filter(RCAReport.analysis_id == analysis_id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail=f"No RCA report found for analysis_id={analysis_id}")

    return {
        "analysis_id":       report.analysis_id,
        "target_type":       report.target_type,
        "target_id":         report.target_id,
        "root_cause_type":   report.root_cause_type,
        "confidence":        report.confidence,
        "summary":           report.summary,
        "remediation_steps": report.remediation,
        "anomalies_found":   report.anomalies_found,
        "agent_messages":    report.agent_messages,
        "created_at":        report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/agents", summary="Describe the RCA agent system")
def describe_agents():
    return {
        "system": "Root Cause Analysis — Collaborative AI Agents",
        "agents": [
            {
                "name": "data_collector",
                "role": "Step 1 — Gathers raw evidence (order details, movement audits, discrepancies)",
                "tools": ["get_order_failure_details", "get_inventory_movement_audit",
                          "get_inventory_alert_history", "detect_stock_discrepancy", "get_failed_orders_batch"],
                "emits": "RCA_DATA_COLLECTED",
            },
            {
                "name": "inventory_analyzer",
                "role": "Step 2a — Classifies inventory anomalies (oversell, missing movements, corruption)",
                "tools": ["detect_stock_discrepancy", "get_concurrent_order_pressure"],
                "emits": "RCA_INV_ANOMALIES",
            },
            {
                "name": "order_analyzer",
                "role": "Step 2b — Classifies order failures (payment, stuck state, stockout at checkout)",
                "tools": ["get_order_lifecycle_trace", "get_payment_failure_pattern"],
                "emits": "RCA_ORD_ANOMALIES",
            },
            {
                "name": "root_cause",
                "role": "Step 3 — Synthesizes both anomaly reports into a single root cause + remediation",
                "tools": [],
                "emits": "RCA_COMPLETE",
            },
        ],
        "root_cause_taxonomy": [
            "OVERSELL_RACE_CONDITION", "DOUBLE_DEDUCTION", "MISSING_MOVEMENT_RECORD",
            "MANUAL_ADJUSTMENT_WITHOUT_AUDIT", "RETURN_NOT_RESTOCKED", "DATA_CORRUPTION",
            "PAYMENT_GATEWAY_TIMEOUT", "INSUFFICIENT_STOCK_AT_CHECKOUT",
            "PAYMENT_DECLINED", "STATE_MACHINE_STUCK", "CONCURRENT_OVERSELL", "UNKNOWN",
        ],
    }
