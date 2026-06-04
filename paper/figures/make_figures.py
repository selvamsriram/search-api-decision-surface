#!/usr/bin/env python3
"""Regenerate all decision-surface paper artifacts.

Outputs:
  figures/numbers.tex
  figures/fig_architecture.dot
  figures/fig_architecture.tikz.tex
  figures/fig_provider_profiles.dot
  figures/fig_provider_profiles.tikz.tex
  figures/fig_partition.dot
  figures/fig_partition.tikz.tex
  figures/decision_surface_audit.json
  figures/decision_surface_audit.md

Default mode recomputes all metrics from the raw trace/judge JSONL files. The raw
large JSONL files are stored via Git LFS in this repository; run `git lfs pull`
before auditing. Use --render-only to regenerate diagrams/macros from the last
validated constants without requiring LFS data.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

PROVIDERS = ["brave", "tavily", "firecrawl"]
LABEL = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}

JUDGE_PATHS = {
    "brave": REPO / "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
    "tavily": REPO / "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
    "firecrawl": REPO / "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
}

TRACE_PATHS = {
    "brave": REPO / "data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl",
    "tavily": REPO / "data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl",
    "firecrawl": REPO / "data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl",
}
PER_QUERY = REPO / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_per_query.jsonl"
SUMMARY = REPO / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_summary.json"

# Last validated constants from the source-data audit. These are used only for
# --render-only and as guardrails for audit mode.
EXPECTED: dict[str, Any] = {
    "meta": {
        "queries": 100,
        "providers": 3,
        "traces": 300,
        "judge_total": 6909,
        "judge_valid": 6869,
        "judge_invalid": 40,
        "judge_snippet_valid": 6519,
        "judge_page_valid": 350,
        "all_correct": 9,
        "two_correct": 9,
        "one_correct": 20,
        "all_wrong": 62,
    },
    "providers": {
        "brave": {
            "em": 21,
            "f1": 0.270,
            "answered": 98,
            "avg_search": 2.29,
            "avg_fetch": 1.02,
            "fetched_pct": 65,
            "tokens_m": 5.96,
            "snippet_rows": 2095,
            "page_rows": 101,
            "support_visible_q": 33,
            "no_support_q": 67,
            "gold_urls": 97,
            "contra_urls": 89,
            "contra_ratio": 0.92,
            "rank1_pct": 12,
            "rank1_count": 12,
            "bucket": {"smart": [8, 3], "missed": [25, 9], "blind": [51, 9], "noop": [16, 0]},
            "answer_available": 78,
        },
        "tavily": {
            "em": 21,
            "f1": 0.261,
            "answered": 97,
            "avg_search": 2.74,
            "avg_fetch": 1.30,
            "fetched_pct": 76,
            "tokens_m": 5.42,
            "snippet_rows": 2339,
            "page_rows": 125,
            "support_visible_q": 24,
            "no_support_q": 76,
            "gold_urls": 31,
            "contra_urls": 58,
            "contra_ratio": 1.87,
            "rank1_pct": 48,
            "rank1_count": 15,
            "bucket": {"smart": [11, 7], "missed": [13, 5], "blind": [55, 9], "noop": [21, 0]},
            "answer_available": 75,
        },
        "firecrawl": {
            "em": 23,
            "f1": 0.282,
            "answered": 96,
            "avg_search": 2.51,
            "avg_fetch": 1.28,
            "fetched_pct": 81,
            "tokens_m": 5.80,
            "snippet_rows": 2085,
            "page_rows": 124,
            "support_visible_q": 19,
            "no_support_q": 81,
            "gold_urls": 27,
            "contra_urls": 70,
            "contra_ratio": 2.59,
            "rank1_pct": 11,
            "rank1_count": 3,
            "bucket": {"smart": [7, 2], "missed": [12, 5], "blind": [67, 16], "noop": [14, 0]},
            "answer_available": 76,
        },
    },
}

COLOR_NAMES = {
    "#334155": "slateink",
    "#475569": "slateedge",
    "#64748B": "slatemid",
    "#F8FAFC": "slatefill",
    "#FFF7ED": "orangefill",
    "#C2410C": "orangeedge",
    "#FEE2E2": "redfill",
    "#DC2626": "rededge",
    "#DBEAFE": "bluefill",
    "#2563EB": "blueedge",
    "#DCFCE7": "greenfill",
    "#16A34A": "greenedge",
    "#F0FDF4": "greenlight",
    "#15803D": "greendark",
    "#EEF2FF": "indigofill",
    "#4F46E5": "indigoedge",
    "#ECFEFF": "cyanfill",
    "#0891B2": "cyanedge",
    "#F1F5F9": "slatefillb",
    "#FAE8FF": "purplefill",
    "#A21CAF": "purpleedge",
    "#FFFBEB": "amberfill",
    "#B45309": "amberedge",
    "#FFF1F2": "pinkfill",
    "#EFF6FF": "bluelight",
    "#FEF3C7": "amberfillb",
    "#D97706": "amberedgeb",
    "#E0F2FE": "skyfill",
    "#0284C7": "skyedge",
    "#FEF9C3": "yellowfill",
    "#CA8A04": "yellowedge",
    "#FFEDD5": "orangefillb",
    "#EA580C": "orangeedgeb",
    "#E2E8F0": "grayfill",
}

TIKZ_PREAMBLE = "\n".join(
    rf"\definecolor{{{name}}}{{HTML}}{{{hexval[1:]}}}"
    for hexval, name in COLOR_NAMES.items()
)
TIKZ_STYLE = r"""
\begin{tikzpicture}[x=0.52in,y=0.52in,>=latex]
\tikzset{gvnode/.style={draw, rounded corners=3pt, align=center, font=\scriptsize, inner sep=2.8pt, line width=0.35pt}}
\tikzset{gvedge/.style={->, line width=0.35pt, color=slateedge}}
""".strip()


def main() -> None:
    args = parse_args()
    stats = EXPECTED if args.render_only else compute_from_sources()
    if not args.render_only:
        validate_against_expected(stats)
    write_numbers(stats)
    write_audit(stats, source="last_validated_constants" if args.render_only else "raw_jsonl_and_provider_summary")
    render_all_figures(stats)
    mode = "render-only" if args.render_only else "audited"
    print(f"Wrote decision-surface paper artifacts ({mode}) to {OUT}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Regenerate DOT/TikZ and number macros from last validated constants without opening LFS JSONLs.",
    )
    return parser.parse_args()


def latest_by_query_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = row.get("query_id")
        if qid:
            latest[str(qid)] = row
    return latest


def compute_from_sources() -> dict[str, Any]:
    summary = load_json(SUMMARY)
    per_query = load_jsonl(PER_QUERY)
    emap = {(row["provider_id"], row["query_id"]): bool(row.get("exact_match")) for row in per_query}
    per_query_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_query:
        per_query_by_provider[row["provider_id"]].append(row)

    providers: dict[str, dict[str, Any]] = {}
    judge_total = judge_valid = judge_snippet_valid = judge_page_valid = 0
    for provider in PROVIDERS:
        trace_rows = load_jsonl(TRACE_PATHS[provider])
        latest_traces = latest_by_query_id(trace_rows)
        rows_all = load_jsonl(JUDGE_PATHS[provider])
        valid = [r for r in rows_all if valid_judge_record(r)]
        judge_total += len(rows_all)
        judge_valid += len(valid)
        snippet = [r for r in valid if r.get("judge_surface_class") == "snippet_only"]
        page = [r for r in valid if r.get("judge_surface_class") == "page_visible"]
        judge_snippet_valid += len(snippet)
        judge_page_valid += len(page)

        psummary = summary["providers"][provider]
        buckets = compute_buckets(valid, emap, provider, per_query_by_provider[provider])
        rank_dist = Counter(
            int(r.get("rank") or 0)
            for r in snippet
            if (r.get("judgment") or {}).get("contains_gold_answer")
        )
        gold_urls = sum(1 for r in snippet if (r.get("judgment") or {}).get("contains_gold_answer"))
        contra_urls = sum(1 for r in snippet if (r.get("judgment") or {}).get("contradicts_gold_answer"))
        support_visible = len(
            {
                r.get("query_id")
                for r in valid
                if (r.get("judgment") or {}).get("contains_gold_answer")
            }
        )
        total_queries = len(latest_traces) or len(per_query_by_provider[provider]) or 100
        fetch_status = psummary.get("fetch_status_counts") or {}
        fetch_calls = sum(int(v) for v in fetch_status.values())
        fetched_queries = sum(1 for trace in latest_traces.values() if trace.get("fetches"))
        if not fetched_queries:
            # Older trace-derived per-query rows retain only per-query fetch-status counters.
            fetched_queries = sum(1 for r in per_query_by_provider[provider] if r.get("fetch_status_counts"))

        providers[provider] = {
            "em": int(psummary["exact_match"]),
            "f1": round(float(psummary["avg_f1"]), 3),
            "answered": int(psummary["answered"]),
            "avg_search": round(float(psummary["avg_search_calls"]), 2),
            "avg_fetch": round(fetch_calls / total_queries, 2),
            "fetched_pct": round(100 * fetched_queries / total_queries),
            "tokens_m": round(float(psummary["total_tokens"]) / 1_000_000, 2),
            "snippet_rows": len(snippet),
            "page_rows": len(page),
            "support_visible_q": support_visible,
            "no_support_q": total_queries - support_visible,
            "gold_urls": gold_urls,
            "contra_urls": contra_urls,
            "contra_ratio": round(contra_urls / gold_urls, 2) if gold_urls else math.nan,
            "rank1_pct": round(100 * rank_dist.get(1, 0) / gold_urls) if gold_urls else 0,
            "rank1_count": rank_dist.get(1, 0),
            "bucket": buckets,
            "answer_available": int(psummary["answer_in_any_retrieved_text"]),
        }

    three_way = summary.get("three_way", {}).get("classes", {})
    return {
        "meta": {
            "queries": 100,
            "providers": 3,
            "traces": 300,
            "judge_total": judge_total,
            "judge_valid": judge_valid,
            "judge_invalid": judge_total - judge_valid,
            "judge_snippet_valid": judge_snippet_valid,
            "judge_page_valid": judge_page_valid,
            "all_correct": int(three_way.get("all_correct", 0)),
            "two_correct": int(three_way.get("two_providers_correct", 0)),
            "one_correct": int(three_way.get("one_provider_correct", 0)),
            "all_wrong": int(three_way.get("all_wrong", 0)),
        },
        "providers": providers,
    }


def load_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    ensure_not_lfs_pointer(path, text)
    return json.loads(text)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    ensure_not_lfs_pointer(path, text)
    rows = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Malformed JSONL row {path}:{line_num}: {error}") from error
    return rows


def ensure_not_lfs_pointer(path: Path, text: str) -> None:
    if text.startswith("version https://git-lfs.github.com/spec/v1"):
        raise RuntimeError(
            f"{path} is still a Git LFS pointer. Run `git lfs pull` from the repo root, "
            "then rerun `python3 paper/figures/make_figures.py`. For LaTeX-only builds, "
            "use `python3 paper/figures/make_figures.py --render-only`."
        )


def valid_judge_record(record: dict[str, Any]) -> bool:
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


def compute_buckets(
    rows: list[dict[str, Any]],
    emap: dict[tuple[str, str], bool],
    provider: str,
    per_query_rows: list[dict[str, Any]],
) -> dict[str, list[int]]:
    q_state: dict[str, dict[str, set[str]]] = {}
    for row in per_query_rows:
        q_state.setdefault(row["query_id"], {"gold_urls": set(), "fetched_urls": set(), "fetched_gold": set()})
    for row in rows:
        qid = row["query_id"]
        url = row.get("normalized_url") or row.get("url") or ""
        judgment = row.get("judgment") or {}
        state = q_state.setdefault(qid, {"gold_urls": set(), "fetched_urls": set(), "fetched_gold": set()})
        surface = row.get("judge_surface_class")
        if surface == "snippet_only":
            if judgment.get("contains_gold_answer"):
                state["gold_urls"].add(url)
            if row.get("model_fetched_document"):
                state["fetched_urls"].add(url)
        elif surface == "page_visible":
            state["fetched_urls"].add(url)
            if judgment.get("contains_gold_answer"):
                state["gold_urls"].add(url)
                state["fetched_gold"].add(url)
    out: dict[str, list[int]] = {"smart": [0, 0], "missed": [0, 0], "blind": [0, 0], "noop": [0, 0]}
    for qid, state in q_state.items():
        gold = bool(state["gold_urls"])
        fetched_any = bool(state["fetched_urls"])
        fetched_gold = bool(state["fetched_gold"])
        if gold and fetched_gold:
            key = "smart"
        elif gold and not fetched_gold:
            key = "missed"
        elif (not gold) and fetched_any:
            key = "blind"
        else:
            key = "noop"
        out[key][0] += 1
        out[key][1] += int(emap.get((provider, qid), False))
    return out


def validate_against_expected(stats: dict[str, Any]) -> None:
    diffs: list[str] = []
    for key, expected in EXPECTED["meta"].items():
        actual = stats["meta"].get(key)
        if actual != expected:
            diffs.append(f"meta.{key}: expected {expected}, got {actual}")
    for provider in PROVIDERS:
        for key, expected in EXPECTED["providers"][provider].items():
            actual = stats["providers"][provider].get(key)
            if key == "bucket":
                if actual != expected:
                    diffs.append(f"{provider}.{key}: expected {expected}, got {actual}")
            elif isinstance(expected, float):
                if abs(float(actual) - expected) > 0.005:
                    diffs.append(f"{provider}.{key}: expected {expected}, got {actual}")
            elif actual != expected:
                diffs.append(f"{provider}.{key}: expected {expected}, got {actual}")
    if diffs:
        msg = "Metric audit mismatches:\n" + "\n".join(f"  - {d}" for d in diffs)
        raise RuntimeError(msg)


def macro(name: str, value: Any) -> str:
    if isinstance(value, float):
        value = f"{value:.3f}" if value < 1 else f"{value:.2f}"
    return rf"\newcommand{{\{name}}}{{{value}}}"


def pct(value: int | float) -> str:
    return rf"{int(round(value))}\%"


def thousands(value: int) -> str:
    return f"{value:,}".replace(",", r"{,}")


def write_numbers(stats: dict[str, Any]) -> None:
    m = stats["meta"]
    p = stats["providers"]
    lines = ["% Deterministic paper numbers. Regenerate with figures/make_figures.py after git lfs pull."]
    lines += [
        macro("NQueries", m["queries"]),
        macro("NProviders", m["providers"]),
        macro("NTraces", m["traces"]),
        macro("NJudgeTotal", thousands(m["judge_total"])),
        macro("NJudgeValid", thousands(m["judge_valid"])),
        macro("NJudgeInvalid", m["judge_invalid"]),
        macro("NJudgeSnippetValid", thousands(m["judge_snippet_valid"])),
        macro("NJudgePageValid", m["judge_page_valid"]),
    ]
    for provider in PROVIDERS:
        L = LABEL[provider]
        row = p[provider]
        lines += [
            macro(f"{L}EM", row["em"]),
            macro(f"{L}Fone", f"{row['f1']:.3f}"),
            macro(f"{L}SearchAvg", f"{row['avg_search']:.2f}"),
            macro(f"{L}FetchAvg", f"{row['avg_fetch']:.2f}"),
            macro(f"{L}FetchedPct", pct(row["fetched_pct"])),
            macro(f"{L}TokensM", f"{row['tokens_m']:.2f}"),
            macro(f"{L}SupportVisibleQ", row["support_visible_q"]),
            macro(f"{L}NoSupportQ", row["no_support_q"]),
            macro(f"{L}SnippetRows", thousands(row["snippet_rows"])),
            macro(f"{L}PageRows", row["page_rows"]),
            macro(f"{L}GoldURLs", row["gold_urls"]),
            macro(f"{L}ContraURLs", row["contra_urls"]),
            macro(f"{L}ContraRatio", f"{row['contra_ratio']:.2f}"),
            macro(f"{L}RankOnePct", pct(row["rank1_pct"])),
        ]
        for bucket_name, cap in (("smart", "Smart"), ("missed", "Missed"), ("blind", "Blind"), ("noop", "Noop")):
            n, em = row["bucket"][bucket_name]
            lines.append(macro(f"{L}{cap}N", n))
            lines.append(macro(f"{L}{cap}EM", em))
        lines.append(macro(f"{L}AnswerAvailable", row["answer_available"]))
    tav = p["tavily"]
    lines.append(macro("TavilyRankOneGold", f"{tav['rank1_count']}/{tav['gold_urls']}"))
    lines += [
        macro("AllCorrect", m["all_correct"]),
        macro("TwoCorrect", m["two_correct"]),
        macro("OneCorrect", m["one_correct"]),
        macro("AllWrong", m["all_wrong"]),
    ]
    (OUT / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_audit(stats: dict[str, Any], *, source: str) -> None:
    payload = {"source": source, **stats}
    (OUT / "decision_surface_audit.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Decision-surface data dictionary and audit",
        "",
        f"Source mode: `{source}`.",
        "",
        "This file is regenerated by `paper/figures/make_figures.py`. Audit mode recomputes metrics from raw LFS JSONL files; render-only mode writes the last validated constants so the paper can compile without large local data.",
        "",
        "## Core metric definitions",
        "",
        "- **Visible support**: at least one judged URL for the provider-query pair has `contains_gold_answer=true` on the snippet-only or page-visible surface. Because unfetched pages are not page-judged, this is a lower bound on true pool support.",
        "- **SMART**: visible support exists and the agent fetched a gold-supporting URL.",
        "- **MISSED**: visible support exists and the agent fetched none of the supporting URLs.",
        "- **BLIND**: no visible support exists and the agent fetched at least one URL.",
        "- **NO-OP**: no visible support exists and the agent fetched no URL.",
        "- **Contradict-to-gold ratio**: snippet-only `contradicts_gold_answer` URL count divided by snippet-only `contains_gold_answer` URL count.",
        "",
        "## Provider summary",
        "",
        "| Provider | EM | visible support | SMART | MISSED | BLIND | NO-OP | contradict:gold |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in PROVIDERS:
        row = stats["providers"][provider]
        b = row["bucket"]
        lines.append(
            f"| {LABEL[provider]} | {row['em']} | {row['support_visible_q']} | "
            f"{b['smart'][0]}/{b['smart'][1]} | {b['missed'][0]}/{b['missed'][1]} | "
            f"{b['blind'][0]}/{b['blind'][1]} | {b['noop'][0]}/{b['noop'][1]} | "
            f"{row['contra_ratio']:.2f} ({row['contra_urls']}/{row['gold_urls']}) |"
        )
    lines += [
        "",
        "## Raw files consumed in audit mode",
        "",
        f"- `{TRACE_PATHS['brave'].relative_to(REPO)}`",
        f"- `{TRACE_PATHS['tavily'].relative_to(REPO)}`",
        f"- `{TRACE_PATHS['firecrawl'].relative_to(REPO)}`",
        f"- `{JUDGE_PATHS['brave'].relative_to(REPO)}`",
        f"- `{JUDGE_PATHS['tavily'].relative_to(REPO)}`",
        f"- `{JUDGE_PATHS['firecrawl'].relative_to(REPO)}`",
        f"- `{PER_QUERY.relative_to(REPO)}`",
        f"- `{SUMMARY.relative_to(REPO)}`",
        "",
        "Before audit mode, run `git lfs pull` from the repository root. If any raw JSONL path is still a Git LFS pointer, the script exits with a clear error instead of silently using incomplete data.",
    ]
    (OUT / "decision_surface_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_architecture_dot(_: dict[str, Any]) -> str:
    return r'''
digraph G {
  graph [rankdir=LR, bgcolor="transparent", splines=ortho, nodesep=0.55, ranksep=0.80, margin=0.02];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, margin="0.10,0.06", color="#334155", penwidth=1.2, fillcolor="#F8FAFC"];
  edge [fontname="Helvetica", fontsize=9, color="#475569", arrowsize=0.7, penwidth=1.1];
  q [label="100\nSealQA-Hard\nqueries", fillcolor="#FFF7ED", color="#C2410C"];
  brave [label="Brave", fillcolor="#FEE2E2", color="#DC2626"];
  tavily [label="Tavily", fillcolor="#DBEAFE", color="#2563EB"];
  firecrawl [label="Firecrawl", fillcolor="#DCFCE7", color="#16A34A"];
  surface [label="provider\ndecision surface\n(snippets + URLs + ranks)", fillcolor="#F8FAFC", color="#334155"];
  agent [label="frozen GPT-5.4\nagent\nsearch_web + fetch_page", fillcolor="#EEF2FF", color="#4F46E5"];
  jina [label="Jina Reader\npage fetcher\nfixed backend", fillcolor="#ECFEFF", color="#0891B2"];
  trace [label="JSONL trace\nsearches, fetches,\nfinal answer", fillcolor="#F1F5F9", color="#475569"];
  judge [label="Kimi-K2.6\nper-URL judge\ntemp. 0", fillcolor="#FAE8FF", color="#A21CAF"];
  oracle [label="visible-URL oracle\ngold / contradiction / garbage", fillcolor="#F0FDF4", color="#15803D"];
  metrics [label="decision-surface metrics\nEM, buckets, rank, r_c:g", fillcolor="#FFFBEB", color="#B45309"];
  q -> brave; q -> tavily; q -> firecrawl;
  brave -> surface; tavily -> surface; firecrawl -> surface;
  surface -> agent [label="search surface"];
  agent -> jina [label="selected URLs"];
  jina -> agent [label="markdown page"];
  agent -> trace;
  trace -> judge [label="one row per visible URL"];
  judge -> oracle;
  oracle -> metrics;
  trace -> metrics [label="actions + EM"];
}
'''


def build_provider_profiles_dot(stats: dict[str, Any]) -> str:
    p = stats["providers"]
    return f'''
digraph G {{
  graph [rankdir=LR, bgcolor="transparent", splines=ortho, nodesep=0.45, ranksep=0.55, margin=0.02];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, margin="0.08,0.05", color="#334155", penwidth=1.1, fillcolor="#F8FAFC"];
  edge [fontname="Helvetica", fontsize=8, color="#64748B", arrowsize=0.55, penwidth=1.0];
  b0 [label="Brave\\nEM {p['brave']['em']}/100", fillcolor="#FEE2E2", color="#DC2626"];
  b1 [label="visible support\\n{p['brave']['support_visible_q']} queries", fillcolor="#FFF1F2", color="#DC2626"];
  b2 [label="large snippet-side\\nsupport pool\\n{p['brave']['gold_urls']} gold URLs", fillcolor="#FFF1F2", color="#DC2626"];
  b3 [label="low contamination\\nr_c:g = {p['brave']['contra_ratio']:.2f}", fillcolor="#FFF1F2", color="#DC2626"];
  t0 [label="Tavily\\nEM {p['tavily']['em']}/100", fillcolor="#DBEAFE", color="#2563EB"];
  t1 [label="visible support\\n{p['tavily']['support_visible_q']} queries", fillcolor="#EFF6FF", color="#2563EB"];
  t2 [label="rank-1 concentration\\n{p['tavily']['rank1_count']}/{p['tavily']['gold_urls']} gold URLs", fillcolor="#EFF6FF", color="#2563EB"];
  t3 [label="fetching gold pays\\nSMART EM {round(100*p['tavily']['bucket']['smart'][1]/p['tavily']['bucket']['smart'][0])}%", fillcolor="#EFF6FF", color="#2563EB"];
  f0 [label="Firecrawl\\nEM {p['firecrawl']['em']}/100", fillcolor="#DCFCE7", color="#16A34A"];
  f1 [label="visible support\\n{p['firecrawl']['support_visible_q']} queries", fillcolor="#F0FDF4", color="#16A34A"];
  f2 [label="broad exploration\\n{p['firecrawl']['bucket']['blind'][0]} BLIND queries", fillcolor="#F0FDF4", color="#16A34A"];
  f3 [label="high contamination\\nr_c:g = {p['firecrawl']['contra_ratio']:.2f}", fillcolor="#F0FDF4", color="#16A34A"];
  b0 -> b1 -> b2 -> b3;
  t0 -> t1 -> t2 -> t3;
  f0 -> f1 -> f2 -> f3;
  {{ rank=same; b0; t0; f0; }}
  {{ rank=same; b1; t1; f1; }}
  {{ rank=same; b2; t2; f2; }}
  {{ rank=same; b3; t3; f3; }}
}}
'''


def build_partition_dot(stats: dict[str, Any]) -> str:
    p = stats["providers"]
    return f'''
digraph G {{
  graph [rankdir=TB, bgcolor="transparent", splines=ortho, nodesep=0.55, ranksep=0.55, margin=0.02];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, margin="0.08,0.05", color="#334155", penwidth=1.1, fillcolor="#F8FAFC"];
  edge [fontname="Helvetica", fontsize=8, color="#64748B", arrowsize=0.55, penwidth=1.0];
  start [label="For each provider-query pair\\njoin judge labels with agent actions", fillcolor="#F8FAFC", color="#334155"];
  gold [label="Any visible URL\\ncontains gold?", shape=diamond, fillcolor="#FEF3C7", color="#D97706"];
  fetched_gold [label="Agent fetched\\na gold URL?", shape=diamond, fillcolor="#DCFCE7", color="#16A34A"];
  fetched_any [label="Agent fetched\\nany URL?", shape=diamond, fillcolor="#E0F2FE", color="#0284C7"];
  smart [label="SMART\\nvisible support + fetched it\\nBrave {p['brave']['bucket']['smart'][0]}, Tavily {p['tavily']['bucket']['smart'][0]}, Firecrawl {p['firecrawl']['bucket']['smart'][0]}", fillcolor="#DCFCE7", color="#16A34A"];
  missed [label="MISSED\\nvisible support + did not fetch it\\nBrave {p['brave']['bucket']['missed'][0]}, Tavily {p['tavily']['bucket']['missed'][0]}, Firecrawl {p['firecrawl']['bucket']['missed'][0]}", fillcolor="#FEF9C3", color="#CA8A04"];
  blind [label="BLIND\\nno visible support + fetched\\nBrave {p['brave']['bucket']['blind'][0]}, Tavily {p['tavily']['bucket']['blind'][0]}, Firecrawl {p['firecrawl']['bucket']['blind'][0]}", fillcolor="#FFEDD5", color="#EA580C"];
  noop [label="NO-OP\\nno visible support + no fetch\\nBrave {p['brave']['bucket']['noop'][0]}, Tavily {p['tavily']['bucket']['noop'][0]}, Firecrawl {p['firecrawl']['bucket']['noop'][0]}", fillcolor="#E2E8F0", color="#475569"];
  start -> gold;
  gold -> fetched_gold [label="yes"];
  gold -> fetched_any [label="no"];
  fetched_gold -> smart [label="yes"];
  fetched_gold -> missed [label="no"];
  fetched_any -> blind [label="yes"];
  fetched_any -> noop [label="no"];
}}
'''


def render_all_figures(stats: dict[str, Any]) -> None:
    specs = {
        "fig_architecture": build_architecture_dot(stats),
        "fig_provider_profiles": build_provider_profiles_dot(stats),
        "fig_partition": build_partition_dot(stats),
    }
    for name, dot in specs.items():
        render_dot_to_tikz(name, dot)


def tex_escape(text: str) -> str:
    text = text.replace(r"\n", "\n")
    repl = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    out = "".join(repl.get(ch, ch) for ch in text)
    return out.replace("\n", r"\\")


def parse_node_attrs(dot: str) -> dict[str, dict[str, str]]:
    attrs: dict[str, dict[str, str]] = {}
    for line in dot.splitlines():
        line = line.strip()
        match = re.match(r"([A-Za-z0-9_]+)\s+\[(.*)\];", line)
        if not match:
            continue
        name, attr_text = match.groups()
        parsed: dict[str, str] = {}
        for attr_match in re.finditer(r'(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|[^,\]]+)', attr_text):
            key, value = attr_match.groups()
            if value.startswith('"'):
                value = bytes(value[1:-1], "utf-8").decode("unicode_escape")
            else:
                value = value.strip()
            parsed[key] = value
        attrs[name] = parsed
    return attrs


def render_dot_to_tikz(name: str, dot: str) -> None:
    dot_path = OUT / f"{name}.dot"
    dot_path.write_text(dot.strip() + "\n", encoding="utf-8")
    attrs = parse_node_attrs(dot)
    proc = subprocess.run(["dot", "-Tplain", str(dot_path)], check=True, text=True, capture_output=True)
    nodes: list[tuple[str, float, float, float, float, str]] = []
    edges: list[tuple[list[tuple[float, float]], str | None]] = []
    for line in proc.stdout.splitlines():
        parts = shlex.split(line)
        if not parts:
            continue
        if parts[0] == "node":
            _, node_id, x, y, width, height, label, *_ = parts
            nodes.append((node_id, float(x), float(y), float(width), float(height), label))
        elif parts[0] == "edge":
            n_points = int(parts[3])
            idx = 4
            pts: list[tuple[float, float]] = []
            for _ in range(n_points):
                pts.append((float(parts[idx]), float(parts[idx + 1])))
                idx += 2
            label = None
            # Graphviz plain edge labels are followed by x y after the label.
            if len(parts) >= idx + 3 and not _is_float(parts[idx]):
                label = parts[idx]
            edges.append((pts, label))
    tex = ["% Generated from Graphviz DOT by figures/make_figures.py; do not edit by hand.", TIKZ_PREAMBLE, TIKZ_STYLE]
    for pts, label in edges:
        coords = " -- ".join(f"({x:.3f},{y:.3f})" for x, y in pts)
        tex.append(rf"\draw[gvedge] {coords};")
        if label:
            x, y = pts[len(pts) // 2]
            tex.append(rf"\node[font=\tiny, fill=white, inner sep=1pt, text=slatemid] at ({x:.3f},{y:.3f}) {{{tex_escape(label)}}};")
    for node_id, x, y, width, height, label in nodes:
        node_attrs = attrs.get(node_id, {})
        fill = COLOR_NAMES.get(node_attrs.get("fillcolor", "#F8FAFC"), "slatefill")
        edge = COLOR_NAMES.get(node_attrs.get("color", "#334155"), "slateink")
        shape = node_attrs.get("shape", "box")
        if shape == "diamond":
            style = f"gvnode, diamond, aspect=2.1, fill={fill}, draw={edge}, text=slateink"
        else:
            style = f"gvnode, minimum width={width * 0.52:.3f}in, minimum height={height * 0.52:.3f}in, fill={fill}, draw={edge}, text=slateink"
        tex.append(rf"\node[{style}] ({node_id}) at ({x:.3f},{y:.3f}) {{{tex_escape(label)}}};")
    tex.append(r"\end{tikzpicture}")
    (OUT / f"{name}.tikz.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
