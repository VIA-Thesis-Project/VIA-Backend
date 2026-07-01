"""Tavily RAG recommendation drafting provider.

Three-step pipeline with hard domain filtering:
  1. Tavily Search (``include_domains`` enforced server-side) → filtered URLs + snippets
  2. Jina Reader (optional) → full document/PDF content from top URLs
  3. OpenAI Chat Completions → structured recommendation draft

Unlike ``openai_web_search``, the domain list is a hard filter applied by Tavily's API,
not a soft prompt instruction that the model can ignore.
"""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from via.bounded_contexts.recommendation.application.ports import RecommendationDraftContext
from via.bounded_contexts.recommendation.domain.value_objects import RecommendationDomainError
from via.bounded_contexts.recommendation.infrastructure.jina_reader_client import (
    JinaReaderClient,
    JinaReaderResult,
)
from via.bounded_contexts.recommendation.infrastructure.openai_file_search_provider import (
    INSUFFICIENT_EVIDENCE_MSG,
    MIN_DRAFT_CHARS,
    _build_system_prompt,
    _build_user_prompt,
    _parse_structured_output,
    _render_structured_output,
)
from via.bounded_contexts.recommendation.infrastructure.tavily_search_client import (
    TavilySearchClient,
    TavilySearchResult,
)

logger = logging.getLogger(__name__)


class TavilyRagError(RecommendationDomainError):
    """Raised when Tavily RAG drafting cannot be completed."""


@dataclass(frozen=True)
class TavilyRagConfig:
    """Configuration for the Tavily RAG drafting provider."""

    openai_api_key: str
    openai_model: str
    prompt_version: str
    timeout_seconds: int
    tavily_api_key: str
    tavily_max_results: int = 5
    tavily_search_depth: str = "advanced"
    include_domains: tuple[str, ...] = ()
    max_output_tokens: int | None = None


@dataclass
class TavilyRagTrace:
    """Trazabilidad de una llamada Tavily RAG."""

    evaluation_id: str
    crop_id: str
    model: str
    prompt_version: str
    tavily_queries: list[str]
    tavily_results: list[dict]
    source_urls: list[str]
    jina_enriched_urls: list[str]
    generated_recommendation: str
    created_at: str
    warnings: list[str] = field(default_factory=list)

    @property
    def retrieved_results(self) -> list[dict]:
        """Expose Tavily results in the format expected by _file_search_evidence_from_provider."""
        return [
            {
                "text": r.get("content", ""),
                "file_id": "",
                "source_url": r.get("url", ""),
                "filename": "",
                "score": r.get("score"),
            }
            for r in self.tavily_results
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "crop_id": self.crop_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "tavily_queries": self.tavily_queries,
            "tavily_results": self.tavily_results,
            "source_urls": self.source_urls,
            "jina_enriched_urls": self.jina_enriched_urls,
            "generated_recommendation": self.generated_recommendation,
            "created_at": self.created_at,
            "warnings": self.warnings,
        }


class IOpenAICompletionsClient(Protocol):
    """Minimal injectable interface for OpenAI Chat Completions (used in tests)."""

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
        max_output_tokens: int | None = None,
    ) -> str:
        """Return assistant message text. Raise on error."""


