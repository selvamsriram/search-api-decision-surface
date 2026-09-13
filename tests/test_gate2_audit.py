import json
from pathlib import Path

import pytest

from scripts.camera_ready_gate2_audit import LocatedRow, Provenance, ratio_interval, select_independent


def row(doc, message, gold=False):
    messages = [{"role": "system", "content": "judge"}, {"role": "user", "content": message}]
    return {"document_id": doc, "schema_version": "kimi_judge_record_v3", "query_id": "q1",
            "provider_id": "brave", "retrieval_id": doc, "url": "https://example.org/a",
            "judge_surface_class": "snippet_only", "judgment": {"contains_gold_answer": gold},
            "messages": messages, "request_snapshot": {"messages": messages}, "llm_response": {}}


def test_selection_uses_canonical_order_and_excludes_changed_copied_prompt():
    path = Path("judge.jsonl")
    independent_later = LocatedRow(path, 1, row("later", "independent later", True))
    copied_first = LocatedRow(path, 2, row("copy", "changed surface", True))
    independent_first = LocatedRow(path, 3, row("first", "independent first", False))
    observations = [independent_later, copied_first, independent_first]
    origins = {(path, 1): independent_later, (path, 2): independent_later, (path, 3): independent_first}
    selected, missing = select_independent(observations, origins, {"copy": (0, 0), "first": (1, 0), "later": (2, 0)})
    assert selected == [independent_first]
    assert missing == []
    # Changing label values cannot change which observation is retained.
    independent_first.row["judgment"]["contains_gold_answer"] = True
    assert select_independent(observations, origins, {"copy": (0, 0), "first": (1, 0), "later": (2, 0)})[0] == selected


def test_selection_reports_url_group_with_no_verified_independent_observation():
    loc = LocatedRow(Path("judge.jsonl"), 1, row("copy", "copied"))
    selected, missing = select_independent([loc], {}, {"copy": (0, 0)})
    assert selected == []
    assert missing == [("q1", "https://example.org/a")]


def test_provenance_resolves_archived_exact_import_and_rejects_bad_line(tmp_path):
    folder = tmp_path / "results/llm_judge"
    (folder / "archive").mkdir(parents=True)
    original = row("first", "same surface")
    (folder / "archive/old.jsonl").write_text(json.dumps(original) + "\n")
    imported = {**row("current", "same surface"), "cache_reused": True,
                "reuse_source": {"document_id": "first", "cache_source": "results/llm_judge/old.jsonl", "cache_source_line_num": 1}}
    path = folder / "current.jsonl"
    path.write_text(json.dumps(imported) + "\n")
    provenance = Provenance(tmp_path)
    loc = provenance.load(path)[1]
    origin = provenance.origin(loc)
    assert origin.row["document_id"] == "first"
    assert origin.path == folder / "archive/old.jsonl"
    loc.row["reuse_source"]["cache_source_line_num"] = 2
    with pytest.raises(ValueError, match="Source file/line"):
        provenance.origin(loc)


def test_ratio_bootstrap_preserves_question_clusters_and_reports_zero_denominators():
    estimate, values, undefined = ratio_interval([(2, 1), (0, 3)], [[0, 0], [0, 1], [1, 1]])
    assert estimate == 2.0
    assert values[:2] == [0.5, 2.0]
    assert values[2] != values[2]
    assert undefined == 1
