from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from searchapi_eval.agent.prompts import render_liquid, render_search_documents


PROMPT_DIR = Path(__file__).parent / "prompts"
UNSUPPORTED_EXTRACTORS = {
    "binary_unsupported_v1",
    "office_unsupported_v1",
    "pdf_unsupported_v1",
}


def render_document_judge_prompt(
    trace: dict[str, Any],
    retrieval: dict[str, Any],
    result: dict[str, Any],
    *,
    max_extracted_chars: int = 0,
) -> list[dict[str, str]]:
    model_visible_document, truncated = render_model_visible_document(
        trace,
        retrieval,
        result,
        max_extracted_chars=max_extracted_chars,
    )
    context = {
        "question": trace.get("question") or "",
        "gold_answer": trace.get("gold_answer") or "",
        "final_answer": trace.get("final_answer") or "",
        "text_truncated": str(truncated).lower(),
        "model_visible_document": model_visible_document,
    }
    return [
        {"role": "system", "content": "You are a precise JSON-only evaluation judge."},
        {"role": "user", "content": render_liquid(_load_prompt("document_support_judge.liquid"), context)},
    ]


def render_model_visible_document(
    trace: dict[str, Any],
    retrieval: dict[str, Any],
    result: dict[str, Any],
    *,
    max_extracted_chars: int = 0,
) -> tuple[str, bool]:
    """Render one result using the same search-document XML sent to the agent."""
    result_for_judge = deepcopy(result)
    page_fetch = result_for_judge.get("page_fetch") or {}
    extracted_text = page_fetch.get("extracted_text") or ""
    truncated = max_extracted_chars > 0 and len(extracted_text) > max_extracted_chars
    if truncated:
        page_fetch["extracted_text"] = extracted_text[:max_extracted_chars]
        result_for_judge["page_fetch"] = page_fetch

    search_response = retrieval.get("search_response") or {}
    provider_id = trace.get("provider_id") or search_response.get("provider_id") or ""
    rendered = render_search_documents(
        {
            "query": retrieval.get("search_query") or search_response.get("query") or "",
            "provider_id": provider_id,
            "results": [result_for_judge],
        }
    )
    return rendered, truncated


def document_id(trace: dict[str, Any], retrieval: dict[str, Any], result: dict[str, Any]) -> str:
    return f"{trace.get('query_id')}::{trace.get('provider_id')}::{retrieval.get('retrieval_id')}::r{result.get('rank')}"


def deterministic_garbage_precheck(result: dict[str, Any]) -> dict[str, Any]:
    page_fetch = result.get("page_fetch") or {}
    fetch_status = page_fetch.get("fetch_status") or ""
    extractor = page_fetch.get("extractor") or ""
    extracted_chars = int(page_fetch.get("extracted_text_chars") or 0)
    content_type = page_fetch.get("content_type") or ""

    if fetch_status == "failed":
        return {
            "is_garbage": True,
            "category": "fetch_failed",
            "reason": "The page fetch failed, so no usable page content was extracted.",
        }
    if extractor in UNSUPPORTED_EXTRACTORS:
        return {
            "is_garbage": True,
            "category": "unsupported_content",
            "reason": f"The page content type was not extractable by the current fetcher ({extractor}).",
        }
    if fetch_status == "empty" and extracted_chars == 0:
        return {
            "is_garbage": True,
            "category": "empty_extraction",
            "reason": "The fetch completed but produced no extracted text.",
        }
    if fetch_status == "success" and extracted_chars == 0:
        return {
            "is_garbage": True,
            "category": "empty_success",
            "reason": "The fetch was marked successful but extracted zero text characters.",
        }
    if content_type.startswith("image/") or content_type.startswith("audio/") or content_type.startswith("video/"):
        return {
            "is_garbage": True,
            "category": "media_content",
            "reason": f"The fetched content is media rather than text ({content_type}).",
        }
    return {"is_garbage": False, "category": "", "reason": ""}


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty model response content")
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")