class TavilyRagDraftingProvider:
    """Draft recommendations using Tavily Search → Jina Reader → OpenAI Completions."""

    def __init__(
        self,
        config: TavilyRagConfig,
        tavily_client: TavilySearchClient | None = None,
        jina_client: JinaReaderClient | None = None,
        openai_client: IOpenAICompletionsClient | None = None,
    ) -> None:
        self._config = config
        from via.bounded_contexts.recommendation.infrastructure.tavily_search_client import (
            TavilySearchConfig,
        )
        self._tavily = tavily_client or TavilySearchClient(
            TavilySearchConfig(
                api_key=config.tavily_api_key,
                max_results=config.tavily_max_results,
                search_depth=config.tavily_search_depth,
                include_domains=config.include_domains,
                timeout_seconds=config.timeout_seconds,
            )
        )
        self._jina = jina_client
        self._openai: IOpenAICompletionsClient = openai_client or _RealOpenAICompletionsClient(
            api_key=config.openai_api_key,
        )
        self._last_trace: TavilyRagTrace | None = None
        self._last_structured_output: dict | None = None

    def draft(self, context: RecommendationDraftContext) -> str:
        """Draft a recommendation using the three-step Tavily RAG pipeline."""
        self._last_structured_output = None
        crop_id = context.crop_result.crop_id
        warnings: list[str] = []

        # ── Pre-filter: drop STRUCTURAL gaps (altitude, topography, etc.) ───────
        actionable = _actionable_gaps(context)
        structural_skipped = len(context.crop_result.gaps) - len(actionable)
        if structural_skipped:
            warnings.append(
                f"{structural_skipped} brecha(s) STRUCTURAL excluidas de la busqueda "
                "(altitud, topografia u otras condiciones no modificables a nivel de parcela)."
            )
            logger.info(
                "[VIA-TAVILY-FILTER] crop=%s | structural_skipped=%d | actionable=%d",
                crop_id, structural_skipped, len(actionable),
            )
        actionable_context = replace(
            context,
            crop_result=replace(context.crop_result, gaps=actionable),
        )

        # ── Step 1: Tavily search (one query per criterion group) ────────────
        queries = _build_tavily_queries(actionable_context)
        all_results: list = []
        seen_urls: set[str] = set()
        for query in queries:
            resp = self._tavily.search(query)
            if not resp.results:
                warnings.append(f"Tavily sin resultados para: '{query[:60]}'.")
            for r in resp.results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
        source_urls = [r.url for r in all_results]
        tavily_dicts = [_result_to_dict(r) for r in all_results]
        logger.info(
            "[VIA-TAVILY-MULTI] crop=%s | n_queries=%d | n_unique_results=%d",
            crop_id, len(queries), len(all_results),
        )
        if not all_results:
            warnings.append("Tavily no devolvió resultados para ninguna consulta.")

        # ── Step 2: Jina Reader (optional full-text enrichment) ───────────────
        jina_enriched_urls: list[str] = []
        jina_docs_text = ""
        if self._jina and source_urls:
            jina_results = self._jina.fetch_many(source_urls)
            successful = [r for r in jina_results if r.success]
            if successful:
                jina_enriched_urls = [r.url for r in successful]
                jina_docs_text = _format_jina_docs(successful)
                logger.info(
                    "[VIA-TAVILY-JINA] crop=%s | n_docs=%d | chars=%d",
                    crop_id,
                    len(successful),
                    sum(r.chars for r in successful),
                )
            else:
                warnings.append("Jina Reader no recuperó contenido de las URLs de Tavily.")

        # ── Step 3: OpenAI Chat Completions ───────────────────────────────────
        system_prompt = _build_tavily_system_prompt(self._config.prompt_version)
        user_prompt = _build_tavily_user_prompt(
            actionable_context,
            all_results,
            jina_docs_text,
            self._config.include_domains,
        )

        started = time.perf_counter()
        try:
            text = self._openai.create_completion(
                model=self._config.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=self._config.timeout_seconds,
                max_output_tokens=self._config.max_output_tokens,
            )
        except Exception as exc:
            raise TavilyRagError(
                f"OpenAI completions falló en Tavily RAG: {exc.__class__.__name__}: {exc}"
            ) from exc
        elapsed = time.perf_counter() - started

        logger.info(
            "[VIA-TAVILY-RAG-LATENCY] crop=%s | t_llm=%.3fs | n_tavily=%d | n_jina=%d | model=%s",
            crop_id,
            elapsed,
            len(all_results),
            len(jina_enriched_urls),
            self._config.openai_model,
        )

        structured_output = _parse_structured_output(text, warnings)
        if structured_output is not None:
            text = _render_structured_output(structured_output)

        if not text.strip() or len(text.strip()) < MIN_DRAFT_CHARS:
            text = INSUFFICIENT_EVIDENCE_MSG
            structured_output = None

        self._last_structured_output = structured_output
        self._last_trace = TavilyRagTrace(
            evaluation_id=str(context.evaluation_id),
            crop_id=crop_id,
            model=self._config.openai_model,
            prompt_version=self._config.prompt_version,
            tavily_queries=queries,
            tavily_results=tavily_dicts,
            source_urls=source_urls,
            jina_enriched_urls=jina_enriched_urls,
            generated_recommendation=text,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            warnings=warnings,
        )
        return text

    def get_last_trace(self) -> TavilyRagTrace | None:
        return self._last_trace

    def get_last_structured_output(self) -> dict | None:
        return self._last_structured_output


# ── Helpers ───────────────────────────────────────────────────────────────────


