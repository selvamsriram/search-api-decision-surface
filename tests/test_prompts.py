from searchapi_eval.agent.prompts import FETCH_PAGE_TOOL, SYSTEM_PROMPT, render_fetched_page, render_search_documents, render_system_prompt, render_user_query


def test_system_prompt_includes_demarcated_example():
    assert "<system_instructions>" in SYSTEM_PROMPT
    assert "<user_query_example>" in SYSTEM_PROMPT
    assert "<search_documents_example>" in SYSTEM_PROMPT
    assert "not a recommendation to always search" in SYSTEM_PROMPT
    assert "fetch_page" not in SYSTEM_PROMPT


def test_system_prompt_can_include_fetch_page_instructions():
    rendered = render_system_prompt(fetch_tool_enabled=True)

    assert "fetch_page" in rendered
    assert "document_id" in rendered
    assert "<fetched_page>" in rendered
    assert "search_web" in rendered
    assert FETCH_PAGE_TOOL["function"]["name"] == "fetch_page"
    assert FETCH_PAGE_TOOL["function"]["parameters"]["required"] == ["document_id"]
    assert "url" not in FETCH_PAGE_TOOL["function"]["parameters"]["properties"]


def test_system_prompt_omits_fetch_page_instructions_when_disabled():
    rendered = render_system_prompt(fetch_tool_enabled=False)

    assert "fetch_page" not in rendered
    assert "<fetched_page>" not in rendered


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
                    "page_fetch": {
                        "fetch_status": "success",
                        "http_status": 200,
                        "content_type": "text/html",
                        "extractor": "trafilatura",
                        "artifact_path": "data/page_cache/a/b.json.gz",
                        "final_url": "https://example.com/?a=1&b=2",
                        "extracted_text_chars": 19,
                        "extracted_text_tokens_estimate": 5,
                        "extracted_text": "Full <page> & answer",
                    },
                }
            ],
        }
    )
    assert "<search_documents>" in rendered
    assert 'query="A &amp; B"' in rendered
    assert '<document id="rank_1" rank="1">' in rendered
    assert "<document_id>rank_1</document_id>" in rendered
    assert "Title &lt;unsafe&gt;" in rendered
    assert "Evidence &amp; context" in rendered
    assert "<extra_snippet>More &lt;evidence&gt;</extra_snippet>" in rendered
    assert "<extra_snippet>Another &amp; detail</extra_snippet>" in rendered
    assert "<extracted_page>" in rendered
    assert "Full &lt;page&gt; &amp; answer" in rendered


def test_search_documents_can_omit_auto_fetched_page_content():
    rendered = render_search_documents(
        {
            "query": "A",
            "provider_id": "exa",
            "results": [
                {
                    "rank": 1,
                    "title": "Title",
                    "url": "https://example.com",
                    "domain": "example.com",
                    "snippet": "Snippet only",
                    "provider_metadata": {},
                    "page_fetch": {
                        "fetch_status": "success",
                        "extracted_text": "Hidden page text",
                    },
                }
            ],
        },
        include_page_fetch=False,
    )

    assert "Snippet only" in rendered
    assert "<extracted_page>" not in rendered
    assert "Hidden page text" not in rendered


def test_render_fetched_page_escapes_content_and_metadata():
    rendered = render_fetched_page(
        {
            "final_url": "https://example.com/?a=1&b=2",
            "fetch_status": "success",
            "http_status": 200,
            "content_type": "text/html",
            "extractor": "trafilatura",
            "artifact_path": "data/page_cache/a.json.gz",
            "extracted_text_chars": 19,
            "extracted_text_tokens_estimate": 5,
            "extracted_text": "Full <page> & answer",
        },
        url="https://example.com/?a=1&b=2",
        source={"document_id": "s1r1", "retrieval_id": "ret1", "rank": 1, "title": "Title", "domain": "example.com", "snippet": "Snippet"},
    )

    assert "<fetched_page>" in rendered
    assert "<source_document_id>s1r1</source_document_id>" in rendered
    assert "https://example.com/?a=1&amp;b=2" in rendered
    assert "<source_rank>1</source_rank>" in rendered
    assert "Full &lt;page&gt; &amp; answer" in rendered
