from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}


@dataclass
class SearchResult:
    rank: int
    title: str
    url: str
    snippet: str
    domain: str
    provider_metadata: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResponse:
    provider_id: str
    query: str
    results: list[SearchResult]
    latency_ms: float
    raw_response: dict[str, Any]
    timestamp: str

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = [result.to_json() for result in self.results]
        return data


class SearchProvider:
    provider_id: str
    cost_per_query_usd: float

    async def search(self, query: str, max_results: int = 10) -> SearchResponse:
        raise NotImplementedError


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def root_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return re.sub(r"^www\.", "", netloc)


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_PARAMS and not key.startswith(TRACKING_PARAMS_PREFIXES)
    ]
    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(query_items, doseq=True),
        fragment="",
    )
    rendered = urlunparse(cleaned)
    if rendered.endswith("/"):
        rendered = rendered[:-1]
    return rendered


def truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "..."

