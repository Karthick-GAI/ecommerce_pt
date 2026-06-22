from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Notification

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ── GET /notifications/customer/{id} — all notifications (newest first) ──────
# Defined BEFORE /{id}/read to avoid literal "customer" matching /{id}

@router.get("/customer/{customer_id}")
def get_notifications(
    customer_id: str,
    channel: str = None,   # optional filter: email | sms | push
    event: str = None,     # optional filter by event type
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.customer_id == customer_id)
    if channel:
        q = q.filter(Notification.channel == channel)
    if event:
        q = q.filter(Notification.event == event)

    notifications = q.order_by(Notification.sent_at.desc()).limit(limit).all()
    unread_count  = db.query(Notification).filter(
        Notification.customer_id == customer_id,
        Notification.is_read == False,
    ).count()

    return {
        "customer_id":   customer_id,
        "total":         len(notifications),
        "unread_count":  unread_count,
        "notifications": [
            {
                "id":       n.id,
                "order_id": n.order_id,
                "channel":  n.channel,
                "event":    n.event,
                "title":    n.title,
                "message":  n.message,
                "is_read":  n.is_read,
                "sent_at":  str(n.sent_at),
            }
            for n in notifications
        ],
    }


# ── GET /notifications/customer/{id}/unread — unread only ────────────────────

@router.get("/customer/{customer_id}/unread")
def get_unread(customer_id: str, db: Session = Depends(get_db)):
    notifications = (
        db.query(Notification)
        .filter(
            Notification.customer_id == customer_id,
            Notification.is_read == False,
        )
        .order_by(Notification.sent_at.desc())
        .all()
    )
    return {
        "customer_id":   customer_id,
        "unread_count":  len(notifications),
        "notifications": [
            {
                "id":       n.id,
                "order_id": n.order_id,
                "channel":  n.channel,
                "event":    n.event,
                "title":    n.title,
                "message":  n.message,
                "sent_at":  str(n.sent_at),
            }
            for n in notifications
        ],
    }


# ── PUT /notifications/{id}/read — mark single notification as read ───────────

@router.put("/{notification_id}/read")
def mark_read(notification_id: str, db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    db.commit()

    return {"message": "Notification marked as read", "id": notification_id}


# ── PUT /notifications/customer/{id}/read-all — mark all as read ─────────────

@router.put("/customer/{customer_id}/read-all")
def mark_all_read(customer_id: str, db: Session = Depends(get_db)):
    updated = (
        db.query(Notification)
        .filter(
            Notification.customer_id == customer_id,
            Notification.is_read == False,
        )
        .update({"is_read": True})
    )
    db.commit()

    return {
        "message":          f"Marked {updated} notification(s) as read",
        "notifications_updated": updated,
    }