_GROUP_QUERY_TEMPLATES: dict[str, str] = {
    "clima": "{crop} sistema riego goteo aspersion calendario fenologico manejo agua produccion Peru",
    "suelo": "{crop} incorporar materia organica compost estiercol enmiendas corregir pH azufre cal produccion Peru",
    "pendiente": "{crop} labranza minima curvas nivel terrazas cobertura vegetal conservacion suelo Peru",
    "altitud": "{crop} altitud temperatura manejo agronomico produccion Peru",
    "salinidad": "{crop} lavado sales yeso agricola drenaje lixiviacion CE conductividad electrica manejo suelo Peru",
}


def _actionable_gaps(context: RecommendationDraftContext) -> list:
    """Return gaps that have an actionable intervention class (not STRUCTURAL)."""
    return [
        g for g in context.crop_result.gaps
        if getattr(g, "intervention_class", None) != "STRUCTURAL"
    ]


def _build_tavily_queries(context: RecommendationDraftContext) -> list[str]:
    """Build one targeted query per criterion group from actionable gaps."""
    crop_name = context.crop_result.crop_id.replace("_", " ")
    groups = list(
        dict.fromkeys(
            g.criterion_group
            for g in context.crop_result.gaps
            if getattr(g, "criterion_group", None)
        )
    )
    if not groups:
        return [f"{crop_name} manejo agronomico requerimientos produccion Peru"]
    return [
        _GROUP_QUERY_TEMPLATES.get(
            group,
            "{crop} manejo {group} requerimientos agronomicos produccion Peru",
        ).format(crop=crop_name, group=group)
        for group in groups
    ]


def _build_tavily_query(context: RecommendationDraftContext) -> str:
    """Legacy single-query builder — returns first query from _build_tavily_queries."""
    return _build_tavily_queries(context)[0]


def _build_tavily_system_prompt(prompt_version: str) -> str:
    return (
        _build_system_prompt(prompt_version)
        + "\n\nMODO TAVILY RAG — las siguientes reglas REEMPLAZAN las restricciones de evidencia anteriores:\n"
        "\nPOLITICA DE EVIDENCIA (RELAJADA PARA BUSQUEDA WEB):\n"
        "- Acepta como evidencia suficiente cualquier fuente que describa practicas de manejo "
        "del cultivo, suelo, riego o condiciones agronomicas, aunque no cite el nombre exacto "
        "del criterio VIA. El criterio y la practica recomendada deben estar relacionados logicamente.\n"
        "- Declara evidencia insuficiente SOLO si las fuentes no contienen ninguna informacion "
        "sobre el tema agronomico de la brecha (ni directa ni indirectamente).\n"
        "\nREGLAS DE RECOMENDACION ACCIONABLE (OBLIGATORIAS):\n"
        "1. PROHIBIDO usar 'verificar', 'validar', 'confirmar' o 'revisar los datos' como recomendacion "
        "principal. El agricultor ya tiene los datos calculados por VIA; necesita saber QUE HACER. "
        "Si la evidencia es indirecta, da igual la practica concreta y registra la limitacion en "
        "el campo 'limitations'.\n"
        "2. Cada recommendation debe contener al menos un verbo de accion directa: "
        "'aplicar', 'incorporar', 'instalar', 'sembrar', 'realizar', 'adoptar', 'ajustar', "
        "'establecer', 'utilizar', 'reducir', 'aumentar (dosis o frecuencia, no textura fisica)'.\n"
        "3. TEXTURA DE SUELO (contenido_arena, contenido_arcilla): NO recomiendes 'aumentar el "
        "contenido de arena/arcilla' directamente — es impracticable a escala de parcela. "
        "En cambio recomienda: incorporacion de materia organica para mejorar estructura, "
        "labranza minima para conservar agregados, cobertura vegetal (mulch), riego adaptado "
        "a la textura actual (goteo para suelos arenosos, surcos para arcillosos).\n"
        "4. pH (reaccion_suelo_ph): si el pH observado es mayor que el optimo (alcalino), "
        "recomienda aplicacion de azufre elemental o sulfato de aluminio; si es menor (acido), "
        "recomienda encalado con cal agricola o cal dolomita. Incluye dosis orientativas "
        "si la evidencia las menciona.\n"
        "5. DEFICIT HIDRICO (deficit_hidrico, precipitacion): recomienda instalar riego por goteo "
        "o aspersion segun la disponibilidad del cultivo, definir calendarios de riego por fase "
        "fenologica, aplicar mulch organico para reducir evapotranspiracion, o complementar con "
        "reservorios si el deficit es severo. No digas solo 'manejo adecuado del riego'.\n"
        "6. CARBONO ORGANICO (carbono_organico_suelo): recomienda incorporacion de estiercol "
        "descompuesto (t/ha si la fuente lo indica), compost, abonos verdes o cultivos de "
        "cobertura entre campanas. Menciona la especie o producto si la fuente lo cita. "
        "IMPORTANTE: un valor observado de 0.0 g/kg es un resultado valido del sensor GEE — "
        "indica suelo con contenido de carbono organico muy bajo o casi nulo. "
        "No interpretes el cero como dato faltante o erroneo; da directamente la recomendacion "
        "de incorporacion de materia organica para este caso.\n"
        "7. SALINIDAD (salinidad_suelo / conductividad_electrica): recomienda acciones de "
        "manejo concretas: lavado de sales con laminas de agua (m3/ha si la fuente lo indica), "
        "aplicacion de yeso agricola (sulfato de calcio, t/ha), mejora del drenaje subsuperficial, "
        "seleccion de portainjertos tolerantes a sal, o fraccionamiento del riego para lixiviar "
        "sales. Menciona la dosis o lamina si la fuente la cita. "
        "No digas solo 'reducir la salinidad' — indica el metodo especifico.\n"
        "\nFORMATO DE EVIDENCIA PARA TAVILY:\n"
        "- En evidence_used usa: source_file_id=<URL exacta de la lista>, "
        "source_filename='' (dejar vacio), quote_summary=<frase clave del documento>.\n"
        "- Usa solo las fuentes entregadas en el prompt; no inventes URLs adicionales.\n"
        "- Incluye rangos numericos concretos cuando esten disponibles en los documentos.\n"
        "- Marca confianza segun la especificidad: alta=rango numerico exacto del cultivo, "
        "media=practica mencionada para el cultivo, baja=referencia general de manejo.\n"
    )


