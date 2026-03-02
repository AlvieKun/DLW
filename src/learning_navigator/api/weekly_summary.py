"""Weekly AI Summary — LLM-powered reflective summaries via Azure OpenAI.

Generates a weekly progress summary for each user, grounded in their
portfolio entries, events, and learner state. If Azure OpenAI is not
configured, the service degrades gracefully.

Responsible AI:
- No sensitive inference (demographics, disability, etc.)
- No shaming language
- Grounded in observed data only
- Disclaimers always included
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from learning_navigator.llm import get_llm_client

logger = structlog.get_logger(__name__)

# ── Storage ────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS user_weekly_summaries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    highlights TEXT NOT NULL DEFAULT '[]',
    focus_items TEXT NOT NULL DEFAULT '[]',
    burnout_flag INTEGER NOT NULL DEFAULT 0,
    evidence_bullets TEXT NOT NULL DEFAULT '[]',
    model_used TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'generated',
    disclaimer TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, week_start)
);
"""


async def _ensure_table(db) -> None:  # type: ignore[no-untyped-def]
    """Create the weekly summaries table if it doesn't exist."""
    await db.executescript(_CREATE_TABLE)
    await db.commit()


async def get_latest_summary(db, user_id: str) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    """Get the most recent weekly summary for a user."""
    await _ensure_table(db)
    cursor = await db.execute(
        "SELECT * FROM user_weekly_summaries WHERE user_id = ? ORDER BY week_start DESC LIMIT 1",
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


async def save_summary(db, summary: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    """Save a weekly summary, replacing any existing one for the same week."""
    await _ensure_table(db)
    await db.execute(
        """INSERT OR REPLACE INTO user_weekly_summaries
           (id, user_id, week_start, week_end, summary_text, highlights,
            focus_items, burnout_flag, evidence_bullets, model_used, status, disclaimer, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            summary["id"],
            summary["user_id"],
            summary["week_start"],
            summary["week_end"],
            summary["summary_text"],
            json.dumps(summary.get("highlights", [])),
            json.dumps(summary.get("focus_items", [])),
            1 if summary.get("burnout_flag") else 0,
            json.dumps(summary.get("evidence_bullets", [])),
            summary.get("model_used", ""),
            summary.get("status", "generated"),
            summary.get("disclaimer", ""),
            summary["created_at"],
        ),
    )
    await db.commit()


def _row_to_dict(row) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Convert a sqlite Row to a dict, parsing JSON fields."""
    d = dict(row)
    for json_field in ("highlights", "focus_items", "evidence_bullets"):
        if json_field in d and isinstance(d[json_field], str):
            try:
                d[json_field] = json.loads(d[json_field])
            except (json.JSONDecodeError, TypeError):
                d[json_field] = []
    d["burnout_flag"] = bool(d.get("burnout_flag", 0))
    return d


# ── Summary generation ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a supportive learning coach writing a weekly progress summary for a student.

Rules:
- Ground every observation in the provided data. Never invent facts.
- Be encouraging but honest. Do not shame the student.
- Do not infer demographics, disability, or sensitive characteristics.
- Use plain English, no jargon.
- Format your response as a JSON object with these fields:
  {
    "summary_text": "2-3 paragraph reflective summary",
    "highlights": ["strength 1", "strength 2"],
    "focus_items": ["suggestion 1", "suggestion 2", "suggestion 3"],
    "burnout_flag": false,
    "evidence_bullets": ["bullet 1 referencing data", "bullet 2"]
  }
- Keep highlights to 2-4 items, focus_items to 1-3 items.
- If the student seems to be overworking, set burnout_flag to true and mention it gently.
- evidence_bullets should reference specific data points (e.g., "Practiced Algebra 3 times this week").
"""


def _build_user_prompt(
    events: list[dict[str, Any]],
    portfolio_entries: list[dict[str, Any]],
    learner_state: dict[str, Any] | None,
    week_start: str,
    week_end: str,
) -> str:
    """Build the user prompt from real data."""
    parts = [f"Weekly summary for {week_start} to {week_end}.\n"]

    # Events summary
    if events:
        parts.append(f"## Learning Events ({len(events)} this week)")
        for ev in events[:30]:  # Cap to avoid token overflow
            concept = ev.get("concept", "general")
            etype = ev.get("event_type", "activity")
            score = ev.get("score")
            time_spent = ev.get("time_spent_minutes")
            line = f"- {etype}: {concept}"
            if score is not None:
                line += f" (score: {score})"
            if time_spent is not None:
                line += f" ({time_spent} min)"
            parts.append(line)
    else:
        parts.append("## Learning Events\nNo events recorded this week.")

    # Portfolio entries
    if portfolio_entries:
        parts.append(f"\n## Portfolio Entries ({len(portfolio_entries)} this week)")
        for entry in portfolio_entries[:20]:
            etype = entry.get("entry_type", "unknown")
            data = entry.get("data", {})
            if isinstance(data, dict):
                action = data.get("recommended_action", "")
                conf = data.get("confidence", "")
                parts.append(f"- {etype}: {action} (conf: {conf})" if action else f"- {etype}")
            else:
                parts.append(f"- {etype}")
    else:
        parts.append("\n## Portfolio\nNo portfolio entries this week.")

    # Learner state snapshot
    if learner_state:
        concepts = learner_state.get("concepts", {})
        if concepts:
            parts.append(f"\n## Current Knowledge State ({len(concepts)} topics)")
            for cid, cstate in list(concepts.items())[:15]:
                mastery = cstate.get("bkt", {}).get("p_know", 0)
                forgetting = cstate.get("forgetting_score", 0)
                name = cstate.get("display_name", cid)
                parts.append(f"- {name}: mastery {mastery:.0%}, forgetting risk {forgetting:.0%}")

        motivation = learner_state.get("motivation", {})
        if motivation:
            parts.append(f"\n## Motivation: {motivation.get('level', 'unknown')} (score: {motivation.get('score', 0):.2f}, trend: {motivation.get('trend', 0):.2f})")

        sessions = learner_state.get("session_count", 0)
        parts.append(f"\n## Total sessions: {sessions}")

    return "\n".join(parts)


async def generate_weekly_summary(
    db,  # type: ignore[no-untyped-def]
    user_id: str,
    events: list[dict[str, Any]],
    portfolio_entries: list[dict[str, Any]],
    learner_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a weekly summary using Azure OpenAI.

    Returns a summary dict. If LLM is unavailable, returns a status='unavailable' entry.
    """
    llm = get_llm_client()
    now = datetime.now(timezone.utc)
    week_end = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # Check if LLM is available
    if not llm.enabled:
        return {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "week_start": week_start,
            "week_end": week_end,
            "status": "unavailable",
            "summary_text": "",
            "highlights": [],
            "focus_items": [],
            "burnout_flag": False,
            "evidence_bullets": [],
            "model_used": "",
            "disclaimer": "",
            "message": "Weekly AI summary requires Azure OpenAI configuration. "
                       "Set LN_AZURE_OPENAI_ENDPOINT, LN_AZURE_OPENAI_API_KEY, and "
                       "LN_AZURE_OPENAI_DEPLOYMENT environment variables.",
            "created_at": now.isoformat(),
        }

    # Build prompt from real data
    user_prompt = _build_user_prompt(events, portfolio_entries, learner_state, week_start, week_end)

    logger.info("weekly_summary.generating", user_id=user_id, week_start=week_start)

    response = await llm.chat(
        prompt=user_prompt,
        system=SYSTEM_PROMPT,
        temperature=0.5,
        max_tokens=800,
        json_mode=True,
    )

    if response is None:
        logger.warning("weekly_summary.llm_failed", user_id=user_id)
        return {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "week_start": week_start,
            "week_end": week_end,
            "status": "error",
            "summary_text": "Unable to generate summary at this time.",
            "highlights": [],
            "focus_items": [],
            "burnout_flag": False,
            "evidence_bullets": [],
            "model_used": "",
            "disclaimer": "",
            "message": "LLM call failed. Please try again later.",
            "created_at": now.isoformat(),
        }

    # Parse JSON response from LLM
    try:
        parsed = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        # Fallback: use raw content as summary text
        parsed = {
            "summary_text": response.content,
            "highlights": [],
            "focus_items": [],
            "burnout_flag": False,
            "evidence_bullets": [],
        }

    disclaimer = (
        "This summary was generated by AI based on your recorded learning data. "
        "It may not capture everything and should be used as a reflection aid, not a definitive assessment."
    )

    summary = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "week_start": week_start,
        "week_end": week_end,
        "summary_text": parsed.get("summary_text", ""),
        "highlights": parsed.get("highlights", [])[:4],
        "focus_items": parsed.get("focus_items", [])[:3],
        "burnout_flag": bool(parsed.get("burnout_flag", False)),
        "evidence_bullets": parsed.get("evidence_bullets", [])[:6],
        "model_used": response.model,
        "status": "generated",
        "disclaimer": disclaimer,
        "created_at": now.isoformat(),
    }

    # Persist to DB
    await save_summary(db, summary)

    logger.info(
        "weekly_summary.generated",
        user_id=user_id,
        model=response.model,
        tokens=response.usage.get("total_tokens", 0),
    )

    return summary
