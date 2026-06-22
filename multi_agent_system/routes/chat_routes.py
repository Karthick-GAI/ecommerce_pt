"""
Primary chat endpoint — orchestrates intent classification, agent routing,
handoff chaining, and SSE streaming.
"""
import json
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from schemas import ChatRequest, ChatResponse
from models import AgentType, AgentAnalyticsLog
from orchestrator.router import route
from agents import get_agent
from memory.store import (
    get_or_create_session, load_history, save_message,
    record_handoff, update_shared_context, get_shared_context,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_MAX_HANDOFFS = 2  # prevent infinite handoff loops


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    t0 = time.monotonic()

    # ── Session ──────────────────────────────────────────────────────────────
    session = get_or_create_session(db, req.session_id, req.customer_id)
    session_id = session.id

    # Inject customer_id into shared context if provided
    if req.customer_id:
        update_shared_context(session_id, {"customer_id": req.customer_id}, db)

    context = get_shared_context(session_id, db)
    history = load_history(session_id, db)

    # ── Intent Classification ─────────────────────────────────────────────────
    if req.target_agent:
        target = req.target_agent
    else:
        decision = route(req.message, history)
        target   = decision.agent
        # Merge routing entities into shared context
        update_shared_context(session_id, decision.entities, db)
        context = get_shared_context(session_id, db)

    # Persist user message
    save_message(session_id, "user", req.message, db)

    # ── Agent Loop (with handoff support) ────────────────────────────────────
    handoff_count   = 0
    current_agent_t = target
    final_result    = None

    while handoff_count <= _MAX_HANDOFFS:
        agent  = get_agent(current_agent_t)
        result = await agent.run(req.message, history, context, db, session_id)

        if result.handoff and handoff_count < _MAX_HANDOFFS:
            # Log handoff
            record_handoff(
                session_id, current_agent_t, result.handoff.to_agent,
                result.handoff.reason, db, context,
            )
            if result.handoff.context_update:
                update_shared_context(session_id, result.handoff.context_update, db)
                context = get_shared_context(session_id, db)

            current_agent_t = result.handoff.to_agent
            handoff_count  += 1
            # Update history to include the handoff agent's partial response
            history.append({"role": "assistant", "content": result.content})
            continue

        final_result = result
        break

    if not final_result:
        final_result = result  # use last result even if handoff limit hit

    # Persist assistant response
    save_message(
        session_id, "assistant", final_result.content, db,
        agent_type=current_agent_t, tools_used=final_result.tools_used,
    )

    # ── Analytics log ─────────────────────────────────────────────────────────
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log = AgentAnalyticsLog(
        session_id       = session_id,
        agent_type       = current_agent_t,
        intent           = getattr(route, "__last_intent__", None),
        tools_called     = final_result.tools_used,
        response_time_ms = elapsed_ms,
        handoff_to       = final_result.handoff.to_agent if final_result.handoff else None,
        resolved         = bool(final_result.content and not final_result.handoff),
    )
    db.add(log)
    db.commit()

    return ChatResponse(
        session_id       = session_id,
        agent_type       = current_agent_t,
        content          = final_result.content,
        tools_used       = final_result.tools_used,
        handoff_occurred = handoff_count > 0,
        ticket_id        = final_result.ticket_id,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest, db: Session = Depends(get_db)):
    session  = get_or_create_session(db, req.session_id, req.customer_id)
    session_id = session.id

    if req.customer_id:
        update_shared_context(session_id, {"customer_id": req.customer_id}, db)

    context = get_shared_context(session_id, db)
    history = load_history(session_id, db)

    if req.target_agent:
        target = req.target_agent
    else:
        decision = route(req.message, history)
        target   = decision.agent
        update_shared_context(session_id, decision.entities, db)
        context  = get_shared_context(session_id, db)

    save_message(session_id, "user", req.message, db)
    agent = get_agent(target)

    async def event_stream():
        # Emit routing decision
        yield f"data: {json.dumps({'type': 'routing', 'agent': target.value})}\n\n"

        full_content = ""
        tools_used   = []

        async for raw in agent.stream(req.message, history, context, db, session_id):
            payload = json.loads(raw)
            if payload["type"] == "token":
                full_content += payload["content"]
            elif payload["type"] == "tool_call":
                tools_used.append(payload["name"])
            elif payload["type"] == "done":
                tools_used = payload.get("tools_used", tools_used)

            yield f"data: {raw}\n\n"

        # Persist the full assembled response
        if full_content:
            save_message(
                session_id, "assistant", full_content, db,
                agent_type=target, tools_used=tools_used,
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/history")
def get_session_history(session_id: str, db: Session = Depends(get_db)):
    from models import MASSession, MASMessage
    session = db.query(MASSession).filter(MASSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = (
        db.query(MASMessage)
        .filter(MASMessage.session_id == session_id)
        .order_by(MASMessage.created_at.asc())
        .all()
    )
    return {
        "session_id":     session_id,
        "customer_id":    session.customer_id,
        "current_agent":  session.current_agent.value,
        "total_messages": session.total_messages,
        "total_handoffs": session.total_handoffs,
        "messages": [
            {
                "role":       m.role,
                "content":    m.content,
                "agent_type": m.agent_type.value if m.agent_type else None,
                "tools_used": m.tools_used,
                "created_at": str(m.created_at),
            }
            for m in messages
        ],
    }
