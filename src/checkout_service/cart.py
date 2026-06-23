from sqlalchemy.orm import Session
from models import Cart, CartItem, Product
from schemas import CartResponse, CartItemResponse


def build_cart_response(cart: Cart, db: Session) -> CartResponse:
    """Build full cart response with live product details for each item."""
    items = []
    subtotal = 0.0

    for item in cart.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            continue
        total_price = round(item.price_at_add * item.quantity, 2)
        subtotal   += total_price
        items.append(CartItemResponse(
            product_id=item.product_id,
            product_name=product.name,
            brand=product.brand,
            quantity=item.quantity,
            unit_price=item.price_at_add,
            total_price=total_price,
            in_stock=product.inventory_count >= item.quantity,
        ))

    return CartResponse(
        cart_id=cart.id,
        status=cart.status,
        items=items,
        item_count=sum(i.quantity for i in cart.items),
        subtotal=round(subtotal, 2),
        created_at=str(cart.created_at),
    )
