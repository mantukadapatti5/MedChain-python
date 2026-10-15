"""Direct port of backend/utils/notifications.js, backed by the Postgres Notification table."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.sql_models import Notification
from app.serializers import row_to_dict

VALID_TYPES = ["SHORTAGE", "ANOMALY", "RECALL", "COLD_CHAIN", "SHIPMENT", "EXPIRY", "SYSTEM"]
VALID_SEVERITIES = ["info", "low", "medium", "high", "critical"]


def create_notification(db: Session, *, user_id=None, role=None, type="SYSTEM", severity="info",
                         title, message, related_drug=None, related_batch=None,
                         related_request_id=None, action_path=None, event_key=None):
    if not title or not message:
        raise ValueError("Notification title and message are required.")

    if event_key:
        q = db.query(Notification).filter(Notification.event_key == event_key)
        if user_id is not None:
            q = q.filter(Notification.user_id == user_id)
        if role is not None:
            q = q.filter(Notification.role == role)
        existing = q.first()
        if existing:
            return existing, False

    notification = Notification(
        user_id=user_id,
        role=role,
        type=type if type in VALID_TYPES else "SYSTEM",
        severity=severity if severity in VALID_SEVERITIES else "info",
        title=title,
        message=message,
        related_drug=related_drug,
        related_batch=related_batch,
        related_request_id=related_request_id,
        action_path=action_path,
        event_key=event_key,
        read=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(notification)
    db.flush()
    return notification, True


def _visible_to(n, user_id, role) -> bool:
    """A notification is visible to a user when it is a broadcast (no user and no role),
    is addressed to that user, or is addressed to that user's role. (Previously any
    notification without a user_id was visible to everybody, so admin-only alerts
    leaked to vendors, distributors and clients.)"""
    if n.user_id is None and not n.role:
        return True
    return (n.user_id is not None and n.user_id == user_id) or (bool(n.role) and n.role == role)


def list_notifications(db: Session, *, user_id=None, role=None, type=None, unread_only=False, limit=100):
    max_limit = max(1, min(limit or 100, 500))
    q = db.query(Notification)
    rows = q.order_by(desc(Notification.created_at)).all()

    filtered = [n for n in rows if _visible_to(n, user_id, role) and (not type or n.type == type) and (not unread_only or not n.read)]
    return filtered[:max_limit]


def mark_read(db: Session, notification_id: int, *, user_id=None, role=None):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        return None
    if not _visible_to(notification, user_id, role):
        return None
    notification.read = True
    notification.read_at = datetime.now(timezone.utc).isoformat()
    db.flush()
    return notification


def mark_all_read(db: Session, *, user_id=None, role=None) -> int:
    rows = db.query(Notification).all()
    count = 0
    now = datetime.now(timezone.utc).isoformat()
    for n in rows:
        if _visible_to(n, user_id, role) and not n.read:
            n.read = True
            n.read_at = now
            count += 1
    db.flush()
    return count


def unread_count(db: Session, *, user_id=None, role=None) -> int:
    return len(list_notifications(db, user_id=user_id, role=role, unread_only=True, limit=500))
