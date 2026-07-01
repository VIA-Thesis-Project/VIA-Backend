"""OpenAI Web Search recommendation drafting provider.

This provider is an optional "lab mode" for exploring current public web
sources. It does not replace the curated vector-store provider used for thesis
and controlled production runs.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from via.bounded_contexts.recommendation.application.ports import RecommendationDraftContext
from via.bounded_contexts.recommendation.infrastructure.openai_file_search_provider import (
    INSUFFICIENT_EVIDENCE_MSG,
    MIN_DRAFT_CHARS,
    _build_system_prompt,
    _build_user_prompt,
    _parse_structured_output,
    _render_structured_output,
    _sdk_response_to_dict,
)
from via.bounded_contexts.recommendation.infrastructure.jina_reader_client import (
    JinaReaderClient,
    JinaReaderResult,
)
from via.bounded_contexts.recommendation.domain.value_objects import RecommendationDomainError

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class OpenAIWebSearchError(RecommendationDomainError):
    """Raised when OpenAI Web Search drafting cannot be completed."""


@dataclass(frozen=True)
class OpenAIWebSearchConfig:
    """Configuration for the OpenAI Web Search drafting provider."""

    api_key: str
    model: str
    prompt_version: str
    timeout_seconds: int
    allowed_domains: tuple[str, ...] = ()
    search_context_size: str = "medium"
    user_country: str | None = "PE"
    user_region: str | None = "Lima"
    max_output_tokens: int | None = None


@dataclass
class WebSearchTrace:
    """Trazabilidad de una llamada a OpenAI Responses API con Web Search."""

    evaluation_id: str
    crop_id: str
    model: str
    prompt_version: str
    response_id: str
    web_search_call_ids: list[str]
    retrieved_results: list[dict]
    source_urls: list[str]
    generated_recommendation: str
    created_at: str
    raw_output_validation_status: str
    warnings: list[str] = field(default_factory=list)
    jina_enriched_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "crop_id": self.crop_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "response_id": self.response_id,
            "web_search_call_ids": self.web_search_call_ids,
            "retrieved_results": self.retrieved_results,
            "source_urls": self.source_urls,
            "generated_recommendation": self.generated_recommendation,
            "created_at": self.created_at,
            "raw_output_validation_status": self.raw_output_validation_status,
            "warnings": self.warnings,
            "jina_enriched_urls": self.jina_enriched_urls,
        }


class IOpenAIWebSearchClient(Protocol):
    """Injectable client for the OpenAI Responses API with Web Search."""

    def create_response(
        self,
        *,
        model: str,
        input_messages: list[dict[str, str]],
        tool: dict[str, Any],
        timeout: int,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call Responses API and return raw response as a plain dict."""

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
        max_output_tokens: int | None = None,
    ) -> str:
        """Call chat completions and return the assistant message text."""


