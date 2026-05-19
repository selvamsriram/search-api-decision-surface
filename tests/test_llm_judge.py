import json
from argparse import Namespace

from scripts.run_llm_judge import (
    _build_query_url_reuse_cache,
    _build_kimi_client,
    _cached_output_record,
    _load_judge_cache,
    _matching_cache_record,
    _matching_query_url_reuse_record,
    _query_url_duplicate_output_record,
    _query_url_reuse_key,
    _record_key,
    _records_for_trace,
)
from searchapi_eval.evaluation.llm_judge import (
    deterministic_garbage_precheck,
    parse_json_object,
    render_document_judge_prompt,
)


def _trace():
    return {
        "query_id": "q1",
        "provider_id": "fake",
        "question": "Which country won?",
        "gold_answer": "Sweden",
        "final_answer": "Sweden",
        "answered": True,
        "failed": False,
        "total_search_calls": 1,
        "total_prompt_tokens": 100,
        "total_completion_tokens": 5,
        "retrievals": [
            {
                "retrieval_id": "ret1",
                "search_query": "winner country",
                "search_response": {
                    "results": [
                        {
                            "rank": 1,
                            "title": "Source",
                            "url": "https://example.com",
                            "domain": "example.com",
                            "snippet": "Sweden won.",
                            "provider_metadata": {
                                "extra_snippets": ["The final was decided by Sweden."],
                            },
                            "page_fetch": {
                                "fetch_status": "success",
                                "http_status": 200,
                                "content_type": "text/html",
                                "extractor": "trafilatura",
                                "artifact_path": "data/page_cache/example.json.gz",
                                "final_url": "https://example.com/final",
                                "extracted_text_chars": 11,
                                "extracted_text_tokens_estimate": 3,
                                "extracted_text": "Sweden won.",
                            },
                        }
                    ]
                },
            }
        ],
    }


def test_document_judge_prompt_contains_schema_and_document_fields():
    trace = _trace()
    retrieval = trace["retrievals"][0]
    result = retrieval["search_response"]["results"][0]

    messages = render_document_judge_prompt(trace, retrieval, result)
    user_content = messages[-1]["content"]

    assert "Required JSON schema" in user_content
    assert "<gold_answer>" in user_content
    assert "<url>https://example.com</url>" in user_content
    assert "<extra_snippet>The final was decided by Sweden.</extra_snippet>" in user_content
    assert "<fetch_status>success</fetch_status>" in user_content
    assert "<final_url>https://example.com/final</final_url>" in user_content
    assert "Sweden won." in user_content
    assert "gold_answer_in_snippets" in user_content
    assert "gold_answer_in_extracted_page" in user_content
    assert "gold_snippet_span" in user_content
    assert "gold_extracted_page_span" in user_content
    assert "supports_gold_answer" not in user_content
    assert "evidence_quality" not in user_content
    assert "<query_id>" not in user_content
    assert "is_garbage" in user_content


def test_document_judge_prompt_uses_full_extracted_text_by_default():
    trace = _trace()
    retrieval = trace["retrievals"][0]
    result = retrieval["search_response"]["results"][0]
    result["page_fetch"]["extracted_text"] = "a" * 13_000

    messages = render_document_judge_prompt(trace, retrieval, result)
    user_content = messages[-1]["content"]

    assert 'truncated_for_judge="false"' in user_content
    assert "a" * 13_000 in user_content


def test_document_judge_prompt_can_cap_extracted_text_when_requested():
    trace = _trace()
    retrieval = trace["retrievals"][0]
    result = retrieval["search_response"]["results"][0]
    result["page_fetch"]["extracted_text"] = "abcdef"

    messages = render_document_judge_prompt(trace, retrieval, result, max_extracted_chars=3)
    user_content = messages[-1]["content"]

    assert 'truncated_for_judge="true"' in user_content
    assert "abc" in user_content
    assert "abcdef" not in user_content


