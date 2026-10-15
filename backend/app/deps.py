from fastapi import Depends, HTTPException, Header
from typing import Optional

from app.security import decode_access_token


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Port of middleware/auth.js:verifyToken. Reads `Authorization: Bearer <token>`."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No authentication token provided.")
    token = authorization[len("Bearer "):]
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session token.")
    return payload  # {id, email, name, role}


def require_roles(*roles: str):
    """Port of middleware/auth.js:requireRole. Usage: Depends(require_roles('vendor','admin'))"""

    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. This route requires role(s): {', '.join(roles)}.",
            )
        return user

    return _checker
