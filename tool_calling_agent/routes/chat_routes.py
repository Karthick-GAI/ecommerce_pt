import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from schemas import ChatRequest, ChatResponse
from agent.loop import run_agent, run_agent_stream

router = APIRouter(prefix="/agent", tags=["Agent Chat"])


# ── POST /agent/chat — synchronous ────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    """
    Send a message to the agent and receive a complete response.
    Pass session_id to continue an existing conversation; omit to start a new one.
    Pass customer_id to personalise responses with customer context.
    """
    result = run_agent(
        message     = payload.message,
        customer_id = payload.customer_id,
        session_id  = payload.session_id,
        db          = db,
    )
    from models import AgentMessage
    turn_count = db.query(AgentMessage).filter(
        AgentMessage.session_id == result["session_id"],
        AgentMessage.role == "user",
    ).count()

    return ChatResponse(
        session_id = result["session_id"],
        response   = result["response"],
        tools_used = result["tools_used"],
        turn_count = turn_count,
    )


# ── POST /agent/chat/stream — SSE streaming ───────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    """
    Send a message and receive a streaming response via Server-Sent Events.

    SSE event types emitted:
      data: {"type": "tool_call", "tool": "<name>"}   — tool being executed
      data: {"type": "token",     "content": "<text>"} — response token
      data: {"type": "done",  "tools_used": [...], "session_id": "..."}

    Connect with:
      curl -N -X POST http://localhost:8007/agent/chat/stream \\
        -H 'Content-Type: application/json' \\
        -d '{"message": "What are trending products?"}'
    """
    async def generate():
        async for event in run_agent_stream(
            message     = payload.message,
            customer_id = payload.customer_id,
            session_id  = payload.session_id,
            db          = db,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )
