from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import ChatSession, ChatMessage
from rag import retrieve_products, build_context, generate_reply, fetch_purchase_history
from schemas import ChatRequest, ChatResponse, HistoryResponse, SourceProduct, MessageItem

router = APIRouter(prefix="/chat", tags=["Shopping Assistant"])


# ── POST /chat ────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    """
    Main conversational endpoint.

    - Omit session_id on the first message → a new session is created automatically.
    - Pass the returned session_id in every subsequent message to maintain history.

    RAG pipeline per request:
      1. Get or create session
      2. Load conversation history from DB
      3. parse_nl_query()  → structured filters
      4. embed_text()      → 1536-dim query vector
      5. semantic_search() → top-8 products (pgvector cosine + SQL filters)
      6. build_context()   → format products as GPT context
      7. generate_reply()  → GPT response grounded in retrieved products
      8. Persist both turns to DB
    """
    # ── 1. Session ─────────────────────────────────────────
    if payload.session_id:
        session = db.query(ChatSession).filter(ChatSession.id == payload.session_id).first()
        if not session:
            raise HTTPException(
                status_code=404,
                detail="Session not found. Omit session_id to start a new chat.",
            )
    else:
        session = ChatSession()
        db.add(session)
        db.commit()
        db.refresh(session)

    # ── 2. History ──────────────────────────────────────────
    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in history_rows[-20:]   # last 20 messages = 10 exchanges
    ]

    # ── 3-6. RAG pipeline (with graceful degradation) ──────
    results, parsed_filters, retrieval_mode = retrieve_products(db, payload.message, n=8)
    context = build_context(results)
    purchase_history = fetch_purchase_history(db, payload.user_id)

    if retrieval_mode == "keyword":
        # Vector indexing failed — skip GPT, format keyword results directly
        from local_fallback import format_keyword_results
        reply        = format_keyword_results([p for p, _ in results])
        used_fallback = True
    else:
        reply, used_fallback = generate_reply(
            conversation_history, context, payload.message, purchase_history
        )

    # ── 7. Persist this turn ────────────────────────────────
    source_refs = [
        {"id": p.id, "name": p.name,
         "price": round(p.price * (1 - p.discount_pct / 100), 2)}
        for p, _ in results[:5]
    ]
    db.add(ChatMessage(session_id=session.id, role="user",      content=payload.message))
    db.add(ChatMessage(session_id=session.id, role="assistant", content=reply, sources=source_refs))
    db.commit()

    # ── 8. Response ─────────────────────────────────────────
    sources = [
        SourceProduct(
            id=p.id,
            name=p.name,
            category=p.category,
            effective_price=round(p.price * (1 - p.discount_pct / 100), 2),
            in_stock=p.inventory_count > 0,
            primary_image=p.primary_image,
            rating_avg=p.rating_avg,
            rating_count=p.rating_count,
        )
        for p, _ in results[:5]
    ]

    return ChatResponse(
        session_id=session.id,
        reply=reply,
        sources=sources,
        parsed_filters=parsed_filters,
        fallback_mode=used_fallback,
    )


# ── GET /chat/{session_id}/history ────────────────────────────────────────────

@router.get("/{session_id}/history", response_model=HistoryResponse)
def get_history(session_id: str, db: Session = Depends(get_db)):
    """Retrieve the full conversation history for a session."""
    if not db.query(ChatSession).filter(ChatSession.id == session_id).first():
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    return HistoryResponse(
        session_id=session_id,
        messages=[
            MessageItem(role=m.role, content=m.content, created_at=str(m.created_at))
            for m in messages
        ],
    )


# ── DELETE /chat/{session_id} ─────────────────────────────────────────────────

@router.delete("/{session_id}")
def clear_session(session_id: str, db: Session = Depends(get_db)):
    """Delete a session and all its messages (cascade)."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session)
    db.commit()
    return {"message": "Session cleared", "session_id": session_id}


# ── GET /chat/sessions/list ───────────────────────────────────────────────────

@router.get("/sessions/list")
def list_sessions(db: Session = Depends(get_db)):
    """List the 50 most recent chat sessions."""
    sessions = (
        db.query(ChatSession)
        .order_by(ChatSession.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "total": len(sessions),
        "sessions": [
            {
                "session_id": s.id,
                "created_at": str(s.created_at),
                "message_count": len(s.messages),
            }
            for s in sessions
        ],
    }
