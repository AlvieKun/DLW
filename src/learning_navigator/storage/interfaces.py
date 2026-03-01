"""Storage interfaces — abstract contracts for persistence.

All persistence in Learning Navigator flows through these interfaces.
Concrete implementations live in separate modules (local_store, azure_store).

Design rationale
────────────────
• Interfaces use ``abc.ABC`` so mypy enforces implementation.
• Methods are async — even if local impls are synchronous, this keeps the
  contract compatible with I/O-bound Azure SDK calls.
• ``MemoryStore`` handles learner state (current snapshot).
• ``PortfolioLogger`` handles append-only audit/history records.
• ``RetrievalIndex`` is the RAG vector store abstraction (Phase 7).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from learning_navigator.contracts.learner_state import LearnerState

# ── Portfolio log entry ────────────────────────────────────────────────────

class PortfolioEntry(BaseModel):
    """A single immutable record in the learner's portfolio log.

    Portfolio entries capture *what happened and why* — recommendations,
    overrides, state snapshots, replay artifacts, etc.
    """

    entry_id: str
    learner_id: str
    entry_type: str  # e.g., "recommendation", "state_snapshot", "override", "replay_artifact"
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)
    source_agent_id: str = "system"
    correlation_id: str = ""
    tags: list[str] = Field(default_factory=list)


# ── MemoryStore ────────────────────────────────────────────────────────────

class MemoryStore(ABC):
    """Persistence interface for current learner state.

    Implementations:
    • ``LocalJsonMemoryStore`` — JSON files on disk (dev / local).
    • ``AzureBlobMemoryStore`` — Azure Blob Storage (production stub).
    """

    @abstractmethod
    async def get_learner_state(self, learner_id: str) -> LearnerState | None:
        """Retrieve the latest state for a learner, or None if not found."""
        ...

    @abstractmethod
    async def save_learner_state(self, state: LearnerState) -> None:
        """Persist the learner state (upsert by learner_id)."""
        ...

    @abstractmethod
    async def delete_learner_state(self, learner_id: str) -> bool:
        """Delete a learner's state.  Returns True if it existed."""
        ...

    @abstractmethod
    async def list_learner_ids(self) -> list[str]:
        """Return all known learner IDs."""
        ...


# ── PortfolioLogger ────────────────────────────────────────────────────────

class PortfolioLogger(ABC):
    """Append-only audit log for learner portfolios.

    Every recommendation, override, state change, and replay artifact is
    recorded here for:
    • Teacher verification (HITL).
    • Explainability / provenance.
    • Evaluation harness replay.
    """

    @abstractmethod
    async def append(self, entry: PortfolioEntry) -> None:
        """Append an entry to the portfolio."""
        ...

    @abstractmethod
    async def get_entries(
        self,
        learner_id: str,
        *,
        entry_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[PortfolioEntry]:
        """Retrieve portfolio entries with optional filters."""
        ...

    @abstractmethod
    async def count(self, learner_id: str) -> int:
        """Count total entries for a learner."""
        ...


# ── RetrievalIndex (RAG store) ─────────────────────────────────────────────

class RetrievalIndex(ABC):
    """Vector / keyword index for RAG retrieval.

    Concrete implementations:
    • ``LocalTfidfIndex`` — TF-IDF baseline (Phase 7).
    • ``AzureAISearchIndex`` — Azure AI Search (Phase 9).
    """

    @abstractmethod
    async def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or update a document in the index."""
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search the index and return ranked results."""
        ...

    @abstractmethod
    async def delete_document(self, doc_id: str) -> bool:
        """Remove a document from the index."""
        ...
