"""Azure Blob Storage adapters — real implementations behind SDK guard.

These implement the ``MemoryStore`` and ``PortfolioLogger`` interfaces
targeting Azure Blob Storage.  When the ``azure-storage-blob`` SDK is
not installed or connection string is empty, they degrade to no-op
stubs that log warnings.

Container layout
────────────────
- ``states/{learner_id}.json`` — current learner state snapshots
- ``portfolio/{learner_id}.jsonl`` — append-only JSONL portfolio logs

All methods are async-compatible (they wrap synchronous SDK calls with
regular async def so the interface stays uniform).
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

import structlog

from learning_navigator.contracts.learner_state import LearnerState
from learning_navigator.storage.interfaces import (
    MemoryStore,
    PortfolioEntry,
    PortfolioLogger,
)

logger = structlog.get_logger(__name__)

_STUB_MSG = (
    "Azure Blob Storage adapter is in stub mode. "
    "Install azure-storage-blob and configure LN_AZURE_STORAGE_CONNECTION_STRING "
    "to enable."
)


def _try_import_azure() -> bool:
    """Check if the Azure Blob SDK is available."""
    try:
        import azure.storage.blob  # noqa: F401

        return True
    except ImportError:
        return False


def _get_blob_service_client(connection_string: str) -> Any:
    """Create a BlobServiceClient from connection string.

    Returns None if SDK is unavailable.
    """
    try:
        from azure.storage.blob import BlobServiceClient

        return BlobServiceClient.from_connection_string(connection_string)
    except Exception:
        return None


class AzureBlobMemoryStore(MemoryStore):
    """Azure Blob Storage-backed learner state store.

    When the Azure SDK is installed and connection string is provided,
    stores learner state JSON blobs in a container.
    Container layout: ``states/{learner_id}.json``

    Falls back to no-op stub when deps/config are missing.
    """

    def __init__(
        self,
        connection_string: str = "",
        container: str = "learning-navigator",
    ) -> None:
        self._connection_string = connection_string
        self._container = container
        self._available = _try_import_azure() and bool(connection_string)
        self._service_client: Any = None

        if self._available:
            self._service_client = _get_blob_service_client(connection_string)
            if self._service_client is None:
                self._available = False
            else:
                self._ensure_container()
                logger.info(
                    "azure_memory_store.ready",
                    container=container,
                )
        else:
            logger.warning("azure_memory_store.stub_mode", reason=_STUB_MSG)

    @property
    def available(self) -> bool:
        """Whether the Azure SDK is configured and connected."""
        return self._available

    def _ensure_container(self) -> None:
        """Create the container if it doesn't exist."""
        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            if not container_client.exists():
                container_client.create_container()
                logger.info(
                    "azure_memory_store.container_created",
                    container=self._container,
                )
        except Exception as exc:
            logger.warning(
                "azure_memory_store.container_ensure_failed",
                error=str(exc),
            )

    def _blob_path(self, learner_id: str) -> str:
        return f"states/{learner_id}.json"

    async def get_learner_state(self, learner_id: str) -> LearnerState | None:
        if not self._available:
            logger.debug("azure_memory_store.stub.get", learner_id=learner_id)
            return None

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            blob_client = container_client.get_blob_client(
                self._blob_path(learner_id),
            )
            data = blob_client.download_blob().readall()
            logger.debug(
                "azure_memory_store.get",
                learner_id=learner_id,
                size=len(data),
            )
            return LearnerState.model_validate_json(data)
        except Exception as exc:
            error_type = type(exc).__name__
            if "NotFound" in error_type or "ResourceNotFoundError" in str(type(exc)):
                logger.debug(
                    "azure_memory_store.not_found",
                    learner_id=learner_id,
                )
                return None
            logger.error(
                "azure_memory_store.get_failed",
                learner_id=learner_id,
                error=str(exc),
            )
            return None

    async def save_learner_state(self, state: LearnerState) -> None:
        if not self._available:
            logger.debug(
                "azure_memory_store.stub.save",
                learner_id=state.learner_id,
            )
            return

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            blob_client = container_client.get_blob_client(
                self._blob_path(state.learner_id),
            )
            blob_client.upload_blob(
                state.model_dump_json(indent=2),
                overwrite=True,
            )
            logger.debug(
                "azure_memory_store.saved",
                learner_id=state.learner_id,
            )
        except Exception as exc:
            logger.error(
                "azure_memory_store.save_failed",
                learner_id=state.learner_id,
                error=str(exc),
            )

    async def delete_learner_state(self, learner_id: str) -> bool:
        if not self._available:
            logger.debug(
                "azure_memory_store.stub.delete",
                learner_id=learner_id,
            )
            return False

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            blob_client = container_client.get_blob_client(
                self._blob_path(learner_id),
            )
            blob_client.delete_blob()
            logger.debug(
                "azure_memory_store.deleted",
                learner_id=learner_id,
            )
            return True
        except Exception as exc:
            logger.warning(
                "azure_memory_store.delete_failed",
                learner_id=learner_id,
                error=str(exc),
            )
            return False

    async def list_learner_ids(self) -> list[str]:
        if not self._available:
            return []

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            ids: list[str] = []
            for blob in container_client.list_blobs(name_starts_with="states/"):
                name = blob.name  # "states/learner-1.json"
                learner_id = name.removeprefix("states/").removesuffix(".json")
                ids.append(learner_id)
            return ids
        except Exception as exc:
            logger.error(
                "azure_memory_store.list_failed",
                error=str(exc),
            )
            return []


