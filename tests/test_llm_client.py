"""Tests for the LLM client module (Phase 2).

Tests cover:
1. Disabled client when config is missing
2. Client instantiation with mock config
3. Graceful fallback when LLM is unavailable
4. Chat method returns None when disabled
5. Singleton pattern
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning_navigator.infra.config import Settings
from learning_navigator.llm.azure_client import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    get_llm_client,
    reset_llm_client,
)


# ── Fixtures ───────────────────────────────────────────────────────


def _disabled_settings() -> Settings:
    """Settings with no Azure OpenAI config → client disabled."""
    return Settings(
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
    )


def _enabled_settings() -> Settings:
    """Settings with Azure OpenAI config → client enabled."""
    return Settings(
        azure_openai_endpoint="https://test.openai.azure.com",
        azure_openai_api_key="test-key-12345",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_version="2024-12-01-preview",
    )


# ── Disabled client tests ─────────────────────────────────────────


class TestLLMClientDisabled:
    """When config is missing, all operations return None gracefully."""

    def test_client_not_enabled(self) -> None:
        client = LLMClient(_disabled_settings())
        assert client.enabled is False

    @pytest.mark.asyncio()
    async def test_chat_returns_none(self) -> None:
        client = LLMClient(_disabled_settings())
        result = await client.chat("Hello")
        assert result is None

    @pytest.mark.asyncio()
    async def test_stream_yields_nothing(self) -> None:
        client = LLMClient(_disabled_settings())
        chunks = []
        async for chunk in client.chat_stream("Hello"):
            chunks.append(chunk)
        assert chunks == []


# ── Enabled client tests (mocked) ─────────────────────────────────


class TestLLMClientEnabled:
    """When config is present, the client is enabled and calls OpenAI."""

    def test_client_enabled(self) -> None:
        client = LLMClient(_enabled_settings())
        assert client.enabled is True

    @pytest.mark.asyncio()
    async def test_chat_success(self) -> None:
        client = LLMClient(_enabled_settings())

        # Mock the OpenAI response
        mock_choice = MagicMock()
        mock_choice.message.content = "Test response"
        mock_choice.finish_reason = "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_usage.total_tokens = 15

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client._client = mock_client
        client._enabled = True

        result = await client.chat("Hello", system="You are helpful.")
        assert result is not None
        assert isinstance(result, LLMResponse)
        assert result.content == "Test response"
        assert result.usage["total_tokens"] == 15

    @pytest.mark.asyncio()
    async def test_chat_with_messages(self) -> None:
        client = LLMClient(_enabled_settings())

        mock_choice = MagicMock()
        mock_choice.message.content = "Response"
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client._client = mock_client

        messages = [
            LLMMessage(role="system", content="You are a tutor."),
            LLMMessage(role="user", content="Explain algebra"),
        ]
        result = await client.chat("ignored", messages=messages)
        assert result is not None
        assert result.content == "Response"

        # Verify the messages were passed correctly
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"

    @pytest.mark.asyncio()
    async def test_chat_json_mode(self) -> None:
        client = LLMClient(_enabled_settings())

        mock_choice = MagicMock()
        mock_choice.message.content = '{"key": "value"}'
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        client._client = mock_client

        result = await client.chat("Return JSON", json_mode=True)
        assert result is not None

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio()
    async def test_chat_handles_exception(self) -> None:
        client = LLMClient(_enabled_settings())

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API quota exceeded")
        )
        client._client = mock_client

        result = await client.chat("Hello")
        assert result is None  # Graceful fallback, no exception raised


# ── Singleton tests ────────────────────────────────────────────────


class TestLLMSingleton:
    def test_get_returns_same_instance(self) -> None:
        reset_llm_client()
        s = _disabled_settings()
        c1 = get_llm_client(s)
        c2 = get_llm_client()
        assert c1 is c2

    def test_reset_clears_instance(self) -> None:
        reset_llm_client()
        c1 = get_llm_client(_disabled_settings())
        reset_llm_client()
        c2 = get_llm_client(_disabled_settings())
        assert c1 is not c2

    def test_new_settings_replaces_instance(self) -> None:
        reset_llm_client()
        c1 = get_llm_client(_disabled_settings())
        c2 = get_llm_client(_enabled_settings())
        assert c1 is not c2
        assert c2.enabled is True


# ── Config integration ─────────────────────────────────────────────


class TestConfigIntegration:
    def test_default_settings_have_llm_fields(self) -> None:
        s = Settings()
        assert hasattr(s, "azure_openai_endpoint")
        assert hasattr(s, "azure_openai_api_key")
        assert hasattr(s, "azure_openai_deployment")
        assert hasattr(s, "azure_openai_api_version")
        assert hasattr(s, "llm_temperature")
        assert hasattr(s, "llm_max_tokens")
        assert s.llm_temperature == 0.4
        assert s.llm_max_tokens == 1024

    def test_env_prefix_ln(self) -> None:
        """LN_ prefix means LN_AZURE_OPENAI_ENDPOINT → azure_openai_endpoint."""
        import os

        with patch.dict(os.environ, {"LN_AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com"}):
            s = Settings()
            assert s.azure_openai_endpoint == "https://test.openai.azure.com"