def test_deterministic_garbage_precheck_marks_unsupported_fetch_without_prompt_metadata():
    result = {
        "snippet": "Potentially useful search snippet.",
        "page_fetch": {
            "fetch_status": "empty",
            "content_type": "application/pdf",
            "extractor": "pdf_unsupported_v1",
            "extracted_text_chars": 0,
        },
    }

    precheck = deterministic_garbage_precheck(result)

    assert precheck["is_garbage"] is True
    assert precheck["category"] == "unsupported_content"


def test_judge_records_attach_matching_fetch_tool_page_to_visible_document():
    trace = {
        "query_id": "q1",
        "provider_id": "fake",
        "question": "Which country won?",
        "gold_answer": "Sweden",
        "final_answer": "Finland",
        "retrievals": [
            {
                "retrieval_id": "ret1",
                "search_query": "winner country",
                "search_response": {
                    "results": [
                        {
                            "document_id": "s1r1",
                            "rank": 1,
                            "title": "Source",
                            "url": "https://example.com",
                            "domain": "example.com",
                            "snippet": "Search snippet only.",
                            "provider_metadata": {},
                        }
                    ]
                },
            }
        ],
        "fetches": [
            {
                "fetch_id": "fetch1",
                "iteration_num": 2,
                "requested_document_id": "s1r1",
                "source_document_id": "s1r1",
                "source_retrieval_id": "ret1",
                "source_rank": 1,
                "url": "https://example.com",
                "page_fetch": {
                    "fetch_backend": "jina",
                    "fetch_status": "success",
                    "http_status": 200,
                    "content_type": "text/markdown",
                    "extractor": "jina_reader_markdown",
                    "artifact_path": "data/page_cache/example.json.gz",
                    "final_url": "https://example.com",
                    "reader_url": "https://r.jina.ai/http://r.jina.ai/http://example.com",
                    "extracted_text_chars": 18,
                    "extracted_text_tokens_estimate": 4,
                    "extracted_text": "The winner was Sweden.",
                },
            }
        ],
    }
    args = Namespace(max_docs_per_query=0, max_docs_per_search=0, max_document_chars=0)

    records = _records_for_trace(trace, args)

    assert len(records) == 1
    record = records[0]
    assert record["schema_version"] == "kimi_judge_record_v3"
    assert record["page_fetch_source"] == "fetch_tool"
    assert record["model_fetched_document"] is True
    assert record["fetch_tool_requested_document_id"] == "s1r1"
    assert record["page_fetch"]["fetch_backend"] == "jina"
    assert record["page_fetch"]["extracted_text_chars"] == 18
    assert "<extractor>jina_reader_markdown</extractor>" in record["messages"][-1]["content"]
    assert "The winner was Sweden." in record["messages"][-1]["content"]


