from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import get_current_user
from app.models.sql_models import Settings, Recall
from app.serializers import row_to_dict, rows_to_list
from app.services import blockchain

router = APIRouter(prefix="/api/blockchain", tags=["blockchain"], dependencies=[Depends(get_current_user)])


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.get("/ledger")
def ledger(limit: int = 50):
    all_blocks = list(reversed(blockchain.get_all()))
    return {"total": len(all_blocks), "blocks": all_blocks[:limit]}


@router.get("/verify")
def verify():
    return blockchain.verify_chain()


@router.get("/provenance/{batch}")
def provenance(batch: str):
    blocks = blockchain.get_by_batch(batch)
    return {"batch": batch, "found": len(blocks) > 0, "history": blocks}


@router.get("/emergency-status")
def emergency_status(db: Session = Depends(get_db)):
    s = db.query(Settings).first()
    if not s:
        s = Settings(id=1, emergency_mode=False)
        db.add(s)
        db.commit()
        db.refresh(s)
    return row_to_dict(s)


@router.get("/recalls/active")
def active_recalls(db: Session = Depends(get_db)):
    return rows_to_list(db.query(Recall).filter(Recall.status == "active").all())


@router.post("/recalls/{recall_id}/acknowledge")
def acknowledge_recall(recall_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    recall = db.query(Recall).filter(Recall.id == recall_id).first()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found.")
    ack_list = list(recall.acknowledged_by or [])
    already = any(a.get("email") == user["email"] for a in ack_list)
    if not already:
        ack_list.append({"role": user["role"], "email": user["email"], "name": user.get("name"), "acknowledgedAt": _now()})
        recall.acknowledged_by = ack_list
        blockchain.add_block("RECALL_ACKNOWLEDGED", user["email"], {"recallId": recall.id, "batch": recall.batch,
                              "drugName": recall.drug_name, "role": user["role"]})
        db.commit()
        db.refresh(recall)
    return row_to_dict(recall)
