#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from searchapi_eval.evaluation.metrics import compute_trace_metrics


DEFAULT_TRACE_DIR = "data/traces"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            trace = json.loads(line)
            trace["_jsonl_line_num"] = line_num
            yield trace


def compact_trace(trace: dict[str, Any]) -> dict[str, Any]:
    try:
        metrics = compute_trace_metrics(trace)
    except Exception as error:
        metrics = {"metric_error": str(error)}
    return {
        "line": trace.get("_jsonl_line_num"),
        "trace_id": trace.get("trace_id"),
        "run_id": trace.get("run_id"),
        "query_id": trace.get("query_id"),
        "question": trace.get("question"),
        "provider_id": trace.get("provider_id"),
        "model_id": trace.get("model_id"),
        "final_answer": trace.get("final_answer"),
        "gold_answer": trace.get("gold_answer"),
        "answered": trace.get("answered"),
        "failed": trace.get("failed"),
        "failure_stage": trace.get("failure_stage"),
        "exact_match": metrics.get("exact_match"),
        "gold_document_hit": metrics.get("gold_document_hit"),
        "failure_mode": metrics.get("failure_mode"),
        "total_search_calls": trace.get("total_search_calls"),
        "total_tokens": (trace.get("total_prompt_tokens") or 0) + (trace.get("total_completion_tokens") or 0),
        "started_at": trace.get("started_at"),
        "ended_at": trace.get("ended_at"),
        "metadata": trace.get("metadata", {}),
    }


