from searchapi_eval.evaluation.trace_analysis import per_trace_metrics, source_family, summarize_provider


def test_per_trace_metrics_detects_answer_text_and_gold_alignment():
    trace = {
        "trace_id": "trace1",
        "query_id": "q1",
        "provider_id": "fake",
        "question": "Which country won?",
        "gold_answer": "Sweden",
        "gold_urls": ["https://example.com/report"],
        "final_answer": "Finland",
        "answered": True,
        "failed": False,
        "total_search_calls": 1,
        "total_prompt_tokens": 100,
        "total_completion_tokens": 5,
        "retrievals": [
            {
                "search_query": "country winner",
                "search_response": {
                    "results": [
                        {
                            "rank": 1,
                            "title": "Report",
                            "url": "https://example.com/report?utm_source=x",
                            "domain": "example.com",
                            "snippet": "The answer is Sweden.",
                            "provider_metadata": {},
                            "page_fetch": {
                                "fetch_status": "success",
                                "extractor": "trafilatura",
                                "extracted_text_chars": 32,
                                "extracted_text": "The answer is Sweden.",
                            },
                        }
                    ]
                },
            }
        ],
        "iterations": [{"iteration_num": 1, "agent_decision": "answer", "searches": []}],
    }

    metrics = per_trace_metrics(trace)

    assert metrics["gold_url_prefix_hit"] is True
    assert metrics["gold_url_exact_hit"] is True
    assert metrics["answer_in_snippet"] is True
    assert metrics["answer_in_page"] is True
    assert metrics["wrong_with_answer_text_available"] is True


def test_per_trace_metrics_counts_fetch_tool_pages_as_retrieved_text():
    trace = {
        "trace_id": "trace-fetch-tool",
        "query_id": "q-fetch-tool",
        "provider_id": "fake",
        "question": "Which country won?",
        "gold_answer": "Sweden",
        "gold_urls": ["https://example.com/report"],
        "final_answer": "Finland",
        "answered": True,
        "failed": False,
        "total_search_calls": 1,
        "total_prompt_tokens": 100,
        "total_completion_tokens": 5,
        "retrievals": [
            {
                "search_query": "country winner",
                "search_response": {
                    "results": [
                        {
                            "rank": 2,
                            "title": "Report",
                            "url": "https://example.com/report",
                            "domain": "example.com",
                            "snippet": "A report about the contest.",
                            "provider_metadata": {},
                        }
                    ]
                },
            }
        ],
        "fetches": [
            {
                "requested_document_id": "s1r2",
                "source_document_id": "s1r2",
                "source_rank": 2,
                "url": "https://example.com/report",
                "page_fetch": {
                    "fetch_status": "success",
                    "extractor": "jina_reader_markdown",
                    "extracted_text_chars": 32,
                    "extracted_text": "The answer is Sweden.",
                },
            }
        ],
        "iterations": [{"iteration_num": 1, "agent_decision": "answer", "searches": []}],
    }

    metrics = per_trace_metrics(trace)

    assert metrics["answer_in_snippet"] is False
    assert metrics["answer_in_page"] is True
    assert metrics["answer_in_any_retrieved_text"] is True
    assert metrics["first_answer_page_rank"] == 2
    assert metrics["fetch_status_counts"] == {"success": 1}
    assert metrics["extractor_counts"] == {"jina_reader_markdown": 1}


def test_summarize_provider_counts_recovered_transient_failures():
    failed = {"query_id": "q1", "provider_id": "fake", "failed": True}
    recovered = {
        "query_id": "q1",
        "provider_id": "fake",
        "failed": False,
        "answered": True,
        "final_answer": "Sweden",
        "gold_answer": "Sweden",
        "gold_urls": [],
        "retrievals": [],
        "iterations": [],
    }

    summary = summarize_provider([failed, recovered])

    assert summary["historical_failed_rows"] == 1
    assert summary["latest_failed_queries"] == 0
    assert summary["transient_failures_recovered"] == 1


def test_source_family_groups_wikipedia_page_variants():
    assert source_family("https://en.wikipedia.org/wiki/Example#Section") == "en.wikipedia.org/wiki/example"
