from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from searchapi_eval.agent.trace import utc_now_iso
from searchapi_eval.providers.base import normalize_url

from .html_extract import clean_text, extract_html_text


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)
DEFAULT_JINA_READER_BASE_URL = "https://r.jina.ai"
SUPPORTED_FETCH_BACKENDS = {"local", "jina"}

TEXTUAL_CONTENT_TYPE_HINTS = (
    "text/",
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/csv",
    "application/x-ndjson",
)
OFFICE_CONTENT_TYPE_HINTS = (
    "application/msword",
    "application/vnd.ms-",
    "application/vnd.openxmlformats-officedocument",
    "application/vnd.oasis.opendocument",
)
UNSUPPORTED_BINARY_CONTENT_TYPE_HINTS = (
    "application/octet-stream",
    "application/zip",
    "application/x-zip",
    "application/x-7z",
    "application/x-rar",
    "application/x-tar",
    "application/gzip",
    "image/",
    "audio/",
    "video/",
    "font/",
)
OFFICE_EXTENSIONS = {
    ".doc",
    ".docm",
    ".docx",
    ".dot",
    ".dotm",
    ".dotx",
    ".odp",
    ".ods",
    ".odt",
    ".pot",
    ".potm",
    ".potx",
    ".pps",
    ".ppsm",
    ".ppsx",
    ".ppt",
    ".pptm",
    ".pptx",
    ".rtf",
    ".xls",
    ".xlsb",
    ".xlsm",
    ".xlsx",
}
UNSUPPORTED_BINARY_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".bz2",
    ".dmg",
    ".eot",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".otf",
    ".png",
    ".rar",
    ".tar",
    ".tif",
    ".tiff",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}


