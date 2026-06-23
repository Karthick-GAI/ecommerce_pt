"""
InventoryAgent — finds in-stock substitutes for every blocked line item.

Receives STOCKOUT_DETECTED (payload.stockout_items list), calls
find_alternative_products once per blocked item, cross-checks the best
candidate with check_warehouse_stock, then emits ALTERNATIVES_READY with
a recommended_substitutes list that the LogisticsAgent can plan around.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from rerouting.base import BaseReroutingAgent
from rerouting.bus import AgentMessage
from tools.rerouting_tools import find_alternative_products, check_warehouse_stock

_TOOLS = [
    {"type": "function", "function": {
        "name": "find_alternative_products",
        "description": (
            "Find in-stock substitute products for an out-of-stock item. "
            "Returns up to 5 alternatives sorted by rating and stock depth."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_id":            {"type": "string"},
                "category":              {"type": "string"},
                "max_price_premium_pct": {"type": "number", "default": 20.0},
                "required_qty":          {"type": "integer", "default": 1},
            },
            "required": ["product_id"],
        },
    }},
    {"type": "function", "function": {
        "name": "check_warehouse_stock",
        "description": (
            "Verify the current stock depth and fulfilment readiness of a candidate "
            "substitute product before recommending it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
            },
            "required": ["product_id"],
        },
    }},
]


class InventoryAgent(BaseReroutingAgent):
    AGENT_NAME = "inventory"

    def system_prompt(self, incoming: AgentMessage) -> str:
        stockout_items = incoming.payload.get("stockout_items", [])
        item_summary = "\n".join(
            f"  - {s['product_name']} (id: {s['product_id']}, "
            f"need: {s['requested_qty']}, have: {s['available_stock']}, "
            f"category: {s['category']})"
            for s in stockout_items
        )
        return f"""You are the InventoryAgent resolving a stockout situation.

Out-of-stock items to resolve:
{item_summary or "  (see payload.stockout_items)"}

Your procedure for EACH stockout item:
1. Call find_alternative_products with product_id and required_qty.
2. From the returned alternatives, pick the best one:
   - Prefer is_recommended=true
   - Prefer stock_count >= required_qty * 2 (buffer)
   - Prefer smallest absolute price_diff_pct
3. For your chosen substitute, call check_warehouse_stock to confirm availability.
4. After processing all items, output a JSON block exactly like this:

```json
{{
  "recommended_substitutes": [
    {{
      "original_product_id": "...",
      "substitute_product_id": "...",
      "substitute_name": "...",
      "price_diff_pct": 0.0,
      "stock_count": 0
    }}
  ],
  "unresolvable_items": [],
  "can_reroute": true
}}
```

If NO alternative exists for an item, add its product_id to unresolvable_items and set can_reroute=false.
"""

    def tools_schema(self) -> List[Dict]:
        return _TOOLS

    def dispatch_tool(self, tool_name: str, args: Dict[str, Any], db: Session) -> str:
        if tool_name == "find_alternative_products":
            return find_alternative_products(
                product_id=args["product_id"],
                db=db,
                category=args.get("category"),
                max_price_premium_pct=args.get("max_price_premium_pct", 20.0),
                required_qty=args.get("required_qty", 1),
            )
        if tool_name == "check_warehouse_stock":
            return check_warehouse_stock(args["product_id"], db)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def build_outgoing(
        self,
        incoming: AgentMessage,
        llm_reasoning: str,
        tool_calls_made: List[Tuple[str, Dict, str]],
    ) -> AgentMessage:
        """
        Extract the recommended_substitutes from the LLM's JSON block.
        Fall back to direct tool-result extraction if JSON parsing fails.
        """
        # Try to parse the JSON block from the LLM response
        substitutes_payload = _extract_json_block(llm_reasoning)

        # Fallback: build from tool results if JSON parse failed
        if not substitutes_payload:
            substitutes_payload = _build_from_tool_results(
                incoming.payload.get("stockout_items", []),
                tool_calls_made,
            )

        return AgentMessage(
            message_type="ALTERNATIVES_READY",
            from_agent="inventory",
            to_agent="logistics",
            payload={
                "order_id":        incoming.payload.get("order_id"),
                "shipping_pincode": incoming.payload.get("shipping_pincode"),
                "stockout_items":  incoming.payload.get("stockout_items", []),
                "tools_used":      [t[0] for t in tool_calls_made],
                **substitutes_payload,
            },
        )


def _extract_json_block(text: str) -> dict:
    """Pull the first JSON object out of the LLM's text response."""
    import re
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*\"can_reroute\".*?\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _build_from_tool_results(
    stockout_items: list,
    tool_calls_made: List[Tuple[str, Dict, str]],
) -> dict:
    """
    Deterministic fallback: extract the best alternative per stockout item
    directly from tool results without relying on LLM text parsing.
    """
    # Build: product_id → list of alternatives (from find_alternative_products calls)
    alt_map: Dict[str, list] = {}
    for name, args, result_json in tool_calls_made:
        if name == "find_alternative_products":
            try:
                data = json.loads(result_json)
                pid = data.get("original_product_id") or args.get("product_id", "")
                alts = data.get("alternatives", [])
                if pid:
                    alt_map[pid] = alts
            except json.JSONDecodeError:
                pass

    recommended: list = []
    unresolvable: list = []

    for item in stockout_items:
        orig_pid = item["product_id"]
        alts = alt_map.get(orig_pid, [])

        # Pick best: is_recommended first, then highest stock
        best = next(
            (a for a in alts if a.get("is_recommended")),
            max(alts, key=lambda a: a.get("stock_count", 0)) if alts else None,
        )
        if best:
            recommended.append({
                "original_product_id":   orig_pid,
                "substitute_product_id": best["product_id"],
                "substitute_name":       best["name"],
                "price_diff_pct":        best.get("price_diff_pct", 0.0),
                "stock_count":           best.get("stock_count", 0),
            })
        else:
            unresolvable.append(orig_pid)

    return {
        "recommended_substitutes": recommended,
        "unresolvable_items":      unresolvable,
        "can_reroute":             len(recommended) > 0 and len(unresolvable) == 0,
    }
