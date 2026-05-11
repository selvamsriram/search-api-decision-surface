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

    def resolve_path(path_text: str) -> Any:
        path = path_text.strip().split(".")
        value: Any = context
        for part in path:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)
        return value

    def replace_raw_variable(match: re.Match[str]) -> str:
        return "" if (value := resolve_path(match.group(1))) is None else str(value)

    rendered = re.sub(r"{{{\s*([^}]+?)\s*}}}", replace_raw_variable, rendered)

    def replace_variable(match: re.Match[str]) -> str:
        value = resolve_path(match.group(1))
        return _liquid_escape(value)

    return re.sub(r"{{\s*([^}]+?)\s*}}", replace_variable, rendered).strip()


def render_prompt(name: str, **context: Any) -> str:
    return render_liquid(_load_template(name), context)


SYSTEM_PROMPT = render_prompt("system.liquid")


def render_user_query(question: str) -> str:
    return render_prompt("user_query.liquid", question=question)


def render_search_documents(search_response: dict[str, Any]) -> str:
    results = []
    for result in search_response["results"]:
        enriched = dict(result)
        metadata = enriched.get("provider_metadata") or {}
        extra_snippets = metadata.get("extra_snippets") or []
        enriched["extra_snippets_xml"] = "\n".join(
            f"    <extra_snippet>{_liquid_escape(snippet)}</extra_snippet>"
            for snippet in extra_snippets
        )
        results.append(enriched)
    return render_prompt(
        "search_documents.liquid",
        search_query=search_response["query"],
        provider_id=search_response["provider_id"],
        results=results,
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