@dataclass
class PageFetcher:
    enabled: bool = True
    cache_dir: Path = Path("data/page_cache")
    timeout_seconds: float = 15.0
    max_bytes: int = 2_000_000
    user_agent: str = DEFAULT_USER_AGENT
    concurrency: int = 4
    backend: str = "local"
    jina_reader_base_url: str = DEFAULT_JINA_READER_BASE_URL
    jina_api_key: str = ""

    @classmethod
    def from_env(cls) -> "PageFetcher":
        return cls(
            enabled=os.environ.get("PAGE_FETCH_ENABLED", "true").lower() not in {"0", "false", "no"},
            cache_dir=Path(os.environ.get("PAGE_FETCH_CACHE_DIR", "data/page_cache")),
            timeout_seconds=float(os.environ.get("PAGE_FETCH_TIMEOUT_SECONDS", "15")),
            max_bytes=int(os.environ.get("PAGE_FETCH_MAX_BYTES", "2000000")),
            user_agent=os.environ.get("PAGE_FETCH_USER_AGENT", DEFAULT_USER_AGENT),
            concurrency=int(os.environ.get("PAGE_FETCH_CONCURRENCY", "4")),
            backend=os.environ.get("PAGE_FETCH_BACKEND", "local"),
            jina_reader_base_url=os.environ.get("JINA_READER_BASE_URL", DEFAULT_JINA_READER_BASE_URL),
            jina_api_key=os.environ.get("JINA_API_KEY", ""),
        )

    async def fetch_results(self, search_response: dict[str, Any], retrieval_id: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        semaphore = asyncio.Semaphore(max(1, self.concurrency))

        async def fetch_one(result: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await asyncio.to_thread(self.fetch_result, result, search_response, retrieval_id)

        return await asyncio.gather(*(fetch_one(result) for result in search_response.get("results", [])))

    async def fetch_result_async(
        self,
        result: dict[str, Any],
        search_response: dict[str, Any],
        retrieval_id: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        return await asyncio.to_thread(self.fetch_result, result, search_response, retrieval_id)

    def fetch_result(
        self,
        result: dict[str, Any],
        search_response: dict[str, Any],
        retrieval_id: str,
    ) -> dict[str, Any]:
        backend = self.backend.lower().strip()
        if backend not in SUPPORTED_FETCH_BACKENDS:
            raise ValueError(f"Unsupported page fetch backend: {self.backend}")
        url = result.get("url") or ""
        artifact_path = self._artifact_path(url)
        if artifact_path.exists():
            artifact = _read_json_gz(artifact_path)
            return self._summary_from_artifact(artifact, artifact_path)

        started = time.perf_counter()
        artifact: dict[str, Any] = {
            "schema_version": "page_extract_v1",
            "fetch_backend": backend,
            "url": url,
            "normalized_url": normalize_url(url),
            "final_url": None,
            "fetched_at": utc_now_iso(),
            "retrieval_id": retrieval_id,
            "search_context": {
                "provider_id": search_response.get("provider_id"),
                "search_query": search_response.get("query"),
                "rank": result.get("rank"),
                "title": result.get("title"),
                "snippet": result.get("snippet"),
                "domain": result.get("domain"),
            },
            "http": {
                "status": None,
                "content_type": None,
                "content_length": None,
                "truncated_by_max_bytes": False,
            },
            "extraction": {
                "status": "failed",
                "method": None,
                "text": "",
                "text_sha256": None,
                "text_chars": 0,
                "tokens_estimate": 0,
                "error": None,
            },
            "fetch_latency_ms": None,
        }

        try:
            if backend == "jina":
                text, method, response_info = self._fetch_jina_markdown(url)
                artifact["final_url"] = response_info["final_url"]
                artifact["reader_url"] = response_info.get("reader_url")
                artifact["http"].update(response_info)
            else:
                body, response_info = self._fetch_url(url)
                artifact["final_url"] = response_info["final_url"]
                artifact["http"].update(response_info)
                text, method = self._extract_text(
                    body,
                    response_info.get("content_type") or "",
                    response_info.get("final_url") or url,
                )
            artifact["extraction"].update(
                {
                    "status": "success" if text else "empty",
                    "method": method,
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
                    "text_chars": len(text),
                    "tokens_estimate": estimate_tokens(text),
                    "error": None,
                }
            )
        except Exception as error:
            artifact["extraction"]["error"] = str(error)
        finally:
            artifact["fetch_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            _write_json_gz(artifact_path, artifact)

        return self._summary_from_artifact(artifact, artifact_path)

    def _fetch_url(self, url: str) -> tuple[bytes, dict[str, Any]]:
        if not urlparse(url).scheme.startswith("http"):
            raise ValueError(f"Unsupported URL scheme: {url}")
        request = Request(
            url,
            headers={
                "user-agent": self.user_agent,
                "accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.7,*/*;q=0.2",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(self.max_bytes + 1)
                truncated = len(body) > self.max_bytes
                if truncated:
                    body = body[: self.max_bytes]
                return body, {
                    "status": response.status,
                    "content_type": response.headers.get("content-type"),
                    "content_length": response.headers.get("content-length"),
                    "truncated_by_max_bytes": truncated,
                    "final_url": response.geturl(),
                }
        except HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}: {error.reason}") from error
        except URLError as error:
            raise RuntimeError(f"URL error: {error.reason}") from error

    def _fetch_jina_markdown(self, url: str) -> tuple[str, str, dict[str, Any]]:
        if not urlparse(url).scheme.startswith("http"):
            raise ValueError(f"Unsupported URL scheme: {url}")
        reader_url = f"{self.jina_reader_base_url.rstrip('/')}/{url}"
        headers = {
            "user-agent": self.user_agent,
            "accept": "text/plain,text/markdown,*/*;q=0.2",
            "x-return-format": "markdown",
        }
        if self.jina_api_key:
            headers["authorization"] = f"Bearer {self.jina_api_key}"
        request = Request(
            reader_url,
            headers=headers,
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(self.max_bytes + 1)
                truncated = len(body) > self.max_bytes
                if truncated:
                    body = body[: self.max_bytes]
                content_type = response.headers.get("content-type") or ""
                charset = "utf-8"
                lower_type = content_type.lower()
                if "charset=" in lower_type:
                    charset = lower_type.rsplit("charset=", 1)[-1].split(";", 1)[0].strip()
                text = clean_text(body.decode(charset or "utf-8", errors="replace"))
                return text, "jina_reader_markdown", {
                    "status": response.status,
                    "content_type": content_type,
                    "content_length": response.headers.get("content-length"),
                    "truncated_by_max_bytes": truncated,
                    "final_url": url,
                    "reader_url": response.geturl() or reader_url,
                }
        except HTTPError as error:
            raise RuntimeError(f"Jina Reader HTTP {error.code}: {error.reason}") from error
        except URLError as error:
            raise RuntimeError(f"Jina Reader URL error: {error.reason}") from error

    def _extract_text(self, body: bytes, content_type: str, url: str = "") -> tuple[str, str]:
        lower_type = content_type.lower()
        suffix = _url_suffix(url)
        if "pdf" in lower_type:
            return "", "pdf_unsupported_v1"
        if suffix == ".pdf":
            return "", "pdf_unsupported_v1"
        if _has_hint(lower_type, OFFICE_CONTENT_TYPE_HINTS) or suffix in OFFICE_EXTENSIONS:
            return "", "office_unsupported_v1"
        if _has_hint(lower_type, UNSUPPORTED_BINARY_CONTENT_TYPE_HINTS) or suffix in UNSUPPORTED_BINARY_EXTENSIONS:
            return "", "binary_unsupported_v1"

        charset = "utf-8"
        if "charset=" in lower_type:
            charset = lower_type.rsplit("charset=", 1)[-1].split(";", 1)[0].strip()
        decoded = body.decode(charset or "utf-8", errors="replace")
        if "html" in lower_type or "<html" in decoded[:1000].lower():
            return extract_html_text(decoded)
        if lower_type and not _has_hint(lower_type, TEXTUAL_CONTENT_TYPE_HINTS):
            return "", "binary_unsupported_v1"
        if _looks_binary(body, decoded):
            return "", "binary_unsupported_v1"
        return clean_text(decoded), "plain_text"

    def _artifact_path(self, url: str) -> Path:
        normalized = normalize_url(url)
        cache_key = normalized if self.backend.lower().strip() == "local" else f"{self.backend.lower().strip()}:{normalized}"
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self.cache_dir / digest[:2] / digest[2:4] / f"{digest}.json.gz"

    def _summary_from_artifact(self, artifact: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
        extraction = artifact.get("extraction") or {}
        http = artifact.get("http") or {}
        return {
            "schema_version": "page_fetch_summary_v1",
            "fetch_backend": artifact.get("fetch_backend") or "local",
            "url": artifact.get("url"),
            "normalized_url": artifact.get("normalized_url"),
            "final_url": artifact.get("final_url"),
            "reader_url": artifact.get("reader_url"),
            "artifact_path": str(artifact_path),
            "fetch_status": extraction.get("status"),
            "http_status": http.get("status"),
            "content_type": http.get("content_type"),
            "truncated_by_max_bytes": bool(http.get("truncated_by_max_bytes")),
            "extractor": extraction.get("method"),
            "extracted_text_chars": extraction.get("text_chars", 0),
            "extracted_text_tokens_estimate": extraction.get("tokens_estimate", 0),
            "text_sha256": extraction.get("text_sha256"),
            "fetch_latency_ms": artifact.get("fetch_latency_ms"),
            "error": extraction.get("error"),
            "extracted_text": extraction.get("text") or "",
        }


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _has_hint(value: str, hints: tuple[str, ...]) -> bool:
    return any(hint in value for hint in hints)


def _url_suffix(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def _looks_binary(body: bytes, decoded: str) -> bool:
    if not body:
        return False
    sample = body[:4096]
    if b"\x00" in sample:
        return True

    text_chars = bytes(range(32, 127)) + b"\n\r\t\b\f"
    non_text = sum(byte not in text_chars for byte in sample)
    if non_text / len(sample) > 0.30:
        return True

    decoded_sample = decoded[:4096]
    if decoded_sample:
        replacement_ratio = decoded_sample.count("\ufffd") / len(decoded_sample)
        if replacement_ratio > 0.02:
            return True
    return False


def _read_json_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_gz(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True)
