"""Local filesystem storage implementations.

These are the *default* backends for development and single-machine
deployment.  They store data as JSON files on disk.

Design notes
────────────
• Async interfaces are satisfied with synchronous file I/O wrapped in
  the async contract — acceptable for local dev.  For production scale,
  use Azure adapters.
• Learner states are stored as individual JSON files: ``{data_dir}/states/{learner_id}.json``
• Portfolio entries are appended to JSONL files: ``{data_dir}/portfolio/{learner_id}.jsonl``
• Thread-safety is not guaranteed — single-process use only.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import structlog

from learning_navigator.contracts.learner_state import LearnerState
from learning_navigator.storage.interfaces import (
    MemoryStore,
    PortfolioEntry,
    PortfolioLogger,
)

logger = structlog.get_logger(__name__)


class LocalJsonMemoryStore(MemoryStore):
    """Persists LearnerState as individual JSON files on disk."""

    def __init__(self, data_dir: Path | str = "data") -> None:
        self._base = Path(data_dir) / "states"
        self._base.mkdir(parents=True, exist_ok=True)
        logger.info("local_memory_store.init", path=str(self._base))

    def _path_for(self, learner_id: str) -> Path:
        # Sanitise ID to safe filename
        safe_id = learner_id.replace("/", "_").replace("\\", "_")
        return self._base / f"{safe_id}.json"

    async def get_learner_state(self, learner_id: str) -> LearnerState | None:
        path = self._path_for(learner_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return LearnerState.model_validate_json(raw)
        except Exception:
            logger.exception("local_memory_store.read_error", learner_id=learner_id)
            return None

    async def save_learner_state(self, state: LearnerState) -> None:
        path = self._path_for(state.learner_id)
        json_str = state.model_dump_json(indent=2)
        path.write_text(json_str, encoding="utf-8")
        logger.debug("local_memory_store.saved", learner_id=state.learner_id)

    async def delete_learner_state(self, learner_id: str) -> bool:
        path = self._path_for(learner_id)
        if path.exists():
            path.unlink()
            logger.debug("local_memory_store.deleted", learner_id=learner_id)
            return True
        return False

    async def list_learner_ids(self) -> list[str]:
        return [p.stem for p in self._base.glob("*.json")]


class LocalJsonPortfolioLogger(PortfolioLogger):
    """Append-only JSONL portfolio log stored on local filesystem."""

    def __init__(self, data_dir: Path | str = "data") -> None:
        self._base = Path(data_dir) / "portfolio"
        self._base.mkdir(parents=True, exist_ok=True)
        logger.info("local_portfolio_logger.init", path=str(self._base))

    def _path_for(self, learner_id: str) -> Path:
        safe_id = learner_id.replace("/", "_").replace("\\", "_")
        return self._base / f"{safe_id}.jsonl"

    async def append(self, entry: PortfolioEntry) -> None:
        path = self._path_for(entry.learner_id)
        line = entry.model_dump_json() + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        logger.debug(
            "local_portfolio_logger.appended",
            learner_id=entry.learner_id,
            entry_type=entry.entry_type,
        )

    async def get_entries(
        self,
        learner_id: str,
        *,
        entry_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[PortfolioEntry]:
        path = self._path_for(learner_id)
        if not path.exists():
            return []

        entries: list[PortfolioEntry] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = PortfolioEntry.model_validate_json(line)
                if entry_type and entry.entry_type != entry_type:
                    continue
                if since and entry.timestamp < since:
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    break
        return entries

    async def count(self, learner_id: str) -> int:
        path = self._path_for(learner_id)
        if not path.exists():
            return 0
        with open(path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