def _build_tavily_user_prompt(
    context: RecommendationDraftContext,
    tavily_results: list[TavilySearchResult],
    jina_docs_text: str,
    include_domains: tuple[str, ...],
) -> str:
    domains = ", ".join(include_domains) if include_domains else "sin filtro"
    base = _build_user_prompt(context)

    snippets_block = ""
    if tavily_results:
        lines = [
            f"[{i + 1}] {r.title}\nURL: {r.url}\n{r.content}"
            for i, r in enumerate(tavily_results)
        ]
        snippets_block = "\n\n".join(lines)
    else:
        snippets_block = "(sin resultados de Tavily Search)"

    prompt = (
        base
        + f"\n\nFUENTES RECUPERADAS — Tavily Search (dominios permitidos: {domains}):\n"
        + snippets_block
    )

    if jina_docs_text:
        prompt += "\n\nCONTENIDO COMPLETO — Jina Reader (texto íntegro de documentos):\n" + jina_docs_text

    prompt += (
        "\n\nINSTRUCCIÓN: Fundamenta cada recomendación en las fuentes de arriba. "
        "En evidence_used: source_file_id=<URL exacta de la lista>, "
        "source_filename=<dominio>, quote_summary=<cita o resumen del párrafo relevante>. "
        "No cites URLs que no aparezcan en las fuentes entregadas. "
        "Si no hay evidencia suficiente para una brecha, marca evidencia insuficiente."
    )
    return prompt


def _format_jina_docs(results: list[JinaReaderResult]) -> str:
    return "\n\n".join(
        f"--- DOCUMENTO {i + 1} ---\nFuente: {r.url}\n\n{r.text}"
        for i, r in enumerate(results)
    )


def _result_to_dict(r: TavilySearchResult) -> dict[str, Any]:
    return {
        "url": r.url,
        "title": r.title,
        "content": r.content[:500],
        "score": r.score,
    }


class _RealOpenAICompletionsClient:
    """Wraps OpenAI Chat Completions API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

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
            raise TavilyRagError(
                "El paquete 'openai' es requerido para el provider tavily_rag. "
                "Instalalo con: pip install openai"
            ) from exc

        client = OpenAI(api_key=self._api_key, timeout=float(timeout))
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
            raise TavilyRagError(
                f"OpenAI chat completions falló: {exc.__class__.__name__}: {exc}"
            ) from exc
