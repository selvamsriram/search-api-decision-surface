"""Fetch actions from canonical traces, independent of evidence judgments."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from searchapi_eval.evaluation.trace_analysis import latest_by_query_id, load_jsonl
from searchapi_eval.providers.base import normalize_url


@dataclass
class FetchActions:
    attempts: int = 0
    successes: int = 0
    urls: set[str] = field(default_factory=set)
    provenance: list[dict[str, Any]] = field(default_factory=list)


def canonical_trace_paths(root: Path) -> dict[str, Path]:
    return {
        p: root / f"data/traces/phase1_v1_{p}_gpt54_fetch_tool_jina_100.jsonl"
        for p in ("brave", "tavily", "firecrawl")
    }


def load_canonical_traces(path: Path, provider: str, query_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Use the last trace per query, including the recorded Tavily retry."""
    traces = latest_by_query_id(load_jsonl(path))
    if set(traces) != query_ids:
        raise ValueError(f"Trace/semantic query IDs differ for {provider}")
    if any(t.get("provider_id") != provider for t in traces.values()):
        raise ValueError(f"Unexpected provider in {path}")
    return traces


def fetch_actions(trace: dict[str, Any]) -> FetchActions:
    """Count every attempt; join original URLs by retrieval and document ID.

    Failed fetches remain actions. A fetch with unresolved provenance remains
    an attempt too; it cannot be credited as fetching a supporting URL.
    Redirect destinations are not substituted for the selected search URL.
    """
    out = FetchActions()
    retrievals = {r["retrieval_id"]: r for r in trace.get("retrievals") or []}
    for fetch in trace.get("fetches") or []:
        out.attempts += 1
        status = (fetch.get("page_fetch") or {}).get("fetch_status")
        out.successes += status == "success"
        retrieval_id = fetch.get("source_retrieval_id")
        document_id = fetch.get("source_document_id") or fetch.get("requested_document_id")
        results = (retrievals.get(retrieval_id, {}).get("search_response") or {}).get("results") or []
        matches = [r for r in results if document_id and r.get("document_id") == document_id]
        selected_url = normalize_url(str(fetch.get("url") or ""))
        source_url = normalize_url(str(matches[0].get("url") or "")) if len(matches) == 1 else ""
        joined = bool(source_url and selected_url == source_url)
        if joined:
            out.urls.add(source_url)
        out.provenance.append({
            "fetch_id": fetch.get("fetch_id"),
            "source_retrieval_id": retrieval_id,
            "source_document_id": document_id,
            "normalized_url": selected_url,
            "fetch_status": status,
            "provenance_joined": joined,
        })
    return out
