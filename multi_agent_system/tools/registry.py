"""
Central tool registry.

AGENT_TOOLS   — per-agent OpenAI-compatible function schemas
dispatch()    — executes a named tool with parsed arguments
"""
import json
from sqlalchemy.orm import Session

from tools.order_tools import (
    lookup_order, get_customer_orders, get_order_timeline,
    check_refund_eligibility, get_refund_status,
)
from tools.support_tools import (
    create_support_ticket, get_customer_tickets, escalate_ticket,
    resolve_ticket, get_faq_answers,
)
from tools.product_tools import (
    search_products, get_product_detail, get_similar_products,
    compare_products, get_products_by_category,
)
from tools.recommendation_tools import (
    get_personalized_recommendations, get_trending_products,
    get_best_deals, get_customer_preferences,
)
from tools.fulfillment_tools import (
    get_cart_summary, check_product_availability, calculate_order_estimate,
    get_payment_status, track_active_shipment, check_return_eligibility,
    get_delivery_estimate,
)
from tools.inventory_tools import (
    get_inventory_dashboard, get_low_stock_products, get_stock_movements,
    forecast_demand, get_restock_recommendations, get_sales_velocity,
    get_open_inventory_alerts, acknowledge_alert,
)

# ── Tool Schemas ───────────────────────────────────────────────────────────────

_SUPPORT_TOOLS = [
    {"type": "function", "function": {
        "name": "lookup_order",
        "description": "Look up an order by ID. Returns status, items, payment, and shipping details.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "The order ID (UUID)."},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_customer_orders",
        "description": "Get recent order history for a customer.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string"},
            "limit":       {"type": "integer", "default": 5},
        }, "required": ["customer_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_order_timeline",
        "description": "Get the full status timeline and tracking info for an order.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "check_refund_eligibility",
        "description": "Check if an order is eligible for a refund.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_refund_status",
        "description": "Get the current status of a refund for an order.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "create_support_ticket",
        "description": "Create a support ticket for a customer issue.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string"},
            "issue_type":  {"type": "string", "enum": ["order_issue", "payment", "return", "account", "product", "other"]},
            "description": {"type": "string"},
            "order_id":    {"type": "string"},
            "product_id":  {"type": "string"},
            "priority":    {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        }, "required": ["customer_id", "issue_type", "description"]},
    }},
    {"type": "function", "function": {
        "name": "get_customer_tickets",
        "description": "Get open support tickets for a customer.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string"},
        }, "required": ["customer_id"]},
    }},
    {"type": "function", "function": {
        "name": "escalate_ticket",
        "description": "Escalate a support ticket to senior support.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"},
            "reason":    {"type": "string"},
        }, "required": ["ticket_id", "reason"]},
    }},
    {"type": "function", "function": {
        "name": "get_faq_answers",
        "description": "Search the knowledge base for answers to common customer questions.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
        }, "required": ["query"]},
    }},
]

