from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

PROMPT_DIR = Path(__file__).with_suffix("")


def _load_template(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _liquid_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_liquid(template: str, context: dict[str, Any]) -> str:
    rendered = template

    def resolve_path(path_text: str) -> Any:
        path = path_text.strip().split(".")
        value: Any = context
        for part in path:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)
        return value

    include_pattern = re.compile(r'{%\s*include\s+"(?P<name>[^"]+)"\s*%}')
    rendered = include_pattern.sub(lambda match: _load_template(match.group("name")), rendered)

    for_loop = re.compile(
        r"{%\s*for\s+(?P<item>\w+)\s+in\s+(?P<items>\w+)\s*%}(?P<body>.*?){%\s*endfor\s*%}",
        flags=re.DOTALL,
    )
    while True:
        match = for_loop.search(rendered)
        if not match:
            break
        item_name = match.group("item")
        items = context.get(match.group("items"), [])
        body = match.group("body")
        parts = []
        for item in items:
            scoped = dict(context)
            scoped[item_name] = item
            parts.append(render_liquid(body, scoped))
        rendered = rendered[: match.start()] + "".join(parts) + rendered[match.end() :]

    def replace_raw_variable(match: re.Match[str]) -> str:
        return "" if (value := resolve_path(match.group(1))) is None else str(value)

    rendered = re.sub(r"{{{\s*([^}]+?)\s*}}}", replace_raw_variable, rendered)

    def replace_variable(match: re.Match[str]) -> str:
        value = resolve_path(match.group(1))
        return _liquid_escape(value)

    return re.sub(r"{{\s*([^}]+?)\s*}}", replace_variable, rendered).strip()


def render_prompt(name: str, **context: Any) -> str:
    return render_liquid(_load_template(name), context)


SYSTEM_SEARCH_ONLY_PROMPT = render_prompt("system_search_only.liquid")
SYSTEM_PROMPT = SYSTEM_SEARCH_ONLY_PROMPT


def render_system_prompt(*, fetch_tool_enabled: bool = False) -> str:
    prompt_name = "system_fetch_tool.liquid" if fetch_tool_enabled else "system_search_only.liquid"
    return render_prompt(prompt_name)


def render_user_query(question: str) -> str:
    return render_prompt("user_query.liquid", question=question)


def render_search_documents(search_response: dict[str, Any], *, include_page_fetch: bool = True) -> str:
    results = []
    for result in search_response["results"]:
        enriched = dict(result)
        enriched["document_id"] = enriched.get("document_id") or f"rank_{enriched.get('rank')}"
        metadata = enriched.get("provider_metadata") or {}
        extra_snippets = metadata.get("extra_snippets") or []
        enriched["extra_snippets_xml"] = "\n".join(
            f"    <extra_snippet>{_liquid_escape(snippet)}</extra_snippet>"
            for snippet in extra_snippets
        )
        page_fetch = enriched.get("page_fetch") or {}
        extracted_text = page_fetch.get("extracted_text") or ""
        if include_page_fetch and page_fetch:
            enriched["extracted_page_xml"] = "\n".join(
                [
                    "    <extracted_page>",
                    f"      <fetch_backend>{_liquid_escape(page_fetch.get('fetch_backend'))}</fetch_backend>",
                    f"      <fetch_status>{_liquid_escape(page_fetch.get('fetch_status'))}</fetch_status>",
                    f"      <http_status>{_liquid_escape(page_fetch.get('http_status'))}</http_status>",
                    f"      <content_type>{_liquid_escape(page_fetch.get('content_type'))}</content_type>",
                    f"      <extractor>{_liquid_escape(page_fetch.get('extractor'))}</extractor>",
                    f"      <artifact_path>{_liquid_escape(page_fetch.get('artifact_path'))}</artifact_path>",
                    f"      <final_url>{_liquid_escape(page_fetch.get('final_url'))}</final_url>",
                    f"      <extracted_text_chars>{_liquid_escape(page_fetch.get('extracted_text_chars'))}</extracted_text_chars>",
                    f"      <extracted_text_tokens_estimate>{_liquid_escape(page_fetch.get('extracted_text_tokens_estimate'))}</extracted_text_tokens_estimate>",
                    "      <content>",
                    _liquid_escape(extracted_text),
                    "      </content>",
                    "    </extracted_page>",
                ]
            )
        else:
            enriched["extracted_page_xml"] = ""
        results.append(enriched)
    return render_prompt(
        "search_documents.liquid",
        search_query=search_response["query"],
        provider_id=search_response["provider_id"],
        results=results,
    )


def render_fetched_page(page_fetch: dict[str, Any], *, url: str, source: dict[str, Any] | None = None) -> str:
    source = source or {}
    extracted_text = page_fetch.get("extracted_text") or ""
    return "\n".join(
        [
            "<fetched_page>",
            f"  <url>{_liquid_escape(url)}</url>",
            f"  <source_document_id>{_liquid_escape(source.get('document_id'))}</source_document_id>",
            f"  <source_retrieval_id>{_liquid_escape(source.get('retrieval_id'))}</source_retrieval_id>",
            f"  <source_rank>{_liquid_escape(source.get('rank'))}</source_rank>",
            f"  <title>{_liquid_escape(source.get('title'))}</title>",
            f"  <domain>{_liquid_escape(source.get('domain'))}</domain>",
            f"  <snippet>{_liquid_escape(source.get('snippet'))}</snippet>",
            f"  <fetch_backend>{_liquid_escape(page_fetch.get('fetch_backend'))}</fetch_backend>",
            f"  <final_url>{_liquid_escape(page_fetch.get('final_url'))}</final_url>",
            f"  <reader_url>{_liquid_escape(page_fetch.get('reader_url'))}</reader_url>",
            f"  <fetch_status>{_liquid_escape(page_fetch.get('fetch_status'))}</fetch_status>",
            f"  <http_status>{_liquid_escape(page_fetch.get('http_status'))}</http_status>",
            f"  <content_type>{_liquid_escape(page_fetch.get('content_type'))}</content_type>",
            f"  <extractor>{_liquid_escape(page_fetch.get('extractor'))}</extractor>",
            f"  <artifact_path>{_liquid_escape(page_fetch.get('artifact_path'))}</artifact_path>",
            f"  <extracted_text_chars>{_liquid_escape(page_fetch.get('extracted_text_chars'))}</extracted_text_chars>",
            f"  <extracted_text_tokens_estimate>{_liquid_escape(page_fetch.get('extracted_text_tokens_estimate'))}</extracted_text_tokens_estimate>",
            "  <content>",
            _liquid_escape(extracted_text),
            "  </content>",
            "</fetched_page>",
        ]
    )


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web for information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to send to the configured web search provider.",
                }
            },
            "required": ["query"],
        },
    },
}

FETCH_PAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_page",
        "description": "Fetch and extract text from a search result by document_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Exact document_id from a previous search_web result, for example s1r3.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason this page is worth opening.",
                },
            },
            "required": ["document_id"],
        },
    },
}
