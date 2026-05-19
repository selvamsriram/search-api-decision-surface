from searchapi_eval.providers.tavily import TavilySearchProvider


def test_tavily_parse_results_normalizes_results():
    provider = TavilySearchProvider(api_key="test")
    results = provider._parse_results(
        {
            "response_time": "0.84",
            "request_id": "req-123",
            "usage": {"credits": 1},
            "results": [
                {
                    "title": "Example Result",
                    "url": "https://www.example.com/path?utm_source=x&keep=1#frag",
                    "content": "A useful snippet from Tavily.",
                    "score": 0.88,
                    "favicon": "https://example.com/favicon.ico",
                    "raw_content": "Full page-ish content.",
                }
            ],
        }
    )

    assert len(results) == 1
    assert results[0].rank == 1
    assert results[0].title == "Example Result"
    assert results[0].url == "https://www.example.com/path?keep=1"
    assert results[0].domain == "example.com"
    assert results[0].snippet == "A useful snippet from Tavily."
    assert results[0].provider_metadata["score"] == 0.88
    assert results[0].provider_metadata["raw_content_included"] is True
    assert results[0].provider_metadata["request_id"] == "req-123"
