#!/usr/bin/env python3
"""Compute Task 1 support-split numbers from existing paper artifacts.

This script does not call providers, rerun the agent, rerun the judge, or touch
paper sources. It reads the canonical Kimi per-URL judge JSONLs and the semantic
audit TSV, then writes reproducible audit tables for the pre-fetch/post-fetch
support split.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROVIDERS = ("brave", "tavily", "firecrawl")
PLABEL = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}
DECISION_CELLS = ("smart", "missed", "blind", "noop")


@dataclass
class QueryState:
    pre_fetch_support_urls: set[str] = field(default_factory=set)
    page_extracted_gold_urls: set[str] = field(default_factory=set)
    fetched_urls: set[str] = field(default_factory=set)
    legacy_visible_support_urls: set[str] = field(default_factory=set)
    valid_snippet_rows: int = 0
    valid_page_rows: int = 0
    pre_fetch_support_rows: int = 0
    page_visible_pre_fetch_support_rows: int = 0
    page_extracted_gold_rows: int = 0
    snippet_contains_gold_rows: int = 0
    snippet_gold_in_snippets_rows: int = 0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_judge_paths(root: Path) -> dict[str, Path]:
    return {
        provider: root / "results" / "llm_judge" / f"kimi_document_judge_surface_v3_{provider}_100_all_visible.jsonl"
        for provider in PROVIDERS
    }


def is_lfs_pointer(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:200]
    except UnicodeDecodeError:
        return False
    return head.startswith("version https://git-lfs.github.com/spec/v1")


def load_semantic(path: Path) -> dict[str, dict[str, bool]]:
    semantic: dict[str, dict[str, bool]] = {provider: {} for provider in PROVIDERS}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            provider = (row.get("provider") or "").lower()
            query_id = row.get("query_id") or ""
            if provider not in semantic or not query_id:
                continue
            semantic[provider][query_id] = bool(int(row.get("semantic_match") or 0))
    for provider in PROVIDERS:
        n = len(semantic[provider])
        if n != 100:
            raise RuntimeError(f"Expected 100 semantic rows for {provider}, found {n}")
    return semantic


def valid_judge_row(row: dict[str, Any]) -> bool:
    return (
        row.get("schema_version") == "kimi_judge_record_v3"
        and isinstance(row.get("judgment"), dict)
        and not row.get("execution_error")
        and not row.get("judgment_parse_error")
        and bool(row.get("provider_id"))
        and bool(row.get("query_id"))
        and bool(row.get("url"))
    )


def url_id(row: dict[str, Any]) -> str:
    return str(row.get("normalized_url") or row.get("url") or "")


def load_provider_states(path: Path, semantic_queries: dict[str, bool]) -> tuple[dict[str, QueryState], dict[str, int]]:
    states: dict[str, QueryState] = {query_id: QueryState() for query_id in semantic_queries}
    totals = {
        "judge_total_rows": 0,
        "judge_valid_rows": 0,
        "judge_invalid_rows": 0,
    }
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            totals["judge_total_rows"] += 1
            row = json.loads(line)
            if not valid_judge_row(row):
                totals["judge_invalid_rows"] += 1
                continue
            query_id = row.get("query_id") or ""
            if query_id not in states:
                continue
            totals["judge_valid_rows"] += 1
            state = states[query_id]
            judgment = row["judgment"]
            surface_class = row.get("judge_surface_class")
            url = url_id(row)

            if row.get("model_fetched_document"):
                state.fetched_urls.add(url)

            if judgment.get("contains_gold_answer"):
                state.legacy_visible_support_urls.add(url)

            # Fetched URLs are stored as page_visible rows instead of as
            # duplicate snippet_only + page_visible rows. The judge still emits
            # gold_answer_in_snippets for page_visible rows, and that field is
            # explicitly limited to snippet/extra_snippet text. Count it as
            # pre-fetch support. Do not use page_visible contains_gold_answer
            # here because it may be true only because the fetched page text
            # contains the gold answer.
            pre_fetch_support = bool(judgment.get("gold_answer_in_snippets")) or (
                surface_class == "snippet_only" and bool(judgment.get("contains_gold_answer"))
            )
            if pre_fetch_support:
                state.pre_fetch_support_rows += 1
                state.pre_fetch_support_urls.add(url)

            if surface_class == "snippet_only":
                state.valid_snippet_rows += 1
                contains_gold = bool(judgment.get("contains_gold_answer"))
                gold_in_snippets = bool(judgment.get("gold_answer_in_snippets"))
                if contains_gold:
                    state.snippet_contains_gold_rows += 1
                if gold_in_snippets:
                    state.snippet_gold_in_snippets_rows += 1
            elif surface_class == "page_visible":
                state.valid_page_rows += 1
                state.fetched_urls.add(url)
                if pre_fetch_support:
                    state.page_visible_pre_fetch_support_rows += 1
                if judgment.get("gold_answer_in_extracted_page"):
                    state.page_extracted_gold_rows += 1
                    state.page_extracted_gold_urls.add(url)

    return states, totals


def decision_cell(state: QueryState) -> str:
    pre_fetch_support = bool(state.pre_fetch_support_urls)
    fetched_pre_fetch_support_url = bool(state.pre_fetch_support_urls & state.fetched_urls)
    fetched_any_url = bool(state.fetched_urls)
    if pre_fetch_support and fetched_pre_fetch_support_url:
        return "smart"
    if pre_fetch_support:
        return "missed"
    if fetched_any_url:
        return "blind"
    return "noop"


def summarize_provider(
    provider: str,
    states: dict[str, QueryState],
    semantic: dict[str, bool],
    judge_totals: dict[str, int],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    partition = {cell: {"query_count": 0, "semantic_correct_count": 0, "semantic_correct_rate": None} for cell in DECISION_CELLS}
    query_rows: list[dict[str, Any]] = []

    pre_fetch_support_q = 0
    post_fetch_discovered_support_q = 0
    trajectory_visible_support_q = 0
    legacy_visible_support_q = 0

    snippet_rows = 0
    page_rows = 0
    pre_fetch_support_rows = 0
    page_visible_pre_fetch_support_rows = 0
    page_extracted_gold_rows = 0
    post_fetch_discovered_support_rows = 0
    snippet_contains_gold_rows = 0
    snippet_gold_in_snippets_rows = 0

    for query_id in sorted(semantic):
        state = states[query_id]
        pre_fetch_support = bool(state.pre_fetch_support_urls)
        post_fetch_discovered_support = (not pre_fetch_support) and bool(state.page_extracted_gold_urls)
        trajectory_visible_support = pre_fetch_support or post_fetch_discovered_support
        fetched_any_url = bool(state.fetched_urls)
        fetched_pre_fetch_support_url = bool(state.pre_fetch_support_urls & state.fetched_urls)
        cell = decision_cell(state)
        correct = bool(semantic[query_id])

        pre_fetch_support_q += int(pre_fetch_support)
        post_fetch_discovered_support_q += int(post_fetch_discovered_support)
        trajectory_visible_support_q += int(trajectory_visible_support)
        legacy_visible_support_q += int(bool(state.legacy_visible_support_urls))

        snippet_rows += state.valid_snippet_rows
        page_rows += state.valid_page_rows
        pre_fetch_support_rows += state.pre_fetch_support_rows
        page_visible_pre_fetch_support_rows += state.page_visible_pre_fetch_support_rows
        page_extracted_gold_rows += state.page_extracted_gold_rows
        snippet_contains_gold_rows += state.snippet_contains_gold_rows
        snippet_gold_in_snippets_rows += state.snippet_gold_in_snippets_rows
        if post_fetch_discovered_support:
            post_fetch_discovered_support_rows += state.page_extracted_gold_rows

        partition[cell]["query_count"] += 1
        partition[cell]["semantic_correct_count"] += int(correct)

        query_rows.append(
            {
                "provider": provider,
                "query_id": query_id,
                "pre_fetch_surface_support": int(pre_fetch_support),
                "post_fetch_discovered_support": int(post_fetch_discovered_support),
                "trajectory_visible_support": int(trajectory_visible_support),
                "legacy_visible_support": int(bool(state.legacy_visible_support_urls)),
                "fetched_any_url": int(fetched_any_url),
                "fetched_pre_fetch_support_url": int(fetched_pre_fetch_support_url),
                "decision_cell": cell.upper(),
                "semantic_correct": int(correct),
                "pre_fetch_support_url_count": len(state.pre_fetch_support_urls),
                "page_extracted_gold_url_count": len(state.page_extracted_gold_urls),
                "fetched_url_count": len(state.fetched_urls),
                "valid_snippet_rows": state.valid_snippet_rows,
                "valid_page_rows": state.valid_page_rows,
            }
        )

    for cell in DECISION_CELLS:
        n = partition[cell]["query_count"]
        c = partition[cell]["semantic_correct_count"]
        partition[cell]["semantic_correct_rate"] = round(c / n, 4) if n else None

    summary = {
        "provider": provider,
        "provider_label": PLABEL[provider],
        "query_count": len(semantic),
        "pre_fetch_surface_support_q": pre_fetch_support_q,
        "post_fetch_discovered_support_q": post_fetch_discovered_support_q,
        "trajectory_visible_support_q": trajectory_visible_support_q,
        "no_pre_fetch_surface_support_q": len(semantic) - pre_fetch_support_q,
        "legacy_visible_support_q": legacy_visible_support_q,
        "snippet_only_valid_rows": snippet_rows,
        "page_visible_valid_rows": page_rows,
        "pre_fetch_support_rows": pre_fetch_support_rows,
        "page_visible_pre_fetch_support_rows": page_visible_pre_fetch_support_rows,
        "snippet_contains_gold_rows": snippet_contains_gold_rows,
        "snippet_gold_in_snippets_rows": snippet_gold_in_snippets_rows,
        "page_extracted_gold_rows": page_extracted_gold_rows,
        "post_fetch_discovered_support_rows": post_fetch_discovered_support_rows,
        "judge_total_rows": judge_totals["judge_total_rows"],
        "judge_valid_rows": judge_totals["judge_valid_rows"],
        "judge_invalid_rows": judge_totals["judge_invalid_rows"],
        "decision_partition": partition,
    }

    decision_rows = []
    for cell in DECISION_CELLS:
        values = partition[cell]
        decision_rows.append(
            {
                "provider": provider,
                "cell": cell.upper(),
                "query_count": values["query_count"],
                "semantic_correct_count": values["semantic_correct_count"],
                "semantic_correct_rate": "" if values["semantic_correct_rate"] is None else values["semantic_correct_rate"],
            }
        )

    return summary, decision_rows, query_rows


def validate_outputs(provider_summaries: dict[str, dict[str, Any]], query_rows: list[dict[str, Any]]) -> None:
    rows_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in query_rows:
        rows_by_provider[row["provider"]].append(row)

    for provider in PROVIDERS:
        summary = provider_summaries[provider]
        rows = rows_by_provider[provider]
        if len(rows) != 100:
            raise RuntimeError(f"Expected 100 query rows for {provider}, found {len(rows)}")
        partition_total = sum(
            summary["decision_partition"][cell]["query_count"]
            for cell in DECISION_CELLS
        )
        if partition_total != 100:
            raise RuntimeError(f"Decision cells for {provider} sum to {partition_total}, not 100")
        overlap = [
            row["query_id"]
            for row in rows
            if row["pre_fetch_surface_support"] and row["post_fetch_discovered_support"]
        ]
        if overlap:
            raise RuntimeError(f"{provider} has overlapping pre/post support queries: {overlap[:5]}")
        bad_union = [
            row["query_id"]
            for row in rows
            if bool(row["trajectory_visible_support"])
            != (bool(row["pre_fetch_surface_support"]) or bool(row["post_fetch_discovered_support"]))
        ]
        if bad_union:
            raise RuntimeError(f"{provider} has bad trajectory union rows: {bad_union[:5]}")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pct_text(correct: int, total: int) -> str:
    if total == 0:
        return "--"
    return f"{round(100 * correct / total):.0f}%"


def write_summary_md(path: Path, provider_summaries: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# Task 1 support split numbers",
        "",
        "These numbers are computed from existing Kimi judge JSONLs and `results/em_vs_semantic_audit.tsv`.",
        "",
        "## Support counts",
        "",
        "| Provider | Pre-fetch support | Post-fetch discovered | Trajectory-visible | No pre-fetch support | Legacy visible support |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for provider in PROVIDERS:
        s = provider_summaries[provider]
        lines.append(
            f"| {s['provider_label']} | {s['pre_fetch_surface_support_q']} | "
            f"{s['post_fetch_discovered_support_q']} | {s['trajectory_visible_support_q']} | "
            f"{s['no_pre_fetch_surface_support_q']} | {s['legacy_visible_support_q']} |"
        )

    lines.extend(
        [
            "",
            "## Decision partition using pre-fetch support",
            "",
            "Each cell is `queries / semantic-correct answers (rate)`.",
            "",
            "| Provider | SMART | MISSED | BLIND | NO-OP |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for provider in PROVIDERS:
        s = provider_summaries[provider]
        cells = []
        for cell in DECISION_CELLS:
            values = s["decision_partition"][cell]
            n = values["query_count"]
            c = values["semantic_correct_count"]
            cells.append(f"{n} / {c} ({pct_text(c, n)})")
        lines.append(f"| {s['provider_label']} | " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## Valid row counts",
            "",
            "| Provider | Snippet-only rows | Page-visible rows | Pre-fetch support rows | Page-visible pre-fetch rows | Page extracted-gold rows | Post-fetch discovered rows |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for provider in PROVIDERS:
        s = provider_summaries[provider]
        lines.append(
            f"| {s['provider_label']} | {s['snippet_only_valid_rows']} | {s['page_visible_valid_rows']} | "
            f"{s['pre_fetch_support_rows']} | {s['page_visible_pre_fetch_support_rows']} | "
            f"{s['page_extracted_gold_rows']} | "
            f"{s['post_fetch_discovered_support_rows']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_terminal_summary(provider_summaries: dict[str, dict[str, Any]]) -> None:
    print("Task 1 support split numbers")
    print()
    print("Support counts")
    print("provider,pre_fetch,post_fetch_discovered,trajectory_visible,no_pre_fetch,legacy_visible")
    for provider in PROVIDERS:
        s = provider_summaries[provider]
        print(
            f"{provider},{s['pre_fetch_surface_support_q']},{s['post_fetch_discovered_support_q']},"
            f"{s['trajectory_visible_support_q']},{s['no_pre_fetch_surface_support_q']},"
            f"{s['legacy_visible_support_q']}"
        )
    print()
    print("Decision partition using pre-fetch support: queries/correct(rate)")
    for provider in PROVIDERS:
        s = provider_summaries[provider]
        cells = []
        for cell in DECISION_CELLS:
            values = s["decision_partition"][cell]
            n = values["query_count"]
            c = values["semantic_correct_count"]
            cells.append(f"{cell.upper()}={n}/{c}({pct_text(c, n)})")
        print(f"{provider}: " + ", ".join(cells))


def main() -> None:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-tsv", type=Path, default=root / "results" / "em_vs_semantic_audit.tsv")
    parser.add_argument("--output-dir", type=Path, default=root / "results" / "task1_support_split")
    args = parser.parse_args()

    judge_paths = default_judge_paths(root)
    input_paths = [args.semantic_tsv, *judge_paths.values()]
    missing = [str(path) for path in input_paths if not path.exists()]
    if missing:
        raise SystemExit("Missing input artifact(s): " + ", ".join(missing))
    pointers = [str(path.relative_to(root)) for path in input_paths if is_lfs_pointer(path)]
    if pointers:
        raise SystemExit("Input artifact(s) are still Git LFS pointers: " + ", ".join(pointers))

    semantic = load_semantic(args.semantic_tsv)
    provider_summaries: dict[str, dict[str, Any]] = {}
    all_decision_rows: list[dict[str, Any]] = []
    all_query_rows: list[dict[str, Any]] = []

    for provider in PROVIDERS:
        states, judge_totals = load_provider_states(judge_paths[provider], semantic[provider])
        summary, decision_rows, query_rows = summarize_provider(provider, states, semantic[provider], judge_totals)
        provider_summaries[provider] = summary
        all_decision_rows.extend(decision_rows)
        all_query_rows.extend(query_rows)

    validate_outputs(provider_summaries, all_query_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    provider_rows = [
        {
            "provider": provider,
            "query_count": s["query_count"],
            "pre_fetch_surface_support_q": s["pre_fetch_surface_support_q"],
            "post_fetch_discovered_support_q": s["post_fetch_discovered_support_q"],
            "trajectory_visible_support_q": s["trajectory_visible_support_q"],
            "no_pre_fetch_surface_support_q": s["no_pre_fetch_surface_support_q"],
            "legacy_visible_support_q": s["legacy_visible_support_q"],
            "snippet_only_valid_rows": s["snippet_only_valid_rows"],
            "page_visible_valid_rows": s["page_visible_valid_rows"],
            "pre_fetch_support_rows": s["pre_fetch_support_rows"],
            "page_visible_pre_fetch_support_rows": s["page_visible_pre_fetch_support_rows"],
            "snippet_contains_gold_rows": s["snippet_contains_gold_rows"],
            "snippet_gold_in_snippets_rows": s["snippet_gold_in_snippets_rows"],
            "page_extracted_gold_rows": s["page_extracted_gold_rows"],
            "post_fetch_discovered_support_rows": s["post_fetch_discovered_support_rows"],
            "judge_total_rows": s["judge_total_rows"],
            "judge_valid_rows": s["judge_valid_rows"],
            "judge_invalid_rows": s["judge_invalid_rows"],
        }
        for provider, s in provider_summaries.items()
    ]

    write_csv(
        args.output_dir / "provider_support_split.csv",
        provider_rows,
        [
            "provider",
            "query_count",
            "pre_fetch_surface_support_q",
            "post_fetch_discovered_support_q",
            "trajectory_visible_support_q",
            "no_pre_fetch_surface_support_q",
            "legacy_visible_support_q",
            "snippet_only_valid_rows",
            "page_visible_valid_rows",
            "pre_fetch_support_rows",
            "page_visible_pre_fetch_support_rows",
            "snippet_contains_gold_rows",
            "snippet_gold_in_snippets_rows",
            "page_extracted_gold_rows",
            "post_fetch_discovered_support_rows",
            "judge_total_rows",
            "judge_valid_rows",
            "judge_invalid_rows",
        ],
    )
    write_csv(
        args.output_dir / "decision_partition.csv",
        all_decision_rows,
        ["provider", "cell", "query_count", "semantic_correct_count", "semantic_correct_rate"],
    )
    write_csv(
        args.output_dir / "provider_query_support.csv",
        all_query_rows,
        [
            "provider",
            "query_id",
            "pre_fetch_surface_support",
            "post_fetch_discovered_support",
            "trajectory_visible_support",
            "legacy_visible_support",
            "fetched_any_url",
            "fetched_pre_fetch_support_url",
            "decision_cell",
            "semantic_correct",
            "pre_fetch_support_url_count",
            "page_extracted_gold_url_count",
            "fetched_url_count",
            "valid_snippet_rows",
            "valid_page_rows",
        ],
    )

    payload = {
        "definitions": {
            "pre_fetch_surface_support": "Provider-query has a valid snippet_only row with contains_gold_answer or gold_answer_in_snippets true, or a valid page_visible row with gold_answer_in_snippets true. Page-visible rows are included for gold_answer_in_snippets because fetched documents are not duplicated as separate snippet-only records.",
            "post_fetch_discovered_support": "Provider-query has no pre-fetch support and has a valid page_visible row with gold_answer_in_extracted_page true.",
            "trajectory_visible_support": "Union of pre_fetch_surface_support and post_fetch_discovered_support.",
            "smart": "Pre-fetch support exists and a pre-fetch-support-bearing URL was fetched.",
            "missed": "Pre-fetch support exists and no pre-fetch-support-bearing URL was fetched.",
            "blind": "No pre-fetch support exists and at least one URL was fetched.",
            "noop": "No pre-fetch support exists and no URL was fetched.",
        },
        "inputs": {
            "semantic_tsv": str(args.semantic_tsv.relative_to(root)),
            "judge_jsonls": {provider: str(path.relative_to(root)) for provider, path in judge_paths.items()},
        },
        "providers": provider_summaries,
    }
    (args.output_dir / "provider_support_split.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_summary_md(args.output_dir / "summary.md", provider_summaries)
    print_terminal_summary(provider_summaries)
    print()
    print(f"Wrote {args.output_dir.relative_to(root)}")


if __name__ == "__main__":
    main()
