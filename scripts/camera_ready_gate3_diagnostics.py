"""Offline Gate 3 diagnostics; never writes paper sources or calls a model.

First-search ranking uses the original pre-fetch-support predicate. Contradiction
diagnostics use valid snippet-only observations, with the Gate 2 independent-URL
selection as a separate sensitivity. Invalid judgments remain explicitly unknown.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from scripts.camera_ready_gate2_audit import Provenance, copied, select_independent, write_csv
from scripts.task1_support_split_numbers import PROVIDERS, default_judge_paths, load_semantic, repo_root, url_id, valid_judge_row
from scripts.task4_bootstrap_uncertainty import ci, resample_indices
from searchapi_eval.evaluation.trace_actions import canonical_trace_paths, load_canonical_traces
from searchapi_eval.providers.base import normalize_url


def prefetch_support(row: dict[str, Any] | None) -> bool | None:
    """Never credit page-only support; an invalid judgment is unknown."""
    if row is None or not valid_judge_row(row):
        return None
    judgment = row['judgment']
    surface = row.get('judge_surface_class')
    if surface not in {'snippet_only', 'page_visible'}:
        raise ValueError('Unknown judge surface')
    required = ['gold_answer_in_snippets'] + (['contains_gold_answer'] if surface == 'snippet_only' else [])
    if any(not isinstance(judgment.get(key), bool) for key in required):
        return None
    return judgment['gold_answer_in_snippets'] or (surface == 'snippet_only' and judgment['contains_gold_answer'])


def document_id(trace: dict, retrieval: dict, result: dict) -> str:
    return f"{trace['query_id']}::{trace['provider_id']}::{retrieval['retrieval_id']}::r{result['rank']}"


def first_search_metrics(trace: dict, judge_index: dict[str, dict]) -> tuple[dict, list[dict]]:
    retrievals = trace.get('retrievals') or []
    if not retrievals:
        raise ValueError('Cannot measure a first search in a trajectory with no search')
    retrieval = retrievals[0]
    results = (retrieval.get('search_response') or {}).get('results') or []
    ranks = [int(result['rank']) for result in results]
    if ranks != list(range(1, len(results) + 1)):
        raise ValueError('First-search result ranks are not contiguous and unique')
    supported, unknown, details = [], [], []
    for result in results:
        doc = document_id(trace, retrieval, result)
        row = judge_index.get(doc)
        if row is None:
            raise ValueError(f'Missing judge record for trace result: {doc}')
        if url_id(row) != normalize_url(result['url']):
            raise ValueError(f'Trace/judge URL mismatch: {doc}')
        status = prefetch_support(row)
        rank = int(result['rank'])
        if status is None:
            unknown.append(rank)
        elif status:
            supported.append(rank)
        details.append({
            'provider': trace['provider_id'], 'query_id': trace['query_id'],
            'retrieval_id': retrieval['retrieval_id'], 'document_id': doc,
            'rank': rank, 'surface': row['judge_surface_class'],
            'valid_support_label': int(status is not None),
            'pre_fetch_support': '' if status is None else int(status),
        })
    first = min(supported) if supported else None
    rr = 1 / first if first else 0.0
    rr_upper = max(rr, 1 / min(unknown) if unknown else 0.0)
    return {
        'first_retrieval_id': retrieval['retrieval_id'],
        'first_result_rows': len(results), 'first_valid_rows': len(results) - len(unknown),
        'first_unknown_rows': len(unknown), 'first_empty_result': int(not results),
        'first_rank1_returned': int(1 in ranks), 'first_rank1_unknown': int(1 in unknown),
        'first_support_rank': first, 'first_support_ranks': supported, 'first_unknown_ranks': unknown,
        'first_support_at_1': int(1 in supported), 'first_support_at_1_upper': int(1 in supported or 1 in unknown),
        'first_mrr': rr, 'first_mrr_upper': rr_upper,
        'first_support_any': int(bool(supported)), 'first_support_any_upper': int(bool(supported or unknown)),
    }, details


METRICS = {
    'first_support_at_1': ('First-search observed Support@1', 'percent', 'first_support_at_1', None),
    'first_mrr': ('First-search observed mean reciprocal rank', 'MRR', 'first_mrr', None),
    'first_support_any': ('First-search observed support anywhere', 'percent', 'first_support_any', None),
    'contradiction_query_pct': ('Questions with any judged snippet contradiction', 'percent', 'pooled_any_contra', None),
    'contradiction_row_pct': ('Contradictory snippet-only observations', 'percent', 'pooled_contra', 'pooled_rows'),
    'pooled_cg_ratio': ('Pooled contradiction-to-gold ratio', 'ratio', 'pooled_contra', 'pooled_gold'),
    'deduplicated_contradiction_query_pct': ('Questions with retained contradiction', 'percent', 'retained_any_contra', None),
    'deduplicated_contradiction_row_pct': ('Contradictory retained observations', 'percent', 'retained_contra', 'retained_rows'),
    'deduplicated_cg_ratio': ('Deduplicated contradiction-to-gold ratio', 'ratio', 'retained_contra', 'retained_gold'),
}
UPPER_FIELDS = {
    'first_support_at_1': 'first_support_at_1_upper',
    'first_mrr': 'first_mrr_upper',
    'first_support_any': 'first_support_any_upper',
    'contradiction_query_pct': 'pooled_any_contra_upper',
}


def metric_value(rows: list[dict], key: str, upper: bool = False) -> float:
    _, unit, numerator, denominator = METRICS[key]
    if upper:
        numerator = UPPER_FIELDS[key]
    num = sum(r[numerator] for r in rows)
    den = sum(r[denominator] for r in rows) if denominator else len(rows)
    if not den:
        return float('nan')
    return (100 if unit == 'percent' else 1) * num / den


def bootstrap(data: dict, qids: list[str], reps: int, seed: int, keys: list[str] | None = None):
    """Resample matched whole questions, then recompute every ratio."""
    keys = keys or list(METRICS)
    indices = resample_indices(len(qids), reps, seed)
    provider_rows, pairwise_rows, values, upper_values = [], [], {}, {}
    for provider in PROVIDERS:
        rows = [data[provider][q] for q in qids]
        # Reuse the same sampled question list for every metric and provider.
        samples = [[rows[i] for i in draw] for draw in indices]
        for key in keys:
            array = [metric_value(sample, key) for sample in samples]
            values[(provider, key)] = array
            lo, hi = ci(array)
            entry = {'provider': provider, 'metric': key, 'label': METRICS[key][0],
                     'unit': METRICS[key][1], 'questions': len(rows), 'estimate': metric_value(rows, key),
                     'ci_low': lo, 'ci_high': hi, 'undefined_replicates': sum(not math.isfinite(v) for v in array),
                     'missing_label_lower': '', 'missing_label_upper': '',
                     'sampling_and_missing_low': '', 'sampling_and_missing_high': ''}
            if key in UPPER_FIELDS:
                upper = [metric_value(sample, key, upper=True) for sample in samples]
                upper_values[(provider, key)] = upper
                entry.update(missing_label_lower=entry['estimate'], missing_label_upper=metric_value(rows, key, upper=True),
                             sampling_and_missing_low=lo, sampling_and_missing_high=ci(upper)[1])
            provider_rows.append(entry)
    for i, left in enumerate(PROVIDERS):
        for right in PROVIDERS[i + 1:]:
            for key in keys:
                differences = [a - b for a, b in zip(values[(left, key)], values[(right, key)])]
                lo, hi = ci(differences)
                left_rows = [data[left][q] for q in qids]; right_rows = [data[right][q] for q in qids]
                entry = {'left': left, 'right': right, 'metric': key, 'unit': METRICS[key][1],
                         'questions': len(qids), 'difference': metric_value(left_rows, key) - metric_value(right_rows, key),
                         'ci_low': lo, 'ci_high': hi,
                         'undefined_replicates': sum(not math.isfinite(v) for v in differences),
                         'missing_label_lower': '', 'missing_label_upper': '',
                         'sampling_and_missing_low': '', 'sampling_and_missing_high': ''}
                if key in UPPER_FIELDS:
                    low = [a - b for a, b in zip(values[(left, key)], upper_values[(right, key)])]
                    high = [a - b for a, b in zip(upper_values[(left, key)], values[(right, key)])]
                    entry.update(
                        missing_label_lower=metric_value(left_rows, key) - metric_value(right_rows, key, upper=True),
                        missing_label_upper=metric_value(left_rows, key, upper=True) - metric_value(right_rows, key),
                        sampling_and_missing_low=ci(low)[0], sampling_and_missing_high=ci(high)[1])
                pairwise_rows.append(entry)
    return provider_rows, pairwise_rows


def matches_original_evidence(row: dict, source: dict) -> bool:
    if row.get('messages') == source.get('messages'):
        return True
    surface = row.get('judge_surface_class')
    same_snippet = bool(row.get('judge_snippet_surface_signature')) and row.get('judge_snippet_surface_signature') == source.get('judge_snippet_surface_signature')
    if surface != source.get('judge_surface_class') or not same_snippet:
        return False
    return surface == 'snippet_only' or (bool(row.get('judge_page_fetch_signature')) and row.get('judge_page_fetch_signature') == source.get('judge_page_fetch_signature'))


def diagnostics_table(metrics: list[dict]) -> str:
    """Proposal artifact only; caller must never write this into paper/."""
    indexed = {(r['provider'], r['metric']): r for r in metrics}
    lines = [
        '% Gate 3 proposed table. Manuscript integration requires author approval.',
        r'\begin{table*}[!t]', r'\centering', r'\small',
        r'\setlength{\tabcolsep}{4pt}',
        r'\begin{tabularx}{\textwidth}{@{}L{0.38\textwidth}YYY@{}}', r'\toprule',
        r'\textbf{Metric} & \textbf{Brave} & \textbf{Tavily} & \textbf{Firecrawl} \\', r'\midrule',
        r'\multicolumn{4}{@{}l}{\textit{First search call}} \\',
    ]
    table_rows = [
        ('first_support_any', r'Observed support at any rank (\%)', 0),
        ('first_support_at_1', r'Observed Support@1 (\%)', 0),
        ('first_mrr', 'Observed mean reciprocal rank', 3),
        ('contradiction_query_pct', r'Questions with a judged contradiction (\%)', 0),
        ('contradiction_row_pct', r'Contradictory observations (\%)', 2),
        ('pooled_cg_ratio', r'Contradiction-to-gold ratio $r_{c:g}$', 2),
    ]
    for key, label, digits in table_rows:
        if key == 'contradiction_query_pct':
            lines += [r'\midrule', r'\multicolumn{4}{@{}l}{\textit{Full trajectory: valid snippet-only observations}} \\']
        values = []
        for provider in PROVIDERS:
            r = indexed[(provider, key)]
            values.append(f"{r['estimate']:.{digits}f} [{r['ci_low']:.{digits}f}, {r['ci_high']:.{digits}f}]")
        lines.append(label + ' & ' + ' & '.join(values) + r' \\')
    lines += [r'\bottomrule', r'\end{tabularx}',
              r'\caption{First-search ranking and trajectory-level contradiction diagnostics, with 95\% question-bootstrap intervals. Query percentages use all \NQueries{} questions. Ranking uses the first search call only; contradiction uses valid snippet-only observations across the trajectory. Judgment coverage, missing-label bounds, and first-support-rank summaries are reported in Appendix~\ref{app:query-diagnostics}.}',
              r'\label{tab:query-diagnostics}', r'\end{table*}']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=repo_root() / 'results/camera_ready/gate3')
    parser.add_argument('--reps', type=int, default=10_000)
    parser.add_argument('--seed', type=int, default=20260628)
    args = parser.parse_args()
    if args.reps < 1:
        raise ValueError('Bootstrap repetitions must be positive')
    root = repo_root(); semantic_path = root / 'results/em_vs_semantic_audit.tsv'
    gate2_path = root / 'results/camera_ready/gate2/summary.json'
    gate2 = json.loads(gate2_path.read_text())
    for name, expected in gate2['input_sha256'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Frozen input differs from Gate 2: {name}')
    semantic = load_semantic(semantic_path); qids = sorted(semantic['brave'])
    if any(set(semantic[p]) != set(qids) for p in PROVIDERS):
        raise ValueError('Provider question sets do not match')
    provenance = Provenance(root)
    data, first_details, first_queries, diagnostics, rank_rows = {}, [], {}, {}, []
    for provider, path in default_judge_paths(root).items():
        traces = load_canonical_traces(canonical_trace_paths(root)[provider], provider, set(qids))
        observations = list(provenance.load(path).values())
        index = {loc.row['document_id']: loc.row for loc in observations}
        if len(index) != len(observations):
            raise ValueError('Duplicate judge observation IDs')
        order = {}
        for q, trace in traces.items():
            for ri, retrieval in enumerate(trace.get('retrievals') or []):
                for di, result in enumerate((retrieval.get('search_response') or {}).get('results') or []):
                    doc = document_id(trace, retrieval, result)
                    if doc not in index or url_id(index[doc]) != normalize_url(result['url']):
                        raise ValueError(f'Trace/judge result mismatch: {doc}')
                    order[doc] = (ri, di)
        if set(order) != set(index):
            raise ValueError('Canonical result set differs from judge records')
        origins = {(loc.path, loc.line): provenance.origin(loc) for loc in observations if valid_judge_row(loc.row)}
        selected, missing = select_independent(observations, origins, order)
        if missing:
            raise ValueError(f'Missing independently judged URL groups: {missing}')
        selected_ids = {loc.row['document_id'] for loc in selected}
        origin_by_doc = {loc.row['document_id']: origins[(loc.path, loc.line)].row for loc in observations if valid_judge_row(loc.row)}
        data[provider] = {}; first_queries[provider] = {}
        for q in qids:
            trace = traces[q]
            first, details = first_search_metrics(trace, index)
            retrieval = trace['retrievals'][0]
            first_queries[provider][q] = retrieval.get('search_query') or (retrieval.get('search_response') or {}).get('query') or ''
            if not first_queries[provider][q]:
                raise ValueError('First-search query string is missing')
            for detail in details:
                row = index[detail['document_id']]
                if valid_judge_row(row):
                    origin = origin_by_doc[detail['document_id']]
                    if not matches_original_evidence(row, origin):
                        raise ValueError('First-search record inherits a judgment for different evidence')
                    detail.update(copied=int(copied(row)), messages_match_origin=int(row['messages'] == origin['messages']), evidence_matches_origin=1)
                else:
                    detail.update(copied=0, messages_match_origin='', evidence_matches_origin='')
            first_details.extend(details)
            data[provider][q] = {
                'provider': provider, 'query_id': q, **first,
                'pooled_rows': 0, 'pooled_invalid_rows': 0, 'pooled_gold': 0, 'pooled_contra': 0,
                'retained_rows': 0, 'retained_gold': 0, 'retained_contra': 0,
            }
        for loc in observations:
            row = loc.row
            if row.get('judge_surface_class') != 'snippet_only':
                continue
            query = data[provider][row['query_id']]
            if not valid_judge_row(row):
                query['pooled_invalid_rows'] += 1
                continue
            judgment = row['judgment']
            if any(not isinstance(judgment.get(k), bool) for k in ['contains_gold_answer', 'contradicts_gold_answer']):
                raise ValueError('Valid snippet observation lacks a required boolean label')
            query['pooled_rows'] += 1
            query['pooled_gold'] += int(judgment['contains_gold_answer'])
            query['pooled_contra'] += int(judgment['contradicts_gold_answer'])
            if row['document_id'] in selected_ids:
                query['retained_rows'] += 1
                query['retained_gold'] += int(judgment['contains_gold_answer'])
                query['retained_contra'] += int(judgment['contradicts_gold_answer'])
        for query in data[provider].values():
            query['pooled_any_contra'] = int(query['pooled_contra'] > 0)
            query['pooled_any_contra_upper'] = int(query['pooled_contra'] > 0 or query['pooled_invalid_rows'] > 0)
            query['retained_any_contra'] = int(query['retained_contra'] > 0)
        records = list(data[provider].values())
        support_ranks = [r['first_support_rank'] for r in records if r['first_support_rank'] is not None]
        diag = {key: sum(r[key] for r in records) for key in [
            'first_result_rows', 'first_valid_rows', 'first_unknown_rows', 'first_empty_result',
            'first_rank1_returned', 'first_rank1_unknown', 'first_support_at_1', 'first_support_any',
            'pooled_rows', 'pooled_invalid_rows', 'pooled_gold', 'pooled_contra', 'pooled_any_contra',
            'retained_rows', 'retained_gold', 'retained_contra', 'retained_any_contra']}
        diag.update(
            first_queries_with_unknown_labels=sum(r['first_unknown_rows'] > 0 for r in records),
            first_queries_with_known_mrr=sum(r['first_mrr'] == r['first_mrr_upper'] for r in records),
            first_support_rank_conditional_median=median(support_ranks) if support_ranks else None,
            first_support_rank_distribution=dict(sorted(Counter(support_ranks).items())),
            first_copied_records=sum(r['copied'] for r in first_details if r['provider'] == provider),
            first_changed_evidence_copies=0,
            questions_without_valid_snippet_only_rows=sum(not r['pooled_rows'] for r in records),
        )
        diagnostics[provider] = diag
        for rank in range(1, 11):
            rank_rows.append({'provider': provider, 'rank': rank, 'queries': support_ranks.count(rank),
                             'queries_with_observed_first_search_support': len(support_ranks)})
    metrics, pairs = bootstrap(data, qids, args.reps, args.seed)
    exact_matches = {f'{left}:{right}': sum(first_queries[left][q] == first_queries[right][q] for q in qids)
                     for i, left in enumerate(PROVIDERS) for right in PROVIDERS[i + 1:]}
    common = [q for q in qids if len({first_queries[p][q] for p in PROVIDERS}) == 1]
    shared_metrics, shared_pairs = bootstrap(data, common, args.reps, args.seed, ['first_support_at_1', 'first_mrr', 'first_support_any'])
    # Require reproduction of both existing ratio analyses, including intervals.
    baseline_path = root / 'results/task4_uncertainty/provider_metric_cis.csv'
    with baseline_path.open() as stream:
        pooled_baseline = {r['provider']: r for r in csv.DictReader(stream) if r['metric'] == 'surface_cg'}
    dedup_baseline = {r['provider']: r for r in gate2['ratios']}
    if args.reps == gate2['replicates'] and args.seed == gate2['seed']:
        for row in metrics:
            if row['metric'] not in {'pooled_cg_ratio', 'deduplicated_cg_ratio'}:
                continue
            base = (pooled_baseline if row['metric'] == 'pooled_cg_ratio' else dedup_baseline)[row['provider']]
            for key in ['estimate', 'ci_low', 'ci_high']:
                base_key = 'ratio' if key == 'estimate' and row['metric'] == 'deduplicated_cg_ratio' else key
                if not math.isclose(row[key], float(base[base_key]), rel_tol=1e-10, abs_tol=1e-12):
                    raise ValueError(f'Existing ratio not reproduced: {row["provider"]}, {row["metric"]}, {key}')
    per_query = []
    for provider in PROVIDERS:
        for q in qids:
            row = dict(data[provider][q])
            row['first_query_matches_all_providers'] = int(q in common)
            for key in ['first_support_ranks', 'first_unknown_ranks']:
                row[key] = json.dumps(row[key])
            per_query.append(row)
    inputs = {semantic_path, gate2_path, baseline_path, *canonical_trace_paths(root).values(), *provenance.files.keys()}
    summary = {
        'status': 'Analysis only; manuscript integration requires author approval.',
        'analysis_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'questions_per_provider': len(qids), 'replicates': args.reps, 'seed': args.seed,
        'bootstrap_unit': 'Matched benchmark question ID; all rows from a sampled question travel together.',
        'first_search_method': 'First retrieval in the last canonical trace; use gold_answer_in_snippets OR (snippet_only AND contains_gold_answer). Page-only support and later searches cannot contribute.',
        'missing_label_method': 'Report observed support and reciprocal rank (zero if no known support), plus lower/upper completions of invalid labels. These bounds concern missing labels, not semantic judge errors.',
        'contradiction_method': 'Valid snippet-only observations across the full trajectory; query exposure is any contradiction within this observed subset, not all pre-fetch results.',
        'deduplication_method': gate2['method'],
        'providers': diagnostics, 'metrics': metrics, 'paired_differences': pairs,
        'first_query_exact_matches': exact_matches, 'first_query_common_to_all_count': len(common),
        'common_first_query_metrics': shared_metrics, 'common_first_query_paired_differences': shared_pairs,
        'existing_pooled_and_deduplicated_ratios_reproduced': args.reps == gate2['replicates'] and args.seed == gate2['seed'],
        'input_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in [('per_query.csv', per_query), ('first_search_observations.csv', first_details),
                       ('provider_metrics.csv', metrics), ('paired_differences.csv', pairs),
                       ('first_support_rank_distribution.csv', rank_rows),
                       ('common_first_query_metrics.csv', shared_metrics), ('common_first_query_pairs.csv', shared_pairs)]:
        write_csv(args.output_dir / name, rows)
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n')
    (args.output_dir / 'diagnostics_table.tex').write_text(diagnostics_table(metrics))
    print(json.dumps({'providers': diagnostics, 'metrics': metrics, 'paired_differences': pairs,
                      'common_first_query_count': len(common)}, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
