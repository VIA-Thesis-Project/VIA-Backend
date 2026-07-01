"""Tavily Search client — structured web search with hard domain filtering.

Tavily is designed for AI agents and supports ``include_domains`` as a first-class
parameter, which means the domain list is enforced server-side (not just a prompt hint).

Free tier: 1 000 searches/month — sufficient for thesis use.
No external SDK needed; uses stdlib urllib.request.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_RESULTS = 5
_DEFAULT_SEARCH_DEPTH = "advanced"


_NON_ACADEMIC_DOMAINS = (
    "youtube.com", "youtu.be", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "tiktok.com", "reddit.com", "wikipedia.org",
)


@dataclass(frozen=True)
class TavilySearchConfig:
    api_key: str
    max_results: int = _DEFAULT_MAX_RESULTS
    search_depth: str = _DEFAULT_SEARCH_DEPTH
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = _NON_ACADEMIC_DOMAINS
    timeout_seconds: int = _DEFAULT_TIMEOUT


@dataclass
class TavilySearchResult:
    url: str
    title: str
    content: str
    score: float


@dataclass
class TavilySearchResponse:
    query: str
    results: list[TavilySearchResult] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        return [r.url for r in self.results]


HttpPostCallable = Callable[[str, dict[str, Any], int], dict[str, Any]]


def _stdlib_http_post(url: str, body: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


class TavilySearchClient:
    """Search the web via Tavily API with hard domain filtering."""

    def __init__(
        self,
        config: TavilySearchConfig,
        http_post: HttpPostCallable | None = None,
    ) -> None:
        self._config = config
        self._http_post = http_post or _stdlib_http_post

    def search(self, query: str) -> TavilySearchResponse:
        """Run a search query and return structured results. Never raises."""
        body: dict[str, Any] = {
            "api_key": self._config.api_key,
            "query": query,
            "max_results": self._config.max_results,
            "search_depth": self._config.search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        if self._config.include_domains:
            body["include_domains"] = list(self._config.include_domains)
        if self._config.exclude_domains:
            body["exclude_domains"] = list(self._config.exclude_domains)

        try:
            raw = self._http_post(TAVILY_SEARCH_ENDPOINT, body, self._config.timeout_seconds)
        except urllib.error.HTTPError as exc:
            logger.warning("[VIA-TAVILY] HTTP %s for query=%r", exc.code, query)
            return TavilySearchResponse(query=query)
        except Exception as exc:
            logger.warning("[VIA-TAVILY] search failed query=%r: %s", query, exc)
            return TavilySearchResponse(query=query)

        return _parse_response(
            query, raw,
            exclude_domains=self._config.exclude_domains,
            include_domains=self._config.include_domains,
        )


def _domain_of(url: str) -> str:
    """Extract hostname without www prefix."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _parse_response(
    query: str,
    raw: dict[str, Any],
    exclude_domains: tuple[str, ...] = (),
    include_domains: tuple[str, ...] = (),
) -> TavilySearchResponse:
    results: list[TavilySearchResult] = []
    skipped = 0
    for item in raw.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        host = _domain_of(url).removeprefix("www.")
        if exclude_domains and any(host == d or host.endswith("." + d) for d in exclude_domains):
            skipped += 1
            continue
        if include_domains and not any(host == d or host.endswith("." + d) for d in include_domains):
            skipped += 1
            continue
        results.append(
            TavilySearchResult(
                url=url,
                title=str(item.get("title") or "").strip(),
                content=str(item.get("content") or "").strip(),
                score=float(item.get("score") or 0.0),
            )
        )
    if skipped:
        logger.info("[VIA-TAVILY] query=%r | skipped_off_domain=%d", query, skipped)
    logger.info("[VIA-TAVILY] query=%r | n_results=%d", query, len(results))
    return TavilySearchResponse(query=query, results=results)
