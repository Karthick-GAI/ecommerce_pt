"""
Seller order management dashboard.

Sellers can view orders containing their products and update fulfillment status.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Seller, SellerOrder, SellerProduct
from schemas import SellerOrderResponse, FulfillmentUpdate, SellerDashboard
from dependencies import get_current_seller

router = APIRouter(prefix="/seller/orders", tags=["Seller Orders"])


@router.get("", response_model=list[SellerOrderResponse])
def list_orders(
    status: Optional[str] = Query(None, description="Filter by fulfillment_status"),
    payout: Optional[str] = Query(None, description="Filter by payout_status"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """List orders containing this seller's products, with optional filters."""
    q = db.query(SellerOrder).filter(SellerOrder.seller_id == seller.id)
    if status:
        q = q.filter(SellerOrder.fulfillment_status == status)
    if payout:
        q = q.filter(SellerOrder.payout_status == payout)
    return q.order_by(SellerOrder.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/dashboard", response_model=SellerDashboard)
def dashboard(
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """
    Seller analytics dashboard.
    Returns product counts, order summary, revenue, and pending payout.
    """
    now      = datetime.utcnow()
    days_30  = now - timedelta(days=30)

    total_products  = db.query(SellerProduct).filter(SellerProduct.seller_id == seller.id).count()
    active_products = db.query(SellerProduct).filter(
        SellerProduct.seller_id == seller.id, SellerProduct.is_active == True
    ).count()
    pending_review  = db.query(SellerProduct).filter(
        SellerProduct.seller_id == seller.id, SellerProduct.approval_status == "pending_review"
    ).count()

    orders = db.query(SellerOrder).filter(SellerOrder.seller_id == seller.id).all()
    total_orders   = len(orders)
    pending_orders = sum(1 for o in orders if o.fulfillment_status == "pending")
    total_revenue  = sum(o.payout_amount or 0 for o in orders if o.payout_status == "paid")
    pending_payout = sum(o.payout_amount or 0 for o in orders if o.payout_status == "pending")

    recent = [o for o in orders if o.created_at and o.created_at >= days_30]
    last_30_revenue = sum(o.total_price for o in recent)

    return SellerDashboard(
        seller_id=seller.id,
        business_name=seller.business_name,
        total_products=total_products,
        active_products=active_products,
        pending_review=pending_review,
        total_orders=total_orders,
        pending_orders=pending_orders,
        total_revenue=round(total_revenue, 2),
        pending_payout=round(pending_payout, 2),
        last_30_days_revenue=round(last_30_revenue, 2),
    )


@router.put("/{order_item_id}/fulfillment", response_model=SellerOrderResponse)
def update_fulfillment(
    order_item_id: str,
    payload: FulfillmentUpdate,
    db: Session = Depends(get_db),
    seller: Seller = Depends(get_current_seller),
):
    """Update fulfillment status for an order line (e.g., mark as shipped)."""
    order = db.query(SellerOrder).filter(
        SellerOrder.id == order_item_id,
        SellerOrder.seller_id == seller.id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order item not found")

    # Prevent backward status transitions
    STATUS_ORDER = ["pending", "processing", "shipped", "delivered"]
    if payload.status in STATUS_ORDER and order.fulfillment_status in STATUS_ORDER:
        current_idx = STATUS_ORDER.index(order.fulfillment_status)
        new_idx     = STATUS_ORDER.index(payload.status) if payload.status in STATUS_ORDER else 99
        if new_idx < current_idx:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot move fulfillment back from '{order.fulfillment_status}' to '{payload.status}'",
            )

    order.fulfillment_status = payload.status
    order.updated_at         = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order


@router.post("/seed-demo", tags=["Seller Admin"])
def seed_demo_orders(seller_id: str, db: Session = Depends(get_db)):
    """
    Seed demonstration order data for a seller — useful for testing the dashboard.
    Not for production use.
    """
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    import uuid
    statuses = ["pending", "processing", "shipped", "delivered", "delivered", "delivered"]
    for i, st in enumerate(statuses):
        price = round(100 + i * 150.5, 2)
        commission = round(price * 0.10, 2)
        order = SellerOrder(
            seller_id=seller_id,
            order_id=str(uuid.uuid4()),
            product_id=str(uuid.uuid4()),
            product_name=f"Demo Product {i+1}",
            quantity=i + 1,
            unit_price=price,
            total_price=round(price * (i + 1), 2),
            commission_rate=10.0,
            commission_amt=commission,
            payout_amount=round(price * (i + 1) - commission, 2),
            fulfillment_status=st,
            payout_status="paid" if st == "delivered" else "pending",
            customer_city=["Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad", "Pune"][i],
        )
        db.add(order)

    db.commit()
    return {"message": f"Seeded 6 demo orders for seller '{seller.business_name}'"}
