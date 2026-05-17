from __future__ import annotations

import asyncio

from searchapi_eval.agent.loop import AgentRunner
from searchapi_eval.models.base import LLMClient, LLMResponse
from searchapi_eval.providers.base import SearchProvider, SearchResponse, SearchResult, utc_now_iso


class FakeModel(LLMClient):
    model_id = "fake:model"
    input_price_per_1k_usd = 0.0
    output_price_per_1k_usd = 0.0

    def __init__(self) -> None:
        self.calls = 0

    def request_snapshot(self, messages, tools):
        return {
            "provider": "fake",
            "model_id": self.model_id,
            "temperature": 0,
            "messages": messages,
            "tools": tools,
        }

    async def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search_web", "arguments": '{"query":"example query"}'},
                    }
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                latency_ms=1.0,
                raw_response={},
            )
        return LLMResponse(
            content="FINAL ANSWER: Example",
            tool_calls=[],
            usage={"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26},
            latency_ms=1.0,
            raw_response={},
        )


class FakeFetchModel(LLMClient):
    model_id = "fake:model"
    input_price_per_1k_usd = 0.0
    output_price_per_1k_usd = 0.0

    def __init__(self) -> None:
        self.calls = 0

    def request_snapshot(self, messages, tools):
        return {
            "provider": "fake",
            "model_id": self.model_id,
            "temperature": 0,
            "messages": messages,
            "tools": tools,
        }

    async def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            assert any(tool["function"]["name"] == "fetch_page" for tool in tools)
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_search",
                        "type": "function",
                        "function": {"name": "search_web", "arguments": '{"query":"example query"}'},
                    }
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                latency_ms=1.0,
                raw_response={},
            )
        if self.calls == 2:
            assert "<search_documents>" in messages[-1]["content"]
            assert "<extracted_page>" not in messages[-1]["content"]
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_fetch",
                        "type": "function",
                        "function": {
                            "name": "fetch_page",
                            "arguments": '{"document_id":"s1r1","reason":"open promising source"}',
                        },
                    }
                ],
                usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
                latency_ms=1.0,
                raw_response={},
            )
        return LLMResponse(
            content="FINAL ANSWER: Example",
            tool_calls=[],
            usage={"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36},
            latency_ms=1.0,
            raw_response={},
        )


class FakeProvider(SearchProvider):
    provider_id = "fake-search"
    cost_per_query_usd = 0.0

    async def search(self, query: str, max_results: int = 10):
        return SearchResponse(
            provider_id=self.provider_id,
            query=query,
            results=[
                SearchResult(
                    rank=1,
                    title="Example Source",
                    url="https://example.com/source",
                    snippet="Example evidence.",
                    domain="example.com",
                    provider_metadata={},
                )
            ],
            latency_ms=1.0,
            raw_response={"fake": True},
            timestamp=utc_now_iso(),
        )


class FakePageFetcher:
    enabled = True
    cache_dir = "data/page_cache"
    max_bytes = 1000
    timeout_seconds = 1.0

    async def fetch_results(self, search_response, retrieval_id):
        return [
            {
                "schema_version": "page_fetch_summary_v1",
                "url": "https://example.com/source",
                "normalized_url": "https://example.com/source",
                "final_url": "https://example.com/source",
                "artifact_path": "data/page_cache/fake.json.gz",
                "fetch_status": "success",
                "http_status": 200,
                "content_type": "text/html",
                "truncated_by_max_bytes": False,
                "extractor": "test",
                "extracted_text_chars": 35,
                "extracted_text_tokens_estimate": 9,
                "text_sha256": "abc",
                "fetch_latency_ms": 1.0,
                "error": None,
                "extracted_text": "The example answer is Example.",
            }
        ]


def test_trace_captures_full_llm_request_for_each_iteration():
    runner = AgentRunner(FakeProvider(), FakeModel(), max_iterations=3, max_results=1, page_fetcher=FakePageFetcher())
    trace = asyncio.run(
        runner.run_query(
            {
                "query_id": "q1",
                "source_index": 0,
                "question": "What is the example answer?",
                "answer": "Example",
                "urls": [],
                "freshness": "never-changing",
                "topic": "Others",
                "search_results": "conflicting",
                "question_types": ["advanced reasoning"],
                "effective_year": "before 2024",
            }
        )
    )

    assert len(trace["iterations"]) == 2
    first_request = trace["iterations"][0]["llm_request"]
    second_request = trace["iterations"][1]["llm_request"]

    assert first_request["model_id"] == "fake:model"
    assert first_request["tools"][0]["function"]["name"] == "search_web"
    assert first_request["messages"][0]["role"] == "system"
    assert "<user_query>" in first_request["messages"][1]["content"]

    assert any(message["role"] == "tool" for message in second_request["messages"])
    assert "<search_documents>" in second_request["messages"][-1]["content"]
    assert "<extracted_page>" in second_request["messages"][-1]["content"]
    assert "The example answer is Example." in second_request["messages"][-1]["content"]
    assert "FINAL ANSWER: Example" not in second_request["messages"][-1]["content"]

    result = trace["retrievals"][0]["search_response"]["results"][0]
    assert result["page_fetch"]["artifact_path"] == "data/page_cache/fake.json.gz"


def test_fetch_tool_mode_keeps_search_snippet_only_and_records_fetches():
    runner = AgentRunner(
        FakeProvider(),
        FakeFetchModel(),
        max_iterations=4,
        max_results=1,
        page_fetcher=FakePageFetcher(),
        fetch_tool_enabled=True,
        auto_page_fetch=False,
    )
    trace = asyncio.run(
        runner.run_query(
            {
                "query_id": "q1",
                "source_index": 0,
                "question": "What is the example answer?",
                "answer": "Example",
                "urls": [],
                "freshness": "never-changing",
                "topic": "Others",
                "search_results": "conflicting",
                "question_types": ["advanced reasoning"],
                "effective_year": "before 2024",
            }
        )
    )

    assert len(trace["iterations"]) == 3
    assert trace["config"]["fetch_tool_enabled"] is True
    assert trace["config"]["page_fetch_enabled"] is False
    assert trace["total_search_calls"] == 1
    assert trace["total_fetch_calls"] == 1
    assert "page_fetch" not in trace["retrievals"][0]["search_response"]["results"][0]

    second_request = trace["iterations"][1]["llm_request"]
    assert any(tool["function"]["name"] == "fetch_page" for tool in second_request["tools"])
    assert "<extracted_page>" not in second_request["messages"][-1]["content"]

    third_request = trace["iterations"][2]["llm_request"]
    assert "<fetched_page>" in third_request["messages"][-1]["content"]
    assert "The example answer is Example." in third_request["messages"][-1]["content"]

    fetch = trace["fetches"][0]
    assert fetch["requested_document_id"] == "s1r1"
    assert fetch["source_document_id"] == "s1r1"
    assert fetch["seen_in_search_results"] is True
    assert fetch["source_rank"] == 1
    assert fetch["url"] == "https://example.com/source"
    assert fetch["page_fetch"]["artifact_path"] == "data/page_cache/fake.json.gz"
