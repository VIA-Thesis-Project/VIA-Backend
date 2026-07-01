"""Unit tests for TavilySearchClient."""

from __future__ import annotations

import urllib.error

from via.bounded_contexts.recommendation.infrastructure.tavily_search_client import (
    TavilySearchClient,
    TavilySearchConfig,
)


def _client(http_post=None, *, include_domains=(), max_results=5) -> TavilySearchClient:
    return TavilySearchClient(
        TavilySearchConfig(
            api_key="tvly-test",
            max_results=max_results,
            include_domains=include_domains,
        ),
        http_post=http_post,
    )


def _fake_post(results: list[dict]):
    def _post(url: str, body: dict, timeout: int) -> dict:
        return {"results": results}
    return _post


def test_search_returns_parsed_results() -> None:
    http_post = _fake_post([
        {"url": "https://inia.gob.pe/mandarina", "title": "Mandarina INIA", "content": "Requerimientos suelo", "score": 0.9},
        {"url": "https://fao.org/citrus", "title": "FAO Citrus", "content": "pH óptimo 5.5–7.0", "score": 0.7},
    ])

    response = _client(http_post).search("mandarina murcott requerimientos suelo")

    assert len(response.results) == 2
    assert response.results[0].url == "https://inia.gob.pe/mandarina"
    assert response.results[0].title == "Mandarina INIA"
    assert response.results[0].score == 0.9
    assert response.urls == ["https://inia.gob.pe/mandarina", "https://fao.org/citrus"]


def test_search_sends_include_domains_when_configured() -> None:
    captured: dict = {}

    def _post(url: str, body: dict, timeout: int) -> dict:
        captured.update(body)
        return {"results": []}

    _client(_post, include_domains=("inia.gob.pe", "fao.org")).search("query")

    assert captured.get("include_domains") == ["inia.gob.pe", "fao.org"]


def test_search_omits_include_domains_when_empty() -> None:
    captured: dict = {}

    def _post(url: str, body: dict, timeout: int) -> dict:
        captured.update(body)
        return {"results": []}

    _client(_post, include_domains=()).search("query")

    assert "include_domains" not in captured


def test_search_sends_correct_api_key() -> None:
    captured: dict = {}

    def _post(url: str, body: dict, timeout: int) -> dict:
        captured.update(body)
        return {"results": []}

    _client(_post).search("query")

    assert captured.get("api_key") == "tvly-test"
    assert captured.get("include_answer") is False
    assert captured.get("include_raw_content") is False


def test_search_returns_empty_on_http_error() -> None:
    def _post(url: str, body: dict, timeout: int) -> dict:
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]

    response = _client(_post).search("query")

    assert response.results == []
    assert response.urls == []


def test_search_returns_empty_on_network_error() -> None:
    def _post(url: str, body: dict, timeout: int) -> dict:
        raise TimeoutError("timed out")

    response = _client(_post).search("query")

    assert response.results == []


def test_search_skips_results_without_url() -> None:
    http_post = _fake_post([
        {"url": "", "title": "Sin URL", "content": "contenido", "score": 0.5},
        {"url": "https://inia.gob.pe/valid", "title": "Válido", "content": "ok", "score": 0.8},
    ])

    response = _client(http_post).search("query")

    assert len(response.results) == 1
    assert response.results[0].url == "https://inia.gob.pe/valid"
