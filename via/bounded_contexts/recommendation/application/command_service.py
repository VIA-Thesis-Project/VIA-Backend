"""Application service for supported recommendation generation."""

from __future__ import annotations

import copy
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.recommendation.application.gap_analysis import analyse_gaps
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvidenceData,
    IDocumentEvidencePort,
    IEvaluationResultsPort,
    IRecommendationDraftingProvider,
    IRecommendationRepository,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.domain.evidence import DocumentaryEvidence
from via.bounded_contexts.recommendation.domain.recommendation import Recommendation
from via.bounded_contexts.recommendation.domain.section import RecommendationSection
from via.bounded_contexts.recommendation.domain.value_objects import (
    RecommendationDomainError,
    RecommendationSectionType,
)
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import IdempotentConsumerMixin
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA
from via.shared.orchestration.evaluation_process_manager.events import RECOMENDACION_FALLIDA, RECOMENDACION_GENERADA
from via.shared.outbox.outbox_writer import OutboxWriter


RECOMMENDATION_CONSUMER = "recommendation-consumer"
AGGREGATE_TYPE = "Recommendation"
INSUFFICIENT_EVIDENCE_MSG = (
    "No se encontro evidencia documental suficiente para sustentar una recomendacion especifica sobre esta brecha."
)


@dataclass(frozen=True)
class GenerateRecommendationCommand:
    """Command to draft a supported recommendation for one evaluation."""

    evaluation_id: UUID
    crop_id: str | None = None
    max_fragments: int = 5
    persist: bool = True

    @classmethod
    def from_payload(cls, payload: dict) -> "GenerateRecommendationCommand":
        """Deserialize a GenerarRecomendacionSolicitada payload."""

        return cls(
            evaluation_id=UUID(str(payload["evaluation_id"])),
            crop_id=payload.get("crop_id"),
            max_fragments=int(payload.get("max_fragments", 5)),
            persist=True,
        )


class RecommendationCommandService:
    """Create recommendations from existing evaluation results and evidence."""

    def __init__(
        self,
        evaluation_results_port: IEvaluationResultsPort,
        evidence_port: IDocumentEvidencePort,
        drafting_provider: IRecommendationDraftingProvider,
        repository: IRecommendationRepository | None = None,
    ) -> None:
        """Create the service with injectable ports."""

        self._evaluation_results_port = evaluation_results_port
        self._evidence_port = evidence_port
        self._drafting_provider = drafting_provider
        self._repository = repository

    def generate(self, command: GenerateRecommendationCommand) -> Recommendation:
        """Draft and optionally persist a recommendation."""

        if command.max_fragments <= 0:
            raise RecommendationDomainError("max_fragments must be positive")
        evaluation = self._evaluation_results_port.get_results_for_recommendation(command.evaluation_id)
        crop_result = _select_crop_result(evaluation.crop_results, command.crop_id)
        evidence = self._evidence_port.search_evidence(
            crop_id=crop_result.crop_id,
            gaps=crop_result.gaps,
            max_fragments=command.max_fragments,
        )
        gap_analysis = analyse_gaps(crop_result)
        context = RecommendationDraftContext(
            evaluation_id=command.evaluation_id,
            crop_result=crop_result,
            evidence=evidence,
            gap_analysis=gap_analysis,
        )
        text = self._drafting_provider.draft(context)
        evidence = evidence or _file_search_evidence_from_provider(
            self._drafting_provider,
            crop_result.crop_id,
            command.max_fragments,
        )
        structured_output = _structured_output_from_provider(
            self._drafting_provider,
            crop_result,
            text,
            evidence,
        )
        structured_output = _quality_control_structured_output(
            structured_output, evidence, crop_result.crop_id, crop_result.viability_category
        )
        text = _render_visible_text(structured_output, text)
        recommendation = Recommendation(
            evaluation_id=command.evaluation_id,
            crop_id=crop_result.crop_id,
            text=text,
            sections=_build_sections(crop_result, evidence),
            evidence=[_evidence_to_domain(item) for item in evidence],
            structured_output=structured_output,
        )
        if command.persist and self._repository is not None:
            self._repository.save(recommendation)
        return recommendation


