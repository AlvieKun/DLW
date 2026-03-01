"""Storage adapters — factory functions for backend selection.

Usage::

    from learning_navigator.storage import (
        create_memory_store,
        create_portfolio_logger,
        create_retrieval_index,
    )
    store = create_memory_store(settings)
    portfolio = create_portfolio_logger(settings)
    index = create_retrieval_index(settings)
"""

from __future__ import annotations

from learning_navigator.infra.config import SearchBackend, Settings, StorageBackend
from learning_navigator.storage.interfaces import (
    MemoryStore,
    PortfolioLogger,
    RetrievalIndex,
)


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


def create_retrieval_index(settings: Settings) -> RetrievalIndex:
    """Instantiate the configured RetrievalIndex backend."""
    if settings.search_backend == SearchBackend.AZURE_AI_SEARCH:
        from learning_navigator.storage.azure_search import AzureAISearchIndex

        return AzureAISearchIndex(
            endpoint=settings.azure_search_endpoint,
            api_key=settings.azure_search_key,
            index_name=settings.azure_search_index,
        )
    # Default: local TF-IDF
    from learning_navigator.storage.local_tfidf import LocalTfidfIndex

    return LocalTfidfIndex(data_dir=settings.local_data_dir)
