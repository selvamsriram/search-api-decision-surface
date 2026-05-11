from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import SearchProvider, SearchResponse, SearchResult, normalize_url, root_domain, truncate, utc_now_iso


class ExaSearchProvider(SearchProvider):
    provider_id = "exa"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        search_type: str = "auto",
        cost_per_query_usd: float = 0.005,
        highlight_chars: int = 4000,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("EXA_API_KEY", "")
        self.base_url = base_url or os.environ.get("EXA_BASE_URL", "https://api.exa.ai/search")
        self.search_type = search_type
        self.cost_per_query_usd = cost_per_query_usd
        self.highlight_chars = highlight_chars
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, max_results: int = 10) -> SearchResponse:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY is required for Exa search.")

        body = {
            "query": query,
            "type": self.search_type,
            "numResults": max_results,
            "contents": {"highlights": True},
        }
        request = Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
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
            raise RuntimeError(f"Exa search failed with HTTP {error.code}: {details}") from error

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
            highlights = item.get("highlights") or []
            if isinstance(highlights, list):
                snippet = " ".join(str(value) for value in highlights)
            else:
                snippet = str(highlights)
            if not snippet:
                snippet = str(item.get("text") or item.get("summary") or "")
            parsed.append(
                SearchResult(
                    rank=index,
                    title=truncate(str(item.get("title") or ""), 300),
                    url=url,
                    snippet=truncate(snippet, 1000),
                    domain=root_domain(url),
                    provider_metadata={
                        "id": item.get("id"),
                        "score": item.get("score"),
                        "published_date": item.get("publishedDate"),
                        "author": item.get("author"),
                    },
                )
            )
        return parsed
