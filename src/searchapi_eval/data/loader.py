from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def stable_query_id(question: str) -> str:
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
    return f"sealhard_{digest}"


def load_sealhard_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("query_id", stable_query_id(row["question"]))
            row.setdefault("source_index", index)
            rows.append(row)
    return rows


def public_query_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_id": row["query_id"],
        "source_index": row["source_index"],
        "question": row["question"],
        "answer": row["answer"],
        "urls": row.get("urls", []),
        "freshness": row.get("freshness"),
        "question_types": row.get("question_types", []),
        "effective_year": row.get("effective_year"),
        "search_results": row.get("search_results"),
        "topic": row.get("topic"),
        "canary": row.get("canary"),
        "golds": row.get("golds", []),
    }
