from searchapi_eval.providers.brave import BraveSearchProvider, _fit_brave_query


def test_brave_parse_results_normalizes_web_results():
    provider = BraveSearchProvider(api_key="test")
    results = provider._parse_results(
        {
            "web": {
                "results": [
                    {
                        "type": "search_result",
                        "title": "Example Result",
                        "url": "https://www.example.com/path?utm_source=x&keep=1#frag",
                        "description": "A useful snippet.",
                        "language": "en",
                        "page_age": "2024-01-01T00:00:00",
                    }
                ]
            }
        }
    )

    assert len(results) == 1
    assert results[0].rank == 1
    assert results[0].title == "Example Result"
    assert results[0].url == "https://www.example.com/path?keep=1"
    assert results[0].domain == "example.com"
    assert results[0].snippet == "A useful snippet."
    assert results[0].provider_metadata["language"] == "en"


def test_fit_brave_query_caps_words_and_chars():
    query = " ".join(f"word{i}" for i in range(80))
    fitted = _fit_brave_query(query, max_words=50, max_chars=120)

    assert len(fitted.split()) <= 50
    assert len(fitted) <= 120
