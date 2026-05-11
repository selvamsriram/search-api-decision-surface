from __future__ import annotations

import difflib
from typing import Any
from urllib.parse import urlparse

from searchapi_eval.evaluation.grader import exact_match, token_f1
from searchapi_eval.providers.base import normalize_url


def _retrieval_queries(trace: dict[str, Any]) -> list[str]:
    return [retrieval.get("search_query", "") for retrieval in trace.get("retrievals", [])]


def _all_result_urls(trace: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for retrieval in trace.get("retrievals", []):
        results = retrieval.get("search_response", {}).get("results", [])
        urls.extend(result.get("url", "") for result in results)
    return [url for url in urls if url]


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def reformulation_rate(queries: list[str]) -> float | None:
    if len(queries) < 2:
        return None
    reformulations = 0
    for previous, current in zip(queries, queries[1:]):
        similarity = difflib.SequenceMatcher(None, previous.lower(), current.lower()).ratio()
        if 1 - similarity > 0.30:
            reformulations += 1
    return reformulations / (len(queries) - 1)


def redundant_search_rate(trace: dict[str, Any]) -> float | None:
    retrievals = trace.get("retrievals", [])
    if len(retrievals) < 2:
        return None
    redundant = 0
    for previous, current in zip(retrievals, retrievals[1:]):
        previous_urls = {
            result.get("url")
            for result in previous.get("search_response", {}).get("results", [])
            if result.get("url")
        }
        current_urls = {
            result.get("url")
            for result in current.get("search_response", {}).get("results", [])
            if result.get("url")
        }
        union = previous_urls | current_urls
        overlap = len(previous_urls & current_urls) / len(union) if union else 0.0
        if overlap > 0.70:
            redundant += 1
    return redundant / (len(retrievals) - 1)


def gold_document_hit(trace: dict[str, Any]) -> bool:
    gold_urls = [normalize_url(url) for url in trace.get("gold_urls", [])]
    retrieved_urls = [normalize_url(url) for url in _all_result_urls(trace)]
    for gold in gold_urls:
        gold_no_scheme = gold.split("://", 1)[-1]
        for retrieved in retrieved_urls:
            retrieved_no_scheme = retrieved.split("://", 1)[-1]
            if retrieved_no_scheme.startswith(gold_no_scheme) or gold_no_scheme.startswith(retrieved_no_scheme):
                return True
    return False


def compute_trace_metrics(trace: dict[str, Any]) -> dict[str, Any]:
    queries = _retrieval_queries(trace)
    retrieved_urls = _all_result_urls(trace)
    predicted = trace.get("final_answer") or ""
    gold = trace.get("gold_answer") or ""
    em = exact_match(predicted, gold)
    tsc = int(trace.get("total_search_calls") or len(queries))

    return {
        "trace_id": trace.get("trace_id"),
        "query_id": trace.get("query_id"),
        "provider_id": trace.get("provider_id"),
        "model_id": trace.get("model_id"),
        "freshness": trace.get("metadata", {}).get("freshness"),
        "topic": trace.get("metadata", {}).get("topic"),
        "search_results": trace.get("metadata", {}).get("search_results"),
        "question_types": trace.get("metadata", {}).get("question_types", []),
        "effective_year": trace.get("metadata", {}).get("effective_year"),
        "answered": bool(trace.get("answered")),
        "ceiling_hit": bool(trace.get("ceiling_hit")),
        "exact_match": em,
        "f1": token_f1(predicted, gold),
        "total_search_calls": tsc,
        "reformulation_rate": reformulation_rate(queries),
        "redundant_search_rate": redundant_search_rate(trace),
        "source_diversity": len({_domain(url) for url in retrieved_urls}),
        "gold_document_hit": gold_document_hit(trace),
        "premature_termination": (not em and tsc < trace.get("config", {}).get("max_iterations", 10)),
        "failure_mode": "reasoning_failure" if (not em and gold_document_hit(trace)) else ("retrieval_failure" if not em else None),
        "total_prompt_tokens": trace.get("total_prompt_tokens", 0),
        "total_completion_tokens": trace.get("total_completion_tokens", 0),
        "total_cost_usd": trace.get("total_cost_usd", 0.0),
    }