class AzureBlobPortfolioLogger(PortfolioLogger):
    """Azure Blob Storage-backed portfolio logger.

    Stores portfolio entries as JSONL blobs (one line per entry).
    Container layout: ``portfolio/{learner_id}.jsonl``

    Uses block blob with download-append-upload pattern since Azure
    append blobs have size limits for large histories.
    """

    def __init__(
        self,
        connection_string: str = "",
        container: str = "learning-navigator",
    ) -> None:
        self._connection_string = connection_string
        self._container = container
        self._available = _try_import_azure() and bool(connection_string)
        self._service_client: Any = None

        if self._available:
            self._service_client = _get_blob_service_client(connection_string)
            if self._service_client is None:
                self._available = False
            else:
                self._ensure_container()
                logger.info(
                    "azure_portfolio_logger.ready",
                    container=container,
                )
        else:
            logger.warning("azure_portfolio_logger.stub_mode", reason=_STUB_MSG)

    @property
    def available(self) -> bool:
        """Whether the Azure SDK is configured and connected."""
        return self._available

    def _ensure_container(self) -> None:
        """Create the container if it doesn't exist."""
        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            if not container_client.exists():
                container_client.create_container()
        except Exception:
            pass  # Best-effort

    def _blob_path(self, learner_id: str) -> str:
        return f"portfolio/{learner_id}.jsonl"

    async def append(self, entry: PortfolioEntry) -> None:
        if not self._available:
            logger.debug(
                "azure_portfolio_logger.stub.append",
                learner_id=entry.learner_id,
            )
            return

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            blob_client = container_client.get_blob_client(
                self._blob_path(entry.learner_id),
            )

            # Read existing content (if any)
            existing = b""
            with contextlib.suppress(Exception):
                existing = blob_client.download_blob().readall()

            line = entry.model_dump_json() + "\n"
            new_content = existing + line.encode("utf-8")
            blob_client.upload_blob(new_content, overwrite=True)

            logger.debug(
                "azure_portfolio_logger.appended",
                learner_id=entry.learner_id,
                entry_type=entry.entry_type,
            )
        except Exception as exc:
            logger.error(
                "azure_portfolio_logger.append_failed",
                learner_id=entry.learner_id,
                error=str(exc),
            )

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

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            blob_client = container_client.get_blob_client(
                self._blob_path(learner_id),
            )
            data = blob_client.download_blob().readall().decode("utf-8")

            entries: list[PortfolioEntry] = []
            for line in data.strip().split("\n"):
                if not line.strip():
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
        except Exception:
            return []

    async def count(self, learner_id: str) -> int:
        if not self._available:
            return 0

        try:
            container_client = self._service_client.get_container_client(
                self._container,
            )
            blob_client = container_client.get_blob_client(
                self._blob_path(learner_id),
            )
            data = blob_client.download_blob().readall().decode("utf-8")
            return len([ln for ln in data.strip().split("\n") if ln.strip()])
        except Exception:
            return 0
