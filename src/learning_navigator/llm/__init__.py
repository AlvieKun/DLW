"""LLM integration — Azure OpenAI client with safe fallback."""

from learning_navigator.llm.azure_client import get_llm_client, LLMClient

__all__ = ["get_llm_client", "LLMClient"]
