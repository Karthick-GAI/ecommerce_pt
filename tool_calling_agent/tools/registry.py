"""
Tool registry.

TOOL_SCHEMAS  — OpenAI-compatible function definitions (passed in every API call).
dispatch()    — Executes a tool by name with parsed arguments.
"""
import json
from sqlalchemy.orm import Session
from tools.order_tools import lookup_order, get_customer_orders, get_order_tracking
from tools.inventory_tools import search_products, check_product_stock, get_category_summary
from tools.recommendation_tools import (
    get_recommendations, get_similar_products, get_trending_products, get_deals,
)

# ── OpenAI tool schema definitions ───────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": (
                "Look up an order by its order ID. Returns current status, items purchased, "
                "payment details, shipping address, and estimated delivery. "
                "Use this when a customer asks about a specific order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID (UUID) provided by the customer.",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_orders",
            "description": (
                "Get the recent order history for a customer. Returns a list of orders "
                "with status, total, and item count. "
                "Use this when a customer asks 'what are my orders' or 'show my order history'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer's unique user ID.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of orders to return (default 5, max 10).",
                        "default": 5,
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_tracking",
            "description": (
                "Get the full status timeline and tracking details for an order. "
                "Returns each status change with timestamps, tracking numbers, "
                "estimated delivery dates, and refund info if applicable. "
                "Use this when a customer asks 'where is my order' or 'track my order'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to track.",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search for products by name, brand, or category. "
                "Returns matching products with stock levels, prices, discounts, and ratings. "
                "Use this when a customer asks about product availability or wants to find products."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Product name, brand, or keyword to search for.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g. 'Electronics', 'Clothing').",
                    },
                    "min_price": {
                        "type": "number",
                        "description": "Minimum price in INR.",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price in INR.",
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "If true, only return products with stock > 0.",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_product_stock",
            "description": (
                "Check the current stock level and availability for a specific product by its ID. "
                "Returns stock count, health status (healthy/low/critical/out_of_stock), "
                "price, discount, and any active stock alerts. "
                "Use this when a customer asks if a specific product is available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product's unique ID (UUID).",
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_summary",
            "description": (
                "Get an inventory health overview for all products in a category. "
                "Returns counts of healthy/low/critical/out-of-stock products and open alerts. "
                "Use this for operations-level questions about category stock health."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Product category name (e.g. 'Electronics', 'Home & Kitchen').",
                    }
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recommendations",
            "description": (
                "Get personalised product recommendations for a customer based on their "
                "purchase history using collaborative filtering. "
                "Falls back to trending products for new customers. "
                "Use this when a customer asks 'what should I buy' or 'recommend something for me'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer's unique user ID.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of recommendations to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_similar_products",
            "description": (
                "Find products similar to a given product using semantic (vector) similarity. "
                "Uses pre-computed product embeddings for accurate matching. "
                "Use this when a customer asks 'show me something like this' or "
                "'what else is similar to product X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The reference product's ID (UUID).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of similar products to return (default 5).",
                        "default": 5,
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trending_products",
            "description": (
                "Get the most purchased products in the last 30 days. "
                "Optionally filter by category. "
                "Use this when a customer asks what's popular, trending, or best-selling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional: filter trending products by category.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of trending products to return (default 5).",
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_deals",
            "description": (
                "Get the best current deals: products with the highest discounts, "
                "strong ratings, and good stock. "
                "Use this when a customer asks about deals, offers, or discounts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of deals to return (default 5).",
                        "default": 5,
                    }
                },
                "required": [],
            },
        },
    },
]


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def dispatch(
    tool_name: str,
    arguments_json: str,
    db: Session,
    customer_id: str | None = None,
) -> dict:
    """
    Parse tool arguments and execute the corresponding tool function.
    Returns the result dict (will be serialised to JSON for the LLM).
    """
    try:
        args = json.loads(arguments_json)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON arguments for tool '{tool_name}'."}

    # Clamp any limit arguments to sane bounds
    if "limit" in args:
        args["limit"] = min(max(int(args["limit"]), 1), 10)

    try:
        match tool_name:
            case "lookup_order":
                return lookup_order(db, **args)
            case "get_customer_orders":
                if "customer_id" not in args and customer_id:
                    args["customer_id"] = customer_id
                return get_customer_orders(db, **args)
            case "get_order_tracking":
                return get_order_tracking(db, **args)
            case "search_products":
                return search_products(db, **args)
            case "check_product_stock":
                return check_product_stock(db, **args)
            case "get_category_summary":
                return get_category_summary(db, **args)
            case "get_recommendations":
                if "customer_id" not in args and customer_id:
                    args["customer_id"] = customer_id
                return get_recommendations(db, **args)
            case "get_similar_products":
                return get_similar_products(db, **args)
            case "get_trending_products":
                return get_trending_products(db, **args)
            case "get_deals":
                return get_deals(db, **args)
            case _:
                return {"error": f"Unknown tool: '{tool_name}'."}
    except TypeError as e:
        return {"error": f"Tool '{tool_name}' called with wrong arguments: {e}"}
    except Exception as e:
        return {"error": f"Tool '{tool_name}' execution failed: {type(e).__name__}: {e}"}
