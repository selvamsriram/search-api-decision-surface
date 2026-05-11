#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from searchapi_eval.evaluation.metrics import compute_trace_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute V1 offline metrics from trace JSONL.")
    parser.add_argument("--input", default="data/traces/phase1_v1_exa_gpt54.jsonl")
    parser.add_argument("--output", default="results/per_query_metrics.json")
    args = parser.parse_args()

    metrics = []
    with Path(args.input).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                metrics.append(compute_trace_metrics(json.loads(line)))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(metrics)} metric rows to {output}")


if __name__ == "__main__":
    main()

