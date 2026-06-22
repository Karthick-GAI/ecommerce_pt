"""
Agent loop.

run_agent()        — synchronous tool-calling loop, returns complete response.
run_agent_stream() — async generator that streams the final answer token-by-token.

Flow per turn:
  1. Build message history from DB (system + prior turns).
  2. Call Azure OpenAI with TOOL_SCHEMAS.
  3. If the model calls tools → execute them via registry.dispatch(), append
     results, loop back to step 2.
  4. If finish_reason == "stop" → save assistant reply to DB, return/stream it.
  5. Safety cap: max MAX_TOOL_ROUNDS iterations before giving a graceful error.
"""
import json
import os
from openai import AzureOpenAI, AsyncAzureOpenAI
from sqlalchemy.orm import Session
from models import AgentSession, AgentMessage, Customer
from tools.registry import TOOL_SCHEMAS, dispatch

MAX_TOOL_ROUNDS = 6

# ── Azure OpenAI clients ──────────────────────────────────────────────────────

def _sync_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key        = os.environ["AZURE_OPENAI_API_KEY"],
        api_version    = os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"],
    )


def _async_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        api_key        = os.environ["AZURE_OPENAI_API_KEY"],
        api_version    = os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"],
    )


def _deployment() -> str:
    return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")


# ── System prompt ─────────────────────────────────────────────────────────────

def _system_prompt(customer_id: str | None, db: Session) -> str:
    base = (
        "You are a helpful e-commerce assistant. You help customers with:\n"
        "- Order status, tracking, and refunds\n"
        "- Product availability and inventory checks\n"
        "- Personalised product recommendations\n"
        "- Finding similar products and current deals\n\n"
        "Guidelines:\n"
        "- Always use the available tools to fetch real data before answering.\n"
        "- Be concise and specific — include order IDs, prices, stock counts.\n"
        "- For product recommendations, mention the product name, price, and why it's recommended.\n"
        "- If a tool returns no results, say so clearly and suggest alternatives.\n"
        "- Currency is INR (₹). Format prices as ₹X,XXX.\n"
        "- Never make up information — only state what the tools return.\n"
    )

    if not customer_id:
        return base

    customer = db.query(Customer).filter(Customer.user_id == customer_id).first()
    if customer:
        base += (
            f"\nCustomer context:\n"
            f"  Name:     {customer.first_name} {customer.last_name}\n"
            f"  Location: {customer.city}, {customer.state}\n"
            f"  Segment:  {customer.segment}\n"
            f"  ID:       {customer_id}\n"
            f"\nAddress the customer by their first name ({customer.first_name}) "
            f"when appropriate.\n"
        )
    return base


# ── Session & history helpers ─────────────────────────────────────────────────

def get_or_create_session(
    db: Session,
    session_id: str | None,
    customer_id: str | None,
    first_message: str,
) -> AgentSession:
    if session_id:
        session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
        if session:
            return session

    title = (first_message[:60] + "…") if len(first_message) > 60 else first_message
    session = AgentSession(customer_id=customer_id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _load_history(session_id: str, db: Session) -> list[dict]:
    """Reconstruct the OpenAI message list from stored AgentMessages."""
    rows = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at)
        .all()
    )
    messages = []
    for r in rows:
        if r.role == "user":
            messages.append({"role": "user", "content": r.content})
        elif r.role == "assistant":
            m: dict = {"role": "assistant", "content": r.content}
            if r.tool_calls:
                m["tool_calls"] = r.tool_calls
            messages.append(m)
        elif r.role == "tool":
            messages.append({
                "role":         "tool",
                "tool_call_id": r.tool_call_id,
                "name":         r.tool_name,
                "content":      r.content,
            })
    return messages


def _save_user_message(session_id: str, content: str, db: Session):
    db.add(AgentMessage(session_id=session_id, role="user", content=content))
    db.commit()


def _save_assistant_message(
    session_id: str,
    content: str | None,
    tool_calls: list | None,
    db: Session,
):
    db.add(AgentMessage(
        session_id = session_id,
        role       = "assistant",
        content    = content,
        tool_calls = tool_calls,
    ))
    db.commit()


def _save_tool_result(
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    result: dict,
    db: Session,
):
    db.add(AgentMessage(
        session_id   = session_id,
        role         = "tool",
        content      = json.dumps(result),
        tool_call_id = tool_call_id,
        tool_name    = tool_name,
    ))
    db.commit()


# ── Synchronous agent loop ────────────────────────────────────────────────────

