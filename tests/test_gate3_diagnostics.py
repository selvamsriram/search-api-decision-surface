import pytest

from scripts.camera_ready_gate3_diagnostics import (
    bootstrap, first_search_metrics, matches_original_evidence, metric_value, prefetch_support,
)


def judge(doc, rank, *, surface='snippet_only', gold=False, snippet=False, invalid=False):
    return {
        'document_id': doc, 'query_id': 'q', 'provider_id': 'brave', 'rank': rank,
        'schema_version': 'kimi_judge_record_v3', 'url': f'https://example.org/{rank}',
        'normalized_url': f'https://example.org/{rank}', 'judge_surface_class': surface,
        'judgment': {'contains_gold_answer': gold, 'gold_answer_in_snippets': snippet,
                     'gold_answer_in_extracted_page': gold if surface == 'page_visible' else False},
        'judgment_parse_error': 'invalid' if invalid else None,
    }


def fixture_trace(first_count=2):
    return {'query_id': 'q', 'provider_id': 'brave', 'retrievals': [
        {'retrieval_id': 'first', 'search_response': {'results': [
            {'rank': r, 'url': f'https://example.org/{r}'} for r in range(1, first_count + 1)
        ]}},
        {'retrieval_id': 'later', 'search_response': {'results': [{'rank': 1, 'url': 'https://example.org/1'}]}},
    ]}


def test_page_support_and_later_search_cannot_leak_into_first_search_ranking():
    trace = fixture_trace()
    rows = {
        'q::brave::first::r1': judge('q::brave::first::r1', 1, surface='page_visible', gold=True),
        'q::brave::first::r2': judge('q::brave::first::r2', 2, surface='page_visible', gold=True, snippet=True),
        'q::brave::later::r1': judge('q::brave::later::r1', 1, gold=True, snippet=True),
    }
    metrics, details = first_search_metrics(trace, rows)
    assert metrics['first_support_at_1'] == 0
    assert metrics['first_support_rank'] == 2
    assert metrics['first_mrr'] == .5
    assert len(details) == 2


def test_invalid_rank_one_remains_unknown_and_changes_reciprocal_rank_bounds():
    rows = {'q::brave::first::r1': judge('q::brave::first::r1', 1, invalid=True),
            'q::brave::first::r2': judge('q::brave::first::r2', 2, gold=True)}
    metrics, details = first_search_metrics(fixture_trace(), rows)
    assert metrics['first_support_at_1'] == 0
    assert metrics['first_support_at_1_upper'] == 1
    assert metrics['first_mrr'] == .5
    assert metrics['first_mrr_upper'] == 1
    assert metrics['first_unknown_rows'] == 1
    assert details[0]['pre_fetch_support'] == ''


def test_empty_first_response_is_zero_observed_support_not_a_missing_judgment():
    metrics, details = first_search_metrics(fixture_trace(0), {})
    assert metrics['first_empty_result'] == 1
    assert metrics['first_support_at_1'] == metrics['first_support_at_1_upper'] == 0
    assert metrics['first_mrr'] == metrics['first_mrr_upper'] == 0
    assert metrics['first_unknown_rows'] == 0
    assert details == []


def test_absent_required_label_is_unknown_and_trace_join_failure_is_not_silenced():
    row = judge('q::brave::first::r1', 1)
    del row['judgment']['gold_answer_in_snippets']
    assert prefetch_support(row) is None
    with pytest.raises(ValueError, match='Missing judge record'):
        first_search_metrics(fixture_trace(), {})


def test_contradiction_ratio_uses_cluster_totals_not_mean_of_question_ratios():
    rows = [{'pooled_contra': 2, 'pooled_gold': 1}, {'pooled_contra': 0, 'pooled_gold': 9}]
    assert metric_value(rows, 'pooled_cg_ratio') == .2
    assert metric_value([rows[0], rows[0]], 'pooled_cg_ratio') == 2
    identical = {p: {'q1': rows[0], 'q2': rows[1]} for p in ['brave', 'tavily', 'firecrawl']}
    _, pairs = bootstrap(identical, ['q1', 'q2'], 30, 123, ['pooled_cg_ratio'])
    assert all(r['difference'] == r['ci_low'] == r['ci_high'] == 0 for r in pairs)


def test_same_url_does_not_establish_same_original_evidence():
    a = {'messages': ['source'], 'judge_surface_class': 'snippet_only', 'judge_snippet_surface_signature': 'text-a'}
    b = {**a, 'messages': ['different rank, same text']}
    assert matches_original_evidence(a, b)
    b['judge_snippet_surface_signature'] = 'text-b'
    assert not matches_original_evidence(a, b)
    b = {**a, 'messages': ['page'], 'judge_surface_class': 'page_visible', 'judge_page_fetch_signature': 'page-b'}
    assert not matches_original_evidence(a, b)
