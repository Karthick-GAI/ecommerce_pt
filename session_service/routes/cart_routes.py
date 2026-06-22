"""
Session cart routes.

The session cart is the pre-checkout intent cart — it persists for the
lifetime of the session. It is separate from checkout_carts (which is
created when the customer proceeds to checkout).

GET    /sessions/{id}/cart                    — cart with totals
POST   /sessions/{id}/cart/items              — add item
PUT    /sessions/{id}/cart/items/{product_id} — update quantity (0 = remove)
DELETE /sessions/{id}/cart/items/{product_id} — remove item
DELETE /sessions/{id}/cart                    — clear active items
POST   /sessions/{id}/cart/save/{product_id}  — toggle save-for-later
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import ShoppingSession, SessionCartItem, SessionEvent, Product
from schemas import CartItemAdd, CartItemUpdate

router = APIRouter(prefix="/sessions", tags=["Cart"])


def _get_session(session_id: str, db: Session) -> ShoppingSession:
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status not in ("active",):
        raise HTTPException(status_code=400,
                            detail=f"Cart is locked — session is {session.status}.")
    return session


def _cart_totals(items: list[SessionCartItem]) -> dict:
    active = [i for i in items if not i.saved_for_later]
    saved  = [i for i in items if i.saved_for_later]

    def total(lst):
        return round(sum(
            (i.unit_price or 0) * (1 - (i.discount_pct or 0) / 100) * i.quantity
            for i in lst
        ), 2)

    return {
        "active_items":      len(active),
        "saved_items":       len(saved),
        "subtotal":          total(active),
        "total_after_discount": total(active),
        "items": [
            {
                "product_id":   i.product_id,
                "product_name": i.product_name,
                "category":     i.category,
                "brand":        i.brand,
                "quantity":     i.quantity,
                "unit_price":   i.unit_price,
                "discount_pct": i.discount_pct,
                "effective_price": round((i.unit_price or 0) * (1 - (i.discount_pct or 0) / 100), 2),
                "line_total":   round((i.unit_price or 0) * (1 - (i.discount_pct or 0) / 100) * i.quantity, 2),
                "saved_for_later": i.saved_for_later,
                "added_at":     str(i.added_at),
            }
            for i in items
        ],
    }


# ── GET /sessions/{session_id}/cart ──────────────────────────────────────────

@router.get("/{session_id}/cart")
def get_cart(session_id: str, db: Session = Depends(get_db)):
    """Current cart contents with line totals and subtotal."""
    session = db.query(ShoppingSession).filter(ShoppingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    items = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id
    ).order_by(SessionCartItem.added_at).all()

    return {"session_id": session_id, **_cart_totals(items)}


# ── POST /sessions/{session_id}/cart/items ───────────────────────────────────

@router.post("/{session_id}/cart/items", status_code=201)
def add_to_cart(session_id: str, payload: CartItemAdd, db: Session = Depends(get_db)):
    """Add a product to the session cart. Increments quantity if already present."""
    session = _get_session(session_id, db)

    product = db.query(Product).filter(
        Product.id == payload.product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    existing = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id,
        SessionCartItem.product_id == payload.product_id,
        SessionCartItem.saved_for_later == False,
    ).first()

    if existing:
        existing.quantity   += payload.quantity
        existing.updated_at  = datetime.now(timezone.utc)
        action = "updated"
    else:
        existing = SessionCartItem(
            session_id   = session_id,
            customer_id  = session.customer_id,
            product_id   = payload.product_id,
            product_name = product.name,
            category     = product.category,
            brand        = product.brand,
            quantity     = payload.quantity,
            unit_price   = product.price,
            discount_pct = product.discount_pct,
        )
        db.add(existing)
        action = "added"

    # Log event
    db.add(SessionEvent(
        session_id   = session_id,
        customer_id  = session.customer_id,
        event_type   = "add_to_cart",
        product_id   = payload.product_id,
        product_name = product.name,
        category     = product.category,
    ))
    session.event_count      = (session.event_count or 0) + 1
    session.last_activity_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "message":      f"Cart {action}",
        "product_name": product.name,
        "quantity":     existing.quantity,
        "unit_price":   product.price,
        "effective_price": round(product.price * (1 - (product.discount_pct or 0) / 100), 2),
    }


# ── PUT /sessions/{session_id}/cart/items/{product_id} ───────────────────────

@router.put("/{session_id}/cart/items/{product_id}")
def update_cart_item(
    session_id: str,
    product_id: str,
    payload: CartItemUpdate,
    db: Session = Depends(get_db),
):
    """Update item quantity. Send quantity=0 to remove the item."""
    _get_session(session_id, db)

    item = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id,
        SessionCartItem.product_id == product_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not in cart")

    if payload.quantity == 0:
        db.delete(item)
        db.commit()
        return {"message": "Item removed from cart", "product_id": product_id}

    item.quantity   = payload.quantity
    item.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "message":    "Quantity updated",
        "product_id": product_id,
        "quantity":   item.quantity,
        "line_total": round((item.unit_price or 0) * (1 - (item.discount_pct or 0) / 100) * item.quantity, 2),
    }


# ── DELETE /sessions/{session_id}/cart/items/{product_id} ────────────────────

@router.delete("/{session_id}/cart/items/{product_id}")
def remove_cart_item(session_id: str, product_id: str, db: Session = Depends(get_db)):
    """Remove a specific item from the cart."""
    _get_session(session_id, db)

    item = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id,
        SessionCartItem.product_id == product_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not in cart")

    db.delete(item)
    db.commit()
    return {"message": "Item removed", "product_id": product_id}


# ── DELETE /sessions/{session_id}/cart ───────────────────────────────────────

@router.delete("/{session_id}/cart")
def clear_cart(session_id: str, db: Session = Depends(get_db)):
    """Remove all active cart items (saved-for-later items are preserved)."""
    _get_session(session_id, db)

    deleted = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id,
        SessionCartItem.saved_for_later == False,
    ).delete()
    db.commit()
    return {"message": f"Cart cleared — {deleted} item(s) removed", "session_id": session_id}


# ── POST /sessions/{session_id}/cart/save/{product_id} ───────────────────────

@router.post("/{session_id}/cart/save/{product_id}")
def toggle_save_for_later(session_id: str, product_id: str, db: Session = Depends(get_db)):
    """Toggle a cart item between active cart and saved-for-later."""
    _get_session(session_id, db)

    item = db.query(SessionCartItem).filter(
        SessionCartItem.session_id == session_id,
        SessionCartItem.product_id == product_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not in cart")

    item.saved_for_later = not item.saved_for_later
    item.updated_at      = datetime.now(timezone.utc)
    db.commit()

    state = "saved for later" if item.saved_for_later else "moved back to cart"
    return {
        "message":        f"Item {state}",
        "product_name":   item.product_name,
        "saved_for_later": item.saved_for_later,
    }
