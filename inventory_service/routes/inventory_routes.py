import asyncio
import json
from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Product, InventoryMovement, Alert
from schemas import RestockRequest, AdjustmentRequest
from alert_engine import check_and_create_alerts, stock_health

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# ── GET /inventory/dashboard  ─────────────────────────────────────────────────
# Defined BEFORE /{product_id} so "dashboard" is not treated as a product_id.

@router.get("/dashboard", tags=["Dashboard"])
def dashboard(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True).all()

    out_of_stock = sum(1 for p in products if p.inventory_count == 0)
    critical     = sum(1 for p in products if 1 <= p.inventory_count <= 5)
    low          = sum(1 for p in products if 6 <= p.inventory_count <= 20)
    healthy      = sum(1 for p in products if p.inventory_count > 20)

    open_critical = db.query(Alert).filter(Alert.status == "open",    Alert.severity == "critical").count()
    open_warning  = db.query(Alert).filter(Alert.status == "open",    Alert.severity == "warning").count()
    acknowledged  = db.query(Alert).filter(Alert.status == "acknowledged").count()

    top_critical = (
        db.query(Product)
        .filter(Product.is_active == True, Product.inventory_count <= 5)
        .order_by(Product.inventory_count)
        .limit(10)
        .all()
    )

    recent_movements = (
        db.query(InventoryMovement)
        .order_by(InventoryMovement.created_at.desc())
        .limit(10)
        .all()
    )

    categories = (
        db.query(Product.category, func.count(Product.id), func.sum(Product.inventory_count))
        .filter(Product.is_active == True)
        .group_by(Product.category)
        .all()
    )

    return {
        "summary": {
            "total_active_products": len(products),
            "out_of_stock":          out_of_stock,
            "critical":              critical,
            "low":                   low,
            "healthy":               healthy,
        },
        "alerts": {
            "open_critical": open_critical,
            "open_warning":  open_warning,
            "acknowledged":  acknowledged,
        },
        "top_critical_products": [
            {
                "product_id":   p.id,
                "name":         p.name,
                "category":     p.category,
                "brand":        p.brand,
                "stock":        p.inventory_count,
                "health":       stock_health(p.inventory_count),
            }
            for p in top_critical
        ],
        "recent_movements": [
            {
                "product_name":   m.product_name,
                "change_type":    m.change_type,
                "quantity_change": m.quantity_change,
                "quantity_after": m.quantity_after,
                "changed_by":     m.changed_by,
                "timestamp":      str(m.created_at),
            }
            for m in recent_movements
        ],
        "by_category": [
            {
                "category":    cat,
                "products":    cnt,
                "total_stock": int(total or 0),
            }
            for cat, cnt, total in sorted(categories, key=lambda x: x[0])
        ],
    }


# ── GET /inventory/stream — SSE real-time feed ────────────────────────────────
# Defined BEFORE /{product_id}.

