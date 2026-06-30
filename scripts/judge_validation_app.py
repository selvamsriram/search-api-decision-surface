"""Local dashboard for human validation of Kimi per-URL oracle labels.

Usage:
    python scripts/build_judge_validation_queue.py
    python scripts/judge_validation_app.py

Optional:
    python scripts/judge_validation_app.py --build
    python scripts/judge_validation_app.py --export
    python scripts/judge_validation_app.py --port 8767

Outputs:
    results/task2_judge_validation/judge_validation_progress.json
    results/task2_judge_validation/judge_validation_sample.csv
    results/task2_judge_validation/judge_validation_results.csv
    results/task2_judge_validation/summary.md
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import threading
import time
import webbrowser
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "results" / "task2_judge_validation"
QUEUE_JSON = OUT_DIR / "judge_validation_queue.json"
SAMPLE_CSV = OUT_DIR / "judge_validation_sample.csv"
RESULTS_CSV = OUT_DIR / "judge_validation_results.csv"
PROGRESS_JSON = OUT_DIR / "judge_validation_progress.json"
DASHBOARD = OUT_DIR / "judge_validation_dashboard.html"
SUMMARY_MD = OUT_DIR / "summary.md"

HUMAN_COLUMNS = ["human_value", "human_disagreement_pattern", "human_notes"]
LABELS = ["contains_gold_answer", "contradicts_gold_answer", "is_garbage"]
PROVIDERS = ["brave", "tavily", "firecrawl"]
SURFACES = ["snippet_only", "page_visible"]
KIMI_VALUES = [True, False]
LEAF_QUOTA_TARGET = 5

_lock = threading.Lock()


def load_queue() -> list[dict]:
    return json.loads(QUEUE_JSON.read_text(encoding="utf-8"))["cases"]


def load_meta() -> dict:
    return json.loads(QUEUE_JSON.read_text(encoding="utf-8")).get("meta", {})


def load_progress() -> dict[str, dict]:
    if not PROGRESS_JSON.exists():
        return {}
    try:
        return json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_progress(progress: dict[str, dict]) -> None:
    PROGRESS_JSON.write_text(json.dumps(progress, indent=2, sort_keys=True), encoding="utf-8")


def is_done(labels: dict | None) -> bool:
    return bool((labels or {}).get("human_value"))


def human_bool(value: str | None) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def agreement(case: dict, labels: dict | None) -> bool | None:
    hv = human_bool((labels or {}).get("human_value"))
    if hv is None:
        return None
    return hv is bool(case.get("kimi_value"))


def compute_quota(cases: list[dict], progress: dict[str, dict]) -> dict:
    def reviewed(members: list[dict]) -> int:
        return sum(1 for c in members if is_done(progress.get(c["case_id"])))

    leaf_rows = []
    for provider in PROVIDERS:
        for label in LABELS:
            for surface in SURFACES:
                for kimi_value in KIMI_VALUES:
                    members = [
                        c
                        for c in cases
                        if c["provider_id"] == provider
                        and c["label"] == label
                        and c["surface"] == surface
                        and bool(c["kimi_value"]) is kimi_value
                    ]
                    target = min(LEAF_QUOTA_TARGET, len(members))
                    done = reviewed(members)
                    leaf_rows.append(
                        {
                            "provider": provider,
                            "label": label,
                            "surface": surface,
                            "kimi_value": kimi_value,
                            "sampled": len(members),
                            "target": target,
                            "reviewed": done,
                            "remaining": max(0, target - done),
                            "complete": done >= target,
                        }
                    )

    core_rows = []
    for label in LABELS:
        for surface in SURFACES:
            for kimi_value in KIMI_VALUES:
                leaves = [
                    r
                    for r in leaf_rows
                    if r["label"] == label and r["surface"] == surface and r["kimi_value"] is kimi_value
                ]
                target = sum(r["target"] for r in leaves)
                done = sum(r["reviewed"] for r in leaves)
                core_rows.append(
                    {
                        "label": label,
                        "surface": surface,
                        "kimi_value": kimi_value,
                        "sampled": sum(r["sampled"] for r in leaves),
                        "target": target,
                        "reviewed": done,
                        "remaining": max(0, target - done),
                        "complete": done >= target,
                    }
                )

    target_total = sum(r["target"] for r in leaf_rows)
    reviewed_to_quota = sum(min(r["reviewed"], r["target"]) for r in leaf_rows)
    remaining_total = sum(r["remaining"] for r in leaf_rows)
    leaf_complete = sum(1 for r in leaf_rows if r["complete"])
    core_complete = sum(1 for r in core_rows if r["complete"])
    return {
        "leaf_target": LEAF_QUOTA_TARGET,
        "target_total": target_total,
        "reviewed_to_quota": reviewed_to_quota,
        "remaining_total": remaining_total,
        "pct": "" if target_total == 0 else f"{reviewed_to_quota / target_total:.0%}",
        "leaf_complete": leaf_complete,
        "leaf_total": len(leaf_rows),
        "core_complete": core_complete,
        "core_total": len(core_rows),
        "core_rows": core_rows,
        "leaf_rows": leaf_rows,
    }


def compute_summary(cases: list[dict], progress: dict[str, dict]) -> dict:
    rows = []
    by_label = defaultdict(list)
    by_provider = defaultdict(list)
    by_surface = defaultdict(list)
    for c in cases:
        by_label[c["label"]].append(c)
        by_provider[c["provider_id"]].append(c)
        by_surface[c["surface"]].append(c)

    def summarize_group(name: str, members: list[dict]) -> dict:
        reviewed = [c for c in members if is_done(progress.get(c["case_id"]))]
        clear = [c for c in reviewed if human_bool(progress.get(c["case_id"], {}).get("human_value")) is not None]
        agree = [c for c in clear if agreement(c, progress.get(c["case_id"]))]
        disagree = [c for c in clear if agreement(c, progress.get(c["case_id"])) is False]
        patterns = Counter(
            (progress.get(c["case_id"], {}).get("human_disagreement_pattern") or "unspecified")
            for c in disagree
        )
        top_pattern = patterns.most_common(1)[0][0] if patterns else ""
        rate = (len(agree) / len(clear)) if clear else None
        return {
            "name": name,
            "sampled": len(members),
            "reviewed": len(reviewed),
            "clear": len(clear),
            "unclear": len(reviewed) - len(clear),
            "agree": len(agree),
            "disagree": len(disagree),
            "agreement_rate": rate,
            "agreement_pct": "" if rate is None else f"{rate:.0%}",
            "top_disagreement_pattern": top_pattern,
        }

    for label in LABELS:
        rows.append({"kind": "label", **summarize_group(label, by_label[label])})
    provider_rows = [{"kind": "provider", **summarize_group(provider, by_provider[provider])} for provider in PROVIDERS]
    surface_rows = [{"kind": "surface", **summarize_group(surface, by_surface[surface])} for surface in SURFACES]
    reviewed_total = sum(1 for c in cases if is_done(progress.get(c["case_id"])))
    clear_total = sum(
        1 for c in cases if human_bool(progress.get(c["case_id"], {}).get("human_value")) is not None
    )
    agree_total = sum(1 for c in cases if agreement(c, progress.get(c["case_id"])) is True)
    return {
        "total_cases": len(cases),
        "reviewed": reviewed_total,
        "clear": clear_total,
        "agree": agree_total,
        "agreement_pct": "" if clear_total == 0 else f"{agree_total / clear_total:.0%}",
        "label_rows": rows,
        "provider_rows": provider_rows,
        "surface_rows": surface_rows,
        "quota": compute_quota(cases, progress),
    }


def sync_csv(cases: list[dict], progress: dict[str, dict]) -> None:
    sample_rows_by_id = {}
    fieldnames = []
    if SAMPLE_CSV.exists():
        with SAMPLE_CSV.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = list(reader.fieldnames or [])
            sample_rows_by_id = {r.get("case_id", ""): r for r in reader}
    if not fieldnames:
        fieldnames = [
            "case_id",
            "provider_id",
            "query_id",
            "surface",
            "label",
            "kimi_value",
            "rank",
            "title",
            "url",
            "domain",
            "question",
            "gold_answer",
            "model_final_answer",
        ] + HUMAN_COLUMNS
    for col in HUMAN_COLUMNS + ["human_agrees_with_kimi", "reviewed_at"]:
        if col not in fieldnames:
            fieldnames.append(col)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for c in cases:
            row = sample_rows_by_id.get(c["case_id"], {}).copy()
            if not row:
                row = {k: c.get(k, "") for k in fieldnames}
            labels = progress.get(c["case_id"], {})
            for k in HUMAN_COLUMNS:
                row[k] = labels.get(k, "")
            ag = agreement(c, labels)
            row["human_agrees_with_kimi"] = "" if ag is None else str(ag).lower()
            row["reviewed_at"] = labels.get("updated_at", "")
            writer.writerow(row)


def write_summary(cases: list[dict], progress: dict[str, dict]) -> dict:
    summary = compute_summary(cases, progress)
    lines = [
        "# Task 2 judge-validation summary",
        "",
        "_Human validation of sampled Kimi per-URL oracle labels. Auto-generated by `scripts/judge_validation_app.py`._",
        "",
        f"Progress: **{summary['reviewed']} / {summary['total_cases']}** cases reviewed.",
        "Quota: **"
        + f"{summary['quota']['reviewed_to_quota']} / {summary['quota']['target_total']}** "
        + "provider-balanced cases reviewed "
        + (f"({summary['quota']['pct']})" if summary["quota"]["pct"] else "")
        + f"; **{summary['quota']['remaining_total']}** remaining.",
        f"Quota slices complete: **{summary['quota']['core_complete']} / {summary['quota']['core_total']}** core slices; "
        f"**{summary['quota']['leaf_complete']} / {summary['quota']['leaf_total']}** provider leaf slices.",
        f"Clear-label agreement: **{summary['agree']} / {summary['clear']}**"
        + (f" ({summary['agreement_pct']})" if summary["agreement_pct"] else "")
        + ".",
        "",
        "## Quota progress",
        "",
        f"Quota target: `{LEAF_QUOTA_TARGET}` reviewed cases per provider × label × surface × Kimi-value leaf slice.",
        "",
        "| Label | Surface | Kimi value | Target | Reviewed | Remaining |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in summary["quota"]["core_rows"]:
        lines.append(
            f"| `{row['label']}` | `{row['surface']}` | `{str(row['kimi_value']).lower()}` | "
            f"{row['target']} | {row['reviewed']} | {row['remaining']} |"
        )
    lines += [
        "",
        "### Provider leaf slices",
        "",
        "| Provider | Label | Surface | Kimi value | Target | Reviewed | Remaining |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary["quota"]["leaf_rows"]:
        lines.append(
            f"| {row['provider']} | `{row['label']}` | `{row['surface']}` | `{str(row['kimi_value']).lower()}` | "
            f"{row['target']} | {row['reviewed']} | {row['remaining']} |"
        )
    lines += [
        "",
        "## Label agreement",
        "",
        "| Label | Sampled | Reviewed | Clear | Unclear | Agree | Disagree | Agreement | Main disagreement pattern |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["label_rows"]:
        lines.append(
            f"| `{row['name']}` | {row['sampled']} | {row['reviewed']} | {row['clear']} | {row['unclear']} | "
            f"{row['agree']} | {row['disagree']} | {row['agreement_pct'] or ''} | "
            f"{row['top_disagreement_pattern']} |"
        )
    lines += [
        "",
        "## Provider agreement",
        "",
        "| Provider | Sampled | Reviewed | Clear | Agree | Disagree | Agreement |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["provider_rows"]:
        lines.append(
            f"| {row['name']} | {row['sampled']} | {row['reviewed']} | {row['clear']} | "
            f"{row['agree']} | {row['disagree']} | {row['agreement_pct'] or ''} |"
        )
    lines += [
        "",
        "## Surface agreement",
        "",
        "| Surface | Sampled | Reviewed | Clear | Agree | Disagree | Agreement |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["surface_rows"]:
        lines.append(
            f"| `{row['name']}` | {row['sampled']} | {row['reviewed']} | {row['clear']} | "
            f"{row['agree']} | {row['disagree']} | {row['agreement_pct'] or ''} |"
        )
    lines += [
        "",
        "A case is clear when the human value is `true` or `false`; `unclear` cases are counted as reviewed but excluded from the agreement denominator.",
        "",
    ]
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    return summary


def regenerate_all() -> dict:
    cases = load_queue()
    progress = load_progress()
    sync_csv(cases, progress)
    return write_summary(cases, progress)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode("utf-8")
        elif isinstance(body, bytes):
            payload = body
        else:
            payload = str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, DASHBOARD.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path == "/api/queue":
            with _lock:
                cases = load_queue()
                progress = load_progress()
                summary = compute_summary(cases, progress)
                meta = load_meta()
            return self._send(200, {"cases": cases, "progress": progress, "summary": summary, "meta": meta})
        if path == "/api/summary":
            with _lock:
                return self._send(200, compute_summary(load_queue(), load_progress()))
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0")) or b"{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        if path == "/api/save":
            case_id = data.get("case_id")
            if not case_id:
                return self._send(400, {"error": "missing case_id"})
            labels = data.get("labels") or {}
            clean = {k: labels.get(k, "") for k in HUMAN_COLUMNS}
            clean["updated_at"] = int(time.time())
            with _lock:
                progress = load_progress()
                progress[case_id] = clean
                save_progress(progress)
                cases = load_queue()
                sync_csv(cases, progress)
                summary = write_summary(cases, progress)
            return self._send(200, {"ok": True, "progress": progress, "summary": summary})
        if path == "/api/export":
            with _lock:
                summary = regenerate_all()
            return self._send(
                200,
                {
                    "ok": True,
                    "summary": summary,
                    "written": [
                        str(SAMPLE_CSV.relative_to(ROOT)),
                        str(RESULTS_CSV.relative_to(ROOT)),
                        str(PROGRESS_JSON.relative_to(ROOT)),
                        str(SUMMARY_MD.relative_to(ROOT)),
                    ],
                },
            )
        return self._send(404, {"error": "not found"})


def run_builder() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/build_judge_validation_queue.py")], check=True)


def serve(port: int) -> None:
    if not QUEUE_JSON.exists():
        run_builder()
    if not DASHBOARD.exists():
        raise SystemExit(f"Dashboard missing: {DASHBOARD.relative_to(ROOT)}")
    if PROGRESS_JSON.exists():
        backup = OUT_DIR / ("judge_validation_progress.backup-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
        backup.write_text(PROGRESS_JSON.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  backup: {backup.relative_to(ROOT)}")
    regenerate_all()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Judge-validation dashboard -> {url}")
    print(f"  queue:    {QUEUE_JSON.relative_to(ROOT)}")
    print(f"  progress: {PROGRESS_JSON.relative_to(ROOT)}")
    print(f"  summary:  {SUMMARY_MD.relative_to(ROOT)}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Progress saved.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--build", action="store_true", help="rebuild the sampled validation queue before serving")
    parser.add_argument("--export", action="store_true", help="regenerate CSV/summary from current progress and exit")
    args = parser.parse_args()
    if args.build or not QUEUE_JSON.exists():
        run_builder()
    if args.export:
        summary = regenerate_all()
        print(f"Exported {summary['reviewed']}/{summary['total_cases']} reviewed cases.")
        print(f"Wrote {RESULTS_CSV.relative_to(ROOT)} and {SUMMARY_MD.relative_to(ROOT)}")
        return
    serve(args.port)


if __name__ == "__main__":
    main()
