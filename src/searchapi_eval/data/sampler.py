from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .loader import public_query_record


STRATA_FIELDS = ("freshness", "search_results", "topic")
CHECK_FIELDS = ("freshness", "search_results", "topic", "effective_year")


@dataclass(frozen=True)
class SamplingConfig:
    sample_size: int = 100
    seed: int = 20260509
    question_type_tolerance_pp: float = 5.0
    effective_year_tolerance_pp: float = 5.0


def _cell_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row.get(field, "")) for field in STRATA_FIELDS)  # type: ignore[return-value]


def _largest_remainder_allocations(
    cell_counts: dict[tuple[str, str, str], int],
    sample_size: int,
) -> dict[tuple[str, str, str], int]:
    total = sum(cell_counts.values())
    exact = {key: sample_size * count / total for key, count in cell_counts.items()}
    allocations = {key: min(count, math.floor(value)) for key, value in exact.items() for count in [cell_counts[key]]}
    remaining = sample_size - sum(allocations.values())

    ranked = sorted(
        cell_counts,
        key=lambda key: (exact[key] - math.floor(exact[key]), cell_counts[key], key),
        reverse=True,
    )
    while remaining > 0:
        moved = False
        for key in ranked:
            if allocations[key] < cell_counts[key]:
                allocations[key] += 1
                remaining -= 1
                moved = True
                if remaining == 0:
                    break
        if not moved:
            raise ValueError("Cannot allocate requested sample size from available cells.")
    return allocations


