from __future__ import annotations

import copy
import time
from typing import Any

from searchapi_eval.models.base import LLMClient
from searchapi_eval.providers.base import SearchProvider

from .prompts import SEARCH_TOOL, SYSTEM_PROMPT, render_search_documents, render_user_query
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
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_iterations = max_iterations
        self.max_results = max_results
        self.run_id = run_id

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
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_query(query_record["question"])},
        ]

        for iteration_num in range(1, self.max_iterations + 1):
            llm_request = copy.deepcopy(self.model.request_snapshot(messages, [SEARCH_TOOL]))
            try:
                llm_response = await self.model.chat(messages, tools=[SEARCH_TOOL])
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
                "agent_decision": "search" if llm_response.tool_calls else "answer",
                "searches": [],
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
                search_query = str(args.get("query") or query_record["question"])
                if function_name != "search_web":
                    trace["errors"].append(
                        {
                            "iteration_num": iteration_num,
                            "tool_call_id": tool_call.get("id"),
                            "message": f"Unsupported tool call: {function_name}",
                        }
                    )
                    continue

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
                    break
                search_json = search_response.to_json()
                retrieval_record = {
                    "retrieval_id": f"{trace['trace_id']}_it{iteration_num}_search{call_index}",
                    "iteration_num": iteration_num,
                    "tool_call_id": tool_call.get("id"),
                    "search_query": search_query,
                    "search_response": search_json,
                }
                trace["retrievals"].append(retrieval_record)
                iteration["searches"].append(retrieval_record)
                trace["total_search_calls"] += 1

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": render_search_documents(search_json),
                    }
                )

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