class RecommendationMessageCommandService(IdempotentConsumerMixin):
    """Consume recommendation generation messages idempotently."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        service_factory: Callable[[Session], RecommendationCommandService],
        outbox_writer: OutboxWriter | None = None,
    ) -> None:
        """Create the message service with transactional dependencies."""

        self._session_factory = session_factory
        self._service_factory = service_factory
        self._outbox_writer = outbox_writer or OutboxWriter()

    def handle_generation_requested(self, message: Message, consumer_name: str = RECOMMENDATION_CONSUMER) -> None:
        """Handle one GenerarRecomendacionSolicitada command."""

        if message.type != GENERAR_RECOMENDACION_SOLICITADA:
            return
        command = GenerateRecommendationCommand.from_payload(message.payload)
        with self._transaction() as session:
            if self.is_already_processed(session, message.id, consumer_name):
                return

            try:
                recommendation = self._service_factory(session).generate(command)
                self._outbox_writer.write(
                    session,
                    _recommendation_generated_event(
                        recommendation,
                        correlation_id=_outgoing_correlation_id(message, command.evaluation_id),
                    ),
                    AGGREGATE_TYPE,
                    recommendation.id,
                )
            except RecommendationDomainError as exc:
                self._outbox_writer.write(
                    session,
                    _recommendation_failed_event(
                        command.evaluation_id,
                        str(exc),
                        correlation_id=_outgoing_correlation_id(message, command.evaluation_id),
                    ),
                    "EvaluationSaga",
                    command.evaluation_id,
                )

            self.mark_as_processed(session, message.id, consumer_name)

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        """Open a synchronous session and commit or roll back as one unit."""

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _select_crop_result(
    crop_results: list[CropEvaluationResultData],
    crop_id: str | None,
) -> CropEvaluationResultData:
    if not crop_results:
        raise RecommendationDomainError("evaluation results are required")
    if crop_id is not None:
        for result in crop_results:
            if result.crop_id == crop_id:
                return result
        raise RecommendationDomainError(f"crop result not found: {crop_id}")

    if len(crop_results) == 1:
        return crop_results[0]

    top_ranked = [result for result in crop_results if result.rank_position == 1]
    if not top_ranked:
        raise RecommendationDomainError("rank_position=1 is required when crop_id is not provided")
    if len(top_ranked) > 1:
        raise RecommendationDomainError("ambiguous rank_position=1 results when crop_id is not provided")
    return top_ranked[0]


def _build_sections(
    crop_result: CropEvaluationResultData,
    evidence: list[EvidenceData],
) -> list[RecommendationSection]:
    return [
        RecommendationSection(
            section_type=RecommendationSectionType.SUMMARY,
            title="Resumen",
            content=f"Recomendacion sustentada para {crop_result.crop_id}.",
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.VIABILITY_RESULT,
            title="Resultado de viabilidad",
            content=(
                f"Score={crop_result.score}; condicion={crop_result.calc_condition}; "
                f"categoria={crop_result.viability_category}; ranking={crop_result.rank_position}."
            ),
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.AGRONOMIC_GAPS,
            title="Brechas agronomicas",
            content="; ".join(
                f"{gap.criterion_id}/{gap.phase_id}: {gap.gap_value}"
                for gap in crop_result.gaps
            )
            or "No se recibieron brechas agronomicas.",
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.LIMITING_FACTORS,
            title="Factores limitantes",
            content="; ".join(
                f"{factor.criterion_id}/{factor.phase_id}: {factor.policy}"
                for factor in crop_result.limiting_factors
            )
            or "No se recibieron factores limitantes.",
        ),
        RecommendationSection(
            section_type=RecommendationSectionType.DOCUMENTARY_EVIDENCE,
            title="Evidencia documental",
            content="; ".join(str(item.fragment_id) for item in evidence)
            or "No se encontro evidencia documental suficiente.",
        ),
    ]


def _evidence_to_domain(item: EvidenceData) -> DocumentaryEvidence:
    return DocumentaryEvidence(
        fragment_id=item.fragment_id,
        document_id=item.document_id,
        text=item.text,
        crop_tags=item.crop_tags,
        page_ref=item.page_ref,
        score=item.score,
        source_filename=item.source_filename,
        source_file_id=item.source_file_id,
    )


def _file_search_evidence_from_provider(
    drafting_provider: IRecommendationDraftingProvider,
    crop_id: str,
    max_fragments: int,
) -> list[EvidenceData]:
    get_last_trace = getattr(drafting_provider, "get_last_trace", None)
    if not callable(get_last_trace):
        return []
    trace = get_last_trace()
    if trace is None:
        return []

    evidence: list[EvidenceData] = []
    for index, result in enumerate(getattr(trace, "retrieved_results", []) or []):
        if len(evidence) >= max_fragments:
            break
        if not isinstance(result, dict):
            continue
        text = str(result.get("text") or "").strip()
        if not text:
            continue
        file_id = str(result.get("file_id") or "").strip()
        filename = str(result.get("filename") or "").strip()
        source_key = file_id or filename or f"result-{index}"
        score = result.get("score")
        evidence.append(
            EvidenceData(
                fragment_id=uuid5(
                    NAMESPACE_URL,
                    f"openai-file-search:fragment:{source_key}:{index}:{text[:200]}",
                ),
                document_id=uuid5(NAMESPACE_URL, f"openai-file-search:document:{source_key}"),
                text=text,
                crop_tags=[crop_id],
                score=score if isinstance(score, (int, float)) and 0.0 <= float(score) <= 1.0 else None,
                source_filename=filename or None,
                source_file_id=file_id or None,
            )
        )
    return evidence


def _structured_output_from_provider(
    drafting_provider: IRecommendationDraftingProvider,
    crop_result: CropEvaluationResultData,
    text: str,
    evidence: list[EvidenceData],
) -> dict:
    get_last_structured_output = getattr(drafting_provider, "get_last_structured_output", None)
    if callable(get_last_structured_output):
        structured = get_last_structured_output()
        if _is_valid_structured_output(structured):
            return structured
    return _fallback_structured_output(crop_result, text, evidence)


def _quality_control_structured_output(
    structured_output: dict,
    evidence: list[EvidenceData],
    crop_id: str | None = None,
    viability_category: str | None = None,
) -> dict:
    controlled = copy.deepcopy(structured_output)
    controlled["schema_version"] = "recommendation_structured_v1"
    controlled["quality_control"] = {
        "max_visible_recommendations": 5,
        "evidence_policy": "criterion_phase_or_practice_overlap_required",
    }
    if viability_category:
        controlled["viability_category"] = viability_category

    # ── Preserve LLM raw output for traceability ────────────────────────────
    controlled["llm_raw_output"] = {
        "summary": controlled.get("summary"),
        "gap_recommendations_count": len(controlled.get("gap_recommendations") or []),
    }

    items = controlled.get("gap_recommendations") or []
    normalized_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        checked = _quality_control_item(item, evidence, crop_id)
        normalized_items.append(checked)

    normalized_items.sort(key=_recommendation_priority_key)

    # ── Separate suspects: they must NOT appear in gap_recommendations ───────
    suspect_items = _dedupe_mapping_suspects(
        [it for it in normalized_items if it.get("criterion_mapping_suspect")]
    )
    actionable_items = [it for it in normalized_items if not it.get("criterion_mapping_suspect")]

    controlled["gap_recommendations"] = actionable_items
    controlled["pending_methodological_validation"] = suspect_items

    controlled["visible_gap_keys"] = [
        str(item.get("gap_key") or "")
        for item in actionable_items[:5]
        if item.get("gap_key")
    ]
    if len(actionable_items) > 5:
        limitation = "Se muestran como maximo 5 recomendaciones priorizadas por severidad y evidencia."
        current = str(controlled.get("overall_limitations") or "").strip()
        controlled["overall_limitations"] = f"{current} {limitation}".strip()

    # ── Programmatic summary when suspects present (no LLM text for actions) ─
    if suspect_items:
        controlled["summary"] = _generate_qc_summary(viability_category, actionable_items, suspect_items)

    return controlled


def _quality_control_item(item: dict, evidence: list[EvidenceData], crop_id: str | None = None) -> dict:
    checked = dict(item)
    checked.setdefault("evidence_used", [])
    checked["evidence_status"] = "compatible"

    _normalize_limitations_field(checked)

    _rewrite_unsafe_clay_recommendation(checked)
    _rewrite_unsafe_thermal_recommendation(checked, crop_id)
    _sanitize_perennial_annual_language(checked, crop_id)
    _sanitize_maiz_huerto_language(checked, crop_id)
    _rewrite_unsafe_arena_recommendation(checked)
    _guard_mandarina_controlled_hydric_stress(checked)

    if _has_invalid_crop_phase(checked, crop_id):
        checked["unsafe_recommendation"] = True
        checked["evidence_status"] = "insuficiente"
        checked["confidence"] = "baja"
        checked["recommendation"] = None
        checked["rationale"] = None
        checked["evidence_used"] = []
        checked["limitations"] = _append_limitation(
            checked.get("limitations"),
            "La recomendacion contiene una fase fenologica que no pertenece al cultivo evaluado.",
        )
        return checked

    if _has_suspect_heat_mapping(checked):
        checked["criterion_mapping_suspect"] = True
        checked["evidence_status"] = "insuficiente"
        checked["confidence"] = "baja"
        checked["recommendation"] = None
        checked["rationale"] = None
        checked["evidence_used"] = []
        checked["mapping_validation_note"] = (
            "El criterio riesgo_calor aparece con direccion below_optimum. VIA debe validar si "
            "corresponde a aptitud termica insuficiente antes de recomendar evitar temperaturas excesivas."
        )
        checked["limitations"] = _append_limitation(
            checked.get("limitations"),
            "riesgo_calor/below_optimum requiere validacion de mapeo antes de recomendar.",
        )
        return checked

    if _has_suspect_hydric_as_altitude(checked):
        checked["criterion_mapping_suspect"] = True
        checked["evidence_status"] = "insuficiente"
        checked["confidence"] = "baja"
        checked["recommendation"] = None
        checked["rationale"] = None
        checked["evidence_used"] = []
        checked["mapping_validation_note"] = (
            "Los valores observados y el limite optimo de este criterio son consistentes con altitud "
            "(msnm), no con deficit hidrico (mm). Requiere revision del mapeo en el rulebook: "
            "verificar si este criterion_id corresponde a aptitud_altitudinal u otro criterio "
            "topografico antes de emitir recomendaciones."
        )
        checked["limitations"] = _append_limitation(
            checked.get("limitations"),
            "Posible mapeo incorrecto: valores en rango de altitud etiquetados como deficit hidrico.",
        )
        return checked

    compatible_refs = _compatible_evidence_refs(checked, evidence)
    if not compatible_refs:
        checked["evidence_status"] = "insuficiente"
        checked["confidence"] = "baja"
        checked["recommendation"] = None
        checked["rationale"] = None
        checked["evidence_used"] = []
        checked["limitations"] = _append_limitation(
            checked.get("limitations"),
            "La evidencia recuperada no menciona explicitamente el criterio, fase o practica recomendada.",
        )
    else:
        checked["evidence_used"] = compatible_refs
        if _has_only_indirect_soil_evidence(checked, evidence):
            checked["evidence_status"] = "compatible_indirecta"
            checked["confidence"] = "baja"
            checked["limitations"] = _append_limitation(
                checked.get("limitations"),
                "La evidencia de suelo es compatible pero indirecta para esta brecha fisica especifica.",
            )
        if _requires_explicit_controlled_hydric_stress_evidence(checked) and not _has_explicit_wmurcott_sayan_evidence(compatible_refs, evidence):
            checked["evidence_status"] = "insuficiente"
            checked["confidence"] = "baja"
            checked["recommendation"] = None
            checked["rationale"] = None
            checked["evidence_used"] = []
            checked["limitations"] = _append_limitation(
                checked.get("limitations"),
                "El estres hidrico controlado requiere evidencia explicita de W. Murcott/Sayan para la fase indicada.",
            )
        criterion_name = checked.get("criterion_name")
        for ref in checked["evidence_used"]:
            if isinstance(ref, dict) and not ref.get("source_locator"):
                filename = ref.get("source_filename") or ""
                if filename.endswith(".md"):
                    ref["source_locator"] = _compute_source_locator(criterion_name, filename, crop_id)

    if checked.get("confidence") == "alta" and len(compatible_refs) < 2:
        checked["confidence"] = "media"
        checked["limitations"] = _append_limitation(
            checked.get("limitations"),
            "La evidencia es compatible pero no suficientemente directa para confianza alta.",
        )
    return checked


def _dedupe_mapping_suspects(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        if not item.get("criterion_mapping_suspect"):
            result.append(item)
            continue
        key = _normalize_text(str(item.get("criterion_name") or item.get("criterion_id") or item.get("gap_key") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _visible_recommendation_items(items: list[dict], limit: int) -> list[dict]:
    return [item for item in items if not item.get("criterion_mapping_suspect")][:limit]


def _rewrite_unsafe_clay_recommendation(item: dict) -> None:
    criterion_text = _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("criterion_name", "criterion_label", "recommendation", "rationale")
        )
    )
    if "arcilla" not in criterion_text:
        return
    recommendation = _normalize_text(str(item.get("recommendation") or ""))
    if "aumentar" not in recommendation and "incrementar" not in recommendation:
        return
    item["recommendation"] = (
        "Mejorar la retencion de humedad y la estructura del suelo mediante incorporacion "
        "de materia organica, cobertura, preparacion adecuada del terreno y ajuste de la "
        "frecuencia de riego. No se recomienda plantear el aumento directo de arcilla como "
        "medida principal."
    )
    item["confidence"] = _min_confidence(item.get("confidence"), "media")
    item["limitations"] = _append_limitation(
        item.get("limitations"),
        "VIA ajusto una recomendacion no practica sobre aumento directo de arcilla.",
    )


def _rewrite_unsafe_thermal_recommendation(item: dict, crop_id: str | None = None) -> None:
    """Rewrite aptitud_termica/below_optimum recs that use riego as primary temperature fix."""
    criterion_text = _normalize_text(
        " ".join(str(item.get(k) or "") for k in ("criterion_name", "criterion_label"))
    )
    if "aptitud_termica" not in criterion_text and "aptitud termica" not in criterion_text:
        return
    if _normalize_text(str(item.get("gap_direction") or "")) != "below_optimum":
        return
    norm_rec = _normalize_text(str(item.get("recommendation") or ""))
    if _is_perennial_crop(crop_id) and _uses_perennial_sowing_calendar_as_action(norm_rec):
        item["recommendation"] = (
            "Evaluar aptitud termica para instalacion/renovacion del cultivo perenne y ajustar "
            "manejo fenologico en plantas establecidas, sin aplicar logica de cultivo anual."
        )
        item["confidence"] = _min_confidence(item.get("confidence"), "media")
        item["limitations"] = _append_limitation(
            item.get("limitations"),
            "VIA ajusto lenguaje de cultivo anual para cultivo perenne.",
        )
        return
    if "riego" not in norm_rec:
        return
    if any(t in norm_rec for t in ("siembra", "ventana", "fenologia")):
        return
    item["recommendation"] = (
        "Ajustar la ventana de siembra para evitar que el panojamiento y la floracion coincidan "
        "con periodos frios o nublados. Priorizar campanas donde las fases reproductivas ocurran "
        "bajo condiciones termicas cercanas al rango favorable documentado."
    )
    item["confidence"] = _min_confidence(item.get("confidence"), "media")
    item["limitations"] = _append_limitation(
        item.get("limitations"),
        "VIA ajusto una recomendacion que usaba riego como accion principal para correccion termica.",
    )


def _is_perennial_crop(crop_id: str | None) -> bool:
    return crop_id in {
        "palta_hass",
        "mandarina_murcott",
        "maracuya_criolla_amarilla",
        "uva_de_mesa_sweet_globe",
    }


def _uses_perennial_sowing_calendar_as_action(normalized_recommendation: str) -> bool:
    return any(
        term in normalized_recommendation
        for term in (
            "ventana de siembra",
            "calendario de siembra",
            "fecha de siembra",
            "fechas de siembra",
            "campana",
            "campanas",
            "siembra",
        )
    )


def _sanitize_perennial_annual_language(item: dict, crop_id: str | None) -> None:
    if not _is_perennial_crop(crop_id):
        return
    fields = ("recommendation", "rationale", "limitations", "mapping_validation_note")
    has_annual_language = any(
        _uses_perennial_sowing_calendar_as_action(_normalize_text(str(item.get(field) or "")))
        for field in fields
    )
    if not has_annual_language:
        return
    if item.get("recommendation"):
        item["recommendation"] = (
            "Evaluar aptitud termica para instalacion/renovacion del cultivo perenne y ajustar "
            "manejo fenologico en plantas establecidas, sin aplicar logica de cultivo anual."
        )
    for field in ("rationale", "limitations", "mapping_validation_note"):
        if item.get(field):
            item[field] = _remove_annual_crop_terms(str(item[field]))
    item["limitations"] = _append_limitation(
        item.get("limitations"),
        "VIA removio lenguaje de cultivo anual para este cultivo perenne.",
    )
    item["confidence"] = _min_confidence(item.get("confidence"), "media")


def _sanitize_maiz_huerto_language(item: dict, crop_id: str | None) -> None:
    if crop_id != "maiz_amarillo_duro":
        return
    fields = ("recommendation", "rationale", "limitations", "mapping_validation_note")
    if not any(_has_huerto_language(str(item.get(field) or "")) for field in fields):
        return
    for field in fields:
        if item.get(field):
            item[field] = _replace_huerto_language(str(item[field]))
    item["limitations"] = _append_limitation(
        item.get("limitations"),
        "VIA ajusto lenguaje perenne para cultivo anual.",
    )
    item["confidence"] = _min_confidence(item.get("confidence"), "media")


def _remove_annual_crop_terms(value: str) -> str:
    replacements = {
        "ventana de siembra": "manejo fenologico",
        "calendario de siembra": "manejo fenologico",
        "fechas de siembra": "manejo fenologico",
        "fecha de siembra": "manejo fenologico",
        "campañas": "periodos fenologicos",
        "campaña": "periodo fenologico",
        "campanas": "periodos fenologicos",
        "campana": "periodo fenologico",
    }
    result = value
    for old, new in replacements.items():
        result = result.replace(old, new).replace(old.capitalize(), new.capitalize())
    return result


def _has_huerto_language(value: str) -> bool:
    normalized = _normalize_text(value)
    return any(term in normalized for term in ("huerto", "huertos establecidos", "renovacion del huerto"))


def _replace_huerto_language(value: str) -> str:
    replacements = {
        "huertos establecidos": "lotes establecidos",
        "Huertos establecidos": "Lotes establecidos",
        "renovacion del huerto": "ajuste del lote",
        "Renovacion del huerto": "Ajuste del lote",
        "renovación del huerto": "ajuste del lote",
        "Renovación del huerto": "Ajuste del lote",
        "cultivo perenne": "cultivo anual",
        "Cultivo perenne": "Cultivo anual",
        "plantas establecidas": "lotes establecidos",
        "Plantas establecidas": "Lotes establecidos",
        "huerto": "lote",
        "Huerto": "Lote",
    }
    result = value
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def _rewrite_unsafe_arena_recommendation(item: dict) -> None:
    """Rewrite contenido_arena recs that suggest directly modifying soil texture."""
    criterion_text = _normalize_text(
        " ".join(str(item.get(k) or "") for k in ("criterion_name", "criterion_label"))
    )
    if "contenido_arena" not in criterion_text and "contenido arena" not in criterion_text:
        return
    norm_rec = _normalize_text(str(item.get("recommendation") or ""))
    unsafe = (
        "controlar la textura",
        "controlar textura",
        "modificar textura",
        "modificar la textura",
        "cambiar textura",
        "cambiar la textura",
        "reducir arena",
        "aumentar arena",
        "aumentar la arena",
        "elevar arena",
        "elevar la arena",
        "incrementar arena",
        "incrementar la arena",
        "reducir la arena",
        "mejorar la proporcion de arena",
        "mejorar proporcion de arena",
    )
    if not any(u in norm_rec for u in unsafe):
        return
    item["recommendation"] = (
        "Validar la textura mediante analisis fisico de suelo. Si la baja proporcion de arena "
        "refleja un suelo pesado o de baja aireacion, priorizar mejora de estructura, drenaje, "
        "materia organica y manejo de riego. No plantear cambios directos de textura como medida principal."
    )
    item["confidence"] = _min_confidence(item.get("confidence"), "media")
    item["limitations"] = _append_limitation(
        item.get("limitations"),
        "VIA ajusto una recomendacion que planteaba modificar directamente la textura del suelo.",
    )


def _guard_mandarina_controlled_hydric_stress(item: dict) -> None:
    haystack = _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("criterion_name", "criterion_label", "phase_name", "recommendation", "rationale")
        )
    )
    if "deficit_hidrico" not in haystack:
        return
    if not any(term in haystack for term in ("estres hidrico controlado", "deficit hidrico controlado", "induccion")):
        return
    phase = _normalize_text(str(item.get("phase_name") or item.get("phase_id") or ""))
    if any(term in phase for term in ("induccion", "floracion", "cuajado")):
        return
    item["recommendation"] = None
    item["rationale"] = None
    item["confidence"] = "baja"
    item["evidence_status"] = "insuficiente"
    item["limitations"] = _append_limitation(
        item.get("limitations"),
        "El estres hidrico controlado en mandarina solo puede recomendarse con evidencia explicita para induccion/floracion.",
    )


def _requires_explicit_controlled_hydric_stress_evidence(item: dict) -> bool:
    haystack = _normalize_text(
        " ".join(str(item.get(key) or "") for key in ("criterion_name", "recommendation", "rationale"))
    )
    if "deficit_hidrico" not in haystack:
        return False
    return any(term in haystack for term in ("estres hidrico controlado", "deficit hidrico controlado", "induccion"))


def _has_explicit_wmurcott_sayan_evidence(refs: list[dict], evidence: list[EvidenceData]) -> bool:
    for ref in refs:
        matched = _match_evidence(ref, evidence)
        if matched is None:
            continue
        haystack = _normalize_text(" ".join([matched.text, matched.source_filename or ""]))
        if ("murcott" in haystack or "wmurcott" in haystack or "w murcott" in haystack) and (
            "sayan" in haystack or "sayán" in haystack
        ):
            return True
    return False


def _has_compatible_evidence(item: dict, evidence: list[EvidenceData]) -> bool:
    return bool(_compatible_evidence_refs(item, evidence))


def _has_strong_evidence_alignment(item: dict, evidence: list[EvidenceData]) -> bool:
    return len(_compatible_evidence_refs(item, evidence)) >= 2


def _compatible_evidence_refs(item: dict, evidence: list[EvidenceData]) -> list[dict]:
    refs = item.get("evidence_used") or []
    compatible_refs: list[dict] = []
    preferred_refs = _preferred_curated_evidence_refs(item, evidence)
    if _is_soil_physical_item(item):
        return preferred_refs
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if not _is_valid_llm_evidence_ref(ref):
            continue
        matched = _match_evidence(ref, evidence)
        if matched is None or not _evidence_matches_item(item, matched):
            continue
        compatible_refs.append(_evidence_to_structured_ref(matched))
    if preferred_refs:
        return preferred_refs
    return compatible_refs


def _preferred_curated_evidence_refs(item: dict, evidence: list[EvidenceData]) -> list[dict]:
    preferred_filenames = _preferred_curated_filenames(item)
    if not preferred_filenames:
        return []
    refs = []
    for evidence_item in evidence:
        filename = evidence_item.source_filename or ""
        if filename not in preferred_filenames:
            continue
        if not _is_valid_retrieved_evidence_ref(evidence_item):
            continue
        if not _evidence_matches_item(item, evidence_item):
            continue
        refs.append(_evidence_to_structured_ref(evidence_item))
    return refs


def _is_valid_llm_evidence_ref(ref: dict) -> bool:
    source_file_id = str(ref.get("source_file_id") or "").strip()
    fragment_id = str(ref.get("fragment_id") or "").strip()
    source_filename = str(ref.get("source_filename") or "").strip()
    if not fragment_id and not source_file_id and not source_filename:
        return False
    if source_file_id and _is_placeholder_source_file_id(source_file_id):
        return False
    if source_filename and not _is_valid_corpus_filename(source_filename):
        return False
    # Filename-only refs are accepted when the filename is a valid corpus file
    if not fragment_id and not source_file_id:
        return bool(source_filename)
    return True


def _is_placeholder_source_file_id(value: str) -> bool:
    normalized = _normalize_text(value).replace("-", "_").strip()
    if normalized.isdigit():
        return True
    return normalized in {"...", "source_file_id", "file_id", "placeholder", "null", "none"} or any(
        term in normalized for term in ("fake", "dummy", "example", "ejemplo")
    )


def _is_valid_corpus_filename(value: str) -> bool:
    filename = value.strip()
    if not filename:
        return False
    if filename in {"archivo.md", "archivo.pdf", "..."}:
        return False
    return filename.endswith((".md", ".pdf", ".json"))


def _is_valid_retrieved_evidence_ref(evidence: EvidenceData) -> bool:
    source_file_id = str(evidence.source_file_id or "").strip()
    source_filename = str(evidence.source_filename or "").strip()
    if source_file_id and _is_placeholder_source_file_id(source_file_id):
        return False
    if source_filename and not _is_valid_corpus_filename(source_filename):
        return False
    return bool(source_file_id or evidence.fragment_id)


def _preferred_curated_filenames(item: dict) -> set[str]:
    if _is_soil_physical_item(item):
        return {"suelo.md"}
    haystack = _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("criterion_group", "criterion_name", "criterion_label", "recommendation")
        )
    )
    mapping = {
        "clima_fenologia.md": ("clima", "temperatura", "riesgo_frio", "aptitud_termica"),
        "riego.md": ("riego", "agua", "hidrico", "humedad"),
        "agua_riego.md": ("riego", "agua", "hidrico", "humedad", "requerimiento_hidrico"),
        "suelo.md": ("suelo", "textura", "arcilla", "materia_organica", "ph", "drenaje"),
        "fertilizacion.md": ("fertilizacion", "nutricion", "nitrogeno", "fosforo", "potasio", "nutrientes"),
        "fertilizacion_nutricion.md": ("fertilizacion", "nutricion", "nitrogeno", "fosforo", "potasio", "analisis_foliar"),
        "malezas_sanidad.md": ("malezas", "sanidad", "plagas", "enfermedades"),
        "sanidad.md": ("sanidad", "plagas", "enfermedades", "mip", "phytophthora", "antracnosis"),
        "sanidad_mip.md": ("sanidad", "plagas", "enfermedades", "mip", "trips", "acaros", "queresa"),
        "sanidad_mip_bpa.md": ("sanidad", "plagas", "enfermedades", "mip", "bpa", "oidio", "botrytis"),
        "cosecha_postcosecha.md": ("cosecha", "postcosecha", "calidad_grano"),
        "cosecha_postcosecha_calidad.md": ("cosecha", "postcosecha", "calidad", "exportacion", "madurez"),
        "siembra_manejo.md": ("siembra", "densidad", "semilla", "manejo"),
        "instalacion_material_vegetal.md": ("instalacion", "establecimiento", "material_vegetal", "planton", "vivero"),
        "polinizacion_floracion.md": ("floracion", "polinizacion", "cuajado", "abejas", "induccion_floral"),
        "polinizacion_floracion_cuajado.md": ("floracion", "polinizacion", "cuajado", "fecundacion", "xylocopa"),
        "floracion_cuajado_raleo_calibre.md": ("floracion", "cuajado", "raleo", "calibre", "baya"),
        "induccion_floracion_cuajado.md": ("induccion_floral", "floracion", "cuajado", "estres_hidrico", "brotacion"),
        "propagacion_vivero_material.md": ("propagacion", "vivero", "material_vegetal", "semilla", "germinacion"),
        "instalacion_conduccion_podas.md": ("instalacion", "establecimiento", "conduccion", "poda", "tutorado"),
        "instalacion_conduccion_canopia_podas.md": ("instalacion", "establecimiento", "conduccion", "canopia", "poda"),
        "hybridos_variedades.md": ("hibrido", "variedad"),
        "variedades_portainjertos.md": ("variedad", "portainjerto", "hass"),
        "material_varietal_portainjerto.md": ("variedad", "portainjerto", "sweet_globe", "material_vegetal"),
        "certificacion_exportacion.md": ("certificacion", "exportacion", "fitosanitaria", "calidad"),
        "fitosanitario_exportacion_trazabilidad.md": ("fitosanitario", "certificacion", "exportacion", "trazabilidad"),
        "mercado_cadena_productiva.md": ("mercado", "cadena_productiva", "comercializacion", "exportacion"),
        "mercado_varietal_exportacion.md": ("mercado", "varietal", "exportacion", "sweet_globe", "calibre"),
    }
    return {
        filename
        for filename, terms in mapping.items()
        if any(term in haystack for term in terms)
    }


def _is_soil_physical_item(item: dict) -> bool:
    group = _normalize_text(str(item.get("criterion_group") or ""))
    criterion = _normalize_text(str(item.get("criterion_name") or item.get("criterion_id") or ""))
    if group == "suelo":
        return True
    return any(
        term in criterion
        for term in (
            "contenido_arena",
            "contenido_arcilla",
            "reaccion_suelo_ph",
            "carbono_organico_suelo",
            "salinidad",
            "profundidad",
        )
    )


def _normalize_limitations_field(item: dict) -> None:
    """Convert 'None'/'null'/'-' string values in limitations to actual None."""
    raw = item.get("limitations")
    if raw is None:
        return
    stripped = str(raw).strip().lower()
    if stripped in ("none", "null", "n/a", "-", "", "no limitations", "no hay limitaciones"):
        item["limitations"] = None


def _has_suspect_hydric_as_altitude(item: dict) -> bool:
    """True when a deficit_hidrico criterion has values in altitude range (msnm)."""
    criterion_name = _normalize_text(str(item.get("criterion_name") or item.get("criterion_id") or ""))
    if "deficit_hidrico" not in criterion_name and "disponibilidad_hidrica" not in criterion_name:
        return False
    observed = item.get("observed_value")
    optimal = item.get("optimal_limit")
    if not isinstance(observed, (int, float)) or not isinstance(optimal, (int, float)):
        return False
    # Values in 800-4500 msnm range with an optimal also in altitude range
    return 800.0 <= float(observed) <= 4_500.0 and 0 < float(optimal) <= 1_200.0


def _generate_qc_summary(
    viability_category: str | None,
    actionable_items: list[dict],
    suspect_items: list[dict],
) -> str:
    """Generate a deterministic, LLM-free summary when suspect criteria are present."""
    viability = str(viability_category or "").upper()
    if viability == "NO_VIABLE":
        base = "El cultivo fue evaluado como NO VIABLE."
    elif viability == "CONDICIONAL":
        base = "El cultivo presenta viabilidad condicional."
    elif viability == "VIABLE":
        base = "El cultivo es viable bajo las condiciones evaluadas."
    else:
        base = "Evaluacion de viabilidad completada."

    n_actionable = sum(1 for it in actionable_items if it.get("recommendation"))
    parts = [base]
    if n_actionable > 0:
        parts.append(
            f"Se identificaron {n_actionable} brecha(s) con recomendacion tecnica sustentada por evidencia documental."
        )
    suspect_names = list(dict.fromkeys(
        str(it.get("criterion_name") or it.get("criterion_id") or "")
        for it in suspect_items
        if it.get("criterion_name") or it.get("criterion_id")
    ))
    names_str = ", ".join(suspect_names[:3]) if suspect_names else "criterios sin nombre"
    parts.append(
        f"{len(suspect_items)} criterio(s) pendiente(s) de validacion metodologica "
        f"({names_str}): no se incluyen en las recomendaciones de manejo hasta que VIA "
        "confirme el mapeo en el rulebook."
    )
    return " ".join(parts)


def _has_suspect_heat_mapping(item: dict) -> bool:
    criterion = _normalize_text(str(item.get("criterion_name") or item.get("criterion_id") or ""))
    gap_direction = _normalize_text(str(item.get("gap_direction") or ""))
    return "riesgo_calor" in criterion and gap_direction == "below_optimum"


def _has_invalid_crop_phase(item: dict, crop_id: str | None) -> bool:
    if crop_id != "mandarina_murcott":
        return False
    haystack = _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("phase_id", "phase_name", "recommendation", "rationale")
        )
    )
    return "panojamiento" in haystack


def _match_evidence(ref: dict, evidence: list[EvidenceData]) -> EvidenceData | None:
    fragment_id = str(ref.get("fragment_id") or "")
    source_file_id = str(ref.get("source_file_id") or "")
    source_filename = str(ref.get("source_filename") or "")
    for item in evidence:
        if fragment_id and str(item.fragment_id) == fragment_id:
            return item
        if source_file_id and item.source_file_id == source_file_id:
            return item
        if source_filename and item.source_filename == source_filename:
            return item
    return None


def _evidence_matches_item(item: dict, evidence: EvidenceData) -> bool:
    haystack = _normalize_text(
        " ".join(
            [
                evidence.text,
                evidence.source_filename or "",
                evidence.source_file_id or "",
            ]
        )
    )
    group = _normalize_text(str(item.get("criterion_group") or ""))
    if group == "clima":
        if any(term in haystack for term in ("plaguicida", "herbicida", "lmr", "carencia")):
            return False
        if any(term in haystack for term in ("clima", "senamhi", "temperatura", "precipitacion", "agroclimat")):
            return True
    if group == "topografia":
        if any(term in haystack for term in ("pendiente", "topografia", "ladera", "erosion", "escorrentia", "surco")):
            return True
        return False
    if group == "suelo":
        filename = _normalize_text(evidence.source_filename or "")
        if filename == "clima_fenologia.md":
            return False
        if any(term in haystack for term in ("plaguicida", "herbicida", "lmr", "carencia")):
            return False
        if any(
            term in haystack
            for term in (
                "suelo",
                "textura",
                "arcilla",
                "arena",
                "materia organica",
                "ph",
                "drenaje",
                "retencion",
                "salinidad",
                "profundidad",
            )
        ):
            return True
    if group == "riego" or any(term in _normalize_text(str(item.get("criterion_name") or "")) for term in ("hidrico", "riego", "agua")):
        if any(term in haystack for term in ("plaguicida", "herbicida", "lmr", "carencia")):
            return False
        if any(
            term in haystack
            for term in ("agua", "riego", "humedad", "requerimiento hidrico", "floracion", "cuajado", "m3/ha", "m³/ha")
        ):
            return True
    if group in {"sanidad", "plagas", "enfermedades"}:
        if any(
            term in haystack
            for term in ("sanidad", "plaga", "enfermedad", "phytophthora", "antracnosis", "mip", "trips", "acaro")
        ):
            return True
        return False
    if group in {"floracion", "polinizacion", "cuajado"}:
        if any(term in haystack for term in ("floracion", "polinizacion", "cuajado", "abeja", "fecundacion", "xylocopa")):
            return True
        return False
    if group in {"instalacion", "material_vegetal", "vivero"}:
        if any(
            term in haystack
            for term in ("instalacion", "planton", "vivero", "material vegetal", "distanciamiento", "conduccion", "poda")
        ):
            return True
        return False

    needles = _semantic_needles(item)
    return any(needle in haystack for needle in needles)


def _has_only_indirect_soil_evidence(item: dict, evidence: list[EvidenceData]) -> bool:
    if not _is_soil_physical_item(item):
        return False
    refs = item.get("evidence_used") or []
    matched = [_match_evidence(ref, evidence) for ref in refs if isinstance(ref, dict)]
    matched = [item for item in matched if item is not None]
    if not matched:
        return False
    return not any(_has_direct_soil_evidence(item, evidence_item) for evidence_item in matched)


def _has_direct_soil_evidence(item: dict, evidence: EvidenceData) -> bool:
    criterion = _normalize_text(str(item.get("criterion_name") or item.get("criterion_id") or ""))
    haystack = _normalize_text(" ".join([evidence.text, evidence.source_filename or ""]))
    if evidence.source_filename == "suelo.md":
        if "contenido_arena" in criterion:
            return any(term in haystack for term in ("arena", "textura", "drenaje", "aireacion"))
        if "contenido_arcilla" in criterion:
            return any(term in haystack for term in ("arcilla", "textura", "drenaje"))
        if "reaccion_suelo_ph" in criterion:
            return "ph" in haystack
        if "carbono_organico_suelo" in criterion:
            return any(term in haystack for term in ("carbono", "materia organica"))
        if "salinidad" in criterion:
            return "salinidad" in haystack
        if "profundidad" in criterion:
            return "profundidad" in haystack
        return True
    return False


def _semantic_needles(item: dict) -> list[str]:
    raw = " ".join(
        str(item.get(key) or "")
        for key in (
            "criterion_name",
            "criterion_label",
            "phase_name",
            "recommendation",
            "rationale",
        )
    )
    tokens = []
    for token in _normalize_text(raw).replace("_", " ").split():
        if len(token) >= 5 and token not in {"recomendacion", "evidencia", "manejo"}:
            tokens.append(token)
    return tokens


_CURATED_SECTION_HINTS: dict[str, dict[str, str]] = {
    "suelo.md": {
        "contenido_arcilla": "Contenido de arcilla",
        "contenido_arena": "Drenaje",
        "carbono_organico_suelo": "Materia organica",
        "reaccion_suelo_ph": "pH",
    },
    "clima_fenologia.md": {
        "aptitud_termica": "Temperatura de siembra y crecimiento",
        "riesgo_frio": "Tiempo termico",
        "riesgo_calor": "Temperaturas altas",
    },
    "riego.md": {
        "disponibilidad_hidrica": "Requerimiento hidrico",
        "deficit_hidrico": "Deficit hidrico",
    },
}

_CURATED_SECTION_HINTS_BY_CROP: dict[str, dict[str, dict[str, str]]] = {
    "mandarina_murcott": {
        "clima_fenologia.md": {
            "aptitud_termica": "Aptitud termica y manejo fenologico",
            "riesgo_frio": "Induccion floral y frio inductivo",
            "riesgo_calor": "Temperaturas altas en floracion y cuajado",
        },
    },
    "palta_hass": {
        "clima_fenologia.md": {
            "aptitud_termica": "Aptitud termica y manejo fenologico",
        },
    },
    "maracuya_criolla_amarilla": {
        "clima_fenologia.md": {
            "aptitud_termica": "Aptitud termica y manejo fenologico",
        },
    },
    "uva_de_mesa_sweet_globe": {
        "clima_fenologia.md": {
            "aptitud_termica": "Aptitud termica y manejo fenologico",
        },
    },
}

def _compute_source_locator(criterion_name: str | None, source_filename: str | None, crop_id: str | None = None) -> str | None:
    """Return a section-level locator for curated .md files; None for PDFs."""
    if not source_filename or not source_filename.endswith(".md"):
        return None
    key = _normalize_text(str(criterion_name or "")).replace(" ", "_")
    section = _CURATED_SECTION_HINTS_BY_CROP.get(str(crop_id or ""), {}).get(source_filename, {}).get(key)
    if section is None:
        section = _CURATED_SECTION_HINTS.get(source_filename, {}).get(key)
    return f"{source_filename} > {section}" if section else source_filename


def _split_soil_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate soil items from everything else for compact visible rendering."""
    soil: list[dict] = []
    others: list[dict] = []
    for item in items:
        if isinstance(item, dict) and _is_soil_physical_item(item):
            soil.append(item)
        else:
            others.append(item)
    return soil, others


