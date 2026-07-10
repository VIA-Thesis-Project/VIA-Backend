"""Unit tests for Recommendation 10A base."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from via.bounded_contexts.recommendation.application.command_service import (
    GenerateRecommendationCommand,
    RecommendationCommandService,
)
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvaluationRecommendationData,
    EvidenceData,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.domain.value_objects import (
    RecommendationDomainError,
    RecommendationSectionType,
    RecommendationStatus,
)
from via.bounded_contexts.recommendation.infrastructure.recommendation_repository import (
    SQLAlchemyRecommendationRepository,
)
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel
from via.shared.database.base import TRANSACTIONAL_SCHEMA


ROOT = Path(__file__).resolve().parents[3]
RECOMMENDATION = ROOT / "via" / "bounded_contexts" / "recommendation"
DOMAIN = RECOMMENDATION / "domain"


def test_create_recommendation_from_already_computed_data() -> None:
    evaluation_id = uuid4()
    repository = FakeRecommendationRepository()
    service = _service(evaluation_id, repository=repository)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id))

    assert recommendation.evaluation_id == evaluation_id
    assert recommendation.crop_id == "cacao"
    assert recommendation.status == RecommendationStatus.GENERATED
    assert "score 0.82" in recommendation.text
    assert repository.saved == [recommendation]


def test_recommendation_includes_received_gaps_without_recomputing_them() -> None:
    gap = _gap(gap_value=-12.5)
    service = _service(uuid4(), crop_result=_crop_result(gaps=[gap]))

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))

    gaps_section = _section(recommendation, RecommendationSectionType.AGRONOMIC_GAPS)
    assert "agua/floracion: -12.5" in gaps_section.content


def test_recommendation_includes_received_limiting_factors_without_recomputing_them() -> None:
    factor = _limiting_factor(policy="PENALIZE")
    service = _service(uuid4(), crop_result=_crop_result(limiting_factors=[factor]))

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))

    factors_section = _section(recommendation, RecommendationSectionType.LIMITING_FACTORS)
    assert "temperatura/establecimiento: PENALIZE" in factors_section.content


def test_recommendation_includes_documentary_evidence_from_fake_port() -> None:
    evidence = _evidence(text="Manual tecnico INIA sobre cacao")
    evidence_port = FakeEvidencePort([evidence])
    service = _service(uuid4(), evidence_port=evidence_port)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))

    assert recommendation.evidence[0].text == "Manual tecnico INIA sobre cacao"
    assert recommendation.fragment_ids == [evidence.fragment_id]
    assert evidence_port.requests[0]["crop_id"] == "cacao"


def test_fake_drafting_provider_generates_text_and_no_external_calls() -> None:
    drafting_provider = FakeDraftingProvider()
    service = _service(uuid4(), drafting_provider=drafting_provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))

    assert "cacao" in recommendation.text
    assert drafting_provider.calls == 1
    assert drafting_provider.external_calls == 0


def test_reject_generation_without_sufficient_evaluation_data() -> None:
    evaluation_id = uuid4()
    service = _service(evaluation_id, evaluation_data=EvaluationRecommendationData(evaluation_id, []))

    with pytest.raises(RecommendationDomainError, match="evaluation results"):
        service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id, persist=False))


def test_explicit_crop_id_is_used_even_when_it_is_not_first_result() -> None:
    evaluation_id = uuid4()
    service = _service(
        evaluation_id,
        evaluation_data=EvaluationRecommendationData(
            evaluation_id,
            [
                _crop_result(crop_id="cacao", score=0.9, rank_position=1),
                _crop_result(crop_id="maiz", score=0.4, rank_position=2),
            ],
        ),
    )

    recommendation = service.generate(
        GenerateRecommendationCommand(evaluation_id=evaluation_id, crop_id="maiz", persist=False)
    )

    assert recommendation.crop_id == "maiz"
    assert "score 0.4" in recommendation.text


def test_without_crop_id_single_result_is_accepted() -> None:
    evaluation_id = uuid4()
    service = _service(evaluation_id, crop_result=_crop_result(crop_id="cafe", rank_position=None))

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id, persist=False))

    assert recommendation.crop_id == "cafe"


def test_without_crop_id_multiple_results_uses_rank_position_one() -> None:
    evaluation_id = uuid4()
    service = _service(
        evaluation_id,
        evaluation_data=EvaluationRecommendationData(
            evaluation_id,
            [
                _crop_result(crop_id="maiz", score=0.6, rank_position=2),
                _crop_result(crop_id="cacao", score=0.8, rank_position=1),
            ],
        ),
    )

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id, persist=False))

    assert recommendation.crop_id == "cacao"


def test_without_crop_id_fails_when_no_rank_position_one_exists() -> None:
    evaluation_id = uuid4()
    service = _service(
        evaluation_id,
        evaluation_data=EvaluationRecommendationData(
            evaluation_id,
            [
                _crop_result(crop_id="maiz", rank_position=2),
                _crop_result(crop_id="cacao", rank_position=None),
            ],
        ),
    )

    with pytest.raises(RecommendationDomainError, match="rank_position=1"):
        service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id, persist=False))


def test_without_crop_id_fails_when_rank_position_one_is_ambiguous() -> None:
    evaluation_id = uuid4()
    service = _service(
        evaluation_id,
        evaluation_data=EvaluationRecommendationData(
            evaluation_id,
            [
                _crop_result(crop_id="maiz", rank_position=1),
                _crop_result(crop_id="cacao", rank_position=1),
            ],
        ),
    )

    with pytest.raises(RecommendationDomainError, match="ambiguous rank_position=1"):
        service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id, persist=False))


def test_explicit_crop_id_fails_when_result_does_not_exist() -> None:
    evaluation_id = uuid4()
    service = _service(evaluation_id, crop_result=_crop_result(crop_id="cacao"))

    with pytest.raises(RecommendationDomainError, match="crop result not found: maiz"):
        service.generate(
            GenerateRecommendationCommand(evaluation_id=evaluation_id, crop_id="maiz", persist=False)
        )


def test_selection_policy_does_not_recalculate_ranking_or_score() -> None:
    evaluation_id = uuid4()
    service = _service(
        evaluation_id,
        evaluation_data=EvaluationRecommendationData(
            evaluation_id,
            [
                _crop_result(crop_id="maiz", score=0.99, rank_position=2),
                _crop_result(crop_id="cacao", score=0.10, rank_position=1),
            ],
        ),
    )

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=evaluation_id, persist=False))

    assert recommendation.crop_id == "cacao"
    assert "score 0.1" in recommendation.text
    viability_section = _section(recommendation, RecommendationSectionType.VIABILITY_RESULT)
    assert "Score=0.1" in viability_section.content
    assert "ranking=1" in viability_section.content


def test_repository_persists_recommendation_in_transactional_schema() -> None:
    session = FakeSession()
    service = _service(uuid4(), repository=SQLAlchemyRecommendationRepository(session))

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id))

    assert isinstance(session.added[0], RecommendationModel)
    assert RecommendationModel.__table__.schema == TRANSACTIONAL_SCHEMA
    assert session.added[0].id == recommendation.id
    assert session.added[0].evaluation_id == recommendation.evaluation_id
    assert session.added[0].crop_id == "cacao"
    assert session.added[0].fragment_ids[0]["fragment_id"] == str(recommendation.fragment_ids[0])
    assert session.added[0].fragment_ids[0]["text"] == "Evidencia tecnica cacao"
    assert session.added[0].fragment_ids[0]["crop_tags"] == ["cacao"]
    assert session.added[0].structured_output["schema_version"] == "recommendation_structured_v1"
    assert session.added[0].structured_output["gap_recommendations"]


def test_openai_file_search_trace_results_become_recommendation_evidence() -> None:
    service = _service(
        uuid4(),
        evidence_port=FakeEvidencePort([]),
        drafting_provider=FakeFileSearchDraftingProvider(),
    )

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))

    assert len(recommendation.evidence) == 1
    assert recommendation.evidence[0].source_file_id == "file_maiz_001"
    assert recommendation.evidence[0].source_filename == "manual_maiz.pdf"
    assert recommendation.evidence[0].text == "El maiz requiere riego suplementario en floracion."
    assert recommendation.fragment_ids == [recommendation.evidence[0].fragment_id]


def test_structured_output_downgrades_incompatible_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="INIA 627 Patapo presenta adaptacion en costa norte y resultados de rendimiento.",
        structured_item={
            "gap_key": "aptitud_termica|panojamiento",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "panojamiento",
            "phase_name": "panojamiento",
            "gap_direction": "below_optimum",
            "severity": "media",
            "recommendation": "Optimizar la siembra para incrementar temperaturas medias en panojamiento.",
            "rationale": "La temperatura observada esta por debajo del optimo.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "05_INIA_627_Patapo.pdf"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "insuficiente"
    assert item["confidence"] == "baja"
    assert item["recommendation"] is None
    assert item["evidence_used"] == []


def test_structured_output_rewrites_unsafe_clay_recommendation() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="El manejo de suelo mejora estructura, materia organica, drenaje y retencion de humedad.",
        source_filename="suelo.md",
        structured_item={
            "gap_key": "contenido_arcilla|suelo",
            "criterion_id": "contenido_arcilla",
            "criterion_name": "contenido_arcilla",
            "criterion_label": "Contenido de arcilla",
            "criterion_group": "suelo",
            "unit": "%",
            "phase_id": "potencial",
            "phase_name": "potencial",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "recommendation": "Aumentar el contenido de arcilla mediante enmiendas.",
            "rationale": "Mayor arcilla ayudaria a retener agua.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "suelo.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert "No se recomienda plantear el aumento directo de arcilla" in item["recommendation"]
    assert item["confidence"] == "media"
    assert item["evidence_status"] == "compatible"


def test_structured_output_keeps_only_compatible_riego_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="",
        retrieved_results=[
            {
                "file_id": "file_bad",
                "filename": "senasa_plaguicidas.pdf",
                "score": 0.8,
                "text": "Tabla de plaguicidas, LMR y periodos de carencia para maiz.",
            },
            {
                "file_id": "file_riego",
                "filename": "riego.md",
                "score": 0.95,
                "text": "El riego y la humedad del suelo son criticos durante floracion y cuajado.",
            },
        ],
        structured_item={
            "gap_key": "deficit_hidrico|floracion",
            "criterion_id": "deficit_hidrico",
            "criterion_name": "deficit_hidrico",
            "criterion_label": "Deficit hidrico",
            "criterion_group": "riego",
            "unit": "mm",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "recommendation": "Ajustar el manejo hidrico durante floracion.",
            "rationale": "La fase reproductiva requiere humedad suficiente.",
            "evidence_used": [
                {"source_file_id": "file_bad", "source_filename": "senasa_plaguicidas.pdf"},
                {"source_file_id": "file_riego", "source_filename": "riego.md"},
            ],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "compatible"
    assert item["confidence"] == "media"
    assert len(item["evidence_used"]) == 1
    assert item["evidence_used"][0]["source_file_id"] == "file_riego"
    assert item["evidence_used"][0]["source_filename"] == "riego.md"


def test_structured_output_prefers_curated_climate_evidence_over_pdf() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="",
        retrieved_results=[
            {
                "file_id": "file_pdf",
                "filename": "03_MIDAGRI_Ficha_Agroclimatica_MAD.pdf",
                "score": 0.9,
                "text": "Para favorecer la floracion la temperatura debe ser por lo menos de 18 C.",
            },
            {
                "file_id": "file_curated",
                "filename": "clima_fenologia.md",
                "score": 0.88,
                "text": "source_type: curated. Temperatura en floracion y panojamiento del maiz amarillo duro.",
            },
        ],
        structured_item={
            "gap_key": "aptitud_termica|panojamiento",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "panojamiento",
            "phase_name": "panojamiento",
            "gap_direction": "below_optimum",
            "severity": "media",
            "recommendation": "Ajustar manejo para reducir estres termico en panojamiento.",
            "rationale": "La temperatura afecta panojamiento y floracion.",
            "evidence_used": [{"source_file_id": "file_pdf", "source_filename": "03_MIDAGRI_Ficha_Agroclimatica_MAD.pdf"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "compatible"
    assert item["evidence_used"][0]["source_filename"] == "clima_fenologia.md"


def test_structured_output_rejects_topography_with_generic_soil_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Los maices se desarrollan mejor en suelos de textura media y pH adecuado.",
        source_filename="03_MIDAGRI_Ficha_Agroclimatica_MAD.pdf",
        structured_item={
            "gap_key": "aptitud_topografica|germinacion",
            "criterion_id": "aptitud_topografica",
            "criterion_name": "aptitud_topografica",
            "criterion_label": "Aptitud topografica",
            "criterion_group": "topografia",
            "unit": "degrees",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "above_optimum",
            "severity": "baja",
            "recommendation": "Aplicar agricultura de conservacion en terrenos con pendiente.",
            "rationale": "La pendiente puede afectar retencion de agua.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "03_MIDAGRI_Ficha_Agroclimatica_MAD.pdf"}],
            "confidence": "media",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "insuficiente"
    assert item["recommendation"] is None
    assert item["confidence"] == "baja"


def test_structured_output_prefers_palta_sanidad_curated_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="",
        retrieved_results=[
            {
                "file_id": "file_pdf",
                "filename": "03_SENASA_Evaluacion_Plagas_Cultivo_Palto.pdf",
                "score": 0.9,
                "text": "Evaluacion de plagas y enfermedades en cultivo de palto.",
            },
            {
                "file_id": "file_sanidad",
                "filename": "sanidad.md",
                "score": 0.88,
                "text": "source_type: curated. Sanidad, MIP, Phytophthora y enfermedades radiculares en palta Hass.",
            },
        ],
        structured_item={
            "gap_key": "phytophthora|crecimiento_desarrollo_fruto",
            "criterion_id": "phytophthora",
            "criterion_name": "phytophthora",
            "criterion_label": "Riesgo sanitario Phytophthora",
            "criterion_group": "sanidad",
            "unit": "index",
            "phase_id": "crecimiento_desarrollo_fruto",
            "phase_name": "crecimiento_desarrollo_fruto",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "recommendation": "Aplicar monitoreo sanitario y manejo integrado de enfermedades radiculares.",
            "rationale": "Phytophthora afecta raices de palto.",
            "evidence_used": [{"source_file_id": "file_pdf", "source_filename": "03_SENASA_Evaluacion_Plagas_Cultivo_Palto.pdf"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "compatible"
    assert item["evidence_used"][0]["source_filename"] == "sanidad.md"


def test_structured_output_flags_suspect_deficit_hidrico_above_optimum() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="El riego debe ajustarse segun agua disponible y humedad del suelo.",
        source_filename="riego.md",
        structured_item={
            "gap_key": "deficit_hidrico|germinacion",
            "criterion_id": "deficit_hidrico",
            "criterion_name": "deficit_hidrico",
            "criterion_label": "Deficit hidrico",
            "criterion_group": "riego",
            "unit": "mm",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "above_optimum",
            "severity": "alta",
            "observed_value": 1808.12,
            "optimal_limit": 600.0,
            "gap_value": 1208.12,
            "recommendation": "Incrementar riego.",
            "rationale": "Existe deficit hidrico.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "riego.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["pending_methodological_validation"][0]

    assert item["criterion_mapping_suspect"] is True
    assert item["evidence_status"] == "insuficiente"
    assert item["recommendation"] is None
    assert item["confidence"] == "baja"


def test_structured_output_rewrites_thermal_riego_recommendation() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura en floracion y panojamiento del maiz amarillo duro.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|panojamiento|20.47|22.0|-1.53",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "panojamiento",
            "phase_name": "panojamiento",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 20.47,
            "optimal_limit": 22.0,
            "gap_value": -1.53,
            "recommendation": "Aplicar riegos en horarios especificos para mantener temperaturas adecuadas durante el panojamiento.",
            "rationale": "La temperatura esta por debajo del optimo.",
            "evidence_used": [{"source_file_id": "file_curated", "source_filename": "clima_fenologia.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert "riego" not in item["recommendation"].lower().split()[:5], "riego no debe ser accion principal"
    assert "siembra" in item["recommendation"].lower() or "ventana" in item["recommendation"].lower()
    assert item["confidence"] in ("baja", "media")
    assert "VIA ajusto" in item["limitations"]


def test_perennial_thermal_recommendation_does_not_use_sowing_calendar() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion y manejo fenologico en palta Hass.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|floracion|17.0|20.0|-3.0",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 17.0,
            "optimal_limit": 20.0,
            "gap_value": -3.0,
            "recommendation": "Ajustar el calendario de siembra para evitar floracion en periodos frios.",
            "rationale": "La temperatura baja afecta la floracion.",
            "evidence_used": [{"source_file_id": "file_curated", "source_filename": "clima_fenologia.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="palta_hass")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert "instalacion" in item["recommendation"].lower()
    assert "renovacion" in item["recommendation"].lower()
    assert "manejo fenologico" in item["recommendation"].lower()
    assert "sin aplicar logica de cultivo anual" in item["recommendation"].lower()
    assert "huerto" not in item["recommendation"].lower()
    assert not item["recommendation"].lower().startswith("ajustar el calendario de siembra")
    assert item["confidence"] == "media"


def test_perennial_visible_text_uses_post_qc_rewrite_for_campaign_terms() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion, induccion floral y manejo fenologico de mandarina W. Murcott.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|floracion|17.0|20.0|-3.0",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 17.0,
            "optimal_limit": 20.0,
            "gap_value": -3.0,
            "recommendation": "No usar ventana de siembra; ajustar campanas y fechas de siembra para evitar fases productivas frias.",
            "rationale": "La temperatura baja afecta la floracion.",
            "evidence_used": [{"source_file_id": "file_curated", "source_filename": "clima_fenologia.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="mandarina_murcott")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]
    visible = recommendation.text.lower()

    assert item["recommendation"] == (
        "Evaluar aptitud termica para instalacion/renovacion del cultivo perenne y ajustar "
        "manejo fenologico en plantas establecidas, sin aplicar logica de cultivo anual."
    )
    assert "campanas" not in visible
    assert "fechas de siembra" not in visible
    assert "ventana de siembra" not in visible
    assert "huerto" not in visible
    assert "sin aplicar logica de cultivo anual" in item["recommendation"].lower()
    assert "evaluar aptitud termica" in visible


def test_mandarina_rejects_panojamiento_phase_from_other_crop() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion e induccion floral de mandarina W. Murcott.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|panojamiento|17.0|20.0|-3.0",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "panojamiento",
            "phase_name": "panojamiento",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 17.0,
            "optimal_limit": 20.0,
            "gap_value": -3.0,
            "recommendation": "Ajustar manejo durante panojamiento.",
            "rationale": "La temperatura afecta el panojamiento.",
            "evidence_used": [{"source_file_id": "file_curated", "source_filename": "clima_fenologia.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="mandarina_murcott")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["unsafe_recommendation"] is True
    assert item["recommendation"] is None
    assert item["evidence_status"] == "insuficiente"
    assert "fase fenologica" in item["limitations"].lower()


def test_riesgo_calor_below_optimum_is_mapping_suspect() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion e induccion floral de mandarina W. Murcott.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "riesgo_calor|floracion|18.0|30.0|-12.0",
            "criterion_id": "riesgo_calor",
            "criterion_name": "riesgo_calor",
            "criterion_label": "Riesgo de calor",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 18.0,
            "optimal_limit": 30.0,
            "gap_value": -12.0,
            "recommendation": "Evitar temperaturas excesivas durante la floracion.",
            "rationale": "Existe riesgo de calor.",
            "evidence_used": [{"source_file_id": "file_curated", "source_filename": "clima_fenologia.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="mandarina_murcott")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["pending_methodological_validation"][0]

    assert item["criterion_mapping_suspect"] is True
    assert item["recommendation"] is None
    assert "aptitud termica insuficiente" in item["mapping_validation_note"].lower()


def test_structured_output_rewrites_unsafe_arena_recommendation() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="El manejo de suelo mejora estructura, materia organica, drenaje y retencion de humedad.",
        source_filename="suelo.md",
        structured_item={
            "gap_key": "contenido_arena|germinacion|6.4|35.0|-28.6",
            "criterion_id": "contenido_arena",
            "criterion_name": "contenido_arena",
            "criterion_label": "Contenido arena",
            "criterion_group": "suelo",
            "unit": "%",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "observed_value": 6.4,
            "optimal_limit": 35.0,
            "gap_value": -28.6,
            "recommendation": "Controlar la textura del suelo mediante enmiendas para mejorar la proporcion de arena.",
            "rationale": "Baja arena limita aireacion y drenaje.",
            "evidence_used": [{"source_file_id": "file_suelo", "source_filename": "suelo.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert "controlar" not in item["recommendation"].lower()
    assert "textura" not in item["recommendation"].lower() or "directa" in item["recommendation"].lower() or "plantear" in item["recommendation"].lower()
    assert "analisis fisico" in item["recommendation"].lower() or "analisis" in item["recommendation"].lower()
    assert item["confidence"] in ("baja", "media")
    assert "VIA ajusto" in item["limitations"]


def test_structured_output_rewrites_arena_elevate_recommendation_and_accepts_practice_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="El manejo de suelo mejora estructura, materia organica y retencion de humedad.",
        source_filename="suelo.md",
        structured_item={
            "gap_key": "contenido_arena|germinacion|6.4|35.0|-28.6",
            "criterion_id": "contenido_arena",
            "criterion_name": "contenido_arena",
            "criterion_label": "Contenido arena",
            "criterion_group": "suelo",
            "unit": "%",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "observed_value": 6.4,
            "optimal_limit": 35.0,
            "gap_value": -28.6,
            "recommendation": "Elevar la arena para modificar textura y mejorar infiltracion.",
            "rationale": "Baja arena limita el suelo.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "suelo.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert "elevar" not in item["recommendation"].lower()
    assert "analisis fisico" in item["recommendation"].lower()
    # La evidencia menciona estructura y materia organica (practicas correctivas de
    # arena), asi que tras la recalibracion cuenta como respaldo directo (no indirecto);
    # el rewrite de textura insegura la limita a "media", no a "baja".
    assert item["evidence_status"] == "compatible"
    assert item["confidence"] == "media"


def test_web_evidence_with_corrective_practice_counts_as_direct_soil_support() -> None:
    from via.bounded_contexts.recommendation.application.command_service import _has_direct_soil_evidence

    item = {"criterion_id": "reaccion_suelo_ph", "criterion_name": "reaccion_suelo_ph"}
    web_evidence = EvidenceData(
        fragment_id=uuid4(),
        document_id=uuid4(),
        text="Para corregir el pH alcalino del suelo se recomienda aplicar azufre elemental.",
        crop_tags=["mandarina"],
        score=0.9,
        source_filename="",
        source_file_id="https://intagri.com/articulos/suelos/ph",
    )

    # Antes de la recalibracion solo suelo.md contaba como directo; ahora la evidencia
    # web que menciona la practica correctiva (azufre para pH) tambien respalda directo.
    assert _has_direct_soil_evidence(item, web_evidence) is True


def test_support_level_label_renames_confidence_to_document_support() -> None:
    from via.bounded_contexts.recommendation.application.command_service import _support_level_label

    assert _support_level_label("alta") == "directo"
    assert _support_level_label("media") == "parcial"
    assert _support_level_label("baja") == "indirecto"
    assert _support_level_label(None) == "indirecto"


def test_soil_criterion_rejects_climate_curated_as_main_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="La fenologia y temperatura influyen en el desarrollo del cultivo.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "contenido_arena|germinacion|6.4|35.0|-28.6",
            "criterion_id": "contenido_arena",
            "criterion_name": "contenido_arena",
            "criterion_label": "Contenido arena",
            "criterion_group": "suelo",
            "unit": "%",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "observed_value": 6.4,
            "optimal_limit": 35.0,
            "gap_value": -28.6,
            "recommendation": "Mejorar estructura, drenaje y manejo de riego.",
            "rationale": "Baja arena limita drenaje.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "clima_fenologia.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "insuficiente"
    assert item["recommendation"] is None
    assert item["evidence_used"] == []


def test_soil_criterion_requires_curated_suelo_before_pdf_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="",
        retrieved_results=[
            {
                "file_id": "file_pdf",
                "filename": "03_MIDAGRI_Ficha_Agroclimatica_MAD.pdf",
                "score": 0.91,
                "text": "El cultivo requiere suelo profundo, buen drenaje, textura media y pH adecuado.",
            },
            {
                "file_id": "file_clima",
                "filename": "clima_fenologia.md",
                "score": 0.88,
                "text": "Temperatura y fenologia del cultivo.",
            },
        ],
        structured_item={
            "gap_key": "contenido_arena|germinacion|6.4|35.0|-28.6",
            "criterion_id": "contenido_arena",
            "criterion_name": "contenido_arena",
            "criterion_label": "Contenido arena",
            "criterion_group": "suelo",
            "unit": "%",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "observed_value": 6.4,
            "optimal_limit": 35.0,
            "gap_value": -28.6,
            "recommendation": "Mejorar estructura, drenaje, materia organica y manejo de riego.",
            "rationale": "La textura limita la aireacion y el drenaje.",
            "evidence_used": [{"source_file_id": "file_pdf", "source_filename": "03_MIDAGRI_Ficha_Agroclimatica_MAD.pdf"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "insuficiente"
    assert item["recommendation"] is None
    assert item["evidence_used"] == []
    assert "evidencia recuperada" in item["limitations"].lower()


def test_qc_rejects_placeholder_evidence_ids_and_generic_locators() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="SENAMHI registra temperatura y condiciones agroclimaticas para floracion.",
        source_filename="04_SENAMHI_Clima_MAD_Costa_Central.pdf",
        structured_item={
            "gap_key": "aptitud_termica|floracion|17.0|20.0|-3.0",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 17.0,
            "optimal_limit": 20.0,
            "gap_value": -3.0,
            "recommendation": "Ajustar manejo fenologico.",
            "rationale": "La temperatura afecta floracion.",
            "evidence_used": [
                {
                    "source_file_id": "12345",
                    "source_filename": "04_SENAMHI_Clima_MAD_Costa_Central.pdf",
                    "source_locator": "archivo.md",
                }
            ],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "insuficiente"
    assert item["recommendation"] is None
    assert item["evidence_used"] == []


def test_mapping_suspect_visible_text_shows_validation_note() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="El riego debe ajustarse segun agua disponible.",
        source_filename="riego.md",
        structured_item={
            "gap_key": "deficit_hidrico|germinacion|1808.12|600.0|1208.12",
            "criterion_id": "deficit_hidrico",
            "criterion_name": "deficit_hidrico",
            "criterion_label": "Deficit hidrico",
            "criterion_group": "clima",
            "unit": "mm",
            "phase_id": "germinacion",
            "phase_name": "germinacion",
            "gap_direction": "above_optimum",
            "severity": "alta",
            "observed_value": 1808.12,
            "optimal_limit": 600.0,
            "gap_value": 1208.12,
            "recommendation": "Incrementar riego urgentemente — requiere intervencion inmediata.",
            "rationale": "Existe deficit hidrico severo.",
            "evidence_used": [{"source_file_id": "file_riego", "source_filename": "riego.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["pending_methodological_validation"][0]

    assert item["criterion_mapping_suspect"] is True
    assert item["recommendation"] is None
    assert "mapping_validation_note" in item
    assert "inconsistente" in item["mapping_validation_note"].lower() or "revision" in item["mapping_validation_note"].lower() or "revisar" in item["mapping_validation_note"].lower()

    visible = recommendation.text
    assert "inmediata" not in visible.lower()
    assert "revision" in visible.lower() or "revisar" in visible.lower() or "inconsistente" in visible.lower()


def test_mapping_suspects_are_deduped_and_do_not_fill_visible_slots() -> None:
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
        _render_visible_text,
    )

    def suspect_item(phase: str) -> dict:
        return {
            "gap_key": f"deficit_hidrico|{phase}",
            "criterion_id": "deficit_hidrico",
            "criterion_name": "deficit_hidrico",
            "criterion_label": "Deficit hidrico",
            "criterion_group": "riego",
            "unit": "mm",
            "phase_id": phase,
            "phase_name": phase,
            "gap_direction": "above_optimum",
            "severity": "alta",
            "observed_value": 1808.12,
            "optimal_limit": 600.0,
            "gap_value": 1208.12,
            "recommendation": "Incrementar riego.",
            "rationale": "Existe deficit hidrico.",
            "evidence_used": [{"source_file_id": "riego", "source_filename": "riego.md"}],
            "confidence": "alta",
            "limitations": "",
        }

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "Resumen.",
        "overall_limitations": "",
        "gap_recommendations": [
            suspect_item("germinacion"),
            suspect_item("floracion"),
            {
                "gap_key": "aptitud_termica|floracion",
                "criterion_id": "aptitud_termica",
                "criterion_name": "aptitud_termica",
                "criterion_label": "Aptitud termica",
                "criterion_group": "clima",
                "unit": "celsius",
                "phase_id": "floracion",
                "phase_name": "floracion",
                "gap_direction": "below_optimum",
                "severity": "media",
                "recommendation": "Ajustar ventana de siembra.",
                "rationale": "Temperatura baja.",
                "evidence_used": [{"source_file_id": "clima", "source_filename": "clima_fenologia.md"}],
                "confidence": "media",
                "limitations": "",
            },
        ],
    }
    evidence = [
        EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Temperatura y fenologia del cultivo.",
            crop_tags=["mandarina"],
            source_file_id="clima",
            source_filename="clima_fenologia.md",
        ),
        EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Riego y humedad del suelo.",
            crop_tags=["mandarina"],
            source_file_id="riego",
            source_filename="riego.md",
        ),
    ]

    qc_output = _quality_control_structured_output(structured, evidence)
    visible = _render_visible_text(qc_output, "fallback")

    assert len(qc_output["gap_recommendations"]) == 1
    assert len(qc_output["pending_methodological_validation"]) == 1
    # "Criterios: Deficit hidrico" should appear exactly once (in the validation block, not duplicated)
    assert visible.count("Criterios: Deficit hidrico") == 1
    # In the recommendations section, actionable item (Aptitud termica) must appear before the suspect block
    assert visible.index("Aptitud termica (respaldo documental:") < visible.index("Criterios: Deficit hidrico")


def test_controlled_hydric_stress_requires_wmurcott_sayan_evidence() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="El riego debe ajustarse segun humedad disponible en citricos.",
        source_filename="riego.md",
        structured_item={
            "gap_key": "deficit_hidrico|induccion_floral",
            "criterion_id": "deficit_hidrico",
            "criterion_name": "deficit_hidrico",
            "criterion_label": "Deficit hidrico",
            "criterion_group": "riego",
            "unit": "mm",
            "phase_id": "induccion_floral",
            "phase_name": "induccion_floral",
            "gap_direction": "below_optimum",
            "severity": "media",
            "observed_value": 10.0,
            "optimal_limit": 50.0,
            "gap_value": -40.0,
            "recommendation": "Aplicar estres hidrico controlado para induccion floral.",
            "rationale": "El deficit hidrico controlado favorece induccion.",
            "evidence_used": [{"source_file_id": "file_fake", "source_filename": "riego.md"}],
            "confidence": "alta",
            "limitations": "",
        },
    )
    service = _service(uuid4(), evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert item["evidence_status"] == "insuficiente"
    assert item["recommendation"] is None
    assert "W. Murcott" in item["limitations"] or "Murcott" in item["limitations"]


def test_visible_text_groups_soil_brechas_into_single_block() -> None:
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
        _render_visible_text,
    )

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "Resumen de brechas de suelo.",
        "overall_limitations": "",
        "gap_recommendations": [
            {
                "gap_key": "contenido_arcilla|germinacion|1.73|15.0|-13.27",
                "criterion_id": "arcilla",
                "criterion_name": "contenido_arcilla",
                "criterion_label": "Contenido arcilla",
                "criterion_group": "suelo",
                "unit": "%",
                "phase_id": "g",
                "phase_name": "germinacion",
                "gap_direction": "below_optimum",
                "severity": "alta",
                "observed_value": 1.73,
                "optimal_limit": 15.0,
                "gap_value": -13.27,
                "recommendation": "Mejorar estructura del suelo mediante materia organica.",
                "rationale": "Baja arcilla.",
                "evidence_used": [{"source_file_id": "fs", "source_filename": "suelo.md"}],
                "confidence": "media",
                "limitations": "",
            },
            {
                "gap_key": "carbono_organico_suelo|germinacion|0.0|10.0|-10.0",
                "criterion_id": "carbono",
                "criterion_name": "carbono_organico_suelo",
                "criterion_label": "Carbono organico suelo",
                "criterion_group": "suelo",
                "unit": "g/kg",
                "phase_id": "g",
                "phase_name": "germinacion",
                "gap_direction": "below_optimum",
                "severity": "alta",
                "observed_value": 0.0,
                "optimal_limit": 10.0,
                "gap_value": -10.0,
                "recommendation": "Aplicar compost para incrementar materia organica.",
                "rationale": "Falta carbono organico.",
                "evidence_used": [{"source_file_id": "fs", "source_filename": "suelo.md"}],
                "confidence": "media",
                "limitations": "",
            },
        ],
    }
    from via.bounded_contexts.recommendation.application.ports import EvidenceData as _EvidenceData
    from uuid import uuid4 as _uuid4
    evidence = [
        _EvidenceData(
            fragment_id=_uuid4(),
            document_id=_uuid4(),
            text="El manejo de suelo mejora estructura, materia organica, drenaje.",
            crop_tags=["maiz"],
            score=0.9,
            source_filename="suelo.md",
            source_file_id="fs",
        )
    ]
    qc_output = _quality_control_structured_output(structured, evidence)
    visible = _render_visible_text(qc_output, "fallback")

    assert "Condicion fisica y organica del suelo" in visible
    assert "Contenido arcilla" not in visible or "Condicion fisica" in visible
    assert "Atender estas brechas como una condicion integrada de suelo" in visible
    assert visible.count("Mejorar estructura del suelo mediante materia organica") == 0
    assert "suelo.md" in visible
    assert visible.count("1.") == 1, "solo debe haber un bloque numerado 1 para suelo"


def test_visible_text_keeps_strong_soil_group_even_with_insufficient_evidence_outside_top_five() -> None:
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
        _render_visible_text,
    )

    def climate_item(index: int) -> dict:
        return {
            "gap_key": f"aptitud_termica|floracion|{index}",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": f"Aptitud termica {index}",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "alta",
            "recommendation": f"Ajustar fechas de siembra para floracion {index}.",
            "rationale": "Temperatura baja en floracion.",
            "evidence_used": [{"source_file_id": "file-clima", "source_filename": "clima_fenologia.md"}],
            "confidence": "media",
            "limitations": "",
        }

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "Resumen.",
        "overall_limitations": "",
        "gap_recommendations": [
            *(climate_item(index) for index in range(6)),
            {
                "gap_key": "contenido_arena|suelo",
                "criterion_id": "contenido_arena",
                "criterion_name": "contenido_arena",
                "criterion_label": "Contenido arena",
                "criterion_group": "suelo",
                "unit": "%",
                "phase_id": "potencial",
                "phase_name": "potencial",
                "gap_direction": "below_optimum",
                "severity": "alta",
                "recommendation": "Mejorar estructura del suelo.",
                "rationale": "Brecha fuerte de suelo.",
                "evidence_used": [{"source_file_id": "file-clima", "source_filename": "clima_fenologia.md"}],
                "confidence": "alta",
                "limitations": "",
            },
        ],
    }
    evidence = [
        EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Temperatura, clima y floracion del cultivo.",
            crop_tags=["maiz"],
            score=0.9,
            source_filename="clima_fenologia.md",
            source_file_id="file-clima",
        )
    ]

    qc_output = _quality_control_structured_output(structured, evidence)
    visible = _render_visible_text(qc_output, "fallback")

    assert "Condicion fisica y organica del suelo" in visible
    assert "Contenido arena" in visible
    assert "No se emite una accion correctiva especifica" in visible


def test_visible_text_groups_all_mapping_suspects_into_one_block() -> None:
    from via.bounded_contexts.recommendation.application.command_service import (
        _quality_control_structured_output,
        _render_visible_text,
    )

    structured = {
        "schema_version": "recommendation_structured_v1",
        "summary": "Resumen.",
        "overall_limitations": "",
        "gap_recommendations": [
            {
                "gap_key": "aptitud_termica|floracion",
                "criterion_id": "aptitud_termica",
                "criterion_name": "aptitud_termica",
                "criterion_label": "Aptitud termica",
                "criterion_group": "clima",
                "unit": "celsius",
                "phase_id": "floracion",
                "phase_name": "floracion",
                "gap_direction": "below_optimum",
                "severity": "media",
                "recommendation": "Ajustar manejo fenologico.",
                "rationale": "Temperatura baja.",
                "evidence_used": [{"source_file_id": "file-clima", "source_filename": "clima_fenologia.md"}],
                "confidence": "media",
                "limitations": "",
            },
            {
                "gap_key": "deficit_hidrico|induccion",
                "criterion_id": "deficit_hidrico",
                "criterion_name": "deficit_hidrico",
                "criterion_label": "Deficit hidrico",
                "criterion_group": "riego",
                "unit": "mm",
                "phase_id": "induccion_floral",
                "phase_name": "induccion_floral",
                "gap_direction": "above_optimum",
                "severity": "alta",
                "observed_value": 900.0,
                "optimal_limit": 600.0,
                "gap_value": 300.0,
                "recommendation": "Incrementar riego.",
                "rationale": "Deficit hidrico.",
                "evidence_used": [{"source_file_id": "file-riego", "source_filename": "riego.md"}],
                "confidence": "alta",
                "limitations": "",
            },
            {
                "gap_key": "riesgo_calor|floracion",
                "criterion_id": "riesgo_calor",
                "criterion_name": "riesgo_calor",
                "criterion_label": "Riesgo calor",
                "criterion_group": "clima",
                "unit": "celsius",
                "phase_id": "floracion",
                "phase_name": "floracion",
                "gap_direction": "below_optimum",
                "severity": "alta",
                "recommendation": "Evitar temperaturas excesivas.",
                "rationale": "Riesgo de calor.",
                "evidence_used": [{"source_file_id": "file-clima", "source_filename": "clima_fenologia.md"}],
                "confidence": "alta",
                "limitations": "",
            },
            {
                "gap_key": "riesgo_frio|induccion",
                "criterion_id": "riesgo_frio",
                "criterion_name": "riesgo_frio",
                "criterion_label": "Riesgo frio",
                "criterion_group": "clima",
                "unit": "celsius",
                "phase_id": "induccion_floral",
                "phase_name": "induccion_floral",
                "gap_direction": "above_optimum",
                "severity": "alta",
                "recommendation": "Proteger de frio.",
                "rationale": "Riesgo de frio.",
                "evidence_used": [{"source_file_id": "file-clima", "source_filename": "clima_fenologia.md"}],
                "confidence": "alta",
                "limitations": "",
            },
        ],
    }
    evidence = [
        EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Temperatura, clima, floracion e induccion floral de mandarina.",
            crop_tags=["mandarina"],
            score=0.9,
            source_filename="clima_fenologia.md",
            source_file_id="file-clima",
        ),
        EvidenceData(
            fragment_id=uuid4(),
            document_id=uuid4(),
            text="Riego y humedad del suelo.",
            crop_tags=["mandarina"],
            score=0.9,
            source_filename="riego.md",
            source_file_id="file-riego",
        ),
    ]

    qc_output = _quality_control_structured_output(structured, evidence, crop_id="mandarina_murcott")
    visible = _render_visible_text(qc_output, "fallback")

    assert visible.count("Criterios pendientes de validacion metodologica") == 1
    assert visible.count("(respaldo documental: indirecto)") == 1
    assert "Deficit hidrico" in visible
    assert "Riesgo calor" in visible
    assert "Riesgo frio" in visible


def test_mandarina_climate_source_locator_does_not_use_sowing_section() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion, induccion floral y manejo fenologico de mandarina W. Murcott.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|floracion",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "floracion",
            "phase_name": "floracion",
            "gap_direction": "below_optimum",
            "severity": "media",
            "recommendation": "Ajustar manejo fenologico.",
            "rationale": "Temperatura baja en floracion.",
            "evidence_used": [{"source_file_id": "file-test", "source_filename": "clima_fenologia.md"}],
            "confidence": "media",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="mandarina_murcott")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    locator = recommendation.structured_output["gap_recommendations"][0]["evidence_used"][0]["source_locator"]

    assert "Temperatura de siembra y crecimiento" not in locator
    assert "manejo fenologico" in locator.lower()


def test_maiz_can_keep_sowing_dates_for_thermal_recommendation() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion, panojamiento y fechas de siembra del maiz amarillo duro.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|panojamiento",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "panojamiento",
            "phase_name": "panojamiento",
            "gap_direction": "below_optimum",
            "severity": "media",
            "recommendation": "Ajustar fechas de siembra para evitar panojamiento en periodos frios.",
            "rationale": "Temperatura baja durante panojamiento.",
            "evidence_used": [{"source_file_id": "file-test", "source_filename": "clima_fenologia.md"}],
            "confidence": "media",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="maiz_amarillo_duro")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]

    assert "fechas de siembra" in item["recommendation"].lower()
    assert "instalacion/renovacion" not in item["recommendation"].lower()


def test_maiz_blocks_huerto_language_in_visible_and_internal_text() -> None:
    provider = FakeStructuredFileSearchProvider(
        retrieved_text="Temperatura, floracion, panojamiento y fechas de siembra del maiz amarillo duro.",
        source_filename="clima_fenologia.md",
        structured_item={
            "gap_key": "aptitud_termica|panojamiento",
            "criterion_id": "aptitud_termica",
            "criterion_name": "aptitud_termica",
            "criterion_label": "Aptitud termica",
            "criterion_group": "clima",
            "unit": "celsius",
            "phase_id": "panojamiento",
            "phase_name": "panojamiento",
            "gap_direction": "below_optimum",
            "severity": "media",
            "recommendation": (
                "Evaluar aptitud termica para instalacion/renovacion del huerto y ajustar manejo "
                "fenologico en huertos establecidos."
            ),
            "rationale": "El huerto requiere ajuste termico.",
            "evidence_used": [{"source_file_id": "file-test", "source_filename": "clima_fenologia.md"}],
            "confidence": "media",
            "limitations": "",
        },
    )
    crop_result = _crop_result(crop_id="maiz_amarillo_duro")
    service = _service(uuid4(), crop_result=crop_result, evidence_port=FakeEvidencePort([]), drafting_provider=provider)

    recommendation = service.generate(GenerateRecommendationCommand(evaluation_id=service.evaluation_id, persist=False))
    item = recommendation.structured_output["gap_recommendations"][0]
    visible = recommendation.text.lower()

    assert "huerto" not in item["recommendation"].lower()
    assert "huerto" not in str(item.get("rationale") or "").lower()
    assert "huerto" not in visible
    assert "cultivo perenne" not in item["recommendation"].lower()


def test_recommendation_does_not_implement_mcda_or_external_providers() -> None:
    forbidden_import_prefixes = (
        "fastapi",
        "sqlalchemy",
        "via.bounded_contexts.viability_evaluation",
        "via.bounded_contexts.document_management",
        "via.bounded_contexts.agroenv_extraction",
        "via.shared.outbox",
        "via.shared.event_bus",
        "openai",
        "anthropic",
        "google",
    )
    forbidden_source_terms = (
        "Fuzzification",
        "EntropyWeights",
        "HybridWeights",
        "Multicriteria",
        "GapCalculation",
        "rank_crops",
        "classify",
    )
    offenders: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_import_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")
    for path in RECOMMENDATION.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for term in forbidden_source_terms:
            if term in source:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} contains {term}")

    assert offenders == []


class FakeRecommendationService:
    """Bundle service and fakes for concise tests."""

    def __init__(
        self,
        evaluation_id: UUID,
        service: RecommendationCommandService,
    ) -> None:
        """Create a bundle with an evaluation id."""

        self.evaluation_id = evaluation_id
        self.service = service

    def generate(self, command: GenerateRecommendationCommand):
        """Delegate generation to the wrapped service."""

        return self.service.generate(command)


class FakeEvaluationResultsPort:
    """Fake evaluation result reader."""

    def __init__(self, data: EvaluationRecommendationData) -> None:
        """Create the fake with prepared data."""

        self.data = data
        self.requests: list[UUID] = []

    def get_results_for_recommendation(self, evaluation_id: UUID) -> EvaluationRecommendationData:
        """Return prepared evaluation data."""

        self.requests.append(evaluation_id)
        return self.data


class FakeEvidencePort:
    """Fake documentary evidence search port."""

    def __init__(self, evidence: list[EvidenceData]) -> None:
        """Create the fake with prepared evidence."""

        self.evidence = evidence
        self.requests: list[dict[str, object]] = []

    def search_evidence(self, crop_id: str, gaps: list[GapData], max_fragments: int) -> list[EvidenceData]:
        """Return prepared evidence and record the request."""

        self.requests.append({"crop_id": crop_id, "gaps": gaps, "max_fragments": max_fragments})
        return self.evidence[:max_fragments]


class FakeDraftingProvider:
    """Fake drafting provider without external calls."""

    def __init__(self) -> None:
        """Create a fake provider."""

        self.calls = 0
        self.external_calls = 0
        self.last_context: RecommendationDraftContext | None = None

    def draft(self, context: RecommendationDraftContext) -> str:
        """Draft deterministic text from the supplied context."""

        self.calls += 1
        self.last_context = context
        return (
            f"Recomendacion para {context.crop_result.crop_id} con score {context.crop_result.score}. "
            f"Se usan {len(context.evidence)} fragmentos documentales."
        )


class FakeFileSearchDraftingProvider(FakeDraftingProvider):
    """Fake OpenAI File Search provider with trace results."""

    def __init__(self) -> None:
        """Create a provider with one retrieved result."""

        super().__init__()
        self._trace = None

    def draft(self, context: RecommendationDraftContext) -> str:
        """Draft text and expose retrieved File Search evidence."""

        self.calls += 1
        self.last_context = context
        self._trace = SimpleNamespace(
            retrieved_results=[
                {
                    "file_id": "file_maiz_001",
                    "filename": "manual_maiz.pdf",
                    "score": 0.87,
                    "text": "El maiz requiere riego suplementario en floracion.",
                }
            ]
        )
        return "Recomendacion tecnica sustentada con File Search."

    def get_last_trace(self):
        """Return the fake File Search trace."""

        return self._trace


class FakeStructuredFileSearchProvider(FakeDraftingProvider):
    """Fake File Search provider returning structured output and retrieved evidence."""

    def __init__(
        self,
        *,
        retrieved_text: str,
        structured_item: dict,
        source_filename: str = "05_INIA_627_Patapo.pdf",
        retrieved_results: list[dict] | None = None,
    ) -> None:
        """Create a structured provider double."""

        super().__init__()
        self._trace = None
        self._structured_item = structured_item
        self._retrieved_text = retrieved_text
        self._source_filename = source_filename
        self._retrieved_results = retrieved_results

    def draft(self, context: RecommendationDraftContext) -> str:
        """Expose fake retrieval and structured recommendation data."""

        self.calls += 1
        self.last_context = context
        retrieved_results = self._retrieved_results or [
            {
                "file_id": "file-test",
                "filename": self._source_filename,
                "score": 0.9,
                "text": self._retrieved_text,
            }
        ]
        self._trace = SimpleNamespace(
            retrieved_results=retrieved_results
        )
        return "Texto estructurado renderizado por proveedor."

    def get_last_trace(self):
        """Return fake trace."""

        return self._trace

    def get_last_structured_output(self):
        """Return fake structured output."""

        return {
            "schema_version": "recommendation_structured_v1",
            "summary": "Resumen estructurado.",
            "overall_limitations": "",
            "gap_recommendations": [self._structured_item],
        }


class FakeRecommendationRepository:
    """Fake recommendation repository."""

    def __init__(self) -> None:
        """Create an empty fake repository."""

        self.saved = []

    def save(self, recommendation) -> None:
        """Record saved recommendations."""

        self.saved.append(recommendation)


class FakeSession:
    """Fake SQLAlchemy session."""

    def __init__(self) -> None:
        """Create an empty fake session."""

        self.added: list[object] = []

    def add(self, model: object) -> None:
        """Record added ORM rows."""

        self.added.append(model)


def test_focus_recommendable_gaps_drops_near_optimal_criteria() -> None:
    from via.bounded_contexts.recommendation.application.command_service import (
        DEFAULT_RECOMMENDABLE_GAP_MEMBERSHIP_THRESHOLD,
        _focus_recommendable_gaps,
    )

    low = GapData(criterion_id="agua", phase_id="floracion", most_limiting_period="p1",
                  observed_value=10.0, optimal_limit=22.0, gap_value=-12.0, membership=0.2)
    near_optimal = GapData(criterion_id="ph", phase_id="floracion", most_limiting_period="p1",
                           observed_value=6.3, optimal_limit=6.5, gap_value=-0.2, membership=0.95)
    legacy = GapData(criterion_id="arcilla", phase_id="floracion", most_limiting_period="p1",
                     observed_value=20.0, optimal_limit=35.0, gap_value=-15.0, membership=None)
    crop_result = _crop_result(gaps=[low, near_optimal, legacy])

    focused = _focus_recommendable_gaps(crop_result, DEFAULT_RECOMMENDABLE_GAP_MEMBERSHIP_THRESHOLD)

    kept = {gap.criterion_id for gap in focused.gaps}
    assert "agua" in kept  # membresia baja -> brecha accionable
    assert "arcilla" in kept  # sin membresia (legacy) -> se conserva
    assert "ph" not in kept  # casi optimo -> excluido de la recomendacion
    # Los factores limitantes (vetos criticos) nunca se filtran.
    assert len(focused.limiting_factors) == len(crop_result.limiting_factors)


def _service(
    evaluation_id: UUID,
    crop_result: CropEvaluationResultData | None = None,
    evaluation_data: EvaluationRecommendationData | None = None,
    evidence_port: FakeEvidencePort | None = None,
    drafting_provider: object | None = None,
    repository=None,
) -> FakeRecommendationService:
    data = evaluation_data or EvaluationRecommendationData(evaluation_id, [crop_result or _crop_result()])
    service = RecommendationCommandService(
        evaluation_results_port=FakeEvaluationResultsPort(data),
        evidence_port=evidence_port or FakeEvidencePort([_evidence()]),
        drafting_provider=drafting_provider or FakeDraftingProvider(),
        repository=repository,
    )
    return FakeRecommendationService(evaluation_id, service)


def _crop_result(
    crop_id: str = "cacao",
    score: float | None = 0.82,
    rank_position: int | None = 1,
    gaps: list[GapData] | None = None,
    limiting_factors: list[LimitingFactorData] | None = None,
) -> CropEvaluationResultData:
    return CropEvaluationResultData(
        crop_id=crop_id,
        score=score,
        rank_position=rank_position,
        calc_condition="DEFINITIVO",
        viability_category="VIABLE",
        gaps=gaps if gaps is not None else [_gap()],
        limiting_factors=limiting_factors if limiting_factors is not None else [_limiting_factor()],
    )


def _gap(gap_value: float = -4.0) -> GapData:
    return GapData(
        criterion_id="agua",
        phase_id="floracion",
        most_limiting_period="p2",
        observed_value=18.0,
        optimal_limit=22.0,
        gap_value=gap_value,
    )


def _limiting_factor(policy: str = "NO_VIABLE") -> LimitingFactorData:
    return LimitingFactorData(
        criterion_id="temperatura",
        phase_id="establecimiento",
        policy=policy,
        penalty_factor=0.5,
        observed_value=35.0,
        optimal_limit=30.0,
        membership=0.0,
        doc_source="Manual cacao",
    )


def _evidence(text: str = "Evidencia tecnica cacao") -> EvidenceData:
    return EvidenceData(
        fragment_id=uuid4(),
        document_id=uuid4(),
        text=text,
        crop_tags=["cacao"],
        page_ref=3,
        score=0.9,
    )


def _section(recommendation, section_type: RecommendationSectionType):
    return next(section for section in recommendation.sections if section.section_type == section_type)


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
