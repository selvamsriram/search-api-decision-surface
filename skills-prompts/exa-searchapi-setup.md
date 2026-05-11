> **Canonical reference:** https://docs.exa.ai/reference/search-api-guide-for-coding-agents
>
> If anything below looks outdated or contradicts real API behavior, fetch that URL — it is the source of truth for search types, parameters, and response shape. Report staleness back to the user.

---

# Exa API Setup Guide

## Your Configuration

| Setting | Value |
|---------|-------|
| Coding Tool | Codex |
| Framework | OpenAI SDK |
| Use Case | Web search tool |
| Search Type | Auto - Balanced relevance and speed (default) |
| Content | Highlights |

**Project Description:** (Not provided)

---

## API Key Setup

### Environment Variable

```bash
export EXA_API_KEY="YOUR_API_KEY"
```

### .env File

```env
EXA_API_KEY=YOUR_API_KEY
```

### Usage in Code

```javascript
import Exa from "exa-js";

const exa = new Exa(process.env.EXA_API_KEY);
```

---

## OpenAI SDK Integration

Exa provides OpenAI-compatible endpoints. Use Exa as a drop-in replacement for OpenAI.

### Quick Answer (Chat Completions)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.exa.ai",
    api_key="YOUR_EXA_API_KEY",
)

completion = client.chat.completions.create(
    model="exa",
    messages=[
        {"role": "user", "content": "What are the latest developments in quantum computing?"}
    ],
    extra_body={"text": True}  # include full text from sources
)

print(completion.choices[0].message.content)
print(completion.choices[0].message.citations)  # citations included
```

### Deep Research

```python
completion = client.chat.completions.create(
    model="exa-research",  # or "exa-research-pro"
    messages=[
        {"role": "user", "content": "What makes some LLMs so much better than others?"}
    ],
    stream=True,
)

for chunk in completion:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### Wrap Existing OpenAI Client (RAG)

```python
from openai import OpenAI
from exa_py import Exa

openai = OpenAI(api_key='OPENAI_API_KEY')
exa = Exa('EXA_API_KEY')

# Wrap the OpenAI client - adds RAG automatically
exa_openai = exa.wrap(openai)

# Use exactly like normal OpenAI client
completion = exa_openai.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is the latest climate tech news?"}]
)
```

