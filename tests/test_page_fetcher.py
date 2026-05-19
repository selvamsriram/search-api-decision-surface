from searchapi_eval.page_fetcher.fetcher import PageFetcher
from searchapi_eval.page_fetcher.html_extract import extract_html_text


def test_stdlib_html_extractor_removes_scripts_and_keeps_visible_text():
    text, method = extract_html_text(
        """
        <html>
          <head><script>secret()</script></head>
          <body><h1>Largest deals</h1><p>The answer is visible.</p></body>
        </html>
        """
    )

    assert method in {"trafilatura", "stdlib_html_parser"}
    assert "The answer is visible." in text
    assert "secret()" not in text


def test_page_fetcher_marks_powerpoint_as_unsupported():
    fetcher = PageFetcher()
    text, method = fetcher._extract_text(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 128,
        "application/vnd.ms-powerpoint",
        "https://example.com/deck.ppt",
    )

    assert text == ""
    assert method == "office_unsupported_v1"


def test_page_fetcher_marks_unknown_binary_as_unsupported():
    fetcher = PageFetcher()
    text, method = fetcher._extract_text(
        b"\x00\x01\x02\x03\x04\x05\x06\x07" * 32,
        "",
        "https://example.com/download",
    )

    assert text == ""
    assert method == "binary_unsupported_v1"


def test_page_fetcher_keeps_plain_text_content():
    fetcher = PageFetcher()
    text, method = fetcher._extract_text(
        b"The answer is Sweden.\nThis is normal text.",
        "text/plain; charset=utf-8",
        "https://example.com/result.txt",
    )

    assert method == "plain_text"
    assert "The answer is Sweden." in text


def test_jina_backend_uses_distinct_cache_key():
    local_fetcher = PageFetcher(backend="local")
    jina_fetcher = PageFetcher(backend="jina")

    assert local_fetcher._artifact_path("https://example.com/page") != jina_fetcher._artifact_path("https://example.com/page")


def test_jina_markdown_fetch_decodes_reader_response(monkeypatch):
    class FakeHeaders:
        def get(self, name):
            if name.lower() == "content-type":
                return "text/markdown; charset=utf-8"
            if name.lower() == "content-length":
                return "24"
            return None

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return b"Title\n\nThe answer is HPC6."

        def geturl(self):
            return "https://r.jina.ai/https://example.com/page"

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://r.jina.ai/https://example.com/page"
        assert timeout == 5
        return FakeResponse()

    monkeypatch.setattr("searchapi_eval.page_fetcher.fetcher.urlopen", fake_urlopen)

    fetcher = PageFetcher(backend="jina", timeout_seconds=5)
    text, method, info = fetcher._fetch_jina_markdown("https://example.com/page")

    assert method == "jina_reader_markdown"
    assert "The answer is HPC6." in text
    assert info["reader_url"] == "https://r.jina.ai/https://example.com/page"


def test_jina_markdown_fetch_sends_api_key_when_configured(monkeypatch):
    class FakeHeaders:
        def get(self, _name):
            return None

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return b"ok"

        def geturl(self):
            return "https://r.jina.ai/https://example.com/page"

    def fake_urlopen(request, timeout=None):
        assert request.get_header("Authorization") == "Bearer jina_test_key"
        assert timeout == fetcher.timeout_seconds
        return FakeResponse()

    monkeypatch.setattr("searchapi_eval.page_fetcher.fetcher.urlopen", fake_urlopen)

    fetcher = PageFetcher(backend="jina", jina_api_key="jina_test_key")
    text, _, _ = fetcher._fetch_jina_markdown("https://example.com/page")

    assert text == "ok"
