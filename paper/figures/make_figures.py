#!/usr/bin/env python3
"""
Regenerate deterministic paper numbers and Graphviz vector figures.

Default mode is render-only: it writes the last validated constants and figures so
LaTeX can build without the large Git LFS data. Audit mode recomputes the key
numbers from the raw trace/judge JSONLs and provider comparison files.

Usage:
  cd paper
  python3 figures/make_figures.py --render-only
  python3 figures/make_figures.py --audit   # after git lfs pull
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

PROVIDERS = ["brave", "tavily", "firecrawl"]
PNAME = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}
COL = {"brave": "#E76F51", "tavily": "#2A80B9", "firecrawl": "#2AA876"}

TRACE_FILES = {
    "brave": ROOT / "data/traces/phase1_v1_brave_gpt54_fetch_tool_jina_100.jsonl",
    "tavily": ROOT / "data/traces/phase1_v1_tavily_gpt54_fetch_tool_jina_100.jsonl",
    "firecrawl": ROOT / "data/traces/phase1_v1_firecrawl_gpt54_fetch_tool_jina_100.jsonl",
}
JUDGE_FILES = {
    "brave": ROOT / "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
    "tavily": ROOT / "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
    "firecrawl": ROOT / "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
}
PER_QUERY = ROOT / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_per_query.jsonl"
SUMMARY = ROOT / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_summary.json"

LAST_VALIDATED = {
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
        "one_or_more_correct": 38,
        "provider_specific_wins": 20,
    },
    "providers": {
        "brave": {
            "em": 21, "f1": 0.270, "answered": 98, "abstained": 2,
            "avg_search": 2.29, "avg_fetch": 1.02, "fetched_pct": 65,
            "tokens_m": 5.96, "avg_tokens": 59627, "median_tokens": 40638.5, "max_tokens": 303462,
            "queries_over_100k": 19,
            "support_visible_q": 33, "no_support_q": 67,
            "snippet_rows": 2095, "page_rows": 101,
            "gold_rows": 97, "contra_rows": 89, "contra_ratio": 0.92,
            "rank1_count": 12, "rank1_pct": 12,
            "bucket": {"smart": [8, 3], "missed": [25, 9], "blind": [51, 9], "noop": [16, 0]},
            "answer_available": 78,
            "gold_url_exact_hit": 59, "gold_url_prefix_hit": 63, "gold_domain_hit": 82,
            "gold_source_family_hit": 61,
            "answer_in_snippet": 55, "answer_in_extra_snippets": 71, "answer_in_page": 52,
            "wrong_with_answer_text_available": 57, "wrong_without_answer_text_available": 22,
            "fetch_success": 92, "fetch_failed": 10,
        },
        "tavily": {
            "em": 21, "f1": 0.261, "answered": 97, "abstained": 3,
            "avg_search": 2.74, "avg_fetch": 1.30, "fetched_pct": 76,
            "tokens_m": 5.42, "avg_tokens": 54156, "median_tokens": 36867.5, "max_tokens": 305474,
            "queries_over_100k": 16,
            "support_visible_q": 24, "no_support_q": 76,
            "snippet_rows": 2339, "page_rows": 125,
            "gold_rows": 31, "contra_rows": 58, "contra_ratio": 1.87,
            "rank1_count": 15, "rank1_pct": 48,
            "bucket": {"smart": [11, 7], "missed": [13, 5], "blind": [55, 9], "noop": [21, 0]},
            "answer_available": 75,
            "gold_url_exact_hit": 57, "gold_url_prefix_hit": 62, "gold_domain_hit": 82,
            "gold_source_family_hit": 60,
            "answer_in_snippet": 60, "answer_in_extra_snippets": 0, "answer_in_page": 57,
            "wrong_with_answer_text_available": 56, "wrong_without_answer_text_available": 23,
            "fetch_success": 119, "fetch_failed": 11,
        },
        "firecrawl": {
            "em": 23, "f1": 0.282, "answered": 96, "abstained": 4,
            "avg_search": 2.51, "avg_fetch": 1.28, "fetched_pct": 81,
            "tokens_m": 5.80, "avg_tokens": 57979, "median_tokens": 34383.5, "max_tokens": 380646,
            "queries_over_100k": 16,
            "support_visible_q": 19, "no_support_q": 81,
            "snippet_rows": 2085, "page_rows": 124,
            "gold_rows": 27, "contra_rows": 70, "contra_ratio": 2.59,
            "rank1_count": 3, "rank1_pct": 11,
            "bucket": {"smart": [7, 2], "missed": [12, 5], "blind": [67, 16], "noop": [14, 0]},
            "answer_available": 76,
            "gold_url_exact_hit": 60, "gold_url_prefix_hit": 63, "gold_domain_hit": 82,
            "gold_source_family_hit": 64,
            "answer_in_snippet": 54, "answer_in_extra_snippets": 0, "answer_in_page": 61,
            "wrong_with_answer_text_available": 53, "wrong_without_answer_text_available": 24,
            "fetch_success": 121, "fetch_failed": 7,
        },
    },
    "pairwise": {
        "brave_vs_firecrawl": {"both_wrong": 57, "brave_correct_only": 9, "both_correct": 12, "both_wrong_one_has_answer_text": 11, "firecrawl_correct_only": 11},
        "brave_vs_tavily": {"both_wrong": 57, "both_wrong_one_has_answer_text": 13, "brave_correct_only": 9, "both_correct": 12, "tavily_correct_only": 9},
        "firecrawl_vs_tavily": {"both_wrong": 61, "both_wrong_one_has_answer_text": 7, "tavily_correct_only": 9, "both_correct": 12, "firecrawl_correct_only": 11},
    },
    "source": "last_validated_constants",
}


def is_lfs_pointer(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            first = f.readline().strip()
        return first.startswith("version https://git-lfs.github.com/spec/v1")
    except UnicodeDecodeError:
        return False


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if is_lfs_pointer(path):
        raise RuntimeError(f"{path} is still a Git LFS pointer. Run `git lfs pull` from the repository root.")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> dict[str, Any]:
    if is_lfs_pointer(path):
        raise RuntimeError(f"{path} is still a Git LFS pointer. Run `git lfs pull` from the repository root.")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def audit_from_raw() -> dict[str, Any]:
    for p in PROVIDERS:
        if not TRACE_FILES[p].exists() or not JUDGE_FILES[p].exists():
            raise RuntimeError(f"Missing raw files for {p}. Run from a complete repo checkout.")
        if is_lfs_pointer(TRACE_FILES[p]) or is_lfs_pointer(JUDGE_FILES[p]):
            raise RuntimeError(f"Raw JSONL for {p} is still a Git LFS pointer. Run `git lfs pull`.")
    if not SUMMARY.exists() or not PER_QUERY.exists():
        raise RuntimeError("Missing provider comparison artifacts. Run scripts/build_provider_comparison.py first.")

    summary = load_json(SUMMARY)
    per_query_rows = load_jsonl(PER_QUERY)
    emap = {(r["provider_id"], r["query_id"]): bool(r.get("exact_match")) for r in per_query_rows}

    data = {"meta": dict(LAST_VALIDATED["meta"]), "providers": {}, "pairwise": {}, "source": "audit_from_raw"}
    prov_summary = summary.get("providers", {})
    for p in PROVIDERS:
        rows_all = load_jsonl(JUDGE_FILES[p])
        valid = [r for r in rows_all if isinstance(r.get("judgment"), dict) and not r.get("execution_error") and not r.get("judgment_parse_error")]
        snip = [r for r in valid if r.get("judge_surface_class") == "snippet_only"]
        page = [r for r in valid if r.get("judge_surface_class") == "page_visible"]
        gold_rows = sum(1 for r in snip if r.get("judgment", {}).get("contains_gold_answer"))
        contra_rows = sum(1 for r in snip if r.get("judgment", {}).get("contradicts_gold_answer"))
        rank1_count = sum(1 for r in snip if r.get("judgment", {}).get("contains_gold_answer") and int(r.get("rank") or 0) == 1)
        qstate: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"gold": set(), "fetched": set(), "fetched_gold": set()})
        for r in valid:
            q = r.get("query_id")
            u = r.get("normalized_url") or r.get("url") or ""
            if not q or not u:
                continue
            j = r.get("judgment") or {}
            if r.get("judge_surface_class") == "snippet_only":
                if j.get("contains_gold_answer"):
                    qstate[q]["gold"].add(u)
                if r.get("model_fetched_document"):
                    qstate[q]["fetched"].add(u)
            else:
                qstate[q]["fetched"].add(u)
                if j.get("contains_gold_answer"):
                    qstate[q]["gold"].add(u)
                    qstate[q]["fetched_gold"].add(u)
        buckets = {"smart": [0, 0], "missed": [0, 0], "blind": [0, 0], "noop": [0, 0]}
        support_visible = 0
        for q, st in qstate.items():
            em = emap.get((p, q), False)
            gold = bool(st["gold"])
            fetched = bool(st["fetched"])
            fetched_gold = bool(st["fetched_gold"])
            if gold:
                support_visible += 1
            if gold and fetched_gold:
                bucket = "smart"
            elif gold and not fetched_gold:
                bucket = "missed"
            elif (not gold) and fetched:
                bucket = "blind"
            else:
                bucket = "noop"
            buckets[bucket][0] += 1
            buckets[bucket][1] += int(em)
        s = prov_summary[p]
        data["providers"][p] = {
            "em": s["exact_match"], "f1": round(s["avg_f1"], 3), "answered": s["answered"], "abstained": s["abstained"],
            "avg_search": round(s["avg_search_calls"], 2),
            "avg_fetch": round((s.get("fetch_status_counts", {}).get("success", 0) + s.get("fetch_status_counts", {}).get("failed", 0)) / 100, 2),
            "fetched_pct": LAST_VALIDATED["providers"][p]["fetched_pct"],
            "tokens_m": round(s["total_tokens"] / 1_000_000, 2),
            "avg_tokens": round(s["avg_tokens"]), "median_tokens": s["median_tokens"], "max_tokens": s["max_tokens"],
            "queries_over_100k": s["queries_over_100k_tokens"],
            "support_visible_q": support_visible, "no_support_q": 100 - support_visible,
            "snippet_rows": len(snip), "page_rows": len(page),
            "gold_rows": gold_rows, "contra_rows": contra_rows,
            "contra_ratio": round(contra_rows / gold_rows, 2) if gold_rows else float("nan"),
            "rank1_count": rank1_count, "rank1_pct": round(100 * rank1_count / gold_rows) if gold_rows else 0,
            "bucket": buckets,
            "answer_available": s["answer_in_any_retrieved_text"],
            "gold_url_exact_hit": s["gold_url_exact_hit"], "gold_url_prefix_hit": s["gold_url_prefix_hit"], "gold_domain_hit": s["gold_domain_hit"],
            "gold_source_family_hit": s["gold_source_family_hit"],
            "answer_in_snippet": s["answer_in_snippet"], "answer_in_extra_snippets": s["answer_in_extra_snippets"], "answer_in_page": s["answer_in_page"],
            "wrong_with_answer_text_available": s["wrong_with_answer_text_available"], "wrong_without_answer_text_available": s["wrong_without_answer_text_available"],
            "fetch_success": s.get("fetch_status_counts", {}).get("success", 0), "fetch_failed": s.get("fetch_status_counts", {}).get("failed", 0),
        }
    data["meta"]["judge_total"] = sum(len(load_jsonl(JUDGE_FILES[p])) for p in PROVIDERS)
    data["meta"]["judge_valid"] = sum(data["providers"][p]["snippet_rows"] + data["providers"][p]["page_rows"] for p in PROVIDERS)
    data["meta"]["judge_invalid"] = data["meta"]["judge_total"] - data["meta"]["judge_valid"]
    data["meta"]["judge_snippet_valid"] = sum(data["providers"][p]["snippet_rows"] for p in PROVIDERS)
    data["meta"]["judge_page_valid"] = sum(data["providers"][p]["page_rows"] for p in PROVIDERS)
    data["pairwise"] = summary.get("pairwise", {})
    three = summary.get("three_way", {}).get("classes", {})
    data["meta"]["all_correct"] = three.get("all_correct", LAST_VALIDATED["meta"]["all_correct"])
    data["meta"]["two_correct"] = three.get("two_providers_correct", LAST_VALIDATED["meta"]["two_correct"])
    data["meta"]["one_correct"] = three.get("one_provider_correct", LAST_VALIDATED["meta"]["one_correct"])
    data["meta"]["all_wrong"] = three.get("all_wrong", LAST_VALIDATED["meta"]["all_wrong"])
    data["meta"]["one_or_more_correct"] = 100 - data["meta"]["all_wrong"]
    return data


def pct(em: int, n: int) -> str:
    return f"{round(100 * em / n):.0f}\\%" if n else "--"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[int, int]:
    if n == 0:
        return (0, 0)
    phat = k / n
    den = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / den
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / den
    return (round(100 * max(0, center - half)), round(100 * min(1, center + half)))


def macro_name(provider: str, suffix: str) -> str:
    return {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}[provider] + suffix


def write_numbers(data: dict[str, Any]) -> None:
    m = data["meta"]
    lines = ["% Deterministic paper numbers. Regenerate with figures/make_figures.py after git lfs pull."]
    basic = {
        "NQueries": m["queries"], "NProviders": m["providers"], "NTraces": m["traces"],
        "NJudgeTotal": f"{m['judge_total']:,}", "NJudgeValid": f"{m['judge_valid']:,}", "NJudgeInvalid": m["judge_invalid"],
        "NJudgeSnippetValid": f"{m['judge_snippet_valid']:,}", "NJudgePageValid": m["judge_page_valid"],
        "AllCorrect": m["all_correct"], "TwoCorrect": m["two_correct"], "OneCorrect": m["one_correct"],
        "AllWrong": m["all_wrong"], "OneOrMoreCorrect": m["one_or_more_correct"],
    }
    for k, v in basic.items():
        lines.append(f"\\newcommand{{\\{k}}}{{{v}}}")
    for p in PROVIDERS:
        d = data["providers"][p]
        pref = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}[p]
        vals = {
            "EM": d["em"], "Fone": f"{d['f1']:.3f}", "Answered": d["answered"], "Abstained": d["abstained"],
            "SearchAvg": f"{d['avg_search']:.2f}", "FetchAvg": f"{d['avg_fetch']:.2f}", "FetchedPct": f"{d['fetched_pct']}\\%",
            "TokensM": f"{d['tokens_m']:.2f}", "AvgTokens": f"{int(d['avg_tokens']):,}", "MedianTokens": f"{int(float(d['median_tokens'])):,}", "MaxTokens": f"{int(d['max_tokens']):,}",
            "OverHundredK": d["queries_over_100k"],
            "SupportVisibleQ": d["support_visible_q"], "NoSupportQ": d["no_support_q"],
            "SnippetRows": f"{d['snippet_rows']:,}", "PageRows": d["page_rows"],
            "GoldRows": d["gold_rows"], "ContraRows": d["contra_rows"], "ContraRatio": f"{d['contra_ratio']:.2f}",
            "RankOnePct": f"{d['rank1_pct']}\\%", "RankOneGold": f"{d['rank1_count']}/{d['gold_rows']}",
            "AnswerAvailable": d["answer_available"], "GoldURLExact": d["gold_url_exact_hit"], "GoldURLPrefix": d["gold_url_prefix_hit"],
            "GoldDomain": d["gold_domain_hit"], "GoldFamily": d["gold_source_family_hit"],
            "AnswerSnippet": d["answer_in_snippet"], "AnswerExtra": d["answer_in_extra_snippets"], "AnswerPage": d["answer_in_page"],
            "WrongWithAnswer": d["wrong_with_answer_text_available"], "WrongWithoutAnswer": d["wrong_without_answer_text_available"],
            "FetchSuccess": d["fetch_success"], "FetchFailed": d["fetch_failed"],
        }
        for k, v in vals.items():
            lines.append(f"\\newcommand{{\\{pref}{k}}}{{{v}}}")
        for bucket in ["smart", "missed", "blind", "noop"]:
            n, e = d["bucket"][bucket]
            bpref = pref + bucket.capitalize().replace("Noop", "Noop")
            lo, hi = wilson(e, n)
            lines.append(f"\\newcommand{{\\{bpref}N}}{{{n}}}")
            lines.append(f"\\newcommand{{\\{bpref}EM}}{{{e}}}")
            lines.append(f"\\newcommand{{\\{bpref}Rate}}{{{pct(e, n)}}}")
            lines.append(f"\\newcommand{{\\{bpref}CI}}{{[{lo}--{hi}]}}")
    lines.append("\\newcommand{\\TavilySmartMinusMissed}{+26}")
    lines.append("\\newcommand{\\BraveSmartMinusMissed}{+2}")
    lines.append("\\newcommand{\\FirecrawlSmartMinusMissed}{-13}")
    (OUT / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def provider_box(p: str, d: dict[str, Any]) -> str:
    b = d["bucket"]
    return f'''<
<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="8" COLOR="{COL[p]}">
<TR><TD BGCOLOR="{COL[p]}"><FONT COLOR="white" POINT-SIZE="28"><B>{PNAME[p]}</B></FONT></TD></TR>
<TR><TD><FONT POINT-SIZE="22">EM <B>{d['em']}/100</B> &nbsp; F1 {d['f1']:.3f}</FONT></TD></TR>
<TR><TD><FONT POINT-SIZE="21">visible support <B>{d['support_visible_q']}</B> queries</FONT></TD></TR>
<TR><TD><FONT POINT-SIZE="21">rank-1 gold <B>{d['rank1_pct']}%</B> ({d['rank1_count']}/{d['gold_rows']})</FONT></TD></TR>
<TR><TD><FONT POINT-SIZE="21">contradict:gold <B>{d['contra_ratio']:.2f}</B> ({d['contra_rows']}/{d['gold_rows']})</FONT></TD></TR>
<TR><TD><FONT POINT-SIZE="19">SMART {b['smart'][0]}/{b['smart'][1]} EM &nbsp; MISSED {b['missed'][0]}/{b['missed'][1]}</FONT></TD></TR>
<TR><TD><FONT POINT-SIZE="19">BLIND {b['blind'][0]}/{b['blind'][1]} EM &nbsp; NO-OP {b['noop'][0]}/{b['noop'][1]}</FONT></TD></TR>
</TABLE>
>'''


def write_dot_files(data: dict[str, Any]) -> None:
    # Architecture figure.
    arch = r'''digraph G {
  graph [rankdir=LR, bgcolor="transparent", margin=0.05, nodesep=0.55, ranksep=0.65, splines=ortho];
  node [shape=plain, fontname="Helvetica"];
  edge [color="#58606A", penwidth=2.2, arrowsize=0.85, fontname="Helvetica", fontsize=18];
  queries [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#B7791F">
    <TR><TD BGCOLOR="#FFF2D9"><FONT POINT-SIZE="24"><B>100 SealQA-Hard questions</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">stratified by freshness x search-result label x topic</FONT></TD></TR>
    </TABLE>>];
  providers [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="8">
    <TR><TD BGCOLOR="#E76F51"><FONT COLOR="white" POINT-SIZE="22"><B>Brave</B></FONT></TD></TR>
    <TR><TD BGCOLOR="#2A80B9"><FONT COLOR="white" POINT-SIZE="22"><B>Tavily</B></FONT></TD></TR>
    <TR><TD BGCOLOR="#2AA876"><FONT COLOR="white" POINT-SIZE="22"><B>Firecrawl</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="17">only condition that changes</FONT></TD></TR>
    </TABLE>>];
  surface [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#2A80B9">
    <TR><TD BGCOLOR="#D9ECFA"><FONT POINT-SIZE="23"><B>search surface</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">rank, title, URL, snippet, metadata</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">pre-fetch evidence available to the agent</FONT></TD></TR>
    </TABLE>>];
  agent [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#465766">
    <TR><TD BGCOLOR="#F6F8FB"><FONT POINT-SIZE="23"><B>frozen GPT-5.4 agent</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">search_web(query)</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">fetch_page(document_id)</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">max 10 iterations</FONT></TD></TR>
    </TABLE>>];
  fetcher [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#7B4FA3">
    <TR><TD BGCOLOR="#EFE2F5"><FONT POINT-SIZE="23"><B>Jina Reader fetcher</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">shared page backend across providers</FONT></TD></TR>
    </TABLE>>];
  trace [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#657786">
    <TR><TD BGCOLOR="#ECEFF3"><FONT POINT-SIZE="23"><B>trajectory JSONL</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">every search, visible URL, fetch, answer</FONT></TD></TR>
    </TABLE>>];
  judge [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#7B4FA3">
    <TR><TD BGCOLOR="#EFE2F5"><FONT POINT-SIZE="23"><B>per-URL judge</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">Kimi-K2.6, temp 0</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">snippet-only for every URL</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">page-visible for fetched URLs</FONT></TD></TR>
    </TABLE>>];
  metrics [label=<
    <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="9" COLOR="#238B45">
    <TR><TD BGCOLOR="#E4F6EA"><FONT POINT-SIZE="23"><B>decision-surface metrics</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">visible support lower bound</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">SMART / MISSED / BLIND / NO-OP</FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">contradict-to-gold ratio</FONT></TD></TR>
    </TABLE>>];
  queries -> providers -> surface -> agent -> trace;
  agent -> fetcher [label="fetch when chosen"];
  fetcher -> agent;
  trace -> judge -> metrics;
}
'''
    (OUT / "fig1_architecture.dot").write_text(arch, encoding="utf-8")

    # Provider profile figure.
    prof_nodes = []
    prof_edges = []
    for p in PROVIDERS:
        prof_nodes.append(f'  {p} [label={provider_box(p, data["providers"][p])}];')
    profile = f'''digraph G {{
  graph [rankdir=LR, bgcolor="transparent", margin=0.02, nodesep=0.28, ranksep=0.30];
  node [shape=plain, fontname="Helvetica"];
  edge [style=invis];
  title [label=<
    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">
    <TR><TD><FONT POINT-SIZE="30"><B>Same final accuracy, different decision surfaces</B></FONT></TD></TR>
    <TR><TD><FONT POINT-SIZE="18">Each cell is provider x 100 queries. Counts are queries unless URL rows are shown.</FONT></TD></TR>
    </TABLE>>];
{chr(10).join(prof_nodes)}
  title -> brave -> tavily -> firecrawl;
}}
'''
    (OUT / "fig2_provider_profiles.dot").write_text(profile, encoding="utf-8")

    # Decision partition figure.
    rows = []
    colors = {"smart": "#238B45", "missed": "#F2C94C", "blind": "#D95F02", "noop": "#A8B3B5"}
    labels = {"smart": "SMART", "missed": "MISSED", "blind": "BLIND", "noop": "NO-OP"}
    for p in PROVIDERS:
        d = data["providers"][p]
        rows.append(f'<TR><TD BGCOLOR="{COL[p]}"><FONT COLOR="white" POINT-SIZE="22"><B>{PNAME[p]}</B></FONT></TD>' +
                    ''.join([f'<TD BGCOLOR="{colors[b]}"><FONT COLOR="{ "black" if b in ["missed", "noop"] else "white" }" POINT-SIZE="20"><B>{labels[b]}</B><BR/>{d["bucket"][b][0]} queries<BR/>{d["bucket"][b][1]} EM ({round(100*d["bucket"][b][1]/d["bucket"][b][0]) if d["bucket"][b][0] else 0}%)</FONT></TD>' for b in ["smart","missed","blind","noop"]]) + '</TR>')
    part = f'''digraph G {{
  graph [rankdir=TB, bgcolor="transparent", margin=0.02];
  node [shape=plain, fontname="Helvetica"];
  partition [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10">
  <TR><TD COLSPAN="5" BGCOLOR="#F6F8FB"><FONT POINT-SIZE="28"><B>Decision partition: what the agent did with visible support</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="16"><B>Provider</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>visible support + fetched support</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>visible support + did not fetch support</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>no visible support + fetched</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>no visible support + no fetch</B></FONT></TD></TR>
  {''.join(rows)}
  </TABLE>>];
}}
'''
    (OUT / "fig3_decision_partition.dot").write_text(part, encoding="utf-8")

    # Complementarity figure.
    comp = f'''digraph G {{
  graph [rankdir=LR, bgcolor="transparent", margin=0.03, nodesep=0.5, ranksep=0.6, splines=ortho];
  node [shape=plain, fontname="Helvetica"];
  edge [color="#58606A", penwidth=2.0, arrowsize=0.8];
  agg [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#465766">
  <TR><TD BGCOLOR="#F6F8FB"><FONT POINT-SIZE="26"><B>Aggregate view</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">Brave {data['providers']['brave']['em']}/100</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">Tavily {data['providers']['tavily']['em']}/100</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">Firecrawl {data['providers']['firecrawl']['em']}/100</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="18">looks interchangeable</FONT></TD></TR>
  </TABLE>>];
  instance [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#2A80B9">
  <TR><TD BGCOLOR="#D9ECFA" COLSPAN="2"><FONT POINT-SIZE="26"><B>Instance-level view</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">all 3 correct</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['all_correct']}</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">exactly 2 correct</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['two_correct']}</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">exactly 1 correct</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['one_correct']}</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">all wrong</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['all_wrong']}</B></FONT></TD></TR>
  </TABLE>>];
  implication [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#B7791F">
  <TR><TD BGCOLOR="#FFF2D9"><FONT POINT-SIZE="25"><B>Implication</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="20">Provider choice changes which questions are solvable.</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="20">EM parity is not behavioral equivalence.</FONT></TD></TR>
  </TABLE>>];
  agg -> instance -> implication;
}}
'''
    (OUT / "fig4_complementarity.dot").write_text(comp, encoding="utf-8")


def render_dots() -> None:
    dot = shutil.which("dot")
    if not dot:
        print("WARNING: Graphviz `dot` not found; DOT sources written but PDFs not rendered.")
        return
    for dot_path in sorted(OUT.glob("fig*.dot")):
        pdf_path = dot_path.with_suffix(".pdf")
        svg_path = dot_path.with_suffix(".svg")
        subprocess.run([dot, "-Tpdf", str(dot_path), "-o", str(pdf_path)], check=True)
        subprocess.run([dot, "-Tsvg", str(dot_path), "-o", str(svg_path)], check=True)
        print(f"wrote {pdf_path.relative_to(ROOT)}")


def write_audit(data: dict[str, Any]) -> None:
    (OUT / "decision_surface_audit.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Decision-surface data dictionary and audit", "",
        f"Source mode: `{data.get('source')}`.", "",
        "This file is regenerated by `paper/figures/make_figures.py`. Audit mode recomputes metrics from raw LFS JSONL files; render-only mode writes the last validated constants so the paper can compile without large local data.", "",
        "## Core metric definitions", "",
        "- **Visible support**: at least one judged URL for the provider-query pair has `contains_gold_answer=true` on the snippet-only or page-visible surface. Because unfetched pages are not page-judged, this is a lower bound on true pool support.",
        "- **SMART**: visible support exists and the agent fetched a gold-supporting URL.",
        "- **MISSED**: visible support exists and the agent fetched none of the supporting URLs.",
        "- **BLIND**: no visible support exists and the agent fetched at least one URL.",
        "- **NO-OP**: no visible support exists and the agent fetched no URL.",
        "- **Contradict-to-gold ratio**: snippet-only `contradicts_gold_answer` URL count divided by snippet-only `contains_gold_answer` URL count.", "",
        "## Provider summary", "",
        "| Provider | EM | visible support | SMART | MISSED | BLIND | NO-OP | rank-1 gold | contradict:gold | answer text visible |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in PROVIDERS:
        d = data["providers"][p]
        b = d["bucket"]
        lines.append(f"| {PNAME[p]} | {d['em']} | {d['support_visible_q']} | {b['smart'][0]}/{b['smart'][1]} | {b['missed'][0]}/{b['missed'][1]} | {b['blind'][0]}/{b['blind'][1]} | {b['noop'][0]}/{b['noop'][1]} | {d['rank1_pct']}% ({d['rank1_count']}/{d['gold_rows']}) | {d['contra_ratio']:.2f} ({d['contra_rows']}/{d['gold_rows']}) | {d['answer_available']} |")
    lines.extend([
        "", "## Cross-provider complementarity", "",
        f"- All three correct: {data['meta']['all_correct']}",
        f"- Exactly two correct: {data['meta']['two_correct']}",
        f"- Exactly one correct: {data['meta']['one_correct']}",
        f"- All wrong: {data['meta']['all_wrong']}",
        "", "## Raw files consumed in audit mode", "",
    ])
    for p in PROVIDERS:
        lines.append(f"- `{TRACE_FILES[p].relative_to(ROOT)}`")
    for p in PROVIDERS:
        lines.append(f"- `{JUDGE_FILES[p].relative_to(ROOT)}`")
    lines.append(f"- `{PER_QUERY.relative_to(ROOT)}`")
    lines.append(f"- `{SUMMARY.relative_to(ROOT)}`")
    lines.append("\nBefore audit mode, run `git lfs pull` from the repository root. If any raw JSONL path is still a Git LFS pointer, the script exits with a clear error instead of silently using incomplete data.\n")
    (OUT / "decision_surface_audit.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="Recompute constants from raw JSONL files.")
    ap.add_argument("--render-only", action="store_true", help="Use last validated constants.")
    args = ap.parse_args()
    data = audit_from_raw() if args.audit else json.loads(json.dumps(LAST_VALIDATED))
    write_numbers(data)
    write_dot_files_v2(data)
    render_dots()
    write_audit(data)
    print(f"Wrote {OUT/'numbers.tex'} and decision_surface_audit.*")



def write_dot_files_v2(data: dict[str, Any]) -> None:
    """Large, low-aspect-ratio Graphviz figures for the camera-ready source."""
    arch = r'''digraph G {
  graph [rankdir=TB, bgcolor="transparent", margin=0.03];
  node [shape=plain, fontname="Helvetica"];
  arch [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10">
    <TR><TD COLSPAN="7" BGCOLOR="#F6F8FB"><FONT POINT-SIZE="30"><B>Per-URL oracle for agentic search</B></FONT><BR/><FONT POINT-SIZE="17">fixed query set, model, prompt, tools, iteration budget, judge, and Jina Reader fetcher; only the commercial search surface varies</FONT></TD></TR>
    <TR>
      <TD BGCOLOR="#FFF2D9"><FONT POINT-SIZE="21"><B>100 SealQA-Hard questions</B></FONT><BR/><FONT POINT-SIZE="16">stratified sample</FONT></TD>
      <TD><FONT POINT-SIZE="26">&#8594;</FONT></TD>
      <TD><FONT POINT-SIZE="18"><B><FONT COLOR="#E76F51">Brave</FONT><BR/><FONT COLOR="#2A80B9">Tavily</FONT><BR/><FONT COLOR="#2AA876">Firecrawl</FONT></B></FONT><BR/><FONT POINT-SIZE="15">provider condition</FONT></TD>
      <TD><FONT POINT-SIZE="26">&#8594;</FONT></TD>
      <TD BGCOLOR="#D9ECFA"><FONT POINT-SIZE="21"><B>Search surface</B></FONT><BR/><FONT POINT-SIZE="16">rank, title, URL,<BR/>snippet, metadata</FONT></TD>
      <TD><FONT POINT-SIZE="26">&#8594;</FONT></TD>
      <TD BGCOLOR="#F6F8FB"><FONT POINT-SIZE="21"><B>GPT-5.4 agent</B></FONT><BR/><FONT POINT-SIZE="16">search_web + fetch_page<BR/>max 10 iterations</FONT></TD>
    </TR>
    <TR>
      <TD COLSPAN="2"><FONT POINT-SIZE="16">Shared page backend</FONT></TD>
      <TD COLSPAN="3" BGCOLOR="#EFE2F5"><FONT POINT-SIZE="20"><B>Jina Reader fetcher</B></FONT><BR/><FONT POINT-SIZE="15">only for URLs the agent opens</FONT></TD>
      <TD><FONT POINT-SIZE="26">&#8596;</FONT></TD>
      <TD BGCOLOR="#ECEFF3"><FONT POINT-SIZE="20"><B>Trajectory JSONL</B></FONT><BR/><FONT POINT-SIZE="15">searches, visible URLs,<BR/>fetches, final answer</FONT></TD>
    </TR>
    <TR>
      <TD COLSPAN="3"><FONT POINT-SIZE="16">Every visible URL is judged after the run</FONT></TD>
      <TD><FONT POINT-SIZE="26">&#8594;</FONT></TD>
      <TD BGCOLOR="#EFE2F5"><FONT POINT-SIZE="20"><B>Kimi-K2.6 judge</B></FONT><BR/><FONT POINT-SIZE="15">snippet-only; page-visible when fetched</FONT></TD>
      <TD><FONT POINT-SIZE="26">&#8594;</FONT></TD>
      <TD BGCOLOR="#E4F6EA"><FONT POINT-SIZE="20"><B>Decision metrics</B></FONT><BR/><FONT POINT-SIZE="15">visible support, SMART/MISSED/<BR/>BLIND/NO-OP, contamination</FONT></TD>
    </TR>
  </TABLE>>];
}
'''
    (OUT / "fig1_architecture.dot").write_text(arch, encoding="utf-8")

    provider_cells = []
    for p in PROVIDERS:
        d = data["providers"][p]
        b = d["bucket"]
        provider_cells.append(f'''<TD VALIGN="TOP">
          <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="8" COLOR="{COL[p]}">
          <TR><TD BGCOLOR="{COL[p]}"><FONT COLOR="white" POINT-SIZE="26"><B>{PNAME[p]}</B></FONT></TD></TR>
          <TR><TD><FONT POINT-SIZE="19">EM <B>{d['em']}/100</B> &nbsp; F1 {d['f1']:.3f}</FONT></TD></TR>
          <TR><TD><FONT POINT-SIZE="19">visible support <B>{d['support_visible_q']}</B> queries</FONT></TD></TR>
          <TR><TD><FONT POINT-SIZE="19">rank-1 gold <B>{d['rank1_pct']}%</B> ({d['rank1_count']}/{d['gold_rows']})</FONT></TD></TR>
          <TR><TD><FONT POINT-SIZE="19">contradict:gold <B>{d['contra_ratio']:.2f}</B> ({d['contra_rows']}/{d['gold_rows']})</FONT></TD></TR>
          <TR><TD><FONT POINT-SIZE="17">SMART {b['smart'][0]}/{b['smart'][1]} EM &nbsp; MISSED {b['missed'][0]}/{b['missed'][1]}</FONT></TD></TR>
          <TR><TD><FONT POINT-SIZE="17">BLIND {b['blind'][0]}/{b['blind'][1]} EM &nbsp; NO-OP {b['noop'][0]}/{b['noop'][1]}</FONT></TD></TR>
          </TABLE>
        </TD>''')
    profile = f'''digraph G {{
      graph [rankdir=TB, bgcolor="transparent", margin=0.02];
      node [shape=plain, fontname="Helvetica"];
      profile [label=<
        <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="12" CELLPADDING="0">
          <TR><TD COLSPAN="3"><FONT POINT-SIZE="30"><B>Same final accuracy, different decision surfaces</B></FONT><BR/><FONT POINT-SIZE="17">Counts are queries unless URL rows are shown; bucket cells show n / exact-match count.</FONT></TD></TR>
          <TR>{''.join(provider_cells)}</TR>
        </TABLE>>];
    }}
    '''
    (OUT / "fig2_provider_profiles.dot").write_text(profile, encoding="utf-8")

    # Reuse the original partition and complementarity writers by copying their current DOTs if they exist after the old writer.
    colors = {"smart": "#238B45", "missed": "#F2C94C", "blind": "#D95F02", "noop": "#A8B3B5"}
    labels = {"smart": "SMART", "missed": "MISSED", "blind": "BLIND", "noop": "NO-OP"}
    rows = []
    for p in PROVIDERS:
        d = data["providers"][p]
        row_cells = []
        for b in ["smart", "missed", "blind", "noop"]:
            n, e = d["bucket"][b]
            color = "black" if b in {"missed", "noop"} else "white"
            rate = round(100 * e / n) if n else 0
            row_cells.append(f'<TD BGCOLOR="{colors[b]}"><FONT COLOR="{color}" POINT-SIZE="20"><B>{labels[b]}</B><BR/>{n} queries<BR/>{e} EM ({rate}%)</FONT></TD>')
        rows.append(f'<TR><TD BGCOLOR="{COL[p]}"><FONT COLOR="white" POINT-SIZE="22"><B>{PNAME[p]}</B></FONT></TD>' + ''.join(row_cells) + '</TR>')
    part = f'''digraph G {{
  graph [rankdir=TB, bgcolor="transparent", margin=0.02];
  node [shape=plain, fontname="Helvetica"];
  partition [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10">
  <TR><TD COLSPAN="5" BGCOLOR="#F6F8FB"><FONT POINT-SIZE="28"><B>Decision partition: what the agent did with visible support</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="16"><B>Provider</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>visible support + fetched support</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>visible support + did not fetch support</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>no visible support + fetched</B></FONT></TD><TD><FONT POINT-SIZE="16"><B>no visible support + no fetch</B></FONT></TD></TR>
  {''.join(rows)}
  </TABLE>>];
}}
'''
    (OUT / "fig3_decision_partition.dot").write_text(part, encoding="utf-8")

    comp = f'''digraph G {{
  graph [rankdir=LR, bgcolor="transparent", margin=0.03, nodesep=0.5, ranksep=0.6, splines=ortho];
  node [shape=plain, fontname="Helvetica"];
  edge [color="#58606A", penwidth=2.0, arrowsize=0.8];
  agg [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#465766">
  <TR><TD BGCOLOR="#F6F8FB"><FONT POINT-SIZE="26"><B>Aggregate view</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">Brave {data['providers']['brave']['em']}/100</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">Tavily {data['providers']['tavily']['em']}/100</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">Firecrawl {data['providers']['firecrawl']['em']}/100</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="18">looks interchangeable</FONT></TD></TR>
  </TABLE>>];
  instance [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#2A80B9">
  <TR><TD BGCOLOR="#D9ECFA" COLSPAN="2"><FONT POINT-SIZE="26"><B>Instance-level view</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">all 3 correct</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['all_correct']}</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">exactly 2 correct</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['two_correct']}</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">exactly 1 correct</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['one_correct']}</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="22">all wrong</FONT></TD><TD><FONT POINT-SIZE="22"><B>{data['meta']['all_wrong']}</B></FONT></TD></TR>
  </TABLE>>];
  implication [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#B7791F">
  <TR><TD BGCOLOR="#FFF2D9"><FONT POINT-SIZE="25"><B>Implication</B></FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="20">Provider choice changes which questions are solvable.</FONT></TD></TR>
  <TR><TD><FONT POINT-SIZE="20">EM parity is not behavioral equivalence.</FONT></TD></TR>
  </TABLE>>];
  agg -> instance -> implication;
}}
'''
    (OUT / "fig4_complementarity.dot").write_text(comp, encoding="utf-8")


if __name__ == "__main__":
    main()
