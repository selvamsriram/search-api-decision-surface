#!/usr/bin/env python3
"""
Regenerate the three figures used in main.tex.

All numbers are recomputed from source data so this script doubles
as a validation harness — diffs against hardcoded numbers in the
paper are printed at the end.

Usage:
    cd paper/figures && python3 make_figures.py
Outputs:
    fig1_buckets.pdf
    fig2_rank_distribution.pdf
    fig3_contradict_ratio.pdf
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Resolve repo root from this script's location
REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

JUDGE = {
    "Brave": REPO / "results/llm_judge/kimi_document_judge_surface_v3_brave_100_all_visible.jsonl",
    "Tavily": REPO / "results/llm_judge/kimi_document_judge_surface_v3_tavily_100_all_visible.jsonl",
    "Firecrawl": REPO / "results/llm_judge/kimi_document_judge_surface_v3_firecrawl_100_all_visible.jsonl",
}
PER_QUERY = REPO / "results/provider_comparison/brave_tavily_firecrawl_fetch_tool_jina/provider_per_query.jsonl"

PROVIDERS = ["Brave", "Tavily", "Firecrawl"]
PROVIDER_KEYS = {"Brave": "brave", "Tavily": "tavily", "Firecrawl": "firecrawl"}
COLORS = {"Brave": "#E76F51", "Tavily": "#2A80B9", "Firecrawl": "#2AA876"}

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "axes.edgecolor": "#202A33",
        "axes.labelcolor": "#202A33",
        "axes.titlecolor": "#202A33",
        "xtick.color": "#202A33",
        "ytick.color": "#202A33",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


def load_judge(path: Path) -> list[dict]:
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("judgment") is not None:
                rows.append(r)
    return rows


def load_per_query() -> dict[tuple[str, str], dict]:
    out = {}
    with open(PER_QUERY) as fh:
        for line in fh:
            r = json.loads(line)
            out[(r["provider_id"], r["query_id"])] = r
    return out


def compute_buckets(rows: list[dict], emap: dict, provider_key: str) -> dict:
    """Clean 4-bucket partition of all 100 queries per provider.

    SMART:  gold visible AND model fetched at least one gold-supporting URL.
    MISSED: gold visible AND model did NOT fetch any gold-supporting URL.
            (subdivides into "foolish" = fetched something else, vs
            "passive" = no fetches at all)
    BLIND:  no gold visible AND model fetched at least one URL.
    NO-OP:  no gold visible AND no fetches.
    These four buckets partition the 100 queries with no overlap.
    """
    q_state: dict[str, dict] = {}
    for r in rows:
        q = r["query_id"]
        u = r["normalized_url"]
        j = r["judgment"]
        st = q_state.setdefault(
            q, {"gold_urls": set(), "fetched_urls": set(), "fetched_gold": set()}
        )
        if r["judge_surface_class"] == "snippet_only":
            if j.get("contains_gold_answer"):
                st["gold_urls"].add(u)
            if r.get("model_fetched_document"):
                st["fetched_urls"].add(u)
        else:  # page_visible
            st["fetched_urls"].add(u)
            if j.get("contains_gold_answer"):
                st["gold_urls"].add(u)
                st["fetched_gold"].add(u)
    buckets = {"smart": [], "missed": [], "blind": [], "noop": []}
    for q, s in q_state.items():
        em = emap.get((provider_key, q), {}).get("exact_match", False)
        gold = bool(s["gold_urls"])
        fetched_any = bool(s["fetched_urls"])
        fetched_gold = bool(s["fetched_gold"])
        if gold and fetched_gold:
            buckets["smart"].append((q, em))
        elif gold and not fetched_gold:
            buckets["missed"].append((q, em))
        elif (not gold) and fetched_any:
            buckets["blind"].append((q, em))
        else:
            buckets["noop"].append((q, em))
    return buckets


def compute_rank_dist(rows: list[dict]) -> Counter:
    rd = Counter()
    for r in rows:
        if r["judge_surface_class"] == "snippet_only" and r["judgment"].get(
            "contains_gold_answer"
        ):
            rd[r.get("rank", 99)] += 1
    return rd


def compute_contradict_ratio(rows: list[dict]) -> tuple[int, int, float]:
    snip = [r for r in rows if r["judge_surface_class"] == "snippet_only"]
    n_gold = sum(1 for r in snip if r["judgment"].get("contains_gold_answer"))
    n_contra = sum(1 for r in snip if r["judgment"].get("contradicts_gold_answer"))
    ratio = n_contra / n_gold if n_gold else float("nan")
    return n_gold, n_contra, ratio


def main():
    emap = load_per_query()
    judge_rows = {p: load_judge(JUDGE[p]) for p in PROVIDERS}
    buckets = {
        p: compute_buckets(judge_rows[p], emap, PROVIDER_KEYS[p]) for p in PROVIDERS
    }
    rank_dist = {p: compute_rank_dist(judge_rows[p]) for p in PROVIDERS}
    contradict = {p: compute_contradict_ratio(judge_rows[p]) for p in PROVIDERS}

    # ---------- Validation: hardcoded numbers in paper ----------
    # Expected values from the paper after the partition fix.
    expected = {
        "Brave":     {"smart": 8,  "missed": 25, "blind": 51, "noop": 16,
                      "smart_em": 3, "missed_em": 9, "blind_em": 9, "noop_em": 0,
                      "gold": 97, "contradicts": 89, "ratio": 0.92},
        "Tavily":    {"smart": 11, "missed": 13, "blind": 55, "noop": 21,
                      "smart_em": 7, "missed_em": 5, "blind_em": 9, "noop_em": 0,
                      "gold": 31, "contradicts": 58, "ratio": 1.87},
        "Firecrawl": {"smart": 7,  "missed": 12, "blind": 67, "noop": 14,
                      "smart_em": 2, "missed_em": 5, "blind_em": 16, "noop_em": 0,
                      "gold": 27, "contradicts": 70, "ratio": 2.59},
    }
    diffs = []
    for p in PROVIDERS:
        b = buckets[p]
        n_b = {k: len(v) for k, v in b.items()}
        em_b = {k: sum(em for _, em in v) for k, v in b.items()}
        total = sum(n_b.values())
        if total != 100:
            diffs.append(f"{p} bucket totals: {total} (expected 100)")
        for k in ("smart", "missed", "blind", "noop"):
            if n_b[k] != expected[p][k]:
                diffs.append(f"{p} bucket {k}: paper={expected[p][k]} actual={n_b[k]}")
            if em_b[k] != expected[p][f"{k}_em"]:
                diffs.append(
                    f"{p} {k} EM: paper={expected[p][f'{k}_em']} actual={em_b[k]}"
                )
        ng, nc, ratio = contradict[p]
        if ng != expected[p]["gold"]:
            diffs.append(f"{p} #gold URLs: paper={expected[p]['gold']} actual={ng}")
        if nc != expected[p]["contradicts"]:
            diffs.append(f"{p} #contradicts: paper={expected[p]['contradicts']} actual={nc}")
        if abs(ratio - expected[p]["ratio"]) > 0.005:
            diffs.append(
                f"{p} contradict:gold ratio: paper={expected[p]['ratio']} actual={ratio:.3f}"
            )

    print("=" * 60)
    print("VALIDATION DIFFS vs hardcoded paper numbers")
    print("=" * 60)
    if not diffs:
        print("ALL OK — every figure number matches the paper.")
    else:
        for d in diffs:
            print(f"  MISMATCH: {d}")
    print()

    print("Per-provider bucket EM rates (computed live):")
    for p in PROVIDERS:
        b = buckets[p]
        print(f"  {p}:")
        for k in ("smart", "missed", "blind", "noop"):
            n = len(b[k])
            em = sum(em for _, em in b[k])
            pct = 100 * em / n if n else 0
            print(f"    {k:6s} n={n:3d} EM={em:3d} ({pct:.1f}%)")

    # ---------- FIGURE 1: smart/missed/blind/no-op stacked bars ----------
    fig, ax = plt.subplots(figsize=(7.0, 3.55))
    bucket_order = ["smart", "missed", "blind", "noop"]
    bucket_colors = ["#238B45", "#F2C94C", "#D95F02", "#A8B3B5"]
    bucket_labels = ["SMART", "MISSED", "BLIND", "NO-OP"]
    x = np.arange(len(PROVIDERS))
    width = 0.62
    bottoms = np.zeros(len(PROVIDERS))
    for bk, color, label in zip(bucket_order, bucket_colors, bucket_labels):
        heights = np.array([len(buckets[p][bk]) for p in PROVIDERS])
        bars = ax.bar(x, heights, width, bottom=bottoms, color=color,
                      edgecolor="white", linewidth=1.0, label=label)
        for i, (h, b) in enumerate(zip(heights, bottoms)):
            if h < 1:
                continue
            n = h
            em = sum(em for _, em in buckets[PROVIDERS[i]][bk])
            pct = 100 * em / n if n else 0
            # All labels go inside the bar; SMART (thinnest) uses a single line.
            if h >= 12:
                txt = f"n={n}\nEM {pct:.0f}%"
                fs = 8.6
            else:
                txt = f"n={n}, EM {pct:.0f}%"
                fs = 8.1
            ax.text(x[i], b + h / 2, txt,
                    ha="center", va="center", fontsize=fs,
                    color="#202A33" if color in ("#F2C94C", "#A8B3B5") else "white",
                    fontweight="bold")
        bottoms += heights
    for i, p in enumerate(PROVIDERS):
        total_em = sum(sum(em for _, em in buckets[p][bk]) for bk in bucket_order)
        ax.text(x[i], 103.3, f"overall EM {total_em}%",
                ha="center", va="bottom", fontsize=8.2,
                color="#596B7A", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(PROVIDERS, fontsize=10.5)
    ax.set_xlim(-0.58, 2.58)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Queries (out of 100)", fontsize=10)
    ax.set_title("Agent decisions by provider, with bucket EM",
                 fontsize=11, pad=9, fontweight="bold")
    ax.yaxis.grid(True, color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12),
              ncol=4, fontsize=9, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT / "fig1_buckets.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig1_buckets.png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    print(f"Wrote {OUT/'fig1_buckets.pdf'}")

    # ---------- FIGURE 2: rank distribution of gold-supporting URLs ----------
    fig, ax = plt.subplots(figsize=(6.55, 3.05))
    ranks = list(range(1, 11))
    x = np.array(ranks)
    for p in PROVIDERS:
        counts = [rank_dist[p].get(r, 0) for r in ranks]
        total = sum(counts)
        pct = [100 * c / total if total else 0 for c in counts]
        ax.plot(
            x,
            pct,
            color=COLORS[p],
            marker="o",
            markersize=4.8,
            linewidth=2.0,
            label=f"{p} (n={total})",
        )
        ax.fill_between(x, pct, [0] * len(pct), color=COLORS[p], alpha=0.055)
    ax.set_xticks(x)
    ax.set_xticklabels([str(r) for r in ranks], fontsize=10)
    ax.set_xlabel("Search-result rank", fontsize=10)
    ax.set_ylabel("% of gold-supporting URLs", fontsize=10)
    ax.set_title("Where gold-supporting URLs appear in the ranked surface",
                 fontsize=11, pad=8, fontweight="bold")
    ax.legend(fontsize=9, frameon=False, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(0, 55)
    ax.set_xlim(0.8, 10.2)
    ax.yaxis.grid(True, color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    # Annotate Tavily rank-1
    tavily_r1 = rank_dist["Tavily"].get(1, 0) / sum(rank_dist["Tavily"].values()) * 100
    ax.annotate(f"{tavily_r1:.0f}% at rank 1",
                xy=(1, tavily_r1),
                xytext=(2.05, 48), fontsize=9,
                arrowprops=dict(arrowstyle="->", color=COLORS["Tavily"], lw=1.2),
                color=COLORS["Tavily"], fontweight="bold")
    plt.tight_layout()
    fig.savefig(OUT / "fig2_rank_distribution.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig2_rank_distribution.png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    print(f"Wrote {OUT/'fig2_rank_distribution.pdf'}")

    # ---------- FIGURE 3: contradict:gold ratio ----------
    fig, ax = plt.subplots(figsize=(5.0, 2.85))
    ratios = [contradict[p][2] for p in PROVIDERS]
    y = np.arange(len(PROVIDERS))
    bar_colors = [COLORS[p] for p in PROVIDERS]
    bars = ax.barh(y, ratios, color=bar_colors, height=0.52,
                   edgecolor="white", linewidth=0.9)
    ax.axvline(1.0, color="#7A8A8B", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.text(1.03, 0.94, "balanced 1.0",
            transform=ax.get_xaxis_transform(),
            color="#7A8A8B", fontsize=8, va="top", ha="left")
    for bar, p, r in zip(bars, PROVIDERS, ratios):
        ng, nc, _ = contradict[p]
        ax.text(bar.get_width() + 0.08,
                bar.get_y() + bar.get_height() / 2,
                f"{r:.2f}  ({nc}/{ng})", ha="left", va="center",
                fontsize=9, fontweight="bold", color="#202A33")
    ax.set_yticks(y)
    ax.set_yticklabels(PROVIDERS, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Contradicting URLs per gold-supporting URL", fontsize=9.5)
    ax.set_xlim(0, max(ratios) * 1.28)
    ax.set_title("Answer-independent surface contamination",
                 fontsize=10.5, pad=8, fontweight="bold")
    ax.xaxis.grid(True, color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT / "fig3_contradict_ratio.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig3_contradict_ratio.png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    print(f"Wrote {OUT/'fig3_contradict_ratio.pdf'}")

    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
