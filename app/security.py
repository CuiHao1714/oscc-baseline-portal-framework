import bcrypt
import secrets
from fastapi import HTTPException, Request

ROLES = {"viewer", "editor", "admin"}


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def validate_csrf(request: Request, token: str | None) -> None:
    if not token or not secrets.compare_digest(token, request.session.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def can_edit(role: str) -> bool:
    return role in {"editor", "admin"}


def can_admin(role: str) -> bool:
    return role == "admin"
