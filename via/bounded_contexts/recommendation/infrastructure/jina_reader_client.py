"""Jina Reader client — fetches full document/PDF content from a URL.

Jina Reader converts any public URL (including PDFs) to clean Markdown via:
    GET https://r.jina.ai/<url>

No external SDK needed — uses stdlib urllib.request only.
With an API key, rate limits are higher; without one, the free tier applies.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

JINA_BASE_URL = "https://r.jina.ai/"
_DEFAULT_TIMEOUT = 25
_DEFAULT_MAX_CHARS = 8_000
_DEFAULT_MIN_CHARS = 300
_DEFAULT_MAX_URLS = 3


@dataclass(frozen=True)
class JinaReaderConfig:
    timeout_seconds: int = _DEFAULT_TIMEOUT
    max_chars_per_doc: int = _DEFAULT_MAX_CHARS
    min_chars_threshold: int = _DEFAULT_MIN_CHARS
    max_urls: int = _DEFAULT_MAX_URLS
    api_key: str | None = None


@dataclass
class JinaReaderResult:
    url: str
    text: str
    success: bool

    @property
    def chars(self) -> int:
        return len(self.text)


class IJinaHttpCaller:
    """Minimal protocol for injectable HTTP caller (used in tests)."""

    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
    ) -> str:
        """Return response body as text. Raise on HTTP/network error."""
        raise NotImplementedError


def _stdlib_http_get(url: str, *, headers: dict[str, str], timeout: int) -> str:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    encoding = resp.headers.get_content_charset("utf-8") or "utf-8"
    return raw.decode(encoding, errors="replace")


class JinaReaderClient:
    """Fetches full document/PDF content via Jina Reader (r.jina.ai)."""

    def __init__(
        self,
        config: JinaReaderConfig,
        http_get: Any = None,
    ) -> None:
        self._config = config
        self._http_get = http_get or _stdlib_http_get

    def fetch(self, url: str) -> JinaReaderResult:
        """Fetch full Markdown content for a URL. Never raises."""
        headers: dict[str, str] = {
            "Accept": "text/markdown",
            "X-Return-Format": "markdown",
            "X-Timeout": str(self._config.timeout_seconds),
            "User-Agent": "VIA-Thesis/1.0",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        jina_url = f"{JINA_BASE_URL}{url}"
        try:
            text = self._http_get(
                jina_url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except urllib.error.HTTPError as exc:
            logger.warning("[VIA-JINA] HTTP %s for url=%s", exc.code, url)
            return JinaReaderResult(url=url, text="", success=False)
        except Exception as exc:
            logger.warning("[VIA-JINA] fetch failed url=%s: %s", url, exc)
            return JinaReaderResult(url=url, text="", success=False)

        text = text[: self._config.max_chars_per_doc].strip()
        success = len(text) >= self._config.min_chars_threshold
        if not success:
            logger.debug("[VIA-JINA] content too short url=%s chars=%d", url, len(text))
        else:
            logger.info("[VIA-JINA] fetched url=%s chars=%d", url, len(text))
        return JinaReaderResult(url=url, text=text, success=success)

    def fetch_many(self, urls: list[str]) -> list[JinaReaderResult]:
        """Fetch up to config.max_urls URLs, returning all results."""
        return [self.fetch(url) for url in urls[: self._config.max_urls]]
