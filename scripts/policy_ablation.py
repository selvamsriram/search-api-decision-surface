#!/usr/bin/env python3
"""Offline fetch-policy ablation from existing URL-level judge labels.

The script does not rerun providers or fetch pages. It reuses the URL surface
and page judgments already visible in the observed trajectories, so page-support
gains for counterfactual rank-k policies are conservative lower bounds.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROVIDERS = ("brave", "tavily", "firecrawl")
PLABEL = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}
JUDGE_FILES = {
    "brave": "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
    "tavily": "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
    "firecrawl": "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
}
POLICIES = (
    "snippet_only",
    "fetch_rank_1",
    "fetch_top_3",
    "fetch_top_5",
    "observed_agent_policy",
    "oracle_fetch_if_any_support",
    "oracle_fetch_if_needed",
)


@dataclass
class UrlState:
    provider: str
    query_id: str
    url_id: str
    rank: int = 10**9
    first_seen: int = 10**9
    pre_support: bool = False
    page_support: bool = False
    surface_contradiction: bool = False
    opened_contradiction: bool = False
    fetched: bool = False
    page_tokens: int | None = None
    page_tokens_known: bool = False
    page_chars: int | None = None


@dataclass
class QueryState:
    provider: str
    query_id: str
    urls: dict[str, UrlState] = field(default_factory=dict)

    def ordered_urls(self) -> list[UrlState]:
        return sorted(self.urls.values(), key=lambda u: (u.rank, u.first_seen, u.url_id))


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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_provider_states(root: Path, provider: str) -> tuple[dict[str, QueryState], dict[str, int]]:
    path = root / JUDGE_FILES[provider]
    rows_all = load_jsonl(path)
    rows = [row for row in rows_all if valid_judge_row(row)]
    states: dict[str, QueryState] = {}
    observed_tokens: list[int] = []
    totals = {
        "judge_rows": len(rows_all),
        "valid_rows": len(rows),
        "invalid_rows": len(rows_all) - len(rows),
        "valid_page_rows": 0,
        "valid_snippet_rows": 0,
        "surface_contradiction_rows": 0,
    }

    for idx, row in enumerate(rows):
        query_id = str(row["query_id"])
        url = str(row.get("normalized_url") or row["url"])
        state = states.setdefault(query_id, QueryState(provider=provider, query_id=query_id))
        url_state = state.urls.setdefault(url, UrlState(provider=provider, query_id=query_id, url_id=url))
        rank = int(row.get("rank") or 0) or 10**9
        url_state.rank = min(url_state.rank, rank)
        url_state.first_seen = min(url_state.first_seen, idx)

        surface = row.get("judge_surface_class")
        judgment = row["judgment"]
        if surface == "snippet_only":
            totals["valid_snippet_rows"] += 1
        elif surface == "page_visible":
            totals["valid_page_rows"] += 1

        # Same pre-fetch support definition as Task 1: fetched URLs appear as
        # page-visible records but still retain snippet-specific labels.
        if judgment.get("gold_answer_in_snippets") or (
            surface == "snippet_only" and judgment.get("contains_gold_answer")
        ):
            url_state.pre_support = True

        if surface == "page_visible":
            url_state.fetched = True
            if judgment.get("gold_answer_in_extracted_page"):
                url_state.page_support = True
            if judgment.get("contradicts_gold_answer"):
                url_state.opened_contradiction = True
            page_fetch = row.get("page_fetch") or {}
            if page_fetch:
                tokens = int(page_fetch.get("extracted_text_tokens_estimate") or 0)
                chars = int(page_fetch.get("extracted_text_chars") or 0)
                url_state.page_tokens = tokens
                url_state.page_chars = chars
                url_state.page_tokens_known = True
                observed_tokens.append(tokens)
        elif row.get("model_fetched_document"):
            url_state.fetched = True

        if judgment.get("contradicts_gold_answer"):
            if surface == "snippet_only":
                totals["surface_contradiction_rows"] += 1
                url_state.surface_contradiction = True
            elif surface == "page_visible":
                # A page-visible contradiction was part of opened evidence.
                url_state.opened_contradiction = True

    totals["query_count"] = len(states)
    if totals["query_count"] != 100:
        raise RuntimeError(f"Expected 100 queries for {provider}, found {totals['query_count']}")
    tokens_nonzero = [value for value in observed_tokens if value > 0]
    totals["imputed_fetch_tokens"] = round(statistics.median(tokens_nonzero or observed_tokens or [0]))
    return states, totals


def select_urls(policy: str, state: QueryState) -> list[UrlState]:
    ordered = state.ordered_urls()
    if policy == "snippet_only":
        return []
    if policy == "fetch_rank_1":
        return ordered[:1]
    if policy == "fetch_top_3":
        return ordered[:3]
    if policy == "fetch_top_5":
        return ordered[:5]
    if policy == "observed_agent_policy":
        return [url for url in ordered if url.fetched]
    if policy == "oracle_fetch_if_any_support":
        support_urls = [url for url in ordered if url.pre_support or url.page_support]
        return support_urls[:1]
    if policy == "oracle_fetch_if_needed":
        if any(url.pre_support for url in ordered):
            return []
        page_urls = [url for url in ordered if url.page_support]
        return page_urls[:1]
    raise KeyError(policy)


def cost_for_selected(urls: list[UrlState], imputed_tokens: int) -> tuple[int, int]:
    total = 0
    imputed = 0
    for url in urls:
        if url.page_tokens_known and url.page_tokens is not None:
            total += url.page_tokens
        else:
            total += imputed_tokens
            imputed += 1
    return total, imputed


def policy_query_row(provider: str, policy: str, state: QueryState, imputed_tokens: int) -> dict[str, Any]:
    selected = select_urls(policy, state)
    pre_support = any(url.pre_support for url in state.urls.values())
    selected_page_support = any(url.page_support for url in selected)
    any_page_support = any(url.page_support for url in state.urls.values())
    captured = pre_support or selected_page_support
    incremental_page_support = (not pre_support) and selected_page_support
    trajectory_support = pre_support or any_page_support
    surface_contradiction = any(url.surface_contradiction for url in state.urls.values())
    opened_contradiction = any(url.opened_contradiction or url.surface_contradiction for url in selected)
    tokens, imputed_count = cost_for_selected(selected, imputed_tokens)
    return {
        "provider": provider,
        "query_id": state.query_id,
        "policy": policy,
        "support_captured": int(captured),
        "pre_fetch_support": int(pre_support),
        "page_support_selected": int(selected_page_support),
        "incremental_page_support": int(incremental_page_support),
        "trajectory_support": int(trajectory_support),
        "fetches_used": len(selected),
        "estimated_fetch_tokens": tokens,
        "imputed_fetches": imputed_count,
        "surface_contradiction_seen": int(surface_contradiction),
        "opened_contradiction_seen": int(opened_contradiction),
        "selected_urls": ";".join(url.url_id for url in selected),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    support = sum(int(row["support_captured"]) for row in rows)
    incremental = sum(int(row["incremental_page_support"]) for row in rows)
    fetches = sum(int(row["fetches_used"]) for row in rows)
    tokens = sum(int(row["estimated_fetch_tokens"]) for row in rows)
    imputed = sum(int(row["imputed_fetches"]) for row in rows)
    surface_contra = sum(int(row["surface_contradiction_seen"]) for row in rows)
    opened_contra = sum(int(row["opened_contradiction_seen"]) for row in rows)
    return {
        "queries": n,
        "support_captured_q": support,
        "support_captured_pct": round(100 * support / n),
        "incremental_page_support_q": incremental,
        "fetches_used": fetches,
        "avg_fetches_per_query": round(fetches / n, 2),
        "support_per_fetch": None if fetches == 0 else round(support / fetches, 3),
        "incremental_support_per_fetch": None if fetches == 0 else round(incremental / fetches, 3),
        "estimated_fetch_tokens": tokens,
        "estimated_fetch_tokens_per_query": round(tokens / n),
        "imputed_fetches": imputed,
        "surface_contradiction_q": surface_contra,
        "opened_contradiction_q": opened_contra,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_spf(value: Any) -> str:
    return "--" if value is None else f"{value:.3f}".rstrip("0").rstrip(".")


def write_markdown(out_dir: Path, policy_rows: list[dict[str, Any]], provider_totals: dict[str, dict[str, int]]) -> None:
    by_policy_provider: dict[tuple[str, str], dict[str, Any]] = {}
    for row in policy_rows:
        by_policy_provider[(row["policy"], row["provider"])] = row

    lines: list[str] = [
        "# Task 3 offline fetch-policy ablation",
        "",
        "Computed from existing Kimi per-URL judge JSONLs; no provider calls or page fetches were rerun.",
        "",
        "Important interpretation notes:",
        "",
        "- All policies see the same pre-fetch snippet surface; `snippet_only` therefore captures pre-fetch support with zero fetches.",
        "- Rank-k policies select the lowest-rank distinct URLs in the already observed provider-query trajectory.",
        "- Counterfactual page support is a lower bound: a rank-k policy only gets page-support credit when that URL was actually fetched and page-judged in the observed trace.",
        "- Counterfactual fetch cost uses the observed page token estimate when available and otherwise imputes the provider median observed successful fetch size.",
        "- `oracle_fetch_if_any_support` is a hindsight upper bound that fetches the lowest-rank judged support URL, if any.",
        "- `oracle_fetch_if_needed` is a more cost-minimal hindsight diagnostic: it fetches only when no pre-fetch support exists but an observed page-only support URL exists.",
        "",
        "## Main support and budget table",
        "",
        "| Policy | Brave support | Tavily support | Firecrawl support | Brave fetch/q | Tavily fetch/q | Firecrawl fetch/q |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy in POLICIES:
        cells = [policy]
        for provider in PROVIDERS:
            row = by_policy_provider[(policy, provider)]
            cells.append(f'{row["support_captured_q"]} ({row["support_captured_pct"]}%)')
        for provider in PROVIDERS:
            row = by_policy_provider[(policy, provider)]
            cells.append(f'{row["avg_fetches_per_query"]:.2f}')
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Efficiency and contamination diagnostics",
        "",
        "| Provider | Policy | Incremental page support | Incremental support/fetch | Total support/fetch | Fetch tokens/query | Imputed fetches | Opened contradiction q | Surface contradiction q |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in PROVIDERS:
        for policy in POLICIES:
            row = by_policy_provider[(policy, provider)]
            lines.append(
                "| "
                + " | ".join(
                    [
                        PLABEL[provider],
                        policy,
                        str(row["incremental_page_support_q"]),
                        fmt_spf(row["incremental_support_per_fetch"]),
                        fmt_spf(row["support_per_fetch"]),
                        f'{row["estimated_fetch_tokens_per_query"]:,}',
                        str(row["imputed_fetches"]),
                        str(row["opened_contradiction_q"]),
                        str(row["surface_contradiction_q"]),
                    ]
                )
                + " |"
            )

    lines += [
        "",
        "## Provider judge totals",
        "",
        "| Provider | Valid rows | Snippet rows | Page rows | Invalid rows | Imputed fetch token median |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for provider in PROVIDERS:
        totals = provider_totals[provider]
        lines.append(
            f"| {PLABEL[provider]} | {totals['valid_rows']} | {totals['valid_snippet_rows']} | "
            f"{totals['valid_page_rows']} | {totals['invalid_rows']} | {totals['imputed_fetch_tokens']:,} |"
        )

    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--output-dir", type=Path, default=root / "results" / "task3_policy_ablation")
    args = parser.parse_args()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    all_query_rows: list[dict[str, Any]] = []
    provider_totals: dict[str, dict[str, int]] = {}
    for provider in PROVIDERS:
        states, totals = load_provider_states(root, provider)
        provider_totals[provider] = totals
        imputed_tokens = totals["imputed_fetch_tokens"]
        for policy in POLICIES:
            for query_id in sorted(states):
                all_query_rows.append(policy_query_row(provider, policy, states[query_id], imputed_tokens))

    summary_rows: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        for policy in POLICIES:
            rows = [row for row in all_query_rows if row["provider"] == provider and row["policy"] == policy]
            summary_rows.append({"provider": provider, "policy": policy, **summarize(rows)})

    write_csv(
        out_dir / "policy_ablation_per_query.csv",
        all_query_rows,
        [
            "provider",
            "query_id",
            "policy",
            "support_captured",
            "pre_fetch_support",
            "page_support_selected",
            "incremental_page_support",
            "trajectory_support",
            "fetches_used",
            "estimated_fetch_tokens",
            "imputed_fetches",
            "surface_contradiction_seen",
            "opened_contradiction_seen",
            "selected_urls",
        ],
    )
    write_csv(
        out_dir / "policy_ablation_summary.csv",
        summary_rows,
        [
            "provider",
            "policy",
            "queries",
            "support_captured_q",
            "support_captured_pct",
            "incremental_page_support_q",
            "fetches_used",
            "avg_fetches_per_query",
            "support_per_fetch",
            "incremental_support_per_fetch",
            "estimated_fetch_tokens",
            "estimated_fetch_tokens_per_query",
            "imputed_fetches",
            "surface_contradiction_q",
            "opened_contradiction_q",
        ],
    )
    (out_dir / "policy_ablation_summary.json").write_text(
        json.dumps({"provider_totals": provider_totals, "policies": summary_rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(out_dir, summary_rows, provider_totals)
    print(f"Wrote policy ablation outputs to {out_dir}")


if __name__ == "__main__":
    main()