class OpenAIWebSearchDraftingProvider:
    """Draft recommendations using OpenAI Responses API + Web Search."""

    def __init__(
        self,
        config: OpenAIWebSearchConfig,
        client: IOpenAIWebSearchClient | None = None,
        jina_client: JinaReaderClient | None = None,
    ) -> None:
        self._config = config
        self._client: IOpenAIWebSearchClient = client or _RealOpenAIWebSearchClient(
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
        )
        self._jina_client = jina_client
        self._last_trace: WebSearchTrace | None = None
        self._last_structured_output: dict | None = None

    def draft(self, context: RecommendationDraftContext) -> str:
        """Draft a recommendation using public web search."""

        self._last_structured_output = None
        crop_id = context.crop_result.crop_id
        system_prompt = _build_web_system_prompt(self._config.prompt_version)
        user_prompt = _build_web_user_prompt(context, self._config.allowed_domains)
        tool = _build_web_search_tool(self._config)

        started = time.perf_counter()
        raw = self._client.create_response(
            model=self._config.model,
            input_messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tool=tool,
            timeout=self._config.timeout_seconds,
            max_output_tokens=self._config.max_output_tokens,
        )
        elapsed = time.perf_counter() - started

        text, call_ids, results, urls, warnings = _parse_web_response(raw)
        logger.info(
            "[VIA-WEB-RAG-LATENCY] crop=%s | t_api=%.3fs | n_results=%d | model=%s",
            crop_id,
            elapsed,
            len(results),
            self._config.model,
        )

        # ── Jina Reader enrichment (second pass) ──────────────────────────────
        jina_enriched_urls: list[str] = []
        if self._jina_client and urls:
            text, jina_enriched_urls, warnings = _jina_second_pass(
                client=self._client,
                jina_client=self._jina_client,
                context=context,
                config=self._config,
                discovery_urls=urls,
                fallback_text=text,
                warnings=warnings,
            )

        structured_output = _parse_structured_output(text, warnings)
        if structured_output is not None:
            text = _render_structured_output(structured_output)
        validation_status = "ok"

        if not results and not jina_enriched_urls:
            warnings.append("Web Search no recupero citas URL verificables.")
            validation_status = "no_web_citations"

        if not text.strip() or len(text.strip()) < MIN_DRAFT_CHARS:
            text = INSUFFICIENT_EVIDENCE_MSG
            validation_status = "insufficient_text"
            structured_output = None

        self._last_structured_output = structured_output
        self._last_trace = WebSearchTrace(
            evaluation_id=str(context.evaluation_id),
            crop_id=crop_id,
            model=self._config.model,
            prompt_version=self._config.prompt_version,
            response_id=raw.get("id", ""),
            web_search_call_ids=call_ids,
            retrieved_results=results,
            source_urls=urls,
            generated_recommendation=text,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            raw_output_validation_status=validation_status,
            warnings=warnings,
            jina_enriched_urls=jina_enriched_urls,
        )
        return text

    def get_last_trace(self) -> WebSearchTrace | None:
        """Return trace from the most recent draft() call."""

        return self._last_trace

    def get_last_structured_output(self) -> dict | None:
        """Return structured recommendation output from the most recent draft."""

        return self._last_structured_output


def _jina_second_pass(
    *,
    client: IOpenAIWebSearchClient,
    jina_client: JinaReaderClient,
    context: RecommendationDraftContext,
    config: OpenAIWebSearchConfig,
    discovery_urls: list[str],
    fallback_text: str,
    warnings: list[str],
) -> tuple[str, list[str], list[str]]:
    """Fetch full document content via Jina Reader and generate enriched draft.

    Returns (text, jina_enriched_urls, updated_warnings).
    Falls back to fallback_text if enrichment fails or yields no content.
    """
    jina_results = jina_client.fetch_many(discovery_urls)
    successful = [r for r in jina_results if r.success]
    if not successful:
        warnings.append("Jina Reader no recuperó contenido útil de las URLs descubiertas.")
        return fallback_text, [], warnings

    enriched_urls = [r.url for r in successful]
    enriched_prompt = _build_jina_enriched_user_prompt(context, successful, config.allowed_domains)
    logger.info(
        "[VIA-JINA-SECOND-PASS] crop=%s | n_docs=%d | chars=%d",
        context.crop_result.crop_id,
        len(successful),
        sum(r.chars for r in successful),
    )
    try:
        enriched_text = client.create_completion(
            model=config.model,
            messages=[
                {"role": "system", "content": _build_web_system_prompt(config.prompt_version)},
                {"role": "user", "content": enriched_prompt},
            ],
            timeout=config.timeout_seconds,
            max_output_tokens=config.max_output_tokens,
        )
    except Exception as exc:
        warnings.append(f"Jina second pass LLM call falló: {exc}")
        return fallback_text, enriched_urls, warnings

    if enriched_text.strip():
        return enriched_text, enriched_urls, warnings
    warnings.append("Jina second pass devolvió texto vacío; usando borrador web search.")
    return fallback_text, enriched_urls, warnings


def _build_jina_enriched_user_prompt(
    context: RecommendationDraftContext,
    jina_results: list[JinaReaderResult],
    allowed_domains: tuple[str, ...],
) -> str:
    domains = ", ".join(allowed_domains) if allowed_domains else "sin filtro de dominio"
    docs = "\n\n".join(
        f"--- DOCUMENTO {i + 1} ---\nFuente: {r.url}\n\n{r.text}"
        for i, r in enumerate(jina_results)
    )
    return (
        _build_user_prompt(context)
        + f"\n\nDOCUMENTOS RECUPERADOS (texto completo vía Jina Reader):\n"
        f"Dominios preferidos: {domains}\n\n"
        + docs
        + "\n\nINSTRUCCIÓN JINA: Usa el contenido completo de estos documentos para fundamentar "
        "las recomendaciones. Incluye rangos numéricos concretos, citas textuales y referencias "
        "específicas. Para cada evidence_used, usa source_file_id=<URL del documento>, "
        "source_filename=<dominio>, quote_summary=<cita o resumen del párrafo relevante>."
    )


