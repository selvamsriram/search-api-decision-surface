#!/usr/bin/env python3
from __future__ import annotations

import argparse

from searchapi_eval.data.loader import load_sealhard_jsonl
from searchapi_eval.data.sampler import SamplingConfig, select_phase1_queries, write_phase1_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Select the Phase 1 100-query SealQA Hard sample.")
    parser.add_argument("--input", default="data/raw/seal-hard.jsonl")
    parser.add_argument("--output", default="data/queries/phase1_100.json")
    parser.add_argument("--rationale", default="data/100-dataset-selection-rationale.md")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260509)
    args = parser.parse_args()

    rows = load_sealhard_jsonl(args.input)
    selected, diagnostics = select_phase1_queries(
        rows,
        SamplingConfig(sample_size=args.sample_size, seed=args.seed),
    )
    write_phase1_outputs(selected, diagnostics, args.output, args.rationale)
    print(f"Wrote {len(selected)} queries to {args.output}")
    print(f"Wrote selection rationale to {args.rationale}")


if __name__ == "__main__":
    main()

