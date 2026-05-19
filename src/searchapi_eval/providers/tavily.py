from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import SearchProvider, SearchResponse, SearchResult, normalize_url, root_domain, truncate, utc_now_iso


class TavilySearchProvider(SearchProvider):
    provider_id = "tavily"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        search_depth: str = "basic",
        topic: str = "general",
        include_raw_content: str | bool = False,
        include_favicon: bool = False,
        timeout_seconds: float = 45.0,
        cost_per_query_usd: float = 0.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        self.base_url = base_url or os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com/search")
        self.search_depth = search_depth
        self.topic = topic
        self.include_raw_content = include_raw_content
        self.include_favicon = include_favicon
        self.timeout_seconds = timeout_seconds
        self.cost_per_query_usd = cost_per_query_usd

    async def search(self, query: str, max_results: int = 10) -> SearchResponse:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is required for Tavily search.")

        body = {
            "query": query,
            "search_depth": self.search_depth,
            "topic": self.topic,
            "max_results": max(1, min(max_results, 20)),
            "include_answer": False,
            "include_images": False,
            "include_image_descriptions": False,
            "include_favicon": self.include_favicon,
            "include_raw_content": self.include_raw_content,
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
            raise RuntimeError(f"Tavily search failed with HTTP {error.code}: {details}") from error

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
        for index, item in enumerate(payload.get("results", []), start=1):
            url = normalize_url(str(item.get("url", "")))
            raw_content = item.get("raw_content")
            parsed.append(
                SearchResult(
                    rank=index,
                    title=truncate(str(item.get("title") or ""), 300),
                    url=url,
                    snippet=truncate(str(item.get("content") or ""), 1000),
                    domain=root_domain(url),
                    provider_metadata={
                        "score": item.get("score"),
                        "favicon": item.get("favicon"),
                        "raw_content": truncate(str(raw_content or ""), 4000) if raw_content else "",
                        "raw_content_included": raw_content is not None,
                        "images": item.get("images") or [],
                        "response_time": payload.get("response_time"),
                        "request_id": payload.get("request_id"),
                        "auto_parameters": payload.get("auto_parameters"),
                        "usage": payload.get("usage"),
                    },
                )
            )
        return parsed
