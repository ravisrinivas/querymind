"""LLM provider adapters (raw HTTP via httpx — no vendor SDK required)."""
from __future__ import annotations

import os
from typing import Protocol

import httpx

from ..config import PROVIDER_DEFAULT_MODELS


class ProviderError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    def complete(self, system: str, user: str, *, model: str, temperature: float, max_tokens: int) -> str: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, base_url: str = ""):
        self.base = (base_url or "https://api.anthropic.com").rstrip("/")
        self.key = os.getenv("ANTHROPIC_API_KEY", "")

    def complete(self, system, user, *, model, temperature, max_tokens):
        if not self.key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        r = httpx.post(f"{self.base}/v1/messages", timeout=60,
                       headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                             "messages": [{"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise ProviderError(f"Anthropic API {r.status_code}: {r.text[:300]}")
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


class OpenAIProvider:
    name = "openai"

    def __init__(self, base_url: str = ""):
        self.base = (base_url or "https://api.openai.com").rstrip("/")
        self.key = os.getenv("OPENAI_API_KEY", "")

    def complete(self, system, user, *, model, temperature, max_tokens):
        if not self.key:
            raise ProviderError("OPENAI_API_KEY is not set")
        r = httpx.post(f"{self.base}/v1/chat/completions", timeout=60,
                       headers={"Authorization": f"Bearer {self.key}"},
                       json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise ProviderError(f"OpenAI API {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = ""):
        self.base = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    def complete(self, system, user, *, model, temperature, max_tokens):
        try:
            r = httpx.post(f"{self.base}/api/chat", timeout=120,
                           json={"model": model, "stream": False,
                                 "options": {"temperature": temperature, "num_predict": max_tokens},
                                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Ollama at {self.base}: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"Ollama {r.status_code}: {r.text[:300]}")
        return r.json()["message"]["content"]


def get_provider(cfg: dict) -> LLMProvider | None:
    """Returns None for the offline baseline (handled inside the generator/formatter)."""
    p = cfg.get("provider", "offline")
    base = cfg.get("base_url", "")
    if p == "anthropic":
        return AnthropicProvider(base)
    if p == "openai":
        return OpenAIProvider(base)
    if p == "ollama":
        return OllamaProvider(base)
    return None


def effective_model(cfg: dict) -> str:
    return cfg.get("model") or PROVIDER_DEFAULT_MODELS.get(cfg.get("provider", "offline"), "")
