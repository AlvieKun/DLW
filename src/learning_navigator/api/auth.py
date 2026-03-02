"""Authentication module: password hashing, JWT tokens, FastAPI dependencies.

Implements:
  - bcrypt password hashing
  - JWT access tokens in HttpOnly cookies
  - FastAPI dependency `get_current_user` for route protection
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
import structlog
from fastapi import Cookie, HTTPException, Request, status

logger = structlog.get_logger(__name__)

JWT_SECRET = os.environ.get("LN_JWT_SECRET", "dev-secret-change-in-production-!!!!")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.environ.get("LN_JWT_EXPIRY_HOURS", "72"))
COOKIE_NAME = "ln_session"


# ── Password hashing ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ── JWT tokens ────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str) -> str:
    """Create a JWT access token."""
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session. Please log in again.",
        )


# ── FastAPI dependency ────────────────────────────────────────────

async def get_current_user(request: Request) -> dict[str, Any]:
    """Extract and validate the current user from the session cookie or Authorization header.
    
    Returns dict with keys: user_id, email
    """
    token = None

    # Try cookie first
    token = request.cookies.get(COOKIE_NAME)

    # Fallback to Authorization header
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )

    payload = decode_token(token)
    return {"user_id": payload["sub"], "email": payload["email"]}


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Like get_current_user but returns None instead of raising."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
