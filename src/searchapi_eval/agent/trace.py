from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "searchapi_trace_v1"

ABSTENTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"cannot determine",
        r"unable to find",
        r"insufficient information",
        r"no final answer",
    )
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex}"


def extract_final_answer(text: str) -> tuple[str, bool]:
    match = re.search(r"FINAL ANSWER:\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
    answer = match.group(1).strip() if match else text.strip()
    answer = re.sub(r"\s+", " ", answer)
    answered = bool(match and answer)
    if any(pattern.search(answer) for pattern in ABSTENTION_PATTERNS):
        answered = False
    return answer, answered


def make_trace(
    *,
    query_record: dict[str, Any],
    provider_id: str,
    model_id: str,
    run_id: str,
    max_iterations: int,
    max_results: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": new_trace_id(),
        "run_id": run_id,
        "started_at": utc_now_iso(),
        "ended_at": None,
        "dataset": {
            "name": "vtllms/sealqa",
            "subset": "seal_hard",
            "selection": "phase1_100",
        },
        "query_id": query_record["query_id"],
        "source_index": query_record.get("source_index"),
        "question": query_record["question"],
        "gold_answer": query_record.get("answer"),
        "gold_urls": query_record.get("urls", []),
        "metadata": {
            "freshness": query_record.get("freshness"),
            "topic": query_record.get("topic"),
            "search_results": query_record.get("search_results"),
            "question_types": query_record.get("question_types", []),
            "effective_year": query_record.get("effective_year"),
        },
        "provider_id": provider_id,
        "model_id": model_id,
        "config": {
            "max_iterations": max_iterations,
            "max_results_per_search": max_results,
        },
        "iterations": [],
        "retrievals": [],
        "final_response": None,
        "final_answer": None,
        "answered": False,
        "ceiling_hit": False,
        "total_search_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_cost_usd": 0.0,
        "wall_time_seconds": None,
        "failed": False,
        "failure_stage": None,
        "errors": [],
    }


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
