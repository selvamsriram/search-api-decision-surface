import json

import pytest

from scripts.task1_support_split_numbers import decision_cell, load_provider_states
from searchapi_eval.evaluation.trace_actions import fetch_actions, load_canonical_traces


def trace(status="success"):
    return {
        "provider_id": "brave", "query_id": "q1",
        "retrievals": [{"retrieval_id": "r1", "search_response": {"results": [
            {"document_id": "s1r1", "url": "https://example.org/a?utm_source=search"},
        ]}}],
        "fetches": [{"fetch_id": "f1", "source_retrieval_id": "r1", "source_document_id": "s1r1",
                     "url": "https://example.org/a", "page_fetch": {"fetch_status": status, "final_url": "https://redirect.example/a"}}],
    }


@pytest.mark.parametrize("status", ["success", "failed"])
def test_fetch_action_survives_invalid_judgment(tmp_path, status):
    path = tmp_path / "judge.jsonl"
    path.write_text(json.dumps({"schema_version": "kimi_judge_record_v3", "provider_id": "brave",
                               "query_id": "q1", "url": "https://example.org/a", "judgment_parse_error": "invalid"}) + "\n")
    states, totals = load_provider_states(path, {"q1": False}, {"q1": trace(status)})
    state = states["q1"]
    assert decision_cell(state) == "blind"
    assert state.fetch_attempt_count == 1
    assert state.fetch_success_count == int(status == "success")
    assert state.fetched_urls == {"https://example.org/a"}
    assert not state.pre_fetch_support_urls and not state.page_extracted_gold_urls
    assert totals["judge_invalid_rows"] == 1


def test_support_url_join_counts_failed_attempt_without_claiming_page_support(tmp_path):
    path = tmp_path / "judge.jsonl"
    path.write_text(json.dumps({"schema_version": "kimi_judge_record_v3", "provider_id": "brave",
                               "query_id": "q1", "url": "https://example.org/a", "normalized_url": "https://example.org/a",
                               "judge_surface_class": "snippet_only", "judgment": {"contains_gold_answer": True}}) + "\n")
    states, _ = load_provider_states(path, {"q1": True}, {"q1": trace("failed")})
    assert decision_cell(states["q1"]) == "smart"
    assert not states["q1"].page_extracted_gold_urls


def test_wrong_retrieval_provenance_is_not_silently_credited():
    row = trace()
    row["fetches"][0]["source_retrieval_id"] = "other-retrieval"
    actions = fetch_actions(row)
    assert actions.attempts == 1
    assert actions.urls == set()
    assert not actions.provenance[0]["provenance_joined"]


def test_canonical_trace_selection_uses_last_retry_and_checks_query_set(tmp_path):
    path = tmp_path / "traces.jsonl"
    first = trace(); first["fetches"] = []
    path.write_text(json.dumps(first) + "\n" + json.dumps(trace()) + "\n")
    assert fetch_actions(load_canonical_traces(path, "brave", {"q1"})["q1"]).attempts == 1
    with pytest.raises(ValueError, match="query IDs"):
        load_canonical_traces(path, "brave", {"q1", "q2"})
