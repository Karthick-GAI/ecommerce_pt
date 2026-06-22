"""
BaseAgent: shared tool-calling loop used by all specialist agents.

Subclasses provide:
  - AGENT_TYPE  : AgentType enum value
  - system_prompt() : str
  (tools are pulled from registry.AGENT_TOOLS[AGENT_TYPE.value])
"""
import os
import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Optional, Any
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from models import AgentType
from schemas import AgentResult, HandoffRequest
from tools.registry import AGENT_TOOLS, dispatch

load_dotenv()
logger = logging.getLogger(__name__)

_async_client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
)
_MODEL        = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")
_MAX_TOOL_ITERATIONS = 8   # prevent infinite loops


class BaseAgent(ABC):
    AGENT_TYPE: AgentType

    @abstractmethod
    def system_prompt(self, context: Dict[str, Any]) -> str: ...

    def _tools(self) -> List[Dict]:
        return AGENT_TOOLS.get(self.AGENT_TYPE.value, [])

    def _build_messages(
        self,
        user_message: str,
        history: List[Dict],
        context: Dict[str, Any],
    ) -> List[Dict]:
        messages = [{"role": "system", "content": self.system_prompt(context)}]
        messages.extend(history[-12:])  # last 12 turns for context window efficiency
        messages.append({"role": "user", "content": user_message})
        return messages

    async def run(
        self,
        user_message: str,
        history: List[Dict],
        context: Dict[str, Any],
        db: Session,
        session_id: str = None,
    ) -> AgentResult:
        messages    = self._build_messages(user_message, history, context)
        tools       = self._tools()
        tools_used  = []
        ticket_id   = None
        handoff     = None

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = await _async_client.chat.completions.create(
                model=_MODEL,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else "none",
                temperature=0.3,
                max_tokens=1024,
            )
            choice = response.choices[0]

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                # Append assistant message with tool call intent
                messages.append(choice.message.model_dump())

                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    tools_used.append(tool_name)
                    result = dispatch(tool_name, tc.function.arguments, db, session_id)

                    # Track ticket IDs created by support tools
                    if tool_name == "create_support_ticket":
                        try:
                            ticket_id = json.loads(result).get("ticket_id")
                        except Exception:
                            pass

                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      result,
                    })
            else:
                # Final response
                content = choice.message.content or ""

                # Detect handoff signal embedded in response (JSON block)
                handoff = _extract_handoff(content)
                if handoff:
                    # Strip the JSON block from visible response
                    content = content[:content.rfind("```")].strip() if "```" in content else content

                return AgentResult(
                    content    = content,
                    agent_type = self.AGENT_TYPE,
                    tools_used = list(dict.fromkeys(tools_used)),  # deduplicated
                    handoff    = handoff,
                    ticket_id  = ticket_id,
                )

        # Safety fallback after max iterations
        return AgentResult(
            content    = "I've gathered the information needed. Please let me know if you need anything else.",
            agent_type = self.AGENT_TYPE,
            tools_used = tools_used,
        )

    async def stream(
        self,
        user_message: str,
        history: List[Dict],
        context: Dict[str, Any],
        db: Session,
        session_id: str = None,
    ) -> AsyncGenerator[str, None]:
        messages   = self._build_messages(user_message, history, context)
        tools      = self._tools()
        tools_used = []

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = await _async_client.chat.completions.create(
                model=_MODEL,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else "none",
                temperature=0.3,
                max_tokens=1024,
                stream=True,
            )

            tool_calls_buffer: Dict[int, Dict] = {}
            full_content = ""
            finish_reason = None

            async for chunk in response:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                finish_reason = choice.finish_reason

                if choice.delta.content:
                    full_content += choice.delta.content
                    yield json.dumps({"type": "token", "content": choice.delta.content})

                if choice.delta.tool_calls:
                    for tc in choice.delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buffer:
                            tool_calls_buffer[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_buffer[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_buffer[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_buffer[idx]["arguments"] += tc.function.arguments

            if finish_reason == "tool_calls" and tool_calls_buffer:
                # Reconstruct assistant message
                assistant_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in tool_calls_buffer.values()
                    ],
                }
                messages.append(assistant_msg)

                for tc in tool_calls_buffer.values():
                    tools_used.append(tc["name"])
                    yield json.dumps({"type": "tool_call", "name": tc["name"]})
                    result = dispatch(tc["name"], tc["arguments"], db, session_id)
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            else:
                break

        yield json.dumps({
            "type":       "done",
            "agent":      self.AGENT_TYPE.value,
            "tools_used": list(dict.fromkeys(tools_used)),
            "session_id": session_id,
        })


def _extract_handoff(content: str) -> Optional[HandoffRequest]:
    """Check if agent embedded a handoff JSON block in its response."""
    try:
        if "HANDOFF:" in content:
            start = content.index("HANDOFF:") + 8
            raw   = content[start:].strip()
            if raw.startswith("{"):
                end   = raw.index("}") + 1
                data  = json.loads(raw[:end])
                return HandoffRequest(
                    to_agent       = AgentType(data["to_agent"]),
                    reason         = data.get("reason", ""),
                    context_update = data.get("context_update", {}),
                )
    except Exception:
        pass
    return None