def run_agent(
    message: str,
    customer_id: str | None,
    session_id: str | None,
    db: Session,
) -> dict:
    """
    Run the tool-calling loop synchronously.
    Returns {"response": str, "tools_used": list[str], "session_id": str}.
    """
    client   = _sync_client()
    model    = _deployment()
    session  = get_or_create_session(db, session_id, customer_id, message)
    sys_msg  = _system_prompt(customer_id, db)

    _save_user_message(session.id, message, db)

    messages = [{"role": "system", "content": sys_msg}] + _load_history(session.id, db)
    tools_used: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model       = model,
            messages    = messages,
            tools       = TOOL_SCHEMAS,
            tool_choice = "auto",
        )
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            tc_list = choice.message.tool_calls
            # Serialisable form for DB storage
            tc_json = [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tc_list
            ]
            _save_assistant_message(session.id, choice.message.content, tc_json, db)

            # Append to in-memory messages for next round
            messages.append({
                "role":       "assistant",
                "content":    choice.message.content,
                "tool_calls": tc_json,
            })

            # Execute each tool call
            for tc in tc_list:
                name   = tc.function.name
                result = dispatch(name, tc.function.arguments, db, customer_id)
                tools_used.append(name)

                _save_tool_result(session.id, tc.id, name, result, db)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         name,
                    "content":      json.dumps(result),
                })

        else:
            # finish_reason == "stop" — final answer
            final = choice.message.content or ""
            _save_assistant_message(session.id, final, None, db)
            return {
                "response":   final,
                "tools_used": list(dict.fromkeys(tools_used)),  # deduplicated, ordered
                "session_id": session.id,
            }

    # Safety cap reached
    fallback = "I'm sorry, I wasn't able to complete your request. Please try rephrasing."
    _save_assistant_message(session.id, fallback, None, db)
    return {
        "response":   fallback,
        "tools_used": list(dict.fromkeys(tools_used)),
        "session_id": session.id,
    }


# ── Async streaming agent loop ────────────────────────────────────────────────

async def run_agent_stream(
    message: str,
    customer_id: str | None,
    session_id: str | None,
    db: Session,
):
    """
    Async generator for streaming the final assistant response.

    Tool-calling rounds are executed synchronously (non-streamed) because
    we need the complete tool call specification before executing.
    Only the final response is streamed token-by-token.

    Yields dicts: {"type": "token", "content": str}
                  {"type": "done",  "tools_used": list, "session_id": str}
                  {"type": "error", "message": str}
    """
    client   = _async_client()
    model    = _deployment()
    session  = get_or_create_session(db, session_id, customer_id, message)
    sys_msg  = _system_prompt(customer_id, db)

    _save_user_message(session.id, message, db)

    messages   = [{"role": "system", "content": sys_msg}] + _load_history(session.id, db)
    tools_used: list[str] = []

    # ── Tool-calling rounds (non-streamed) ────────────────────────────────
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.chat.completions.create(
            model       = model,
            messages    = messages,
            tools       = TOOL_SCHEMAS,
            tool_choice = "auto",
        )
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            tc_list = choice.message.tool_calls
            tc_json = [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name,
                                 "arguments": tc.function.arguments},
                }
                for tc in tc_list
            ]
            _save_assistant_message(session.id, choice.message.content, tc_json, db)
            messages.append({
                "role":       "assistant",
                "content":    choice.message.content,
                "tool_calls": tc_json,
            })

            for tc in tc_list:
                name   = tc.function.name
                result = dispatch(name, tc.function.arguments, db, customer_id)
                tools_used.append(name)
                yield {"type": "tool_call", "tool": name}

                _save_tool_result(session.id, tc.id, name, result, db)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         name,
                    "content":      json.dumps(result),
                })

        else:
            # ── Stream final answer ───────────────────────────────────────
            stream = await client.chat.completions.create(
                model    = model,
                messages = messages,
                stream   = True,
            )
            full_response = ""
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    full_response += delta.content
                    yield {"type": "token", "content": delta.content}

            _save_assistant_message(session.id, full_response, None, db)
            yield {
                "type":       "done",
                "tools_used": list(dict.fromkeys(tools_used)),
                "session_id": session.id,
            }
            return

    # Safety cap
    fallback = "I'm sorry, I wasn't able to complete your request. Please try rephrasing."
    _save_assistant_message(session.id, fallback, None, db)
    yield {"type": "token",  "content": fallback}
    yield {"type": "done",   "tools_used": list(dict.fromkeys(tools_used)),
           "session_id": session.id}
