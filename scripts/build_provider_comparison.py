#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from searchapi_eval.evaluation.trace_analysis import (
    domain_rows,
    latest_by_query_id,
    load_jsonl,
    pairwise_matrix,
    per_trace_metrics,
    provider_label,
    summarize_provider,
    three_way_outcomes,
)


def main() -> None:
    args = parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    provider_rows: dict[str, list[dict[str, Any]]] = {}
    provider_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    per_query_rows: list[dict[str, Any]] = []
    all_domain_rows: list[dict[str, Any]] = []

    for trace_path in args.trace:
        rows = load_jsonl(trace_path)
        provider = args.label.pop(0) if args.label else provider_label(trace_path, rows)
        provider_rows[provider] = rows
        latest = latest_by_query_id(rows)
        provider_metrics[provider] = {}
        for query_id, trace in latest.items():
            metrics = per_trace_metrics(trace)
            provider_metrics[provider][query_id] = metrics
            per_query_rows.append(metrics)
        all_domain_rows.extend(domain_rows(provider, rows))

    summary = {
        "schema_version": "provider_comparison_v1",
        "providers": {
            provider: summarize_provider(rows)
            for provider, rows in provider_rows.items()
        },
        "pairwise": pairwise_matrix(provider_metrics),
        "three_way": three_way_outcomes(provider_metrics),
    }

    _write_json(output_dir / "provider_summary.json", summary)
    _write_jsonl(output_dir / "provider_per_query.jsonl", sorted(per_query_rows, key=lambda row: (row["query_id"], row["provider_id"])))
    _write_csv(output_dir / "provider_domains.csv", all_domain_rows)
    _write_json(output_dir / "provider_pairwise_matrices.json", summary["pairwise"])
    _write_json(output_dir / "provider_three_way_outcomes.json", summary["three_way"])
    _write_json(
        output_dir / "provider_reliability.json",
        {
            provider: {
                key: summary["providers"][provider][key]
                for key in ("trace_rows", "latest_queries", "historical_failed_rows", "latest_failed_queries", "transient_failures_recovered")
            }
            for provider in summary["providers"]
        },
    )
    print(f"Wrote provider comparison artifacts to {output_dir}")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Build deterministic provider-comparison metrics from trace JSONL files.")
    cli.add_argument("--trace", action="append", required=True, help="Trace JSONL file. Repeat for each provider.")
    cli.add_argument("--label", action="append", default=[], help="Optional provider label. Repeat in the same order as --trace.")
    cli.add_argument("--output-dir", default="results/provider_comparison")
    return cli


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
