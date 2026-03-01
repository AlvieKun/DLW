"""Local TF-IDF retrieval index — lightweight RAG backend.

Implements ``RetrievalIndex`` using in-memory TF-IDF with cosine similarity.
Documents are indexed in memory and optionally persisted to a JSON file on disk
so the index survives restarts without reindexing.

This is the **default** local development backend.  For production, use
``AzureAISearchIndex`` (Phase 9).

Design notes
────────────
• Pure Python — no external vector-store dependency for local dev.
• Uses scikit-learn-style TF-IDF math implemented from scratch to avoid
  adding sklearn as a required dependency.
• Cosine similarity for ranking.
• Metadata filters applied post-ranking (filter-then-rerank).
• Thread-safety not guaranteed (single-process local dev use).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import structlog

from learning_navigator.storage.interfaces import RetrievalIndex

logger = structlog.get_logger(__name__)

# ── Tokeniser ──────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "of", "to", "and", "or",
    "for", "with", "that", "this", "are", "was", "be", "as", "at", "by",
    "from", "not", "but", "has", "have", "had", "do", "does", "did",
    "will", "would", "can", "could", "should", "may", "might",
})


def _tokenise(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, remove stop words."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


# ── TF-IDF engine ─────────────────────────────────────────────────────────


class _TfidfEngine:
    """Minimal TF-IDF engine (no sklearn dependency)."""

    def __init__(self) -> None:
        self._docs: dict[str, list[str]] = {}  # doc_id -> tokens
        self._idf: dict[str, float] = {}
        self._dirty = True  # IDF needs recomputing

    def add(self, doc_id: str, tokens: list[str]) -> None:
        self._docs[doc_id] = tokens
        self._dirty = True

    def remove(self, doc_id: str) -> bool:
        if doc_id in self._docs:
            del self._docs[doc_id]
            self._dirty = True
            return True
        return False

    def _recompute_idf(self) -> None:
        if not self._dirty:
            return
        n = len(self._docs)
        if n == 0:
            self._idf = {}
            self._dirty = False
            return

        df: Counter[str] = Counter()
        for tokens in self._docs.values():
            unique = set(tokens)
            for t in unique:
                df[t] += 1

        self._idf = {
            term: math.log((n + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }
        self._dirty = False

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        """Compute TF-IDF vector for a token list."""
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        vec: dict[str, float] = {}
        for term, count in tf.items():
            tf_val = count / total
            idf_val = self._idf.get(term, 1.0)
            vec[term] = tf_val * idf_val
        return vec

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        if not a or not b:
            return 0.0
        # dot product
        dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in b)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, query_tokens: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        """Return top-k (doc_id, score) pairs sorted by relevance."""
        self._recompute_idf()
        if not self._docs:
            return []

        query_vec = self._tfidf_vector(query_tokens)
        scores: list[tuple[str, float]] = []

        for doc_id, tokens in self._docs.items():
            doc_vec = self._tfidf_vector(tokens)
            sim = self._cosine(query_vec, doc_vec)
            if sim > 0:
                scores.append((doc_id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ── LocalTfidfIndex ────────────────────────────────────────────────────────


class LocalTfidfIndex(RetrievalIndex):
    """TF-IDF based local retrieval index.

    Parameters
    ----------
    data_dir : Path | str | None
        Directory for optional persistence.  If None, operates in-memory only.
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._engine = _TfidfEngine()
        self._metadata: dict[str, dict[str, Any]] = {}
        self._raw_content: dict[str, str] = {}

        self._persist_path: Path | None = None
        if data_dir is not None:
            base = Path(data_dir) / "rag_index"
            base.mkdir(parents=True, exist_ok=True)
            self._persist_path = base / "index.json"
            self._load_from_disk()

        logger.info(
            "local_tfidf_index.init",
            persist=self._persist_path is not None,
            docs=len(self._raw_content),
        )

    # ── RetrievalIndex interface ───────────────────────────────────

    async def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Index (or update) a document."""
        tokens = _tokenise(content)
        self._engine.add(doc_id, tokens)
        self._raw_content[doc_id] = content
        self._metadata[doc_id] = metadata or {}
        self._persist_to_disk()

        logger.debug(
            "local_tfidf_index.indexed",
            doc_id=doc_id,
            tokens=len(tokens),
        )

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search the index and return ranked results.

        Returns a list of dicts, each with:
        - ``doc_id``: document identifier
        - ``score``: cosine similarity score (0-1)
        - ``content``: original document text (or snippet)
        - ``metadata``: user-provided metadata dict
        """
        query_tokens = _tokenise(query)
        if not query_tokens:
            return []

        # Get more than top_k to allow for post-filter
        raw_results = self._engine.search(query_tokens, top_k=top_k * 3)

        results: list[dict[str, Any]] = []
        for doc_id, score in raw_results:
            meta = self._metadata.get(doc_id, {})

            # Apply metadata filters
            if filters and not self._matches_filters(meta, filters):
                continue

            content = self._raw_content.get(doc_id, "")
            # Return a snippet (first 500 chars) for efficiency
            snippet = content[:500] + ("..." if len(content) > 500 else "")

            results.append({
                "doc_id": doc_id,
                "score": round(score, 4),
                "content": snippet,
                "metadata": meta,
            })

            if len(results) >= top_k:
                break

        return results

    async def delete_document(self, doc_id: str) -> bool:
        """Remove a document from the index."""
        removed = self._engine.remove(doc_id)
        self._metadata.pop(doc_id, None)
        self._raw_content.pop(doc_id, None)
        if removed:
            self._persist_to_disk()
        return removed

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _matches_filters(meta: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if metadata matches all filter criteria."""
        for key, value in filters.items():
            if key not in meta:
                return False
            if isinstance(value, list):
                if meta[key] not in value:
                    return False
            elif meta[key] != value:
                return False
        return True

    def _persist_to_disk(self) -> None:
        """Save index state to disk if persistence is enabled."""
        if self._persist_path is None:
            return
        data = {
            doc_id: {
                "content": self._raw_content[doc_id],
                "metadata": self._metadata.get(doc_id, {}),
            }
            for doc_id in self._raw_content
        }
        self._persist_path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_from_disk(self) -> None:
        """Restore index state from disk."""
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for doc_id, entry in raw.items():
                content = entry.get("content", "")
                meta = entry.get("metadata", {})
                tokens = _tokenise(content)
                self._engine.add(doc_id, tokens)
                self._raw_content[doc_id] = content
                self._metadata[doc_id] = meta
            logger.info(
                "local_tfidf_index.loaded",
                docs=len(self._raw_content),
            )
        except Exception:
            logger.exception("local_tfidf_index.load_error")

    @property
    def document_count(self) -> int:
        """Number of documents in the index."""
        return len(self._raw_content)
