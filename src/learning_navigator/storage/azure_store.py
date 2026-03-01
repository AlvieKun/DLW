"""Azure Blob Storage adapter stubs.

These implement the same MemoryStore and PortfolioLogger interfaces but
target Azure Blob Storage.  In v1 they are **stubs** that raise or fall
back gracefully when the Azure SDK is not installed.

The interface is fully defined so that:
• Integration tests can mock at this boundary.
• Moving to production Azure is a config change, not a code change.
• The adapter is isolated — no Azure imports leak into core logic.

TODO(phase9): Implement real Azure Blob calls with azure-storage-blob SDK.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from learning_navigator.contracts.learner_state import LearnerState
from learning_navigator.storage.interfaces import (
    MemoryStore,
    PortfolioEntry,
    PortfolioLogger,
)

logger = structlog.get_logger(__name__)

_STUB_MSG = (
    "Azure Blob Storage adapter is a stub. "
    "Install azure-storage-blob and configure LN_AZURE_STORAGE_CONNECTION_STRING "
    "to enable. Falling back to no-op."
)


def _try_import_azure() -> bool:
    """Check if the Azure Blob SDK is available."""
    try:
        import azure.storage.blob  # noqa: F401

        return True
    except ImportError:
        return False


class AzureBlobMemoryStore(MemoryStore):
    """Azure Blob Storage-backed learner state store (stub).

    When the Azure SDK is installed and connection string is provided,
    this will store learner state JSON blobs in a container.
    Container layout: ``states/{learner_id}.json``
    """

    def __init__(self, connection_string: str = "", container: str = "learning-navigator") -> None:
        self._connection_string = connection_string
        self._container = container
        self._available = _try_import_azure() and bool(connection_string)
        if not self._available:
            logger.warning("azure_memory_store.stub_mode", reason=_STUB_MSG)

    async def get_learner_state(self, learner_id: str) -> LearnerState | None:
        if not self._available:
            logger.debug("azure_memory_store.stub.get", learner_id=learner_id)
            return None
        # TODO(phase9): Real implementation
        # blob_client = BlobServiceClient.from_connection_string(self._connection_string)
        # container_client = blob_client.get_container_client(self._container)
        # blob = container_client.get_blob_client(f"states/{learner_id}.json")
        # data = blob.download_blob().readall()
        # return LearnerState.model_validate_json(data)
        return None

    async def save_learner_state(self, state: LearnerState) -> None:
        if not self._available:
            logger.debug("azure_memory_store.stub.save", learner_id=state.learner_id)
            return
        # TODO(phase9): Real implementation
        # blob_client = ...
        # blob.upload_blob(state.model_dump_json(), overwrite=True)

    async def delete_learner_state(self, learner_id: str) -> bool:
        if not self._available:
            logger.debug("azure_memory_store.stub.delete", learner_id=learner_id)
            return False
        # TODO(phase9): Real implementation
        return False

    async def list_learner_ids(self) -> list[str]:
        if not self._available:
            return []
        # TODO(phase9): list blobs with prefix "states/"
        return []


class AzureBlobPortfolioLogger(PortfolioLogger):
    """Azure Blob Storage-backed portfolio logger (stub).

    Stores portfolio entries as append blobs or JSONL blobs.
    Container layout: ``portfolio/{learner_id}.jsonl``
    """

    def __init__(self, connection_string: str = "", container: str = "learning-navigator") -> None:
        self._connection_string = connection_string
        self._container = container
        self._available = _try_import_azure() and bool(connection_string)
        if not self._available:
            logger.warning("azure_portfolio_logger.stub_mode", reason=_STUB_MSG)

    async def append(self, entry: PortfolioEntry) -> None:
        if not self._available:
            logger.debug("azure_portfolio_logger.stub.append", learner_id=entry.learner_id)
            return
        # TODO(phase9): append blob implementation

    async def get_entries(
        self,
        learner_id: str,
        *,
        entry_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[PortfolioEntry]:
        if not self._available:
            return []
        # TODO(phase9): download + filter
        return []

    async def count(self, learner_id: str) -> int:
        if not self._available:
            return 0
        # TODO(phase9): line count from blob
        return 0