def _render_soil_group_lines(lines: list[str], index: int, soil_items: list[dict]) -> None:
    """Render multiple soil brechas as a single grouped visible block."""
    order = {"alta": 2, "media": 1, "baja": 0}
    group_confidence = min(
        (item.get("confidence") or "baja" for item in soil_items),
        key=lambda c: order.get(c, 0),
        default="baja",
    )
    criterion_labels = list(dict.fromkeys(
        str(item.get("criterion_label") or item.get("criterion_name") or "")
        for item in soil_items
        if item.get("criterion_label") or item.get("criterion_name")
    ))
    has_actionable_soil = any(item.get("recommendation") for item in soil_items)
    merged_rec = (
        "Atender estas brechas como una condicion integrada de suelo: validar textura, pH, salinidad, "
        "profundidad y materia organica con analisis de suelo; priorizar mejora de estructura, drenaje, "
        "cobertura, aporte organico y ajuste de riego segun resultados."
        if has_actionable_soil
        else "No se emite una accion correctiva especifica porque la evidencia compatible fue insuficiente. "
        "Priorizar analisis fisico-quimico de suelo y validacion tecnica local antes de intervenir."
    )
    evidence_names: list[str] = []
    for item in soil_items:
        for ref in item.get("evidence_used") or []:
            if isinstance(ref, dict):
                fn = str(ref.get("source_filename") or ref.get("source_file_id") or "")
                if fn and fn not in evidence_names:
                    evidence_names.append(fn)
    limitations = list(dict.fromkeys(
        str(item["limitations"]) for item in soil_items
        if item.get("limitations") and str(item["limitations"]).strip().lower() not in ("none", "null", "")
    ))
    lines.append(f"{index}. Condicion fisica y organica del suelo (confianza: {group_confidence})")
    lines.append(f"Brechas detectadas: {', '.join(criterion_labels)}.")
    lines.append(str(merged_rec))
    if evidence_names:
        lines.append(f"Evidencia: {', '.join(dict.fromkeys(evidence_names))}.")
    for lim in limitations:
        if lim and str(lim).strip().lower() not in ("none", "null", ""):
            lines.append(f"Limitacion: {lim}")
    lines.append("")