📖 Full docs: [docs.exa.ai/reference/openai-sdk](https://docs.exa.ai/reference/openai-sdk)

---

## 🔌 Exa MCP Server for OpenAI Codex

Give OpenAI Codex real-time web search, code context, and company research with Exa MCP.

**Run in terminal:**

```bash
codex mcp add exa --url https://mcp.exa.ai/mcp
```

**Tool enablement (optional):**
Add a `tools=` query param to the MCP URL.

Enable specific tools:
```
https://mcp.exa.ai/mcp?tools=web_search_exa,get_code_context_exa,people_search_exa
```

Enable all tools:
```
https://mcp.exa.ai/mcp?tools=web_search_exa,web_search_advanced_exa,get_code_context_exa,crawling_exa,company_research_exa,people_search_exa,deep_researcher_start,deep_researcher_check
```

**Authentication:** Exa MCP uses OAuth — no API key needed. Your client opens a browser to sign in to your Exa account on first connection. Manage your account at [dashboard.exa.ai](https://dashboard.exa.ai).

**Troubleshooting:** if tools don't appear, restart your MCP client after updating the config.

📖 Full docs: [docs.exa.ai/reference/exa-mcp](https://docs.exa.ai/reference/exa-mcp)

---

## Quick Start (JavaScript)

```bash
npm install exa-js
```

```javascript
import Exa from "exa-js";

const exa = new Exa("YOUR_API_KEY");

const results = await exa.search("latest developments in AI safety research", {
  "type": "auto",
  "numResults": 10,
  "contents": {
    "highlights": true
  }
});

results.results.forEach(result => {
  console.log(result.title, result.url);
});
```

---

## Function Calling / Tool Use

Function calling (also known as tool use) allows your AI agent to dynamically decide when to search the web based on the conversation context. Instead of searching on every request, the LLM intelligently determines when real-time information would improve its response—making your agent more efficient and accurate.

**Why use function calling with Exa?**
- Your agent can ground responses in current, factual information
- Reduces hallucinations by fetching real sources when needed
- Enables multi-step reasoning where the agent searches, analyzes, and responds

📚 **Full documentation**: https://docs.exa.ai/reference/openai-tool-calling

### OpenAI Function Calling

```javascript
import OpenAI from "openai";
import Exa from "exa-js";

const openai = new OpenAI();
const exa = new Exa(process.env.EXA_API_KEY);

const tools = [{
  type: "function",
  function: {
    name: "exa_search",
    description: "Search the web for current information.",
    parameters: {
      type: "object",
      properties: { query: { type: "string", description: "Search query" } },
      required: ["query"],
    },
  },
}];

async function exaSearch(query) {
  const results = await exa.search(query, {
    type: "auto",
    numResults: 10,
    contents: { highlights: true },
  });
  return results.results.map((r) => `${r.title}: ${r.url}`).join("\n");
}

const messages = [{ role: "user", content: "What's the latest in AI safety?" }];
const response = await openai.chat.completions.create({ model: "gpt-4o", messages, tools });

const toolCall = response.choices[0].message.tool_calls?.[0];
if (toolCall) {
  const args = JSON.parse(toolCall.function.arguments);
  const searchResults = await exaSearch(args.query);
  messages.push(response.choices[0].message);
  messages.push({ role: "tool", tool_call_id: toolCall.id, content: searchResults });
  const final = await openai.chat.completions.create({ model: "gpt-4o", messages });
  console.log(final.choices[0].message.content);
}
```

### Anthropic Tool Use

```javascript
import Anthropic from "@anthropic-ai/sdk";
import Exa from "exa-js";

const client = new Anthropic();
const exa = new Exa(process.env.EXA_API_KEY);

const tools = [{
  name: "exa_search",
  description: "Search the web for current information.",
  input_schema: {
    type: "object",
    properties: { query: { type: "string", description: "Search query" } },
    required: ["query"],
  },
}];

async function exaSearch(query) {
  const results = await exa.search(query, {
    type: "auto",
    numResults: 10,
    contents: { highlights: true },
  });
  return results.results.map((r) => `${r.title}: ${r.url}`).join("\n");
}

const messages = [{ role: "user", content: "Latest quantum computing developments?" }];
const response = await client.messages.create({
  model: "claude-sonnet-4-20250514",
  max_tokens: 4096,
  tools,
  messages,
});

if (response.stop_reason === "tool_use") {
  const toolUse = response.content.find((b) => b.type === "tool_use");
  const toolResult = await exaSearch(toolUse.input.query);
  messages.push({ role: "assistant", content: response.content });
  messages.push({
    role: "user",
    content: [{ type: "tool_result", tool_use_id: toolUse.id, content: toolResult }],
  });
  const final = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 4096,
    tools,
    messages,
  });
  console.log(final.content[0].text);
}
```

---

## Search Type Reference

| Type | Best For | Approx Latency | Depth |
|------|----------|----------------|-------|
| `auto` | Most queries — balanced relevance and speed | ~1 second | Smart | ← your selection
| `fast` | Latency-sensitive queries that still need good relevance | ~450 ms | Basic |
| `instant` | Chat, voice, autocomplete, quick lookups | ~250 ms | Basic |
| `deep-lite` | Cheaper synthesis when full deep search is overkill | 4 seconds | Deep |
| `deep` | Research, enrichment, thorough results | 4-15 seconds | Deep |
| `deep-reasoning` | Complex research, multi-step reasoning, hard synthesis tasks | 12-40 seconds | Deepest |

Latency numbers are ballpark — synthesis (`outputSchema`) and forced livecrawls (`contents.maxAgeHours: 0`) stack on top of the base `type`. See the Latency Characteristics section for details.

**Tip:** `type="auto"` works well for most queries. `outputSchema` works on every search type, so you can request structured, grounded output regardless of which type you pick.

---

## Structured Outputs (outputSchema)

`outputSchema` works on **every** search type. Pass a JSON schema and Exa returns the synthesized answer as structured JSON in `output.content`, with field-level citations in `output.grounding`. Deep variants (`deep-lite`, `deep`, `deep-reasoning`) give higher-quality synthesis for complex queries, but the response shape is the same.

**Schema controls:** `type`, `description`, `required`, `properties`, `items`. Max nesting depth 2, max total properties 10. Do NOT add citation or confidence fields to the schema — `/search` returns grounding data automatically.

```javascript
import Exa from "exa-js";

const exa = new Exa("YOUR_API_KEY");

const results = await exa.search("articles about GPUs", {
  type: "auto",
  outputSchema: {
    type: "object",
    description: "Companies mentioned in articles",
    required: ["companies"],
    properties: {
      companies: {
        type: "array",
        description: "List of companies mentioned",
        items: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string", description: "Name of the company" },
            description: { type: "string", description: "Short description of what the company does" }
          }
        }
      }
    }
  },
  contents: {
    highlights: true
  }
});

// Access structured output
console.log(results.output.content);   // {"companies": [{"name": "Nvidia", ...}]}
console.log(results.output.grounding); // Field-level citations and confidence
```

### Response Shape

Responses with `outputSchema` include:
- `output.content` — structured JSON matching your schema (or a string for `{"type": "text"}` schemas)
- `output.grounding` — array of `{field, citations, confidence}` entries with source URLs

```json
{
  "output": {
    "content": {
      "companies": [
        {"name": "Nvidia", "description": "GPU and AI chip manufacturer"},
        {"name": "AMD", "description": "Semiconductor company producing GPUs and CPUs"}
      ]
    },
    "grounding": [
      {
        "field": "companies[0].name",
        "citations": [{"url": "https://...", "title": "Source"}],
        "confidence": "high"
      }
    ]
  }
}
```

### When to Use Structured Outputs

- **Enrichment workflows** — extract specific fields (company info, people data, product details)
- **Data pipelines** — get structured data directly instead of parsing free text
- **Grounded answers** — prefer `outputSchema` on `/search` over the legacy `/answer` endpoint
- Prefer a deep variant (`deep-lite`/`deep`/`deep-reasoning`) when you need multi-step reasoning or synthesis across many sources

---

## Content Configuration

The generated examples request highlights by default:

```json
"contents": {
  "highlights": true
}
```

Highlights return query-relevant excerpts, which are usually the right content mode for LLM workflows because they keep token usage predictable.

Content is controlled via the `contents` object on `/search` (or top-level fields on `/contents`). You can combine `text`, `highlights`, and `summary` in the same call — they are not mutually exclusive.

| Mode | Config | Best For |
|------|--------|----------|
| Highlights | `"highlights": true` | Token-efficient excerpts |
| Text | `"text": {"maxCharacters": 20000}` | Full content extraction, RAG |
| Summary | `"summary": {"query": "your question"}` or `"summary": true` | LLM-written summary per result |

### Tuning knobs

- **`highlights`** — pass `true` to return query-relevant highlights for each result.
- **`summary`** — pass `true` for a generic summary, or `{"query": "..."}` to bias the summary toward a specific question. Supports a `schema` field for per-result structured output. Summary has no `verbosity` setting — verbosity lives on `text` (below).
- **`text.verbosity`** — `"compact" | "full"` (default `"compact"`). Compact returns only the main content of the page, excluding navbars, banners, footers etc.
- **`text.includeHtmlTags`** — boolean (default `false`). When `true`, preserves HTML structure (useful for code blocks, tables).
- **`text.maxCharacters`** — hard cap on extracted text length. Always set this to control token cost when requesting text.

**Case conventions:** JavaScript SDK and raw JSON use camelCase (`maxCharacters`). Python SDK uses snake_case (`max_characters`) — this applies inside nested dicts too.

**Token usage:** `text: true` with no cap can blow up context. Prefer `highlights: true`, or `text` with `maxCharacters`, for agent workflows.

---

## Domain Filtering (Optional)

Usually not needed - Exa's neural search finds relevant results without domain restrictions.

**When to use:**
- Targeting specific authoritative sources
- Excluding low-quality domains from results

**Example:**

```json
{
  "includeDomains": ["arxiv.org", "github.com"],
  "excludeDomains": ["pinterest.com"]
}
```

**Note:** `includeDomains` and `excludeDomains` can be used together to include a broad domain while excluding specific subdomains (e.g., `"includeDomains": ["vercel.com"], "excludeDomains": ["community.vercel.com"]`).

---

## Web Search Tool

```json
{
  "query": "latest developments in AI safety research",
  "num_results": 10,
  "contents": {
    "highlights": true
  }
}
```

**Tips:**
- Use `type: "auto"` for most queries
- Great for building search-powered chatbots or agents
- Combine with contents for RAG workflows

---

## Content Freshness (maxAgeHours)

`maxAgeHours` sets the maximum acceptable age (in hours) for cached content. If the cached version is older than this threshold, Exa will livecrawl the page to get fresh content.

| Value | Behavior | Best For |
|-------|----------|----------|
| 24 | Use cache if less than 24 hours old, otherwise livecrawl | Daily-fresh content |
| 1 | Use cache if less than 1 hour old, otherwise livecrawl | Near real-time data |
| 0 | Always livecrawl (ignore cache entirely) | Real-time data where cached content is unusable |
| -1 | Never livecrawl (cache only) | Maximum speed, historical/static content |
| *(omit)* | Default behavior (livecrawl as fallback if no cache exists) | **Recommended** — balanced speed and freshness |

**When LiveCrawl Isn't Necessary:**
Cached data is sufficient for many queries, especially for historical topics or educational content. These subjects rarely change, so reliable cached results can provide accurate information quickly.

See [maxAgeHours docs](https://exa.ai/docs/reference/livecrawling-contents#maxAgeHours) for more details.

---

## Other Endpoints

Beyond `/search`, the other endpoint you'll commonly use is `/contents`:

| Endpoint | Description | Docs |
|----------|-------------|------|
| `/contents` | Get clean, parsed content for URLs you already have | [Docs](https://exa.ai/docs/reference/get-contents) |

> For grounded answers, use `outputSchema` on `/search` instead of the legacy `/answer` endpoint. `/search` + `outputSchema` returns the same answer-with-citations shape in `output.content` / `output.grounding`.

### /contents — Get Contents for Known URLs

Use `/contents` when you already have URLs and need their content. Unlike `/search` (which finds and optionally retrieves content), `/contents` is purely for content extraction from known URLs.

**When to use `/contents` vs `/search`:**
- URLs from another source (database, user input, RSS feeds) → `/contents`
- Need to refresh stale content for URLs you already have → `/contents` with `maxAgeHours`
- Need to find AND get content in one call → `/search` with `contents`

```javascript
import Exa from "exa-js";

const exa = new Exa("YOUR_API_KEY");

const results = await exa.getContents(
  ["https://example.com/article", "https://example.com/blog-post"],
  { highlights: true }
);

results.results.forEach(result => {
  console.log(result.title, result.url);
  console.log(result.highlights);
});
```

**Content retrieval options** (choose one per request):

| Option | Config | Best For |
|--------|--------|----------|
| Highlights | `"highlights": true` | Key excerpts, lower token usage |
| Text | `"text": {"max_characters": 20000}` | Full content extraction, RAG |

**Highlights example:**

```json
{
  "urls": ["https://example.com/article"],
  "highlights": true
}
```

**Freshness control:** Add `maxAgeHours` to ensure content is fresh:
- `24` — livecrawl if cached content is older than 24 hours
- `0` — always livecrawl (ignore cache)
- Omit — use cache when available, livecrawl as fallback

---

## Troubleshooting

**⚠️ COMMON PARAMETER MISTAKES — avoid these:**
- `useAutoprompt` → **deprecated**, remove it entirely
- `includeUrls` / `excludeUrls` → **do not exist**. Use `includeDomains` / `excludeDomains`
- `text`, `summary`, `highlights` at the top level of `/search` → **must be nested** inside `contents` (e.g. `"contents": {"highlights": true}`). On `/contents` they ARE top-level — don't confuse the two.
- `numSentences`, `highlightsPerUrl` → **deprecated** highlights params. Use `highlights: true` instead
- `tokensNum` → **does not exist**. Use `contents.text.maxCharacters` to limit text length
- `livecrawl: "always"` → **deprecated**. Use `contents.maxAgeHours: 0` instead
- `excludeDomains` + `category: "company" | "people"` → **400 error**. Those categories don't support `excludeDomains` or any date filters.

> **`stream: true`** switches `/search` to SSE mode (OpenAI-compatible chat-completion chunks). It's supported — just expect streaming chunks instead of one JSON response.

**Results not relevant?**
1. Try `type: "auto"` - most balanced option
2. Try `type: "deep"` - runs multiple query variations and ranks the combined results
3. Refine query - use singular form, be specific
4. Check category matches your use case

**Need structured data from search?**
1. Pass `outputSchema` on any search type — `auto` works, `deep`/`deep-reasoning` gives higher-quality synthesis
2. Define the fields you need in the schema — Exa returns grounded JSON in `output.content` with citations in `output.grounding`

**Results too slow?**
1. Use `type: "fast"` or `type: "instant"`
2. Reduce `numResults`
3. Skip contents if you only need URLs

**No results?**
1. Remove filters (date, domain restrictions)
2. Simplify query
3. Try `type: "auto"` - has fallback mechanisms

---

## Resources

- Docs: https://exa.ai/docs
- Dashboard: https://dashboard.exa.ai
- API Status: https://status.exa.ai