class TraceStore:
    def __init__(self, trace_dir: Path) -> None:
        self.trace_dir = trace_dir.resolve()

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for path in sorted(self.trace_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        return files

    def resolve_file(self, name: str) -> Path:
        candidate = (self.trace_dir / name).resolve()
        if candidate.parent != self.trace_dir or candidate.suffix != ".jsonl":
            raise ValueError("Trace file must be a JSONL file inside the configured trace directory.")
        if not candidate.exists():
            raise FileNotFoundError(candidate.name)
        return candidate

    def list_traces(self, file_name: str, page: int, page_size: int, query: str = "") -> dict[str, Any]:
        path = self.resolve_file(file_name)
        page = max(page, 1)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size
        query_lower = query.strip().lower()
        rows: list[dict[str, Any]] = []
        matched = 0
        has_more = False

        for trace in iter_jsonl(path):
            summary = compact_trace(trace)
            haystack = " ".join(
                str(summary.get(key) or "")
                for key in ("trace_id", "run_id", "query_id", "question", "final_answer", "gold_answer", "provider_id")
            ).lower()
            if query_lower and query_lower not in haystack:
                continue
            if matched < offset:
                matched += 1
                continue
            if len(rows) >= page_size:
                has_more = True
                break
            rows.append(summary)
            matched += 1

        return {
            "file": file_name,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
            "rows": rows,
        }

    def get_trace(self, file_name: str, line: int) -> dict[str, Any]:
        path = self.resolve_file(file_name)
        if line < 1:
            raise ValueError("Line must be >= 1.")
        for trace in iter_jsonl(path):
            if trace.get("_jsonl_line_num") == line:
                trace["metrics"] = compute_trace_metrics(trace)
                return trace
        raise FileNotFoundError(f"No trace at line {line} in {file_name}")


class DashboardHandler(BaseHTTPRequestHandler):
    store: TraceStore

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_html(INDEX_HTML)
            elif parsed.path == "/api/files":
                self.send_json({"files": self.store.list_files()})
            elif parsed.path == "/api/traces":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                page = int(params.get("page", ["1"])[0])
                page_size = int(params.get("page_size", ["50"])[0])
                query = params.get("q", [""])[0]
                self.send_json(self.store.list_traces(file_name, page, page_size, query))
            elif parsed.path == "/api/trace":
                params = parse_qs(parsed.query)
                file_name = required_param(params, "file")
                line = int(required_param(params, "line"))
                self.send_json(self.store.get_trace(file_name, line))
            elif parsed.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as error:
            self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def send_html(self, html_text: str) -> None:
        payload = html_text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def required_param(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key)
    if not values or not values[0]:
        raise ValueError(f"Missing required parameter: {key}")
    return values[0]


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SearchAPI Trace Dashboard</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-2: #f9fafb;
      --ink: #17202a;
      --muted: #667789;
      --line: #d7dee6;
      --line-strong: #bdc8d3;
      --brand: #255c99;
      --brand-soft: #e9f1fb;
      --green: #16704a;
      --green-soft: #e8f5ef;
      --red: #a33939;
      --red-soft: #faecec;
      --amber: #8a6416;
      --amber-soft: #fff5dc;
      --violet: #7259a5;
      --teal: #277866;
      --shadow: 0 1px 2px rgba(21, 34, 48, .06), 0 8px 24px rgba(21, 34, 48, .06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.42;
    }
    button, input, select {
      font: inherit;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
    }
    aside {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      border-right: 1px solid var(--line);
      background: #fbfcfd;
      padding: 18px;
    }
    main {
      min-width: 0;
      padding: 22px;
    }
    .brand {
      margin-bottom: 18px;
    }
    .brand h1 {
      font-size: 19px;
      margin: 0;
      letter-spacing: 0;
    }
    .brand p {
      color: var(--muted);
      margin: 4px 0 0;
      font-size: 13px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .sidebar-section {
      margin-bottom: 16px;
    }
    .sidebar-section h2 {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      margin: 0 0 8px;
    }
    .file-list {
      display: grid;
      gap: 8px;
    }
    .file-card {
      width: 100%;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 10px;
      text-align: left;
      cursor: pointer;
    }
    .file-card:hover, .file-card.active {
      border-color: var(--brand);
      background: var(--brand-soft);
    }
    .file-name {
      font-weight: 700;
      word-break: break-word;
      font-size: 13px;
    }
    .file-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }
    .controls {
      display: grid;
      gap: 8px;
    }
    .controls input, .controls select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 9px 10px;
    }
    .button-row {
      display: flex;
      gap: 8px;
    }
    .btn {
      border: 1px solid var(--line-strong);
      background: var(--surface);
      border-radius: 8px;
      padding: 8px 10px;
      cursor: pointer;
      color: var(--ink);
    }
    .btn:hover {
      border-color: var(--brand);
      color: var(--brand);
    }
    .btn.primary {
      background: var(--brand);
      border-color: var(--brand);
      color: white;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 16px;
    }
    .topbar h2 {
      margin: 0;
      font-size: 22px;
    }
    .topbar p {
      margin: 4px 0 0;
      color: var(--muted);
    }
    .trace-grid {
      display: grid;
      grid-template-columns: minmax(360px, 430px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .row-list {
      max-height: calc(100vh - 170px);
      overflow: auto;
      display: grid;
      gap: 8px;
      padding: 10px;
    }
    .trace-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 10px;
      cursor: pointer;
    }
    .trace-row:hover, .trace-row.active {
      border-color: var(--brand);
      background: var(--brand-soft);
    }
    .trace-row-title {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      font-size: 13px;
      font-weight: 700;
    }
    .question {
      margin: 7px 0;
      font-size: 13px;
    }
    .tiny {
      color: var(--muted);
      font-size: 12px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      margin: 2px 4px 2px 0;
      font-size: 12px;
      white-space: nowrap;
      background: var(--surface-2);
    }
    .pill.good { color: var(--green); background: var(--green-soft); border-color: #badfcc; }
    .pill.bad { color: var(--red); background: var(--red-soft); border-color: #edc3c3; }
    .pill.warn { color: var(--amber); background: var(--amber-soft); border-color: #ecd89d; }
    .detail {
      min-width: 0;
    }
    .hero {
      padding: 16px;
      margin-bottom: 14px;
    }
    .hero h2 {
      margin: 0 0 8px;
      font-size: 20px;
    }
    .hero .answer {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .answer-box {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: var(--surface-2);
    }
    .answer-box label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: 4px;
    }
    .metrics {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 12px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--line);
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }
    th {
      color: var(--muted);
      background: var(--surface-2);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .section {
      margin-bottom: 14px;
    }
    .section h3 {
      font-size: 15px;
      margin: 0 0 8px;
    }
    details.block {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      margin-bottom: 10px;
      overflow: hidden;
    }
    details.block > summary {
      padding: 11px 12px;
      cursor: pointer;
      font-weight: 750;
      background: var(--surface-2);
    }
    .iteration-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .message {
      margin: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface);
    }
    .message summary {
      padding: 9px 10px;
      cursor: pointer;
      font-weight: 650;
      font-size: 13px;
      border-left: 4px solid var(--line-strong);
    }
    .message.system summary { border-left-color: #5f7286; }
    .message.user summary { border-left-color: var(--brand); }
    .message.assistant summary { border-left-color: var(--violet); }
    .message.tool summary { border-left-color: var(--teal); }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 12px;
      background: #111923;
      color: #e9eef5;
      font-size: 12px;
      line-height: 1.45;
      max-height: 520px;
      overflow: auto;
    }
    .json {
      margin: 10px;
      border-radius: 8px;
    }
    .result {
      display: grid;
      grid-template-columns: 42px 1fr;
      gap: 10px;
      padding: 11px 12px;
      border-top: 1px solid var(--line);
    }
    .result h4 {
      margin: 0 0 4px;
      font-size: 14px;
    }
    .result a {
      color: var(--brand);
      word-break: break-all;
      font-size: 13px;
    }
    .result p {
      margin: 7px 0 0;
      font-size: 13px;
    }
    .raw-response {
      margin: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface);
    }
    .raw-response summary {
      cursor: pointer;
      padding: 9px 10px;
      background: var(--surface-2);
      font-weight: 700;
    }
    .rank {
      color: var(--muted);
      font-weight: 800;
    }
    .empty {
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      padding: 24px;
      text-align: center;
      color: var(--muted);
      background: var(--surface);
    }
    .error {
      padding: 10px;
      background: var(--red-soft);
      color: var(--red);
      border: 1px solid #edc3c3;
      border-radius: 8px;
      margin-bottom: 10px;
    }
    @media (max-width: 1050px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      .trace-grid { grid-template-columns: 1fr; }
      .row-list { max-height: none; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <h1>Trace Dashboard</h1>
        <p>Browse JSONL traces from the local trace directory.</p>
      </div>
      <div class="sidebar-section">
        <h2>Trace Files</h2>
        <div id="fileList" class="file-list"></div>
      </div>
      <div class="sidebar-section">
        <h2>Row Filters</h2>
        <div class="controls">
          <input id="rowSearch" placeholder="Search query id, answer, question">
          <select id="pageSize">
            <option value="25">25 rows</option>
            <option value="50" selected>50 rows</option>
            <option value="100">100 rows</option>
            <option value="200">200 rows</option>
          </select>
          <div class="button-row">
            <button id="prevPage" class="btn">Previous</button>
            <button id="nextPage" class="btn">Next</button>
          </div>
          <button id="refresh" class="btn primary">Refresh</button>
        </div>
      </div>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h2 id="currentFile">Select a trace file</h2>
          <p id="pageInfo">Files auto-load from <code>data/traces</code>.</p>
        </div>
      </div>
      <div id="errorBox"></div>
      <div class="trace-grid">
        <section class="panel">
          <div id="rowList" class="row-list">
            <div class="empty">Choose a JSONL file to inspect traces.</div>
          </div>
        </section>
        <section id="traceDetail" class="detail">
          <div class="empty">Select one row to render the full trace.</div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const state = {
      files: [],
      selectedFile: null,
      selectedLine: null,
      page: 1,
      pageSize: 50,
      query: ''
    };

    const $ = (id) => document.getElementById(id);
    const fmtBytes = (bytes) => {
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    };
    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
    const short = (value, n = 180) => {
      const text = String(value ?? '').replace(/\s+/g, ' ').trim();
      return text.length <= n ? text : `${text.slice(0, n - 1).trim()}…`;
    };
    const pill = (label, value) => {
      let klass = 'pill';
      if (value === true) klass += ' good';
      else if (value === false) klass += ' bad';
      else if (value) klass += ' warn';
      return `<span class="${klass}">${esc(label)}: <strong>${esc(value)}</strong></span>`;
    };
    const api = async (path) => {
      const response = await fetch(path);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    };
    const showError = (error) => {
      $('errorBox').innerHTML = error ? `<div class="error">${esc(error.message || error)}</div>` : '';
    };

    async function loadFiles() {
      showError(null);
      const data = await api('/api/files');
      state.files = data.files;
      $('fileList').innerHTML = data.files.length ? data.files.map(file => `
        <button class="file-card ${file.name === state.selectedFile ? 'active' : ''}" data-file="${esc(file.name)}">
          <div class="file-name">${esc(file.name)}</div>
          <div class="file-meta">${fmtBytes(file.size_bytes)} · modified ${esc(file.modified_at)}</div>
        </button>
      `).join('') : '<div class="empty">No JSONL files found.</div>';
      document.querySelectorAll('.file-card').forEach(button => {
        button.addEventListener('click', () => selectFile(button.dataset.file));
      });
      if (!state.selectedFile && data.files.length) {
        await selectFile(data.files[0].name);
      }
    }

    async function selectFile(name) {
      state.selectedFile = name;
      state.selectedLine = null;
      state.page = 1;
      $('currentFile').textContent = name;
      $('traceDetail').innerHTML = '<div class="empty">Select one row to render the full trace.</div>';
      await loadFiles();
      await loadRows();
    }

    async function loadRows() {
      if (!state.selectedFile) return;
      showError(null);
      state.pageSize = Number($('pageSize').value);
      state.query = $('rowSearch').value.trim();
      const params = new URLSearchParams({
        file: state.selectedFile,
        page: String(state.page),
        page_size: String(state.pageSize),
        q: state.query
      });
      const data = await api(`/api/traces?${params}`);
      $('pageInfo').textContent = `Page ${data.page} · ${data.rows.length} row(s)${data.has_more ? ' · more available' : ''}`;
      $('prevPage').disabled = state.page <= 1;
      $('nextPage').disabled = !data.has_more;
      $('rowList').innerHTML = data.rows.length ? data.rows.map(renderRow).join('') : '<div class="empty">No matching traces on this page.</div>';
      document.querySelectorAll('.trace-row').forEach(row => {
        row.addEventListener('click', () => loadTrace(Number(row.dataset.line)));
      });
    }

    function renderRow(row) {
      const active = row.line === state.selectedLine ? 'active' : '';
      return `
        <article class="trace-row ${active}" data-line="${esc(row.line)}">
          <div class="trace-row-title">
            <span>${esc(row.query_id || row.trace_id)}</span>
            <span class="tiny">line ${esc(row.line)}</span>
          </div>
          <div class="question">${esc(short(row.question, 210))}</div>
          <div>
            ${pill('answered', row.answered)}
            ${pill('match', row.exact_match)}
            ${pill('gold hit', row.gold_document_hit)}
            ${row.failed ? pill('failed', row.failed) : ''}
          </div>
          <div class="tiny">
            ${esc(row.provider_id)} · searches ${esc(row.total_search_calls)} · tokens ${esc(row.total_tokens)}
          </div>
          <div class="tiny">final: ${esc(short(row.final_answer, 120))}</div>
        </article>
      `;
    }

    async function loadTrace(line) {
      state.selectedLine = line;
      document.querySelectorAll('.trace-row').forEach(row => row.classList.toggle('active', Number(row.dataset.line) === line));
      const params = new URLSearchParams({ file: state.selectedFile, line: String(line) });
      const trace = await api(`/api/trace?${params}`);
      renderTrace(trace);
    }

    function renderTrace(trace) {
      const metrics = trace.metrics || {};
      $('traceDetail').innerHTML = `
        <section class="panel hero">
          <h2>${esc(trace.query_id || trace.trace_id)}</h2>
          <div class="tiny">${esc(trace.trace_id)} · ${esc(trace.provider_id)} / ${esc(trace.model_id)} · line ${esc(trace._jsonl_line_num)}</div>
          <p>${esc(trace.question)}</p>
          <div class="metrics">
            ${pill('failed', trace.failed)}
            ${pill('answered', trace.answered)}
            ${pill('exact match', metrics.exact_match)}
            ${pill('gold hit', metrics.gold_document_hit)}
            ${pill('ceiling', trace.ceiling_hit)}
          </div>
          <div class="answer">
            <div class="answer-box"><label>Final</label>${esc(trace.final_answer || '—')}</div>
            <div class="answer-box"><label>Gold</label>${esc(trace.gold_answer || '—')}</div>
            <div class="answer-box"><label>Searches</label>${esc(trace.total_search_calls || 0)}</div>
            <div class="answer-box"><label>Tokens</label>${esc((trace.total_prompt_tokens || 0) + (trace.total_completion_tokens || 0))}</div>
          </div>
        </section>
        <section class="section">
          <h3>Timeline</h3>
          ${renderTimeline(trace)}
        </section>
        <section class="section">
          <h3>Metrics</h3>
          <pre>${esc(JSON.stringify(metrics, null, 2))}</pre>
        </section>
        <section class="section">
          <h3>Gold URLs</h3>
          ${(trace.gold_urls || []).map(url => `<div><a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a></div>`).join('') || '<div class="tiny">No gold URLs.</div>'}
        </section>
        <section class="section">
          <h3>Iterations</h3>
          ${(trace.iterations || []).map(renderIteration).join('')}
        </section>
      `;
    }

    function renderTimeline(trace) {
      const rows = (trace.iterations || []).map(iteration => {
        const queries = (iteration.searches || []).map(search => esc(short(search.search_query, 130))).join('<br>') || '<span class="tiny">none</span>';
        const resultCount = (iteration.searches || []).reduce((sum, search) => sum + (((search.search_response || {}).results || []).length), 0);
        const usage = iteration.llm_usage || {};
        return `
          <tr>
            <td>${esc(iteration.iteration_num)}</td>
            <td>${esc(iteration.agent_decision)}</td>
            <td>${queries}</td>
            <td>${resultCount}</td>
            <td>${esc(usage.prompt_tokens || 0)} / ${esc(usage.completion_tokens || 0)}</td>
            <td>${Math.round(iteration.llm_latency_ms || 0)} ms</td>
          </tr>
        `;
      }).join('');
      return `<table><thead><tr><th>Iter</th><th>Decision</th><th>Search Query</th><th>Results</th><th>Tokens</th><th>Latency</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    function renderIteration(iteration) {
      const request = iteration.llm_request || {};
      const config = {};
      ['provider', 'model_id', 'endpoint', 'deployment', 'api_version', 'temperature', 'max_tokens_field', 'max_tokens', 'tool_choice'].forEach(key => {
        if (key in request) config[key] = request[key];
      });
      const messages = (request.messages || []).map((message, index) => renderMessage(message, index)).join('');
      const searches = (iteration.searches || []).map(renderSearch).join('') || '<div class="tiny" style="padding: 10px;">No search calls after this response.</div>';
      const toolCalls = iteration.llm_tool_calls || [];
      return `
        <details class="block" open>
          <summary>
            <div class="iteration-head">
              <span>Iteration ${esc(iteration.iteration_num)} · ${esc(iteration.agent_decision)}</span>
              <span class="tiny">${Math.round(iteration.llm_latency_ms || 0)} ms</span>
            </div>
          </summary>
          <details class="message" open>
            <summary>LLM request snapshot · ${(request.messages || []).length} messages</summary>
            <pre>${esc(JSON.stringify(config, null, 2))}</pre>
            ${messages}
          </details>
          <details class="message" open>
            <summary>LLM response · ${toolCalls.length} tool call(s)</summary>
            <pre>${esc(iteration.llm_response || 'No assistant text content.')}</pre>
            <pre>${esc(JSON.stringify(toolCalls, null, 2))}</pre>
          </details>
          <details class="message" open>
            <summary>Searches performed after this response</summary>
            ${searches}
          </details>
        </details>
      `;
    }

    function renderMessage(message, index) {
      const content = message.content || '';
      const toolCalls = message.tool_calls || [];
      return `
        <details class="message ${esc(message.role || '')}">
          <summary>message ${index} · role=${esc(message.role)} · ${content.length.toLocaleString()} chars ${toolCalls.length ? `· ${toolCalls.length} tool call(s)` : ''}</summary>
          ${content ? `<pre>${esc(content)}</pre>` : '<div class="tiny" style="padding: 10px;">No text content.</div>'}
          ${toolCalls.length ? `<pre>${esc(JSON.stringify(toolCalls, null, 2))}</pre>` : ''}
        </details>
      `;
    }

    function renderSearch(search) {
      const response = search.search_response || {};
      const results = response.results || [];
      return `
        <details class="block" open>
          <summary>${esc(short(search.search_query, 160))} · ${results.length} results · ${Math.round(response.latency_ms || 0)} ms</summary>
          ${results.map(renderResult).join('') || '<div class="tiny" style="padding: 10px;">No results.</div>'}
          <details class="raw-response">
            <summary>Full raw provider response</summary>
            <pre>${esc(JSON.stringify(response.raw_response || {}, null, 2))}</pre>
          </details>
        </details>
      `;
    }

    function renderResult(result) {
      const metadata = result.provider_metadata || {};
      const extra = metadata.extra_snippets || [];
      return `
        <article class="result">
          <div class="rank">#${esc(result.rank)}</div>
          <div>
            <h4>${esc(result.title)}</h4>
            <a href="${esc(result.url)}" target="_blank" rel="noreferrer">${esc(result.url)}</a>
            <div class="tiny">${esc(result.domain || '')}</div>
            <p>${esc(result.snippet || '')}</p>
            ${extra.length ? `<details><summary class="tiny">extra snippets (${extra.length})</summary><ul>${extra.slice(0, 4).map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
          </div>
        </article>
      `;
    }

    let searchTimer = null;
    $('rowSearch').addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.page = 1; loadRows().catch(showError); }, 180);
    });
    $('pageSize').addEventListener('change', () => { state.page = 1; loadRows().catch(showError); });
    $('prevPage').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadRows().catch(showError); } });
    $('nextPage').addEventListener('click', () => { state.page += 1; loadRows().catch(showError); });
    $('refresh').addEventListener('click', () => loadFiles().catch(showError));

    loadFiles().catch(showError);
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the live SearchAPI trace dashboard.")
    parser.add_argument("--trace-dir", default=DEFAULT_TRACE_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    trace_dir = Path(args.trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)

    handler = DashboardHandler
    handler.store = TraceStore(trace_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Trace dashboard serving {trace_dir.resolve()} at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping trace dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
