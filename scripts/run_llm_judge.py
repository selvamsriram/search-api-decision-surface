#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import html
import json
import os
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from searchapi_eval.config import load_env_file
from searchapi_eval.evaluation.llm_judge import (
    deterministic_garbage_precheck,
    document_id,
    parse_json_object,
    render_document_judge_prompt,
)
from searchapi_eval.evaluation.trace_analysis import iter_results, latest_by_query_id, load_jsonl, provider_label
from searchapi_eval.models.azure_openai import AzureOpenAIChatClient
from searchapi_eval.providers.base import normalize_url


async def main_async() -> None:
    load_env_file()
    args = parser().parse_args()
    if (args.cache_jsonl or args.reuse_query_url_duplicates) and args.concurrency > 1:
        print("Cache/duplicate reuse is sequential; overriding --concurrency to 1.", flush=True)
        args.concurrency = 1
    started_at = time.monotonic()
    traces = _load_latest_traces(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    client = _build_kimi_client(args) if args.execute else None
    rate_limiter = RateLimiter(requests_per_minute=args.rate_limit_rpm, tokens_per_minute=args.rate_limit_tpm)
    cache = _load_judge_cache(args.cache_jsonl)
    records = [record for trace in traces for record in _records_for_trace(trace, args)]
    completed_records = _load_completed_records(output) if args.resume else []
    completed_keys = {_record_key(record) for record in completed_records}
    query_url_reuse_cache = _build_query_url_reuse_cache(
        list(cache.values()) + completed_records,
        enabled=args.reuse_query_url_duplicates,
    )
    initial_count = len(records)
    if completed_keys:
        records = [record for record in records if _record_key(record) not in completed_keys]
    reuse_estimate = _estimate_reuse_counts(
        records,
        cache=cache,
        query_url_reuse_cache=query_url_reuse_cache,
        use_query_url_duplicates=args.reuse_query_url_duplicates,
    )

    _log_run_header(
        args,
        traces,
        initial_count,
        len(completed_keys),
        len(records),
        cache,
        query_url_reuse_cache,
        reuse_estimate,
    )

    mode_flag = "a" if args.resume and output.exists() else "w"
    stats = {
        "written": 0,
        "cache_reused": 0,
        "exact_cache_reused": 0,
        "query_url_duplicate_reused": 0,
        "fresh_calls": 0,
        "execution_errors": 0,
        "parse_errors": 0,
        "total_tokens": 0,
        "reused_source_tokens": 0,
    }
    with _output_lock(output):
        with output.open(mode_flag, encoding="utf-8") as handle:
            if client and args.concurrency > 1:
                count = await _execute_concurrent(records, client, handle, args.concurrency, rate_limiter, args.parse_retries)
            else:
                count = 0
                for record in records:
                    output_record = record
                    cache_key = _record_key(record)
                    cached_record = _matching_cache_record(cache, record)
                    if cached_record:
                        output_record = _cached_output_record(cached_record, record)
                        stats["cache_reused"] += 1
                        stats["exact_cache_reused"] += 1
                    elif args.reuse_query_url_duplicates and (
                        duplicate_record := _matching_query_url_reuse_record(query_url_reuse_cache, record)
                    ):
                        output_record = _query_url_duplicate_output_record(duplicate_record, record)
                        stats["cache_reused"] += 1
                        stats["query_url_duplicate_reused"] += 1
                    elif client:
                        await _execute_record(
                            output_record,
                            client,
                            rate_limiter=rate_limiter,
                            parse_retries=args.parse_retries,
                            execution_retries=args.execution_retries,
                            throttle_sleep_seconds=args.throttle_sleep_seconds,
                        )
                        output_record["cache_reused"] = False
                        output_record["duplicate_reused"] = False
                        output_record["reuse_type"] = "none"
                        stats["fresh_calls"] += 1
                    else:
                        output_record["cache_reused"] = False
                        output_record["duplicate_reused"] = False
                        output_record["reuse_type"] = "none"
                    _write_record(handle, output_record)
                    _register_query_url_reuse_record(
                        query_url_reuse_cache,
                        output_record,
                        enabled=args.reuse_query_url_duplicates,
                    )
                    count += 1
                    _update_stats(stats, output_record)
                    if args.log_records or count % args.progress_every == 0:
                        _log_record_progress(count, len(records), output_record, stats, started_at)

    mode = "executed" if args.execute else "prepared"
    skipped = len(completed_keys)
    resume_note = f" ({skipped} skipped by --resume)" if skipped else ""
    print(
        f"{mode.title()} {count} judge record(s) -> {output}{resume_note}; "
        f"cache_reused={stats['cache_reused']} exact_cache={stats['exact_cache_reused']} "
        f"query_url_duplicates={stats['query_url_duplicate_reused']} fresh_calls={stats['fresh_calls']} "
        f"execution_errors={stats['execution_errors']} parse_errors={stats['parse_errors']} "
        f"fresh_tokens={stats['total_tokens']} reused_source_tokens={stats['reused_source_tokens']} "
        f"elapsed={_format_seconds(time.monotonic() - started_at)}",
        flush=True,
    )
    if not args.execute:
        print("No LLM calls were made. Review prompts, add Kimi Azure keys, then rerun with --execute.")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Prepare or run Kimi K2.6 judge prompts over trace JSONL files.")
    cli.add_argument("--trace", action="append", required=True, help="Trace JSONL. Repeat for each provider.")
    cli.add_argument("--output", default="results/llm_judge/kimi_k26_judge_prompts.jsonl")
    cli.add_argument("--query-id", action="append", help="Restrict to one or more query IDs.")
    cli.add_argument("--provider", action="append", help="Restrict to provider IDs.")
    cli.add_argument("--limit-queries", type=int, default=None)
    cli.add_argument("--max-docs-per-query", type=int, default=0, help="0 means judge every result URL in the trace.")
    cli.add_argument("--max-docs-per-search", type=int, default=0, help="0 means judge every result URL per search call.")
    cli.add_argument(
        "--max-document-chars",
        type=int,
        default=0,
        help="Maximum extracted-page characters to include in the judge prompt. 0 means use the full model-visible extracted text.",
    )
    cli.add_argument("--execute", action="store_true", help="Actually call Kimi on Azure. Default only writes prompt records.")
    cli.add_argument("--resume", action="store_true", help="Append to the output file and skip document IDs already present.")
    cli.add_argument("--cache-jsonl", action="append", default=[], help="Reuse valid judge rows from this JSONL when provider/query/retrieval/rank/url match. Can be repeated.")
    cli.add_argument(
        "--reuse-query-url-duplicates",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Reuse valid judgments for duplicate normalized URLs within the same SealQA query. "
            "The key intentionally ignores provider/retrieval/rank and separates snippet-only from page-visible rows."
        ),
    )
    cli.add_argument("--concurrency", type=int, default=1, help="Number of judge calls to run in parallel.")
    cli.add_argument("--rate-limit-rpm", type=float, default=float(os.environ.get("KIMI_RATE_LIMIT_RPM", "0")), help="Optional request-per-minute throttle. 0 disables.")
    cli.add_argument("--rate-limit-tpm", type=float, default=float(os.environ.get("KIMI_RATE_LIMIT_TPM", "0")), help="Optional token-per-minute throttle using actual response usage. 0 disables.")
    cli.add_argument("--progress-every", type=int, default=int(os.environ.get("KIMI_JUDGE_PROGRESS_EVERY", "25")))
    cli.add_argument("--log-records", action=argparse.BooleanOptionalAction, default=os.environ.get("KIMI_JUDGE_LOG_RECORDS", "true").lower() not in {"0", "false", "no"})
    cli.add_argument("--parse-retries", type=int, default=int(os.environ.get("KIMI_JUDGE_PARSE_RETRIES", "1")))
    cli.add_argument("--execution-retries", type=int, default=int(os.environ.get("KIMI_JUDGE_EXECUTION_RETRIES", "2")))
    cli.add_argument("--throttle-sleep-seconds", type=float, default=float(os.environ.get("KIMI_THROTTLE_SLEEP_SECONDS", "60")))
    cli.add_argument(
        "--kimi-env-slot",
        default=os.environ.get("KIMI_AZURE_ENV_SLOT", ""),
        help=(
            "Optional Kimi Azure env slot suffix, e.g. 2 reads KIMI_AZURE_OPENAI_ENDPOINT_2 "
            "and KIMI_AZURE_OPENAI_API_KEY_2. Default uses the primary Kimi env vars."
        ),
    )
    cli.add_argument("--model-id", default=os.environ.get("KIMI_AZURE_MODEL_ID", "azure:kimi-k2.6"))
    cli.add_argument("--temperature", type=float, default=float(os.environ.get("KIMI_AZURE_TEMPERATURE", "0")))
    cli.add_argument("--max-tokens", type=int, default=int(os.environ.get("KIMI_AZURE_MAX_TOKENS", "8192")))
    cli.add_argument("--timeout-seconds", type=float, default=float(os.environ.get("KIMI_AZURE_TIMEOUT_SECONDS", "120")))
    return cli


