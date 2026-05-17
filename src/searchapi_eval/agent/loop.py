from __future__ import annotations

import copy
import time
from typing import Any

from searchapi_eval.models.base import LLMClient
from searchapi_eval.page_fetcher import PageFetcher
from searchapi_eval.providers.base import SearchProvider
from searchapi_eval.providers.base import normalize_url, root_domain

from .prompts import FETCH_PAGE_TOOL, SEARCH_TOOL, render_fetched_page, render_search_documents, render_system_prompt, render_user_query
from .trace import extract_final_answer, make_trace, utc_now_iso


def _safe_tool_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    import json

    raw_args = tool_call.get("function", {}).get("arguments") or "{}"
    if isinstance(raw_args, dict):
        return raw_args
    try:
        return json.loads(raw_args)
    except json.JSONDecodeError:
        return {}


class AgentRunner:
    def __init__(
        self,
        provider: SearchProvider,
        model: LLMClient,
        max_iterations: int = 10,
        max_results: int = 10,
        run_id: str = "phase1_v1",
        page_fetcher: PageFetcher | None = None,
        fetch_tool_enabled: bool = False,
        auto_page_fetch: bool | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_iterations = max_iterations
        self.max_results = max_results
        self.run_id = run_id
        self.page_fetcher = page_fetcher
        self.fetch_tool_enabled = fetch_tool_enabled
        self.auto_page_fetch = bool(page_fetcher and page_fetcher.enabled) if auto_page_fetch is None else auto_page_fetch

    async def run_query(self, query_record: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        trace = make_trace(
            query_record=query_record,
            provider_id=self.provider.provider_id,
            model_id=self.model.model_id,
            run_id=self.run_id,
            max_iterations=self.max_iterations,
            max_results=self.max_results,
        )
        trace["config"]["page_fetch_enabled"] = bool(self.auto_page_fetch and self.page_fetcher and self.page_fetcher.enabled)
        trace["config"]["fetch_tool_enabled"] = self.fetch_tool_enabled
        if self.page_fetcher:
            trace["config"]["page_fetch_cache_dir"] = str(self.page_fetcher.cache_dir)
            trace["config"]["page_fetch_max_bytes"] = self.page_fetcher.max_bytes
            trace["config"]["page_fetch_timeout_seconds"] = self.page_fetcher.timeout_seconds
            trace["config"]["page_fetch_backend"] = getattr(self.page_fetcher, "backend", "local")
            trace["config"]["jina_api_key_configured"] = bool(getattr(self.page_fetcher, "jina_api_key", ""))
        tools = [SEARCH_TOOL]
        if self.fetch_tool_enabled:
            tools.append(FETCH_PAGE_TOOL)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": render_system_prompt(fetch_tool_enabled=self.fetch_tool_enabled)},
            {"role": "user", "content": render_user_query(query_record["question"])},
        ]

        for iteration_num in range(1, self.max_iterations + 1):
            llm_request = copy.deepcopy(self.model.request_snapshot(messages, tools))
            try:
                llm_response = await self.model.chat(messages, tools=tools)
            except Exception as error:
                trace["failed"] = True
                trace["failure_stage"] = "llm_chat"
                trace["errors"].append(
                    {
                        "iteration_num": iteration_num,
                        "stage": "llm_chat",
                        "llm_request": llm_request,
                        "message": str(error),
                    }
                )
                break
            trace["total_prompt_tokens"] += llm_response.usage.get("prompt_tokens", 0)
            trace["total_completion_tokens"] += llm_response.usage.get("completion_tokens", 0)

            assistant_message: dict[str, Any] = {"role": "assistant", "content": llm_response.content}
            if llm_response.tool_calls:
                assistant_message["tool_calls"] = llm_response.tool_calls

            iteration: dict[str, Any] = {
                "iteration_num": iteration_num,
                "llm_request": llm_request,
                "llm_response": llm_response.content,
                "llm_tool_calls": llm_response.tool_calls,
                "llm_usage": llm_response.usage,
                "llm_latency_ms": llm_response.latency_ms,
                "agent_decision": _agent_decision(llm_response.tool_calls),
                "searches": [],
                "fetches": [],
            }
            messages.append(assistant_message)

            if not llm_response.tool_calls:
                trace["final_response"] = llm_response.content
                trace["final_answer"], trace["answered"] = extract_final_answer(llm_response.content)
                trace["iterations"].append(iteration)
                break

            for call_index, tool_call in enumerate(llm_response.tool_calls, start=1):
                function_name = tool_call.get("function", {}).get("name")
                args = _safe_tool_args(tool_call)
                if function_name == "search_web":
                    search_query = str(args.get("query") or query_record["question"])
                    handled = await self._handle_search_tool(
                        trace=trace,
                        iteration=iteration,
                        messages=messages,
                        iteration_num=iteration_num,
                        call_index=call_index,
                        tool_call=tool_call,
                        search_query=search_query,
                    )
                    if not handled:
                        break
                    continue
                if function_name == "fetch_page":
                    handled = await self._handle_fetch_tool(
                        trace=trace,
                        iteration=iteration,
                        messages=messages,
                        iteration_num=iteration_num,
                        call_index=call_index,
                        tool_call=tool_call,
                        args=args,
                    )
                    if not handled:
                        break
                    continue

                if function_name != "search_web":
                    trace["errors"].append(
                        {
                            "iteration_num": iteration_num,
                            "tool_call_id": tool_call.get("id"),
                            "message": f"Unsupported tool call: {function_name}",
                        }
                    )
                    continue

            trace["iterations"].append(iteration)
            if trace["failed"]:
                break

        if trace["final_response"] is None:
            trace["ceiling_hit"] = not trace["failed"]
            trace["final_response"] = ""
            trace["final_answer"] = ""
            trace["answered"] = False

        search_cost = trace["total_search_calls"] * self.provider.cost_per_query_usd
        input_cost = trace["total_prompt_tokens"] * self.model.input_price_per_1k_usd / 1000
        output_cost = trace["total_completion_tokens"] * self.model.output_price_per_1k_usd / 1000
        trace["total_cost_usd"] = round(search_cost + input_cost + output_cost, 8)
        trace["ended_at"] = utc_now_iso()
        trace["wall_time_seconds"] = round(time.perf_counter() - started, 3)
        return trace

    async def _handle_search_tool(
        self,
        *,
        trace: dict[str, Any],
        iteration: dict[str, Any],
        messages: list[dict[str, Any]],
        iteration_num: int,
        call_index: int,
        tool_call: dict[str, Any],
        search_query: str,
    ) -> bool:
        try:
            search_response = await self.provider.search(search_query, max_results=self.max_results)
        except Exception as error:
            trace["failed"] = True
            trace["failure_stage"] = "search"
            trace["errors"].append(
                {
                    "iteration_num": iteration_num,
                    "tool_call_id": tool_call.get("id"),
                    "stage": "search",
                    "search_query": search_query,
                    "message": str(error),
                }
            )
            return False

        retrieval_record = {
            "retrieval_id": f"{trace['trace_id']}_it{iteration_num}_search{call_index}",
            "iteration_num": iteration_num,
            "tool_call_id": tool_call.get("id"),
            "search_query": search_query,
            "search_response": search_response.to_json(),
        }
        search_index = len(trace.get("retrievals") or []) + 1
        for result in retrieval_record["search_response"].get("results", []) or []:
            result["document_id"] = _make_document_id(search_index, result.get("rank"))
        if self.auto_page_fetch and self.page_fetcher:
            try:
                page_fetches = await self.page_fetcher.fetch_results(
                    retrieval_record["search_response"],
                    retrieval_record["retrieval_id"],
                )
                for result, page_fetch in zip(
                    retrieval_record["search_response"].get("results", []),
                    page_fetches,
                ):
                    result["page_fetch"] = page_fetch
            except Exception as error:
                trace["errors"].append(
                    {
                        "iteration_num": iteration_num,
                        "tool_call_id": tool_call.get("id"),
                        "stage": "page_fetch",
                        "search_query": search_query,
                        "message": str(error),
                    }
                )
        trace["retrievals"].append(retrieval_record)
        iteration["searches"].append(retrieval_record)
        trace["total_search_calls"] += 1

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": render_search_documents(
                    retrieval_record["search_response"],
                    include_page_fetch=self.auto_page_fetch,
                ),
            }
        )
        return True

    async def _handle_fetch_tool(
        self,
        *,
        trace: dict[str, Any],
        iteration: dict[str, Any],
        messages: list[dict[str, Any]],
        iteration_num: int,
        call_index: int,
        tool_call: dict[str, Any],
        args: dict[str, Any],
    ) -> bool:
        requested_document_id = str(args.get("document_id") or args.get("doc_id") or "").strip()
        requested_url = str(args.get("url") or "").strip()
        fetch_id = f"{trace['trace_id']}_it{iteration_num}_fetch{call_index}"
        if not self.fetch_tool_enabled:
            trace["errors"].append(
                {
                    "iteration_num": iteration_num,
                    "tool_call_id": tool_call.get("id"),
                    "stage": "fetch_page",
                    "document_id": requested_document_id,
                    "url": requested_url,
                    "message": "fetch_page called while fetch tool is disabled.",
                }
            )
            return True
        if not self.page_fetcher:
            trace["failed"] = True
            trace["failure_stage"] = "fetch_page"
            trace["errors"].append(
                {
                    "iteration_num": iteration_num,
                    "tool_call_id": tool_call.get("id"),
                    "stage": "fetch_page",
                    "document_id": requested_document_id,
                    "url": requested_url,
                    "message": "fetch_page requires a page fetcher.",
                }
            )
            return False
        source = _find_seen_result_by_document_id(trace, requested_document_id) if requested_document_id else None
        if not source and requested_url:
            source = _find_seen_result_by_url(trace, requested_url)

        if not source and not requested_url:
            trace["errors"].append(
                {
                    "iteration_num": iteration_num,
                    "tool_call_id": tool_call.get("id"),
                    "stage": "fetch_page",
                    "document_id": requested_document_id,
                    "message": "fetch_page called without a valid document_id.",
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": "<fetched_page><fetch_status>failed</fetch_status><error>Missing or unknown document_id.</error></fetched_page>",
                }
            )
            return True

        source_result = source.get("result") if source else None
        fetch_url = (source_result or {}).get("url") or requested_url
        result_for_fetch = {
            "rank": source.get("rank") if source else None,
            "title": (source_result or {}).get("title") or "",
            "url": fetch_url,
            "snippet": (source_result or {}).get("snippet") or "",
            "domain": (source_result or {}).get("domain") or root_domain(fetch_url),
        }
        search_response_context = {
            "provider_id": trace.get("provider_id"),
            "query": source.get("search_query") if source else "",
            "results": [result_for_fetch],
        }
        try:
            page_fetch = await self._fetch_page(result_for_fetch, search_response_context, fetch_id)
        except Exception as error:
            page_fetch = {
                "schema_version": "page_fetch_summary_v1",
                "fetch_backend": getattr(self.page_fetcher, "backend", "local") if self.page_fetcher else "local",
                "url": fetch_url,
                "normalized_url": normalize_url(fetch_url),
                "final_url": None,
                "artifact_path": None,
                "fetch_status": "failed",
                "http_status": None,
                "content_type": None,
                "truncated_by_max_bytes": False,
                "extractor": None,
                "extracted_text_chars": 0,
                "extracted_text_tokens_estimate": 0,
                "text_sha256": None,
                "fetch_latency_ms": None,
                "error": str(error),
                "extracted_text": "",
            }

        fetch_record = {
            "fetch_id": fetch_id,
            "iteration_num": iteration_num,
            "tool_call_id": tool_call.get("id"),
            "requested_document_id": requested_document_id,
            "url": fetch_url,
            "reason": args.get("reason") or "",
            "seen_in_search_results": bool(source),
            "source_retrieval_id": source.get("retrieval_id") if source else None,
            "source_document_id": (source_result or {}).get("document_id") if source_result else None,
            "source_search_query": source.get("search_query") if source else None,
            "source_rank": source.get("rank") if source else None,
            "source_title": (source_result or {}).get("title") if source_result else "",
            "source_domain": (source_result or {}).get("domain") if source_result else root_domain(fetch_url),
            "source_snippet": (source_result or {}).get("snippet") if source_result else "",
            "page_fetch": page_fetch,
        }
        trace.setdefault("fetches", []).append(fetch_record)
        iteration["fetches"].append(fetch_record)
        trace["total_fetch_calls"] = int(trace.get("total_fetch_calls") or 0) + 1
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": render_fetched_page(
                    page_fetch,
                    url=fetch_url,
                    source={
                        "document_id": fetch_record["source_document_id"],
                        "retrieval_id": fetch_record["source_retrieval_id"],
                        "rank": fetch_record["source_rank"],
                        "title": fetch_record["source_title"],
                        "domain": fetch_record["source_domain"],
                        "snippet": fetch_record["source_snippet"],
                    },
                ),
            }
        )
        return True

    async def _fetch_page(
        self,
        result_for_fetch: dict[str, Any],
        search_response_context: dict[str, Any],
        fetch_id: str,
    ) -> dict[str, Any]:
        assert self.page_fetcher is not None
        if hasattr(self.page_fetcher, "fetch_result_async"):
            return await self.page_fetcher.fetch_result_async(result_for_fetch, search_response_context, fetch_id)
        page_fetches = await self.page_fetcher.fetch_results(search_response_context, fetch_id)
        return page_fetches[0] if page_fetches else {}


