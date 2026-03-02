"""Azure OpenAI async client with safe fallback.

When LN_AZURE_OPENAI_ENDPOINT / LN_AZURE_OPENAI_API_KEY / LN_AZURE_OPENAI_DEPLOYMENT
are **not** configured, the client degrades gracefully — every call returns ``None``
and logs a warning.  This lets the deterministic agents keep working without LLM.

Usage::

    from learning_navigator.llm import get_llm_client

    client = get_llm_client()
    result = await client.chat("Summarise this concept for a beginner.", system="You are a tutor.")
    if result is None:
        # LLM not available — use rule-based fallback
        ...
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Sequence

import structlog

from learning_navigator.infra.config import Settings, get_settings

logger = structlog.get_logger(__name__)

# ── Types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMMessage:
    """A single chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """Wrapper around a completion result."""

    content: str
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


# ── Client ─────────────────────────────────────────────────────────


class LLMClient:
    """Async wrapper around Azure OpenAI chat completions.

    Initialise once (via :func:`get_llm_client`) and reuse.
    If the required config is missing the client is **disabled** — all calls
    return ``None`` without raising.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._enabled = bool(
            self._settings.azure_openai_endpoint
            and self._settings.azure_openai_api_key
            and self._settings.azure_openai_deployment
        )
        self._client: Any | None = None

        if not self._enabled:
            logger.warning(
                "llm_client.disabled",
                reason="Azure OpenAI config missing — LLM features will be skipped.",
            )
        else:
            logger.info(
                "llm_client.enabled",
                endpoint=self._settings.azure_openai_endpoint,
                deployment=self._settings.azure_openai_deployment,
                api_version=self._settings.azure_openai_api_version,
            )

    # ── Lazy init ──────────────────────────────────────────────────

    def _get_client(self) -> Any:
        """Lazily create the ``AsyncAzureOpenAI`` client."""
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncAzureOpenAI  # type: ignore[import-untyped]
        except ImportError:
            logger.error(
                "llm_client.import_error",
                msg="'openai' package not installed — run: pip install openai",
            )
            self._enabled = False
            return None

        self._client = AsyncAzureOpenAI(
            azure_endpoint=self._settings.azure_openai_endpoint,
            api_key=self._settings.azure_openai_api_key,
            api_version=self._settings.azure_openai_api_version,
        )
        return self._client

    # ── Public API ─────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        messages: Sequence[LLMMessage] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse | None:
        """Send a chat completion request.

        Parameters
        ----------
        prompt:
            The user message.  Ignored if *messages* is provided.
        system:
            Optional system message prepended to the conversation.
        messages:
            Full message list — overrides *prompt* and *system*.
        temperature:
            Sampling temperature (default from config).
        max_tokens:
            Max response tokens (default from config).
        json_mode:
            If True, set ``response_format={"type": "json_object"}``.

        Returns
        -------
        LLMResponse | None
            The completion result, or ``None`` if LLM is unavailable.
        """
        if not self._enabled:
            return None

        client = self._get_client()
        if client is None:
            return None

        # Build message list
        if messages:
            msgs = [{"role": m.role, "content": m.content} for m in messages]
        else:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": self._settings.azure_openai_deployment,
            "messages": msgs,
            "temperature": temperature if temperature is not None else self._settings.llm_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self._settings.llm_max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model or self._settings.azure_openai_deployment,
                usage=usage,
                finish_reason=choice.finish_reason or "stop",
            )
        except Exception as exc:
            logger.error(
                "llm_client.chat.failed",
                error=str(exc),
                deployment=self._settings.azure_openai_deployment,
            )
            return None

    async def chat_stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """Streaming chat completion — yields content chunks.

        Yields ``str`` chunks.  If LLM is unavailable, yields nothing.
        """
        if not self._enabled:
            return

        client = self._get_client()
        if client is None:
            return

        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})

        try:
            stream = await client.chat.completions.create(
                model=self._settings.azure_openai_deployment,
                messages=msgs,
                temperature=temperature if temperature is not None else self._settings.llm_temperature,
                max_tokens=max_tokens if max_tokens is not None else self._settings.llm_max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            logger.error("llm_client.stream.failed", error=str(exc))
            return


# ── Singleton ──────────────────────────────────────────────────────

_llm_client: LLMClient | None = None


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Return (and cache) the global LLM client instance."""
    global _llm_client
    if _llm_client is None or settings is not None:
        _llm_client = LLMClient(settings)
    return _llm_client


def reset_llm_client() -> None:
    """Reset cached client — useful in tests."""
    global _llm_client
    _llm_client = None
