"""Build a human-validation queue for the Kimi per-URL oracle.

The queue is a stratified sample of row/label pairs from the Kimi judge JSONLs.
Each case asks a human to validate one Kimi label value:

    contains_gold_answer
    contradicts_gold_answer
    is_garbage

Sampling is balanced over provider x surface type x label, and within each cell
tries to include both positive and negative Kimi decisions. No model calls are
made; this only reads committed traces and judge rows.

Usage:
    python scripts/build_judge_validation_queue.py
    JUDGE_VALIDATION_CAP_PER_CELL=12 python scripts/build_judge_validation_queue.py
"""
from __future__ import annotations

import csv
import html
import json
import os
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "results" / "task2_judge_validation"

PROVIDERS = ["brave", "tavily", "firecrawl"]
SURFACES = ["snippet_only", "page_visible"]
LABELS = ["contains_gold_answer", "contradicts_gold_answer", "is_garbage"]

JUDGE_FILES = {
    "brave": ROOT / "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
    "tavily": ROOT / "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
    "firecrawl": ROOT / "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
}
TRACE_FILES = {
    "brave": ROOT / "data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl",
    "tavily": ROOT / "data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl",
    "firecrawl": ROOT / "data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl",
}

SEED = int(os.environ.get("JUDGE_VALIDATION_SEED", "20260629"))
CAP_PER_PROVIDER_SURFACE_LABEL = int(os.environ.get("JUDGE_VALIDATION_CAP_PER_CELL", "10"))
PAGE_EXCERPT_CHARS = int(os.environ.get("JUDGE_VALIDATION_PAGE_EXCERPT_CHARS", "16000"))

QUEUE_JSON = OUT_DIR / "judge_validation_queue.json"
SAMPLE_CSV = OUT_DIR / "judge_validation_sample.csv"

HUMAN_COLUMNS = [
    "human_value",
    "human_disagreement_pattern",
    "human_notes",
]

CSV_COLUMNS = [
    "case_id",
    "provider_id",
    "query_id",
    "surface",
    "label",
    "kimi_value",
    "rank",
    "title",
    "url",
    "domain",
    "question",
    "gold_answer",
    "model_final_answer",
    "search_query",
    "judge_contains_gold_answer",
    "judge_contradicts_gold_answer",
    "judge_is_garbage",
    "judge_gold_answer_in_snippets",
    "judge_gold_answer_in_extracted_page",
    "judge_supports_model_answer",
    "judge_confidence",
    "answer_span",
    "gold_snippet_span",
    "gold_extracted_page_span",
    "garbage_reason",
] + HUMAN_COLUMNS


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_traces() -> dict[tuple[str, str], dict[str, Any]]:
    traces: dict[tuple[str, str], dict[str, Any]] = {}
    for provider, path in TRACE_FILES.items():
        for row in read_jsonl(path):
            traces[(provider, row.get("query_id", ""))] = row
    return traces


def prompt_text(row: dict[str, Any]) -> str:
    messages = row.get("messages") or []
    if messages and isinstance(messages[-1], dict):
        return str(messages[-1].get("content") or "")
    return ""


def prompt_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    messages = row.get("messages") or []
    clean: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        clean.append(
            {
                "role": str(message.get("role") or ""),
                "content": str(message.get("content") or ""),
            }
        )
    return clean


