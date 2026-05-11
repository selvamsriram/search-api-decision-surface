from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import SearchProvider, SearchResponse, SearchResult, normalize_url, root_domain, truncate, utc_now_iso


class BraveSearchProvider(SearchProvider):
    provider_id = "brave"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        country: str = "US",
        search_lang: str = "en",
        ui_lang: str = "en-US",
        safesearch: str = "moderate",
        cost_per_query_usd: float = 0.0,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("BRAVE_SEARCH_API_KEY")
            or os.environ.get("BRAVE_API_KEY")
            or os.environ.get("BRAVE_SEARCH_SUBSCRIPTION_TOKEN")
            or ""
        )
        self.base_url = base_url or os.environ.get(
            "BRAVE_SEARCH_BASE_URL",
            "https://api.search.brave.com/res/v1/web/search",
        )
        self.country = country
        self.search_lang = search_lang
        self.ui_lang = ui_lang
        self.safesearch = safesearch
        self.cost_per_query_usd = cost_per_query_usd
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, max_results: int = 10) -> SearchResponse:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("BRAVE_SEARCH_API_KEY is required for Brave search.")

        original_query = query
        query = _fit_brave_query(query)
        count = max(1, min(max_results, 20))
        params = {
            "q": query,
            "count": str(count),
            "offset": "0",
            "country": self.country,
            "search_lang": self.search_lang,
            "ui_lang": self.ui_lang,
            "safesearch": self.safesearch,
            "spellcheck": "true",
            "text_decorations": "false",
            "result_filter": "web",
        }
        url = f"{self.base_url}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "accept": "application/json",
                "accept-encoding": "gzip",
                "x-subscription-token": self.api_key,
                "user-agent": "searchapi-hard-eval/0.1",
            },
            method="GET",
        )
        start = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload_bytes = response.read()
                if response.headers.get("content-encoding") == "gzip":
                    payload_bytes = gzip.decompress(payload_bytes)
                payload = json.loads(payload_bytes.decode("utf-8"))
        except HTTPError as error:
            details = error.read()
            if error.headers.get("content-encoding") == "gzip":
                details = gzip.decompress(details)
            message = details.decode("utf-8", errors="replace")
            raise RuntimeError(f"Brave search failed with HTTP {error.code}: {message}") from error

        latency_ms = (time.perf_counter() - start) * 1000
        return SearchResponse(
            provider_id=self.provider_id,
            query=original_query,
            results=self._parse_results(payload),
            latency_ms=latency_ms,
            raw_response=payload,
            timestamp=utc_now_iso(),
        )

    def _parse_results(self, payload: dict[str, Any]) -> list[SearchResult]:
        parsed: list[SearchResult] = []
        for index, item in enumerate(payload.get("web", {}).get("results", []), start=1):
            url = normalize_url(str(item.get("url", "")))
            parsed.append(
                SearchResult(
                    rank=index,
                    title=truncate(str(item.get("title") or ""), 300),
                    url=url,
                    snippet=truncate(str(item.get("description") or ""), 1000),
                    domain=root_domain(url),
                    provider_metadata={
                        "type": item.get("type"),
                        "profile": item.get("profile"),
                        "language": item.get("language"),
                        "family_friendly": item.get("family_friendly"),
                        "page_age": item.get("page_age"),
                        "age": item.get("age"),
                        "is_source_local": item.get("is_source_local"),
                        "is_source_both": item.get("is_source_both"),
                        "extra_snippets": item.get("extra_snippets"),
                    },
                )
            )
        return parsed


def _fit_brave_query(query: str, max_words: int = 50, max_chars: int = 400) -> str:
    words = query.split()
    fitted = " ".join(words[:max_words])
    if len(fitted) <= max_chars:
        return fitted
    return fitted[:max_chars].rsplit(" ", 1)[0] or fitted[:max_chars]