def _build_web_system_prompt(prompt_version: str) -> str:
    return (
        _build_system_prompt(prompt_version)
        + "\n\nMODO WEB SEARCH EXPERIMENTAL:\n"
        "- Usa solo fuentes web recuperadas por la herramienta.\n"
        "- Prioriza fuentes oficiales o tecnicas de dominios permitidos.\n"
        "- Incluye URLs reales en evidence_used como source_file_id cuando cites evidencia.\n"
        "- Nunca inventes URLs ni uses dominios de ejemplo como example.com, ejemplo.com o placeholders.\n"
        "- Si no tienes una URL real recuperada para una brecha, marca evidencia insuficiente.\n"
        "- Marca confianza media o baja si la evidencia web no es directa.\n"
        "- No presentes este modo como salida reproducible de tesis.\n"
    )


def _build_web_user_prompt(
    context: RecommendationDraftContext,
    allowed_domains: tuple[str, ...],
) -> str:
    domains = ", ".join(allowed_domains) if allowed_domains else "sin filtro de dominio configurado"
    return (
        _build_user_prompt(context)
        + "\n\nINSTRUCCION WEB SEARCH:\n"
        f"- Dominios permitidos/preferidos: {domains}.\n"
        "- Busca evidencia actual para las brechas principales, pero no recalcules MCDA.\n"
        "- Para cada evidence_used usa: source_file_id=<URL>, source_filename=<dominio>, "
        "quote_summary=<resumen breve>, retrieved_at=<fecha actual>.\n"
        "- source_file_id debe ser una URL real abierta por Web Search; no uses URLs ficticias.\n"
    )


def _build_web_search_tool(config: OpenAIWebSearchConfig) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": "web_search",
        "search_context_size": config.search_context_size,
    }
    user_location = _build_user_location(config)
    if user_location:
        tool["user_location"] = user_location
    return tool


def _build_user_location(config: OpenAIWebSearchConfig) -> dict[str, str] | None:
    if not config.user_country and not config.user_region:
        return None
    location = {"type": "approximate"}
    if config.user_country:
        location["country"] = config.user_country
    if config.user_region:
        location["region"] = config.user_region
    return location


def _parse_web_response(raw: dict[str, Any]) -> tuple[str, list[str], list[dict], list[str], list[str]]:
    output = raw.get("output") or []
    text_parts: list[str] = []
    call_ids: list[str] = []
    results: list[dict] = []
    urls: list[str] = []
    warnings: list[str] = []

    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")
        if item_type in {"web_search_call", "web_search_preview_call"} and item.get("id"):
            call_ids.append(str(item.get("id")))
            for source in _sources_from_web_search_call(item):
                _append_result(results, urls, source)
        if item_type != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            part_text = str(part.get("text") or "")
            text_parts.append(part_text)
            for annotation in part.get("annotations") or []:
                entry = _annotation_to_result(annotation, part_text)
                if entry is None:
                    continue
                _append_result(results, urls, entry)
            for url in _urls_from_text(part_text):
                _append_result(results, urls, _text_url_to_result(url, part_text))

    text = "".join(text_parts)
    if not text.strip():
        warnings.append("La respuesta de OpenAI Web Search no contiene texto.")
    return text, call_ids, results, urls, warnings


def _sources_from_web_search_call(item: dict[str, Any]) -> list[dict[str, Any]]:
    action = item.get("action") if isinstance(item.get("action"), dict) else {}
    sources = action.get("sources") if isinstance(action, dict) else None
    if not isinstance(sources, list):
        return []
    results: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or _domain_from_url(url)).strip()
        snippet = str(source.get("snippet") or source.get("text") or "").strip()
        results.append(
            {
                "source_url": url,
                "source_title": title,
                "source_domain": _domain_from_url(url),
                "text": _source_text(title=title, snippet=snippet, url=url),
                "score": None,
            }
        )
    return results


