"""
BaseReroutingAgent — autonomous LLM tool-calling loop for rerouting agents.

Key design differences from BaseAgent (the chat agent):
  • No MASSession / AgentType / human-in-the-loop
  • Runs fully autonomously — input is an AgentMessage, output is an AgentMessage
  • Tool results are collected as structured data; the coordinator uses them
    for the next step rather than trusting LLM text verbatim
  • temperature=0.1 for deterministic, reproducible decisions
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from agents.base import _async_client, _MODEL
from rerouting.bus import AgentMessage

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 6


class BaseReroutingAgent(ABC):
    """Autonomous rerouting agent driven by the RerouteCoordinator."""

    AGENT_NAME: str = "base"

    @abstractmethod
    def system_prompt(self, incoming: AgentMessage) -> str: ...

    @abstractmethod
    def tools_schema(self) -> List[Dict]: ...

    @abstractmethod
    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str: ...

    @abstractmethod
    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],   # (name, args, result_json)
    ) -> AgentMessage: ...

    async def run(self, incoming: AgentMessage, db: Session) -> AgentMessage:
        """
        Execute the tool-calling loop.

        Returns an AgentMessage whose payload is built from structured tool
        results — not from parsing LLM prose — so downstream agents always
        receive reliable, machine-readable data.
        """
        messages = [
            {"role": "system", "content": self.system_prompt(incoming)},
            {
                "role": "user",
                "content": (
                    f"Message type: {incoming.message_type}\n"
                    f"From: {incoming.from_agent}\n"
                    f"Payload:\n{json.dumps(incoming.payload, indent=2)}"
                ),
            },
        ]
        tool_schema = self.tools_schema()
        tool_calls_made: List[Tuple[str, Dict, str]] = []

        for iteration in range(_MAX_ITERATIONS):
            response = await _async_client.chat.completions.create(
                model=_MODEL,
                messages=messages,
                tools=tool_schema or None,
                tool_choice="auto" if tool_schema else "none",
                temperature=0.1,
                max_completion_tokens=1024,
            )
            choice = response.choices[0]

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                messages.append(choice.message.model_dump())

                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    logger.debug(
                        "[%s] Tool call %d: %s(%s)",
                        self.AGENT_NAME, iteration, tool_name, list(args.keys()),
                    )
                    result = self.dispatch_tool(tool_name, args, db)
                    tool_calls_made.append((tool_name, args, result))

                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      result,
                    })
            else:
                # Final response
                llm_reasoning = choice.message.content or ""
                return self.build_outgoing(incoming, llm_reasoning, tool_calls_made)

        # Safety fallback
        logger.warning("[%s] Reached max iterations without finishing.", self.AGENT_NAME)
        return AgentMessage(
            message_type="REROUTE_FAILED",
            from_agent=self.AGENT_NAME,
            to_agent="coordinator",
            payload={
                "error":      f"{self.AGENT_NAME} hit max iterations ({_MAX_ITERATIONS})",
                "tools_used": [t[0] for t in tool_calls_made],
            },
        )
