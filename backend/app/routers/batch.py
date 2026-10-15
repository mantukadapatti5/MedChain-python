from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.services import batch_verify

router = APIRouter(prefix="/api/batch", tags=["batch"], dependencies=[Depends(require_roles("admin", "vendor", "distributor", "client"))])


@router.get("/{batch}/verify")
def verify(batch: str, db: Session = Depends(get_db)):
    return batch_verify.verify_batch_everywhere(db, batch)