def _annotation_to_result(annotation: dict[str, Any], text: str) -> dict[str, Any] | None:
    if not isinstance(annotation, dict):
        return None
    url = str(annotation.get("url") or "").strip()
    if not url:
        return None
    title = str(annotation.get("title") or _domain_from_url(url)).strip()
    start = annotation.get("start_index")
    end = annotation.get("end_index")
    cited_text = ""
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
        cited_text = text[max(0, start - 180): min(len(text), end + 240)].strip()
    return {
        "source_url": url,
        "source_title": title,
        "source_domain": _domain_from_url(url),
        "text": _source_text(title=title, snippet=cited_text, url=url),
        "score": None,
    }


def _text_url_to_result(url: str, text: str) -> dict[str, Any]:
    title = _domain_from_url(url)
    return {
        "source_url": url,
        "source_title": title,
        "source_domain": title,
        "text": _source_text(title=title, snippet=_context_around_url(url, text), url=url),
        "score": None,
    }


def _append_result(results: list[dict], urls: list[str], entry: dict[str, Any]) -> None:
    url = str(entry.get("source_url") or "").strip()
    if not url or _is_placeholder_url(url):
        return
    if url not in urls:
        urls.append(url)
        results.append(entry)
        return
    index = urls.index(url)
    existing = results[index]
    if _is_sparse_source_text(str(existing.get("text") or ""), url) and not _is_sparse_source_text(
        str(entry.get("text") or ""), url
    ):
        merged = dict(existing)
        merged.update({key: value for key, value in entry.items() if value not in (None, "")})
        results[index] = merged


def _urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(text):
        url = match.group(0).replace("\\/", "/").rstrip(".,;:)]}\"'")
        if url and not _is_placeholder_url(url) and url not in urls:
            urls.append(url)
    return urls


def _context_around_url(url: str, text: str) -> str:
    index = text.find(url)
    if index < 0:
        return ""
    return text[max(0, index - 220) : min(len(text), index + len(url) + 260)].strip()


def _source_text(*, title: str, snippet: str, url: str) -> str:
    domain = _domain_from_url(url)
    parts = [title.strip(), snippet.strip(), f"Fuente: {domain}", url.strip()]
    text = ". ".join(dict.fromkeys(part for part in parts if part))
    return text[:1200]


def _is_sparse_source_text(text: str, url: str) -> bool:
    normalized = text.strip().lower()
    domain = _domain_from_url(url).lower()
    return len(normalized) < 40 or normalized in {domain, url.lower()}


def _is_placeholder_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    normalized = f"{host}{parsed.path}".lower()
    return (
        host in {"example.com", "www.example.com", "ejemplo.com", "www.ejemplo.com"}
        or ".example." in host
        or any(term in normalized for term in ("placeholder", "dummy", "fake", "ejemplo"))
    )


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or url


class _RealOpenAIWebSearchClient:
    """Wraps the OpenAI Python SDK Responses API."""

    def __init__(self, api_key: str, timeout_seconds: int) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def create_response(
        self,
        *,
        model: str,
        input_messages: list[dict[str, str]],
        tool: dict[str, Any],
        timeout: int,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIWebSearchError(
                "El paquete 'openai' es requerido para el provider openai_web_search. "
                "Instalalo con: pip install openai"
            ) from exc

        client = OpenAI(api_key=self._api_key, timeout=float(timeout or self._timeout_seconds))
        extra: dict[str, Any] = {}
        if max_output_tokens is not None:
            extra["max_output_tokens"] = max_output_tokens
        try:
            response = client.responses.create(
                model=model,
                input=input_messages,
                tools=[tool],
                include=["web_search_call.action.sources"],
                **extra,
            )
        except Exception as exc:
            raise OpenAIWebSearchError(
                f"OpenAI Responses API con Web Search fallo: {exc.__class__.__name__}: {exc}"
            ) from exc

        return _sdk_response_to_dict(response)

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
        max_output_tokens: int | None = None,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIWebSearchError(
                "El paquete 'openai' es requerido para el segundo pase Jina."
            ) from exc

        client = OpenAI(api_key=self._api_key, timeout=float(timeout or self._timeout_seconds))
        extra: dict[str, Any] = {}
        if max_output_tokens is not None:
            extra["max_tokens"] = max_output_tokens
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **extra,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise OpenAIWebSearchError(
                f"OpenAI chat completions falló en segundo pase Jina: {exc.__class__.__name__}: {exc}"
            ) from exc
