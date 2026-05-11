from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]
    latency_ms: float
    raw_response: dict[str, Any] = field(repr=False)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class LLMClient:
    model_id: str
    input_price_per_1k_usd: float
    output_price_per_1k_usd: float

    def request_snapshot(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "messages": messages,
            "tools": tools,
        }

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        raise NotImplementedError
