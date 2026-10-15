from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import get_current_user
from app.serializers import row_to_dict
from app.services import notifications as notif_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_notifications(type: str = None, unreadOnly: bool = False, limit: int = 100,
                        db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    user_id, role = user.get("id"), user.get("role")
    rows = notif_service.list_notifications(db, user_id=user_id, role=role, type=type, unread_only=unreadOnly, limit=limit)
    return {
        "notifications": [row_to_dict(n) for n in rows],
        "unreadCount": notif_service.unread_count(db, user_id=user_id, role=role),
    }


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    n = notif_service.mark_read(db, notification_id, user_id=user.get("id"), role=user.get("role"))
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found.")
    db.commit()
    return row_to_dict(n)


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    count = notif_service.mark_all_read(db, user_id=user.get("id"), role=user.get("role"))
    db.commit()
    return {"updated": count}


@router.post("/system", status_code=201)
def system_notification(body: dict, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    n, _ = notif_service.create_notification(
        db, role=body.get("role"), type=body.get("type", "SYSTEM"), severity=body.get("severity", "info"),
        title=body.get("title"), message=body.get("message"), related_drug=body.get("relatedDrug"),
        related_batch=body.get("relatedBatch"), related_request_id=body.get("relatedRequestId"),
        action_path=body.get("actionPath"),
    )
    db.commit()
    return row_to_dict(n)
