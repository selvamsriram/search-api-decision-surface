#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import mimetypes
from statistics import mean
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from searchapi_eval.evaluation.metrics import compute_trace_metrics


DEFAULT_TRACE_DIR = "data/traces"
DEFAULT_JUDGE_DIR = "results/llm_judge"
DEFAULT_PAGE_CACHE_DIR = "data/page_cache"
DEFAULT_PROVIDER_COMPARISON_DIR = "results/provider_comparison/brave_tavily_firecrawl"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            trace = json.loads(line)
            trace["_jsonl_line_num"] = line_num
            yield trace


def compact_trace(trace: dict[str, Any]) -> dict[str, Any]:
    try:
        metrics = compute_trace_metrics(trace)
    except Exception as error:
        metrics = {"metric_error": str(error)}
    return {
        "line": trace.get("_jsonl_line_num"),
        "trace_id": trace.get("trace_id"),
        "run_id": trace.get("run_id"),
        "query_id": trace.get("query_id"),
        "question": trace.get("question"),
        "provider_id": trace.get("provider_id"),
        "model_id": trace.get("model_id"),
        "final_answer": trace.get("final_answer"),
        "gold_answer": trace.get("gold_answer"),
        "answered": trace.get("answered"),
        "failed": trace.get("failed"),
        "failure_stage": trace.get("failure_stage"),
        "exact_match": metrics.get("exact_match"),
        "gold_document_hit": metrics.get("gold_document_hit"),
        "failure_mode": metrics.get("failure_mode"),
        "total_search_calls": trace.get("total_search_calls"),
        "total_fetch_calls": trace.get("total_fetch_calls", 0),
        "total_tokens": (trace.get("total_prompt_tokens") or 0) + (trace.get("total_completion_tokens") or 0),
        "started_at": trace.get("started_at"),
        "ended_at": trace.get("ended_at"),
        "metadata": trace.get("metadata", {}),
    }


def extract_prompt_tag(messages: list[dict[str, Any]], tag: str) -> str:
    marker_start = f"<{tag}>"
    marker_end = f"</{tag}>"
    for message in messages:
        content = str(message.get("content") or "")
        start = content.find(marker_start)
        end = content.find(marker_end)
        if start >= 0 and end > start:
            return content[start + len(marker_start) : end].strip()
    return ""


def pct(count: int, total: int) -> float:
    return round((count / total) * 100, 1) if total else 0.0


def compact_judge_record(record: dict[str, Any]) -> dict[str, Any]:
    judgment = record.get("judgment") or {}
    return {
        "line": record.get("_jsonl_line_num"),
        "query_id": record.get("query_id"),
        "provider_id": record.get("provider_id"),
        "document_id": record.get("document_id"),
        "retrieval_id": record.get("retrieval_id"),
        "search_query": record.get("search_query"),
        "rank": record.get("rank"),
        "title": record.get("title"),
        "url": record.get("url"),
        "domain": record.get("domain"),
        "page_fetch_source": record.get("page_fetch_source"),
        "model_fetched_document": record.get("model_fetched_document"),
        "contains_gold_answer": judgment.get("contains_gold_answer"),
        "gold_answer_in_snippets": judgment.get("gold_answer_in_snippets"),
        "gold_answer_in_extracted_page": judgment.get("gold_answer_in_extracted_page"),
        "supports_gold_answer": judgment.get("supports_gold_answer"),
        "supports_model_answer": judgment.get("supports_model_answer"),
        "contradicts_gold_answer": judgment.get("contradicts_gold_answer"),
        "evidence_quality": judgment.get("evidence_quality"),
        "judge_is_garbage": judgment.get("is_garbage"),
        "effective_is_garbage": record.get("effective_is_garbage"),
        "execution_error": record.get("execution_error"),
        "judgment_parse_error": record.get("judgment_parse_error"),
    }


def judge_flags(record: dict[str, Any]) -> dict[str, bool]:
    judgment = record.get("judgment") or {}
    precheck = record.get("document_garbage_precheck") or {}
    return {
        "contains_gold": judgment.get("contains_gold_answer") is True,
        "gold_in_snippets": judgment.get("gold_answer_in_snippets") is True,
        "gold_in_extracted_page": judgment.get("gold_answer_in_extracted_page") is True,
        "supports_gold": judgment.get("supports_gold_answer") is True,
        "supports_model": judgment.get("supports_model_answer") is True,
        "contradicts_gold": judgment.get("contradicts_gold_answer") is True,
        "judge_garbage": judgment.get("is_garbage") is True,
        "precheck_garbage": precheck.get("is_garbage") is True,
        "effective_garbage": record.get("effective_is_garbage") is True,
        "execution_error": bool(record.get("execution_error")),
        "parse_error": bool(record.get("judgment_parse_error")),
    }


def summarize_judge_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    quality_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    confidence_values: list[float] = []
    for record in records:
        judgment = record.get("judgment") or {}
        quality = judgment.get("evidence_quality") or "missing"
        provider = record.get("provider_id") or "unknown"
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        confidence = judgment.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence_values.append(float(confidence))

    total = len(records)
    flag_totals = {key: sum(1 for record in records if judge_flags(record)[key]) for key in (
        "contains_gold",
        "gold_in_snippets",
        "gold_in_extracted_page",
        "supports_gold",
        "supports_model",
        "contradicts_gold",
        "judge_garbage",
        "precheck_garbage",
        "effective_garbage",
        "execution_error",
        "parse_error",
    )}
    return {
        "records": total,
        "queries": len({record.get("query_id") for record in records if record.get("query_id")}),
        "providers": provider_counts,
        "quality_counts": dict(sorted(quality_counts.items())),
        "avg_confidence": round(mean(confidence_values), 3) if confidence_values else 0.0,
        "gold_answer_only_in_snippets": {
            "count": sum(
                1
                for record in records
                if judge_flags(record)["gold_in_snippets"] and not judge_flags(record)["gold_in_extracted_page"]
            ),
            "pct": pct(
                sum(
                    1
                    for record in records
                    if judge_flags(record)["gold_in_snippets"] and not judge_flags(record)["gold_in_extracted_page"]
                ),
                total,
            ),
        },
        "gold_answer_only_in_extracted_page": {
            "count": sum(
                1
                for record in records
                if judge_flags(record)["gold_in_extracted_page"] and not judge_flags(record)["gold_in_snippets"]
            ),
            "pct": pct(
                sum(
                    1
                    for record in records
                    if judge_flags(record)["gold_in_extracted_page"] and not judge_flags(record)["gold_in_snippets"]
                ),
                total,
            ),
        },
        "gold_answer_in_both": {
            "count": sum(
                1
                for record in records
                if judge_flags(record)["gold_in_snippets"] and judge_flags(record)["gold_in_extracted_page"]
            ),
            "pct": pct(
                sum(
                    1
                    for record in records
                    if judge_flags(record)["gold_in_snippets"] and judge_flags(record)["gold_in_extracted_page"]
                ),
                total,
            ),
        },
        **{
            key: {"count": count, "pct": pct(count, total)}
            for key, count in flag_totals.items()
        },
    }


