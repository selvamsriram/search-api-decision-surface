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


def test_trace_captures_full_llm_request_for_each_iteration():
    runner = AgentRunner(FakeProvider(), FakeModel(), max_iterations=3, max_results=1)
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
    assert "FINAL ANSWER: Example" not in second_request["messages"][-1]["content"]