def _render_single_item_lines(lines: list[str], index: int, item: dict) -> None:
    """Render one gap recommendation as a numbered visible block."""
    title = item.get("criterion_label") or item.get("criterion_name") or item.get("gap_key")
    confidence = item.get("confidence") or "baja"
    if item.get("criterion_mapping_suspect"):
        recommendation_text = item.get("mapping_validation_note") or INSUFFICIENT_EVIDENCE_MSG
    else:
        recommendation_text = _limit_words(item.get("recommendation") or INSUFFICIENT_EVIDENCE_MSG, 120)
    evidence_names = [
        str(ref.get("source_filename") or ref.get("source_file_id"))
        for ref in item.get("evidence_used") or []
        if isinstance(ref, dict) and (ref.get("source_filename") or ref.get("source_file_id"))
    ]
    lines.append(f"{index}. {title} (confianza: {confidence})")
    lines.append(str(recommendation_text))
    if evidence_names:
        lines.append(f"Evidencia: {', '.join(dict.fromkeys(evidence_names))}.")
    limitations = item.get("limitations")
    if limitations and str(limitations).strip().lower() not in ("none", "null", ""):
        lines.append(f"Limitacion: {limitations}")
    lines.append("")


def _render_mapping_suspect_group_lines(lines: list[str], index: int, suspect_items: list[dict]) -> None:
    """Render mapping validation warnings as one visible block."""
    labels = list(
        dict.fromkeys(
            str(item.get("criterion_label") or item.get("criterion_name") or item.get("gap_key") or "")
            for item in suspect_items
            if item.get("criterion_label") or item.get("criterion_name") or item.get("gap_key")
        )
    )
    notes = list(
        dict.fromkeys(
            str(item.get("mapping_validation_note") or item.get("limitations") or "")
            for item in suspect_items
            if item.get("mapping_validation_note") or item.get("limitations")
        )
    )
    lines.append(f"{index}. Criterios pendientes de validacion metodologica (confianza: baja)")
    if labels:
        lines.append(f"Criterios: {', '.join(labels)}.")
    if notes:
        lines.append(_limit_words(" ".join(notes), 140))
    else:
        lines.append("VIA debe validar el mapeo metodologico antes de emitir recomendaciones para estos criterios.")
    lines.append("")


