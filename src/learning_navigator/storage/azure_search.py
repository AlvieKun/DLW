"""Azure AI Search adapter stub.

Implements ``RetrievalIndex`` targeting Azure AI Search (formerly Cognitive
Search).  In v1 this is a **stub** that gracefully degrades when the
``azure-search-documents`` SDK is not installed.

The interface is fully wired so that:
• Integration tests can mock at this boundary.
• Switching to production Azure Search is a config change, not a code change.

TODO(phase9): Implement real Azure AI Search calls.
"""

from __future__ import annotations

from typing import Any

import structlog

from learning_navigator.storage.interfaces import RetrievalIndex

logger = structlog.get_logger(__name__)

_STUB_MSG = (
    "Azure AI Search adapter is a stub. Install azure-search-documents "
    "and configure LN_AZURE_SEARCH_ENDPOINT + LN_AZURE_SEARCH_KEY to enable."
)


def _try_import_azure_search() -> bool:
    """Check if the Azure Search SDK is available."""
    try:
        import azure.search.documents  # noqa: F401

        return True
    except ImportError:
        return False


class AzureAISearchIndex(RetrievalIndex):
    """Azure AI Search backed retrieval index (stub).

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
        if not self._available:
            logger.warning("azure_search_index.stub_mode", reason=_STUB_MSG)

    async def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._available:
            logger.debug("azure_search_index.stub.index", doc_id=doc_id)
            return
        # TODO(phase9): Real implementation
        # from azure.search.documents import SearchClient
        # from azure.core.credentials import AzureKeyCredential
        # client = SearchClient(
        #     endpoint=self._endpoint,
        #     index_name=self._index_name,
        #     credential=AzureKeyCredential(self._api_key),
        # )
        # client.upload_documents([{
        #     "id": doc_id,
        #     "content": content,
        #     **(metadata or {}),
        # }])

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
        # TODO(phase9): Real implementation
        # client = SearchClient(...)
        # results = client.search(query, top=top_k, filter=odata_filter)
        # return [{"doc_id": r["id"], "score": r["@search.score"], ...} for r in results]
        return []

    async def delete_document(self, doc_id: str) -> bool:
        if not self._available:
            logger.debug("azure_search_index.stub.delete", doc_id=doc_id)
            return False
        # TODO(phase9): Real implementation
        return False