def test_judge_cache_reuses_only_valid_exact_document_matches(tmp_path):
    valid = {
        "schema_version": "kimi_judge_record_v3",
        "provider_id": "fake",
        "query_id": "q1",
        "retrieval_id": "ret1",
        "rank": 1,
        "url": "https://example.com",
        "document_id": "q1::fake::ret1::r1",
        "judgment": {"contains_gold_answer": True},
        "llm_response": {"usage": {"total_tokens": 123}},
        "messages": [{"role": "user", "content": "same prompt"}],
    }
    invalid = {
        **valid,
        "rank": 2,
        "document_id": "q1::fake::ret1::r2",
        "judgment_parse_error": "bad json",
    }
    cache_path = tmp_path / "cache.jsonl"
    cache_path.write_text(
        "\n".join(
            [
                json.dumps(valid),
                json.dumps(invalid),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cache = _load_judge_cache([str(cache_path)])

    assert len(cache) == 1
    assert _record_key(valid) in cache
    target = {**valid, "document_id": "target-doc-id", "messages": [{"role": "user", "content": "same prompt"}]}
    cache_match = _matching_cache_record(cache, target)
    assert cache_match is not None
    reused = _cached_output_record(cache_match, target)
    assert reused["cache_reused"] is True
    assert reused["cache_source"] == str(cache_path)
    assert reused["cache_source_line_num"] == 1
    assert reused["target_document_id"] == "target-doc-id"
    assert reused["judgment"] == {"contains_gold_answer": True}
    mismatched_prompt = {**target, "messages": [{"role": "user", "content": "different prompt"}]}
    assert _matching_cache_record(cache, mismatched_prompt) is None


def test_query_url_duplicate_reuse_ignores_provider_retrieval_rank_for_same_query_url():
    trace = {
        "query_id": "q1",
        "provider_id": "fake",
        "question": "Which country won?",
        "gold_answer": "Sweden",
        "final_answer": "Sweden",
        "retrievals": [
            {
                "retrieval_id": "ret1",
                "search_query": "first search",
                "search_response": {
                    "results": [
                        {
                            "document_id": "s1r1",
                            "rank": 1,
                            "title": "Source",
                            "url": "https://example.com/source?utm_source=x",
                            "domain": "example.com",
                            "snippet": "First snippet.",
                            "provider_metadata": {},
                        }
                    ]
                },
            },
            {
                "retrieval_id": "ret2",
                "search_query": "second search",
                "search_response": {
                    "results": [
                        {
                            "document_id": "s2r3",
                            "rank": 3,
                            "title": "Source again",
                            "url": "https://example.com/source",
                            "domain": "example.com",
                            "snippet": "Different snippet from a later search.",
                            "provider_metadata": {},
                        }
                    ]
                },
            },
        ],
    }
    args = Namespace(max_docs_per_query=0, max_docs_per_search=0, max_document_chars=0)
    records = _records_for_trace(trace, args)
    source = {**records[0], "judgment": {"contains_gold_answer": True}}
    target = {**records[1], "provider_id": "another-provider"}

    assert _query_url_reuse_key(source) == _query_url_reuse_key(target)
    reuse_cache = _build_query_url_reuse_cache([source], enabled=True)
    match = _matching_query_url_reuse_record(reuse_cache, target)

    assert match is source
    reused = _query_url_duplicate_output_record(match, target)
    assert reused["duplicate_reused"] is True
    assert reused["reuse_type"] == "query_url_duplicate"
    assert reused["retrieval_id"] == "ret2"
    assert reused["rank"] == 3
    assert reused["provider_id"] == "another-provider"
    assert reused["judgment"] == {"contains_gold_answer": True}
    assert reused["reuse_prompt_content_match"] is False


def test_query_url_duplicate_reuse_does_not_mix_fetched_and_unfetched_surfaces():
    trace = {
        "query_id": "q1",
        "provider_id": "fake",
        "question": "Which country won?",
        "gold_answer": "Sweden",
        "final_answer": "Sweden",
        "retrievals": [
            {
                "retrieval_id": "ret1",
                "search_query": "winner country",
                "search_response": {
                    "results": [
                        {
                            "document_id": "s1r1",
                            "rank": 1,
                            "title": "Source",
                            "url": "https://example.com/source",
                            "domain": "example.com",
                            "snippet": "Snippet only.",
                            "provider_metadata": {},
                        }
                    ]
                },
            },
            {
                "retrieval_id": "ret2",
                "search_query": "winner source",
                "search_response": {
                    "results": [
                        {
                            "document_id": "s2r1",
                            "rank": 1,
                            "title": "Source",
                            "url": "https://example.com/source",
                            "domain": "example.com",
                            "snippet": "Snippet with a fetched page.",
                            "provider_metadata": {},
                        }
                    ]
                },
            },
        ],
        "fetches": [
            {
                "fetch_id": "fetch1",
                "iteration_num": 2,
                "requested_document_id": "s2r1",
                "source_document_id": "s2r1",
                "source_retrieval_id": "ret2",
                "source_rank": 1,
                "url": "https://example.com/source",
                "page_fetch": {
                    "fetch_backend": "jina",
                    "fetch_status": "success",
                    "http_status": 200,
                    "content_type": "text/markdown",
                    "extractor": "jina_reader_markdown",
                    "final_url": "https://example.com/source",
                    "extracted_text": "The winner was Sweden.",
                    "extracted_text_chars": 22,
                },
            }
        ],
    }
    args = Namespace(max_docs_per_query=0, max_docs_per_search=0, max_document_chars=0)
    records = _records_for_trace(trace, args)
    snippet_only = {**records[0], "judgment": {"gold_answer_in_snippets": False}}
    page_visible = {**records[1], "judgment": {"gold_answer_in_extracted_page": True}}

    assert snippet_only["judge_surface_class"] == "snippet_only"
    assert page_visible["judge_surface_class"] == "page_visible"
    assert _query_url_reuse_key(snippet_only) != _query_url_reuse_key(page_visible)

    reuse_cache = _build_query_url_reuse_cache([page_visible], enabled=True)
    assert _matching_query_url_reuse_record(reuse_cache, snippet_only) is None


def test_kimi_env_slot_uses_slot_specific_endpoint_without_primary_fallback(monkeypatch):
    monkeypatch.setenv("KIMI_AZURE_OPENAI_ENDPOINT", "https://primary.example.openai.azure.com")
    monkeypatch.setenv("KIMI_AZURE_OPENAI_API_KEY", "primary-key")
    monkeypatch.setenv("KIMI_AZURE_OPENAI_ENDPOINT_2", "https://slot2.example.openai.azure.com")
    monkeypatch.setenv("KIMI_AZURE_OPENAI_API_KEY_2", "slot2-key")
    monkeypatch.setenv("KIMI_AZURE_OPENAI_DEPLOYMENT", "primary-deployment")
    monkeypatch.setenv("KIMI_AZURE_OPENAI_DEPLOYMENT_2", "slot2-deployment")
    args = Namespace(
        kimi_env_slot="2",
        model_id="azure:kimi-k2.6",
        temperature=0,
        max_tokens=123,
        timeout_seconds=45,
    )

    client = _build_kimi_client(args)

    assert client.endpoint == "https://slot2.example.openai.azure.com"
    assert client.api_key == "slot2-key"
    assert client.deployment == "slot2-deployment"


def test_kimi_env_slot_requires_slot_specific_endpoint_and_key(monkeypatch):
    monkeypatch.setenv("KIMI_AZURE_OPENAI_ENDPOINT", "https://primary.example.openai.azure.com")
    monkeypatch.setenv("KIMI_AZURE_OPENAI_API_KEY", "primary-key")
    monkeypatch.delenv("KIMI_AZURE_OPENAI_ENDPOINT_2", raising=False)
    monkeypatch.delenv("KIMI_AZURE_OPENAI_API_KEY_2", raising=False)
    args = Namespace(
        kimi_env_slot="2",
        model_id="azure:kimi-k2.6",
        temperature=0,
        max_tokens=123,
        timeout_seconds=45,
    )

    try:
        _build_kimi_client(args)
    except RuntimeError as error:
        assert "KIMI_AZURE_OPENAI_ENDPOINT_2" in str(error)
        assert "KIMI_AZURE_OPENAI_API_KEY_2" in str(error)
    else:
        raise AssertionError("slot 2 should not fall back to primary endpoint/key")


def test_parse_json_object_handles_fenced_json():
    parsed = parse_json_object('```json\n{"contains_gold_answer": true}\n```')

    assert parsed["contains_gold_answer"] is True


def test_parse_json_object_rejects_empty_content():
    try:
        parse_json_object("")
    except ValueError as error:
        assert "empty model response content" in str(error)
    else:
        raise AssertionError("empty content should fail explicitly")
