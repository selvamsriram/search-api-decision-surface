from searchapi_eval.providers.firecrawl import FirecrawlSearchProvider


def test_firecrawl_parse_results_normalizes_v2_web_results():
    provider = FirecrawlSearchProvider(api_key="test")
    results = provider._parse_results(
        {
            "success": True,
            "id": "fc-job-123",
            "creditsUsed": 2,
            "data": {
                "web": [
                    {
                        "title": "Example Result",
                        "description": "A useful Firecrawl description.",
                        "url": "https://www.example.com/path?utm_source=x&keep=1#frag",
                        "markdown": "# Example\nFull markdown content.",
                        "metadata": {"statusCode": 200, "sourceURL": "https://example.com/path"},
                    }
                ]
            },
        }
    )

    assert len(results) == 1
    assert results[0].rank == 1
    assert results[0].title == "Example Result"
    assert results[0].url == "https://www.example.com/path?keep=1"
    assert results[0].domain == "example.com"
    assert results[0].snippet == "A useful Firecrawl description."
    assert results[0].provider_metadata["markdown_included"] is True
    assert results[0].provider_metadata["credits_used"] == 2


def test_firecrawl_parse_results_supports_legacy_data_list_shape():
    provider = FirecrawlSearchProvider(api_key="test")
    results = provider._parse_results(
        {
            "success": True,
            "data": [
                {
                    "url": "https://example.org/a",
                    "markdown": "Legacy markdown content.",
                    "metadata": {"title": "Legacy Result", "description": "Legacy description."},
                }
            ],
        }
    )

    assert len(results) == 1
    assert results[0].title == "Legacy Result"
    assert results[0].snippet == "Legacy description."