_RECOMMENDATION_TOOLS = [
    {"type": "function", "function": {
        "name": "search_products",
        "description": "Semantic + keyword product search. Use for 'find X', 'show me Y', 'I need Z'.",
        "parameters": {"type": "object", "properties": {
            "query":         {"type": "string"},
            "category":      {"type": "string"},
            "brand":         {"type": "string"},
            "min_price":     {"type": "number"},
            "max_price":     {"type": "number"},
            "in_stock_only": {"type": "boolean"},
            "limit":         {"type": "integer", "default": 8},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "get_product_detail",
        "description": "Get full details for a specific product including specs and stock.",
        "parameters": {"type": "object", "properties": {
            "product_id": {"type": "string"},
        }, "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_similar_products",
        "description": "Find products similar to a given product using vector similarity.",
        "parameters": {"type": "object", "properties": {
            "product_id": {"type": "string"},
            "limit":      {"type": "integer", "default": 6},
        }, "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "compare_products",
        "description": "Compare 2-4 products side-by-side on specs, price, and ratings.",
        "parameters": {"type": "object", "properties": {
            "product_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["product_ids"]},
    }},
    {"type": "function", "function": {
        "name": "get_personalized_recommendations",
        "description": "Get personalised product recommendations based on customer purchase/browse history.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string"},
            "limit":       {"type": "integer", "default": 10},
        }, "required": ["customer_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_trending_products",
        "description": "Get the most purchased products in the last 30 days.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string"},
            "limit":    {"type": "integer", "default": 10},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_best_deals",
        "description": "Get products with the highest discount percentages.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "default": 10},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_customer_preferences",
        "description": "Get a customer's inferred preferences: categories, brands, price range, lifecycle stage.",
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string"},
        }, "required": ["customer_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_products_by_category",
        "description": "Browse all products in a given category or subcategory.",
        "parameters": {"type": "object", "properties": {
            "category":    {"type": "string"},
            "subcategory": {"type": "string"},
            "limit":       {"type": "integer", "default": 12},
        }, "required": ["category"]},
    }},
]

_FULFILLMENT_TOOLS = [
    {"type": "function", "function": {
        "name": "get_cart_summary",
        "description": "Get cart contents and price breakdown (subtotal, GST, shipping, total).",
        "parameters": {"type": "object", "properties": {
            "cart_id": {"type": "string"},
        }, "required": ["cart_id"]},
    }},
    {"type": "function", "function": {
        "name": "check_product_availability",
        "description": "Check if a product has sufficient stock for a requested quantity.",
        "parameters": {"type": "object", "properties": {
            "product_id": {"type": "string"},
            "quantity":   {"type": "integer"},
        }, "required": ["product_id", "quantity"]},
    }},
    {"type": "function", "function": {
        "name": "calculate_order_estimate",
        "description": "Calculate estimated order total including GST, shipping, and optional coupon discount.",
        "parameters": {"type": "object", "properties": {
            "cart_id":     {"type": "string"},
            "pincode":     {"type": "string"},
            "coupon_code": {"type": "string"},
        }, "required": ["cart_id", "pincode"]},
    }},
    {"type": "function", "function": {
        "name": "get_payment_status",
        "description": "Get payment status and transaction details for an order.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "track_active_shipment",
        "description": "Track shipment and delivery status for an order.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "check_return_eligibility",
        "description": "Check if an order can be returned under the return policy.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string"},
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_delivery_estimate",
        "description": "Estimate delivery timeline and shipping cost for a pincode.",
        "parameters": {"type": "object", "properties": {
            "pincode": {"type": "string"},
        }, "required": ["pincode"]},
    }},
]

_INVENTORY_TOOLS = [
    {"type": "function", "function": {
        "name": "get_inventory_dashboard",
        "description": "Overall inventory health: out-of-stock, critical, low, healthy counts by category.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "get_low_stock_products",
        "description": "List products with low or critical stock levels.",
        "parameters": {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["out_of_stock", "critical", "low"]},
            "limit":    {"type": "integer", "default": 20},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_stock_movements",
        "description": "Get stock movement audit trail for a product (restocks, sales, adjustments).",
        "parameters": {"type": "object", "properties": {
            "product_id": {"type": "string"},
            "days":       {"type": "integer", "default": 30},
        }, "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "forecast_demand",
        "description": "Forecast demand for a product using historical sales data. Returns reorder point and recommended restock quantity.",
        "parameters": {"type": "object", "properties": {
            "product_id":    {"type": "string"},
            "horizon_days":  {"type": "integer", "default": 30},
        }, "required": ["product_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_restock_recommendations",
        "description": "Get a prioritised list of products that need restocking, with recommended quantities.",
        "parameters": {"type": "object", "properties": {
            "top_n": {"type": "integer", "default": 20},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_sales_velocity",
        "description": "Get sales velocity (units per day) for a product or category over a time period.",
        "parameters": {"type": "object", "properties": {
            "product_id": {"type": "string"},
            "category":   {"type": "string"},
            "days":       {"type": "integer", "default": 30},
        }},
    }},
    {"type": "function", "function": {
        "name": "get_open_inventory_alerts",
        "description": "List all open inventory alerts (low stock, out of stock, etc.).",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "acknowledge_alert",
        "description": "Acknowledge an inventory alert to mark it as seen.",
        "parameters": {"type": "object", "properties": {
            "alert_id": {"type": "string"},
        }, "required": ["alert_id"]},
    }},
]

AGENT_TOOLS = {
    "customer_support":   _SUPPORT_TOOLS,
    "recommendation":     _RECOMMENDATION_TOOLS,
    "fulfillment":        _FULFILLMENT_TOOLS,
    "inventory_planning": _INVENTORY_TOOLS,
}


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def dispatch(tool_name: str, arguments: str, db: Session, session_id: str = None) -> str:
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        args = {}

    # ── Order tools ──
    if tool_name == "lookup_order":
        return lookup_order(args["order_id"], db)
    if tool_name == "get_customer_orders":
        return get_customer_orders(args["customer_id"], db, args.get("limit", 5))
    if tool_name == "get_order_timeline":
        return get_order_timeline(args["order_id"], db)
    if tool_name == "check_refund_eligibility":
        return check_refund_eligibility(args["order_id"], db)
    if tool_name == "get_refund_status":
        return get_refund_status(args["order_id"], db)

    # ── Support tools ──
    if tool_name == "create_support_ticket":
        return create_support_ticket(
            customer_id=args["customer_id"],
            issue_type=args["issue_type"],
            description=args["description"],
            db=db,
            session_id=session_id,
            order_id=args.get("order_id"),
            product_id=args.get("product_id"),
            priority=args.get("priority"),
        )
    if tool_name == "get_customer_tickets":
        return get_customer_tickets(args["customer_id"], db)
    if tool_name == "escalate_ticket":
        return escalate_ticket(args["ticket_id"], args["reason"], db)
    if tool_name == "resolve_ticket":
        return resolve_ticket(args["ticket_id"], args["resolution"], db)
    if tool_name == "get_faq_answers":
        return get_faq_answers(args["query"])

    # ── Product tools ──
    if tool_name == "search_products":
        return search_products(
            query=args["query"], db=db,
            category=args.get("category"), brand=args.get("brand"),
            min_price=args.get("min_price"), max_price=args.get("max_price"),
            in_stock_only=args.get("in_stock_only", False),
            limit=args.get("limit", 8),
        )
    if tool_name == "get_product_detail":
        return get_product_detail(args["product_id"], db)
    if tool_name == "get_similar_products":
        return get_similar_products(args["product_id"], db, args.get("limit", 6))
    if tool_name == "compare_products":
        return compare_products(args["product_ids"], db)
    if tool_name == "get_products_by_category":
        return get_products_by_category(
            args["category"], db,
            subcategory=args.get("subcategory"),
            limit=args.get("limit", 12),
        )

    # ── Recommendation tools ──
    if tool_name == "get_personalized_recommendations":
        return get_personalized_recommendations(args["customer_id"], db, args.get("limit", 10))
    if tool_name == "get_trending_products":
        return get_trending_products(db, category=args.get("category"), limit=args.get("limit", 10))
    if tool_name == "get_best_deals":
        return get_best_deals(db, limit=args.get("limit", 10))
    if tool_name == "get_customer_preferences":
        return get_customer_preferences(args["customer_id"], db)

    # ── Fulfillment tools ──
    if tool_name == "get_cart_summary":
        return get_cart_summary(args["cart_id"], db)
    if tool_name == "check_product_availability":
        return check_product_availability(args["product_id"], args["quantity"], db)
    if tool_name == "calculate_order_estimate":
        return calculate_order_estimate(
            args["cart_id"], args["pincode"], db,
            coupon_code=args.get("coupon_code"),
        )
    if tool_name == "get_payment_status":
        return get_payment_status(args["order_id"], db)
    if tool_name == "track_active_shipment":
        return track_active_shipment(args["order_id"], db)
    if tool_name == "check_return_eligibility":
        return check_return_eligibility(args["order_id"], db)
    if tool_name == "get_delivery_estimate":
        return get_delivery_estimate(args["pincode"], db)

    # ── Inventory tools ──
    if tool_name == "get_inventory_dashboard":
        return get_inventory_dashboard(db)
    if tool_name == "get_low_stock_products":
        return get_low_stock_products(db, severity=args.get("severity"), limit=args.get("limit", 20))
    if tool_name == "get_stock_movements":
        return get_stock_movements(args["product_id"], db, days=args.get("days", 30))
    if tool_name == "forecast_demand":
        return forecast_demand(args["product_id"], db, horizon_days=args.get("horizon_days", 30))
    if tool_name == "get_restock_recommendations":
        return get_restock_recommendations(db, top_n=args.get("top_n", 20))
    if tool_name == "get_sales_velocity":
        return get_sales_velocity(
            db,
            product_id=args.get("product_id"),
            category=args.get("category"),
            days=args.get("days", 30),
        )
    if tool_name == "get_open_inventory_alerts":
        return get_open_inventory_alerts(db)
    if tool_name == "acknowledge_alert":
        return acknowledge_alert(args["alert_id"], db)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})
