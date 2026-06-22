from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Cart, CartItem, Product
from schemas import CartResponse, CreateCartRequest, AddItemRequest, UpdateItemRequest
from cart import build_cart_response

router = APIRouter(prefix="/cart", tags=["Cart"])


# ── POST /cart — create cart ──────────────────────────────────────────────────

@router.post("", response_model=CartResponse, status_code=201)
def create_cart(payload: CreateCartRequest, db: Session = Depends(get_db)):
    """Create a new shopping cart. customer_id is optional (guest carts allowed)."""
    cart = Cart(customer_id=payload.customer_id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return build_cart_response(cart, db)


# ── GET /cart/{cart_id} — view cart ──────────────────────────────────────────

@router.get("/{cart_id}", response_model=CartResponse)
def get_cart(cart_id: str, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.id == cart_id).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    return build_cart_response(cart, db)


# ── POST /cart/{cart_id}/items — add item ─────────────────────────────────────

@router.post("/{cart_id}/items", response_model=CartResponse)
def add_item(cart_id: str, payload: AddItemRequest, db: Session = Depends(get_db)):
    """
    Add a product to the cart.
    - If the product is already in the cart, quantity is increased.
    - Price is snapshotted at add time (discount already applied).
    """
    cart = db.query(Cart).filter(Cart.id == cart_id, Cart.status == "active").first()
    if not cart:
        raise HTTPException(status_code=404, detail="Active cart not found")

    product = db.query(Product).filter(
        Product.id == payload.product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or unavailable")
    if product.inventory_count == 0:
        raise HTTPException(status_code=400, detail=f"'{product.name}' is out of stock")

    effective_price = round(product.price * (1 - product.discount_pct / 100), 2)

    existing = db.query(CartItem).filter(
        CartItem.cart_id == cart_id,
        CartItem.product_id == payload.product_id,
    ).first()

    if existing:
        new_qty = existing.quantity + payload.quantity
        if new_qty > product.inventory_count:
            raise HTTPException(
                status_code=400,
                detail=f"Only {product.inventory_count} units available (you already have {existing.quantity} in cart)",
            )
        existing.quantity     = new_qty
        existing.price_at_add = effective_price   # refresh to latest price
    else:
        if payload.quantity > product.inventory_count:
            raise HTTPException(
                status_code=400,
                detail=f"Only {product.inventory_count} units available",
            )
        db.add(CartItem(
            cart_id=cart_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            price_at_add=effective_price,
        ))

    cart.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cart)
    return build_cart_response(cart, db)


# ── PUT /cart/{cart_id}/items/{product_id} — update quantity ──────────────────

@router.put("/{cart_id}/items/{product_id}", response_model=CartResponse)
def update_item(cart_id: str, product_id: str, payload: UpdateItemRequest, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.id == cart_id, Cart.status == "active").first()
    if not cart:
        raise HTTPException(status_code=404, detail="Active cart not found")

    item = db.query(CartItem).filter(
        CartItem.cart_id == cart_id, CartItem.product_id == product_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not in cart")

    product = db.query(Product).filter(Product.id == product_id).first()
    if product and payload.quantity > product.inventory_count:
        raise HTTPException(status_code=400, detail=f"Only {product.inventory_count} units available")

    item.quantity   = payload.quantity
    cart.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cart)
    return build_cart_response(cart, db)


# ── DELETE /cart/{cart_id}/items/{product_id} — remove item ──────────────────

@router.delete("/{cart_id}/items/{product_id}", response_model=CartResponse)
def remove_item(cart_id: str, product_id: str, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.id == cart_id, Cart.status == "active").first()
    if not cart:
        raise HTTPException(status_code=404, detail="Active cart not found")

    item = db.query(CartItem).filter(
        CartItem.cart_id == cart_id, CartItem.product_id == product_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not in cart")

    db.delete(item)
    cart.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cart)
    return build_cart_response(cart, db)


# ── DELETE /cart/{cart_id} — clear cart ──────────────────────────────────────

@router.delete("/{cart_id}")
def clear_cart(cart_id: str, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.id == cart_id).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    db.delete(cart)
    db.commit()
    return {"message": "Cart deleted", "cart_id": cart_id}
