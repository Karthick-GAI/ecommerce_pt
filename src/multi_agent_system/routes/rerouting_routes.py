"""
Rerouting API — autonomous A2A order rerouting when stock is unavailable.

Endpoints
─────────
POST /rerouting/trigger/{order_id}        — start a full 4-step reroute workflow
POST /rerouting/simulate/{order_id}       — dry-run: assess only, no DB writes
GET  /rerouting/history                   — list recent RerouteEvent records
GET  /rerouting/history/{order_id}        — get reroute history for one order
GET  /rerouting/agents                    — describe the 3 rerouting agents

The rerouting workflow is fully autonomous:
  OrderManagementAgent  → assesses stockout
  InventoryAgent        → finds substitutes
  LogisticsAgent        → validates feasibility & builds plan
  OrderManagementAgent  → applies the plan or cancels
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/rerouting", tags=["A2A Rerouting"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────

class RerouteResponse(BaseModel):
    run_id:        str
    order_id:      str
    outcome:       str
    duration_ms:   int
    message_count: int
    result:        dict
    message_log:   list


class SimulateResponse(BaseModel):
    order_id:        str
    stockout_detected: bool
    stockout_items:  list
    ok_items:        list
    assessment_note: str


# ── POST /rerouting/trigger/{order_id} ────────────────────────────────────────

@router.post(
    "/trigger/{order_id}",
    response_model=RerouteResponse,
    summary="Trigger autonomous A2A rerouting for an order",
    description=(
        "Runs the full 4-step agent-to-agent rerouting protocol:\n\n"
        "1. **OrderManagementAgent** — detect which line items are out of stock\n"
        "2. **InventoryAgent** — find in-stock substitute products\n"
        "3. **LogisticsAgent** — validate feasibility and build the logistics plan\n"
        "4. **OrderManagementAgent** — apply the reroute (or cancel + refund)\n\n"
        "Returns the full inter-agent message log and the final outcome."
    ),
)
async def trigger_rerouting(order_id: str, db: Session = Depends(get_db)):
    from rerouting.coordinator import RerouteCoordinator

    # Verify order exists before spinning up agents
    from tools.shared_models import CheckoutOrder
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

    coordinator = RerouteCoordinator()
    result = await coordinator.handle(order_id, db)
    return result.to_dict()


# ── POST /rerouting/simulate/{order_id} ───────────────────────────────────────

@router.post(
    "/simulate/{order_id}",
    response_model=SimulateResponse,
    summary="Dry-run: assess stockout without applying any changes",
    description=(
        "Runs only Step 1 (OrderManagementAgent stockout assessment). "
        "No DB writes are made. Use this to preview which items would be "
        "rerouted before running a full trigger."
    ),
)
async def simulate_rerouting(order_id: str, db: Session = Depends(get_db)):
    from tools.rerouting_tools import assess_order_stockout
    import json

    from tools.shared_models import CheckoutOrder
    order = db.query(CheckoutOrder).filter(CheckoutOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

    raw = assess_order_stockout(order_id, db)
    data = json.loads(raw)

    if "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])

    stockout_items = data.get("stockout_items", [])
    ok_items       = data.get("ok_items", [])

    if data.get("stockout_detected"):
        note = (
            f"{len(stockout_items)} item(s) would be rerouted: "
            + ", ".join(s["product_name"] for s in stockout_items)
        )
    else:
        note = "All items are in stock. No rerouting would be needed."

    return {
        "order_id":          order_id,
        "stockout_detected": data.get("stockout_detected", False),
        "stockout_items":    stockout_items,
        "ok_items":          ok_items,
        "assessment_note":   note,
    }


# ── GET /rerouting/history ─────────────────────────────────────────────────────

@router.get(
    "/history",
    summary="List recent rerouting events",
)
def get_reroute_history(limit: int = 20, db: Session = Depends(get_db)):
    from models import RerouteEvent
    events = (
        db.query(RerouteEvent)
        .order_by(RerouteEvent.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return {
        "total": len(events),
        "events": [
            {
                "run_id":        e.run_id,
                "order_id":      e.order_id,
                "outcome":       e.outcome,
                "message_count": e.message_count,
                "created_at":    e.created_at.isoformat(),
            }
            for e in events
        ],
    }


# ── GET /rerouting/history/{order_id} ─────────────────────────────────────────

@router.get(
    "/history/{order_id}",
    summary="Get rerouting history for a specific order",
)
def get_order_reroute_history(order_id: str, db: Session = Depends(get_db)):
    from models import RerouteEvent
    events = (
        db.query(RerouteEvent)
        .filter(RerouteEvent.order_id == order_id)
        .order_by(RerouteEvent.created_at.desc())
        .all()
    )
    return {
        "order_id": order_id,
        "reroute_count": len(events),
        "events": [
            {
                "run_id":        e.run_id,
                "outcome":       e.outcome,
                "message_count": e.message_count,
                "created_at":    e.created_at.isoformat(),
            }
            for e in events
        ],
    }


# ── GET /rerouting/agents ──────────────────────────────────────────────────────

@router.get(
    "/agents",
    summary="Describe the three rerouting agents and their tools",
)
def describe_agents():
    return {
        "protocol": "4-step agent-to-agent (A2A) message passing",
        "message_bus": "In-process AgentBus (ordered audit log per run)",
        "agents": [
            {
                "name": "order_management",
                "step": [1, 4],
                "tools": ["assess_order_stockout", "apply_reroute_decision", "cancel_order_and_refund"],
                "step1_output": "STOCKOUT_DETECTED — structured list of blocked line items",
                "step4_output": "REROUTE_APPLIED | ORDER_CANCELLED",
            },
            {
                "name": "inventory",
                "step": 2,
                "tools": ["find_alternative_products", "check_warehouse_stock"],
                "output": "ALTERNATIVES_READY — recommended_substitutes per stockout item",
            },
            {
                "name": "logistics",
                "step": 3,
                "tools": ["create_logistics_reroute_plan"],
                "output": "REROUTE_PLAN — feasible plan with price delta and ETA, or action=cancel",
            },
        ],
        "outcomes": {
            "rerouted":         "Order line item swapped to substitute; stock deducted; audit trail written",
            "cancelled":        "Order cancelled and refund queued (no viable substitute found)",
            "no_action_needed": "All items were in stock; no rerouting required",
            "failed":           "Agent error; no DB changes made",
        },
    }