def _agent_decision(tool_calls: list[dict[str, Any]]) -> str:
    if not tool_calls:
        return "answer"
    names = {call.get("function", {}).get("name") for call in tool_calls}
    if names == {"search_web"}:
        return "search"
    if names == {"fetch_page"}:
        return "fetch"
    return "tool"


def _make_document_id(search_index: int, rank: Any) -> str:
    return f"s{search_index}r{rank or 'x'}"


def _find_seen_result_by_document_id(trace: dict[str, Any], document_id: str) -> dict[str, Any] | None:
    for retrieval in reversed(trace.get("retrievals") or []):
        for result in retrieval.get("search_response", {}).get("results", []) or []:
            if str(result.get("document_id") or "") == document_id:
                return {
                    "retrieval_id": retrieval.get("retrieval_id"),
                    "search_query": retrieval.get("search_query"),
                    "rank": result.get("rank"),
                    "result": result,
                }
    return None


def _find_seen_result_by_url(trace: dict[str, Any], url: str) -> dict[str, Any] | None:
    normalized = normalize_url(url)
    for retrieval in reversed(trace.get("retrievals") or []):
        for result in retrieval.get("search_response", {}).get("results", []) or []:
            if normalize_url(result.get("url") or "") == normalized:
                return {
                    "retrieval_id": retrieval.get("retrieval_id"),
                    "search_query": retrieval.get("search_query"),
                    "rank": result.get("rank"),
                    "result": result,
                }
    return None
