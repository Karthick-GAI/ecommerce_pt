"""
Orchestrator: intent classification and agent routing.

Uses GPT to classify the user message into one of four specialist domains,
returning a RoutingDecision with the target agent, confidence, and extracted entities.
"""
import os
import json
import logging
from typing import List, Dict, Optional
from openai import AzureOpenAI
from dotenv import load_dotenv
from schemas import RoutingDecision
from models import AgentType

load_dotenv()
logger = logging.getLogger(__name__)

_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
)
_MODEL = os.getenv("AZURE_OPENAI_GPT54_MINI_DEPLOYMENT", "gpt-5.4-mini")
_AZURE_TIMEOUT_SECS = float(os.getenv("AZURE_TIMEOUT_SECS", "5.0"))

_ROUTING_SYSTEM_PROMPT = """You are the orchestrator for an AI-powered e-commerce multi-agent system.
Classify the user message into exactly one of these agent domains:

- customer_support: Order problems, delivery issues, complaints, returns, refunds, damaged items,
  wrong items, account help, password reset, billing disputes, product defects, FAQs.

- recommendation: Product discovery, "what should I buy", browsing, comparisons, deals,
  gift ideas, category exploration, "show me X", "best Y under Z price".

- fulfillment: Completing a purchase, checkout process, payment flow, applying coupons,
  shipment tracking, checking cart totals, return initiation, delivery estimate for a pincode.

- inventory_planning: Stock levels, restock planning, demand forecasting, purchase orders,
  low-stock alerts, sales velocity analysis. This is for OPERATIONS TEAM queries only.

Return a JSON object with exactly these fields:
{
  "agent": "<one of: customer_support | recommendation | fulfillment | inventory_planning>",
  "confidence": <float 0.0-1.0>,
  "intent": "<one-sentence description of what the user wants>",
  "entities": {
    "order_id": "<if mentioned>",
    "product_id": "<if mentioned>",
    "customer_id": "<if mentioned>",
    "category": "<if mentioned>",
    "price_max": <number if mentioned>,
    "pincode": "<if mentioned>"
  }
}

Only include entity keys that are explicitly present in the message.
"""

_FALLBACK: RoutingDecision = RoutingDecision(
    agent=AgentType.customer_support,
    confidence=0.4,
    intent="General enquiry",
    entities={},
)


def route(message: str, history: Optional[List[Dict]] = None) -> RoutingDecision:
    messages = [{"role": "system", "content": _ROUTING_SYSTEM_PROMPT}]

    # Include up to last 4 history turns for context
    if history:
        for turn in history[-4:]:
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": message})

    try:
        response = _client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=256,
            timeout=_AZURE_TIMEOUT_SECS,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        agent_str = data.get("agent", "customer_support")
        # Validate agent value
        valid_agents = {a.value for a in AgentType} - {"orchestrator"}
        if agent_str not in valid_agents:
            agent_str = "customer_support"

        return RoutingDecision(
            agent=AgentType(agent_str),
            confidence=float(data.get("confidence", 0.7)),
            intent=data.get("intent", ""),
            entities={k: v for k, v in data.get("entities", {}).items() if v},
        )

    except Exception as e:
        logger.warning("Routing failed (%s), using fallback.", e)
        return _FALLBACK
