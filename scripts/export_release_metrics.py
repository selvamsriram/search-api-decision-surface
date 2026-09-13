#!/usr/bin/env python3
"""Export numeric/label-only study results from author-local audit records.

The public paper build does not need this script or its private inputs. No live
API calls are made. Column allowlists prevent copied evidence from being exported.
"""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/released"
PROVIDERS = {"brave", "tavily", "firecrawl"}


def read(path, delimiter=","):
    with (ROOT / path).open(newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def write(name, rows, fields):
    with (OUT / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    answers = read("results/em_vs_semantic_audit.tsv", "\t")
    assert len(answers) == 300 and {r["provider"] for r in answers} == PROVIDERS
    write("answer_audit.csv", answers, ["query_id", "provider", "em", "semantic_match"])
    actions = read("results/camera_ready/gate2/per_query_audit.csv")
    assert len(actions) == 300
    write("query_actions.csv", actions, ["provider", "query_id", "correct", "after_cell",
          "after_fetched_any", "fetch_attempts", "fetch_successes", "pooled_rows",
          "pooled_gold", "pooled_contra", "retained_rows", "retained_gold", "retained_contra"])
    cells = Counter((r["provider"], r["after_cell"]) for r in actions)
    correct = Counter((r["provider"], r["after_cell"]) for r in actions if r["correct"].lower() in {"1", "true"})
    write("decision_partition.csv", [{"provider": p, "cell": c, "queries": n,
          "correct": correct[p,c]} for (p,c),n in sorted(cells.items())],
          ["provider", "cell", "queries", "correct"])
    diagnostics = read("results/camera_ready/gate3/per_query.csv")
    fields = ["provider", "query_id", "first_result_rows", "first_valid_rows",
              "first_unknown_rows", "first_empty_result", "first_rank1_returned",
              "first_rank1_unknown", "first_support_rank", "first_support_at_1",
              "first_support_at_1_upper", "first_mrr", "first_mrr_upper",
              "first_support_any", "first_support_any_upper", "pooled_rows",
              "pooled_invalid_rows", "pooled_gold", "pooled_contra", "retained_rows",
              "retained_gold", "retained_contra", "pooled_any_contra",
              "pooled_any_contra_upper", "retained_any_contra", "first_query_matches_all_providers"]
    assert len(diagnostics) == 300
    write("query_diagnostics.csv", diagnostics, fields)
    audits = read("results/task2_judge_validation/judge_validation_results.csv")
    assert len(audits) == 180
    write("label_audit.csv", audits, ["provider_id", "query_id", "surface", "label",
          "kimi_value", "rank", "human_value", "human_agrees_with_kimi"])
    metric_fields = ["provider", "metric", "label", "unit", "questions", "estimate",
          "ci_low", "ci_high", "undefined_replicates", "missing_label_lower",
          "missing_label_upper", "sampling_and_missing_low", "sampling_and_missing_high"]
    pair_fields = ["left", "right", "metric", "unit", "questions", "difference",
          "ci_low", "ci_high", "undefined_replicates", "missing_label_lower",
          "missing_label_upper", "sampling_and_missing_low", "sampling_and_missing_high"]
    for name, fields in [("provider_metrics.csv",metric_fields), ("paired_differences.csv",pair_fields),
                         ("common_first_query_metrics.csv",metric_fields), ("common_first_query_pairs.csv",pair_fields),
                         ("first_support_rank_distribution.csv",["provider","rank","queries","queries_with_observed_first_search_support"])]:
        write(name, read("results/camera_ready/gate3/" + name), fields)
    for name, fields in [("deduplicated_ratios.csv",["provider","retained_rows","gold_rows","contra_rows","ratio","ci_low","ci_high","undefined_replicates"]),
                         ("deduplicated_pairwise.csv",["left","right","difference","ci_low","ci_high","undefined_replicates"])]:
        write(name, read("results/camera_ready/gate2/" + name), fields)
    for name, fields in [
        ("provider_metric_cis.csv",["metric","label","provider","provider_label","estimate","ci_low","ci_high","unit","digits","formatted"]),
        ("pairwise_difference_cis.csv",["metric","label","left","right","left_label","right_label","estimate","ci_low","ci_high","unit","digits","formatted"]),
        ]:
        write(name, read("results/task4_uncertainty/" + name), fields)
    # The paper reports Wilson intervals for small action cells, not the
    # historical bootstrap intervals stored with the task-4 diagnostics.
    intervals = []
    for (p, c), n in sorted(cells.items()):
        k = correct[p, c]
        phat, z = k / n, 1.96
        center = (phat + z*z/(2*n)) / (1 + z*z/n)
        half = z * math.sqrt(phat*(1-phat)/n + z*z/(4*n*n)) / (1 + z*z/n)
        intervals.append(dict(provider=p, cell=c, query_count=n, correct_count=k,
                              estimate=100*phat, ci_low=100*(center-half),
                              ci_high=100*(center+half), unit="percent", method="Wilson 95%"))
    write("decision_cell_correctness_cis.csv", intervals,
          ["provider", "cell", "query_count", "correct_count", "estimate", "ci_low", "ci_high", "unit", "method"])
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.glob("*.csv"))}
    (OUT / "hashes.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Exported {len(manifest)} numeric/label-only CSVs to {OUT}")


if __name__ == "__main__":
    main()