def _recommendation_priority_key(item: dict) -> tuple[int, int, int]:
    severity_rank = {"alta": 0, "media": 1, "baja": 2, "sin_brecha": 3}
    evidence_rank = {"compatible": 0, "compatible_indirecta": 1, "insuficiente": 2}
    return (
        1 if item.get("criterion_mapping_suspect") else 0,
        severity_rank.get(str(item.get("severity") or "").lower(), 4),
        evidence_rank.get(str(item.get("evidence_status") or "").lower(), 2),
    )


def _render_visible_text(structured_output: dict, fallback_text: str) -> str:
    if structured_output.get("generated_by") == "via_fallback":
        return fallback_text
    summary = str(structured_output.get("summary") or "").strip()
    items = structured_output.get("gap_recommendations") or []
    # suspects live in their own key, not mixed into gap_recommendations
    suspect_items: list[dict] = [
        item for item in (structured_output.get("pending_methodological_validation") or [])
        if isinstance(item, dict)
    ]
    visible_keys = set(str(key) for key in structured_output.get("visible_gap_keys") or [])
    has_visible_selection = "visible_gap_keys" in structured_output
    if has_visible_selection:
        items = [
            item
            for item in items
            if str(item.get("gap_key") or "") in visible_keys
            or _is_soil_physical_item(item)
        ]
    actionable_items = [item for item in items if isinstance(item, dict) and item.get("recommendation")]
    viability = str(structured_output.get("viability_category") or "").upper()
    if items and not actionable_items and not suspect_items:
        if viability == "CONDICIONAL":
            summary = (
                "El cultivo presenta viabilidad condicional. No fue posible emitir recomendaciones "
                "tecnicas sustentadas para las brechas detectadas porque la evidencia recuperada no "
                "fue compatible o los criterios requieren validacion metodologica previa. "
                "Se recomienda: (1) validar en campo los criterios senalados como pendientes; "
                "(2) realizar analisis de suelo y evaluacion de condiciones microlocales; "
                "(3) consultar con tecnico agronomico especializado antes de implementar el cultivo."
            )
        elif viability == "NO_VIABLE":
            summary = (
                "El cultivo es NO VIABLE bajo las condiciones evaluadas. Los criterios con brechas "
                "estructurales dominantes no pueden corregirse con manejo agronomico. "
                "No se genera plan de instalacion ni de manejo productivo."
            )
        else:
            summary = (
                "No se pudo emitir una recomendacion tecnica confiable porque la evidencia recuperada "
                "no fue suficiente o no fue compatible con las brechas detectadas."
            )
    if not summary and not items and not suspect_items:
        return fallback_text
    lines = ["# Recomendacion tecnica agricola", ""]
    if summary:
        lines += ["## Resumen", summary, ""]
    if items or suspect_items:
        lines += ["## Recomendaciones priorizadas", ""]
        soil_items, other_items = _split_soil_items(items)
        render_queue: list[tuple[str, object]] = []
        if soil_items:
            render_queue.append(("soil_group", soil_items))
        for item in other_items:
            render_queue.append(("single", item))
        if suspect_items:
            render_queue.append(("mapping_suspects", suspect_items))
        for index, (kind, data) in enumerate(render_queue, start=1):
            if kind == "soil_group":
                _render_soil_group_lines(lines, index, data)  # type: ignore[arg-type]
            elif kind == "mapping_suspects":
                _render_mapping_suspect_group_lines(lines, index, data)  # type: ignore[arg-type]
            else:
                _render_single_item_lines(lines, index, data)  # type: ignore[arg-type]
    limitations = structured_output.get("overall_limitations")
    if limitations:
        lines += ["## Limites", str(limitations), ""]
    return "\n".join(lines).strip()


