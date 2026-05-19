from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import SearchProvider, SearchResponse, SearchResult, normalize_url, root_domain, truncate, utc_now_iso


class FirecrawlSearchProvider(SearchProvider):
    provider_id = "firecrawl"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        country: str = "US",
        location: str = "",
        include_markdown: bool = False,
        ignore_invalid_urls: bool = False,
        firecrawl_timeout_ms: int = 60000,
        timeout_seconds: float = 45.0,
        cost_per_query_usd: float = 0.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
        self.base_url = base_url or os.environ.get("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev/v2/search")
        self.country = country
        self.location = location
        self.include_markdown = include_markdown
        self.ignore_invalid_urls = ignore_invalid_urls
        self.firecrawl_timeout_ms = firecrawl_timeout_ms
        self.timeout_seconds = timeout_seconds
        self.cost_per_query_usd = cost_per_query_usd

    async def search(self, query: str, max_results: int = 10) -> SearchResponse:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is required for Firecrawl search.")

        body: dict[str, Any] = {
            "query": query,
            "limit": max(1, min(max_results, 100)),
            "sources": ["web"],
            "country": self.country,
            "timeout": self.firecrawl_timeout_ms,
            "ignoreInvalidURLs": self.ignore_invalid_urls,
        }
        if self.location:
            body["location"] = self.location
        if self.include_markdown:
            body["scrapeOptions"] = {
                "formats": [{"type": "markdown"}],
                "onlyMainContent": True,
            }

        request = Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
                "user-agent": "searchapi-hard-eval/0.1",
            },
            method="POST",
        )
        start = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Firecrawl search failed with HTTP {error.code}: {details}") from error

        if payload.get("success") is False:
            raise RuntimeError(f"Firecrawl search failed: {json.dumps(payload, ensure_ascii=False)[:2000]}")

        latency_ms = (time.perf_counter() - start) * 1000
        return SearchResponse(
            provider_id=self.provider_id,
            query=query,
            results=self._parse_results(payload),
            latency_ms=latency_ms,
            raw_response=payload,
            timestamp=utc_now_iso(),
        )

    def _parse_results(self, payload: dict[str, Any]) -> list[SearchResult]:
        parsed: list[SearchResult] = []
        for index, item in enumerate(_web_results(payload), start=1):
            url = normalize_url(str(item.get("url") or item.get("metadata", {}).get("url") or ""))
            markdown = item.get("markdown") or item.get("content") or ""
            description = item.get("description") or item.get("metadata", {}).get("description") or markdown
            metadata = item.get("metadata") or {}
            parsed.append(
                SearchResult(
                    rank=index,
                    title=truncate(str(item.get("title") or metadata.get("title") or ""), 300),
                    url=url,
                    snippet=truncate(str(description or ""), 1000),
                    domain=root_domain(url),
                    provider_metadata={
                        "category": item.get("category"),
                        "links": item.get("links") or [],
                        "screenshot": item.get("screenshot"),
                        "metadata": metadata,
                        "markdown": truncate(str(markdown or ""), 4000) if markdown else "",
                        "markdown_included": bool(markdown),
                        "warning": payload.get("warning"),
                        "id": payload.get("id"),
                        "credits_used": payload.get("creditsUsed"),
                    },
                )
            )
        return parsed


def _web_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    web = data.get("web") if isinstance(data, dict) else None
    if isinstance(web, list):
        return [item for item in web if isinstance(item, dict)]
    return []
