#!/usr/bin/env python3
"""Paired-bootstrap uncertainty estimates for the decision-surface paper.

The bootstrap unit is the question ID. Each replicate resamples the 100
question IDs with replacement and recomputes provider metrics on the matched
Brave/Tavily/Firecrawl rows. This preserves the paired design of the study.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


PROVIDERS = ("brave", "tavily", "firecrawl")
PLABEL = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}
PAIRS = (("brave", "tavily"), ("brave", "firecrawl"), ("tavily", "firecrawl"))
DECISION_CELLS = ("SMART", "MISSED", "BLIND", "NOOP")


@dataclass
class QueryMetrics:
    correct: int = 0
    token_f1: float = 0.0
    pre_fetch_support: int = 0
    post_fetch_discovered_support: int = 0
    trajectory_visible_support: int = 0
    fetched_any_url: int = 0
    fetched_url_count: int = 0
    total_tokens: float = 0.0
    decision_cell: str = ""
    snippet_gold_rows: int = 0
    snippet_contra_rows: int = 0
    pre_fetch_support_rows: int = 0
    rank1_pre_fetch_support_rows: int = 0


@dataclass(frozen=True)
class MetricSpec:
    metric: str
    label: str
    unit: str
    digits: int
    fn: Callable[[list[QueryMetrics]], float]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * pct
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def ci(values: list[float]) -> tuple[float, float]:
    finite = sorted(v for v in values if v == v)
    return percentile(finite, 0.025), percentile(finite, 0.975)


def fmt(value: float, digits: int) -> str:
    if value != value:
        return "--"
    if digits == 0:
        return f"{round(value):,.0f}"
    return f"{value:,.{digits}f}"


def read_semantic(path: Path, data: dict[str, dict[str, QueryMetrics]]) -> list[str]:
    qids: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            provider = (row.get("provider") or "").lower()
            query_id = row.get("query_id") or ""
            if provider not in data or not query_id:
                continue
            qids.add(query_id)
            data[provider].setdefault(query_id, QueryMetrics()).correct = int(row.get("semantic_match") or 0)
    for provider in PROVIDERS:
        if len(data[provider]) != 100:
            raise RuntimeError(f"Expected 100 semantic rows for {provider}, found {len(data[provider])}")
    return sorted(qids)


def read_task1_per_query(path: Path, data: dict[str, dict[str, QueryMetrics]]) -> None:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            provider = (row.get("provider") or "").lower()
            query_id = row.get("query_id") or ""
            if provider not in data or query_id not in data[provider]:
                continue
            qm = data[provider][query_id]
            qm.pre_fetch_support = int(row.get("pre_fetch_surface_support") or 0)
            qm.post_fetch_discovered_support = int(row.get("post_fetch_discovered_support") or 0)
            qm.trajectory_visible_support = int(row.get("trajectory_visible_support") or 0)
            qm.fetched_any_url = int(row.get("fetched_any_url") or 0)
            qm.fetched_url_count = int(row.get("fetched_url_count") or 0)
            qm.decision_cell = (row.get("decision_cell") or "").upper()


def read_provider_per_query(path: Path, data: dict[str, dict[str, QueryMetrics]]) -> None:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            provider = (row.get("provider_id") or "").lower()
            query_id = row.get("query_id") or ""
            if provider not in data or query_id not in data[provider]:
                continue
            qm = data[provider][query_id]
            qm.token_f1 = float(row.get("f1") or 0.0)
            qm.total_tokens = float(row.get("total_tokens") or 0.0)
            # Headline fetch metrics in the paper are trace-level tool calls,
            # not only successfully page-judged URLs.
            qm.fetched_url_count = sum(int(v or 0) for v in (row.get("fetch_status_counts") or {}).values())
            qm.fetched_any_url = int(qm.fetched_url_count > 0)


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


def read_judge_rows(paths: dict[str, Path], data: dict[str, dict[str, QueryMetrics]]) -> None:
    for provider, path in paths.items():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not valid_judge_row(row):
                    continue
                query_id = row.get("query_id") or ""
                if query_id not in data[provider]:
                    continue
                qm = data[provider][query_id]
                judgment = row["judgment"]
                surface = row.get("judge_surface_class")
                if surface == "snippet_only":
                    qm.snippet_gold_rows += int(bool(judgment.get("contains_gold_answer")))
                    qm.snippet_contra_rows += int(bool(judgment.get("contradicts_gold_answer")))
                pre_fetch_support = bool(judgment.get("gold_answer_in_snippets")) or (
                    surface == "snippet_only" and bool(judgment.get("contains_gold_answer"))
                )
                if pre_fetch_support:
                    qm.pre_fetch_support_rows += 1
                    if int(row.get("rank") or 0) == 1:
                        qm.rank1_pre_fetch_support_rows += 1


def ratio(num: float, den: float) -> float:
    return num / den if den else float("nan")


def make_metric_specs() -> list[MetricSpec]:
    return [
        MetricSpec("correct", "Correct /100", "queries", 0, lambda rows: sum(r.correct for r in rows)),
        MetricSpec("token_f1", "Token F1", "macro F1", 3, lambda rows: sum(r.token_f1 for r in rows) / len(rows)),
        MetricSpec("pre_fetch_support", "Pre-fetch support /100", "queries", 0, lambda rows: sum(r.pre_fetch_support for r in rows)),
        MetricSpec("rank1_pre_fetch", "Rank-1 pre-fetch", "percent", 1, lambda rows: 100 * ratio(sum(r.rank1_pre_fetch_support_rows for r in rows), sum(r.pre_fetch_support_rows for r in rows))),
        MetricSpec("surface_cg", "Surface c:g", "ratio", 2, lambda rows: ratio(sum(r.snippet_contra_rows for r in rows), sum(r.snippet_gold_rows for r in rows))),
        MetricSpec("fetched_queries", "Fetched queries /100", "queries", 0, lambda rows: sum(r.fetched_any_url for r in rows)),
        MetricSpec("avg_fetch_calls", "Avg. fetch calls", "calls/query", 2, lambda rows: sum(r.fetched_url_count for r in rows) / len(rows)),
        MetricSpec("tokens_query", "Tokens/query", "tokens", 0, lambda rows: sum(r.total_tokens for r in rows) / len(rows)),
    ]


def resample_indices(n: int, reps: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(reps)]


def rows_for(data: dict[str, dict[str, QueryMetrics]], provider: str, qids: list[str], indices: list[int] | None = None) -> list[QueryMetrics]:
    selected = qids if indices is None else [qids[i] for i in indices]
    return [data[provider][qid] for qid in selected]


def provider_metric_rows(
    data: dict[str, dict[str, QueryMetrics]],
    qids: list[str],
    specs: list[MetricSpec],
    replicates: list[list[int]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in specs:
        for provider in PROVIDERS:
            estimate = spec.fn(rows_for(data, provider, qids))
            values = [spec.fn(rows_for(data, provider, qids, idxs)) for idxs in replicates]
            lo, hi = ci(values)
            out.append({
                "metric": spec.metric,
                "label": spec.label,
                "provider": provider,
                "provider_label": PLABEL[provider],
                "estimate": estimate,
                "ci_low": lo,
                "ci_high": hi,
                "unit": spec.unit,
                "digits": spec.digits,
                "formatted": f"{fmt(estimate, spec.digits)} [{fmt(lo, spec.digits)}, {fmt(hi, spec.digits)}]",
            })
    return out


def pairwise_metric_rows(
    data: dict[str, dict[str, QueryMetrics]],
    qids: list[str],
    specs: list[MetricSpec],
    replicates: list[list[int]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in specs:
        for left, right in PAIRS:
            estimate = spec.fn(rows_for(data, left, qids)) - spec.fn(rows_for(data, right, qids))
            values = [
                spec.fn(rows_for(data, left, qids, idxs)) - spec.fn(rows_for(data, right, qids, idxs))
                for idxs in replicates
            ]
            lo, hi = ci(values)
            out.append({
                "metric": spec.metric,
                "label": spec.label,
                "left": left,
                "right": right,
                "left_label": PLABEL[left],
                "right_label": PLABEL[right],
                "estimate": estimate,
                "ci_low": lo,
                "ci_high": hi,
                "unit": spec.unit,
                "digits": spec.digits,
                "formatted": f"{fmt(estimate, spec.digits)} [{fmt(lo, spec.digits)}, {fmt(hi, spec.digits)}]",
            })
    return out


def decision_cell_rows(
    data: dict[str, dict[str, QueryMetrics]],
    qids: list[str],
    replicates: list[list[int]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        for cell in DECISION_CELLS:
            actual_rows = rows_for(data, provider, qids)
            cell_rows = [r for r in actual_rows if r.decision_cell == cell]
            estimate = 100 * ratio(sum(r.correct for r in cell_rows), len(cell_rows))
            values: list[float] = []
            for idxs in replicates:
                sampled = rows_for(data, provider, qids, idxs)
                sampled_cell = [r for r in sampled if r.decision_cell == cell]
                values.append(100 * ratio(sum(r.correct for r in sampled_cell), len(sampled_cell)))
            lo, hi = ci(values)
            out.append({
                "provider": provider,
                "provider_label": PLABEL[provider],
                "cell": cell,
                "query_count": len(cell_rows),
                "correct_count": sum(r.correct for r in cell_rows),
                "estimate": estimate,
                "ci_low": lo,
                "ci_high": hi,
                "unit": "percent",
                "digits": 0,
                "formatted": f"{sum(r.correct for r in cell_rows)}/{len(cell_rows)} ({fmt(estimate, 0)}% [{fmt(lo, 0)}, {fmt(hi, 0)}])",
            })
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def by_key(rows: list[dict[str, Any]], *keys: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    return {tuple(row[k] for k in keys): row for row in rows}


def write_summary(
    out_dir: Path,
    provider_rows: list[dict[str, Any]],
    pairwise_rows: list[dict[str, Any]],
    cell_rows: list[dict[str, Any]],
    reps: int,
    seed: int,
) -> None:
    provider = by_key(provider_rows, "metric", "provider")
    pairwise = by_key(pairwise_rows, "metric", "left", "right")

    def p(metric: str, provider_id: str) -> str:
        return provider[(metric, provider_id)]["formatted"]

    def d(metric: str, left: str, right: str) -> str:
        return pairwise[(metric, left, right)]["formatted"]

    lines = [
        "# Task 4 paired-bootstrap uncertainty",
        "",
        f"Bootstrap unit: question ID. Replicates: {reps:,}. Seed: {seed}. Intervals are percentile 95% CIs.",
        "",
        "## Provider metric intervals",
        "",
        "| Metric | Brave | Tavily | Firecrawl |",
        "|---|---:|---:|---:|",
    ]
    for metric in ("correct", "pre_fetch_support", "rank1_pre_fetch", "surface_cg", "fetched_queries", "avg_fetch_calls", "tokens_query"):
        label = provider[(metric, "brave")]["label"]
        lines.append(f"| {label} | {p(metric, 'brave')} | {p(metric, 'tavily')} | {p(metric, 'firecrawl')} |")

    lines += [
        "",
        "## Paired provider differences",
        "",
        "Differences are left minus right in the metric's native units.",
        "",
        "| Metric | Brave-Tavily | Brave-Firecrawl | Tavily-Firecrawl |",
        "|---|---:|---:|---:|",
    ]
    for metric in ("correct", "pre_fetch_support", "rank1_pre_fetch", "surface_cg", "fetched_queries", "avg_fetch_calls", "tokens_query"):
        label = pairwise[(metric, "brave", "tavily")]["label"]
        lines.append(f"| {label} | {d(metric, 'brave', 'tavily')} | {d(metric, 'brave', 'firecrawl')} | {d(metric, 'tavily', 'firecrawl')} |")

    lines += [
        "",
        "## Decision-cell correctness intervals",
        "",
        "| Provider | SMART | MISSED | BLIND | NOOP |",
        "|---|---:|---:|---:|---:|",
    ]
    cells = by_key(cell_rows, "provider", "cell")
    for provider_id in PROVIDERS:
        lines.append(
            f"| {PLABEL[provider_id]} | "
            f"{cells[(provider_id, 'SMART')]['formatted']} | "
            f"{cells[(provider_id, 'MISSED')]['formatted']} | "
            f"{cells[(provider_id, 'BLIND')]['formatted']} | "
            f"{cells[(provider_id, 'NOOP')]['formatted']} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "- Final correctness differences are small: every pairwise correctness interval includes zero.",
        "- Brave's pre-fetch support advantage is larger: Brave-Tavily and Brave-Firecrawl differences are both +14 queries, with intervals that stay positive.",
        "- Rank concentration separates Tavily from the others: Tavily's rank-1 pre-fetch share is much higher, and the paired intervals for Brave-Tavily and Tavily-Firecrawl exclude zero.",
        "- Surface contradiction exposure is directionally higher for Tavily and Firecrawl than Brave, but ratio intervals are wider because the denominator is the number of gold-supporting snippet rows.",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260628)
    parser.add_argument("--out-dir", type=Path, default=repo_root() / "results/task4_uncertainty")
    args = parser.parse_args()

    root = repo_root()
    data: dict[str, dict[str, QueryMetrics]] = {provider: {} for provider in PROVIDERS}
    qids = read_semantic(root / "results/em_vs_semantic_audit.tsv", data)
    read_task1_per_query(root / "results/task1_support_split/provider_query_support.csv", data)
    read_provider_per_query(root / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_per_query.jsonl", data)
    read_judge_rows({
        "brave": root / "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
        "tavily": root / "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
        "firecrawl": root / "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
    }, data)

    if len(qids) != 100:
        raise RuntimeError(f"Expected 100 matched question IDs, found {len(qids)}")
    for provider in PROVIDERS:
        missing = [qid for qid in qids if qid not in data[provider]]
        if missing:
            raise RuntimeError(f"Missing {len(missing)} rows for {provider}: {missing[:3]}")

    specs = make_metric_specs()
    replicates = resample_indices(len(qids), args.reps, args.seed)
    provider_rows = provider_metric_rows(data, qids, specs, replicates)
    pairwise_rows = pairwise_metric_rows(data, qids, specs, replicates)
    cell_rows = decision_cell_rows(data, qids, replicates)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "provider_metric_cis.csv", provider_rows)
    write_csv(args.out_dir / "pairwise_difference_cis.csv", pairwise_rows)
    write_csv(args.out_dir / "decision_cell_correctness_cis.csv", cell_rows)
    (args.out_dir / "uncertainty_summary.json").write_text(json.dumps({
        "bootstrap_unit": "question_id",
        "replicates": args.reps,
        "seed": args.seed,
        "providers": provider_rows,
        "pairwise_differences": pairwise_rows,
        "decision_cell_correctness": cell_rows,
    }, indent=2), encoding="utf-8")
    write_summary(args.out_dir, provider_rows, pairwise_rows, cell_rows, args.reps, args.seed)
    print(f"Wrote paired-bootstrap uncertainty outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