class TraceStore:
    def __init__(self, trace_dir: Path, page_cache_dir: Path) -> None:
        self.trace_dir = trace_dir.resolve()
        self.page_cache_dir = page_cache_dir.resolve()
        self._summary_cache: dict[str, tuple[float, int, dict[str, Any]]] = {}

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for path in sorted(self.trace_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        return files

    def resolve_file(self, name: str) -> Path:
        candidate = (self.trace_dir / name).resolve()
        if candidate.parent != self.trace_dir or candidate.suffix != ".jsonl":
            raise ValueError("Trace file must be a JSONL file inside the configured trace directory.")
        if not candidate.exists():
            raise FileNotFoundError(candidate.name)
        return candidate

    def list_traces(self, file_name: str, page: int, page_size: int, query: str = "") -> dict[str, Any]:
        path = self.resolve_file(file_name)
        page = max(page, 1)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size
        query_lower = query.strip().lower()
        rows: list[dict[str, Any]] = []
        matched = 0
        has_more = False

        for trace in iter_jsonl(path):
            summary = compact_trace(trace)
            haystack = " ".join(
                str(summary.get(key) or "")
                for key in ("trace_id", "run_id", "query_id", "question", "final_answer", "gold_answer", "provider_id")
            ).lower()
            if query_lower and query_lower not in haystack:
                continue
            if matched < offset:
                matched += 1
                continue
            if len(rows) >= page_size:
                has_more = True
                break
            rows.append(summary)
            matched += 1

        return {
            "file": file_name,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
            "rows": rows,
        }

    def get_summary(self, file_name: str) -> dict[str, Any]:
        path = self.resolve_file(file_name)
        stat = path.stat()
        cache_key = str(path)
        cached = self._summary_cache.get(cache_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        rows = 0
        latest_by_query: dict[str, dict[str, Any]] = {}
        for trace in iter_jsonl(path):
            rows += 1
            query_id = trace.get("query_id")
            if query_id:
                latest_by_query[query_id] = trace

        latest_traces = list(latest_by_query.values())
        latest_queries = len(latest_traces)
        metrics = [compute_trace_metrics(trace) for trace in latest_traces]

        answered = sum(1 for trace in latest_traces if bool(trace.get("answered")))
        failed = sum(1 for trace in latest_traces if bool(trace.get("failed")))
        abstained = sum(1 for trace in latest_traces if not trace.get("failed") and not trace.get("answered"))
        exact_match = sum(1 for metric in metrics if bool(metric.get("exact_match")))
        gold_hit = sum(1 for metric in metrics if bool(metric.get("gold_document_hit")))
        total_search_calls = sum(int(trace.get("total_search_calls") or 0) for trace in latest_traces)
        total_fetch_calls = sum(int(trace.get("total_fetch_calls") or 0) for trace in latest_traces)
        total_tokens = sum(
            int(trace.get("total_prompt_tokens") or 0) + int(trace.get("total_completion_tokens") or 0)
            for trace in latest_traces
        )
        wall_times = [float(trace.get("wall_time_seconds") or 0.0) for trace in latest_traces]
        total_wall_time_seconds = round(sum(wall_times), 3)
        total_cost_usd = round(sum(float(trace.get("total_cost_usd") or 0.0) for trace in latest_traces), 8)

        def ratio(count: int) -> float:
            return round((count / latest_queries) * 100, 1) if latest_queries else 0.0

        summary = {
            "file": file_name,
            "rows": rows,
            "latest_queries": latest_queries,
            "answered": {"count": answered, "pct": ratio(answered)},
            "abstained": {"count": abstained, "pct": ratio(abstained)},
            "failed": {"count": failed, "pct": ratio(failed)},
            "exact_match": {"count": exact_match, "pct": ratio(exact_match)},
            "gold_document_hit": {"count": gold_hit, "pct": ratio(gold_hit)},
            "total_search_calls": total_search_calls,
            "avg_search_calls": round(total_search_calls / latest_queries, 2) if latest_queries else 0.0,
            "total_fetch_calls": total_fetch_calls,
            "avg_fetch_calls": round(total_fetch_calls / latest_queries, 2) if latest_queries else 0.0,
            "total_tokens": total_tokens,
            "avg_tokens": round(total_tokens / latest_queries, 1) if latest_queries else 0.0,
            "total_wall_time_seconds": total_wall_time_seconds,
            "avg_wall_time_seconds": round(mean(wall_times), 3) if wall_times else 0.0,
            "total_cost_usd": total_cost_usd,
            "avg_cost_usd": round(total_cost_usd / latest_queries, 8) if latest_queries else 0.0,
        }
        self._summary_cache[cache_key] = (stat.st_mtime, stat.st_size, summary)
        return summary

    def get_trace(self, file_name: str, line: int) -> dict[str, Any]:
        path = self.resolve_file(file_name)
        if line < 1:
            raise ValueError("Line must be >= 1.")
        for trace in iter_jsonl(path):
            if trace.get("_jsonl_line_num") == line:
                trace["metrics"] = compute_trace_metrics(trace)
                return trace
        raise FileNotFoundError(f"No trace at line {line} in {file_name}")

    def get_page_artifact(self, artifact_path: str) -> dict[str, Any]:
        candidate = Path(artifact_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(self.page_cache_dir):
            raise ValueError("Page artifact must be inside the configured page cache directory.")
        if not candidate.exists():
            raise FileNotFoundError(str(candidate))
        if candidate.suffix == ".gz":
            with gzip.open(candidate, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(candidate.read_text(encoding="utf-8"))


class ProviderComparisonStore:
    def __init__(self, comparison_dir: Path) -> None:
        self.comparison_dir = comparison_dir.resolve()
        self._cache_signature: tuple[float, int] | None = None
        self._summary: dict[str, Any] = {}
        self._per_query_by_provider: dict[str, dict[str, dict[str, Any]]] = {}
        self._per_query_by_query: dict[str, dict[str, dict[str, Any]]] = {}
        self._domain_rows_by_provider: dict[str, list[dict[str, Any]]] = {}
        self._reliability: dict[str, Any] = {}

    def available(self) -> bool:
        return (self.comparison_dir / "provider_per_query.jsonl").exists()

    def provider_summary(self, provider_id: str) -> dict[str, Any] | None:
        self._load()
        return (self._summary.get("providers") or {}).get(provider_id)

    def comparison_summary(self, provider_ids: list[str]) -> dict[str, Any]:
        self._load()
        providers = self._summary.get("providers") or {}
        selected = {provider: providers[provider] for provider in provider_ids if provider in providers}
        return {
            "available": bool(self._summary),
            "comparison_dir": str(self.comparison_dir),
            "providers": selected,
            "all_provider_ids": sorted(providers),
            "pairwise": self._summary.get("pairwise") or {},
            "three_way": self._summary.get("three_way") or {},
            "reliability": {
                provider: self._reliability.get(provider)
                for provider in provider_ids
                if provider in self._reliability
            },
            "top_domains": {
                provider: self._domain_rows_by_provider.get(provider, [])[:20]
                for provider in provider_ids
            },
        }

    def provider_query_metrics(self, provider_id: str, query_id: str) -> dict[str, Any] | None:
        self._load()
        return self._per_query_by_provider.get(provider_id, {}).get(query_id)

    def query_comparison_metrics(self, query_id: str) -> dict[str, dict[str, Any]]:
        self._load()
        return self._per_query_by_query.get(query_id, {})

    def _load(self) -> None:
        signature = self._signature()
        if self._cache_signature == signature:
            return
        self._cache_signature = signature
        self._summary = self._read_json("provider_summary.json")
        self._reliability = self._read_json("provider_reliability.json")
        self._per_query_by_provider = {}
        self._per_query_by_query = {}
        per_query_path = self.comparison_dir / "provider_per_query.jsonl"
        if per_query_path.exists():
            for row in iter_jsonl(per_query_path):
                provider_id = row.get("provider_id")
                query_id = row.get("query_id")
                if not provider_id or not query_id:
                    continue
                self._per_query_by_provider.setdefault(provider_id, {})[query_id] = row
                self._per_query_by_query.setdefault(query_id, {})[provider_id] = row
        self._domain_rows_by_provider = {}
        domain_path = self.comparison_dir / "provider_domains.csv"
        if domain_path.exists():
            with domain_path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    provider_id = row.get("provider_id")
                    if provider_id:
                        self._domain_rows_by_provider.setdefault(provider_id, []).append(row)

    def _read_json(self, name: str) -> dict[str, Any]:
        path = self.comparison_dir / name
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _signature(self) -> tuple[float, int]:
        signature_mtime = 0.0
        signature_size = 0
        for name in (
            "provider_summary.json",
            "provider_per_query.jsonl",
            "provider_domains.csv",
            "provider_reliability.json",
        ):
            path = self.comparison_dir / name
            if path.exists():
                stat = path.stat()
                signature_mtime = max(signature_mtime, stat.st_mtime)
                signature_size += stat.st_size
        return signature_mtime, signature_size


class JudgeStore:
    def __init__(self, judge_dir: Path, comparison_store: ProviderComparisonStore | None = None) -> None:
        self.judge_dir = judge_dir.resolve()
        self.comparison_store = comparison_store
        self._summary_cache: dict[str, tuple[float, int, dict[str, Any]]] = {}

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for path in sorted(self.judge_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        return files

    def resolve_file(self, name: str) -> Path:
        candidate = (self.judge_dir / name).resolve()
        if candidate.parent != self.judge_dir or candidate.suffix != ".jsonl":
            raise ValueError("Judge file must be a JSONL file inside the configured judge directory.")
        if not candidate.exists():
            raise FileNotFoundError(candidate.name)
        return candidate

    def get_summary(self, file_name: str) -> dict[str, Any]:
        path = self.resolve_file(file_name)
        stat = path.stat()
        cache_key = str(path)
        cached = self._summary_cache.get(cache_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        records = list(iter_jsonl(path))
        provider_ids = sorted({record.get("provider_id") for record in records if record.get("provider_id")})
        summary = {
            "file": file_name,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "size_bytes": stat.st_size,
            **summarize_judge_records(records),
        }
        if self.comparison_store:
            summary["offline_comparison"] = self.comparison_store.comparison_summary(provider_ids)
        self._summary_cache[cache_key] = (stat.st_mtime, stat.st_size, summary)
        return summary

    def list_queries(self, file_name: str, page: int, page_size: int, query: str = "") -> dict[str, Any]:
        path = self.resolve_file(file_name)
        page = max(page, 1)
        page_size = max(1, min(page_size, 200))
        query_lower = query.strip().lower()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in iter_jsonl(path):
            query_id = record.get("query_id") or "unknown"
            grouped.setdefault(query_id, []).append(record)

        rows: list[dict[str, Any]] = []
        for query_id, records in grouped.items():
            first = records[0]
            question = extract_prompt_tag(first.get("messages") or [], "question")
            gold_answer = extract_prompt_tag(first.get("messages") or [], "gold_answer")
            final_answer = extract_prompt_tag(first.get("messages") or [], "model_final_answer")
            haystack = " ".join(
                str(value or "")
                for value in (
                    query_id,
                    question,
                    gold_answer,
                    final_answer,
                    first.get("provider_id"),
                    " ".join(record.get("search_query") or "" for record in records),
                    " ".join(record.get("url") or "" for record in records),
                )
            ).lower()
            if query_lower and query_lower not in haystack:
                continue
            row_summary = summarize_judge_records(records)
            offline_metrics = None
            if self.comparison_store:
                offline_metrics = self.comparison_store.provider_query_metrics(str(first.get("provider_id") or ""), query_id)
            rows.append(
                {
                    "query_id": query_id,
                    "provider_id": first.get("provider_id"),
                    "question": question,
                    "gold_answer": gold_answer,
                    "model_final_answer": final_answer,
                    "searches": len({record.get("retrieval_id") for record in records if record.get("retrieval_id")}),
                    "docs": len(records),
                    "supports_gold": row_summary["supports_gold"],
                    "supports_model": row_summary["supports_model"],
                    "contains_gold": row_summary["contains_gold"],
                    "gold_in_snippets": row_summary["gold_in_snippets"],
                    "gold_in_extracted_page": row_summary["gold_in_extracted_page"],
                    "effective_garbage": row_summary["effective_garbage"],
                    "contradicts_gold": row_summary["contradicts_gold"],
                    "quality_counts": row_summary["quality_counts"],
                    "offline_metrics": offline_metrics,
                }
            )

        rows.sort(key=lambda row: row["query_id"])
        total = len(rows)
        offset = (page - 1) * page_size
        page_rows = rows[offset : offset + page_size]
        return {
            "file": file_name,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
            "rows": page_rows,
        }

    def get_query(self, file_name: str, query_id: str) -> dict[str, Any]:
        path = self.resolve_file(file_name)
        records = [record for record in iter_jsonl(path) if record.get("query_id") == query_id]
        if not records:
            raise FileNotFoundError(f"No judge records for query {query_id} in {file_name}")
        first = records[0]
        retrievals: dict[str, dict[str, Any]] = {}
        for record in records:
            retrieval_id = record.get("retrieval_id") or "unknown"
            entry = retrievals.setdefault(
                retrieval_id,
                {
                    "retrieval_id": retrieval_id,
                    "search_query": record.get("search_query"),
                    "documents": [],
                },
            )
            entry["documents"].append(record)
        for entry in retrievals.values():
            entry["documents"].sort(key=lambda record: int(record.get("rank") or 0))

        return {
            "file": file_name,
            "query_id": query_id,
            "provider_id": first.get("provider_id"),
            "question": extract_prompt_tag(first.get("messages") or [], "question"),
            "gold_answer": extract_prompt_tag(first.get("messages") or [], "gold_answer"),
            "model_final_answer": extract_prompt_tag(first.get("messages") or [], "model_final_answer"),
            "summary": summarize_judge_records(records),
            "offline_metrics": self.comparison_store.provider_query_metrics(str(first.get("provider_id") or ""), query_id)
            if self.comparison_store
            else None,
            "provider_comparison_metrics": self.comparison_store.query_comparison_metrics(query_id)
            if self.comparison_store
            else {},
            "retrievals": list(retrievals.values()),
            "records": [compact_judge_record(record) for record in records],
        }


class DashboardHandler(BaseHTTPRequestHandler):
    store: TraceStore
    judge_store: JudgeStore
    comparison_store: ProviderComparisonStore

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_html(INDEX_HTML)
            elif parsed.path == "/api/files":
                self.send_json({"files": self.store.list_files()})
            elif parsed.path == "/api/judge-files":
                self.send_json({"files": self.judge_store.list_files()})
            elif parsed.path == "/api/judge-summary":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                self.send_json(self.judge_store.get_summary(file_name))
            elif parsed.path == "/api/judge-queries":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                page = int(params.get("page", ["1"])[0])
                page_size = int(params.get("page_size", ["50"])[0])
                query = params.get("q", [""])[0]
                self.send_json(self.judge_store.list_queries(file_name, page, page_size, query))
            elif parsed.path == "/api/judge-query":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                query_id = required_param(params, "query_id")
                self.send_json(self.judge_store.get_query(file_name, query_id))
            elif parsed.path == "/api/traces":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                page = int(params.get("page", ["1"])[0])
                page_size = int(params.get("page_size", ["50"])[0])
                query = params.get("q", [""])[0]
                self.send_json(self.store.list_traces(file_name, page, page_size, query))
            elif parsed.path == "/api/summary":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                self.send_json(self.store.get_summary(file_name))
            elif parsed.path == "/api/trace":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                line = int(required_param(params, "line"))
                self.send_json(self.store.get_trace(file_name, line))
            elif parsed.path == "/api/page-artifact":
                params = parse_qs(parsed.query)
                artifact_path = required_param(params, "path")
                self.send_json(self.store.get_page_artifact(artifact_path))
            elif parsed.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as error:
            self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def send_html(self, html_text: str) -> None:
        payload = html_text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def required_param(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key)
    if not values or not values[0]:
        raise ValueError(f"Missing required parameter: {key}")
    return values[0]


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SearchAPI Trace Dashboard</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-2: #f9fafb;
      --ink: #17202a;
      --muted: #667789;
      --line: #d7dee6;
      --line-strong: #bdc8d3;
      --brand: #255c99;
      --brand-soft: #e9f1fb;
      --green: #16704a;
      --green-soft: #e8f5ef;
      --red: #a33939;
      --red-soft: #faecec;
      --amber: #8a6416;
      --amber-soft: #fff5dc;
      --violet: #7259a5;
      --teal: #277866;
      --shadow: 0 1px 2px rgba(21, 34, 48, .06), 0 8px 24px rgba(21, 34, 48, .06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.42;
    }
    button, input, select {
      font: inherit;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
    }
    aside {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: #fbfcfd;
      padding: 18px;
    }
    main {
      min-width: 0;
      padding: 22px;
    }
    .brand {
      margin-bottom: 18px;
    }
    .brand h1 {
      font-size: 19px;
      margin: 0;
      letter-spacing: 0;
    }
    .brand p {
      color: var(--muted);
      margin: 4px 0 0;
      font-size: 13px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .sidebar-section {
      margin-bottom: 16px;
    }
    .sidebar-folder {
      margin-bottom: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: hidden;
    }
    .sidebar-folder > summary {
      cursor: pointer;
      padding: 10px 11px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      font-weight: 800;
      background: var(--surface-2);
    }
    .sidebar-folder .file-list {
      padding: 8px;
    }
    .sidebar-section h2 {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      margin: 0 0 8px;
    }
    .file-list {
      display: grid;
      gap: 8px;
    }
    .file-card {
      width: 100%;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 10px;
      text-align: left;
      cursor: pointer;
    }
    .file-card:hover, .file-card.active {
      border-color: var(--brand);
      background: var(--brand-soft);
    }
    .file-name {
      font-weight: 700;
      word-break: break-word;
      font-size: 13px;
    }
    .file-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }
    .controls {
      display: grid;
      gap: 8px;
    }
    .controls input, .controls select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 9px 10px;
    }
    .button-row {
      display: flex;
      gap: 8px;
    }
    .btn {
      border: 1px solid var(--line-strong);
      background: var(--surface);
      border-radius: 8px;
      padding: 8px 10px;
      cursor: pointer;
      color: var(--ink);
    }
    .btn:hover {
      border-color: var(--brand);
      color: var(--brand);
    }
    .btn.primary {
      background: var(--brand);
      border-color: var(--brand);
      color: white;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 16px;
    }
    .topbar h2 {
      margin: 0;
      font-size: 22px;
    }
    .topbar p {
      margin: 4px 0 0;
      color: var(--muted);
    }
    .trace-grid {
      display: grid;
      grid-template-columns: minmax(360px, 430px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .run-summary {
      padding: 14px 16px;
      margin-bottom: 16px;
    }
    .run-summary h3 {
      margin: 0 0 6px;
      font-size: 15px;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .summary-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 10px;
      min-height: 92px;
    }
    .summary-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .05em;
      margin-bottom: 5px;
    }
    .summary-value {
      font-size: 22px;
      font-weight: 800;
      line-height: 1.1;
    }
    .summary-detail {
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
    }
    .row-list {
      max-height: calc(100vh - 170px);
      overflow: auto;
      display: grid;
      gap: 8px;
      padding: 10px;
    }
    .trace-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 10px;
      cursor: pointer;
    }
    .trace-row:hover, .trace-row.active {
      border-color: var(--brand);
      background: var(--brand-soft);
    }
    .trace-row-title {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      font-size: 13px;
      font-weight: 700;
    }
    .question {
      margin: 7px 0;
      font-size: 13px;
    }
    .tiny {
      color: var(--muted);
      font-size: 12px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      margin: 2px 4px 2px 0;
      font-size: 12px;
      white-space: nowrap;
      background: var(--surface-2);
    }
    .pill.good { color: var(--green); background: var(--green-soft); border-color: #badfcc; }
    .pill.bad { color: var(--red); background: var(--red-soft); border-color: #edc3c3; }
    .pill.warn { color: var(--amber); background: var(--amber-soft); border-color: #ecd89d; }
    .detail {
      min-width: 0;
    }
    .hero {
      padding: 16px;
      margin-bottom: 14px;
    }
    .hero h2 {
      margin: 0 0 8px;
      font-size: 20px;
    }
    .hero .answer {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .answer-box {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: var(--surface-2);
    }
    .answer-box label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: 4px;
    }
    .metrics {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 12px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--line);
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }
    th {
      color: var(--muted);
      background: var(--surface-2);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    tr.active-provider-row td {
      background: var(--brand-soft);
      font-weight: 700;
    }
    .section {
      margin-bottom: 14px;
    }
    .section h3 {
      font-size: 15px;
      margin: 0 0 8px;
    }
    details.block {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      margin-bottom: 10px;
      overflow: hidden;
    }
    details.block > summary {
      padding: 11px 12px;
      cursor: pointer;
      font-weight: 750;
      background: var(--surface-2);
    }
    .iteration-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .message {
      margin: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface);
    }
    .message summary {
      padding: 9px 10px;
      cursor: pointer;
      font-weight: 650;
      font-size: 13px;
      border-left: 4px solid var(--line-strong);
    }
    .message.system summary { border-left-color: #5f7286; }
    .message.user summary { border-left-color: var(--brand); }
    .message.assistant summary { border-left-color: var(--violet); }
    .message.tool summary { border-left-color: var(--teal); }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 12px;
      background: #111923;
      color: #e9eef5;
      font-size: 12px;
      line-height: 1.45;
      max-height: 520px;
      overflow: auto;
    }
    .json {
      margin: 10px;
      border-radius: 8px;
    }
    .result {
      display: grid;
      grid-template-columns: 42px 1fr;
      gap: 10px;
      padding: 11px 12px;
      border-top: 1px solid var(--line);
    }
    .result h4 {
      margin: 0 0 4px;
      font-size: 14px;
    }
    .result a {
      color: var(--brand);
      word-break: break-all;
      font-size: 13px;
    }
    .result p {
      margin: 7px 0 0;
      font-size: 13px;
    }
    .raw-response {
      margin: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface);
    }
    .raw-response summary {
      cursor: pointer;
      padding: 9px 10px;
      background: var(--surface-2);
      font-weight: 700;
    }
    .rank {
      color: var(--muted);
      font-weight: 800;
    }
    .empty {
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      padding: 24px;
      text-align: center;
      color: var(--muted);
      background: var(--surface);
    }
    .error {
      padding: 10px;
      background: var(--red-soft);
      color: var(--red);
      border: 1px solid #edc3c3;
      border-radius: 8px;
      margin-bottom: 10px;
    }
    @media (max-width: 1050px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      .trace-grid { grid-template-columns: 1fr; }
      .row-list { max-height: none; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <h1>Trace Dashboard</h1>
        <p>Browse trace runs and LLM judge artifacts.</p>
      </div>
      <details id="traceFolder" class="sidebar-folder" open>
        <summary>Trace Files</summary>
        <div id="fileList" class="file-list"></div>
      </details>
      <details id="judgeFolder" class="sidebar-folder">
        <summary>LLM Judge Files</summary>
        <div id="judgeFileList" class="file-list"></div>
      </details>
      <div class="sidebar-section">
        <h2 id="filterTitle">Row Filters</h2>
        <div class="controls">
          <input id="rowSearch" placeholder="Search query id, answer, question">
          <select id="pageSize">
            <option value="25">25 rows</option>
            <option value="50" selected>50 rows</option>
            <option value="100">100 rows</option>
            <option value="200">200 rows</option>
          </select>
          <div class="button-row">
            <button id="prevPage" class="btn">Previous</button>
            <button id="nextPage" class="btn">Next</button>
          </div>
          <button id="refresh" class="btn primary">Refresh</button>
        </div>
      </div>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h2 id="currentFile">Select a trace file</h2>
          <p id="pageInfo">Trace files load from <code>data/traces</code>; judge files load from <code>results/llm_judge</code>.</p>
        </div>
      </div>
      <div id="errorBox"></div>
      <section id="runSummary" class="panel run-summary">
        <div class="empty">Select a trace file to compute the run summary.</div>
      </section>
      <div class="trace-grid">
        <section class="panel">
          <div id="rowList" class="row-list">
            <div class="empty">Choose a JSONL file to inspect traces.</div>
          </div>
        </section>
        <section id="traceDetail" class="detail">
          <div class="empty">Select one row to render the full trace.</div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const state = {
      mode: 'trace',
      files: [],
      judgeFiles: [],
      selectedFile: null,
      selectedJudgeFile: null,
      selectedLine: null,
      selectedQueryId: null,
      page: 1,
      pageSize: 50,
      query: ''
    };

    const $ = (id) => document.getElementById(id);
    const fmtBytes = (bytes) => {
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    };
    const fmtNum = (value) => Number(value ?? 0).toLocaleString();
    const fmtFixed = (value, digits = 2) => Number(value ?? 0).toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
    const fmtPctCount = (entry) => `${fmtNum(entry?.count || 0)} (${fmtFixed(entry?.pct || 0, 1)}%)`;
    const fmtCost = (value) => `$${fmtFixed(value || 0, 6)}`;
    const fmtSeconds = (value) => {
      const seconds = Number(value || 0);
      if (seconds >= 60) return `${fmtFixed(seconds / 60, 2)} min`;
      return `${fmtFixed(seconds, 2)} s`;
    };
    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
    const short = (value, n = 180) => {
      const text = String(value ?? '').replace(/\s+/g, ' ').trim();
      return text.length <= n ? text : `${text.slice(0, n - 1).trim()}…`;
    };
    const yn = (value) => value === true ? 'yes' : value === false ? 'no' : '—';
    const pill = (label, value) => {
      let klass = 'pill';
      if (value === true) klass += ' good';
      else if (value === false) klass += ' bad';
      else if (value) klass += ' warn';
      return `<span class="${klass}">${esc(label)}: <strong>${esc(value)}</strong></span>`;
    };
    const api = async (path) => {
      const response = await fetch(path);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    };
    const showError = (error) => {
      $('errorBox').innerHTML = error ? `<div class="error">${esc(error.message || error)}</div>` : '';
    };

    async function loadFiles() {
      showError(null);
      const [data, judgeData] = await Promise.all([
        api('/api/files'),
        api('/api/judge-files')
      ]);
      state.files = data.files;
      state.judgeFiles = judgeData.files;
      $('fileList').innerHTML = data.files.length ? data.files.map(file => `
        <button class="file-card trace-file-card ${state.mode === 'trace' && file.name === state.selectedFile ? 'active' : ''}" data-file="${esc(file.name)}">
          <div class="file-name">${esc(file.name)}</div>
          <div class="file-meta">${fmtBytes(file.size_bytes)} · modified ${esc(file.modified_at)}</div>
        </button>
      `).join('') : '<div class="empty">No JSONL files found.</div>';
      $('judgeFileList').innerHTML = judgeData.files.length ? judgeData.files.map(file => `
        <button class="file-card judge-file-card ${state.mode === 'judge' && file.name === state.selectedJudgeFile ? 'active' : ''}" data-file="${esc(file.name)}">
          <div class="file-name">${esc(file.name)}</div>
          <div class="file-meta">${fmtBytes(file.size_bytes)} · modified ${esc(file.modified_at)}</div>
        </button>
      `).join('') : '<div class="empty">No judge JSONL files found.</div>';
      document.querySelectorAll('.trace-file-card').forEach(button => {
        button.addEventListener('click', () => selectTraceFile(button.dataset.file));
      });
      document.querySelectorAll('.judge-file-card').forEach(button => {
        button.addEventListener('click', () => selectJudgeFile(button.dataset.file));
      });
      if (state.mode === 'trace' && !state.selectedFile && data.files.length) {
        await selectTraceFile(data.files[0].name);
      }
    }

    async function selectTraceFile(name) {
      state.mode = 'trace';
      state.selectedFile = name;
      state.selectedLine = null;
      state.selectedQueryId = null;
      state.page = 1;
      $('traceFolder').open = true;
      $('judgeFolder').open = false;
      $('filterTitle').textContent = 'Row Filters';
      $('rowSearch').placeholder = 'Search query id, answer, question';
      $('currentFile').textContent = name;
      $('traceDetail').innerHTML = '<div class="empty">Select one row to render the full trace.</div>';
      $('runSummary').innerHTML = '<div class="empty">Computing run summary…</div>';
      await loadFiles();
      await loadSummary();
      await loadRows();
    }

    async function selectJudgeFile(name) {
      state.mode = 'judge';
      state.selectedJudgeFile = name;
      state.selectedLine = null;
      state.selectedQueryId = null;
      state.page = 1;
      $('traceFolder').open = false;
      $('judgeFolder').open = true;
      $('filterTitle').textContent = 'Judge Query Filters';
      $('rowSearch').placeholder = 'Search query id, URL, answer, search query';
      $('currentFile').textContent = name;
      $('traceDetail').innerHTML = '<div class="empty">Select one query to inspect judge details.</div>';
      $('runSummary').innerHTML = '<div class="empty">Computing judge summary…</div>';
      await loadFiles();
      await loadSummary();
      await loadRows();
    }

    async function loadSummary() {
      if (state.mode === 'judge') {
        if (!state.selectedJudgeFile) return;
        const params = new URLSearchParams({ file: state.selectedJudgeFile });
        const summary = await api(`/api/judge-summary?${params}`);
        renderJudgeSummary(summary);
      } else {
        if (!state.selectedFile) return;
        const params = new URLSearchParams({ file: state.selectedFile });
        const summary = await api(`/api/summary?${params}`);
        renderSummary(summary);
      }
    }

    async function loadRows() {
      if (state.mode === 'judge') {
        return loadJudgeRows();
      }
      if (!state.selectedFile) return;
      showError(null);
      state.pageSize = Number($('pageSize').value);
      state.query = $('rowSearch').value.trim();
      const params = new URLSearchParams({
        file: state.selectedFile,
        page: String(state.page),
        page_size: String(state.pageSize),
        q: state.query
      });
      const data = await api(`/api/traces?${params}`);
      $('pageInfo').textContent = `Page ${data.page} · ${data.rows.length} row(s)${data.has_more ? ' · more available' : ''}`;
      $('prevPage').disabled = state.page <= 1;
      $('nextPage').disabled = !data.has_more;
      $('rowList').innerHTML = data.rows.length ? data.rows.map(renderRow).join('') : '<div class="empty">No matching traces on this page.</div>';
      document.querySelectorAll('.trace-row').forEach(row => {
        row.addEventListener('click', () => loadTrace(Number(row.dataset.line)));
      });
    }

    async function loadJudgeRows() {
      if (!state.selectedJudgeFile) return;
      showError(null);
      state.pageSize = Number($('pageSize').value);
      state.query = $('rowSearch').value.trim();
      const params = new URLSearchParams({
        file: state.selectedJudgeFile,
        page: String(state.page),
        page_size: String(state.pageSize),
        q: state.query
      });
      const data = await api(`/api/judge-queries?${params}`);
      $('pageInfo').textContent = `Judge queries · Page ${data.page} · ${data.rows.length} of ${data.total} query row(s)${data.has_more ? ' · more available' : ''}`;
      $('prevPage').disabled = state.page <= 1;
      $('nextPage').disabled = !data.has_more;
      $('rowList').innerHTML = data.rows.length ? data.rows.map(renderJudgeRow).join('') : '<div class="empty">No matching judge queries on this page.</div>';
      document.querySelectorAll('.judge-row').forEach(row => {
        row.addEventListener('click', () => loadJudgeQuery(row.dataset.queryId));
      });
    }

    function renderRow(row) {
      const active = row.line === state.selectedLine ? 'active' : '';
      return `
        <article class="trace-row ${active}" data-line="${esc(row.line)}">
          <div class="trace-row-title">
            <span>${esc(row.query_id || row.trace_id)}</span>
            <span class="tiny">line ${esc(row.line)}</span>
          </div>
          <div class="question">${esc(short(row.question, 210))}</div>
          <div>
            ${pill('answered', row.answered)}
            ${pill('match', row.exact_match)}
            ${pill('gold hit', row.gold_document_hit)}
            ${row.failed ? pill('failed', row.failed) : ''}
          </div>
          <div class="tiny">
            ${esc(row.provider_id)} · searches ${esc(row.total_search_calls)} · fetches ${esc(row.total_fetch_calls || 0)} · tokens ${esc(row.total_tokens)}
          </div>
          <div class="tiny">final: ${esc(short(row.final_answer, 120))}</div>
        </article>
      `;
    }

    function renderJudgeRow(row) {
      const active = row.query_id === state.selectedQueryId ? 'active' : '';
      const offline = row.offline_metrics || {};
      return `
        <article class="trace-row judge-row ${active}" data-query-id="${esc(row.query_id)}">
          <div class="trace-row-title">
            <span>${esc(row.query_id)}</span>
            <span class="tiny">${esc(row.docs)} docs · ${esc(row.searches)} searches</span>
          </div>
          <div class="question">${esc(short(row.question || 'No question captured in prompt.', 210))}</div>
          <div>
            ${pill('supports gold', `${row.supports_gold.count}/${row.docs}`)}
            ${pill('gold in snippets', `${row.gold_in_snippets.count}/${row.docs}`)}
            ${pill('gold in page', `${row.gold_in_extracted_page.count}/${row.docs}`)}
            ${pill('garbage', `${row.effective_garbage.count}/${row.docs}`)}
            ${pill('contradicts', `${row.contradicts_gold.count}/${row.docs}`)}
          </div>
          ${offline.query_id ? `
            <div>
              ${pill('EM', offline.exact_match)}
              ${pill('gold URL', offline.gold_url_prefix_hit)}
              ${pill('answer text', offline.answer_in_any_retrieved_text)}
            </div>
            <div class="tiny">offline: searches ${esc(offline.total_search_calls)} · tokens ${fmtNum(offline.total_tokens)} · max extract ${fmtNum(offline.extracted_chars_max || 0)} chars</div>
          ` : '<div class="tiny">offline metrics: not found</div>'}
          <div class="tiny">${esc(row.provider_id)} · gold: ${esc(short(row.gold_answer, 80))} · model: ${esc(short(row.model_final_answer, 80))}</div>
        </article>
      `;
    }

    function renderSummary(summary) {
      $('runSummary').innerHTML = `
        <h3>Run Summary</h3>
        <div class="tiny">Computed from the latest row per query id. Raw rows are shown separately so retries stay visible.</div>
        <div class="summary-grid">
          ${summaryCard('Rows', fmtNum(summary.rows), `Latest unique queries: ${fmtNum(summary.latest_queries)}`)}
          ${summaryCard('Answered', fmtPctCount(summary.answered), `Abstained: ${fmtPctCount(summary.abstained)} · Failed: ${fmtPctCount(summary.failed)}`)}
          ${summaryCard('Exact Match', fmtPctCount(summary.exact_match), `Gold doc hit: ${fmtPctCount(summary.gold_document_hit)}`)}
          ${summaryCard('Search Calls', fmtNum(summary.total_search_calls), `Average per query: ${fmtFixed(summary.avg_search_calls, 2)}`)}
          ${summaryCard('Fetch Calls', fmtNum(summary.total_fetch_calls || 0), `Average per query: ${fmtFixed(summary.avg_fetch_calls || 0, 2)}`)}
          ${summaryCard('Tokens', fmtNum(summary.total_tokens), `Average per query: ${fmtFixed(summary.avg_tokens, 1)}`)}
          ${summaryCard('Wall Time', fmtSeconds(summary.total_wall_time_seconds), `Average per query: ${fmtSeconds(summary.avg_wall_time_seconds)}`)}
          ${summaryCard('Estimated Cost', fmtCost(summary.total_cost_usd), `Average per query: ${fmtCost(summary.avg_cost_usd)}`)}
        </div>
      `;
    }

    function renderJudgeSummary(summary) {
      const offline = summary.offline_comparison || null;
      $('runSummary').innerHTML = `
        <h3>LLM Judge Run Summary</h3>
        <div class="tiny">Computed across every document-level judge record in this file.</div>
        <div class="summary-grid">
          ${summaryCard('Documents', fmtNum(summary.records), `Queries: ${fmtNum(summary.queries)} · Providers: ${esc(Object.keys(summary.providers || {}).join(', ') || '—')}`)}
          ${summaryCard('Supports Gold', fmtPctCount(summary.supports_gold), `Contains gold string: ${fmtPctCount(summary.contains_gold)}`)}
          ${summaryCard('Gold Surface', `Snippets ${fmtPctCount(summary.gold_in_snippets)}`, `Page: ${fmtPctCount(summary.gold_in_extracted_page)} · Both: ${fmtPctCount(summary.gold_answer_in_both)}`)}
          ${summaryCard('Surface Split', `Snippet-only ${fmtPctCount(summary.gold_answer_only_in_snippets)}`, `Page-only: ${fmtPctCount(summary.gold_answer_only_in_extracted_page)}`)}
          ${summaryCard('Supports Model', fmtPctCount(summary.supports_model), `Contradicts gold: ${fmtPctCount(summary.contradicts_gold)}`)}
          ${summaryCard('Garbage Docs', fmtPctCount(summary.effective_garbage), `Precheck: ${fmtPctCount(summary.precheck_garbage)} · Judge: ${fmtPctCount(summary.judge_garbage)}`)}
          ${summaryCard('Errors', `${fmtNum((summary.execution_error?.count || 0) + (summary.parse_error?.count || 0))}`, `Execution: ${fmtPctCount(summary.execution_error)} · Parse: ${fmtPctCount(summary.parse_error)}`)}
          ${summaryCard('Avg Confidence', fmtFixed(summary.avg_confidence, 3), `File size: ${fmtBytes(summary.size_bytes || 0)}`)}
        </div>
        <details class="raw-response" style="margin: 12px 0 0;">
          <summary>Evidence quality distribution</summary>
          <pre>${esc(JSON.stringify(summary.quality_counts || {}, null, 2))}</pre>
        </details>
        ${renderOfflineRunSummary(offline)}
      `;
    }

    function renderOfflineRunSummary(offline) {
      if (!offline || !offline.available) {
        return `
          <details class="raw-response" style="margin: 12px 0 0;">
            <summary>Offline derived metrics</summary>
            <div class="empty">No provider comparison artifacts found for this judge run.</div>
          </details>
        `;
      }
      const providerCards = Object.entries(offline.providers || {}).map(([provider, metrics]) => `
        <details class="block" open>
          <summary>${esc(provider)} offline trace metrics</summary>
          <div class="summary-grid" style="padding: 12px;">
            ${summaryCard('Exact Match', `${fmtNum(metrics.exact_match)} / ${fmtNum(metrics.latest_queries)}`, `Answered: ${fmtNum(metrics.answered)} · Abstained: ${fmtNum(metrics.abstained)}`)}
            ${summaryCard('Gold Alignment', `${fmtNum(metrics.gold_url_prefix_hit)} prefix`, `Exact: ${fmtNum(metrics.gold_url_exact_hit)} · Domain: ${fmtNum(metrics.gold_domain_hit)} · Family: ${fmtNum(metrics.gold_source_family_hit)}`)}
            ${summaryCard('Answer Text', `${fmtNum(metrics.answer_in_any_retrieved_text)} any`, `Snippet: ${fmtNum(metrics.answer_in_snippet)} · Extra: ${fmtNum(metrics.answer_in_extra_snippets)} · Page: ${fmtNum(metrics.answer_in_page)}`)}
            ${summaryCard('Failure Split', `${fmtNum(metrics.wrong_with_answer_text_available)} wrong+evidence`, `Wrong no evidence: ${fmtNum(metrics.wrong_without_answer_text_available)} · Gold no answer text: ${fmtNum(metrics.gold_hit_but_no_answer_text)}`)}
            ${summaryCard('Tool Behavior', `${fmtFixed(metrics.avg_search_calls, 2)} searches/q`, `Reformulation: ${fmtFixed((metrics.avg_reformulation_rate || 0) * 100, 1)}% · Redundant: ${fmtFixed((metrics.avg_redundant_search_rate || 0) * 100, 1)}%`)}
            ${summaryCard('Context Cost', fmtNum(metrics.total_tokens), `Avg: ${fmtNum(Math.round(metrics.avg_tokens || 0))} · Median: ${fmtNum(metrics.median_tokens || 0)} · >100k: ${fmtNum(metrics.queries_over_100k_tokens || 0)}`)}
            ${summaryCard('Extraction', `${fmtNum(metrics.fetch_status_counts?.success || 0)} success`, `Empty: ${fmtNum(metrics.fetch_status_counts?.empty || 0)} · Failed: ${fmtNum(metrics.fetch_status_counts?.failed || 0)}`)}
            ${summaryCard('Large Pages', `${fmtNum(metrics.large_extract_counts?.over_50000 || 0)} >50k`, `>100k: ${fmtNum(metrics.large_extract_counts?.over_100000 || 0)} · >500k: ${fmtNum(metrics.large_extract_counts?.over_500000 || 0)}`)}
          </div>
          <details class="raw-response">
            <summary>Top domains and full provider summary</summary>
            <pre>${esc(JSON.stringify({ top_domains: metrics.top_domains || [], summary: metrics }, null, 2))}</pre>
          </details>
        </details>
      `).join('');
      return `
        <section class="section" style="margin-top: 14px;">
          <h3>Offline Derived Metrics</h3>
          ${providerCards || '<div class="empty">No provider-level offline metrics found.</div>'}
          <details class="raw-response">
            <summary>Provider comparison matrices</summary>
            <pre>${esc(JSON.stringify({ pairwise: offline.pairwise || {}, three_way: offline.three_way || {}, reliability: offline.reliability || {} }, null, 2))}</pre>
          </details>
        </section>
      `;
    }

    function summaryCard(label, value, detail) {
      return `
        <article class="summary-card">
          <div class="summary-label">${esc(label)}</div>
          <div class="summary-value">${esc(value)}</div>
          <div class="summary-detail">${esc(detail)}</div>
        </article>
      `;
    }

    async function loadTrace(line) {
      state.selectedLine = line;
      document.querySelectorAll('.trace-row').forEach(row => row.classList.toggle('active', Number(row.dataset.line) === line));
      const params = new URLSearchParams({ file: state.selectedFile, line: String(line) });
      const trace = await api(`/api/trace?${params}`);
      renderTrace(trace);
    }

    async function loadJudgeQuery(queryId) {
      state.selectedQueryId = queryId;
      document.querySelectorAll('.judge-row').forEach(row => row.classList.toggle('active', row.dataset.queryId === queryId));
      const params = new URLSearchParams({ file: state.selectedJudgeFile, query_id: queryId });
      const query = await api(`/api/judge-query?${params}`);
      renderJudgeQuery(query);
    }

    function renderJudgeQuery(query) {
      const summary = query.summary || {};
      $('traceDetail').innerHTML = `
        <section class="panel hero">
          <h2>${esc(query.query_id)}</h2>
          <div class="tiny">${esc(query.provider_id)} · ${esc(summary.records || 0)} judged document(s)</div>
          <p>${esc(query.question || 'No question captured in prompt.')}</p>
          <div class="metrics">
            ${pill('supports gold docs', `${summary.supports_gold?.count || 0}/${summary.records || 0}`)}
            ${pill('gold in snippets', `${summary.gold_in_snippets?.count || 0}/${summary.records || 0}`)}
            ${pill('gold in page', `${summary.gold_in_extracted_page?.count || 0}/${summary.records || 0}`)}
            ${pill('supports model docs', `${summary.supports_model?.count || 0}/${summary.records || 0}`)}
            ${pill('garbage docs', `${summary.effective_garbage?.count || 0}/${summary.records || 0}`)}
            ${pill('contradicts gold docs', `${summary.contradicts_gold?.count || 0}/${summary.records || 0}`)}
          </div>
          <div class="answer">
            <div class="answer-box"><label>Gold</label>${esc(query.gold_answer || '—')}</div>
            <div class="answer-box"><label>Model Final</label>${esc(query.model_final_answer || '—')}</div>
            <div class="answer-box"><label>Searches</label>${esc((query.retrievals || []).length)}</div>
            <div class="answer-box"><label>Docs</label>${esc(summary.records || 0)}</div>
          </div>
        </section>
        <section class="section">
          <h3>Query Judge Aggregate</h3>
          <div class="summary-grid">
            ${summaryCard('Supports Gold', fmtPctCount(summary.supports_gold), `Contains gold: ${fmtPctCount(summary.contains_gold)}`)}
            ${summaryCard('Gold Surface', `Snippets ${fmtPctCount(summary.gold_in_snippets)}`, `Page: ${fmtPctCount(summary.gold_in_extracted_page)} · Both: ${fmtPctCount(summary.gold_answer_in_both)}`)}
            ${summaryCard('Surface Split', `Snippet-only ${fmtPctCount(summary.gold_answer_only_in_snippets)}`, `Page-only: ${fmtPctCount(summary.gold_answer_only_in_extracted_page)}`)}
            ${summaryCard('Supports Model', fmtPctCount(summary.supports_model), `Contradicts gold: ${fmtPctCount(summary.contradicts_gold)}`)}
            ${summaryCard('Garbage', fmtPctCount(summary.effective_garbage), `Precheck: ${fmtPctCount(summary.precheck_garbage)} · Judge: ${fmtPctCount(summary.judge_garbage)}`)}
            ${summaryCard('Avg Confidence', fmtFixed(summary.avg_confidence, 3), `Errors: ${fmtNum((summary.execution_error?.count || 0) + (summary.parse_error?.count || 0))}`)}
          </div>
        </section>
        ${renderOfflineQueryMetrics(query.offline_metrics, query.provider_comparison_metrics || {}, query.provider_id)}
        <section class="section">
          <h3>Searches And Documents</h3>
          ${(query.retrievals || []).map(renderJudgeRetrieval).join('') || '<div class="empty">No retrievals found.</div>'}
        </section>
      `;
    }

    function renderOfflineQueryMetrics(metrics, comparisonMetrics, activeProvider) {
      const providers = Object.keys(comparisonMetrics || {}).sort();
      const active = metrics || comparisonMetrics?.[activeProvider] || null;
      const comparisonRows = providers.map(provider => {
        const row = comparisonMetrics[provider] || {};
        return `
          <tr class="${provider === activeProvider ? 'active-provider-row' : ''}">
            <td>${esc(provider)}</td>
            <td>${esc(yn(row.exact_match))}</td>
            <td>${esc(yn(row.gold_url_prefix_hit))}</td>
            <td>${esc(yn(row.gold_domain_hit))}</td>
            <td>${esc(yn(row.answer_in_any_retrieved_text))}</td>
            <td>${esc(yn(row.answer_in_page))}</td>
            <td>${esc(row.total_search_calls ?? '—')}</td>
            <td>${fmtNum(row.total_tokens || 0)}</td>
            <td>${esc(short(row.final_answer || '', 70))}</td>
          </tr>
        `;
      }).join('');
      return `
        <section class="section">
          <h3>Offline Derived Metrics</h3>
          ${active ? `
            <div class="summary-grid">
              ${summaryCard('Outcome', `EM ${yn(active.exact_match)}`, `F1: ${fmtFixed(active.f1 || 0, 3)} · Answered: ${yn(active.answered)} · Abstained: ${yn(active.abstained)}`)}
              ${summaryCard('Gold Alignment', `URL ${yn(active.gold_url_prefix_hit)}`, `Exact: ${yn(active.gold_url_exact_hit)} · Domain: ${yn(active.gold_domain_hit)} · Family: ${yn(active.gold_source_family_hit)}`)}
              ${summaryCard('Answer Text', `Any ${yn(active.answer_in_any_retrieved_text)}`, `Snippet: ${yn(active.answer_in_snippet)} · Extra: ${yn(active.answer_in_extra_snippets)} · Page: ${yn(active.answer_in_page)}`)}
              ${summaryCard('Failure Signals', `Wrong+evidence ${yn(active.wrong_with_answer_text_available)}`, `Wrong no evidence: ${yn(active.wrong_without_answer_text_available)} · Gold no answer text: ${yn(active.gold_hit_but_no_answer_text)}`)}
              ${summaryCard('Search Policy', `${fmtNum(active.search_query_count || 0)} queries`, `Unique: ${fmtNum(active.unique_search_query_count || 0)} · Site: ${fmtNum(active.site_restricted_searches || 0)} · Quoted: ${fmtNum(active.quoted_searches || 0)}`)}
              ${summaryCard('Loop Behavior', `${fmtNum(active.iteration_count || 0)} iterations`, `Search turns: ${fmtNum(active.search_iteration_count || 0)} · Multi-search turns: ${fmtNum(active.multi_search_turn_count || 0)}`)}
              ${summaryCard('Retrieval Surface', `${fmtNum(active.result_count || 0)} results`, `Domains: ${fmtNum(active.source_diversity || 0)} · Median snippet: ${fmtNum(active.snippet_chars_median || 0)} chars`)}
              ${summaryCard('Extraction Surface', `${fmtNum(active.extracted_chars_median || 0)} median chars`, `Max: ${fmtNum(active.extracted_chars_max || 0)} · >50k: ${fmtNum(active.large_extract_50k_count || 0)}`)}
              ${summaryCard('Token Cost', fmtNum(active.total_tokens || 0), `Prompt: ${fmtNum(active.total_prompt_tokens || 0)} · Completion: ${fmtNum(active.total_completion_tokens || 0)}`)}
              ${summaryCard('Wall Time', fmtSeconds(active.wall_time_seconds || 0), `Run: ${esc(active.run_id || '—')}`)}
            </div>
            <details class="raw-response" style="margin-top: 10px;">
              <summary>Full offline metrics for ${esc(activeProvider || active.provider_id || 'provider')}</summary>
              <pre>${esc(JSON.stringify(active, null, 2))}</pre>
            </details>
          ` : '<div class="empty">No offline per-query metrics found for this provider/query.</div>'}
          ${comparisonRows ? `
            <details class="raw-response" open>
              <summary>Same-query provider comparison</summary>
              <table>
                <thead><tr><th>Provider</th><th>EM</th><th>Gold URL</th><th>Gold Domain</th><th>Answer Text</th><th>Answer Page</th><th>Searches</th><th>Tokens</th><th>Final</th></tr></thead>
                <tbody>${comparisonRows}</tbody>
              </table>
            </details>
          ` : ''}
        </section>
      `;
    }

    function renderJudgeRetrieval(retrieval) {
      const docs = retrieval.documents || [];
      const supports = docs.filter(doc => (doc.judgment || {}).supports_gold_answer === true).length;
      const garbage = docs.filter(doc => doc.effective_is_garbage === true).length;
      return `
        <details class="block" open>
          <summary>
            <div class="iteration-head">
              <span>${esc(short(retrieval.search_query || retrieval.retrieval_id, 180))}</span>
              <span class="tiny">${docs.length} docs · supports gold ${supports} · garbage ${garbage}</span>
            </div>
          </summary>
          <div style="padding: 10px 12px;" class="tiny">retrieval_id=${esc(retrieval.retrieval_id)}</div>
          ${docs.map(renderJudgeDocument).join('')}
        </details>
      `;
    }

    function renderJudgeDocument(record) {
      const judgment = record.judgment || {};
      const pageFetch = record.page_fetch || {};
      const precheck = record.document_garbage_precheck || {};
      const rawResponse = record.llm_response || {};
      const request = record.request_snapshot || {};
      const quality = judgment.evidence_quality || (record.execution_error ? 'execution error' : record.judgment_parse_error ? 'parse error' : 'missing');
      return `
        <article class="result">
          <div class="rank">#${esc(record.rank || '—')}</div>
          <div>
            <h4>${esc(record.title || 'Untitled document')}</h4>
            <a href="${esc(record.url || '')}" target="_blank" rel="noreferrer">${esc(record.url || '')}</a>
            <div class="tiny">${esc(record.domain || '')} · line ${esc(record._jsonl_line_num || '')}</div>
            <div class="metrics">
              ${pill('quality', quality)}
              ${pill('fetch source', record.page_fetch_source || 'none')}
              ${pill('model fetched', record.model_fetched_document)}
              ${pill('supports gold', judgment.supports_gold_answer)}
              ${pill('gold in snippets', judgment.gold_answer_in_snippets)}
              ${pill('gold in page', judgment.gold_answer_in_extracted_page)}
              ${pill('supports model', judgment.supports_model_answer)}
              ${pill('contains gold', judgment.contains_gold_answer)}
              ${pill('contradicts gold', judgment.contradicts_gold_answer)}
              ${pill('effective garbage', record.effective_is_garbage)}
            </div>
            <p><strong>Reason:</strong> ${esc(judgment.reason || record.execution_error || record.judgment_parse_error || '—')}</p>
            ${judgment.answer_span ? `<p><strong>Answer span:</strong> ${esc(judgment.answer_span)}</p>` : ''}
            ${judgment.gold_snippet_span ? `<p><strong>Gold snippet span:</strong> ${esc(judgment.gold_snippet_span)}</p>` : ''}
            ${judgment.gold_extracted_page_span ? `<p><strong>Gold page span:</strong> ${esc(judgment.gold_extracted_page_span)}</p>` : ''}
            ${judgment.garbage_reason ? `<p><strong>Garbage reason:</strong> ${esc(judgment.garbage_reason)}</p>` : ''}
            <details class="raw-response">
              <summary>Page fetch and garbage precheck</summary>
              <pre>${esc(JSON.stringify({ page_fetch: pageFetch, document_garbage_precheck: precheck, effective_is_garbage: record.effective_is_garbage }, null, 2))}</pre>
              ${pageFetch.artifact_path ? `<div style="padding: 10px;"><button class="btn" type="button" onclick="loadPageArtifact('${esc(pageFetch.artifact_path)}')">View extracted artifact</button></div>` : ''}
            </details>
            <details class="raw-response">
              <summary>Full judgment JSON</summary>
              <pre>${esc(JSON.stringify(judgment, null, 2))}</pre>
            </details>
            <details class="raw-response">
              <summary>Kimi prompt and response</summary>
              <pre>${esc(JSON.stringify({ request_snapshot: request, llm_response: rawResponse }, null, 2))}</pre>
            </details>
          </div>
        </article>
      `;
    }

    function renderTrace(trace) {
      const metrics = trace.metrics || {};
      $('traceDetail').innerHTML = `
        <section class="panel hero">
          <h2>${esc(trace.query_id || trace.trace_id)}</h2>
          <div class="tiny">${esc(trace.trace_id)} · ${esc(trace.provider_id)} / ${esc(trace.model_id)} · line ${esc(trace._jsonl_line_num)}</div>
          <p>${esc(trace.question)}</p>
          <div class="metrics">
            ${pill('failed', trace.failed)}
            ${pill('answered', trace.answered)}
            ${pill('exact match', metrics.exact_match)}
            ${pill('gold hit', metrics.gold_document_hit)}
            ${pill('ceiling', trace.ceiling_hit)}
          </div>
          <div class="answer">
            <div class="answer-box"><label>Final</label>${esc(trace.final_answer || '—')}</div>
            <div class="answer-box"><label>Gold</label>${esc(trace.gold_answer || '—')}</div>
            <div class="answer-box"><label>Searches</label>${esc(trace.total_search_calls || 0)}</div>
            <div class="answer-box"><label>Fetches</label>${esc(trace.total_fetch_calls || 0)}</div>
            <div class="answer-box"><label>Tokens</label>${esc((trace.total_prompt_tokens || 0) + (trace.total_completion_tokens || 0))}</div>
          </div>
        </section>
        <section class="section">
          <h3>Timeline</h3>
          ${renderTimeline(trace)}
        </section>
        <section class="section">
          <h3>Metrics</h3>
          <pre>${esc(JSON.stringify(metrics, null, 2))}</pre>
        </section>
        <section class="section">
          <h3>Gold URLs</h3>
          ${(trace.gold_urls || []).map(url => `<div><a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a></div>`).join('') || '<div class="tiny">No gold URLs.</div>'}
        </section>
        <section class="section">
          <h3>Iterations</h3>
          ${(trace.iterations || []).map(renderIteration).join('')}
        </section>
        <section class="section" id="pageArtifactPanel"></section>
      `;
    }

    function renderTimeline(trace) {
      const rows = (trace.iterations || []).map(iteration => {
        const queries = (iteration.searches || []).map(search => esc(short(search.search_query, 130))).join('<br>') || '<span class="tiny">none</span>';
        const resultCount = (iteration.searches || []).reduce((sum, search) => sum + (((search.search_response || {}).results || []).length), 0);
        const fetches = (iteration.fetches || []).map(fetch => esc(short(fetch.url, 130))).join('<br>') || '<span class="tiny">none</span>';
        const usage = iteration.llm_usage || {};
        return `
          <tr>
            <td>${esc(iteration.iteration_num)}</td>
            <td>${esc(iteration.agent_decision)}</td>
            <td>${queries}</td>
            <td>${resultCount}</td>
            <td>${fetches}</td>
            <td>${esc(usage.prompt_tokens || 0)} / ${esc(usage.completion_tokens || 0)}</td>
            <td>${Math.round(iteration.llm_latency_ms || 0)} ms</td>
          </tr>
        `;
      }).join('');
      return `<table><thead><tr><th>Iter</th><th>Decision</th><th>Search Query</th><th>Results</th><th>Fetch URL</th><th>Tokens</th><th>Latency</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    function renderIteration(iteration) {
      const request = iteration.llm_request || {};
      const config = {};
      ['provider', 'model_id', 'endpoint', 'deployment', 'api_version', 'temperature', 'max_tokens_field', 'max_tokens', 'tool_choice'].forEach(key => {
        if (key in request) config[key] = request[key];
      });
      const messages = (request.messages || []).map((message, index) => renderMessage(message, index)).join('');
      const searches = (iteration.searches || []).map(renderSearch).join('') || '<div class="tiny" style="padding: 10px;">No search calls after this response.</div>';
      const fetches = (iteration.fetches || []).map(renderFetch).join('') || '<div class="tiny" style="padding: 10px;">No fetch_page calls after this response.</div>';
      const toolCalls = iteration.llm_tool_calls || [];
      return `
        <details class="block" open>
          <summary>
            <div class="iteration-head">
              <span>Iteration ${esc(iteration.iteration_num)} · ${esc(iteration.agent_decision)}</span>
              <span class="tiny">${Math.round(iteration.llm_latency_ms || 0)} ms</span>
            </div>
          </summary>
          <details class="message" open>
            <summary>LLM request snapshot · ${(request.messages || []).length} messages</summary>
            <pre>${esc(JSON.stringify(config, null, 2))}</pre>
            ${messages}
          </details>
          <details class="message" open>
            <summary>LLM response · ${toolCalls.length} tool call(s)</summary>
            <pre>${esc(iteration.llm_response || 'No assistant text content.')}</pre>
            <pre>${esc(JSON.stringify(toolCalls, null, 2))}</pre>
          </details>
          <details class="message" open>
            <summary>Searches performed after this response</summary>
            ${searches}
          </details>
          <details class="message" open>
            <summary>Fetches performed after this response</summary>
            ${fetches}
          </details>
        </details>
      `;
    }

    function renderMessage(message, index) {
      const content = message.content || '';
      const toolCalls = message.tool_calls || [];
      return `
        <details class="message ${esc(message.role || '')}">
          <summary>message ${index} · role=${esc(message.role)} · ${content.length.toLocaleString()} chars ${toolCalls.length ? `· ${toolCalls.length} tool call(s)` : ''}</summary>
          ${content ? `<pre>${esc(content)}</pre>` : '<div class="tiny" style="padding: 10px;">No text content.</div>'}
          ${toolCalls.length ? `<pre>${esc(JSON.stringify(toolCalls, null, 2))}</pre>` : ''}
        </details>
      `;
    }

    function renderSearch(search) {
      const response = search.search_response || {};
      const results = response.results || [];
      return `
        <details class="block" open>
          <summary>${esc(short(search.search_query, 160))} · ${results.length} results · ${Math.round(response.latency_ms || 0)} ms</summary>
          ${results.map(renderResult).join('') || '<div class="tiny" style="padding: 10px;">No results.</div>'}
          <details class="raw-response">
            <summary>Full raw provider response</summary>
            <pre>${esc(JSON.stringify(response.raw_response || {}, null, 2))}</pre>
          </details>
        </details>
      `;
    }

    function renderFetch(fetch) {
      const pageFetch = fetch.page_fetch || {};
      return `
        <details class="block" open>
          <summary>${esc(short(fetch.url, 180))} · source rank ${esc(fetch.source_rank || '—')} · ${esc(pageFetch.fetch_status || 'unknown')} · ${Number(pageFetch.extracted_text_chars || 0).toLocaleString()} chars</summary>
          <div style="padding: 10px;">
            <div class="tiny">Reason: ${esc(fetch.reason || '—')}</div>
            <div class="tiny">Requested document: ${esc(fetch.requested_document_id || '—')} · source document: ${esc(fetch.source_document_id || '—')}</div>
            <div class="tiny">Seen in search results: ${yn(fetch.seen_in_search_results)} · retrieval=${esc(fetch.source_retrieval_id || '—')} · query=${esc(short(fetch.source_search_query || '', 160))}</div>
            <div class="tiny">Title: ${esc(fetch.source_title || '')}</div>
            <div class="tiny">Domain: ${esc(fetch.source_domain || '')}</div>
            ${fetch.source_snippet ? `<p>${esc(fetch.source_snippet)}</p>` : ''}
            ${renderPageFetch(pageFetch)}
          </div>
        </details>
      `;
    }

    function renderResult(result) {
      const metadata = result.provider_metadata || {};
      const extra = metadata.extra_snippets || [];
      const pageFetch = result.page_fetch || null;
      return `
        <article class="result">
          <div class="rank">#${esc(result.rank)}</div>
          <div>
            <h4>${esc(result.title)}</h4>
            <div class="tiny">document_id=${esc(result.document_id || '—')}</div>
            <a href="${esc(result.url)}" target="_blank" rel="noreferrer">${esc(result.url)}</a>
            <div class="tiny">${esc(result.domain || '')}</div>
            <p>${esc(result.snippet || '')}</p>
            ${extra.length ? `<details><summary class="tiny">extra snippets (${extra.length})</summary><ul>${extra.slice(0, 4).map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
            ${pageFetch ? renderPageFetch(pageFetch) : ''}
          </div>
        </article>
      `;
    }

    function renderPageFetch(pageFetch) {
      const path = pageFetch.artifact_path || '';
      return `
        <details class="raw-response">
          <summary>Extracted page · ${esc(pageFetch.fetch_status)} · ${esc(pageFetch.extractor || 'none')} · ${Number(pageFetch.extracted_text_chars || 0).toLocaleString()} chars</summary>
          <div style="padding: 10px;">
            <div class="tiny">Backend: ${esc(pageFetch.fetch_backend || 'local')}</div>
            <div class="tiny">HTTP ${esc(pageFetch.http_status || '—')} · ${esc(pageFetch.content_type || 'unknown type')}</div>
            <div class="tiny">Final URL: ${esc(pageFetch.final_url || '')}</div>
            ${pageFetch.reader_url ? `<div class="tiny">Reader URL: ${esc(pageFetch.reader_url)}</div>` : ''}
            <div class="tiny">Artifact: ${esc(path)}</div>
            ${path ? `<button class="btn" type="button" onclick="loadPageArtifact('${esc(path)}')">View extracted artifact</button>` : ''}
          </div>
          <pre>${esc(short(pageFetch.extracted_text || '', 4000))}</pre>
        </details>
      `;
    }

    async function loadPageArtifact(path) {
      const panel = $('pageArtifactPanel');
      if (!panel) return;
      panel.innerHTML = '<div class="empty">Loading page artifact…</div>';
      try {
        const params = new URLSearchParams({ path });
        const artifact = await api(`/api/page-artifact?${params}`);
        const extraction = artifact.extraction || {};
        panel.innerHTML = `
          <h3>Extracted Page Artifact</h3>
          <details class="block" open>
            <summary>${esc(artifact.search_context?.title || artifact.url)} · ${Number(extraction.text_chars || 0).toLocaleString()} chars</summary>
            <div style="padding: 10px;">
              <div><a href="${esc(artifact.final_url || artifact.url)}" target="_blank" rel="noreferrer">${esc(artifact.final_url || artifact.url)}</a></div>
              <div class="tiny">method=${esc(extraction.method)} · status=${esc(extraction.status)} · fetched=${esc(artifact.fetched_at)}</div>
              <div class="tiny">artifact=${esc(path)}</div>
            </div>
            <pre>${esc(extraction.text || '')}</pre>
          </details>
        `;
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (error) {
        panel.innerHTML = `<div class="error">${esc(error.message || error)}</div>`;
      }
    }

    let searchTimer = null;
    $('rowSearch').addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.page = 1; loadRows().catch(showError); }, 180);
    });
    $('pageSize').addEventListener('change', () => { state.page = 1; loadRows().catch(showError); });
    $('prevPage').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadRows().catch(showError); } });
    $('nextPage').addEventListener('click', () => { state.page += 1; loadRows().catch(showError); });
    $('refresh').addEventListener('click', async () => {
      try {
        await loadFiles();
        if (state.selectedFile) {
          await loadSummary();
          await loadRows();
        }
      } catch (error) {
        showError(error);
      }
    });

    loadFiles().catch(showError);
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the live SearchAPI trace dashboard.")
    parser.add_argument("--trace-dir", default=DEFAULT_TRACE_DIR)
    parser.add_argument("--judge-dir", default=DEFAULT_JUDGE_DIR)
    parser.add_argument("--page-cache-dir", default=DEFAULT_PAGE_CACHE_DIR)
    parser.add_argument("--provider-comparison-dir", default=DEFAULT_PROVIDER_COMPARISON_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    trace_dir = Path(args.trace_dir)
    judge_dir = Path(args.judge_dir)
    page_cache_dir = Path(args.page_cache_dir)
    provider_comparison_dir = Path(args.provider_comparison_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    judge_dir.mkdir(parents=True, exist_ok=True)
    page_cache_dir.mkdir(parents=True, exist_ok=True)

    handler = DashboardHandler
    comparison_store = ProviderComparisonStore(provider_comparison_dir)
    handler.store = TraceStore(trace_dir, page_cache_dir)
    handler.comparison_store = comparison_store
    handler.judge_store = JudgeStore(judge_dir, comparison_store)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(
        "Trace dashboard serving "
        f"{trace_dir.resolve()}, {judge_dir.resolve()}, and {provider_comparison_dir.resolve()} at {url}"
    )
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping trace dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