def _append_limitation(current, addition: str) -> str:
    current_text = str(current or "").strip()
    if not current_text:
        return addition
    if addition in current_text:
        return current_text
    return f"{current_text} {addition}"


def _limit_words(value: str, max_words: int) -> str:
    words = str(value).split()
    if len(words) <= max_words:
        return str(value)
    return " ".join(words[:max_words]).rstrip(".,;:") + "..."


def _min_confidence(current, cap: str) -> str:
    order = {"baja": 0, "media": 1, "alta": 2}
    current_value = str(current or "baja").lower()
    return current_value if order.get(current_value, 0) <= order[cap] else cap


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _is_valid_structured_output(value) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("summary"), str):
        return False
    if not isinstance(value.get("gap_recommendations"), list):
        return False
    for item in value["gap_recommendations"]:
        if not isinstance(item, dict):
            return False
        if not isinstance(item.get("gap_key"), str):
            return False
        if "evidence_used" in item and not isinstance(item["evidence_used"], list):
            return False
    return True


def _fallback_structured_output(
    crop_result: CropEvaluationResultData,
    text: str,
    evidence: list[EvidenceData],
) -> dict:
    evidence_refs = [_evidence_to_structured_ref(item) for item in evidence]
    return {
        "schema_version": "recommendation_structured_v1",
        "generated_by": "via_fallback",
        "summary": text,
        "overall_limitations": (
            "Salida estructurada generada por VIA a partir de texto no estructurado del proveedor."
        ),
        "gap_recommendations": [
            {
                "gap_key": _gap_key(gap),
                "criterion_id": gap.criterion_id,
                "criterion_name": gap.criterion_name,
                "criterion_label": gap.criterion_label,
                "criterion_group": gap.criterion_group,
                "unit": gap.unit,
                "phase_id": gap.phase_id,
                "phase_name": gap.phase_name,
                "gap_direction": gap.gap_direction,
                "severity": gap.severity,
                "observed_value": gap.observed_value,
                "optimal_limit": gap.optimal_limit,
                "gap_value": gap.gap_value,
                "recommendation": None,
                "rationale": None,
                "evidence_used": evidence_refs,
                "confidence": "baja",
                "limitations": (
                    "El proveedor no devolvio JSON estructurado validado para esta brecha."
                ),
            }
            for gap in crop_result.gaps
        ],
    }