@router.get("/stream", tags=["Real-time"])
async def inventory_stream(request: Request):
    """
    Server-Sent Events stream.
    Emits inventory_change and low_stock_alert events every 3 seconds.
    Connect with: curl -N http://localhost:8005/inventory/stream
    """
    async def generate():
        from database import SessionLocal

        last_check = datetime.utcnow()
        yield f"data: {json.dumps({'type': 'connected', 'message': 'Inventory stream active. Polling every 3s.'})}\n\n"

        db = SessionLocal()
        try:
            while True:
                if await request.is_disconnected():
                    break

                now = datetime.utcnow()
                try:
                    new_movements = (
                        db.query(InventoryMovement)
                        .filter(InventoryMovement.created_at > last_check)
                        .order_by(InventoryMovement.created_at)
                        .all()
                    )
                    for m in new_movements:
                        yield "data: " + json.dumps({
                            "type":             "inventory_change",
                            "product_id":       m.product_id,
                            "product_name":     m.product_name,
                            "category":         m.category,
                            "change_type":      m.change_type,
                            "quantity_before":  m.quantity_before,
                            "quantity_change":  m.quantity_change,
                            "quantity_after":   m.quantity_after,
                            "changed_by":       m.changed_by,
                            "reference_id":     m.reference_id,
                            "timestamp":        str(m.created_at),
                        }) + "\n\n"

                    new_alerts = (
                        db.query(Alert)
                        .filter(Alert.created_at > last_check, Alert.status == "open")
                        .order_by(Alert.created_at)
                        .all()
                    )
                    for a in new_alerts:
                        yield "data: " + json.dumps({
                            "type":          "low_stock_alert",
                            "alert_id":      a.id,
                            "product_id":    a.product_id,
                            "product_name":  a.product_name,
                            "category":      a.category,
                            "current_stock": a.current_stock,
                            "threshold":     a.threshold,
                            "severity":      a.severity,
                            "timestamp":     str(a.created_at),
                        }) + "\n\n"

                    last_check = now
                except Exception:
                    db.rollback()

                yield f"data: {json.dumps({'type': 'heartbeat', 'ts': str(now)})}\n\n"
                await asyncio.sleep(3)
        finally:
            db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        },
    )


# ── GET /inventory — paginated product list with stock status ─────────────────

@router.get("")
def list_inventory(
    category: Optional[str]                                                              = Query(None, description="Filter by category"),
    health:   Optional[Literal["out_of_stock", "critical", "low", "healthy"]]           = Query(None),
    search:   Optional[str]                                                              = Query(None, description="Search product name or brand"),
    page:     int                                                                        = Query(1,   ge=1),
    limit:    int                                                                        = Query(50,  ge=1, le=200),
    db:       Session                                                                    = Depends(get_db),
):
    q = db.query(Product).filter(Product.is_active == True)

    if category:
        q = q.filter(Product.category == category)
    if search:
        safe_search = search.replace("%", "\\%").replace("_", "\\_")
        q = q.filter(
            (Product.name.ilike(f"%{safe_search}%", escape="\\")) |
            (Product.brand.ilike(f"%{safe_search}%", escape="\\"))
        )
    if health == "out_of_stock":
        q = q.filter(Product.inventory_count == 0)
    elif health == "critical":
        q = q.filter(Product.inventory_count >= 1, Product.inventory_count <= 5)
    elif health == "low":
        q = q.filter(Product.inventory_count >= 6, Product.inventory_count <= 20)
    elif health == "healthy":
        q = q.filter(Product.inventory_count > 20)

    total   = q.count()
    products = q.order_by(Product.inventory_count, Product.name).offset((page - 1) * limit).limit(limit).all()

    return {
        "total":  total,
        "page":   page,
        "limit":  limit,
        "pages":  (total + limit - 1) // limit,
        "results": [
            {
                "product_id":      p.id,
                "name":            p.name,
                "category":        p.category,
                "subcategory":     p.subcategory,
                "brand":           p.brand,
                "price":           p.price,
                "stock":           p.inventory_count,
                "health":          stock_health(p.inventory_count),
                "discount_pct":    p.discount_pct,
            }
            for p in products
        ],
    }


# ── GET /inventory/{product_id} — single product stock detail ─────────────────