@contextlib.contextmanager
def _output_lock(output: Path):
    lock_path = output.with_suffix(output.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                f"Another judge process is already writing {output}. "
                f"Wait for it to finish before starting a second writer for the same output."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


async def _execute_concurrent(
    records: list[dict[str, Any]],
    client: AzureOpenAIChatClient,
    handle: Any,
    concurrency: int,
    rate_limiter: "RateLimiter | None",
    parse_retries: int,
) -> int:
    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    count = 0

    async def worker(record: dict[str, Any]) -> None:
        nonlocal count
        async with semaphore:
            await _execute_record(record, client, rate_limiter=rate_limiter, parse_retries=parse_retries)
            async with write_lock:
                _write_record(handle, record)
                count += 1
                if count % 25 == 0:
                    print(f"Completed {count}/{len(records)} new judge record(s)", flush=True)

    await asyncio.gather(*(worker(record) for record in records))
    return count


async def _execute_record(
    record: dict[str, Any],
    client: AzureOpenAIChatClient,
    *,
    rate_limiter: "RateLimiter | None" = None,
    parse_retries: int = 0,
    execution_retries: int = 0,
    throttle_sleep_seconds: float = 60,
) -> None:
    attempts: list[dict[str, Any]] = []
    attempt_index = 0
    parse_attempts_left = parse_retries
    execution_attempts_left = execution_retries
    while True:
        if rate_limiter:
            await rate_limiter.wait_before_request()
        try:
            response = await client.chat(record["messages"], tools=[])
            response_json = response.to_json()
            record["llm_response"] = response_json
            attempts.append(response_json)
            try:
                record["judgment"] = parse_json_object(response.content)
                record.pop("judgment_parse_error", None)
                break
            except Exception as error:
                record["judgment_parse_error"] = str(error)
                record["judgment"] = None
                if parse_attempts_left <= 0:
                    break
                parse_attempts_left -= 1
        except Exception as error:
            message = str(error)
            record["execution_error"] = message
            record["judgment"] = None
            if _looks_like_throttle(message) and execution_attempts_left > 0:
                execution_attempts_left -= 1
                record.setdefault("execution_retry_events", []).append(
                    {
                        "reason": "throttle_or_rate_limit",
                        "message": message,
                        "sleep_seconds": throttle_sleep_seconds,
                        "attempt_index": attempt_index,
                    }
                )
                print(
                    f"THROTTLE query={record.get('query_id')} rank={record.get('rank')} "
                    f"sleeping {throttle_sleep_seconds:.1f}s before retry; error={message}",
                    flush=True,
                )
                await asyncio.sleep(throttle_sleep_seconds)
                attempt_index += 1
                continue
            break
        finally:
            if rate_limiter:
                usage = (record.get("llm_response") or {}).get("usage") or {}
                await rate_limiter.note_response(int(usage.get("total_tokens") or 0))
        attempt_index += 1
    if len(attempts) > 1:
        record["llm_response_attempts"] = attempts
    if "llm_response" in record:
        try:
            record["request_snapshot"] = client.request_snapshot(record["messages"], tools=[])
        except Exception:
            pass
    record["effective_is_garbage"] = bool(
        record["document_garbage_precheck"]["is_garbage"]
        or ((record.get("judgment") or {}).get("is_garbage") is True)
    )


class RateLimiter:
    def __init__(self, *, requests_per_minute: float = 0, tokens_per_minute: float = 0) -> None:
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self._lock = asyncio.Lock()
        self._next_available_at = 0.0

    async def wait_before_request(self) -> None:
        async with self._lock:
            wait_seconds = self._next_available_at - time.monotonic()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

    async def note_response(self, total_tokens: int) -> None:
        async with self._lock:
            delay_seconds = 0.0
            if self.requests_per_minute > 0:
                delay_seconds = max(delay_seconds, 60.0 / self.requests_per_minute)
            if self.tokens_per_minute > 0 and total_tokens > 0:
                delay_seconds = max(delay_seconds, (total_tokens / self.tokens_per_minute) * 60.0)
            self._next_available_at = max(self._next_available_at, time.monotonic()) + delay_seconds


def _write_record(handle: Any, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()


def _log_run_header(
    args: argparse.Namespace,
    traces: list[dict[str, Any]],
    initial_count: int,
    completed_count: int,
    remaining_count: int,
    cache: dict[tuple[str, str, str, int, str], dict[str, Any]],
    query_url_reuse_cache: dict[tuple[str, str, str], dict[str, Any]],
    reuse_estimate: dict[str, int],
) -> None:
    provider_counts: dict[str, int] = {}
    for trace in traces:
        provider = str(trace.get("provider_id") or "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
    print("Kimi judge run configuration", flush=True)
    print(f"  traces={len(traces)} providers={provider_counts}", flush=True)
    print(f"  output={args.output}", flush=True)
    print(
        "  scope="
        f"max_docs_per_query={args.max_docs_per_query or 'ALL'} "
        f"max_docs_per_search={args.max_docs_per_search or 'ALL'} "
        f"max_document_chars={args.max_document_chars or 'FULL'}",
        flush=True,
    )
    print(
        f"  execute={args.execute} resume={args.resume} concurrency={args.concurrency} "
        f"parse_retries={args.parse_retries} execution_retries={args.execution_retries}",
        flush=True,
    )
    print(f"  kimi_env_slot={args.kimi_env_slot or 'primary'}", flush=True)
    print(
        f"  throttling: proactive_rpm={args.rate_limit_rpm or 'OFF'} "
        f"proactive_tpm={args.rate_limit_tpm or 'OFF'} reactive_sleep={args.throttle_sleep_seconds}s",
        flush=True,
    )
    print(
        f"  records: generated={initial_count} already_completed={completed_count} "
        f"remaining_to_write={remaining_count}",
        flush=True,
    )
    print(
        f"  exact_cache: files={len(args.cache_jsonl)} valid_keys={len(cache)} "
        f"hits_available_in_remaining={reuse_estimate['exact_cache_hits']}",
        flush=True,
    )
    print(
        f"  query_url_duplicate_reuse: enabled={args.reuse_query_url_duplicates} "
        f"seed_keys={len(query_url_reuse_cache)} "
        f"hits_available_in_remaining={reuse_estimate['query_url_duplicate_hits']} "
        f"fresh_needed={reuse_estimate['fresh_needed']}",
        flush=True,
    )
    if args.reuse_query_url_duplicates and len(provider_counts) > 1:
        print(
            "  WARNING: query-url duplicate reuse ignores provider_id; this run includes multiple providers.",
            flush=True,
        )


def _update_stats(stats: dict[str, int], record: dict[str, Any]) -> None:
    stats["written"] += 1
    if record.get("execution_error"):
        stats["execution_errors"] += 1
    if record.get("judgment_parse_error"):
        stats["parse_errors"] += 1
    usage = (record.get("llm_response") or {}).get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)
    if record.get("cache_reused"):
        stats["reused_source_tokens"] += tokens
    else:
        stats["total_tokens"] += tokens


def _log_record_progress(
    count: int,
    total: int,
    record: dict[str, Any],
    stats: dict[str, int],
    started_at: float,
) -> None:
    usage = (record.get("llm_response") or {}).get("usage") or {}
    usage_tokens = int(usage.get("total_tokens") or 0)
    token_text = f"tokens={usage_tokens}"
    if record.get("cache_reused"):
        token_text = f"tokens=0 source_tokens={usage_tokens}"
    judgment = record.get("judgment") or {}
    status = "CACHE" if record.get("cache_reused") else "FRESH"
    if record.get("duplicate_reused"):
        status = "QUERY_URL_DUP"
    if record.get("execution_error"):
        status = "EXEC_ERROR"
    elif record.get("judgment_parse_error"):
        status = "PARSE_ERROR"
    print(
        f"[{count}/{total}] {status} "
        f"query={record.get('query_id')} rank={record.get('rank')} "
        f"source={record.get('page_fetch_source')} fetched={record.get('model_fetched_document')} "
        f"{token_text} "
        f"gold_snip={judgment.get('gold_answer_in_snippets')} "
        f"gold_page={judgment.get('gold_answer_in_extracted_page')} "
        f"errors=e{stats['execution_errors']}/p{stats['parse_errors']} "
        f"cache={stats['cache_reused']} dup={stats['query_url_duplicate_reused']} fresh={stats['fresh_calls']} "
        f"reuse={record.get('reuse_type') or 'none'} "
        f"elapsed={_format_seconds(time.monotonic() - started_at)}",
        flush=True,
    )


def _format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _looks_like_throttle(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("429", "rate limit", "ratelimit", "too many requests", "throttle"))


def _load_completed_records(output: Path) -> list[dict[str, Any]]:
    if not output.exists():
        return []
    completed: list[dict[str, Any]] = []
    with output.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not _valid_judge_record(record):
                continue
            record = dict(record)
            record["_cache_source"] = str(output)
            record["_cache_source_line_num"] = line_num
            completed.append(record)
    return completed


def _load_judge_cache(paths: list[str]) -> dict[tuple[str, str, str, int, str], dict[str, Any]]:
    cache: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
    for path_text in paths:
        path = Path(path_text)
        if not path.exists():
            print(f"WARNING cache file does not exist: {path}", flush=True)
            continue
        loaded = 0
        valid = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_num, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                loaded += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    print(f"WARNING skipping malformed cache row {path}:{line_num}: {error}", flush=True)
                    continue
                if not _valid_judge_record(record):
                    continue
                record = dict(record)
                record["_cache_source"] = str(path)
                record["_cache_source_line_num"] = line_num
                cache[_record_key(record)] = record
                valid += 1
        print(f"Loaded cache {path}: rows={loaded} valid={valid} cumulative_valid_keys={len(cache)}", flush=True)
    return cache


def _matching_cache_record(
    cache: dict[tuple[str, str, str, int, str], dict[str, Any]],
    target_record: dict[str, Any],
) -> dict[str, Any] | None:
    candidate = cache.get(_record_key(target_record))
    if not candidate:
        return None
    if _prompt_content(candidate) != _prompt_content(target_record):
        return None
    return candidate


def _build_query_url_reuse_cache(
    records: list[dict[str, Any]],
    *,
    enabled: bool,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    reuse_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not enabled:
        return reuse_cache
    for record in records:
        _register_query_url_reuse_record(reuse_cache, record, enabled=enabled)
    return reuse_cache


def _register_query_url_reuse_record(
    reuse_cache: dict[tuple[str, str, str], dict[str, Any]],
    record: dict[str, Any],
    *,
    enabled: bool,
) -> None:
    if not enabled or not _valid_judge_record(record):
        return
    key = _query_url_reuse_key(record)
    if not key:
        return
    reuse_cache.setdefault(key, record)


def _matching_query_url_reuse_record(
    reuse_cache: dict[tuple[str, str, str], dict[str, Any]],
    target_record: dict[str, Any],
) -> dict[str, Any] | None:
    key = _query_url_reuse_key(target_record)
    if not key:
        return None
    return reuse_cache.get(key)


def _estimate_reuse_counts(
    records: list[dict[str, Any]],
    *,
    cache: dict[tuple[str, str, str, int, str], dict[str, Any]],
    query_url_reuse_cache: dict[tuple[str, str, str], dict[str, Any]],
    use_query_url_duplicates: bool,
) -> dict[str, int]:
    exact_cache_hits = 0
    query_url_duplicate_hits = 0
    fresh_needed = 0
    simulated_query_url_cache = dict(query_url_reuse_cache)
    for record in records:
        exact = _matching_cache_record(cache, record)
        if exact:
            exact_cache_hits += 1
            _register_query_url_reuse_record(
                simulated_query_url_cache,
                exact,
                enabled=use_query_url_duplicates,
            )
            continue
        if use_query_url_duplicates and _matching_query_url_reuse_record(simulated_query_url_cache, record):
            query_url_duplicate_hits += 1
            continue
        fresh_needed += 1
        _register_query_url_reuse_record(
            simulated_query_url_cache,
            record,
            enabled=False,
        )
        if use_query_url_duplicates:
            placeholder = dict(record)
            placeholder["judgment"] = {}
            _register_query_url_reuse_record(simulated_query_url_cache, placeholder, enabled=True)
    return {
        "exact_cache_hits": exact_cache_hits,
        "query_url_duplicate_hits": query_url_duplicate_hits,
        "fresh_needed": fresh_needed,
    }


def _valid_judge_record(record: dict[str, Any]) -> bool:
    return (
        record.get("schema_version") == "kimi_judge_record_v3"
        and isinstance(record.get("judgment"), dict)
        and not record.get("execution_error")
        and not record.get("judgment_parse_error")
        and bool(record.get("provider_id"))
        and bool(record.get("query_id"))
        and bool(record.get("retrieval_id"))
        and bool(record.get("url"))
    )


def _record_key(record: dict[str, Any]) -> tuple[str, str, str, int, str]:
    return (
        str(record.get("provider_id") or ""),
        str(record.get("query_id") or ""),
        str(record.get("retrieval_id") or ""),
        int(record.get("rank") or 0),
        str(record.get("url") or ""),
    )


def _query_url_reuse_key(record: dict[str, Any]) -> tuple[str, str, str] | None:
    query_id = str(record.get("query_id") or "")
    normalized = _record_normalized_url(record)
    if not query_id or not normalized:
        return None
    surface_class = str(record.get("judge_surface_class") or _infer_judge_surface_class(record))
    if surface_class == "page_visible":
        page_signature = str(record.get("judge_page_fetch_signature") or _page_signature_from_prompt(record) or "")
        if not page_signature:
            return None
        surface_key = f"{surface_class}:{page_signature}"
    else:
        surface_key = surface_class
    return (query_id, normalized, surface_key)


def _record_normalized_url(record: dict[str, Any]) -> str:
    normalized = record.get("normalized_url")
    if normalized:
        return str(normalized)
    url = str(record.get("url") or "")
    return normalize_url(url) if url else ""


def _infer_judge_surface_class(record: dict[str, Any]) -> str:
    if record.get("page_fetch_source") and record.get("page_fetch_source") != "none":
        return "page_visible"
    page_fetch = record.get("page_fetch") or {}
    if any(page_fetch.get(key) for key in ("fetch_status", "http_status", "artifact_path", "final_url", "reader_url")):
        return "page_visible"
    if "<extracted_page>" in _prompt_content(record):
        return "page_visible"
    return "snippet_only"


def _page_signature_from_prompt(record: dict[str, Any]) -> str:
    content = _prompt_content(record)
    match = re.search(r"<extracted_page>\s*(.*?)\s*</extracted_page>", content, flags=re.DOTALL)
    if not match:
        return ""
    return _hash_json({"extracted_page_xml": html.unescape(match.group(1)).strip()})


def _cached_output_record(cached_record: dict[str, Any], target_record: dict[str, Any]) -> dict[str, Any]:
    return _reused_output_record(cached_record, target_record, reuse_type="exact_cache")


def _query_url_duplicate_output_record(source_record: dict[str, Any], target_record: dict[str, Any]) -> dict[str, Any]:
    return _reused_output_record(source_record, target_record, reuse_type="query_url_duplicate")


def _reused_output_record(source_record: dict[str, Any], target_record: dict[str, Any], *, reuse_type: str) -> dict[str, Any]:
    output = deepcopy(target_record)
    output["judgment"] = deepcopy(source_record.get("judgment"))
    if source_record.get("llm_response") is not None:
        output["llm_response"] = deepcopy(source_record.get("llm_response"))
    if source_record.get("llm_response_attempts") is not None:
        output["llm_response_attempts"] = deepcopy(source_record.get("llm_response_attempts"))
    output.pop("execution_error", None)
    output.pop("judgment_parse_error", None)
    output["cache_reused"] = True
    output["duplicate_reused"] = reuse_type == "query_url_duplicate"
    output["reuse_type"] = reuse_type
    output["cache_source"] = source_record.get("_cache_source") or source_record.get("cache_source")
    output["cache_source_line_num"] = source_record.get("_cache_source_line_num") or source_record.get("cache_source_line_num")
    output["cache_key"] = {
        "provider_id": target_record.get("provider_id"),
        "query_id": target_record.get("query_id"),
        "retrieval_id": target_record.get("retrieval_id"),
        "rank": target_record.get("rank"),
        "url": target_record.get("url"),
    }
    output["target_document_id"] = target_record.get("document_id")
    output["reuse_source"] = {
        "document_id": source_record.get("document_id"),
        "query_id": source_record.get("query_id"),
        "retrieval_id": source_record.get("retrieval_id"),
        "rank": source_record.get("rank"),
        "url": source_record.get("url"),
        "normalized_url": _record_normalized_url(source_record),
        "search_query": source_record.get("search_query"),
        "reuse_type": source_record.get("reuse_type"),
        "cache_source": source_record.get("_cache_source") or source_record.get("cache_source"),
        "cache_source_line_num": source_record.get("_cache_source_line_num") or source_record.get("cache_source_line_num"),
    }
    output["reuse_key"] = {
        "exact_record_key": list(_record_key(source_record)),
        "query_url_reuse_key": list(_query_url_reuse_key(source_record) or ()),
    }
    output["reuse_prompt_content_match"] = _prompt_content(source_record) == _prompt_content(target_record)
    output["source_judge_document_id"] = source_record.get("document_id")
    garbage_precheck = output.get("document_garbage_precheck") or {"is_garbage": False}
    output["effective_is_garbage"] = bool(
        garbage_precheck.get("is_garbage")
        or ((output.get("judgment") or {}).get("is_garbage") is True)
    )
    return output


def _prompt_content(record: dict[str, Any]) -> str:
    request_snapshot = record.get("request_snapshot") or {}
    messages = request_snapshot.get("messages") or record.get("messages") or []
    if not messages:
        return ""
    return str(messages[-1].get("content") or "")


def _load_latest_traces(args: argparse.Namespace) -> list[dict[str, Any]]:
    query_filter = set(args.query_id or [])
    provider_filter = set(args.provider or [])
    traces: list[dict[str, Any]] = []
    for path in args.trace:
        rows = load_jsonl(path)
        label = provider_label(path, rows)
        latest = latest_by_query_id(rows)
        for trace in latest.values():
            trace.setdefault("provider_id", label)
            if query_filter and trace.get("query_id") not in query_filter:
                continue
            if provider_filter and trace.get("provider_id") not in provider_filter:
                continue
            traces.append(trace)
    traces.sort(key=lambda row: (row.get("query_id") or "", row.get("provider_id") or ""))
    if args.limit_queries is not None:
        traces = traces[: args.limit_queries]
    return traces


def _records_for_trace(trace: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    fetch_tool_index = _fetch_tool_index(trace)
    query_doc_count = 0
    for retrieval in trace.get("retrievals") or []:
        results = (retrieval.get("search_response") or {}).get("results") or []
        if args.max_docs_per_search:
            results = results[: args.max_docs_per_search]
        for result in results:
            query_doc_count += 1
            if args.max_docs_per_query and query_doc_count > args.max_docs_per_query:
                break
            records.append(_record_for_result(trace, retrieval, result, args, fetch_tool_index))
        if args.max_docs_per_query and query_doc_count >= args.max_docs_per_query:
            break
    return records


def _record_for_result(
    trace: dict[str, Any],
    retrieval: dict[str, Any],
    result: dict[str, Any],
    args: argparse.Namespace,
    fetch_tool_index: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    result_for_judge = deepcopy(result)
    fetch_tool_record = _matching_fetch_tool_record(retrieval, result, fetch_tool_index)
    page_fetch_source = "search_result_auto_fetch" if result_for_judge.get("page_fetch") else "none"
    if fetch_tool_record:
        result_for_judge["page_fetch"] = deepcopy(fetch_tool_record.get("page_fetch") or {})
        page_fetch_source = "fetch_tool"
    doc_id = document_id(trace, retrieval, result)
    page_fetch = result_for_judge.get("page_fetch") or {}
    garbage_precheck = deterministic_garbage_precheck(result_for_judge)
    normalized = normalize_url(str(result.get("url") or ""))
    surface_class = _judge_surface_class(page_fetch_source, page_fetch)
    messages = render_document_judge_prompt(
        trace,
        retrieval,
        result_for_judge,
        max_extracted_chars=args.max_document_chars,
    )
    record = {
        "schema_version": "kimi_judge_record_v3",
        "judge_type": "document_support",
        "query_id": trace.get("query_id"),
        "provider_id": trace.get("provider_id"),
        "document_id": doc_id,
        "retrieval_id": retrieval.get("retrieval_id"),
        "source_document_id": result.get("document_id"),
        "search_query": retrieval.get("search_query"),
        "rank": result.get("rank"),
        "title": result.get("title"),
        "url": result.get("url"),
        "normalized_url": normalized,
        "domain": result.get("domain"),
        "page_fetch_source": page_fetch_source,
        "judge_surface_class": surface_class,
        "judge_snippet_surface_signature": _snippet_surface_signature(result_for_judge),
        "judge_page_fetch_signature": "",
        "model_fetched_document": bool(fetch_tool_record),
        "fetch_tool_record_id": (fetch_tool_record or {}).get("fetch_id"),
        "fetch_tool_requested_document_id": (fetch_tool_record or {}).get("requested_document_id"),
        "fetch_tool_iteration_num": (fetch_tool_record or {}).get("iteration_num"),
        "page_fetch": {
            "fetch_backend": page_fetch.get("fetch_backend"),
            "fetch_status": page_fetch.get("fetch_status"),
            "http_status": page_fetch.get("http_status"),
            "content_type": page_fetch.get("content_type"),
            "extractor": page_fetch.get("extractor"),
            "extracted_text_chars": page_fetch.get("extracted_text_chars"),
            "extracted_text_tokens_estimate": page_fetch.get("extracted_text_tokens_estimate"),
            "artifact_path": page_fetch.get("artifact_path"),
            "final_url": page_fetch.get("final_url"),
            "reader_url": page_fetch.get("reader_url"),
        },
        "document_garbage_precheck": garbage_precheck,
        "effective_is_garbage": garbage_precheck["is_garbage"],
        "messages": messages,
    }
    if surface_class == "page_visible":
        record["judge_page_fetch_signature"] = _page_signature_from_prompt(record)
    return record


def _judge_surface_class(page_fetch_source: str, page_fetch: dict[str, Any]) -> str:
    if page_fetch_source != "none" or page_fetch:
        return "page_visible"
    return "snippet_only"


def _snippet_surface_signature(result: dict[str, Any]) -> str:
    metadata = result.get("provider_metadata") or {}
    return _hash_json(
        {
            "title": result.get("title") or "",
            "url": normalize_url(str(result.get("url") or "")) if result.get("url") else "",
            "domain": result.get("domain") or "",
            "snippet": result.get("snippet") or "",
            "extra_snippets": metadata.get("extra_snippets") or [],
        }
    )


def _hash_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fetch_tool_index(trace: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fetch in trace.get("fetches") or []:
        retrieval_id = fetch.get("source_retrieval_id")
        document_id_value = fetch.get("source_document_id") or fetch.get("requested_document_id")
        if retrieval_id and document_id_value:
            index.setdefault((str(retrieval_id), str(document_id_value)), []).append(fetch)
    return index


def _matching_fetch_tool_record(
    retrieval: dict[str, Any],
    result: dict[str, Any],
    fetch_tool_index: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    retrieval_id = str(retrieval.get("retrieval_id") or "")
    candidate_document_ids = [result.get("document_id")]
    retrieval_index = retrieval.get("retrieval_index")
    if retrieval_index and result.get("rank"):
        candidate_document_ids.append(f"s{retrieval_index}r{result.get('rank')}")

    for candidate_document_id in candidate_document_ids:
        if not candidate_document_id:
            continue
        candidates = fetch_tool_index.get((retrieval_id, str(candidate_document_id))) or []
        if candidates:
            return _best_fetch_tool_record(candidates)

    result_url = result.get("url")
    result_rank = result.get("rank")
    fallback_candidates: list[dict[str, Any]] = []
    for (indexed_retrieval_id, _), candidates in fetch_tool_index.items():
        if indexed_retrieval_id != retrieval_id:
            continue
        for candidate in candidates:
            if result_url and candidate.get("url") == result_url:
                fallback_candidates.append(candidate)
            elif result_rank and candidate.get("source_rank") == result_rank:
                fallback_candidates.append(candidate)
    return _best_fetch_tool_record(fallback_candidates)


def _best_fetch_tool_record(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            0 if (item.get("page_fetch") or {}).get("fetch_status") == "success" else 1,
            int(item.get("iteration_num") or 0),
            str(item.get("fetch_id") or ""),
        ),
    )[0]


def _build_kimi_client(args: argparse.Namespace) -> AzureOpenAIChatClient:
    slot = _kimi_env_slot(args)
    endpoint = _kimi_env("KIMI_AZURE_OPENAI_ENDPOINT", slot, allow_primary_fallback=False)
    api_key = _kimi_env("KIMI_AZURE_OPENAI_API_KEY", slot, allow_primary_fallback=False)
    if not endpoint or not api_key:
        suffix = f"_{slot}" if slot else ""
        raise RuntimeError(
            f"KIMI_AZURE_OPENAI_ENDPOINT{suffix} and KIMI_AZURE_OPENAI_API_KEY{suffix} are required "
            f"for --kimi-env-slot {slot or 'primary'}."
        )
    return AzureOpenAIChatClient(
        endpoint=endpoint,
        api_key=api_key,
        deployment=_kimi_env("KIMI_AZURE_OPENAI_DEPLOYMENT", slot, default=""),
        api_version=_kimi_env(
            "KIMI_AZURE_OPENAI_API_VERSION",
            slot,
            default=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        ),
        model_id=_kimi_env("KIMI_AZURE_MODEL_ID", slot, default=args.model_id),
        temperature=float(_kimi_env("KIMI_AZURE_TEMPERATURE", slot, default=str(args.temperature))),
        max_tokens=int(_kimi_env("KIMI_AZURE_MAX_TOKENS", slot, default=str(args.max_tokens))),
        timeout_seconds=float(_kimi_env("KIMI_AZURE_TIMEOUT_SECONDS", slot, default=str(args.timeout_seconds))),
        max_tokens_field=_kimi_env("KIMI_AZURE_OPENAI_MAX_TOKENS_FIELD", slot, default="max_tokens"),
        input_price_per_1k_usd=float(_kimi_env("KIMI_AZURE_INPUT_PRICE_PER_1K_USD", slot, default="0")),
        output_price_per_1k_usd=float(_kimi_env("KIMI_AZURE_OUTPUT_PRICE_PER_1K_USD", slot, default="0")),
    )


def _kimi_env_slot(args: argparse.Namespace) -> str:
    slot = str(args.kimi_env_slot or "").strip()
    return slot[1:] if slot.startswith("_") else slot


def _kimi_env(name: str, slot: str, *, default: str = "", allow_primary_fallback: bool = True) -> str:
    if slot:
        slot_name = f"{name}_{slot}"
        value = os.environ.get(slot_name)
        if value:
            return value
        if not allow_primary_fallback:
            return ""
    return os.environ.get(name, default)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
