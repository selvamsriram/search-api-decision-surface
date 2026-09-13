"""Offline Gate 2 action/provenance audit and deduplicated ratio sensitivity.

Run from the repository root with `python -m scripts.camera_ready_gate2_audit`.
Never calls a search provider, fetch service, or judge; original labels are read
only. Selection uses canonical retrieval/result order and verified provenance,
not the value of the support or contradiction label.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.task1_support_split_numbers import (
    PROVIDERS, decision_cell, default_judge_paths, load_provider_states,
    load_semantic, repo_root, url_id, valid_judge_row,
)
from scripts.task4_bootstrap_uncertainty import ci, resample_indices
from searchapi_eval.evaluation.trace_actions import canonical_trace_paths, fetch_actions, load_canonical_traces
from searchapi_eval.providers.base import normalize_url


def copied(row: dict[str, Any]) -> bool:
    return bool(row.get("cache_reused") or row.get("duplicate_reused")) or row.get("reuse_type") in {"exact_cache", "query_url_duplicate"}


@dataclass
class LocatedRow:
    path: Path
    line: int
    row: dict[str, Any]


class Provenance:
    """Resolve explicit file/line ancestry or an earlier in-file document ID."""
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.files: dict[Path, dict[int, LocatedRow]] = {}

    def load(self, path: Path) -> dict[int, LocatedRow]:
        path = path.resolve()
        if not path.is_relative_to(self.root / "results/llm_judge"):
            raise ValueError(f"Provenance path outside judge artifacts: {path}")
        if path not in self.files:
            with path.open() as f:
                self.files[path] = {
                    i: LocatedRow(path, i, json.loads(line))
                    for i, line in enumerate(f, 1) if line.strip()
                }
        return self.files[path]

    def source(self, loc: LocatedRow) -> LocatedRow:
        row = loc.row
        source = row.get("reuse_source") or {}
        doc = source.get("document_id") or row.get("source_judge_document_id")
        filename = source.get("cache_source") or row.get("cache_source")
        line = source.get("cache_source_line_num") or row.get("cache_source_line_num")
        if not doc:
            raise ValueError("Copied row has no source document ID")
        if filename and line:
            path = self.root / filename
            if not path.exists():
                # The historical cache files were moved into archive/.
                path = self.root / "results/llm_judge/archive" / Path(filename).name
            candidate = self.load(path).get(int(line))
            if candidate is None or candidate.row.get("document_id") != doc:
                raise ValueError("Source file/line does not identify the recorded source document")
            return candidate
        candidates = [r for r in self.load(loc.path).values() if r.line < loc.line and r.row.get("document_id") == doc]
        if len(candidates) != 1:
            raise ValueError(f"Expected one earlier in-file source, found {len(candidates)}")
        return candidates[0]

    def origin(self, loc: LocatedRow, seen: tuple[tuple[Path, int], ...] = ()) -> LocatedRow:
        key = (loc.path, loc.line)
        if key in seen:
            raise ValueError("Cycle in judge provenance")
        if not valid_judge_row(loc.row):
            raise ValueError("Invalid source judgment")
        if not copied(loc.row):
            snapshot = loc.row.get("request_snapshot") or {}
            if not loc.row.get("messages") or snapshot.get("messages") != loc.row["messages"] or not isinstance(loc.row.get("llm_response"), dict):
                raise ValueError("Original call lacks a matching request/response record")
            return loc
        source = self.source(loc)
        if source.row.get("judgment") != loc.row.get("judgment"):
            raise ValueError("Copied judgment differs from its recorded source")
        if source.row.get("query_id") != loc.row.get("query_id") or url_id(source.row) != url_id(loc.row):
            raise ValueError("Source query/URL mismatch")
        return self.origin(source, seen + (key,))


def select_independent(
    observations: list[LocatedRow],
    origins: dict[tuple[Path, int], LocatedRow],
    order: dict[str, tuple[int, int]],
) -> tuple[list[LocatedRow], list[tuple[str, str]]]:
    groups: dict[tuple[str, str], list[LocatedRow]] = defaultdict(list)
    for loc in observations:
        if valid_judge_row(loc.row) and loc.row.get("judge_surface_class") == "snippet_only":
            groups[(loc.row["query_id"], url_id(loc.row))].append(loc)
    selected, missing = [], []
    for key, candidates in sorted(groups.items()):
        candidates.sort(key=lambda loc: (*order[loc.row["document_id"]], loc.line))
        for loc in candidates:
            origin = origins.get((loc.path, loc.line))
            # A direct call or a byte-equivalent imported request represents an
            # independently judged observation. Reused changed requests do not.
            if origin is not None and loc.row.get("messages") == origin.row.get("messages"):
                selected.append(loc)
                break
        else:
            missing.append(key)
    return selected, missing


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def legacy_cell(state: Any) -> str:
    if state.pre_fetch_support_urls & state.legacy_judge_fetched_urls:
        return "smart"
    if state.pre_fetch_support_urls:
        return "missed"
    return "blind" if state.legacy_judge_fetched_urls else "noop"


def ratio_interval(counts: list[tuple[int, int]], replicates: list[list[int]]) -> tuple[float, list[float], int]:
    gold = sum(g for g, _ in counts)
    estimate = sum(c for _, c in counts) / gold if gold else float("nan")
    values = []
    for indices in replicates:
        denominator = sum(counts[i][0] for i in indices)
        values.append(sum(counts[i][1] for i in indices) / denominator if denominator else float("nan"))
    return estimate, values, sum(v != v for v in values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=repo_root() / "results/camera_ready/gate2")
    parser.add_argument("--reps", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260628)
    args = parser.parse_args()
    root = repo_root()
    semantic_path = root / "results/em_vs_semantic_audit.tsv"
    semantic = load_semantic(semantic_path)
    qids = sorted(semantic["brave"])
    if any(set(semantic[p]) != set(qids) for p in PROVIDERS):
        raise ValueError("Provider question sets are not matched")
    provenance = Provenance(root)
    audit_rows, fetch_rows, provenance_rows, retained_rows, ratio_rows = [], [], [], [], []
    summaries, replicate_values = {}, {}
    failures = []
    for provider, judge_path in default_judge_paths(root).items():
        trace_path = canonical_trace_paths(root)[provider]
        traces = load_canonical_traces(trace_path, provider, set(qids))
        states, totals = load_provider_states(judge_path, semantic[provider], traces)
        observations = list(provenance.load(judge_path).values())
        order, expected = {}, {}
        for qid, trace in traces.items():
            for ri, retrieval in enumerate(trace.get("retrievals") or []):
                for di, result in enumerate((retrieval.get("search_response") or {}).get("results") or []):
                    doc = f"{qid}::{provider}::{retrieval['retrieval_id']}::r{result['rank']}"
                    order[doc] = (ri, di)
                    expected[doc] = normalize_url(result["url"])
        if len(observations) != len(order):
            raise ValueError(f"Judge observations and trace results differ for {provider}")
        if len({loc.row['document_id'] for loc in observations}) != len(observations):
            raise ValueError("Duplicate canonical document IDs")
        origins, counts = {}, Counter()
        for loc in observations:
            row = loc.row
            if expected.get(row["document_id"]) != url_id(row):
                raise ValueError(f"Judge/trace observation mismatch: {row['document_id']}")
            if not valid_judge_row(row):
                continue
            try:
                origins[(loc.path, loc.line)] = provenance.origin(loc)
            except (ValueError, OSError) as exc:
                failures.append({"provider": provider, "line": loc.line, "reason": str(exc)})
        selected, missing = select_independent(observations, origins, order)
        failures.extend({"provider": provider, "query_id": q, "url": u, "reason": "No independently judged snippet observation"} for q, u in missing)
        chosen = {(loc.path, loc.line) for loc in selected}
        # Archive roots predate surface signatures. Recover a signature only
        # through a canonical observation with exactly the same full messages.
        signatures = {
            json.dumps(loc.row.get("messages"), sort_keys=True): loc.row.get("judge_snippet_surface_signature")
            for loc in observations
        }
        by_query: dict[str, Counter] = {q: Counter() for q in qids}
        for loc in observations:
            row = loc.row
            origin = origins.get((loc.path, loc.line))
            if origin is None:
                continue
            root_row = origin.row
            sig = root_row.get("judge_snippet_surface_signature") or signatures.get(json.dumps(root_row.get("messages"), sort_keys=True))
            if not sig or not row.get("judge_snippet_surface_signature"):
                failures.append({"provider": provider, "line": loc.line, "reason": "Unverifiable snippet signature"})
            changed = bool(sig and sig != row.get("judge_snippet_surface_signature"))
            retained = (loc.path, loc.line) in chosen
            counts["copied_rows"] += copied(row)
            counts["changed_snippet_copied_rows"] += changed
            counts["changed_snippet_copied_positive"] += changed and bool(row["judgment"].get("contains_gold_answer"))
            by_query[row["query_id"]]["changed_snippet_copied_rows"] += changed
            detail = {
                "provider": provider, "query_id": row["query_id"], "document_id": row["document_id"],
                "normalized_url": url_id(row), "surface": row["judge_surface_class"],
                "canonical_line": loc.line, "copied": int(copied(row)),
                "origin_file": str(origin.path.relative_to(root)), "origin_line": origin.line,
                "origin_document_id": root_row["document_id"],
                "full_messages_match_origin": int(row.get("messages") == root_row.get("messages")),
                "changed_snippet_surface": int(changed), "retained": int(retained),
                "contains_gold_answer": int(bool(row["judgment"].get("contains_gold_answer"))),
                "contradicts_gold_answer": int(bool(row["judgment"].get("contradicts_gold_answer"))),
            }
            provenance_rows.append(detail)
            if retained:
                retained_rows.append(detail)
            if row["judge_surface_class"] == "snippet_only":
                qc = by_query[row["query_id"]]
                qc["pooled_rows"] += 1
                qc["pooled_gold"] += detail["contains_gold_answer"]
                qc["pooled_contra"] += detail["contradicts_gold_answer"]
                if retained:
                    qc["retained_rows"] += 1
                    qc["retained_gold"] += detail["contains_gold_answer"]
                    qc["retained_contra"] += detail["contradicts_gold_answer"]
        before, after = Counter(), Counter()
        for qid in qids:
            state = states[qid]
            old, new = legacy_cell(state), decision_cell(state)
            before[old] += 1; after[new] += 1
            actions = fetch_actions(traces[qid])
            fetch_rows.extend({"provider": provider, "query_id": qid, **row} for row in actions.provenance)
            audit_rows.append({
                "provider": provider, "query_id": qid, "correct": int(semantic[provider][qid]),
                "before_cell": old.upper(), "after_cell": new.upper(), "cell_changed": int(old != new),
                "before_fetched_any": int(bool(state.legacy_judge_fetched_urls)),
                "after_fetched_any": int(actions.attempts > 0),
                "fetch_attempts": actions.attempts, "fetch_successes": actions.successes,
                "before_fetched_urls": json.dumps(sorted(state.legacy_judge_fetched_urls)),
                "after_fetched_urls": json.dumps(sorted(state.fetched_urls)),
                "pre_fetch_support_urls": json.dumps(sorted(state.pre_fetch_support_urls)),
                **{k: by_query[qid][k] for k in ("pooled_rows", "pooled_gold", "pooled_contra", "retained_rows", "retained_gold", "retained_contra", "changed_snippet_copied_rows")},
            })
        reps = resample_indices(len(qids), args.reps, args.seed)
        ratio, values, undefined = ratio_interval([(by_query[q]["retained_gold"], by_query[q]["retained_contra"]) for q in qids], reps)
        lo, hi = ci(values)
        replicate_values[provider] = values
        gold = sum(by_query[q]["retained_gold"] for q in qids)
        contra = sum(by_query[q]["retained_contra"] for q in qids)
        ratio_rows.append({"provider": provider, "retained_rows": len(selected), "gold_rows": gold, "contra_rows": contra,
                           "ratio": ratio, "ci_low": lo, "ci_high": hi, "undefined_replicates": undefined})
        summaries[provider] = {**totals, **dict(counts), "before_partition": dict(before), "after_partition": dict(after),
                               "correct": sum(semantic[provider].values()), "unretained_url_groups": len(missing)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if failures:
        (args.output_dir / "provenance_failures.json").write_text(json.dumps(failures, indent=2) + "\n")
        raise RuntimeError(f"Provenance not sufficient: {len(failures)} problems; no sensitivity results written")
    pairwise = []
    for i, left in enumerate(PROVIDERS):
        for right in PROVIDERS[i + 1:]:
            values = [l - r for l, r in zip(replicate_values[left], replicate_values[right])]
            lo, hi = ci(values)
            estimates = {r["provider"]: r["ratio"] for r in ratio_rows}
            pairwise.append({"left": left, "right": right, "difference": estimates[left] - estimates[right],
                             "ci_low": lo, "ci_high": hi, "undefined_replicates": sum(v != v for v in values)})
    for name, rows in [("per_query_audit.csv", audit_rows), ("fetch_provenance.csv", fetch_rows),
                       ("judge_provenance.csv", provenance_rows), ("retained_observations.csv", retained_rows),
                       ("deduplicated_ratios.csv", ratio_rows), ("deduplicated_pairwise.csv", pairwise)]:
        write_csv(args.output_dir / name, rows)
    inputs = {semantic_path, *canonical_trace_paths(root).values(), *provenance.files.keys()}
    summary = {
        "method": "First valid independently judged snippet-only observation per provider/question/normalized URL in canonical retrieval/result order; exact imports require matching full messages to the original call.",
        "bootstrap_unit": "matched_question_id", "replicates": args.reps, "seed": args.seed,
        "interval": "percentile 95%; undefined zero-denominator replicates excluded and counted",
        "provenance_failures": [], "providers": summaries, "ratios": ratio_rows, "pairwise": pairwise,
        "input_sha256": {str(p.resolve().relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)},
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"providers": summaries, "ratios": ratio_rows, "pairwise": pairwise}, indent=2))


if __name__ == "__main__":
    main()
