from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse, urlencode
from urllib.request import Request, urlopen

from .base import LLMClient, LLMResponse


class AzureOpenAIChatClient(LLMClient):
    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
        model_id: str = "azure:gpt-5.4",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        max_tokens_field: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        input_price_per_1k_usd: float = 0.0,
        output_price_per_1k_usd: float = 0.0,
    ) -> None:
        self.endpoint = _normalize_azure_endpoint(endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
        self.api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.deployment = deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
        self.api_version = api_version or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_tokens_field = max_tokens_field or os.environ.get("AZURE_OPENAI_MAX_TOKENS_FIELD", "max_tokens")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries if max_retries is not None else int(os.environ.get("AZURE_OPENAI_MAX_RETRIES", "3"))
        self.retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else float(os.environ.get("AZURE_OPENAI_RETRY_BASE_SECONDS", "5"))
        )
        self.input_price_per_1k_usd = input_price_per_1k_usd
        self.output_price_per_1k_usd = output_price_per_1k_usd

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        return await asyncio.to_thread(self._chat_sync, messages, tools)

    def request_snapshot(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "provider": "azure_openai",
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "api_version": self.api_version,
            "temperature": self.temperature,
            "max_tokens_field": self.max_tokens_field,
            "max_tokens": self.max_tokens,
            "tool_choice": "auto",
            "messages": messages,
            "tools": tools,
        }

    def _chat_sync(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        if not self.endpoint or not self.api_key:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required.")

        attempt = 0
        while True:
            try:
                return self._chat_sync_with_token_field(messages, tools, self.max_tokens_field)
            except _RetryableAzureError as error:
                if attempt >= self.max_retries:
                    raise RuntimeError(error.message) from error.__cause__
                sleep_seconds = error.retry_after_seconds or self.retry_base_seconds * (2**attempt)
                time.sleep(sleep_seconds)
                attempt += 1

    def _chat_sync_with_token_field(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens_field: str,
    ) -> LLMResponse:
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?"
            + urlencode({"api-version": self.api_version})
        )
        body: dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
            max_tokens_field: self.max_tokens,
        }
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json", "api-key": self.api_key},
            method="POST",
        )
        start = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            if (
                error.code == 400
                and max_tokens_field == "max_tokens"
                and "max_completion_tokens" in details
            ):
                self.max_tokens_field = "max_completion_tokens"
                return self._chat_sync_with_token_field(messages, tools, "max_completion_tokens")
            if error.code in {429, 500, 502, 503, 504}:
                retry_after = error.headers.get("retry-after")
                retry_after_seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
                raise _RetryableAzureError(
                    f"Azure OpenAI chat failed with HTTP {error.code}: {details}",
                    retry_after_seconds=retry_after_seconds,
                ) from error
            raise RuntimeError(f"Azure OpenAI chat failed with HTTP {error.code}: {details}") from error

        latency_ms = (time.perf_counter() - start) * 1000
        message = payload.get("choices", [{}])[0].get("message", {})
        tool_calls = message.get("tool_calls") or []
        usage = payload.get("usage") or {}
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            },
            latency_ms=latency_ms,
            raw_response=payload,
        )


def _normalize_azure_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint.strip())
    if not parsed.scheme or not parsed.netloc:
        return endpoint.strip().rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


class _RetryableAzureError(Exception):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after_seconds = retry_after_seconds
