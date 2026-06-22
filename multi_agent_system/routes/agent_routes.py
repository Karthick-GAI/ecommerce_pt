"""Direct access endpoints for each specialist agent (bypasses orchestrator)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas import ChatRequest, ChatResponse
from models import AgentType, MASSession, MASHandoff
from agents import get_agent
from memory.store import (
    get_or_create_session, load_history, save_message,
    get_shared_context, update_shared_context,
)
from tools.registry import AGENT_TOOLS

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def list_agents():
    return {
        "agents": [
            {
                "type":        "customer_support",
                "description": "Handles order issues, refunds, complaints, returns, and FAQs.",
                "tools":       [t["function"]["name"] for t in AGENT_TOOLS["customer_support"]],
            },
            {
                "type":        "recommendation",
                "description": "Product discovery, personalised suggestions, comparisons, and deals.",
                "tools":       [t["function"]["name"] for t in AGENT_TOOLS["recommendation"]],
            },
            {
                "type":        "fulfillment",
                "description": "Cart review, checkout, payment status, shipment tracking, and returns.",
                "tools":       [t["function"]["name"] for t in AGENT_TOOLS["fulfillment"]],
            },
            {
                "type":        "inventory_planning",
                "description": "Stock health, demand forecasting, restock recommendations (ops team).",
                "tools":       [t["function"]["name"] for t in AGENT_TOOLS["inventory_planning"]],
            },
        ]
    }


@router.post("/{agent_type}/chat", response_model=ChatResponse)
async def agent_chat(
    agent_type: AgentType,
    req: ChatRequest,
    db: Session = Depends(get_db),
):
    if agent_type == AgentType.orchestrator:
        raise HTTPException(status_code=400, detail="Use /chat for the orchestrator.")

    session    = get_or_create_session(db, req.session_id, req.customer_id)
    session_id = session.id

    if req.customer_id:
        update_shared_context(session_id, {"customer_id": req.customer_id}, db)

    context = get_shared_context(session_id, db)
    history = load_history(session_id, db)

    save_message(session_id, "user", req.message, db)

    agent  = get_agent(agent_type)
    result = await agent.run(req.message, history, context, db, session_id)

    save_message(
        session_id, "assistant", result.content, db,
        agent_type=agent_type, tools_used=result.tools_used,
    )

    return ChatResponse(
        session_id       = session_id,
        agent_type       = agent_type,
        content          = result.content,
        tools_used       = result.tools_used,
        handoff_occurred = result.handoff is not None,
        ticket_id        = result.ticket_id,
    )


@router.get("/{agent_type}/tools")
def get_agent_tools(agent_type: AgentType):
    if agent_type == AgentType.orchestrator:
        return {"tools": [], "note": "Orchestrator has no tools — it routes to specialist agents."}
    tools = AGENT_TOOLS.get(agent_type.value, [])
    return {
        "agent_type": agent_type.value,
        "tool_count": len(tools),
        "tools": [
            {
                "name":        t["function"]["name"],
                "description": t["function"]["description"],
                "parameters":  list(t["function"].get("parameters", {}).get("properties", {}).keys()),
                "required":    t["function"].get("parameters", {}).get("required", []),
            }
            for t in tools
        ],
    }


@router.get("/sessions/{session_id}/handoffs")
def get_session_handoffs(session_id: str, db: Session = Depends(get_db)):
    session = db.query(MASSession).filter(MASSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    handoffs = (
        db.query(MASHandoff)
        .filter(MASHandoff.session_id == session_id)
        .order_by(MASHandoff.created_at.asc())
        .all()
    )
    return {
        "session_id":     session_id,
        "total_handoffs": len(handoffs),
        "handoffs": [
            {
                "from_agent": h.from_agent.value,
                "to_agent":   h.to_agent.value,
                "reason":     h.reason,
                "at":         str(h.created_at),
            }
            for h in handoffs
        ],
    }