def decode_html_entities(text: str) -> str:
    decoded = text
    for _ in range(3):
        next_decoded = html.unescape(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    return decoded


def tag_text_raw(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def tag_text(text: str, tag: str) -> str:
    return decode_html_entities(tag_text_raw(text, tag))


def tag_list_raw(text: str, tag: str) -> list[str]:
    return [
        m.strip()
        for m in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
    ]


def tag_list(text: str, tag: str) -> list[str]:
    return [decode_html_entities(m) for m in tag_list_raw(text, tag)]


def retrieved_document_text(text: str) -> str:
    """Return only the XML-ish document block passed to the judge.

    The judge prompt also contains literal tag names such as `<snippet>` in its
    instructions. Evidence extraction must be scoped to `<retrieved_document>`
    so those instructional mentions cannot be mistaken for document content.
    """
    return tag_text(text, "retrieved_document") or text


def retrieved_document_text_raw(text: str) -> str:
    return tag_text_raw(text, "retrieved_document") or text


def extracted_page_content(text: str) -> str:
    match = re.search(
        r"<extracted_page[^>]*>.*?<content[^>]*>(.*?)</content>.*?</extracted_page>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return decode_html_entities(match.group(1).strip()) if match else ""


def excerpt_around(content: str, spans: list[str], limit: int = PAGE_EXCERPT_CHARS) -> dict[str, Any]:
    if not content:
        return {"text": "", "truncated": False, "start": 0, "end": 0}
    clean_spans = [s for s in spans if s and s in content]
    if clean_spans:
        idx = content.find(clean_spans[0])
        half = max(0, (limit - len(clean_spans[0])) // 2)
        start = max(0, idx - half)
        end = min(len(content), start + limit)
        start = max(0, end - limit)
    else:
        start = 0
        end = min(len(content), limit)
    return {
        "text": content[start:end],
        "truncated": len(content) > (end - start),
        "start": start,
        "end": end,
        "total_chars": len(content),
    }


def case_id_for(row: dict[str, Any], label: str) -> str:
    bits = [
        row.get("provider_id", ""),
        row.get("query_id", ""),
        row.get("retrieval_id", ""),
        f"r{row.get('rank')}",
        row.get("judge_surface_class", ""),
        label,
    ]
    raw = "__".join(str(b) for b in bits)
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw)


def row_to_cases(row: dict[str, Any], trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    judgment = row.get("judgment") or {}
    surface = row.get("judge_surface_class") or "unknown"
    provider = row.get("provider_id") or ""
    text = prompt_text(row)
    messages = prompt_messages(row)
    document_text_raw = retrieved_document_text_raw(text)
    document_text = decode_html_entities(document_text_raw)
    question = (trace or {}).get("question") or tag_text(text, "question")
    gold_answer = (trace or {}).get("gold_answer") or tag_text(text, "gold_answer")
    model_answer = (trace or {}).get("final_answer") or tag_text(text, "model_final_answer")
    raw_snippet = tag_text_raw(document_text_raw, "snippet")
    raw_extra_snippets = tag_list_raw(document_text_raw, "extra_snippet")
    snippet = decode_html_entities(raw_snippet)
    extra_snippets = [decode_html_entities(x) for x in raw_extra_snippets]
    page_content = extracted_page_content(document_text)
    spans = [
        str(judgment.get("answer_span") or ""),
        str(judgment.get("gold_snippet_span") or ""),
        str(judgment.get("gold_extracted_page_span") or ""),
        str(gold_answer or ""),
        str(model_answer or ""),
    ]
    page_excerpt = excerpt_around(page_content, spans)
    page_fetch = row.get("page_fetch") or {}
    garbage_precheck = row.get("document_garbage_precheck") or {}

    common = {
        "provider_id": provider,
        "query_id": row.get("query_id"),
        "retrieval_id": row.get("retrieval_id"),
        "document_id": row.get("document_id"),
        "source_document_id": row.get("source_document_id"),
        "surface": surface,
        "rank": row.get("rank"),
        "title": row.get("title"),
        "url": row.get("url"),
        "normalized_url": row.get("normalized_url"),
        "domain": row.get("domain"),
        "search_query": row.get("search_query"),
        "question": question,
        "gold_answer": gold_answer,
        "model_final_answer": model_answer,
        "trace_id": (trace or {}).get("trace_id"),
        "run_id": (trace or {}).get("run_id"),
        "started_at": (trace or {}).get("started_at"),
        "snippet": snippet,
        "extra_snippets": extra_snippets,
        "raw_snippet": raw_snippet,
        "raw_extra_snippets": raw_extra_snippets,
        "raw_retrieved_document": document_text_raw,
        "page_excerpt": page_excerpt,
        "page_fetch": page_fetch,
        "garbage_precheck": garbage_precheck,
        "judgment": judgment,
        "judge_messages": messages,
        "judge_prompt": text,
        "judge_prompt_excerpt": text[:20000],
        "llm_response": row.get("llm_response") or {},
    }

    cases = []
    for label in LABELS:
        value = judgment.get(label)
        if not isinstance(value, bool):
            continue
        c = dict(common)
        c.update(
            {
                "case_id": case_id_for(row, label),
                "label": label,
                "kimi_value": value,
                "stratum": f"{provider}/{surface}/{label}",
            }
        )
        cases.append(c)
    return cases


def build_candidates() -> list[dict[str, Any]]:
    traces = load_traces()
    out: list[dict[str, Any]] = []
    for provider, path in JUDGE_FILES.items():
        for row in read_jsonl(path):
            trace = traces.get((provider, row.get("query_id", "")))
            out.extend(row_to_cases(row, trace))
    return out


def balanced_take(cases: list[dict[str, Any]], cap: int, rnd: random.Random) -> list[dict[str, Any]]:
    positives = sorted([c for c in cases if c["kimi_value"] is True], key=lambda c: c["case_id"])
    negatives = sorted([c for c in cases if c["kimi_value"] is False], key=lambda c: c["case_id"])
    half = cap // 2

    def take(pool: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
        if len(pool) <= n:
            return list(pool)
        return rnd.sample(pool, n)

    selected = take(positives, half) + take(negatives, cap - half)
    if len(selected) < cap:
        already = {c["case_id"] for c in selected}
        remainder = [c for c in positives + negatives if c["case_id"] not in already]
        selected += take(remainder, cap - len(selected))
    return sorted(selected, key=lambda c: c["case_id"])


def sample_cases(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rnd = random.Random(SEED)
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        by_cell[(c["provider_id"], c["surface"], c["label"])].append(c)

    selected: list[dict[str, Any]] = []
    strata: dict[str, Any] = {}
    for provider in PROVIDERS:
        for surface in SURFACES:
            for label in LABELS:
                pool = by_cell.get((provider, surface, label), [])
                if not pool:
                    continue
                take = balanced_take(pool, CAP_PER_PROVIDER_SURFACE_LABEL, rnd)
                key = f"{provider}/{surface}/{label}"
                positives = sum(1 for c in pool if c["kimi_value"] is True)
                negatives = sum(1 for c in pool if c["kimi_value"] is False)
                strata[key] = {
                    "provider": provider,
                    "surface": surface,
                    "label": label,
                    "population": len(pool),
                    "population_true": positives,
                    "population_false": negatives,
                    "sampled": len(take),
                    "sampled_true": sum(1 for c in take if c["kimi_value"] is True),
                    "sampled_false": sum(1 for c in take if c["kimi_value"] is False),
                }
                selected.extend(take)
    return selected, strata


def write_outputs(cases: list[dict[str, Any]], strata: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prior: dict[str, dict[str, str]] = {}
    if SAMPLE_CSV.exists():
        with SAMPLE_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                prior[row.get("case_id", "")] = {k: row.get(k, "") for k in HUMAN_COLUMNS}

    payload = {
        "meta": {
            "description": "Human validation queue for Kimi per-URL oracle labels.",
            "seed": SEED,
            "cap_per_provider_surface_label": CAP_PER_PROVIDER_SURFACE_LABEL,
            "labels": LABELS,
            "providers": PROVIDERS,
            "surfaces": SURFACES,
            "n_cases": len(cases),
            "strata": strata,
            "source_judge_files": {k: str(v.relative_to(ROOT)) for k, v in JUDGE_FILES.items()},
            "source_trace_files": {k: str(v.relative_to(ROOT)) for k, v in TRACE_FILES.items()},
        },
        "cases": cases,
    }
    QUEUE_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with SAMPLE_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for c in cases:
            judgment = c["judgment"]
            row = {
                "case_id": c["case_id"],
                "provider_id": c["provider_id"],
                "query_id": c["query_id"],
                "surface": c["surface"],
                "label": c["label"],
                "kimi_value": c["kimi_value"],
                "rank": c["rank"],
                "title": c["title"],
                "url": c["url"],
                "domain": c["domain"],
                "question": c["question"],
                "gold_answer": c["gold_answer"],
                "model_final_answer": c["model_final_answer"],
                "search_query": c["search_query"],
                "judge_contains_gold_answer": judgment.get("contains_gold_answer"),
                "judge_contradicts_gold_answer": judgment.get("contradicts_gold_answer"),
                "judge_is_garbage": judgment.get("is_garbage"),
                "judge_gold_answer_in_snippets": judgment.get("gold_answer_in_snippets"),
                "judge_gold_answer_in_extracted_page": judgment.get("gold_answer_in_extracted_page"),
                "judge_supports_model_answer": judgment.get("supports_model_answer"),
                "judge_confidence": judgment.get("confidence"),
                "answer_span": judgment.get("answer_span"),
                "gold_snippet_span": judgment.get("gold_snippet_span"),
                "gold_extracted_page_span": judgment.get("gold_extracted_page_span"),
                "garbage_reason": judgment.get("garbage_reason"),
            }
            for k in HUMAN_COLUMNS:
                row[k] = prior.get(c["case_id"], {}).get(k, "")
            writer.writerow(row)


def main() -> None:
    candidates = build_candidates()
    selected, strata = sample_cases(candidates)
    write_outputs(selected, strata)
    print(f"Built judge-validation queue: {len(selected)} cases")
    print(f"Seed: {SEED}; cap/provider-surface-label: {CAP_PER_PROVIDER_SURFACE_LABEL}")
    print(f"Wrote: {QUEUE_JSON.relative_to(ROOT)}")
    print(f"Wrote: {SAMPLE_CSV.relative_to(ROOT)}")
    for provider in PROVIDERS:
        n = sum(1 for c in selected if c["provider_id"] == provider)
        print(f"  {provider:9s} {n:3d}")


if __name__ == "__main__":
    main()
