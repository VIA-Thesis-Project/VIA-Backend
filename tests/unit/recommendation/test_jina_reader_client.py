"""Unit tests for JinaReaderClient."""

from __future__ import annotations

import urllib.error

import pytest

from via.bounded_contexts.recommendation.infrastructure.jina_reader_client import (
    JinaReaderClient,
    JinaReaderConfig,
    JinaReaderResult,
)


def _client(
    http_get=None,
    *,
    max_urls: int = 3,
    max_chars: int = 8_000,
    min_chars: int = 300,
    api_key: str | None = None,
) -> JinaReaderClient:
    config = JinaReaderConfig(
        max_urls=max_urls,
        max_chars_per_doc=max_chars,
        min_chars_threshold=min_chars,
        api_key=api_key,
    )
    return JinaReaderClient(config, http_get=http_get)


def test_fetch_returns_markdown_text() -> None:
    content = "# Mandarina\n" + "Contenido sobre suelo y pH. " * 20

    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        assert "r.jina.ai" in url
        assert "https://example.com/doc" in url
        return content

    result = _client(_http_get, min_chars=10).fetch("https://example.com/doc")

    assert result.success is True
    assert result.url == "https://example.com/doc"
    assert result.text == content.strip()
    assert result.chars == len(content.strip())


def test_fetch_sends_api_key_header_when_set() -> None:
    captured_headers: dict = {}

    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        captured_headers.update(headers)
        return "x" * 400

    _client(_http_get, api_key="jina_abc123", min_chars=10).fetch("https://example.com/doc")

    assert captured_headers.get("Authorization") == "Bearer jina_abc123"


def test_fetch_omits_auth_header_without_api_key() -> None:
    captured_headers: dict = {}

    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        captured_headers.update(headers)
        return "x" * 400

    _client(_http_get, min_chars=10).fetch("https://example.com/doc")

    assert "Authorization" not in captured_headers


def test_fetch_truncates_to_max_chars() -> None:
    long_content = "A" * 20_000

    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        return long_content

    result = _client(_http_get, max_chars=5_000, min_chars=10).fetch("https://example.com/doc")

    assert len(result.text) == 5_000
    assert result.success is True


def test_fetch_marks_short_content_as_failure() -> None:
    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        return "too short"

    result = _client(_http_get, min_chars=300).fetch("https://example.com/doc")

    assert result.success is False
    assert result.text == "too short"


def test_fetch_handles_http_error_gracefully() -> None:
    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    result = _client(_http_get).fetch("https://example.com/doc")

    assert result.success is False
    assert result.text == ""
    assert result.url == "https://example.com/doc"


def test_fetch_handles_network_error_gracefully() -> None:
    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        raise TimeoutError("timed out")

    result = _client(_http_get).fetch("https://example.com/doc")

    assert result.success is False
    assert result.text == ""


def test_fetch_many_respects_max_urls() -> None:
    fetched: list[str] = []

    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        fetched.append(url)
        return "x" * 400

    urls = [f"https://example.com/{i}" for i in range(10)]
    results = _client(_http_get, max_urls=3, min_chars=10).fetch_many(urls)

    assert len(results) == 3
    assert len(fetched) == 3


def test_fetch_many_returns_all_results_including_failures() -> None:
    def _http_get(url: str, *, headers: dict, timeout: int) -> str:
        if "bad" in url:
            raise TimeoutError("timeout")
        return "x" * 400

    urls = ["https://example.com/good", "https://example.com/bad"]
    results = _client(_http_get, max_urls=5, min_chars=10).fetch_many(urls)

    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is False
