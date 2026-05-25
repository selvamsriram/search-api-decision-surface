#!/usr/bin/env python3
"""
Architecture diagram for Section 3.

This version uses two explicit lanes instead of a dense loop diagram:
  1. agent execution, ending in the trace;
  2. oracle labeling, starting from the trace.

Keeping the arrows orthogonal and one-directional makes the figure readable at
ACL two-column width and avoids misleading dangling connectors.
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
    "muted": "#5C6F7F",
    "rule": "#D8DEE6",
    "dataset": "#FFF2D9",
    "dataset_edge": "#B7791F",
    "brave": "#E76F51",
    "tavily": "#2A80B9",
    "firecrawl": "#2AA876",
    "agent": "#F6F8FB",
    "agent_edge": "#465766",
    "trace": "#ECEFF3",
    "judge": "#EFE2F5",
    "judge_edge": "#7B4FA3",
    "judgment": "#D9ECFA",
    "judgment_edge": "#2A80B9",
    "smart": "#238B45",
    "waste": "#D95F02",
    "miss": "#F2C94C",
    "skip": "#A8B3B5",
}


def rbox(
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
    fontsize: float = 8,
    weight: str = "normal",
    lw: float = 1.1,
    radius: float = 0.018,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.007,rounding_size={radius}",
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
        fontsize=fontsize,
        fontweight=weight,
        color=color or COL["ink"],
        linespacing=1.15,
    )
    return patch


def arrow(ax, start, end, *, color=None, lw=1.1, ms=11):
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=ms,
        linewidth=lw,
        color=color or COL["muted"],
        connectionstyle="arc3,rad=0",
        shrinkA=6,
        shrinkB=6,
    )
    ax.add_patch(arr)
    return arr


def label(ax, x, y, text, *, size=7.3, color=None, weight="normal", ha="center"):
    ax.text(
        x,
        y,
        text,
        ha=ha,
        va="center",
        fontsize=size,
        fontweight=weight,
        color=color or COL["muted"],
        linespacing=1.08,
    )


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    fig, ax = plt.subplots(figsize=(13.2, 5.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.5,
        0.955,
        "Per-URL Oracle for Agentic Search",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color=COL["ink"],
    )
    ax.text(
        0.5,
        0.918,
        "one frozen agent and judge; only the commercial search surface varies",
        ha="center",
        va="center",
        fontsize=8.5,
        color=COL["muted"],
    )

    # Lane labels.
    label(ax, 0.055, 0.845, "Agent execution", size=7.6, weight="bold", ha="left")

    # Agent execution lane.
    y, h = 0.66, 0.145
    dataset = rbox(
        ax,
        0.035,
        y,
        0.125,
        h,
        "100 SealQA-Hard\nqueries\n(stratified)",
        face=COL["dataset"],
        edge=COL["dataset_edge"],
        fontsize=8.8,
        weight="bold",
        radius=0.018,
    )

    # Provider stack.
    provider_x, provider_w = 0.215, 0.115
    for name, color, yy in [
        ("Brave", COL["brave"], 0.755),
        ("Tavily", COL["tavily"], 0.700),
        ("Firecrawl", COL["firecrawl"], 0.645),
    ]:
        rbox(
            ax,
            provider_x,
            yy,
            provider_w,
            0.045,
            name,
            face=color,
            edge=color,
            color="white",
            fontsize=8.5,
            weight="bold",
            radius=0.014,
        )
    label(ax, provider_x + provider_w / 2, 0.605, "3 provider conditions", size=7.1)

    surface = rbox(
        ax,
        0.380,
        y,
        0.130,
        h,
        "Search surface\nranked snippets\n+ URLs",
        face="white",
        edge=COL["judgment_edge"],
        color="#1D5C82",
        fontsize=7.9,
        weight="bold",
        radius=0.016,
    )
    agent = rbox(
        ax,
        0.565,
        y,
        0.130,
        h,
        "GPT-5.4 agent\ncalls search_web;\nmay fetch_page",
        face=COL["agent"],
        edge=COL["agent_edge"],
        fontsize=7.35,
        weight="bold",
        radius=0.016,
    )
    trace = rbox(
        ax,
        0.750,
        y,
        0.115,
        h,
        "Trace JSONL\nsearches, fetches,\nfinal answer",
        face=COL["trace"],
        edge="#657786",
        fontsize=7.5,
        radius=0.016,
    )

    arrow(ax, (0.160, 0.732), (0.215, 0.732))
    arrow(ax, (0.330, 0.732), (0.380, 0.732))
    arrow(ax, (0.510, 0.732), (0.565, 0.732))
    arrow(ax, (0.695, 0.732), (0.750, 0.732))

    label(ax, 0.605, 0.610, "same prompt, tool schema,\niteration budget, fetch backend", size=6.7)

    # Oracle labeling lane.
    judge = rbox(
        ax,
        0.625,
        0.470,
        0.115,
        0.100,
        "Kimi-K2.6\nLLM judge",
        face=COL["judge"],
        edge=COL["judge_edge"],
        color=COL["judge_edge"],
        fontsize=8.0,
        weight="bold",
        radius=0.014,
    )
    judgments = rbox(
        ax,
        0.805,
        0.465,
        0.145,
        0.110,
        "Per-URL judgments\nn = 6,909\ngold / contradict /\ngarbage labels",
        face=COL["judgment"],
        edge=COL["judgment_edge"],
        color="#1D5C82",
        fontsize=7.0,
        weight="bold",
        radius=0.014,
    )

    arrow(ax, (0.807, 0.660), (0.738, 0.570))
    arrow(ax, (0.740, 0.520), (0.805, 0.520), color=COL["judge_edge"])

    # Divider.
    ax.plot([0.035, 0.965], [0.425, 0.425], color=COL["rule"], lw=0.9, linestyle=(0, (3, 3)))

    # Oracle matrix.
    label(
        ax,
        0.5,
        0.388,
        "Oracle matrix: judge verdict × agent action",
        size=9.0,
        color=COL["ink"],
        weight="bold",
    )
    x0, y0 = 0.315, 0.082
    cw, ch = 0.160, 0.105
    label(ax, x0 + cw / 2, y0 + 2 * ch + 0.048, "Judge: gold-supporting", size=7.0, color=COL["judge_edge"], weight="bold")
    label(ax, x0 + 1.5 * cw, y0 + 2 * ch + 0.048, "Judge: not gold-supporting", size=7.0, color=COL["judge_edge"], weight="bold")
    label(ax, x0 - 0.025, y0 + 1.5 * ch, "Agent\nfetched", size=7.2, color=COL["ink"], weight="bold", ha="right")
    label(ax, x0 - 0.025, y0 + 0.5 * ch, "Agent\nskipped", size=7.2, color=COL["ink"], weight="bold", ha="right")

    cells = [
        (0, 1, COL["smart"], "SMART fetch", "opened useful page", "white"),
        (1, 1, COL["waste"], "FOOLISH fetch", "spent budget", "white"),
        (0, 0, COL["miss"], "MISSED URL", "evidence ignored", COL["ink"]),
        (1, 0, COL["skip"], "SMART-SKIP", "correct rejection", "white"),
    ]
    for col, row, face, title, desc, text_color in cells:
        rbox(
            ax,
            x0 + col * cw,
            y0 + row * ch,
            cw,
            ch,
            f"{title}\n{desc}",
            face=face,
            edge="white",
            color=text_color,
            fontsize=7.8,
            weight="bold",
            radius=0.010,
        )

    rbox(
        ax,
        0.695,
        0.119,
        0.205,
        0.095,
        "Per-query buckets aggregate\nURL-level cells:\nSMART / MISSED / BLIND / NO-OP",
        face="#F8FAFC",
        edge=COL["rule"],
        color=COL["muted"],
        fontsize=7.0,
        radius=0.012,
    )
    arrow(ax, (x0 + 2 * cw, y0 + ch), (0.695, 0.167))

    fig.savefig(OUT / "fig0_architecture.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig0_architecture.png", bbox_inches="tight", dpi=220)
    plt.close(fig)
    print(f"Wrote {OUT / 'fig0_architecture.pdf'}")
    print(f"Wrote {OUT / 'fig0_architecture.png'}")


if __name__ == "__main__":
    main()
