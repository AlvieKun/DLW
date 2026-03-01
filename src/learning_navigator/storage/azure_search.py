"""Azure AI Search adapter — real implementation behind SDK guard.

Implements ``RetrievalIndex`` targeting Azure AI Search (formerly Cognitive
Search).  When the ``azure-search-documents`` SDK is not installed or
credentials are empty, degrades to a no-op stub that logs warnings.

The interface contract is identical to ``LocalTfidfIndex``, ensuring
switching backends is a config change, not a code change.

Index schema
────────────
The adapter assumes an index with at least these fields:
- ``id`` (string, key) — document ID
- ``content`` (string, searchable) — full document text
- ``metadata`` (string) — JSON-encoded metadata blob

Additional filterable fields can be added to the index definition
and used via the ``filters`` parameter.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import structlog

from learning_navigator.storage.interfaces import RetrievalIndex

logger = structlog.get_logger(__name__)

_STUB_MSG = (
    "Azure AI Search adapter is in stub mode. Install azure-search-documents "
    "and configure LN_AZURE_SEARCH_ENDPOINT + LN_AZURE_SEARCH_KEY to enable."
)


def _try_import_azure_search() -> bool:
    """Check if the Azure Search SDK is available."""
    try:
        import azure.search.documents  # noqa: F401

        return True
    except ImportError:
        return False


def _get_search_client(
    endpoint: str, api_key: str, index_name: str,
) -> Any:
    """Create an Azure SearchClient.  Returns None on failure."""
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient

        return SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(api_key),
        )
    except Exception:
        return None


def _get_index_client(endpoint: str, api_key: str) -> Any:
    """Create an Azure SearchIndexClient (admin).  Returns None on failure."""
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexClient

        return SearchIndexClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )
    except Exception:
        return None


class AzureAISearchIndex(RetrievalIndex):
    """Azure AI Search backed retrieval index.

    Parameters
    ----------
    endpoint : str
        Azure Search service endpoint URL.
    api_key : str
        Azure Search admin or query key.
    index_name : str
        Name of the search index.
    """

    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        index_name: str = "learning-navigator-index",
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._index_name = index_name
        self._available = (
            _try_import_azure_search()
            and bool(endpoint)
            and bool(api_key)
        )
        self._search_client: Any = None
        self._index_client: Any = None

        if self._available:
            self._search_client = _get_search_client(
                endpoint, api_key, index_name,
            )
            self._index_client = _get_index_client(endpoint, api_key)
            if self._search_client is None:
                self._available = False
            else:
                self._ensure_index()
                logger.info(
                    "azure_search_index.ready",
                    endpoint=endpoint,
                    index_name=index_name,
                )
        else:
            logger.warning("azure_search_index.stub_mode", reason=_STUB_MSG)

    @property
    def available(self) -> bool:
        """Whether the Azure Search SDK is configured and connected."""
        return self._available

    def _ensure_index(self) -> None:
        """Create the search index if it doesn't exist (best-effort)."""
        if self._index_client is None:
            return
        try:
            from azure.search.documents.indexes.models import (
                SearchableField,
                SearchFieldDataType,
                SearchIndex,
                SimpleField,
            )

            fields = [
                SimpleField(
                    name="id",
                    type=SearchFieldDataType.String,
                    key=True,
                    filterable=True,
                ),
                SearchableField(
                    name="content",
                    type=SearchFieldDataType.String,
                ),
                SimpleField(
                    name="metadata",
                    type=SearchFieldDataType.String,
                    filterable=False,
                ),
            ]
            index = SearchIndex(name=self._index_name, fields=fields)
            self._index_client.create_or_update_index(index)
            logger.info(
                "azure_search_index.index_ensured",
                index_name=self._index_name,
            )
        except Exception as exc:
            logger.warning(
                "azure_search_index.ensure_failed",
                error=str(exc),
            )

    async def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._available:
            logger.debug("azure_search_index.stub.index", doc_id=doc_id)
            return

        try:
            document = {
                "id": doc_id,
                "content": content,
                "metadata": json.dumps(metadata or {}),
            }
            self._search_client.upload_documents([document])
            logger.debug(
                "azure_search_index.indexed",
                doc_id=doc_id,
                content_len=len(content),
            )
        except Exception as exc:
            logger.error(
                "azure_search_index.index_failed",
                doc_id=doc_id,
                error=str(exc),
            )

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._available:
            logger.debug("azure_search_index.stub.search", query=query[:50])
            return []

        try:
            # Build OData filter if provided
            odata_filter: str | None = None
            if filters:
                clauses = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        clauses.append(f"{key} eq '{value}'")
                    else:
                        clauses.append(f"{key} eq {value}")
                odata_filter = " and ".join(clauses)

            results = self._search_client.search(
                search_text=query,
                top=top_k,
                filter=odata_filter,
            )

            hits: list[dict[str, Any]] = []
            for result in results:
                meta = {}
                raw_meta = result.get("metadata", "{}")
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    meta = json.loads(raw_meta) if raw_meta else {}

                hits.append({
                    "doc_id": result["id"],
                    "score": result.get("@search.score", 0.0),
                    "content": result.get("content", ""),
                    **meta,
                })

            logger.debug(
                "azure_search_index.search",
                query=query[:50],
                hits=len(hits),
            )
            return hits
        except Exception as exc:
            logger.error(
                "azure_search_index.search_failed",
                query=query[:50],
                error=str(exc),
            )
            return []

    async def delete_document(self, doc_id: str) -> bool:
        if not self._available:
            logger.debug("azure_search_index.stub.delete", doc_id=doc_id)
            return False

        try:
            self._search_client.delete_documents([{"id": doc_id}])
            logger.debug(
                "azure_search_index.deleted",
                doc_id=doc_id,
            )
            return True
        except Exception as exc:
            logger.warning(
                "azure_search_index.delete_failed",
                doc_id=doc_id,
                error=str(exc),
            )
            return False
