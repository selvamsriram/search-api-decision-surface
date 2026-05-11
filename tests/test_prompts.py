from searchapi_eval.agent.prompts import SYSTEM_PROMPT, render_search_documents, render_user_query


def test_system_prompt_includes_demarcated_example():
    assert "<system_instructions>" in SYSTEM_PROMPT
    assert "<user_query_example>" in SYSTEM_PROMPT
    assert "<search_documents_example>" in SYSTEM_PROMPT
    assert "not a recommendation to always search" in SYSTEM_PROMPT


def test_user_query_template_demarcates_query():
    rendered = render_user_query("Who won?")
    assert rendered == "<user_query>\nWho won?\n</user_query>"


def test_search_documents_template_escapes_document_content():
    rendered = render_search_documents(
        {
            "query": "A & B",
            "provider_id": "exa",
            "results": [
                {
                    "rank": 1,
                    "title": "Title <unsafe>",
                    "url": "https://example.com/?a=1&b=2",
                    "domain": "example.com",
                    "snippet": "Evidence & context",
                    "provider_metadata": {
                        "extra_snippets": ["More <evidence>", "Another & detail"],
                    },
                }
            ],
        }
    )
    assert "<search_documents>" in rendered
    assert 'query="A &amp; B"' in rendered
    assert "Title &lt;unsafe&gt;" in rendered
    assert "Evidence &amp; context" in rendered
    assert "<extra_snippet>More &lt;evidence&gt;</extra_snippet>" in rendered
    assert "<extra_snippet>Another &amp; detail</extra_snippet>" in rendered
