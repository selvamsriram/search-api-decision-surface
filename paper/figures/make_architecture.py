#!/usr/bin/env python3
"""
Architecture diagram for §3 Methodology.

Communicates:
  (1) The agent loop: search_web -> [snippet surface] -> fetch_page -> answer.
  (2) The dual judge surface: per-URL judgment on snippet-only, plus a
      second judgment on page-visible for fetched URLs.
  (3) The 2x2 oracle confusion matrix joining model action with judge
      verdict (smart / foolish / missed / smart-skip).
  (4) Three provider conditions hold model/prompt/budget/judge constant
      while varying only the search backend.

The figure is sized for ACL two-column \\textwidth (figure*).

Outputs:
  fig0_architecture.pdf
  fig0_architecture.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.lines import Line2D

OUT = Path(__file__).resolve().parent

CLR = {
    "panel":       "#F8F9FB",
    "panel_edge":  "#566573",
    "model":       "#34495E",
    "tool_search": "#1F77B4",
    "tool_fetch":  "#9B59B6",
    "answer":      "#1E8449",
    "abstain":     "#7F8C8D",
    "judge":       "#6C3483",
    "smart":       "#27AE60",
    "foolish":     "#E67E22",
    "missed":      "#F4D03F",
    "smart_skip":  "#AAB7B8",
    "data":        "#FDEBD0",
    "data_edge":   "#B7791F",
    "brave":       "#FB7C2D",
    "tavily":      "#2E86C1",
    "firecrawl":   "#27AE60",
    "arrow_dim":   "#7F8C8D",
    "text_muted":  "#566573",
    "title":       "#1A1A1A",
    "rule":        "#BDC3C7",
}


def rbox(ax, xy, w, h, text, *, face, edge, lw=1.0, fontsize=8.5,
         fontweight="normal", text_color="#111", radius=0.05,
         multialignment="center"):
    x, y = xy
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        facecolor=face, edgecolor=edge, linewidth=lw,
    )
    ax.add_patch(p)
    ax.text(
        x + w / 2, y + h / 2, text,
        ha="center", va="center",
        fontsize=fontsize, fontweight=fontweight, color=text_color,
        multialignment=multialignment,
    )


def arrow(ax, src, dst, *, color, lw=1.0, rad=0.0, style="-|>",
          ms=12, alpha=1.0):
    a = FancyArrowPatch(
        src, dst, arrowstyle=style, color=color, lw=lw, alpha=alpha,
        connectionstyle=f"arc3,rad={rad}",
        mutation_scale=ms, shrinkA=2, shrinkB=2,
    )
    ax.add_patch(a)


def main():
    fig, ax = plt.subplots(figsize=(13.0, 5.6))
    ax.set_xlim(0, 26)
    ax.set_ylim(0, 11)
    ax.set_aspect("equal")
    ax.axis("off")

    # =====================================================================
    # LEFT BAND  ::  upstream — dataset and three provider conditions
    # =====================================================================
    rbox(ax, (0.4, 7.5), 3.6, 2.2,
         "100 SealQA-Hard\nqueries\n(stratified sample)",
         face=CLR["data"], edge=CLR["data_edge"],
         fontweight="bold", fontsize=11, radius=0.10)

    for i, (name, col) in enumerate([("Brave", CLR["brave"]),
                                     ("Tavily", CLR["tavily"]),
                                     ("Firecrawl", CLR["firecrawl"])]):
        y = 8.6 - i * 1.20
        rbox(ax, (4.7, y), 2.4, 0.90, name,
             face=col, edge=col, fontweight="bold",
             text_color="white", fontsize=11, radius=0.10)
        arrow(ax, (4.0, 8.6), (4.7, y + 0.45),
              color=CLR["arrow_dim"], lw=1.0, rad=0)

    # Bracket / condition note (placed to the left of the chip column)
    ax.annotate(
        "3 provider conditions:\nagent, prompt, budget,\nand judge held constant",
        xy=(4.65, 7.45), xytext=(3.0, 5.0),
        ha="center", va="top", fontsize=8,
        color=CLR["text_muted"], style="italic",
        arrowprops=dict(arrowstyle="-[, widthB=2.0, lengthB=0.5",
                        color=CLR["text_muted"], lw=0.8),
    )

    # =====================================================================
    # MIDDLE BAND :: the agent loop
    # =====================================================================
    panel_x0, panel_y0, panel_w, panel_h = 8.5, 4.4, 8.6, 5.8
    panel = FancyBboxPatch(
        (panel_x0, panel_y0), panel_w, panel_h,
        boxstyle="round,pad=0.04,rounding_size=0.18",
        facecolor=CLR["panel"], edgecolor=CLR["panel_edge"],
        linewidth=1.0, linestyle=(0, (4, 3)),
    )
    ax.add_patch(panel)
    ax.text(panel_x0 + panel_w / 2, panel_y0 + panel_h - 0.4,
            "Agent loop  (GPT-5.4, T=0,  up to 10 iterations)",
            ha="center", va="center", fontsize=11,
            fontweight="bold", color=CLR["model"])

    # LLM agent (center)
    agent_x, agent_y, agent_w, agent_h = 11.4, 6.55, 2.8, 1.4
    rbox(ax, (agent_x, agent_y), agent_w, agent_h,
         "LLM agent\n(decides next action)",
         face="white", edge=CLR["model"], lw=1.5,
         fontweight="bold", fontsize=10, radius=0.10)

    # search_web tool (top-left)
    sw_x, sw_y, sw_w, sw_h = 8.9, 8.5, 2.7, 1.05
    rbox(ax, (sw_x, sw_y), sw_w, sw_h,
         "search\\_web(query)\n→ snippets, URLs",
         face="white", edge=CLR["tool_search"], lw=1.3, fontsize=9.5,
         text_color=CLR["tool_search"], fontweight="bold", radius=0.10)

    # fetch_page tool (top-right)
    fp_x, fp_y, fp_w, fp_h = 14.0, 8.5, 2.8, 1.05
    rbox(ax, (fp_x, fp_y), fp_w, fp_h,
         "fetch\\_page(doc\\_id)\n→ extracted page text",
         face="white", edge=CLR["tool_fetch"], lw=1.3, fontsize=9.5,
         text_color=CLR["tool_fetch"], fontweight="bold", radius=0.10)

    # FINAL ANSWER (bottom-left), ABSTAIN (bottom-right)
    fa_x, fa_y, fa_w, fa_h = 8.9, 4.85, 2.7, 1.0
    rbox(ax, (fa_x, fa_y), fa_w, fa_h, "FINAL ANSWER",
         face="white", edge=CLR["answer"], lw=1.3, fontsize=10,
         text_color=CLR["answer"], fontweight="bold", radius=0.10)
    ab_x, ab_y, ab_w, ab_h = 14.0, 4.85, 2.8, 1.0
    rbox(ax, (ab_x, ab_y), ab_w, ab_h, "ABSTAIN",
         face="white", edge=CLR["abstain"], lw=1.3, fontsize=10,
         text_color=CLR["abstain"], fontweight="bold", radius=0.10)

    # Curved arrows agent <-> tools (call + response pairs)
    arrow(ax, (agent_x + 0.55, agent_y + agent_h),
          (sw_x + sw_w - 0.4, sw_y),
          color=CLR["tool_search"], lw=1.1, rad=0.25)
    arrow(ax, (sw_x + sw_w - 0.7, sw_y),
          (agent_x + 0.85, agent_y + agent_h),
          color=CLR["tool_search"], lw=0.9, rad=-0.25, alpha=0.55)
    arrow(ax, (agent_x + agent_w - 0.55, agent_y + agent_h),
          (fp_x + 0.4, fp_y),
          color=CLR["tool_fetch"], lw=1.1, rad=-0.25)
    arrow(ax, (fp_x + 0.7, fp_y),
          (agent_x + agent_w - 0.85, agent_y + agent_h),
          color=CLR["tool_fetch"], lw=0.9, rad=0.25, alpha=0.55)

    # Agent -> terminal actions
    arrow(ax, (agent_x + 0.55, agent_y),
          (fa_x + fa_w - 0.4, fa_y + fa_h),
          color=CLR["answer"], lw=1.3, rad=-0.2)
    arrow(ax, (agent_x + agent_w - 0.55, agent_y),
          (ab_x + 0.4, ab_y + ab_h),
          color=CLR["abstain"], lw=1.3, rad=0.2)

    # Provider results enter the loop through search_web
    arrow(ax, (7.15, 8.6), (sw_x, sw_y + sw_h / 2),
          color=CLR["arrow_dim"], lw=1.2, rad=-0.05)
    ax.text(7.85, 9.20, "search\nresults", ha="center", va="bottom",
            fontsize=8, style="italic", color=CLR["text_muted"])

    # =====================================================================
    # RIGHT BAND  ::  trace + judge oracle
    # =====================================================================
    rbox(ax, (17.7, 8.5), 3.6, 1.7,
         "Trace JSONL\n(every search, fetch,\nresponse, final answer)",
         face="#EAEDED", edge="#566573", lw=1.0, fontsize=9, radius=0.10)
    arrow(ax, (17.10, 7.25), (17.7, 9.05),
          color="#566573", lw=1.1, rad=-0.18)
    ax.text(17.55, 8.35, "log", fontsize=8.5,
            color="#566573", style="italic", ha="left")

    rbox(ax, (17.7, 5.7), 3.6, 2.4,
         "Kimi-K2.6\nLLM judge\n\nper URL, per surface\n(snippet | page)",
         face="#E8DAEF", edge=CLR["judge"], lw=1.2, fontsize=9.0,
         fontweight="bold", text_color=CLR["judge"], radius=0.10)
    arrow(ax, (19.5, 8.5), (19.5, 8.1),
          color=CLR["judge"], lw=1.2, rad=0)

    rbox(ax, (22.0, 7.0), 3.6, 2.2,
         "Per-URL judgments\n($n{=}6{,}909$)\n\ncontains gold?\ncontradicts? garbage?",
         face="#D6EAF8", edge="#2874A6", lw=1.2, fontsize=9.0,
         fontweight="bold", text_color="#1A5276", radius=0.10)
    arrow(ax, (21.3, 6.9), (22.0, 8.1),
          color="#2874A6", lw=1.2, rad=-0.2)

    # =====================================================================
    # BOTTOM PANEL  ::  oracle confusion matrix
    # =====================================================================
    ax.add_line(Line2D([0.4, 25.6], [4.05, 4.05], color=CLR["rule"],
                       lw=0.7, linestyle=(0, (3, 3))))

    ax.text(13.0, 3.62,
            "Oracle 2$\\times$2 confusion matrix per URL  "
            "(judge verdict $\\times$ agent action)",
            ha="center", va="center", fontsize=10.5, fontweight="bold",
            color=CLR["title"])

    # Matrix layout (centered around x=13.0)
    mx0, my0 = 9.5, 0.30
    cw, ch = 4.5, 1.2
    # Column headers (judge verdict)
    ax.text(mx0 + cw * 0.5, my0 + 2 * ch + 0.32,
            "Judge: gold-supporting URL", ha="center", va="center",
            fontsize=9.5, fontweight="bold", color=CLR["judge"])
    ax.text(mx0 + cw * 1.5, my0 + 2 * ch + 0.32,
            "Judge: not gold-supporting", ha="center", va="center",
            fontsize=9.5, fontweight="bold", color=CLR["judge"])
    # Row headers (agent action)
    ax.text(mx0 - 0.35, my0 + ch * 1.5,
            "Agent\nfetched", ha="right", va="center",
            fontsize=9.5, fontweight="bold", color=CLR["model"])
    ax.text(mx0 - 0.35, my0 + ch * 0.5,
            "Agent\nskipped", ha="right", va="center",
            fontsize=9.5, fontweight="bold", color=CLR["model"])
    cells = [
        (0, 1, CLR["smart"],      "SMART fetch",        "opened a useful page"),
        (1, 1, CLR["foolish"],    "FOOLISH fetch",      "wasted fetch budget"),
        (0, 0, CLR["missed"],     "MISSED URL",         "evidence ignored"),
        (1, 0, CLR["smart_skip"], "SMART-SKIP",         "correct rejection"),
    ]
    for col, row, color, title, desc in cells:
        x = mx0 + col * cw
        y = my0 + row * ch
        rbox(ax, (x, y), cw, ch,
             f"{title}\n\n{desc}",
             face=color, edge=color, lw=1.0,
             text_color="white", fontsize=10.5, fontweight="bold",
             radius=0.08)

    # Connector arrow from judgments box down to matrix (avoiding rule line)
    arrow(ax, (23.6, 7.0), (mx0 + cw + 0.4, my0 + ch),
          color="#2874A6", lw=1.0, rad=-0.35, alpha=0.7)
    ax.text(20.5, 5.0, "joined with\nagent trace",
            fontsize=8.0, color="#2874A6", style="italic", ha="center")

    # =====================================================================
    # TITLE
    # =====================================================================
    ax.text(13.0, 10.65,
            "Per-URL Oracle for Agentic Search:  "
            "three providers, one agent, one judge",
            ha="center", va="center", fontsize=12.5,
            fontweight="bold", color=CLR["title"])

    plt.tight_layout()
    fig.savefig(OUT / "fig0_architecture.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig0_architecture.png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    print(f"Wrote {OUT/'fig0_architecture.pdf'}")
    print(f"Wrote {OUT/'fig0_architecture.png'}")


if __name__ == "__main__":
    main()
