from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Order, OrderItem, Payment
from schemas import OrderDetailResponse, OrderItemResponse

router = APIRouter(prefix="/orders", tags=["Orders"])


def _build_order_detail(order: Order, db: Session) -> OrderDetailResponse:
    payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    return OrderDetailResponse(
        order_id=order.id,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        transaction_id=payment.transaction_id if payment else None,
        items=[
            OrderItemResponse(
                product_id=i.product_id,
                product_name=i.product_name,
                brand=i.brand,
                quantity=i.quantity,
                unit_price=i.unit_price,
                total_price=i.total_price,
            )
            for i in order.items
        ],
        subtotal=order.subtotal,
        discount=order.discount,
        tax=order.tax,
        shipping_charge=order.shipping_charge,
        total=order.total,
        shipping_name=order.shipping_name,
        shipping_phone=order.shipping_phone,
        shipping_address=order.shipping_address,
        shipping_city=order.shipping_city,
        shipping_state=order.shipping_state,
        shipping_pincode=order.shipping_pincode,
        created_at=str(order.created_at),
    )


# ── GET /orders/{order_id} — order detail ────────────────────────────────────

@router.get("/{order_id}", response_model=OrderDetailResponse)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _build_order_detail(order, db)


# ── GET /orders/customer/{customer_id} — customer history ────────────────────

@router.get("/customer/{customer_id}")
def customer_orders(customer_id: str, db: Session = Depends(get_db)):
    orders = (
        db.query(Order)
        .filter(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return {
        "customer_id": customer_id,
        "total_orders": len(orders),
        "orders": [
            {
                "order_id":       o.id,
                "status":         o.status,
                "payment_status": o.payment_status,
                "total":          o.total,
                "item_count":     len(o.items),
                "created_at":     str(o.created_at),
            }
            for o in orders
        ],
    }


# ── PUT /orders/{order_id}/cancel — cancel order ─────────────────────────────

@router.put("/{order_id}/cancel")
def cancel_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in ("pending", "confirmed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order with status '{order.status}'. Only pending/confirmed orders can be cancelled.",
        )

    # Restore inventory if order was confirmed (payment already taken)
    if order.status == "confirmed":
        for item in order.items:
            from models import Product
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.inventory_count += item.quantity

    order.status = "cancelled"
    db.commit()
    return {"message": "Order cancelled successfully", "order_id": order_id}
