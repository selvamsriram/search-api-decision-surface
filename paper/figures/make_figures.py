#!/usr/bin/env python3
"""Regenerate paper macros and deterministic Graphviz vector figures.

Strict mode (default) requires the semantic audit TSV and raw judge JSONLs so
that all counts labeled Correct are semantic-match counts. Use --render-only
only for layout drafting; it uses validated constants plus the semantic TSV when
available.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent
REPO = PAPER.parent

PROVIDERS = ["brave", "tavily", "firecrawl"]
PLABEL = {"brave": "Brave", "tavily": "Tavily", "firecrawl": "Firecrawl"}

JUDGE_PATHS = {
    "brave": REPO / "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
    "tavily": REPO / "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
    "firecrawl": REPO / "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
}
SEMANTIC_TSV = REPO / "results/em_vs_semantic_audit.tsv"
PROVIDER_SUMMARY = REPO / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_summary.json"
PER_QUERY = REPO / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_per_query.jsonl"

FALLBACK = {
    "meta": {
        "queries": 100, "providers": 3, "traces": 300,
        "judge_total": 6909, "judge_valid": 6869, "judge_invalid": 40,
        "judge_snippet_valid": 6519, "judge_page_valid": 350,
        "all_correct": 10, "two_correct": 12, "one_correct": 22, "all_wrong": 56,
        "one_or_more_correct": 44, "best_single_correct": 26, "oracle_router_lift": 18,
        "overlap_regions": {
            "brave_tavily_firecrawl": 10, "brave_tavily": 4, "brave_firecrawl": 4,
            "tavily_firecrawl": 4, "brave": 7, "tavily": 7, "firecrawl": 8, "none": 56,
        },
    },
    "providers": {
        "brave": {
            "em": 21, "correct": 25, "correct_gain": 4, "f1": 0.270,
            "avg_search": 2.29, "avg_fetch": 1.02, "fetched_pct": 65,
            "avg_tokens": 59627, "tokens_m": 5.96, "median_tokens": 40638.5,
            "max_tokens": 303462, "queries_over_100k": 19, "fetch_success": 92,
            "fetch_failed": 10, "answered": 98, "abstained": 2,
            "gold_url_exact_hit": 59, "gold_url_prefix_hit": 63, "gold_domain_hit": 82,
            "gold_source_family_hit": 61, "snippet_surface_hit": 71,
            "answer_in_page": 52, "answer_available": 78,
            "wrong_with_answer_text_available": 57, "wrong_without_answer_text_available": 22,
            "pre_fetch_support_q": 30, "post_fetch_discovered_q": 3,
            "trajectory_visible_support_q": 33, "no_pre_fetch_support_q": 70,
            "support_visible_q": 33, "no_support_q": 70, "snippet_rows": 2095,
            "page_rows": 101, "gold_rows": 97, "contra_rows": 89,
            "pre_fetch_support_rows": 101, "post_fetch_discovered_rows": 3,
            "contra_ratio": 0.92, "rank1_count": 13, "rank1_pct": 13,
            "bucket": {"smart": [3, 3], "missed": [27, 11], "blind": [54, 11], "noop": [16, 0]},
        },
        "tavily": {
            "em": 21, "correct": 25, "correct_gain": 4, "f1": 0.261,
            "avg_search": 2.74, "avg_fetch": 1.30, "fetched_pct": 76,
            "avg_tokens": 54156, "tokens_m": 5.42, "median_tokens": 36867.5,
            "max_tokens": 305474, "queries_over_100k": 16, "fetch_success": 119,
            "fetch_failed": 11, "answered": 97, "abstained": 3,
            "gold_url_exact_hit": 57, "gold_url_prefix_hit": 62, "gold_domain_hit": 82,
            "gold_source_family_hit": 60, "snippet_surface_hit": 60,
            "answer_in_page": 57, "answer_available": 75,
            "wrong_with_answer_text_available": 56, "wrong_without_answer_text_available": 23,
            "pre_fetch_support_q": 16, "post_fetch_discovered_q": 8,
            "trajectory_visible_support_q": 24, "no_pre_fetch_support_q": 84,
            "support_visible_q": 24, "no_support_q": 84, "snippet_rows": 2339,
            "page_rows": 125, "gold_rows": 31, "contra_rows": 58,
            "pre_fetch_support_rows": 34, "post_fetch_discovered_rows": 9,
            "contra_ratio": 1.87, "rank1_count": 17, "rank1_pct": 50,
            "bucket": {"smart": [3, 1], "missed": [13, 7], "blind": [63, 16], "noop": [21, 1]},
        },
        "firecrawl": {
            "em": 23, "correct": 26, "correct_gain": 3, "f1": 0.282,
            "avg_search": 2.51, "avg_fetch": 1.28, "fetched_pct": 81,
            "avg_tokens": 57979, "tokens_m": 5.80, "median_tokens": 34383.5,
            "max_tokens": 380646, "queries_over_100k": 16, "fetch_success": 121,
            "fetch_failed": 7, "answered": 96, "abstained": 4,
            "gold_url_exact_hit": 60, "gold_url_prefix_hit": 63, "gold_domain_hit": 82,
            "gold_source_family_hit": 64, "snippet_surface_hit": 54,
            "answer_in_page": 61, "answer_available": 76,
            "wrong_with_answer_text_available": 53, "wrong_without_answer_text_available": 24,
            "pre_fetch_support_q": 16, "post_fetch_discovered_q": 3,
            "trajectory_visible_support_q": 19, "no_pre_fetch_support_q": 84,
            "support_visible_q": 19, "no_support_q": 84, "snippet_rows": 2085,
            "page_rows": 124, "gold_rows": 27, "contra_rows": 70,
            "pre_fetch_support_rows": 30, "post_fetch_discovered_rows": 3,
            "contra_ratio": 2.59, "rank1_count": 4, "rank1_pct": 13,
            "bucket": {"smart": [3, 1], "missed": [13, 7], "blind": [70, 18], "noop": [14, 0]},
        },
    },
    "pairwise": {
        "brave_vs_firecrawl": {"both_correct": 14, "brave_correct_only": 11, "firecrawl_correct_only": 12, "both_wrong": 63},
        "brave_vs_tavily": {"both_correct": 14, "brave_correct_only": 11, "tavily_correct_only": 11, "both_wrong": 64},
        "firecrawl_vs_tavily": {"both_correct": 14, "firecrawl_correct_only": 12, "tavily_correct_only": 11, "both_wrong": 63},
    },
}

FALLBACK_EXAMPLES = {
    "brave": [
        {"gold_answer": "Astra Zeneca", "model_answer": "AstraZeneca", "judgement_note": "Spacing only: Astra Zeneca == AstraZeneca"},
        {"gold_answer": "UnionPay", "model_answer": "China UnionPay", "judgement_note": "Same entity: China UnionPay is the full name of UnionPay"},
        {"gold_answer": "US$120,000", "model_answer": "$120,000", "judgement_note": "Same amount: $120,000 == US$120,000"},
    ],
    "tavily": [
        {"gold_answer": "Astra Zeneca", "model_answer": "AstraZeneca", "judgement_note": "Spacing only: Astra Zeneca == AstraZeneca"},
        {"gold_answer": "US$120,000", "model_answer": "$120,000", "judgement_note": "Same amount: $120,000 == US$120,000"},
        {"gold_answer": "3 players", "model_answer": "3", "judgement_note": "Same value: 3 == gold 3 players"},
    ],
    "firecrawl": [
        {"gold_answer": "Astra Zeneca", "model_answer": "AstraZeneca", "judgement_note": "Spacing only: Astra Zeneca == AstraZeneca"},
        {"gold_answer": "Bohemian Rhapsody", "model_answer": "Bohemian Rhapsody, 9,948,386 viewers", "judgement_note": "Correct entity plus extra detail"},
        {"gold_answer": "16 years", "model_answer": "16 years old", "judgement_note": "Same value: 16 years old == 16 years"},
    ],
}


def is_lfs_pointer(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:200].startswith("version https://git-lfs.github.com/spec/v1")
    except Exception:
        return False


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_semantic(strict: bool) -> tuple[dict[str, dict[str, int]], dict[tuple[str, str], bool], dict[str, list[dict[str, str]]]]:
    if not SEMANTIC_TSV.exists():
        if strict:
            raise FileNotFoundError(f"Missing semantic audit TSV: {SEMANTIC_TSV}")
        stats = {p: {"n": 100, "em": FALLBACK["providers"][p]["em"], "correct": FALLBACK["providers"][p]["correct"], "delta": FALLBACK["providers"][p]["correct_gain"]} for p in PROVIDERS}
        return stats, {}, FALLBACK_EXAMPLES
    stats = {p: {"n": 0, "em": 0, "correct": 0, "delta": 0} for p in PROVIDERS}
    sem: dict[tuple[str, str], bool] = {}
    examples: dict[str, list[dict[str, str]]] = {p: [] for p in PROVIDERS}
    with SEMANTIC_TSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            p = (row.get("provider") or "").lower()
            if p not in stats:
                continue
            qid = row.get("query_id") or ""
            em = int(row.get("em") or 0)
            sm = int(row.get("semantic_match") or 0)
            stats[p]["n"] += 1
            stats[p]["em"] += em
            stats[p]["correct"] += sm
            sem[(p, qid)] = bool(sm)
            if em == 0 and sm == 1 and len(examples[p]) < 8:
                examples[p].append(row)
    for p in PROVIDERS:
        if stats[p]["n"] != 100:
            raise RuntimeError(f"Expected 100 semantic rows for {p}, found {stats[p]['n']}")
        stats[p]["delta"] = stats[p]["correct"] - stats[p]["em"]
        if not examples[p]:
            examples[p] = FALLBACK_EXAMPLES[p]
    return stats, sem, examples


def load_provider_summary(data: dict[str, Any]) -> None:
    if not PROVIDER_SUMMARY.exists() or is_lfs_pointer(PROVIDER_SUMMARY):
        return
    summary = json.loads(PROVIDER_SUMMARY.read_text(encoding="utf-8"))
    for p in PROVIDERS:
        row = summary.get("providers", {}).get(p, {})
        if not row:
            continue
        d = data["providers"][p]
        d.update({
            "f1": round(row.get("avg_f1", d["f1"]), 3),
            "avg_search": round(row.get("avg_search_calls", d["avg_search"]), 2),
            "avg_tokens": round(row.get("avg_tokens", d["avg_tokens"])),
            "tokens_m": round(row.get("total_tokens", d["tokens_m"] * 1_000_000) / 1_000_000, 2),
            "median_tokens": row.get("median_tokens", d["median_tokens"]),
            "max_tokens": row.get("max_tokens", d["max_tokens"]),
            "queries_over_100k": row.get("queries_over_100k_tokens", d["queries_over_100k"]),
            "answered": row.get("answered", d["answered"]),
            "abstained": row.get("abstained", d["abstained"]),
            "gold_url_exact_hit": row.get("gold_url_exact_hit", d["gold_url_exact_hit"]),
            "gold_url_prefix_hit": row.get("gold_url_prefix_hit", d["gold_url_prefix_hit"]),
            "gold_domain_hit": row.get("gold_domain_hit", d["gold_domain_hit"]),
            "gold_source_family_hit": row.get("gold_source_family_hit", d["gold_source_family_hit"]),
            "answer_in_page": row.get("answer_in_page", d["answer_in_page"]),
            "answer_available": row.get("answer_in_any_retrieved_text", d["answer_available"]),
            "wrong_with_answer_text_available": row.get("wrong_with_answer_text_available", d["wrong_with_answer_text_available"]),
            "wrong_without_answer_text_available": row.get("wrong_without_answer_text_available", d["wrong_without_answer_text_available"]),
            "fetch_success": (row.get("fetch_status_counts") or {}).get("success", d["fetch_success"]),
            "fetch_failed": (row.get("fetch_status_counts") or {}).get("failed", d["fetch_failed"]),
        })
        # Fold Brave extra_snippets into a generic snippet-surface proxy.
        d["snippet_surface_hit"] = max(row.get("answer_in_snippet", 0), row.get("answer_in_extra_snippets", 0))


def valid_judge_row(r: dict[str, Any]) -> bool:
    return (
        r.get("schema_version") == "kimi_judge_record_v3"
        and isinstance(r.get("judgment"), dict)
        and not r.get("execution_error")
        and not r.get("judgment_parse_error")
        and bool(r.get("provider_id"))
        and bool(r.get("query_id"))
        and bool(r.get("url"))
    )


def compute_from_judge(data: dict[str, Any], sem: dict[tuple[str, str], bool]) -> bool:
    if not sem:
        return False
    if any((not p.exists()) or is_lfs_pointer(p) for p in JUDGE_PATHS.values()):
        return False
    total = valid_total = snippet_total = page_total = 0
    for p in PROVIDERS:
        provider_qids = sorted(q for provider, q in sem if provider == p)
        rows_all = load_jsonl(JUDGE_PATHS[p])
        rows = [r for r in rows_all if valid_judge_row(r)]
        snip = [r for r in rows if r.get("judge_surface_class") == "snippet_only"]
        page = [r for r in rows if r.get("judge_surface_class") == "page_visible"]
        total += len(rows_all); valid_total += len(rows); snippet_total += len(snip); page_total += len(page)
        gold_rows = sum(1 for r in snip if r["judgment"].get("contains_gold_answer"))
        contra_rows = sum(1 for r in snip if r["judgment"].get("contradicts_gold_answer"))
        rank1 = 0
        pre_fetch_support_rows = 0
        qstate: dict[str, dict[str, set[str]]] = {
            q: {"pre": set(), "page": set(), "fetched": set(), "legacy": set()}
            for q in provider_qids
        }
        for r in rows:
            q = r.get("query_id")
            u = r.get("normalized_url") or r.get("url")
            if not q or not u or q not in qstate:
                continue
            j = r.get("judgment") or {}
            surface = r.get("judge_surface_class")
            if j.get("contains_gold_answer"):
                qstate[q]["legacy"].add(u)
            # Fetched URLs are represented by page-visible rows rather than
            # duplicate snippet-only rows. The gold_answer_in_snippets field is
            # still snippet-only, so it is valid pre-fetch evidence even on a
            # page-visible judge row.
            pre_fetch_support = bool(j.get("gold_answer_in_snippets")) or (
                surface == "snippet_only" and bool(j.get("contains_gold_answer"))
            )
            if pre_fetch_support:
                qstate[q]["pre"].add(u)
                pre_fetch_support_rows += 1
                if int(r.get("rank") or 0) == 1:
                    rank1 += 1
            if surface == "page_visible":
                qstate[q]["fetched"].add(u)
                if j.get("gold_answer_in_extracted_page"):
                    qstate[q]["page"].add(u)
            elif r.get("model_fetched_document"):
                qstate[q]["fetched"].add(u)
        buckets = {"smart": [0, 0], "missed": [0, 0], "blind": [0, 0], "noop": [0, 0]}
        pre_fetch_support_q = post_fetch_discovered_q = trajectory_visible_support_q = 0
        post_fetch_discovered_rows = 0
        for q in provider_qids:
            st = qstate[q]
            correct = int(sem.get((p, q), False))
            pre = bool(st["pre"])
            post = (not pre) and bool(st["page"])
            trajectory = pre or post
            fetched = bool(st["fetched"])
            fetched_pre = bool(st["pre"] & st["fetched"])
            if pre:
                pre_fetch_support_q += 1
            if post:
                post_fetch_discovered_q += 1
                post_fetch_discovered_rows += len(st["page"])
            if trajectory:
                trajectory_visible_support_q += 1
            if pre and fetched_pre: b = "smart"
            elif pre and not fetched_pre: b = "missed"
            elif (not pre) and fetched: b = "blind"
            else: b = "noop"
            buckets[b][0] += 1
            buckets[b][1] += correct
        d = data["providers"][p]
        d.update({
            "pre_fetch_support_q": pre_fetch_support_q,
            "post_fetch_discovered_q": post_fetch_discovered_q,
            "trajectory_visible_support_q": trajectory_visible_support_q,
            "no_pre_fetch_support_q": 100 - pre_fetch_support_q,
            "support_visible_q": trajectory_visible_support_q,
            "no_support_q": 100 - pre_fetch_support_q,
            "snippet_rows": len(snip), "page_rows": len(page),
            "gold_rows": gold_rows, "contra_rows": contra_rows,
            "pre_fetch_support_rows": pre_fetch_support_rows,
            "post_fetch_discovered_rows": post_fetch_discovered_rows,
            "contra_ratio": round(contra_rows / gold_rows, 2) if gold_rows else float("nan"),
            "rank1_count": rank1,
            "rank1_pct": round(100 * rank1 / pre_fetch_support_rows) if pre_fetch_support_rows else 0,
            "bucket": buckets,
        })
    data["meta"].update({
        "judge_total": total, "judge_valid": valid_total, "judge_invalid": total - valid_total,
        "judge_snippet_valid": snippet_total, "judge_page_valid": page_total,
    })
    return True


def semantic_complementarity(sem: dict[tuple[str, str], bool]) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    if not sem:
        return FALLBACK["meta"], FALLBACK["pairwise"]
    qids = sorted({q for _, q in sem})
    counts: dict[str, Any] = {
        "all_correct": 0, "two_correct": 0, "one_correct": 0, "all_wrong": 0,
        "one_or_more_correct": 0, "best_single_correct": 0, "oracle_router_lift": 0,
        "overlap_regions": {
            "brave_tavily_firecrawl": 0, "brave_tavily": 0, "brave_firecrawl": 0,
            "tavily_firecrawl": 0, "brave": 0, "tavily": 0, "firecrawl": 0, "none": 0,
        },
    }
    for q in qids:
        correct = [p for p in PROVIDERS if sem.get((p, q), False)]
        k = len(correct)
        if k == 3: counts["all_correct"] += 1
        elif k == 2: counts["two_correct"] += 1
        elif k == 1: counts["one_correct"] += 1
        else: counts["all_wrong"] += 1
        key = "_".join(correct) if correct else "none"
        counts["overlap_regions"][key] += 1
    counts["one_or_more_correct"] = counts["all_correct"] + counts["two_correct"] + counts["one_correct"]
    counts["best_single_correct"] = max(sum(int(sem.get((p, q), False)) for q in qids) for p in PROVIDERS)
    counts["oracle_router_lift"] = counts["one_or_more_correct"] - counts["best_single_correct"]
    pairwise: dict[str, dict[str, int]] = {}
    for i, left in enumerate(PROVIDERS):
        for right in PROVIDERS[i + 1:]:
            c = {"both_correct": 0, f"{left}_correct_only": 0, f"{right}_correct_only": 0, "both_wrong": 0}
            for q in qids:
                l = bool(sem.get((left, q), False)); r = bool(sem.get((right, q), False))
                if l and r: c["both_correct"] += 1
                elif l: c[f"{left}_correct_only"] += 1
                elif r: c[f"{right}_correct_only"] += 1
                else: c["both_wrong"] += 1
            pairwise[f"{left}_vs_{right}"] = c
    return counts, pairwise


def pct(k: int, n: int) -> str:
    return f"{round(100 * k / n):.0f}\\%" if n else "--"


def rate(k: int, n: int) -> str:
    return f"{round(100 * k / n):.0f}%" if n else "--"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[int, int]:
    if n == 0:
        return (0, 0)
    phat = k / n
    den = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / den
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / den
    return (round(100 * max(0, center - half)), round(100 * min(1, center + half)))


def tex_escape(s: str) -> str:
    return (s or "").replace("\\", "\\textbackslash{}")\
        .replace("&", "\\&").replace("%", "\\%").replace("$", "\\$")\
        .replace("#", "\\#").replace("_", "\\_").replace("{", "\\{").replace("}", "\\}")


def write_numbers(data: dict[str, Any], stats: dict[str, dict[str, int]], examples: dict[str, list[dict[str, str]]], mode: str) -> None:
    out = ["% Auto-generated by figures/make_figures.py"]
    m = data["meta"]
    basics = {
        "NQueries": m["queries"], "NProviders": m["providers"], "NTraces": m["traces"],
        "NJudgeTotal": f"{m['judge_total']:,}", "NJudgeValid": f"{m['judge_valid']:,}",
        "NJudgeInvalid": m["judge_invalid"], "NJudgeSnippetValid": f"{m['judge_snippet_valid']:,}",
        "NJudgePageValid": m["judge_page_valid"], "AllCorrect": m["all_correct"],
        "TwoCorrect": m["two_correct"], "OneCorrect": m["one_correct"],
        "AllWrong": m["all_wrong"], "OneOrMoreCorrect": m["one_or_more_correct"],
        "MetricMode": mode, "CorrectMetricName": "semantic-correct",
    }
    for k, v in basics.items():
        out.append(f"\\newcommand{{\\{k}}}{{{v}}}")
    for p in PROVIDERS:
        d = data["providers"][p]
        s = stats[p]
        pref = PLABEL[p]
        vals = {
            "EM": s["em"], "Correct": s["correct"], "CorrectGain": s["delta"],
            "Fone": f"{d['f1']:.3f}", "SearchAvg": f"{d['avg_search']:.2f}",
            "FetchAvg": f"{d['avg_fetch']:.2f}", "FetchedPct": f"{d['fetched_pct']}\\%",
            "AvgTokens": f"{int(d['avg_tokens']):,}", "TokensM": f"{d['tokens_m']:.2f}",
            "MedianTokens": f"{int(float(d['median_tokens'])):,}", "MaxTokens": f"{int(d['max_tokens']):,}",
            "OverHundredK": d["queries_over_100k"], "FetchSuccess": d["fetch_success"],
            "FetchFailed": d["fetch_failed"], "Answered": d["answered"], "Abstained": d["abstained"],
            "GoldURLExact": d["gold_url_exact_hit"], "GoldDomain": d["gold_domain_hit"],
            "GoldFamily": d["gold_source_family_hit"], "SnippetSurfaceHit": d["snippet_surface_hit"],
            "AnswerPage": d["answer_in_page"], "AnswerAvailable": d["answer_available"],
            "WrongWithAnswer": d["wrong_with_answer_text_available"],
            "WrongWithoutAnswer": d["wrong_without_answer_text_available"],
            "PreFetchSupportQ": d["pre_fetch_support_q"],
            "PostFetchDiscoveredSupportQ": d["post_fetch_discovered_q"],
            "TrajectoryVisibleSupportQ": d["trajectory_visible_support_q"],
            "NoPreFetchSupportQ": d["no_pre_fetch_support_q"],
            "SupportVisibleQ": d["trajectory_visible_support_q"], "NoSupportQ": d["no_support_q"],
            "SnippetRows": f"{d['snippet_rows']:,}", "PageRows": d["page_rows"],
            "GoldRows": d["gold_rows"], "PreFetchSupportRows": d["pre_fetch_support_rows"],
            "PostFetchDiscoveredRows": d["post_fetch_discovered_rows"],
            "ContraRows": d["contra_rows"],
            "ContraRatio": f"{d['contra_ratio']:.2f}", "RankOneGold": d["rank1_count"],
            "RankOnePct": f"{d['rank1_pct']}\\%",
        }
        for k, v in vals.items():
            out.append(f"\\newcommand{{\\{pref}{k}}}{{{v}}}")
        for bucket in ["smart", "missed", "blind", "noop"]:
            n, c = d["bucket"][bucket]
            bp = pref + bucket.capitalize()
            lo, hi = wilson(c, n)
            out.extend([
                f"\\newcommand{{\\{bp}N}}{{{n}}}",
                f"\\newcommand{{\\{bp}Correct}}{{{c}}}",
                f"\\newcommand{{\\{bp}EM}}{{{c}}}",
                f"\\newcommand{{\\{bp}Rate}}{{{pct(c, n)}}}",
                f"\\newcommand{{\\{bp}CI}}{{[{lo}--{hi}]}}",
            ])
        sm_n, sm_c = d["bucket"]["smart"]
        mi_n, mi_c = d["bucket"]["missed"]
        gap = round(100 * sm_c / sm_n) - round(100 * mi_c / mi_n) if sm_n and mi_n else 0
        out.append(f"\\newcommand{{\\{pref}SmartMinusMissed}}{{{gap:+d}}}")
    for p in PROVIDERS:
        pref = PLABEL[p]
        for idx, ex in enumerate(examples[p][:3], start=1):
            word = ["One", "Two", "Three"][idx - 1]
            out.append(f"\\newcommand{{\\{pref}SemEx{word}Gold}}{{{tex_escape(ex.get('gold_answer', ''))}}}")
            out.append(f"\\newcommand{{\\{pref}SemEx{word}Ans}}{{{tex_escape(ex.get('model_answer', ''))}}}")
            note = ex.get("judgement_note", "").replace("EM-MISS (EM=0 but correct):", "").strip()
            out.append(f"\\newcommand{{\\{pref}SemEx{word}Note}}{{{tex_escape(note)}}}")
    (HERE / "numbers.tex").write_text("\n".join(out) + "\n", encoding="utf-8")


def render_dot(name: str, dot: str) -> None:
    dot_path = HERE / f"{name}.dot"
    dot_path.write_text(dot, encoding="utf-8")
    formats = ["pdf", "svg"]
    if name == "fig1_architecture":
        formats.append("png")
    for fmt in formats:
        subprocess.run(["dot", f"-T{fmt}", str(dot_path), "-o", str(HERE / f"{name}.{fmt}")], check=True)


def make_architecture() -> str:
    """Deterministic Graphviz block-flow diagram for the experiment pipeline."""
    return r'''digraph G {
  graph [rankdir=TB, bgcolor="white", margin=0.03, pad=0.02, nodesep=0.30, ranksep=0.34, splines=ortho, fontname="Helvetica"];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=13, penwidth=1.35, margin="0.12,0.07", color="#334155", fontcolor="#0F172A"];
  edge [fontname="Helvetica", fontsize=10, color="#64748B", arrowsize=0.7, penwidth=1.1, fontcolor="#475569"];

  q      [label=< <B>100 hard questions</B><BR/><FONT POINT-SIZE="10">SealQA-Hard stratified sample</FONT> >, fillcolor="#FFF7ED", color="#EA580C"];
  agent  [label=< <B>Frozen GPT-5.4 agent</B><BR/><FONT POINT-SIZE="10">same prompt, tools, budget</FONT> >, fillcolor="#EEF2FF", color="#4F46E5"];
  step   [label=< <B>Agent loop step</B><BR/><FONT POINT-SIZE="10">observe evidence, reason,<BR/>then choose next action</FONT> >, fillcolor="#FEF9C3", color="#CA8A04"];
  search [label=< <B>search_web</B><BR/><FONT POINT-SIZE="10">one or many calls</FONT> >, fillcolor="#E0F2FE", color="#0284C7"];
  prov   [label=< <B>Provider condition</B><BR/><FONT POINT-SIZE="10">Brave / Tavily / Firecrawl<BR/>only varied component</FONT> >, fillcolor="#F0FDFA", color="#0F766E"];
  surf   [label=< <B>Decision surface</B><BR/><FONT POINT-SIZE="10">document id, rank, title, URL,<BR/>snippet surface, metadata<BR/><I>no page text unless fetched</I></FONT> >, fillcolor="#DCFCE7", color="#16A34A"];
  fetch  [label=< <B>fetch_page</B><BR/><FONT POINT-SIZE="10">selected document IDs<BR/>shared Jina Reader backend</FONT> >, fillcolor="#FAE8FF", color="#9333EA"];
  obs    [label=< <B>Tool observations</B><BR/><FONT POINT-SIZE="10">search results or page evidence<BR/>returned to the agent</FONT> >, fillcolor="#F8FAFC", color="#475569"];
  ans    [label=< <B>Final answer</B><BR/><FONT POINT-SIZE="10">short answer or abstention</FONT> >, fillcolor="#E2E8F0", color="#475569"];
  trace  [label=< <B>Trajectory JSONL</B><BR/><FONT POINT-SIZE="10">all searches, visible URLs,<BR/>fetches, tokens, final + gold answer</FONT> >, fillcolor="#F8FAFC", color="#475569"];
  records [label=< <B>Judge records</B><BR/><FONT POINT-SIZE="10">one row per visible URL<BR/>page-visible rows include snippet fields</FONT> >, fillcolor="#FFE4E6", color="#E11D48"];
  kimi    [label=< <B>Kimi-K2.6 judge</B><BR/><FONT POINT-SIZE="10">gold support, contradiction,<BR/>model-answer support, spans,<BR/>garbage, confidence</FONT> >, fillcolor="#FDF2F8", color="#BE185D"];
  metrics [label=< <B>Decision-surface metrics</B><BR/><FONT POINT-SIZE="10">pre-fetch / post-fetch support,<BR/>SMART/MISSED/BLIND/NO-OP,<BR/>surface c:g, semantic-correct</FONT> >, fillcolor="#FFFBEB", color="#D97706"];

  q -> agent -> step;
  step -> search [color="#0284C7"];
  search -> prov -> surf -> obs;
  step -> fetch [color="#7C3AED"];
  fetch -> obs;
  obs -> step [color="#CA8A04", penwidth=1.5, constraint=false];
  step -> ans [color="#475569"];
  ans -> trace -> records -> kimi -> metrics;

  {rank=same; search; fetch;}
  subgraph cluster_exec {
    label="Execution lane: agent loop repeats until final answer; only search provider changes";
    color="#CBD5E1"; style="rounded"; penwidth=1.0; fontsize=15; fontname="Helvetica";
    q; agent; step; search; prov; surf; fetch; obs; ans; trace;
  }
  subgraph cluster_oracle {
    label="Oracle lane: replay visible evidence one URL at a time";
    color="#CBD5E1"; style="rounded"; penwidth=1.0; fontsize=15; fontname="Helvetica";
    records; kimi; metrics;
  }
}
'''


def make_profiles(data: dict[str, Any], stats: dict[str, dict[str, int]]) -> str:
    fills = {"brave": "#FEE2E2", "tavily": "#DBEAFE", "firecrawl": "#DCFCE7"}
    accents = {"brave": "#E11D48", "tavily": "#2563EB", "firecrawl": "#16A34A"}
    regimes = {"brave": "snippet-rich surface", "tavily": "rank-one concentration", "firecrawl": "broad exploration"}

    def bar(value: float, max_value: float, color: str, width: int = 112) -> str:
        filled = max(4, round(width * value / max_value)) if max_value else 4
        empty = max(4, width - filled)
        return f'''<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="0">
  <TR><TD WIDTH="{filled}" HEIGHT="9" BGCOLOR="{color}"></TD><TD WIDTH="{empty}" HEIGHT="9" BGCOLOR="#E5E7EB"></TD></TR>
</TABLE>'''

    def metric_row(label: str, value: float, shown: str, max_value: float, color: str) -> str:
        return f'''  <TR>
    <TD ALIGN="LEFT" WIDTH="66"><FONT POINT-SIZE="14">{label}</FONT></TD>
    <TD>{bar(value, max_value, color)}</TD>
    <TD WIDTH="52" ALIGN="RIGHT"><FONT POINT-SIZE="14"><B>{shown}</B></FONT></TD>
  </TR>'''

    cards = []
    support_max = max(data["providers"][provider]["pre_fetch_support_q"] for provider in PROVIDERS)
    rank_max = max(data["providers"][provider]["rank1_pct"] for provider in PROVIDERS)
    contra_max = max(data["providers"][provider]["contra_ratio"] for provider in PROVIDERS)
    fetch_max = max(data["providers"][provider]["fetched_pct"] for provider in PROVIDERS)
    for p in PROVIDERS:
        d = data["providers"][p]
        s = stats[p]
        color = accents[p]
        rows = [
            metric_row("Pre-fetch", d["pre_fetch_support_q"], f'{d["pre_fetch_support_q"]}', support_max, color),
            metric_row("Rank-1", d["rank1_pct"], f'{d["rank1_pct"]}%', rank_max, color),
            metric_row("Contra", d["contra_ratio"], f'{d["contra_ratio"]:.2f}', contra_max, color),
            metric_row("Fetch", d["fetched_pct"], f'{d["fetched_pct"]}%', fetch_max, color),
        ]
        cards.append(f'''  {p} [label=<
<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6">
  <TR><TD COLSPAN="3"><FONT POINT-SIZE="24"><B>{PLABEL[p]}</B></FONT></TD></TR>
  <TR><TD COLSPAN="3"><FONT POINT-SIZE="15">{regimes[p]}</FONT></TD></TR>
  <TR><TD COLSPAN="3"><FONT POINT-SIZE="22"><B>{s['correct']}/100</B> correct</FONT></TD></TR>
{''.join(rows)}
</TABLE>
>, fillcolor="{fills[p]}", color="#334155"];''')
    return f'''digraph G {{
  graph [rankdir=LR, bgcolor="white", margin=0.04, nodesep=0.45, ranksep=0.50, splines=ortho, fontname="Helvetica"];
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=16, margin="0.12,0.08", penwidth=1.6];
  edge [style=invis];
{chr(10).join(cards)}
  brave -> tavily -> firecrawl;
}}
'''


def make_partition(data: dict[str, Any]) -> str:
    rows = []
    for p in PROVIDERS:
        b = data["providers"][p]["bucket"]
        def cell(k: str) -> str:
            n, c = b[k]
            return f"{n} / {c} ({rate(c, n)})"
        rows.append(f'''<TR><TD><B>{PLABEL[p]}</B></TD><TD BGCOLOR="#DCFCE7">{cell('smart')}</TD><TD BGCOLOR="#FEF3C7">{cell('missed')}</TD><TD BGCOLOR="#FFEDD5">{cell('blind')}</TD><TD BGCOLOR="#E5E7EB">{cell('noop')}</TD></TR>''')
    return f'''digraph G {{
  graph [rankdir=TB, bgcolor="white", margin=0.04, fontname="Helvetica"];
  node [shape=plain, fontname="Helvetica"];
  part [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="10" COLOR="#CBD5E1">
    <TR><TD BGCOLOR="#111827"><FONT COLOR="white"><B>Provider</B></FONT></TD><TD BGCOLOR="#166534"><FONT COLOR="white"><B>SMART</B><BR/><FONT POINT-SIZE="11">pre-fetch support + fetched it</FONT></FONT></TD><TD BGCOLOR="#A16207"><FONT COLOR="white"><B>MISSED</B><BR/><FONT POINT-SIZE="11">pre-fetch support + did not fetch it</FONT></FONT></TD><TD BGCOLOR="#C2410C"><FONT COLOR="white"><B>BLIND</B><BR/><FONT POINT-SIZE="11">no pre-fetch support + fetched</FONT></FONT></TD><TD BGCOLOR="#374151"><FONT COLOR="white"><B>NO-OP</B><BR/><FONT POINT-SIZE="11">no pre-fetch support + no fetch</FONT></FONT></TD></TR>
    {''.join(rows)}
  </TABLE>>];
}}
'''


def make_complementarity(meta: dict[str, int]) -> str:
    regions = meta.get("overlap_regions", {})
    def n(key: str) -> int:
        return int(regions.get(key, 0)) if isinstance(regions, dict) else 0
    def dot(on: bool) -> str:
        color = "#111827" if on else "#CBD5E1"
        glyph = "&#9679;" if on else "&#9675;"
        return f'<FONT POINT-SIZE="20" COLOR="{color}">{glyph}</FONT>'
    rows = [
        ("All three providers", True, True, True, n("brave_tavily_firecrawl"), "#DCFCE7"),
        ("Brave + Tavily only", True, True, False, n("brave_tavily"), "#EFF6FF"),
        ("Brave + Firecrawl only", True, False, True, n("brave_firecrawl"), "#EFF6FF"),
        ("Tavily + Firecrawl only", False, True, True, n("tavily_firecrawl"), "#EFF6FF"),
        ("Brave only", True, False, False, n("brave"), "#FEF3C7"),
        ("Tavily only", False, True, False, n("tavily"), "#FEF3C7"),
        ("Firecrawl only", False, False, True, n("firecrawl"), "#FEF3C7"),
        ("None correct", False, False, False, n("none"), "#FEE2E2"),
    ]
    row_html = "\n".join(
        f'''    <TR>
      <TD ALIGN="LEFT" WIDTH="310" BGCOLOR="{bg}">{label}</TD>
      <TD WIDTH="125" BGCOLOR="{bg}">{dot(b)}</TD>
      <TD WIDTH="125" BGCOLOR="{bg}">{dot(t)}</TD>
      <TD WIDTH="125" BGCOLOR="{bg}">{dot(f)}</TD>
      <TD WIDTH="115" BGCOLOR="{bg}"><FONT POINT-SIZE="22"><B>{count}</B></FONT></TD>
    </TR>'''
        for label, b, t, f, count, bg in rows
    )
    return f'''digraph G {{
  graph [rankdir=TB, bgcolor="white", margin=0.04, fontname="Helvetica"];
  node [shape=plain, fontname="Helvetica"];
  upset [label=<
  <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#CBD5E1">
    <TR>
      <TD COLSPAN="5" BGCOLOR="#F8FAFC"><FONT POINT-SIZE="20"><B>Semantic-correct overlap across providers</B></FONT><BR/><FONT POINT-SIZE="13">Any provider: <B>{meta.get('one_or_more_correct',0)}</B> / 100 &nbsp;&nbsp; Best single: <B>{meta.get('best_single_correct',0)}</B> / 100 &nbsp;&nbsp; Oracle routing lift: <B>+{meta.get('oracle_router_lift',0)}</B></FONT></TD>
    </TR>
    <TR>
      <TD WIDTH="310" BGCOLOR="#111827"><FONT COLOR="white"><B>Region</B></FONT></TD>
      <TD WIDTH="125" BGCOLOR="#111827"><FONT COLOR="white"><B>Brave</B></FONT></TD>
      <TD WIDTH="125" BGCOLOR="#111827"><FONT COLOR="white"><B>Tavily</B></FONT></TD>
      <TD WIDTH="125" BGCOLOR="#111827"><FONT COLOR="white"><B>Firecrawl</B></FONT></TD>
      <TD WIDTH="115" BGCOLOR="#111827"><FONT COLOR="white"><B>Queries</B></FONT></TD>
    </TR>
{row_html}
  </TABLE>>];
}}
'''


def write_audit_md(data: dict[str, Any], stats: dict[str, dict[str, int]], examples: dict[str, list[dict[str, str]]], mode: str) -> None:
    lines = [
        "# Decision-surface audit", "",
        f"Source mode: `{mode}`.", "",
        "Correctness is `semantic_match` from `results/em_vs_semantic_audit.tsv`; exact match and normalized token F1 are retained as deterministic answer-overlap diagnostics.", "",
        "| Provider | Correct | EM | Gain | Pre-fetch support | Post-fetch discovered | Trajectory-visible | SMART | MISSED | BLIND | NO-OP | c:g |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in PROVIDERS:
        d = data["providers"][p]; b = d["bucket"]; s = stats[p]
        lines.append(f"| {PLABEL[p]} | {s['correct']} | {s['em']} | +{s['delta']} | {d['pre_fetch_support_q']} | {d['post_fetch_discovered_q']} | {d['trajectory_visible_support_q']} | {b['smart'][0]}/{b['smart'][1]} | {b['missed'][0]}/{b['missed'][1]} | {b['blind'][0]}/{b['blind'][1]} | {b['noop'][0]}/{b['noop'][1]} | {d['contra_ratio']:.2f} |")
    lines += ["", "## Semantic EM-miss examples", ""]
    for p in PROVIDERS:
        lines.append(f"### {PLABEL[p]}")
        for ex in examples[p][:5]:
            lines.append(f"- `{ex.get('gold_answer','')}` vs. `{ex.get('model_answer','')}`: {ex.get('judgement_note','')}")
        lines.append("")
    (HERE / "decision_surface_audit.md").write_text("\n".join(lines), encoding="utf-8")
    (HERE / "decision_surface_audit.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()
    strict = not args.render_only

    data = json.loads(json.dumps(FALLBACK))
    stats, sem, examples = load_semantic(strict=strict)
    load_provider_summary(data)
    raw_ok = compute_from_judge(data, sem)
    if strict and not raw_ok:
        missing = [str(path.relative_to(REPO)) for path in JUDGE_PATHS.values() if (not path.exists()) or is_lfs_pointer(path)]
        raise SystemExit("Raw judge JSONLs are missing or still Git LFS pointers: " + ", ".join(missing) + "\nRun `git lfs pull` from the repository root.")
    comp, pairwise = semantic_complementarity(sem)
    data["meta"].update(comp)
    data["pairwise"] = pairwise
    for p in PROVIDERS:
        data["providers"][p]["em"] = stats[p]["em"]
        data["providers"][p]["correct"] = stats[p]["correct"]
        data["providers"][p]["correct_gain"] = stats[p]["delta"]
    mode = "raw_judge+semantic_tsv" if raw_ok else "render_only_semantic_tsv+validated_surface_constants"
    write_numbers(data, stats, examples, mode)
    write_audit_md(data, stats, examples, mode)
    render_dot("fig1_architecture", make_architecture())
    render_dot("fig2_provider_profiles", make_profiles(data, stats))
    render_dot("fig3_decision_partition", make_partition(data))
    render_dot("fig4_complementarity", make_complementarity(data["meta"]))
    print(f"Wrote figures/macros in {HERE} ({mode})")


if __name__ == "__main__":
    main()