def _gap_key(gap) -> str:
    return "|".join(
        [
            str(gap.criterion_name or gap.criterion_id),
            str(gap.phase_name or gap.phase_id),
            str(gap.observed_value),
            str(gap.optimal_limit),
            str(gap.gap_value),
        ]
    )


def _evidence_to_structured_ref(item: EvidenceData) -> dict:
    return {
        "fragment_id": str(item.fragment_id),
        "source_file_id": item.source_file_id,
        "source_filename": item.source_filename,
        "quote_summary": item.text[:240],
        "score": item.score,
        "page_ref": item.page_ref,
    }


def _recommendation_generated_event(recommendation: Recommendation, correlation_id: UUID) -> Message:
    return Message.event(
        RECOMENDACION_GENERADA,
        {
            "recommendation_id": str(recommendation.id),
            "evaluation_id": str(recommendation.evaluation_id),
            "crop_id": recommendation.crop_id,
            "fragment_ids": [str(fragment_id) for fragment_id in recommendation.fragment_ids],
            "text": recommendation.text,
        },
        correlation_id=correlation_id,
    )


def _recommendation_failed_event(evaluation_id: UUID, failure_cause: str, correlation_id: UUID) -> Message:
    return Message.event(
        RECOMENDACION_FALLIDA,
        {
            "evaluation_id": str(evaluation_id),
            "failure_cause": failure_cause,
        },
        correlation_id=correlation_id,
    )


def _outgoing_correlation_id(message: Message, fallback_evaluation_id: UUID) -> UUID:
    return message.correlation_id or fallback_evaluation_id
