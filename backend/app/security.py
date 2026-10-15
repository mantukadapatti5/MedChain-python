"""Direct port of backend/utils/security.js and backend/middleware/auth.js."""
import hashlib
from datetime import datetime, timedelta, timezone

import jwt

from app.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS

SALT = "drug-scm-static-salt-v1"  # demo project; use per-user salts + a real KDF in production


def hash_password(plain: str) -> str:
    return hashlib.sha256((SALT + plain).encode("utf-8")).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed


def create_access_token(user: dict) -> str:
    payload = {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