@router.get("/{product_id}")
def get_product_inventory(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    alert = db.query(Alert).filter(
        Alert.product_id == product_id,
        Alert.status.in_(["open", "acknowledged"]),
    ).first()

    last_5 = (
        db.query(InventoryMovement)
        .filter(InventoryMovement.product_id == product_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "product_id":   product.id,
        "name":         product.name,
        "category":     product.category,
        "brand":        product.brand,
        "price":        product.price,
        "stock":        product.inventory_count,
        "health":       stock_health(product.inventory_count),
        "alert": {
            "alert_id": alert.id,
            "severity": alert.severity,
            "status":   alert.status,
            "threshold": alert.threshold,
        } if alert else None,
        "recent_movements": [
            {
                "change_type":     m.change_type,
                "quantity_before": m.quantity_before,
                "quantity_change": m.quantity_change,
                "quantity_after":  m.quantity_after,
                "changed_by":      m.changed_by,
                "reference_id":    m.reference_id,
                "notes":           m.notes,
                "timestamp":       str(m.created_at),
            }
            for m in last_5
        ],
    }


# ── POST /inventory/{product_id}/restock — add stock ─────────────────────────

@router.post("/{product_id}/restock", status_code=201)
def restock(product_id: str, payload: RestockRequest, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    before = product.inventory_count
    after  = before + payload.quantity

    product.inventory_count = after

    db.add(InventoryMovement(
        product_id      = product_id,
        product_name    = product.name,
        category        = product.category,
        brand           = product.brand,
        change_type     = "restock",
        quantity_before = before,
        quantity_change = payload.quantity,
        quantity_after  = after,
        reference_id    = payload.reference_id,
        notes           = payload.notes,
        changed_by      = payload.changed_by,
    ))

    check_and_create_alerts(db, product_id, product.name, product.category, product.brand, after)
    db.commit()

    return {
        "message":         f"Restocked {payload.quantity} units of '{product.name}'",
        "product_id":      product_id,
        "quantity_added":  payload.quantity,
        "stock_before":    before,
        "stock_after":     after,
        "health":          stock_health(after),
        "reference_id":    payload.reference_id,
    }


# ── POST /inventory/{product_id}/adjust — manual adjustment ──────────────────

@router.post("/{product_id}/adjust", status_code=201)
def adjust(product_id: str, payload: AdjustmentRequest, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    before = product.inventory_count

    if before + payload.quantity_change < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Adjustment would result in negative stock. "
                   f"Current: {before}, Change: {payload.quantity_change}. "
                   f"Maximum removal: {before} units.",
        )

    after = before + payload.quantity_change
    product.inventory_count = after

    db.add(InventoryMovement(
        product_id      = product_id,
        product_name    = product.name,
        category        = product.category,
        brand           = product.brand,
        change_type     = payload.change_type,
        quantity_before = before,
        quantity_change = payload.quantity_change,
        quantity_after  = after,
        reference_id    = payload.reference_id,
        notes           = payload.reason,
        changed_by      = payload.changed_by,
    ))

    check_and_create_alerts(db, product_id, product.name, product.category, product.brand, after)
    db.commit()

    direction = "added" if payload.quantity_change > 0 else "removed"
    return {
        "message":          f"{abs(payload.quantity_change)} units {direction} ({payload.change_type})",
        "product_id":       product_id,
        "change_type":      payload.change_type,
        "quantity_change":  payload.quantity_change,
        "stock_before":     before,
        "stock_after":      after,
        "health":           stock_health(after),
        "reason":           payload.reason,
    }


# ── GET /inventory/{product_id}/movements — full movement history ─────────────

@router.get("/{product_id}/movements")
def movements(
    product_id: str,
    change_type: str  = Query(None),
    limit:       int  = Query(50, ge=1, le=500),
    page:        int  = Query(1,  ge=1),
    db:          Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    q = db.query(InventoryMovement).filter(InventoryMovement.product_id == product_id)
    if change_type:
        q = q.filter(InventoryMovement.change_type == change_type)

    total     = q.count()
    movements = q.order_by(InventoryMovement.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "product_id":   product_id,
        "product_name": product.name,
        "current_stock": product.inventory_count,
        "total":        total,
        "page":         page,
        "movements": [
            {
                "id":              m.id,
                "change_type":     m.change_type,
                "quantity_before": m.quantity_before,
                "quantity_change": m.quantity_change,
                "quantity_after":  m.quantity_after,
                "reference_id":    m.reference_id,
                "notes":           m.notes,
                "changed_by":      m.changed_by,
                "timestamp":       str(m.created_at),
            }
            for m in movements
        ],
    }
