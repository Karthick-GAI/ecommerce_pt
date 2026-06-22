"""Support ticket creation, tracking, and FAQ tools."""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import SupportTicket, TicketStatus, TicketPriority

_ISSUE_PRIORITY_MAP = {
    "payment":     TicketPriority.high,
    "order_issue": TicketPriority.medium,
    "return":      TicketPriority.medium,
    "account":     TicketPriority.low,
    "product":     TicketPriority.low,
    "other":       TicketPriority.low,
}

_FAQ_KNOWLEDGE_BASE = [
    {
        "keywords": ["return", "refund", "policy"],
        "question": "What is the return policy?",
        "answer":   "You can return most items within 7 days of delivery for a full refund. Items must be unused and in original packaging. Refunds are processed within 5-7 business days.",
    },
    {
        "keywords": ["cancel", "cancellation"],
        "question": "How do I cancel an order?",
        "answer":   "Orders can be cancelled before they are shipped. Once shipped, you will need to initiate a return. Go to My Orders and select the order to cancel.",
    },
    {
        "keywords": ["delivery", "shipping", "time", "when"],
        "question": "How long does delivery take?",
        "answer":   "Standard delivery takes 3-5 business days. Express delivery (1-2 days) is available for most pin codes. You can check estimated delivery when placing your order.",
    },
    {
        "keywords": ["payment", "upi", "card", "wallet", "method"],
        "question": "What payment methods are accepted?",
        "answer":   "We accept credit/debit cards (Visa, Mastercard, RuPay), UPI (all UPI apps), and wallets. EMI is available on select cards for orders above ₹3,000.",
    },
    {
        "keywords": ["track", "tracking", "status", "order status"],
        "question": "How do I track my order?",
        "answer":   "Go to My Orders and click on the order you want to track. You will see the real-time status and tracking number once the order is shipped.",
    },
    {
        "keywords": ["change address", "delivery address"],
        "question": "Can I change my delivery address after placing an order?",
        "answer":   "Address changes are only possible if the order has not been shipped yet. Contact support immediately with your order ID and the new address.",
    },
    {
        "keywords": ["exchange", "replace", "replacement"],
        "question": "Can I exchange a product?",
        "answer":   "Yes, exchanges are available within 7 days of delivery. Initiate a return for the original item and place a new order for the replacement.",
    },
    {
        "keywords": ["damaged", "defective", "broken", "wrong item"],
        "question": "I received a damaged or wrong item. What should I do?",
        "answer":   "We apologise for the inconvenience. Please raise a support ticket with your order ID and photos of the issue. We will arrange a pickup and full refund or replacement within 48 hours.",
    },
    {
        "keywords": ["coupon", "discount", "promo", "code"],
        "question": "How do I apply a coupon code?",
        "answer":   "Enter your coupon code in the 'Apply Coupon' field during checkout. The discount will be applied automatically if the code is valid.",
    },
    {
        "keywords": ["account", "password", "login", "forgot"],
        "question": "I forgot my password. How do I reset it?",
        "answer":   "Click on 'Forgot Password' on the login page and enter your registered email. You will receive a reset link within a few minutes.",
    },
]


def create_support_ticket(
    customer_id: str,
    issue_type: str,
    description: str,
    db: Session,
    session_id: str = None,
    order_id: str = None,
    product_id: str = None,
    priority: str = None,
) -> str:
    resolved_priority = (
        TicketPriority(priority) if priority in [p.value for p in TicketPriority]
        else _ISSUE_PRIORITY_MAP.get(issue_type, TicketPriority.medium)
    )

    ticket = SupportTicket(
        customer_id = customer_id,
        issue_type  = issue_type,
        description = description,
        priority    = resolved_priority,
        session_id  = session_id,
        order_id    = order_id,
        product_id  = product_id,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return json.dumps({
        "ticket_id":   ticket.id,
        "status":      ticket.status.value,
        "priority":    ticket.priority.value,
        "issue_type":  ticket.issue_type,
        "message":     f"Support ticket {ticket.id} created successfully. Our team will respond within 24 hours for {ticket.priority.value} priority issues.",
    })


def get_customer_tickets(customer_id: str, db: Session) -> str:
    tickets = (
        db.query(SupportTicket)
        .filter(SupportTicket.customer_id == customer_id)
        .order_by(SupportTicket.created_at.desc())
        .limit(10)
        .all()
    )
    if not tickets:
        return json.dumps({"tickets": [], "message": "No support tickets found."})

    return json.dumps({
        "tickets": [
            {
                "ticket_id":   t.id,
                "issue_type":  t.issue_type,
                "description": t.description[:120] + "..." if len(t.description) > 120 else t.description,
                "status":      t.status.value,
                "priority":    t.priority.value,
                "order_id":    t.order_id,
                "created_at":  str(t.created_at),
            }
            for t in tickets
        ]
    })


def escalate_ticket(ticket_id: str, reason: str, db: Session) -> str:
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        return json.dumps({"error": f"Ticket {ticket_id} not found."})

    ticket.status     = TicketStatus.escalated
    ticket.resolution = f"Escalated: {reason}"
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()

    return json.dumps({
        "ticket_id": ticket_id,
        "status":    "escalated",
        "message":   "Ticket escalated to senior support. A specialist will contact the customer within 4 hours.",
    })


def resolve_ticket(ticket_id: str, resolution: str, db: Session) -> str:
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        return json.dumps({"error": f"Ticket {ticket_id} not found."})

    ticket.status      = TicketStatus.resolved
    ticket.resolution  = resolution
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.updated_at  = datetime.now(timezone.utc)
    db.commit()

    return json.dumps({
        "ticket_id":  ticket_id,
        "status":     "resolved",
        "resolution": resolution,
    })


def get_faq_answers(query: str) -> str:
    query_lower = query.lower()
    matches = []
    for faq in _FAQ_KNOWLEDGE_BASE:
        score = sum(1 for kw in faq["keywords"] if kw in query_lower)
        if score > 0:
            matches.append((score, faq))

    matches.sort(key=lambda x: x[0], reverse=True)
    top = [m[1] for m in matches[:3]]

    if not top:
        return json.dumps({
            "found": False,
            "message": "No specific FAQ found. Please check our help centre or raise a support ticket.",
        })

    return json.dumps({
        "found": True,
        "answers": [{"question": f["question"], "answer": f["answer"]} for f in top],
    })
