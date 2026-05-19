from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable
from urllib.parse import urlparse

from searchapi_eval.evaluation.grader import exact_match, normalize_answer, token_f1
from searchapi_eval.evaluation.metrics import (
    gold_document_hit,
    redundant_search_rate,
    reformulation_rate,
)
from searchapi_eval.providers.base import normalize_url


LARGE_EXTRACT_THRESHOLDS = (50_000, 100_000, 500_000)


@dataclass(frozen=True)
class TraceFile:
    label: str
    path: Path


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if line.strip():
                row = json.loads(line)
                row["_jsonl_line_num"] = line_num
                rows.append(row)
    return rows


def latest_by_query_id(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        query_id = row.get("query_id")
        if query_id:
            latest[query_id] = row
    return latest


def provider_label(path: str | Path, rows: list[dict[str, Any]]) -> str:
    if rows and rows[-1].get("provider_id"):
        return str(rows[-1]["provider_id"])
    stem = Path(path).stem.lower()
    for candidate in ("brave", "tavily", "firecrawl", "exa"):
        if candidate in stem:
            return candidate
    return stem


def iter_retrievals(trace: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield from trace.get("retrievals") or []


def iter_results(trace: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for retrieval in iter_retrievals(trace):
        for result in retrieval.get("search_response", {}).get("results", []) or []:
            yield retrieval, result


def iter_page_fetch_records(trace: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for _, result in iter_results(trace):
        page_fetch = result.get("page_fetch") or {}
        if page_fetch:
            yield {
                "page_fetch": page_fetch,
                "rank": int(result.get("rank") or 0) or None,
                "domain": result.get("domain") or _domain(result.get("url") or ""),
                "source": "search_result",
            }
    for fetch in trace.get("fetches") or []:
        page_fetch = fetch.get("page_fetch") or {}
        if page_fetch:
            yield {
                "page_fetch": page_fetch,
                "rank": int(fetch.get("source_rank") or 0) or None,
                "domain": fetch.get("source_domain") or _domain(fetch.get("url") or ""),
                "source": "fetch_tool",
            }


def trace_total_tokens(trace: dict[str, Any]) -> int:
    return int(trace.get("total_prompt_tokens") or 0) + int(trace.get("total_completion_tokens") or 0)


def result_text_fields(result: dict[str, Any]) -> dict[str, str]:
    metadata = result.get("provider_metadata") or {}
    extra_snippets = metadata.get("extra_snippets") or []
    extra_text = " ".join(str(snippet) for snippet in extra_snippets if snippet)
    page_fetch = result.get("page_fetch") or {}
    return {
        "title": str(result.get("title") or ""),
        "snippet": str(result.get("snippet") or ""),
        "extra_snippets": extra_text,
        "page": str(page_fetch.get("extracted_text") or ""),
    }


def answer_in_text(gold_answer: str | None, text: str) -> bool:
    if not gold_answer or not text:
        return False
    normalized_gold = normalize_answer(gold_answer)
    normalized_text = normalize_answer(text)
    if not normalized_gold or not normalized_text:
        return False
    if normalized_gold in normalized_text:
        return True

    # Preserve a useful exact check for punctuation-sensitive answers like "4,983"
    simple_gold = _simple_text(gold_answer)
    simple_text = _simple_text(text)
    return bool(simple_gold and simple_gold in simple_text)


def gold_url_exact_hit(trace: dict[str, Any]) -> bool:
    gold_urls = {normalize_url(url) for url in trace.get("gold_urls", []) if url}
    retrieved_urls = {
        normalize_url(result.get("url") or "")
        for _, result in iter_results(trace)
        if result.get("url")
    }
    return bool(gold_urls & retrieved_urls)


def gold_domain_hit(trace: dict[str, Any]) -> bool:
    gold_domains = {_domain(url) for url in trace.get("gold_urls", []) if url}
    retrieved_domains = {_domain(result.get("url") or "") for _, result in iter_results(trace)}
    gold_domains.discard("")
    retrieved_domains.discard("")
    return bool(gold_domains & retrieved_domains)


def source_family(url: str) -> str:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    domain = parsed.netloc.removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]
    if not domain:
        return ""
    if "wikipedia.org" in domain and path_parts:
        return f"{domain}/wiki/{path_parts[-1].lower()}"
    if len(path_parts) >= 2:
        return f"{domain}/{'/'.join(path_parts[:2]).lower()}"
    if path_parts:
        return f"{domain}/{path_parts[0].lower()}"
    return domain


def gold_source_family_hit(trace: dict[str, Any]) -> bool:
    gold_families = {source_family(url) for url in trace.get("gold_urls", []) if url}
    retrieved_families = {source_family(result.get("url") or "") for _, result in iter_results(trace)}
    gold_families.discard("")
    retrieved_families.discard("")
    return bool(gold_families & retrieved_families)


def first_hit_rank(trace: dict[str, Any], predicate) -> int | None:
    best_rank: int | None = None
    for _, result in iter_results(trace):
        if predicate(result):
            rank = int(result.get("rank") or 0)
            if rank and (best_rank is None or rank < best_rank):
                best_rank = rank
    return best_rank


def mrr_from_rank(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def query_features(trace: dict[str, Any]) -> dict[str, Any]:
    queries = [retrieval.get("search_query", "") for retrieval in iter_retrievals(trace)]
    return {
        "search_query_count": len(queries),
        "unique_search_query_count": len({query.lower().strip() for query in queries if query}),
        "reformulation_rate": reformulation_rate(queries),
        "redundant_search_rate": redundant_search_rate(trace),
        "site_restricted_searches": sum("site:" in query.lower() for query in queries),
        "quoted_searches": sum('"' in query for query in queries),
        "avg_search_query_chars": mean([len(query) for query in queries]) if queries else 0.0,
    }


def iteration_features(trace: dict[str, Any]) -> dict[str, Any]:
    iterations = trace.get("iterations") or []
    search_iterations = [item for item in iterations if item.get("agent_decision") == "search"]
    answer_iteration = next(
        (item.get("iteration_num") for item in iterations if item.get("agent_decision") == "answer"),
        None,
    )
    multi_search_turns = sum(len(item.get("searches") or []) > 1 for item in search_iterations)
    return {
        "iteration_count": len(iterations),
        "search_iteration_count": len(search_iterations),
        "answer_iteration": answer_iteration,
        "multi_search_turn_count": multi_search_turns,
        "multi_search_turn_rate": multi_search_turns / len(search_iterations) if search_iterations else None,
        "answered_after_first_search": bool(trace.get("answered")) and int(trace.get("total_search_calls") or 0) <= 1,
        "ceiling_hit": bool(trace.get("ceiling_hit")),
    }


def per_trace_metrics(trace: dict[str, Any]) -> dict[str, Any]:
    gold_answer = trace.get("gold_answer") or ""
    snippet_hit = False
    page_hit = False
    title_hit = False
    extra_snippet_hit = False
    snippet_hit_rank: int | None = None
    page_hit_rank: int | None = None
    result_count = 0
    domains: set[str] = set()
    fetch_status = Counter()
    extractor = Counter()
    snippet_chars: list[int] = []
    extracted_chars: list[int] = []
    provider_metadata_fields = Counter()

    for _, result in iter_results(trace):
        result_count += 1
        if result.get("domain"):
            domains.add(str(result["domain"]))
        fields = result_text_fields(result)
        title_match = answer_in_text(gold_answer, fields["title"])
        snippet_match = answer_in_text(gold_answer, fields["snippet"])
        extra_match = answer_in_text(gold_answer, fields["extra_snippets"])
        title_hit = title_hit or title_match
        snippet_hit = snippet_hit or snippet_match
        extra_snippet_hit = extra_snippet_hit or extra_match
        if snippet_match and snippet_hit_rank is None:
            snippet_hit_rank = int(result.get("rank") or 0) or None

        snippet_chars.append(len(fields["snippet"]))
        metadata = result.get("provider_metadata") or {}
        for key, value in metadata.items():
            if value not in (None, "", [], {}):
                provider_metadata_fields[key] += 1

    for fetch_record in iter_page_fetch_records(trace):
        page_fetch = fetch_record["page_fetch"]
        page_match = answer_in_text(gold_answer, str(page_fetch.get("extracted_text") or ""))
        page_hit = page_hit or page_match
        if page_match and page_hit_rank is None:
            page_hit_rank = fetch_record["rank"]
        fetch_status[page_fetch.get("fetch_status") or "missing"] += 1
        extractor[page_fetch.get("extractor") or "none"] += 1
        extracted_chars.append(int(page_fetch.get("extracted_text_chars") or 0))

    token_total = trace_total_tokens(trace)
    exact = exact_match(trace.get("final_answer") or "", gold_answer)
    gold_prefix = gold_document_hit(trace)
    deterministic_support = snippet_hit or page_hit or extra_snippet_hit

    return {
        "trace_id": trace.get("trace_id"),
        "run_id": trace.get("run_id"),
        "query_id": trace.get("query_id"),
        "provider_id": trace.get("provider_id"),
        "question": trace.get("question"),
        "gold_answer": gold_answer,
        "final_answer": trace.get("final_answer") or "",
        "answered": bool(trace.get("answered")),
        "failed": bool(trace.get("failed")),
        "abstained": (not trace.get("answered")) and (not trace.get("failed")),
        "failure_stage": trace.get("failure_stage"),
        "exact_match": exact,
        "f1": token_f1(trace.get("final_answer") or "", gold_answer),
        "gold_url_exact_hit": gold_url_exact_hit(trace),
        "gold_url_prefix_hit": gold_prefix,
        "gold_domain_hit": gold_domain_hit(trace),
        "gold_source_family_hit": gold_source_family_hit(trace),
        "answer_in_title": title_hit,
        "answer_in_snippet": snippet_hit,
        "answer_in_extra_snippets": extra_snippet_hit,
        "answer_in_page": page_hit,
        "answer_in_any_retrieved_text": deterministic_support,
        "first_answer_snippet_rank": snippet_hit_rank,
        "first_answer_page_rank": page_hit_rank,
        "answer_snippet_mrr": mrr_from_rank(snippet_hit_rank),
        "answer_page_mrr": mrr_from_rank(page_hit_rank),
        "gold_hit_but_no_answer_text": gold_prefix and not deterministic_support,
        "answer_text_without_gold_prefix": deterministic_support and not gold_prefix,
        "wrong_with_answer_text_available": (not exact) and deterministic_support,
        "wrong_without_answer_text_available": (not exact) and not deterministic_support,
        "retrieval_count": len(list(iter_retrievals(trace))),
        "result_count": result_count,
        "source_diversity": len(domains),
        "total_search_calls": int(trace.get("total_search_calls") or 0),
        "total_prompt_tokens": int(trace.get("total_prompt_tokens") or 0),
        "total_completion_tokens": int(trace.get("total_completion_tokens") or 0),
        "total_tokens": token_total,
        "wall_time_seconds": float(trace.get("wall_time_seconds") or 0),
        "snippet_chars_median": median(snippet_chars) if snippet_chars else 0,
        "extracted_chars_median": median(extracted_chars) if extracted_chars else 0,
        "extracted_chars_max": max(extracted_chars) if extracted_chars else 0,
        "large_extract_50k_count": sum(value > 50_000 for value in extracted_chars),
        "large_extract_100k_count": sum(value > 100_000 for value in extracted_chars),
        "large_extract_500k_count": sum(value > 500_000 for value in extracted_chars),
        "fetch_status_counts": dict(fetch_status),
        "extractor_counts": dict(extractor),
        "provider_metadata_field_counts": dict(provider_metadata_fields),
        **query_features(trace),
        **iteration_features(trace),
    }


def summarize_provider(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = latest_by_query_id(rows)
    metrics = [per_trace_metrics(row) for row in latest.values()]
    historical_failures = [row for row in rows if row.get("failed")]
    latest_failures = [row for row in latest.values() if row.get("failed")]
    transient_recovered = [
        row
        for row in historical_failures
        if row.get("query_id") in latest and not latest[row.get("query_id")].get("failed")
    ]
    fetch_status = Counter()
    extractor = Counter()
    domain_counts = Counter()
    all_extracted_chars: list[int] = []
    all_snippet_chars: list[int] = []
    result_counts: list[int] = []

    for row in latest.values():
        for retrieval in iter_retrievals(row):
            results = retrieval.get("search_response", {}).get("results", []) or []
            result_counts.append(len(results))
            for _, result in [(retrieval, result) for result in results]:
                if result.get("domain"):
                    domain_counts[str(result["domain"])] += 1
                all_snippet_chars.append(len(result.get("snippet") or ""))
        for fetch_record in iter_page_fetch_records(row):
            page_fetch = fetch_record["page_fetch"]
            fetch_status[page_fetch.get("fetch_status") or "missing"] += 1
            extractor[page_fetch.get("extractor") or "none"] += 1
            all_extracted_chars.append(int(page_fetch.get("extracted_text_chars") or 0))

    totals = _metric_totals(metrics)
    tokens = [metric["total_tokens"] for metric in metrics]
    searches = [metric["total_search_calls"] for metric in metrics]
    wall_times = [metric["wall_time_seconds"] for metric in metrics]

    return {
        "provider_id": rows[-1].get("provider_id") if rows else None,
        "trace_rows": len(rows),
        "latest_queries": len(latest),
        "historical_failed_rows": len(historical_failures),
        "latest_failed_queries": len(latest_failures),
        "transient_failures_recovered": len(transient_recovered),
        "answered": totals["answered"],
        "abstained": totals["abstained"],
        "exact_match": totals["exact_match"],
        "avg_f1": _safe_mean([metric["f1"] for metric in metrics]),
        "gold_url_exact_hit": totals["gold_url_exact_hit"],
        "gold_url_prefix_hit": totals["gold_url_prefix_hit"],
        "gold_domain_hit": totals["gold_domain_hit"],
        "gold_source_family_hit": totals["gold_source_family_hit"],
        "answer_in_snippet": totals["answer_in_snippet"],
        "answer_in_extra_snippets": totals["answer_in_extra_snippets"],
        "answer_in_page": totals["answer_in_page"],
        "answer_in_any_retrieved_text": totals["answer_in_any_retrieved_text"],
        "gold_hit_but_no_answer_text": totals["gold_hit_but_no_answer_text"],
        "answer_text_without_gold_prefix": totals["answer_text_without_gold_prefix"],
        "wrong_with_answer_text_available": totals["wrong_with_answer_text_available"],
        "wrong_without_answer_text_available": totals["wrong_without_answer_text_available"],
        "total_search_calls": sum(searches),
        "avg_search_calls": _safe_mean(searches),
        "avg_source_diversity": _safe_mean([metric["source_diversity"] for metric in metrics]),
        "avg_result_count_per_search": _safe_mean(result_counts),
        "avg_reformulation_rate": _safe_mean([metric["reformulation_rate"] for metric in metrics if metric["reformulation_rate"] is not None]),
        "avg_redundant_search_rate": _safe_mean([metric["redundant_search_rate"] for metric in metrics if metric["redundant_search_rate"] is not None]),
        "answer_after_first_search": totals["answered_after_first_search"],
        "multi_search_turn_rate_avg": _safe_mean([metric["multi_search_turn_rate"] for metric in metrics if metric["multi_search_turn_rate"] is not None]),
        "total_tokens": sum(tokens),
        "avg_tokens": _safe_mean(tokens),
        "median_tokens": median(tokens) if tokens else 0,
        "max_tokens": max(tokens) if tokens else 0,
        "queries_over_100k_tokens": sum(value > 100_000 for value in tokens),
        "queries_over_500k_tokens": sum(value > 500_000 for value in tokens),
        "total_wall_time_seconds": sum(wall_times),
        "avg_wall_time_seconds": _safe_mean(wall_times),
        "median_snippet_chars": median(all_snippet_chars) if all_snippet_chars else 0,
        "median_extracted_chars": median(all_extracted_chars) if all_extracted_chars else 0,
        "p90_extracted_chars": _percentile(all_extracted_chars, 0.90),
        "max_extracted_chars": max(all_extracted_chars) if all_extracted_chars else 0,
        "large_extract_counts": {
            f"over_{threshold}": sum(value > threshold for value in all_extracted_chars)
            for threshold in LARGE_EXTRACT_THRESHOLDS
        },
        "fetch_status_counts": dict(fetch_status),
        "extractor_counts": dict(extractor),
        "top_domains": domain_counts.most_common(20),
    }


def pairwise_matrix(metrics_by_provider: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    providers = sorted(metrics_by_provider)
    matrices: dict[str, Any] = {}
    for left_index, left in enumerate(providers):
        for right in providers[left_index + 1 :]:
            common = sorted(set(metrics_by_provider[left]) & set(metrics_by_provider[right]))
            counts = Counter()
            for query_id in common:
                left_metric = metrics_by_provider[left][query_id]
                right_metric = metrics_by_provider[right][query_id]
                counts[_pair_class(left, right, left_metric, right_metric)] += 1
            matrices[f"{left}_vs_{right}"] = {
                "common_queries": len(common),
                "classes": dict(counts),
            }
    return matrices


def three_way_outcomes(metrics_by_provider: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    providers = sorted(metrics_by_provider)
    if len(providers) < 3:
        return {}
    common = set.intersection(*(set(metrics_by_provider[provider]) for provider in providers))
    counts = Counter()
    for query_id in common:
        exact_count = sum(metrics_by_provider[provider][query_id]["exact_match"] for provider in providers)
        support_count = sum(metrics_by_provider[provider][query_id]["answer_in_any_retrieved_text"] for provider in providers)
        gold_count = sum(metrics_by_provider[provider][query_id]["gold_url_prefix_hit"] for provider in providers)
        if exact_count == len(providers):
            label = "all_correct"
        elif exact_count == 0:
            label = "all_wrong"
        elif exact_count == 1:
            label = "one_provider_correct"
        elif exact_count == len(providers) - 1:
            label = "two_providers_correct"
        else:
            label = f"{exact_count}_providers_correct"
        counts[label] += 1
        if support_count == len(providers) and exact_count not in {0, len(providers)}:
            counts["all_have_answer_text_but_different_correctness"] += 1
        if support_count == 1:
            counts["only_one_provider_has_answer_text"] += 1
        if gold_count > support_count:
            counts["gold_alignment_exceeds_answer_text_support"] += 1
    return {
        "providers": providers,
        "common_queries": len(common),
        "classes": dict(counts),
    }


def domain_rows(provider: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = latest_by_query_id(rows)
    domains: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "provider_id": provider,
        "domain": "",
        "result_count": 0,
        "fetch_success": 0,
        "fetch_failed": 0,
        "fetch_empty": 0,
        "answer_in_page": 0,
        "extract_chars_total": 0,
        "large_extract_100k": 0,
    })
    for trace in latest.values():
        gold_answer = trace.get("gold_answer") or ""
        for _, result in iter_results(trace):
            domain = result.get("domain") or _domain(result.get("url") or "")
            row = domains[domain]
            row["domain"] = domain
            row["result_count"] += 1
            page_fetch = result.get("page_fetch") or {}
            status = page_fetch.get("fetch_status")
            if status == "success":
                row["fetch_success"] += 1
            elif status == "failed":
                row["fetch_failed"] += 1
            elif status == "empty":
                row["fetch_empty"] += 1
            text_chars = int(page_fetch.get("extracted_text_chars") or 0)
            row["extract_chars_total"] += text_chars
            row["large_extract_100k"] += int(text_chars > 100_000)
            row["answer_in_page"] += int(answer_in_text(gold_answer, page_fetch.get("extracted_text") or ""))
    return sorted(domains.values(), key=lambda item: item["result_count"], reverse=True)


def _pair_class(left: str, right: str, left_metric: dict[str, Any], right_metric: dict[str, Any]) -> str:
    left_em = bool(left_metric["exact_match"])
    right_em = bool(right_metric["exact_match"])
    left_support = bool(left_metric["answer_in_any_retrieved_text"])
    right_support = bool(right_metric["answer_in_any_retrieved_text"])
    if left_em and right_em:
        return "both_correct"
    if not left_em and not right_em:
        if left_support != right_support:
            return "both_wrong_one_has_answer_text"
        return "both_wrong"
    if left_em:
        return f"{left}_correct_only"
    if right_em:
        return f"{right}_correct_only"
    return "unclassified"


def _metric_totals(metrics: list[dict[str, Any]]) -> Counter:
    totals = Counter()
    for metric in metrics:
        for key, value in metric.items():
            if isinstance(value, bool):
                totals[key] += int(value)
    return totals


def _safe_mean(values: Iterable[float | int]) -> float:
    filtered = [float(value) for value in values if value is not None and not math.isnan(float(value))]
    return sum(filtered) / len(filtered) if filtered else 0.0


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _simple_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()
