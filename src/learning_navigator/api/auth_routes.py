"""Auth API routes: register, login, logout, me, profile, events, uploads.

All routes are mounted under the FastAPI app via `include_router`.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    UploadFile,
    File,
    status,
)
from pydantic import BaseModel, EmailStr, Field

from learning_navigator.api.auth import (
    COOKIE_NAME,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from learning_navigator.api.auth_db import (
    create_event,
    create_upload,
    create_user,
    get_profile,
    get_user_by_email,
    get_user_by_id,
    list_events,
    list_uploads,
    update_profile,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

UPLOAD_DIR = os.environ.get("LN_UPLOAD_DIR", "data/uploads")


# ── Request/Response models ───────────────────────────────────────


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)
    display_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    onboarded: bool = False
    created_at: str


class ProfileUpdate(BaseModel):
    learning_goals: dict[str, Any] | None = None
    subjects: list[dict[str, Any]] | None = None
    weekly_schedule: dict[str, Any] | None = None
    preferences: dict[str, Any] | None = None
    baseline_assessment: dict[str, Any] | None = None


class EventCreate(BaseModel):
    concept: str = ""
    score: float | None = None
    time_spent_minutes: float | None = None
    event_type: str = "quiz_result"
    notes: str = ""
    source: str = "manual"
    timestamp: str | None = None


# ── Auth endpoints ────────────────────────────────────────────────


@router.post("/auth/register", response_model=UserResponse)
async def register(req: RegisterRequest, response: Response):
    """Register a new user account."""
    existing = await get_user_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user_id = uuid.uuid4().hex
    pw_hash = hash_password(req.password)
    user = await create_user(user_id, req.email, pw_hash, req.display_name)

    # Set session cookie
    token = create_access_token(user_id, req.email)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=72 * 3600,
        path="/",
    )

    logger.info("auth.register", user_id=user_id, email=req.email)
    return UserResponse(
        id=user_id,
        email=req.email,
        display_name=req.display_name,
        onboarded=False,
        created_at=user["created_at"],
    )


@router.post("/auth/login", response_model=UserResponse)
async def login(req: LoginRequest, response: Response):
    """Log in with email and password."""
    user = await get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_access_token(user["id"], user["email"])
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=72 * 3600,
        path="/",
    )

    profile = await get_profile(user["id"])
    logger.info("auth.login", user_id=user["id"], email=user["email"])
    return UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        onboarded=bool(profile and profile.get("onboarded")),
        created_at=user["created_at"],
    )


@router.post("/auth/logout")
async def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)):
    """Get the current authenticated user."""
    u = await get_user_by_id(user["user_id"])
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    profile = await get_profile(user["user_id"])
    return UserResponse(
        id=u["id"],
        email=u["email"],
        display_name=u["display_name"],
        onboarded=bool(profile and profile.get("onboarded")),
        created_at=u["created_at"],
    )


# ── Profile endpoints ────────────────────────────────────────────


@router.get("/profile")
async def get_user_profile(user: dict = Depends(get_current_user)):
    """Get the authenticated user's profile."""
    profile = await get_profile(user["user_id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/profile")
async def update_user_profile(
    data: ProfileUpdate, user: dict = Depends(get_current_user)
):
    """Update the authenticated user's profile fields."""
    update_data = data.model_dump(exclude_none=True)
    result = await update_profile(user["user_id"], update_data)
    return result


@router.post("/profile/onboarding/complete")
async def complete_onboarding(
    data: ProfileUpdate, user: dict = Depends(get_current_user)
):
    """Mark onboarding as complete and save final profile data."""
    update_data = data.model_dump(exclude_none=True)
    update_data["onboarded"] = True
    result = await update_profile(user["user_id"], update_data)
    logger.info("auth.onboarding_complete", user_id=user["user_id"])
    return result


# ── User Events (learning data) ──────────────────────────────────


@router.post("/events")
async def create_user_event(
    data: EventCreate, user: dict = Depends(get_current_user)
):
    """Create a learning event for the authenticated user."""
    event_id = uuid.uuid4().hex
    event = await create_event(
        event_id=event_id,
        user_id=user["user_id"],
        concept=data.concept,
        score=data.score,
        time_spent=data.time_spent_minutes,
        event_type=data.event_type,
        notes=data.notes,
        source=data.source,
        timestamp=data.timestamp,
    )
    return event


@router.get("/events")
async def list_user_events(
    limit: int = 100, user: dict = Depends(get_current_user)
):
    """List learning events for the authenticated user."""
    events = await list_events(user["user_id"], limit=limit)
    return {"events": events, "count": len(events)}


# ── File Uploads ──────────────────────────────────────────────────


@router.post("/uploads")
async def upload_file(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
):
    """Upload a file (CSV, PDF, etc.) for the authenticated user."""
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 10 MB.",
        )

    upload_id = uuid.uuid4().hex
    user_dir = Path(UPLOAD_DIR) / user["user_id"]
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / f"{upload_id}_{file.filename}"
    file_path.write_bytes(content)

    record = await create_upload(
        upload_id=upload_id,
        user_id=user["user_id"],
        file_name=file.filename or "unknown",
        file_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        storage_path=str(file_path),
    )
    logger.info("upload.created", user_id=user["user_id"], file=file.filename, size=len(content))
    return record


@router.get("/uploads")
async def list_user_uploads(user: dict = Depends(get_current_user)):
    """List uploaded files for the authenticated user."""
    uploads = await list_uploads(user["user_id"])
    return {"uploads": uploads, "count": len(uploads)}
