#!/usr/bin/env python3
"""
Candidate replacement for Figure 1.

This version intentionally removes the internal agent-loop arrows and shows
the experiment as a sparse pipeline plus the oracle matrix. It writes separate
candidate files so the paper figure is not replaced until approved.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent

COL = {
    "ink": "#1F2933",
    "muted": "#667785",
    "line": "#AAB7C4",
    "grid": "#DDE5ED",
    "panel": "#F7F9FC",
    "dataset": "#FFF4DC",
    "dataset_edge": "#B7791F",
    "brave": "#E76F51",
    "tavily": "#2A80B9",
    "firecrawl": "#2AA876",
    "agent": "#EAF2FB",
    "agent_edge": "#2A80B9",
    "trace": "#EEF1F5",
    "judge": "#F0E5F7",
    "judge_edge": "#7B4FA3",
    "judgment": "#DDEFFB",
    "judgment_edge": "#2A80B9",
    "smart": "#238B45",
    "waste": "#D95F02",
    "miss": "#F2C94C",
    "skip": "#A8B3B5",
}


def box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    face: str,
    edge: str,
    color: str | None = None,
    lw: float = 1.15,
    size: float = 8.0,
    weight: str = "normal",
    radius: float = 0.014,
    linespacing: float = 1.12,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        facecolor=face,
        edgecolor=edge,
        linewidth=lw,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=size,
        color=color or COL["ink"],
        fontweight=weight,
        linespacing=linespacing,
    )
    return patch


def arrow(ax, start, end, *, color: str | None = None, lw: float = 1.2, ms: float = 11):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=ms,
        linewidth=lw,
        color=color or COL["muted"],
        shrinkA=7,
        shrinkB=7,
    )
    ax.add_patch(patch)
    return patch


def text(ax, x, y, s, *, size=7.2, color=None, weight="normal", ha="center"):
    ax.text(
        x,
        y,
        s,
        ha=ha,
        va="center",
        fontsize=size,
        color=color or COL["muted"],
        fontweight=weight,
        linespacing=1.1,
    )


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    fig, ax = plt.subplots(figsize=(13.2, 5.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.5,
        0.955,
        "Per-URL Oracle for Agentic Search",
        ha="center",
        va="center",
        fontsize=14.5,
        fontweight="bold",
        color=COL["ink"],
    )
    ax.text(
        0.5,
        0.912,
        "Same agent, prompt, budget, fetch backend, and judge; only the search provider changes.",
        ha="center",
        va="center",
        fontsize=8.4,
        color=COL["muted"],
    )

    # Top architecture band.
    top_y, top_h = 0.57, 0.25
    box(ax, 0.035, top_y, 0.14, top_h, "100\nSealQA-Hard\nqueries", face=COL["dataset"], edge=COL["dataset_edge"], size=10.2, weight="bold", radius=0.02)

    box(ax, 0.225, top_y, 0.15, top_h, "", face=COL["panel"], edge=COL["grid"], lw=1.0, radius=0.018)
    text(ax, 0.300, top_y + top_h - 0.034, "provider condition", size=7.2, weight="bold", color=COL["ink"])
    chip_h = 0.045
    for label, c, y in [
        ("Brave", COL["brave"], top_y + 0.150),
        ("Tavily", COL["tavily"], top_y + 0.094),
        ("Firecrawl", COL["firecrawl"], top_y + 0.038),
    ]:
        box(ax, 0.247, y, 0.106, chip_h, label, face=c, edge=c, color="white", size=8.3, weight="bold", radius=0.013)

    box(
        ax,
        0.425,
        top_y,
        0.17,
        top_h,
        "GPT-5.4 agent\n\nsearch_web\nfetch_page\nanswer / abstain",
        face=COL["agent"],
        edge=COL["agent_edge"],
        color=COL["ink"],
        size=8.0,
        weight="bold",
        radius=0.018,
        linespacing=1.2,
    )
    text(ax, 0.510, top_y - 0.034, "10-iteration budget", size=7.0)

    box(
        ax,
        0.645,
        top_y,
        0.13,
        top_h,
        "JSONL trace\n\nsearches\nfetches\nfinal answer",
        face=COL["trace"],
        edge=COL["muted"],
        size=8.0,
        radius=0.018,
    )

    box(
        ax,
        0.825,
        top_y,
        0.14,
        top_h,
        "Kimi-K2.6\nper-URL judge\n\n6,909 judgments\ncontains gold?\ncontradicts?\ngarbage?",
        face=COL["judge"],
        edge=COL["judge_edge"],
        color=COL["ink"],
        size=7.6,
        weight="bold",
        radius=0.018,
        linespacing=1.13,
    )

    arrow(ax, (0.175, top_y + top_h / 2), (0.225, top_y + top_h / 2))
    arrow(ax, (0.375, top_y + top_h / 2), (0.425, top_y + top_h / 2))
    arrow(ax, (0.595, top_y + top_h / 2), (0.645, top_y + top_h / 2))
    arrow(ax, (0.775, top_y + top_h / 2), (0.825, top_y + top_h / 2))

    text(ax, 0.400, 0.525, "ranked snippets + URLs", size=7.3)
    text(ax, 0.620, 0.525, "logged surfaces", size=7.3)
    text(ax, 0.800, 0.525, "same visible evidence", size=7.3)

    ax.plot([0.035, 0.965], [0.485, 0.485], color=COL["grid"], lw=0.9, linestyle=(0, (4, 4)))

    # Bottom oracle band.
    text(
        ax,
        0.5,
        0.437,
        "Oracle matrix: judge verdict x agent action",
        size=9.3,
        color=COL["ink"],
        weight="bold",
    )
    x0, y0 = 0.315, 0.125
    cw, ch = 0.175, 0.105
    text(ax, x0 + cw / 2, y0 + 2 * ch + 0.050, "gold-supporting URL", size=7.8, color=COL["judge_edge"], weight="bold")
    text(ax, x0 + 1.5 * cw, y0 + 2 * ch + 0.050, "not gold-supporting", size=7.8, color=COL["judge_edge"], weight="bold")
    text(ax, x0 - 0.030, y0 + 1.5 * ch, "agent\nfetched", size=7.9, color=COL["ink"], weight="bold", ha="right")
    text(ax, x0 - 0.030, y0 + 0.5 * ch, "agent\nskipped", size=7.9, color=COL["ink"], weight="bold", ha="right")

    cells = [
        (0, 1, COL["smart"], "SMART fetch", "opened useful page", "white"),
        (1, 1, COL["waste"], "FOOLISH fetch", "spent budget", "white"),
        (0, 0, COL["miss"], "MISSED URL", "evidence ignored", COL["ink"]),
        (1, 0, COL["skip"], "SMART-SKIP", "correct rejection", "white"),
    ]
    for col, row, face, title, desc, tc in cells:
        box(
            ax,
            x0 + col * cw,
            y0 + row * ch,
            cw,
            ch,
            f"{title}\n{desc}",
            face=face,
            edge="white",
            color=tc,
            size=8.4,
            weight="bold",
            radius=0.012,
        )

    box(
        ax,
        0.705,
        0.155,
        0.205,
        0.105,
        "Per-query buckets aggregate\nthese URL-level cells:\nSMART / MISSED / BLIND / NO-OP",
        face="#F8FAFC",
        edge=COL["grid"],
        color=COL["muted"],
        size=7.4,
        radius=0.014,
    )
    arrow(ax, (x0 + 2 * cw + 0.010, y0 + ch), (0.705, 0.205), color=COL["muted"], lw=1.0, ms=10)

    fig.savefig(OUT / "fig0_architecture_candidate.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig0_architecture_candidate.png", bbox_inches="tight", dpi=220)
    print(f"Wrote {OUT / 'fig0_architecture_candidate.pdf'}")
    print(f"Wrote {OUT / 'fig0_architecture_candidate.png'}")


if __name__ == "__main__":
    main()
