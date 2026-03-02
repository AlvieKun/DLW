"""SQLite-backed user database for authentication and profiles.

Tables:
  users        - email, hashed password, timestamps
  user_profiles - onboarding data, learner_profile JSON
  user_uploads  - file upload records
  user_events   - manually logged learning events
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

DB_PATH = os.environ.get("LN_AUTH_DB_PATH", "data/users.db")


def _ensure_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


async def get_db() -> aiosqlite.Connection:
    """Get an async SQLite connection with WAL mode."""
    _ensure_dir(DB_PATH)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    """Create tables if they don't exist."""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                onboarded INTEGER NOT NULL DEFAULT 0,
                learning_goals TEXT DEFAULT '{}',
                subjects TEXT DEFAULT '[]',
                weekly_schedule TEXT DEFAULT '{}',
                preferences TEXT DEFAULT '{}',
                baseline_assessment TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_uploads (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL DEFAULT 'unknown',
                file_size INTEGER NOT NULL DEFAULT 0,
                storage_path TEXT NOT NULL,
                processed_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                concept TEXT NOT NULL DEFAULT '',
                score REAL,
                time_spent_minutes REAL,
                event_type TEXT NOT NULL DEFAULT 'quiz_result',
                notes TEXT DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        await db.commit()
        logger.info("auth_db.init_complete", db_path=DB_PATH)
    finally:
        await db.close()


# ── User CRUD ─────────────────────────────────────────────────────

async def create_user(
    user_id: str, email: str, password_hash: str, display_name: str = ""
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email.lower().strip(), password_hash, display_name, now, now),
        )
        # Create empty profile
        await db.execute(
            "INSERT INTO user_profiles (user_id, onboarded, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (user_id, now, now),
        )
        await db.commit()
        return {"id": user_id, "email": email, "display_name": display_name, "created_at": now}
    finally:
        await db.close()


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, email, password_hash, display_name, created_at FROM users WHERE email = ?",
            (email.lower().strip(),),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        await db.close()


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, email, display_name, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        await db.close()


# ── Profile CRUD ──────────────────────────────────────────────────

async def get_profile(user_id: str) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        # Parse JSON fields
        for field in ("learning_goals", "subjects", "weekly_schedule", "preferences", "baseline_assessment"):
            if isinstance(d.get(field), str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
    finally:
        await db.close()


async def update_profile(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        # Serialize JSON fields
        sets = ["updated_at = ?"]
        vals: list[Any] = [now]
        for field in ("learning_goals", "subjects", "weekly_schedule", "preferences", "baseline_assessment"):
            if field in data:
                sets.append(f"{field} = ?")
                val = data[field]
                vals.append(json.dumps(val) if not isinstance(val, str) else val)
        if "onboarded" in data:
            sets.append("onboarded = ?")
            vals.append(1 if data["onboarded"] else 0)

        vals.append(user_id)
        await db.execute(
            f"UPDATE user_profiles SET {', '.join(sets)} WHERE user_id = ?",
            vals,
        )
        await db.commit()
        return await get_profile(user_id)  # type: ignore
    finally:
        await db.close()


# ── Events CRUD ───────────────────────────────────────────────────

async def create_event(
    event_id: str, user_id: str, concept: str, score: float | None,
    time_spent: float | None, event_type: str, notes: str, source: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    ts = timestamp or now
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO user_events (id, user_id, concept, score, time_spent_minutes,
               event_type, notes, source, timestamp, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, user_id, concept, score, time_spent, event_type, notes, source, ts, now),
        )
        await db.commit()
        return {
            "id": event_id, "user_id": user_id, "concept": concept,
            "score": score, "time_spent_minutes": time_spent,
            "event_type": event_type, "notes": notes, "source": source,
            "timestamp": ts, "created_at": now,
        }
    finally:
        await db.close()


async def list_events(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM user_events WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── Uploads CRUD ──────────────────────────────────────────────────

async def create_upload(
    upload_id: str, user_id: str, file_name: str,
    file_type: str, file_size: int, storage_path: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO user_uploads (id, user_id, file_name, file_type, file_size, storage_path, processed_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (upload_id, user_id, file_name, file_type, file_size, storage_path, now),
        )
        await db.commit()
        return {
            "id": upload_id, "user_id": user_id, "file_name": file_name,
            "file_type": file_type, "file_size": file_size,
            "storage_path": storage_path, "processed_status": "pending",
            "created_at": now,
        }
    finally:
        await db.close()


async def list_uploads(user_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM user_uploads WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
