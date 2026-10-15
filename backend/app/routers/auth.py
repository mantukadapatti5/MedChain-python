from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.sql_models import User, Client
from app.services import client_verification
from app.security import verify_password, create_access_token
from app.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str
    role: str | None = None


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email.ilike(body.email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="No account found for this email.")
    if body.role and user.role != body.role:
        raise HTTPException(status_code=403, detail=f'This account is registered as "{user.role}", not "{body.role}". Please use the correct portal.')
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password. Please try again.")

    if user.role == "client":
        client = db.query(Client).filter(Client.user_id == user.id).first()
        if client:
            blocked = client_verification.login_block_message(
                client.verification_status, client.rejection_reason, client.license_verified)
            if blocked:
                raise HTTPException(status_code=403, detail=blocked)

    user_dict = {"id": user.id, "email": user.email, "name": user.name, "role": user.role}
    token = create_access_token(user_dict)
    return {"token": token, "user": user_dict}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"user": user}
