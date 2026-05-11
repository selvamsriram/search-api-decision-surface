from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from searchapi_eval.agent.loop import AgentRunner
from searchapi_eval.agent.trace import append_jsonl
from searchapi_eval.config import load_env_file
from searchapi_eval.models.azure_openai import AzureOpenAIChatClient
from searchapi_eval.providers.brave import BraveSearchProvider
from searchapi_eval.providers.exa import ExaSearchProvider


def load_phase1_queries(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload["queries"]


def existing_query_ids(path: str | Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                ids.add(json.loads(line).get("query_id"))
    return ids


def build_runner(args: argparse.Namespace) -> AgentRunner:
    provider = build_provider(args)
    model = AzureOpenAIChatClient(
        model_id=args.model_id,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        input_price_per_1k_usd=args.input_price_per_1k,
        output_price_per_1k_usd=args.output_price_per_1k,
    )
    return AgentRunner(
        provider=provider,
        model=model,
        max_iterations=args.max_iterations,
        max_results=args.max_results,
        run_id=args.run_id,
    )


def build_provider(args: argparse.Namespace):
    if args.provider == "brave":
        return BraveSearchProvider(
            country=args.brave_country,
            search_lang=args.brave_search_lang,
            ui_lang=args.brave_ui_lang,
            safesearch=args.brave_safesearch,
            cost_per_query_usd=args.search_cost,
        )
    if args.provider == "exa":
        return ExaSearchProvider(
            cost_per_query_usd=args.search_cost,
            search_type=args.exa_search_type,
        )
    raise ValueError(f"Unsupported provider: {args.provider}")


async def run(args: argparse.Namespace) -> None:
    queries = load_phase1_queries(args.queries)
    if args.query_id:
        query_ids = set(args.query_id)
        queries = [query for query in queries if query["query_id"] in query_ids]
    if args.resume:
        completed = existing_query_ids(args.output)
        queries = [query for query in queries if query["query_id"] not in completed]
    if args.limit is not None:
        queries = queries[args.offset : args.offset + args.limit]
    else:
        queries = queries[args.offset :]

    if not queries:
        print("No queries to run.")
        return

    runner = build_runner(args)
    print(f"Running {len(queries)} query/queries -> {args.output}")
    for index, query_record in enumerate(queries, start=1):
        print(f"[{index}/{len(queries)}] {query_record['query_id']}: {query_record['question'][:100]}")
        trace = await runner.run_query(query_record)
        append_jsonl(args.output, trace)
        print(
            f"  answered={trace['answered']} searches={trace['total_search_calls']} "
            f"tokens={trace['total_prompt_tokens'] + trace['total_completion_tokens']} "
            f"cost=${trace['total_cost_usd']:.6f}"
        )


def parser() -> argparse.ArgumentParser:
    default_run_id = "phase1_v1_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cli = argparse.ArgumentParser(description="Run the V1 Brave/Exa + Azure GPT-5.4 agent over selected SealQA queries.")
    cli.add_argument("--queries", default="data/queries/phase1_100.json")
    cli.add_argument("--output", default="data/traces/phase1_v1_brave_gpt54.jsonl")
    cli.add_argument("--run-id", default=os.environ.get("SEARCHAPI_RUN_ID", default_run_id))
    cli.add_argument("--limit", type=int, default=1, help="Number of queries to run. Use 2 for a tiny pilot.")
    cli.add_argument("--offset", type=int, default=0)
    cli.add_argument("--query-id", action="append", help="Run a specific query_id. Can be repeated.")
    cli.add_argument("--resume", action="store_true", help="Skip query_ids already present in the output JSONL.")
    cli.add_argument("--max-iterations", type=int, default=10)
    cli.add_argument("--max-results", type=int, default=10)
    cli.add_argument("--temperature", type=float, default=0.0)
    cli.add_argument("--max-tokens", type=int, default=4096)
    cli.add_argument("--model-id", default="azure:gpt-5.4")
    cli.add_argument("--provider", choices=("brave", "exa"), default=os.environ.get("SEARCH_PROVIDER", "brave"))
    cli.add_argument("--brave-country", default=os.environ.get("BRAVE_SEARCH_COUNTRY", "US"))
    cli.add_argument("--brave-search-lang", default=os.environ.get("BRAVE_SEARCH_LANG", "en"))
    cli.add_argument("--brave-ui-lang", default=os.environ.get("BRAVE_SEARCH_UI_LANG", "en-US"))
    cli.add_argument("--brave-safesearch", default=os.environ.get("BRAVE_SEARCH_SAFESEARCH", "moderate"))
    cli.add_argument("--exa-search-type", default="auto")
    cli.add_argument("--search-cost", type=float, default=float(os.environ.get("SEARCH_COST_PER_QUERY_USD", "0")))
    cli.add_argument("--input-price-per-1k", type=float, default=float(os.environ.get("AZURE_INPUT_PRICE_PER_1K_USD", "0")))
    cli.add_argument("--output-price-per-1k", type=float, default=float(os.environ.get("AZURE_OUTPUT_PRICE_PER_1K_USD", "0")))
    return cli


def main() -> None:
    load_env_file()
    asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
