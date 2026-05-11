#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Iterable

from searchapi_eval.evaluation.metrics import compute_trace_metrics


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def short(value: str, limit: int = 220) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def iter_traces(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                trace = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on line {line_num} of {path}: {error}") from error
            trace["_jsonl_line_num"] = line_num
            yield trace


def select_trace(
    path: Path,
    *,
    latest: bool,
    trace_id: str | None,
    query_id: str | None,
    index: int | None,
) -> dict[str, Any]:
    matches_seen = 0
    selected: dict[str, Any] | None = None
    for trace in iter_traces(path):
        if trace_id and trace.get("trace_id") != trace_id:
            continue
        if query_id and trace.get("query_id") != query_id:
            continue
        matches_seen += 1
        if index is not None and matches_seen != index:
            continue
        selected = trace
        if not latest:
            break

    if selected is None:
        criteria = []
        if trace_id:
            criteria.append(f"trace_id={trace_id}")
        if query_id:
            criteria.append(f"query_id={query_id}")
        if index is not None:
            criteria.append(f"index={index}")
        if latest:
            criteria.append("latest")
        raise SystemExit(f"No trace matched {', '.join(criteria) or 'the selection'} in {path}")
    return selected


def status_pill(label: str, value: Any) -> str:
    klass = "neutral"
    if value is True:
        klass = "good"
    elif value is False:
        klass = "bad"
    return f'<span class="pill {klass}"><span>{esc(label)}</span><strong>{esc(value)}</strong></span>'


def format_json(data: Any) -> str:
    return esc(json.dumps(data, indent=2, ensure_ascii=False))


def render_message(message: dict[str, Any], index: int) -> str:
    role = message.get("role", "")
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    summary_bits = [f"message {index}", f"role={role}"]
    if content:
        summary_bits.append(f"{len(content):,} chars")
    if tool_calls:
        summary_bits.append(f"{len(tool_calls)} tool call(s)")
    body = []
    if content:
        body.append(f'<pre class="message-content">{esc(content)}</pre>')
    if tool_calls:
        body.append(
            "<div class=\"subhead\">Tool Calls</div>"
            f'<pre class="json">{format_json(tool_calls)}</pre>'
        )
    return (
        f'<details class="message {esc(role)}">'
        f"<summary>{esc(' | '.join(summary_bits))}</summary>"
        + "\n".join(body)
        + "</details>"
    )


def render_result(result: dict[str, Any]) -> str:
    url = result.get("url", "")
    metadata = result.get("provider_metadata") or {}
    extra = metadata.get("extra_snippets") or []
    extra_html = ""
    if extra:
        items = "".join(f"<li>{esc(snippet)}</li>" for snippet in extra[:3])
        extra_html = f"<details><summary>extra snippets ({len(extra)})</summary><ul>{items}</ul></details>"
    return f"""
    <article class="result">
      <div class="rank">#{esc(result.get('rank'))}</div>
      <div>
        <h4>{esc(result.get('title'))}</h4>
        <a href="{esc(url)}">{esc(url)}</a>
        <div class="domain">{esc(result.get('domain'))}</div>
        <p>{esc(result.get('snippet'))}</p>
        {extra_html}
      </div>
    </article>
    """


def render_search(retrieval: dict[str, Any]) -> str:
    response = retrieval.get("search_response", {})
    results = response.get("results", [])
    rendered_results = "\n".join(render_result(result) for result in results)
    raw_response = response.get("raw_response", {})
    return f"""
    <details class="search" open>
      <summary>Search: {esc(retrieval.get('search_query'))} ({len(results)} results, {response.get('latency_ms', 0):.0f} ms)</summary>
      <div class="search-meta">
        provider={esc(response.get('provider_id'))}
        retrieval_id={esc(retrieval.get('retrieval_id'))}
        tool_call_id={esc(retrieval.get('tool_call_id'))}
      </div>
      <div class="results">{rendered_results}</div>
      <details class="raw-response">
        <summary>Full raw provider response</summary>
        <pre class="json">{format_json(raw_response)}</pre>
      </details>
    </details>
    """


def render_iteration(iteration: dict[str, Any]) -> str:
    request = iteration.get("llm_request") or {}
    messages = request.get("messages") or []
    tools = request.get("tools") or []
    searches = iteration.get("searches") or []
    rendered_messages = "\n".join(render_message(message, index) for index, message in enumerate(messages))
    rendered_searches = "\n".join(render_search(search) for search in searches) or '<p class="muted">No search calls in this iteration.</p>'
    request_config = {
        key: request.get(key)
        for key in (
            "provider",
            "model_id",
            "endpoint",
            "deployment",
            "api_version",
            "temperature",
            "max_tokens_field",
            "max_tokens",
            "tool_choice",
        )
        if key in request
    }
    tool_names = [tool.get("function", {}).get("name") for tool in tools]
    response = iteration.get("llm_response") or ""
    response_html = (
        f'<pre class="message-content">{esc(response)}</pre>'
        if response
        else '<p class="muted">No assistant text content. The model returned tool call(s).</p>'
    )
    tool_calls = iteration.get("llm_tool_calls") or []
    return f"""
    <section class="iteration">
      <div class="iteration-head">
        <h2>Iteration {esc(iteration.get('iteration_num'))}</h2>
        <div class="chips">
          <span class="chip">decision: {esc(iteration.get('agent_decision'))}</span>
          <span class="chip">latency: {iteration.get('llm_latency_ms', 0):.0f} ms</span>
          <span class="chip">prompt: {esc((iteration.get('llm_usage') or {}).get('prompt_tokens', 0))}</span>
          <span class="chip">completion: {esc((iteration.get('llm_usage') or {}).get('completion_tokens', 0))}</span>
        </div>
      </div>
      <details class="panel" open>
        <summary>LLM Request Snapshot</summary>
        <div class="kv"><strong>Config</strong><pre class="json">{format_json(request_config)}</pre></div>
        <div class="kv"><strong>Tool schema names</strong><pre class="json">{format_json(tool_names)}</pre></div>
        <div class="messages">{rendered_messages}</div>
      </details>
      <details class="panel" open>
        <summary>LLM Response</summary>
        {response_html}
        <div class="subhead">Tool Calls</div>
        <pre class="json">{format_json(tool_calls)}</pre>
      </details>
      <details class="panel" open>
        <summary>Searches Performed After This Response</summary>
        {rendered_searches}
      </details>
    </section>
    """


def render_timeline(trace: dict[str, Any]) -> str:
    rows = []
    for iteration in trace.get("iterations", []):
        searches = iteration.get("searches") or []
        query_preview = "<br>".join(esc(short(search.get("search_query", ""), 120)) for search in searches)
        if not query_preview:
            query_preview = '<span class="muted">none</span>'
        usage = iteration.get("llm_usage") or {}
        rows.append(
            f"""
            <tr>
              <td>{esc(iteration.get('iteration_num'))}</td>
              <td>{esc(iteration.get('agent_decision'))}</td>
              <td>{query_preview}</td>
              <td>{sum(len((search.get('search_response') or {}).get('results', [])) for search in searches)}</td>
              <td>{esc(usage.get('prompt_tokens', 0))} / {esc(usage.get('completion_tokens', 0))}</td>
              <td>{iteration.get('llm_latency_ms', 0):.0f} ms</td>
            </tr>
            """
        )
    return "<tbody>" + "\n".join(rows) + "</tbody>"


def render_html(trace: dict[str, Any], source_path: Path) -> str:
    metrics = compute_trace_metrics(trace)
    iterations = "\n".join(render_iteration(iteration) for iteration in trace.get("iterations", []))
    gold_urls = "".join(f'<li><a href="{esc(url)}">{esc(url)}</a></li>' for url in trace.get("gold_urls", []))
    errors = trace.get("errors") or []
    errors_html = ""
    if errors:
        errors_html = f"""
        <section class="card">
          <h2>Errors</h2>
          <pre class="json">{format_json(errors)}</pre>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trace View: {esc(trace.get('query_id'))}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #657383;
      --line: #d9e0e7;
      --soft: #eef3f7;
      --good: #126b43;
      --bad: #9b2c2c;
      --warn: #805b10;
      --accent: #255c99;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }}
    header {{
      background: #182331;
      color: white;
      padding: 24px 32px;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 24px; }}
    header p {{ margin: 0; color: #c9d4df; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .card, .iteration, .panel, .message, .search {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(20, 32, 44, 0.04);
    }}
    .card {{ padding: 16px; margin-bottom: 16px; }}
    .card h2, .iteration h2 {{ margin: 0 0 10px; font-size: 18px; }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    .pill, .chip {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 4px 9px;
      margin: 3px 4px 3px 0;
      background: var(--soft);
      font-size: 13px;
    }}
    .pill.good strong {{ color: var(--good); }}
    .pill.bad strong {{ color: var(--bad); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); }}
    th, td {{ border-bottom: 1px solid var(--line); text-align: left; padding: 9px; vertical-align: top; }}
    th {{ background: var(--soft); font-size: 13px; }}
    .iteration {{ margin: 18px 0; padding: 0; overflow: hidden; }}
    .iteration-head {{ padding: 16px; border-bottom: 1px solid var(--line); }}
    .panel, .message, .search {{ margin: 12px 16px; box-shadow: none; }}
    summary {{ cursor: pointer; padding: 10px 12px; font-weight: 650; }}
    .panel > summary, .search > summary {{ background: var(--soft); }}
    .message.system summary {{ border-left: 4px solid #5c6f82; }}
    .message.user summary {{ border-left: 4px solid var(--accent); }}
    .message.assistant summary {{ border-left: 4px solid #7a5ea8; }}
    .message.tool summary {{ border-left: 4px solid #2f7d67; }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 12px;
      background: #0f1720;
      color: #e7edf3;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.45;
    }}
    .message-content {{ margin: 0 12px 12px; }}
    .json {{ margin: 8px 12px 12px; }}
    .subhead {{ font-size: 13px; font-weight: 700; color: var(--muted); margin: 10px 12px 4px; }}
    .kv strong {{ display: block; margin: 10px 12px 4px; }}
    .search-meta, .muted {{ color: var(--muted); font-size: 13px; }}
    .search-meta {{ padding: 0 12px 8px; }}
    .result {{ display: grid; grid-template-columns: 44px 1fr; gap: 10px; padding: 12px; border-top: 1px solid var(--line); }}
    .rank {{ color: var(--muted); font-weight: 700; }}
    .result h4 {{ margin: 0 0 4px; }}
    .result a {{ color: var(--accent); word-break: break-all; }}
    .domain {{ color: var(--muted); font-size: 13px; margin-top: 2px; }}
    .result p {{ margin: 8px 0; }}
    ul {{ margin-top: 6px; }}
    @media (max-width: 720px) {{
      header {{ padding: 18px; }}
      main {{ padding: 14px; }}
      .result {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Trace View: {esc(trace.get('query_id'))}</h1>
    <p>{esc(short(trace.get('question', ''), 260))}</p>
  </header>
  <main>
    <section class="card">
      <h2>Run Summary</h2>
      <div class="meta">Source JSONL: {esc(source_path)} line {esc(trace.get('_jsonl_line_num'))}</div>
      <div>
        {status_pill('failed', trace.get('failed'))}
        {status_pill('answered', trace.get('answered'))}
        {status_pill('exact_match', metrics.get('exact_match'))}
        {status_pill('gold_hit', metrics.get('gold_document_hit'))}
        {status_pill('ceiling_hit', trace.get('ceiling_hit'))}
      </div>
      <div class="grid">
        <div><strong>Trace</strong><br>{esc(trace.get('trace_id'))}</div>
        <div><strong>Provider / Model</strong><br>{esc(trace.get('provider_id'))} / {esc(trace.get('model_id'))}</div>
        <div><strong>Searches</strong><br>{esc(trace.get('total_search_calls'))}</div>
        <div><strong>Tokens</strong><br>{esc(trace.get('total_prompt_tokens'))} prompt / {esc(trace.get('total_completion_tokens'))} completion</div>
        <div><strong>Wall Time</strong><br>{esc(trace.get('wall_time_seconds'))} sec</div>
        <div><strong>Cost</strong><br>${esc(trace.get('total_cost_usd'))}</div>
      </div>
    </section>

    <section class="card">
      <h2>Question And Answers</h2>
      <p><strong>Question:</strong> {esc(trace.get('question'))}</p>
      <p><strong>Final response:</strong> {esc(trace.get('final_response'))}</p>
      <p><strong>Extracted final answer:</strong> {esc(trace.get('final_answer'))}</p>
      <p><strong>Gold answer:</strong> {esc(trace.get('gold_answer'))}</p>
      <p><strong>Gold URLs:</strong></p>
      <ul>{gold_urls}</ul>
    </section>

    <section class="card">
      <h2>Metrics</h2>
      <pre class="json">{format_json(metrics)}</pre>
    </section>

    <section class="card">
      <h2>Timeline</h2>
      <table>
        <thead>
          <tr>
            <th>Iteration</th>
            <th>Decision</th>
            <th>Search Query</th>
            <th>Results</th>
            <th>Prompt / Completion</th>
            <th>LLM Latency</th>
          </tr>
        </thead>
        {render_timeline(trace)}
      </table>
    </section>

    {errors_html}

    {iterations}
  </main>
</body>
</html>
"""


def default_output_path(trace: dict[str, Any], output_dir: Path) -> Path:
    safe_trace_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(trace.get("trace_id", "trace")))
    return output_dir / f"{safe_trace_id}.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one JSONL trace as a readable HTML report.")
    parser.add_argument("--input", default="data/traces/phase1_v1_brave_gpt54.jsonl")
    parser.add_argument("--output", help="HTML output path. Defaults to results/trace_views/<trace_id>.html")
    parser.add_argument("--output-dir", default="results/trace_views")
    parser.add_argument("--latest", action="store_true", help="Render the latest matching trace. Defaults to true when no selector is provided.")
    parser.add_argument("--trace-id")
    parser.add_argument("--query-id")
    parser.add_argument("--index", type=int, help="1-indexed match number for selected traces.")
    args = parser.parse_args()

    input_path = Path(args.input)
    latest = args.latest or not (args.trace_id or args.query_id or args.index)
    trace = select_trace(
        input_path,
        latest=latest,
        trace_id=args.trace_id,
        query_id=args.query_id,
        index=args.index,
    )
    output_path = Path(args.output) if args.output else default_output_path(trace, Path(args.output_dir))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(trace, input_path), encoding="utf-8")
    print(f"Wrote trace view to {output_path}")


if __name__ == "__main__":
    main()