def _distribution(rows: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(field)
        if isinstance(value, list):
            counts.update(str(item) for item in value)
        else:
            counts[str(value)] += 1
    return dict(sorted(counts.items()))


def _list_prevalence(rows: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        values = row.get(field) or []
        counts.update(set(str(item) for item in values))
    return dict(sorted(counts.items()))


def _percentages(counts: dict[str, int], denominator: int) -> dict[str, float]:
    if denominator == 0:
        return {key: 0.0 for key in counts}
    return {key: round(value * 100 / denominator, 2) for key, value in counts.items()}


def _max_abs_delta_pp(
    source_counts: dict[str, int],
    sample_counts: dict[str, int],
    source_denominator: int,
    sample_denominator: int,
) -> float:
    keys = set(source_counts) | set(sample_counts)
    return round(
        max(
            abs(
                source_counts.get(key, 0) * 100 / source_denominator
                - sample_counts.get(key, 0) * 100 / sample_denominator
            )
            for key in keys
        ),
        2,
    )


def select_phase1_queries(
    rows: list[dict[str, Any]],
    config: SamplingConfig = SamplingConfig(),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(rows) < config.sample_size:
        raise ValueError(f"Need at least {config.sample_size} rows, found {len(rows)}.")

    rng = random.Random(config.seed)
    cells: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cells[_cell_key(row)].append(row)

    cell_counts = {key: len(value) for key, value in cells.items()}
    allocations = _largest_remainder_allocations(cell_counts, config.sample_size)

    selected: list[dict[str, Any]] = []
    for key in sorted(cells):
        candidates = list(cells[key])
        candidates.sort(key=lambda row: (row.get("source_index", 0), row["question"]))
        rng.shuffle(candidates)
        selected.extend(candidates[: allocations[key]])

    selected.sort(key=lambda row: row["query_id"])
    diagnostics = build_sampling_diagnostics(rows, selected, allocations, config)
    return [public_query_record(row) for row in selected], diagnostics


def build_sampling_diagnostics(
    source_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    allocations: dict[tuple[str, str, str], int],
    config: SamplingConfig,
) -> dict[str, Any]:
    source_n = len(source_rows)
    sample_n = len(selected_rows)
    distributions: dict[str, Any] = {}
    for field in CHECK_FIELDS:
        source_counts = _distribution(source_rows, field)
        sample_counts = _distribution(selected_rows, field)
        distributions[field] = {
            "source_counts": source_counts,
            "sample_counts": sample_counts,
            "source_percent": _percentages(source_counts, source_n),
            "sample_percent": _percentages(sample_counts, sample_n),
            "max_abs_delta_pp": _max_abs_delta_pp(source_counts, sample_counts, source_n, sample_n),
        }

    source_qt = _list_prevalence(source_rows, "question_types")
    sample_qt = _list_prevalence(selected_rows, "question_types")
    source_qt_denominator = len(source_rows)
    sample_qt_denominator = len(selected_rows)
    distributions["question_types"] = {
        "source_counts": source_qt,
        "sample_counts": sample_qt,
        "source_percent": _percentages(source_qt, source_qt_denominator),
        "sample_percent": _percentages(sample_qt, sample_qt_denominator),
        "max_abs_delta_pp": _max_abs_delta_pp(
            source_qt,
            sample_qt,
            source_qt_denominator,
            sample_qt_denominator,
        ),
    }

    return {
        "sample_size": sample_n,
        "source_size": source_n,
        "seed": config.seed,
        "strata_fields": list(STRATA_FIELDS),
        "cell_allocations": [
            {
                "freshness": key[0],
                "search_results": key[1],
                "topic": key[2],
                "source_count": sum(1 for row in source_rows if _cell_key(row) == key),
                "sample_count": count,
            }
            for key, count in sorted(allocations.items())
            if count > 0
        ],
        "distributions": distributions,
        "tolerances": {
            "question_types_pp": config.question_type_tolerance_pp,
            "effective_year_pp": config.effective_year_tolerance_pp,
        },
    }


def write_phase1_outputs(
    selected: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    queries_path: str | Path,
    rationale_path: str | Path,
) -> None:
    queries_out = {
        "dataset": "vtllms/sealqa",
        "subset": "seal_hard",
        "schema_version": "phase1_selection_v1",
        "selection": {
            "method": "deterministic proportional stratified sample",
            "sample_size": diagnostics["sample_size"],
            "seed": diagnostics["seed"],
            "strata_fields": diagnostics["strata_fields"],
        },
        "diagnostics": diagnostics,
        "queries": selected,
    }
    queries_path = Path(queries_path)
    queries_path.parent.mkdir(parents=True, exist_ok=True)
    queries_path.write_text(json.dumps(queries_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rationale_path = Path(rationale_path)
    rationale_path.parent.mkdir(parents=True, exist_ok=True)
    rationale_path.write_text(_rationale_markdown(diagnostics), encoding="utf-8")


def _rationale_markdown(diagnostics: dict[str, Any]) -> str:
    dist = diagnostics["distributions"]
    lines = [
        "# Phase 1 100-Query Dataset Selection Rationale",
        "",
        "This file records the deterministic V1 sampling methodology for selecting 100 queries from SealQA Hard.",
        "",
        "## Source",
        "",
        "- Dataset: `vtllms/sealqa`",
        "- Subset/config: `seal_hard`",
        f"- Source rows: `{diagnostics['source_size']}`",
        f"- Selected rows: `{diagnostics['sample_size']}`",
        f"- Random seed: `{diagnostics['seed']}`",
        "",
        "## Method",
        "",
        "1. Load all SealQA Hard rows from `data/raw/seal-hard.jsonl`.",
        "2. Assign stable query IDs from a SHA-256 hash of each question.",
        "3. Build a cross-table over `freshness x search_results x topic`.",
        "4. Allocate 100 slots proportionally with largest-remainder rounding, capped by cell availability.",
        "5. Randomly sample within each cell using the fixed seed.",
        "6. Verify coverage for `question_types` and `effective_year`; diagnostics below capture drift from the source distribution.",
        "",
        "## Distribution Diagnostics",
        "",
    ]
    for field, values in dist.items():
        lines.extend(
            [
                f"### {field}",
                "",
                "| Category | Source % | Sample % | Source n | Sample n |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        keys = sorted(set(values["source_counts"]) | set(values["sample_counts"]))
        for key in keys:
            lines.append(
                f"| {key} | {values['source_percent'].get(key, 0.0):.2f} | "
                f"{values['sample_percent'].get(key, 0.0):.2f} | "
                f"{values['source_counts'].get(key, 0)} | {values['sample_counts'].get(key, 0)} |"
            )
        lines.extend(["", f"Max absolute percentage-point delta: `{values['max_abs_delta_pp']}`", ""])

    lines.extend(
        [
            "## Notes",
            "",
            "- The selected query records live in `data/queries/phase1_100.json`.",
            "- Gold answers and gold URLs are retained for offline grading and metrics; the agent runner does not expose them to the model.",
            "- The raw source file is pinned locally so this V1 selection can be reproduced before pushing the sample to Hugging Face.",
            "",
        ]
    )
    return "\n".join(lines)
