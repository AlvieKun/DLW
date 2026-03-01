"""Storage adapters — factory functions for backend selection.

Usage::

    from learning_navigator.storage import create_memory_store, create_portfolio_logger
    store = create_memory_store(settings)
    portfolio = create_portfolio_logger(settings)
"""

from __future__ import annotations

from learning_navigator.infra.config import Settings, StorageBackend
from learning_navigator.storage.interfaces import MemoryStore, PortfolioLogger


def create_memory_store(settings: Settings) -> MemoryStore:
    """Instantiate the configured MemoryStore backend."""
    if settings.storage_backend == StorageBackend.AZURE_BLOB:
        from learning_navigator.storage.azure_store import AzureBlobMemoryStore

        return AzureBlobMemoryStore(
            connection_string=settings.azure_storage_connection_string,
            container=settings.azure_storage_container,
        )
    # Default: local JSON
    from learning_navigator.storage.local_store import LocalJsonMemoryStore

    return LocalJsonMemoryStore(data_dir=settings.local_data_dir)


def create_portfolio_logger(settings: Settings) -> PortfolioLogger:
    """Instantiate the configured PortfolioLogger backend."""
    if settings.storage_backend == StorageBackend.AZURE_BLOB:
        from learning_navigator.storage.azure_store import AzureBlobPortfolioLogger

        return AzureBlobPortfolioLogger(
            connection_string=settings.azure_storage_connection_string,
            container=settings.azure_storage_container,
        )
    from learning_navigator.storage.local_store import LocalJsonPortfolioLogger

    return LocalJsonPortfolioLogger(data_dir=settings.local_data_dir)
