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
from searchapi_eval.page_fetcher import PageFetcher
from searchapi_eval.providers.brave import BraveSearchProvider
from searchapi_eval.providers.exa import ExaSearchProvider
from searchapi_eval.providers.firecrawl import FirecrawlSearchProvider
from searchapi_eval.providers.tavily import TavilySearchProvider


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
    page_fetcher = (
        PageFetcher(
            enabled=args.page_fetch or args.fetch_tool,
            cache_dir=Path(args.page_fetch_cache_dir),
            timeout_seconds=args.page_fetch_timeout,
            max_bytes=args.page_fetch_max_bytes,
            concurrency=args.page_fetch_concurrency,
            backend=args.page_fetch_backend,
            jina_reader_base_url=args.jina_reader_base_url,
            jina_api_key=args.jina_api_key,
        )
        if args.page_fetch or args.fetch_tool
        else None
    )
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
        page_fetcher=page_fetcher,
        fetch_tool_enabled=args.fetch_tool,
        auto_page_fetch=args.page_fetch and not args.fetch_tool,
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
    if args.provider == "tavily":
        return TavilySearchProvider(
            cost_per_query_usd=args.search_cost,
            search_depth=args.tavily_search_depth,
            topic=args.tavily_topic,
            include_raw_content=_parse_bool_or_mode(args.tavily_include_raw_content),
            include_favicon=args.tavily_include_favicon,
        )
    if args.provider == "firecrawl":
        return FirecrawlSearchProvider(
            cost_per_query_usd=args.search_cost,
            country=args.firecrawl_country,
            location=args.firecrawl_location,
            include_markdown=args.firecrawl_include_markdown,
            ignore_invalid_urls=args.firecrawl_ignore_invalid_urls,
            firecrawl_timeout_ms=args.firecrawl_timeout_ms,
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
            f"fetches={trace.get('total_fetch_calls', 0)} "
            f"tokens={trace['total_prompt_tokens'] + trace['total_completion_tokens']} "
            f"cost=${trace['total_cost_usd']:.6f}"
        )


def parser() -> argparse.ArgumentParser:
    default_run_id = "phase1_v1_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cli = argparse.ArgumentParser(description="Run the V1 Brave/Exa/Tavily/Firecrawl + Azure GPT-5.4 agent over selected SealQA queries.")
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
    cli.add_argument("--provider", choices=("brave", "exa", "tavily", "firecrawl"), default=os.environ.get("SEARCH_PROVIDER", "brave"))
    cli.add_argument("--brave-country", default=os.environ.get("BRAVE_SEARCH_COUNTRY", "US"))
    cli.add_argument("--brave-search-lang", default=os.environ.get("BRAVE_SEARCH_LANG", "en"))
    cli.add_argument("--brave-ui-lang", default=os.environ.get("BRAVE_SEARCH_UI_LANG", "en-US"))
    cli.add_argument("--brave-safesearch", default=os.environ.get("BRAVE_SEARCH_SAFESEARCH", "moderate"))
    cli.add_argument("--exa-search-type", default="auto")
    cli.add_argument("--tavily-search-depth", default=os.environ.get("TAVILY_SEARCH_DEPTH", "basic"))
    cli.add_argument("--tavily-topic", default=os.environ.get("TAVILY_TOPIC", "general"))
    cli.add_argument("--tavily-include-raw-content", default=os.environ.get("TAVILY_INCLUDE_RAW_CONTENT", "false"))
    cli.add_argument(
        "--tavily-include-favicon",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("TAVILY_INCLUDE_FAVICON", "false").lower() in {"1", "true", "yes"},
    )
    cli.add_argument("--firecrawl-country", default=os.environ.get("FIRECRAWL_COUNTRY", "US"))
    cli.add_argument("--firecrawl-location", default=os.environ.get("FIRECRAWL_LOCATION", ""))
    cli.add_argument(
        "--firecrawl-include-markdown",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("FIRECRAWL_INCLUDE_MARKDOWN", "false").lower() in {"1", "true", "yes"},
    )
    cli.add_argument(
        "--firecrawl-ignore-invalid-urls",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("FIRECRAWL_IGNORE_INVALID_URLS", "false").lower() in {"1", "true", "yes"},
    )
    cli.add_argument("--firecrawl-timeout-ms", type=int, default=int(os.environ.get("FIRECRAWL_TIMEOUT_MS", "60000")))
    cli.add_argument("--search-cost", type=float, default=float(os.environ.get("SEARCH_COST_PER_QUERY_USD", "0")))
    cli.add_argument(
        "--page-fetch",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAGE_FETCH_ENABLED", "true").lower() not in {"0", "false", "no"},
        help="Auto-fetch and extract page content for each search result before returning documents to the model. Disabled automatically when --fetch-tool is enabled.",
    )
    cli.add_argument(
        "--fetch-tool",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("FETCH_PAGE_TOOL_ENABLED", "false").lower() in {"1", "true", "yes"},
        help="Expose fetch_page as a model tool. Search results remain snippet-only; the model chooses pages to fetch.",
    )
    cli.add_argument("--page-fetch-cache-dir", default=os.environ.get("PAGE_FETCH_CACHE_DIR", "data/page_cache"))
    cli.add_argument("--page-fetch-timeout", type=float, default=float(os.environ.get("PAGE_FETCH_TIMEOUT_SECONDS", "15")))
    cli.add_argument("--page-fetch-max-bytes", type=int, default=int(os.environ.get("PAGE_FETCH_MAX_BYTES", "2000000")))
    cli.add_argument("--page-fetch-concurrency", type=int, default=int(os.environ.get("PAGE_FETCH_CONCURRENCY", "4")))
    cli.add_argument(
        "--page-fetch-backend",
        choices=("local", "jina"),
        default=os.environ.get("PAGE_FETCH_BACKEND", "local"),
        help="Page extraction backend: local urllib+HTML extraction or Jina Reader markdown via r.jina.ai.",
    )
    cli.add_argument("--jina-reader-base-url", default=os.environ.get("JINA_READER_BASE_URL", "https://r.jina.ai"))
    cli.add_argument("--jina-api-key", default=os.environ.get("JINA_API_KEY", ""), help=argparse.SUPPRESS)
    cli.add_argument("--input-price-per-1k", type=float, default=float(os.environ.get("AZURE_INPUT_PRICE_PER_1K_USD", "0")))
    cli.add_argument("--output-price-per-1k", type=float, default=float(os.environ.get("AZURE_OUTPUT_PRICE_PER_1K_USD", "0")))
    return cli


def _parse_bool_or_mode(value: str | bool) -> str | bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes"}:
        return True
    if lowered in {"0", "false", "no", ""}:
        return False
    return value


def main() -> None:
    load_env_file()
    asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
