"""Phase 1 recommendation module activation tests.

Covers 13 test categories:
  1.  Three read endpoints do not raise 500
  2.  RecommendationQueryService wired correctly via dependency override
  3.  GenerarRecomendacionSolicitada generates and persists (template provider)
  4.  Consumer is idempotent
  5.  No-evidence scenario → explicit declaration, no invented evidence
  6.  Uses existing MCDA ranking without modification
  7.  Recommendation includes gaps and limiting factors
  8.  Respects NO_VIABLE / CONDICIONAL / VIABLE / NO_CONCLUYENTE
  9.  Provider does not recalculate scores/weights/memberships/rankings
 10.  --until-recommendation-completed continues past EVALUACION_COMPLETADA
 11.  Existing --until-completed mode still stops at EVALUACION_COMPLETADA
 12.  trace_report.md section 18 shows recommendation when present
 13.  No prohibited dependencies (asyncpg, Redis, Celery, etc.)
"""

from __future__ import annotations

import ast
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from via.bounded_contexts.recommendation.application.command_service import (
    RECOMMENDATION_CONSUMER,
    RecommendationCommandService,
    RecommendationMessageCommandService,
)
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvaluationRecommendationData,
    FinalRecommendationResult,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
    RecommendationReadModel,
)
from via.bounded_contexts.recommendation.application.recommendation_query_service import RecommendationQueryService
from via.bounded_contexts.recommendation.infrastructure.orm_models import RecommendationModel
from via.bounded_contexts.recommendation.infrastructure.recommendation_query_repository import RecommendationQueryRepository
from via.bounded_contexts.recommendation.infrastructure.recommendation_repository import SQLAlchemyRecommendationRepository
from via.bounded_contexts.recommendation.infrastructure.template_drafting_provider import TemplateRecommendationDraftingProvider
from via.bounded_contexts.recommendation.interfaces.recommendation_consumer import RecommendationConsumer
from via.bounded_contexts.recommendation.interfaces.recommendation_router import (
    get_final_recommendation,
    get_recommendation,
    get_recommendation_query_service,
    get_recommendations_for_evaluation,
)
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import GENERAR_RECOMENDACION_SOLICITADA
from via.shared.outbox.models import OutboxMessageModel

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_EID = UUID("10000000-0000-4000-8000-000000000001")
_RID = UUID("10000000-0000-4000-8000-000000000002")
_PID = UUID("10000000-0000-4000-8000-000000000003")
_FID = UUID("10000000-0000-4000-8000-000000000004")
_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)


# ─── Category 1: Endpoints do not raise 500 ───────────────────────────────────


def test_get_recommendation_endpoint_uses_query_service_not_stub() -> None:
    """Calling with a real query service must return a result — no RuntimeError."""
    svc = _fake_query_service(recommendation=_read_model())
    resp = get_recommendation(_RID, svc)
    assert resp.recommendation_id == _RID


def test_get_recommendations_for_evaluation_endpoint_returns_list() -> None:
    svc = _fake_query_service(evaluation_list=[_read_model()])
    resp = get_recommendations_for_evaluation(_EID, svc)
    assert len(resp) == 1


def test_get_final_recommendation_endpoint_returns_response() -> None:
    result = FinalRecommendationResult(evaluation_found=True, recommendation=_read_model())
    svc = _fake_query_service(final_result=result)
    resp = get_final_recommendation(_EID, svc)
    assert resp.recommendation_id == _RID


def test_get_recommendation_query_service_stub_raises_runtime_error() -> None:
    """Confirm the stub raises — wiring test is that dependency override replaces this."""
    with pytest.raises(RuntimeError, match="not configured"):
        get_recommendation_query_service()


# ─── Category 2: Query service wired correctly ────────────────────────────────


def test_recommendation_query_service_delegates_to_query_port() -> None:
    rm = _read_model()
    port = _fake_query_port(by_id=rm)
    svc = RecommendationQueryService(port)
    assert svc.get_recommendation(_RID) is rm


def test_recommendation_query_service_get_recommendations_for_evaluation() -> None:
    rm = _read_model()
    port = _fake_query_port(by_evaluation=[rm])
    svc = RecommendationQueryService(port)
    assert svc.get_recommendations_for_evaluation(_EID) == [rm]


def test_recommendation_query_service_get_final_recommendation() -> None:
    result = FinalRecommendationResult(evaluation_found=True, recommendation=_read_model())
    port = _fake_query_port(final=result)
    svc = RecommendationQueryService(port)
    final = svc.get_final_recommendation(_EID)
    assert final.evaluation_found is True
    assert final.recommendation is not None


# ─── Category 3: Generation and persistence ───────────────────────────────────


def test_generation_creates_recommendation_model_in_session() -> None:
    session = _FakeSession()
    _msg_service(session).handle_generation_requested(_cmd_message())
    recs = _recs(session)
    assert len(recs) == 1
    assert recs[0].evaluation_id == _EID
    assert recs[0].crop_id == "maiz"


def test_generation_writes_outbox_event_recomendacion_generada() -> None:
    from via.shared.orchestration.evaluation_process_manager.events import RECOMENDACION_GENERADA
    session = _FakeSession()
    _msg_service(session).handle_generation_requested(_cmd_message())
    outbox = _outbox(session)
    assert len(outbox) == 1
    assert outbox[0].message_type == RECOMENDACION_GENERADA


def test_generated_recommendation_stored_with_correct_provider() -> None:
    session = _FakeSession()
    _msg_service(session, provider_name="template").handle_generation_requested(_cmd_message())
    recs = _recs(session)
    assert recs[0].provider == "template"


def test_generated_recommendation_text_is_non_empty() -> None:
    session = _FakeSession()
    _msg_service(session).handle_generation_requested(_cmd_message())
    assert len(_recs(session)[0].text) > 50


# ─── Category 4: Consumer idempotency ─────────────────────────────────────────


def test_duplicate_message_does_not_create_second_recommendation() -> None:
    session = _FakeSession()
    msg = _cmd_message()
    session.processed.add((msg.id, RECOMMENDATION_CONSUMER))
    _msg_service(session).handle_generation_requested(msg)
    assert _recs(session) == []
    assert _outbox(session) == []


def test_idempotency_marker_written_after_recommendation() -> None:
    session = _FakeSession()
    msg = _cmd_message()
    _msg_service(session).handle_generation_requested(msg)
    assert (msg.id, RECOMMENDATION_CONSUMER) in session.processed


def test_session_committed_on_success() -> None:
    session = _FakeSession()
    _msg_service(session).handle_generation_requested(_cmd_message())
    assert session.commits == 1
    assert session.rollbacks == 0


# ─── Category 5: No-evidence scenario ────────────────────────────────────────


def test_template_draft_with_no_evidence_contains_explicit_declaration() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context(evidence=[])
    text = provider.draft(context)
    assert "No se encontro evidencia documental suficiente" in text


def test_template_draft_with_no_evidence_does_not_invent_sources() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context(evidence=[])
    text = provider.draft(context)
    assert "INIA" not in text
    assert "FAO" not in text
    assert "Segun" not in text
    assert "fuente:" not in text.lower()


def test_no_evidence_section_in_build_sections() -> None:
    from via.bounded_contexts.recommendation.application.command_service import _build_sections
    from via.bounded_contexts.recommendation.domain.value_objects import RecommendationSectionType
    crop_result = _crop_result()
    sections = _build_sections(crop_result, [])
    evidence_section = next(
        s for s in sections if s.section_type == RecommendationSectionType.DOCUMENTARY_EVIDENCE
    )
    assert "No se encontro evidencia documental suficiente" in evidence_section.content


# ─── Category 6: Uses existing MCDA ranking without modification ──────────────


def test_template_draft_includes_rank_from_evaluation_data() -> None:
    provider = TemplateRecommendationDraftingProvider()
    result = _crop_result(rank_position=3)
    context = _draft_context(crop_result=result)
    text = provider.draft(context)
    assert "3" in text


def test_template_draft_does_not_reassign_rank_position() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context_rank2 = _draft_context(crop_result=_crop_result(crop_id="maiz", score=0.9, rank_position=2))
    text = provider.draft(context_rank2)
    assert "2" in text
    assert "ranking=1" not in text
    assert "Posicion en ranking: 2" in text


def test_selection_policy_does_not_recalculate_ranking() -> None:
    """Using crop_id=2nd place crop in a multi-result evaluation keeps original rank."""
    session = _FakeSession()
    data = EvaluationRecommendationData(
        evaluation_id=_EID,
        crop_results=[
            _crop_result(crop_id="maiz", score=0.4, rank_position=2),
            _crop_result(crop_id="cacao", score=0.9, rank_position=1),
        ],
    )
    service = RecommendationCommandService(
        evaluation_results_port=_FakeEvaluationPort(data),
        evidence_port=_FakeEvidencePort(evidence=[]),
        drafting_provider=TemplateRecommendationDraftingProvider(),
        repository=SQLAlchemyRecommendationRepository(session),
    )
    from via.bounded_contexts.recommendation.application.command_service import GenerateRecommendationCommand
    cmd = GenerateRecommendationCommand(evaluation_id=_EID, crop_id="maiz", persist=True)
    rec = service.generate(cmd)
    assert rec.crop_id == "maiz"
    assert "2" in rec.text


# ─── Category 7: Includes gaps and limiting factors ──────────────────────────


def test_template_draft_includes_gaps() -> None:
    provider = TemplateRecommendationDraftingProvider()
    gap = GapData(
        criterion_id="riego",
        phase_id="floracion",
        most_limiting_period="p1",
        observed_value=300.0,
        optimal_limit=500.0,
        gap_value=-200.0,
    )
    context = _draft_context(crop_result=_crop_result(gaps=[gap]))
    text = provider.draft(context)
    assert "riego" in text
    assert "floracion" in text
    assert "-200.0" in text


def test_template_draft_includes_limiting_factors() -> None:
    provider = TemplateRecommendationDraftingProvider()
    factor = LimitingFactorData(
        criterion_id="temperatura",
        phase_id="establecimiento",
        policy="NO_VIABLE",
        penalty_factor=1.0,
        observed_value=4.0,
        optimal_limit=12.0,
        membership=0.0,
        doc_source="manual",
    )
    context = _draft_context(crop_result=_crop_result(limiting_factors=[factor]))
    text = provider.draft(context)
    assert "temperatura" in text
    assert "NO_VIABLE" in text


def test_agronomic_gaps_section_contains_gap_values() -> None:
    from via.bounded_contexts.recommendation.application.command_service import _build_sections
    from via.bounded_contexts.recommendation.domain.value_objects import RecommendationSectionType
    gap = GapData(
        criterion_id="ph",
        phase_id="desarrollo",
        most_limiting_period="p1",
        observed_value=4.5,
        optimal_limit=6.0,
        gap_value=-1.5,
    )
    sections = _build_sections(_crop_result(gaps=[gap]), [])
    gaps_section = next(s for s in sections if s.section_type == RecommendationSectionType.AGRONOMIC_GAPS)
    assert "ph" in gaps_section.content
    assert "-1.5" in gaps_section.content


# ─── Category 8: Respects viability categories ────────────────────────────────


@pytest.mark.parametrize("category", ["NO_VIABLE", "CONDICIONAL", "VIABLE", "NO_CONCLUYENTE"])
def test_template_draft_preserves_viability_category(category: str) -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context(crop_result=_crop_result(viability_category=category))
    text = provider.draft(context)
    assert category in text


def test_no_viable_category_not_upgraded_to_condicional() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context(crop_result=_crop_result(viability_category="NO_VIABLE"))
    text = provider.draft(context)
    assert "NO_VIABLE" in text
    assert "CONDICIONAL" not in text
    assert "VIABLE" not in text or "NO_VIABLE" in text


def test_no_concluyente_category_not_hidden() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context(crop_result=_crop_result(viability_category="NO_CONCLUYENTE"))
    text = provider.draft(context)
    assert "NO_CONCLUYENTE" in text


# ─── Category 9: Provider does not recalculate scores/weights/memberships ─────


def test_template_draft_uses_score_from_context_not_recalculated() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context(crop_result=_crop_result(score=0.7777))
    text = provider.draft(context)
    assert "0.7777" in text


def test_template_draft_does_not_contain_fuzzification_terms() -> None:
    provider = TemplateRecommendationDraftingProvider()
    context = _draft_context()
    text = provider.draft(context)
    forbidden = ["Fuzzification", "EntropyWeights", "HybridWeights", "Multicriteria", "GapCalculation", "rank_crops"]
    for term in forbidden:
        assert term not in text


def test_template_provider_source_has_no_mcda_imports() -> None:
    src = (ROOT / "via" / "bounded_contexts" / "recommendation" / "infrastructure" / "template_drafting_provider.py").read_text()
    for term in ["viability_evaluation", "Fuzzification", "EntropyWeights", "membership_fn"]:
        assert term not in src, f"template_drafting_provider contains forbidden term: {term}"


# ─── Category 10: --until-recommendation-completed ────────────────────────────


def test_until_recommendation_flag_uses_recommendation_only_terminal_statuses() -> None:
    """When --until-recommendation-completed is set, the relay uses a different terminal set."""
    from process_outbox_for_evaluation import _RECOMMENDATION_ONLY_TERMINAL_STATUSES, _TERMINAL_STATUSES
    from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus

    recom_terminal = _RECOMMENDATION_ONLY_TERMINAL_STATUSES
    all_terminal = _TERMINAL_STATUSES
    evaluacion_completada = EvaluationSagaStatus.EVALUACION_COMPLETADA.value
    recom_completada = EvaluationSagaStatus.RECOMENDACION_COMPLETADA.value

    assert evaluacion_completada not in recom_terminal, (
        "EVALUACION_COMPLETADA should NOT stop --until-recommendation-completed"
    )
    assert recom_completada in recom_terminal
    assert evaluacion_completada in all_terminal


def test_build_relay_accepts_recommendation_consumer_parameter() -> None:
    """_build_relay must accept optional recommendation_consumer without error."""
    import inspect
    from process_outbox_for_evaluation import _build_relay
    sig = inspect.signature(_build_relay)
    assert "recommendation_consumer" in sig.parameters


def test_run_rounds_accepts_terminal_statuses_parameter() -> None:
    import inspect
    from process_outbox_for_evaluation import run_rounds
    sig = inspect.signature(run_rounds)
    assert "terminal_statuses" in sig.parameters


# ─── Category 11: --until-completed still stops at EVALUACION_COMPLETADA ──────


def test_until_completed_default_terminal_statuses_include_evaluacion_completada() -> None:
    from process_outbox_for_evaluation import _TERMINAL_STATUSES
    from via.shared.orchestration.evaluation_process_manager.states import EvaluationSagaStatus
    assert EvaluationSagaStatus.EVALUACION_COMPLETADA.value in _TERMINAL_STATUSES


def test_run_rounds_default_terminal_statuses_same_as_original() -> None:
    import inspect
    from process_outbox_for_evaluation import run_rounds, _TERMINAL_STATUSES
    sig = inspect.signature(run_rounds)
    default = sig.parameters["terminal_statuses"].default
    assert default is None  # None means "use _TERMINAL_STATUSES" (backward compat)


# ─── Category 12: trace_report includes recommendation section ────────────────


def test_generate_trace_report_includes_section_18_when_recommendation_present(tmp_path: Path) -> None:
    from run_traceable_e2e_demo import generate_trace_report

    ctx = _minimal_ctx()
    ctx["recommendation"] = {
        "id": str(_RID),
        "crop_id": "maiz",
        "provider": "template",
        "generated_at": "2026-06-18T12:00:00+00:00",
        "fragment_ids": [],
        "text": "Recomendacion agronomica sustentada para maiz.",
    }
    generate_trace_report(tmp_path, ctx)
    report = (tmp_path / "trace_report.md").read_text(encoding="utf-8")
    assert "## 18. Recomendacion Generada" in report
    assert "template" in report
    assert "maiz" in report


def test_generate_trace_report_section_18_when_no_recommendation(tmp_path: Path) -> None:
    from run_traceable_e2e_demo import generate_trace_report

    ctx = _minimal_ctx()
    ctx["recommendation"] = None
    generate_trace_report(tmp_path, ctx)
    report = (tmp_path / "trace_report.md").read_text(encoding="utf-8")
    assert "## 18. Recomendacion Generada" in report
    assert "no disponible" in report.lower() or "no alcanz" in report.lower()


def test_generate_trace_report_warns_when_no_evidence(tmp_path: Path) -> None:
    from run_traceable_e2e_demo import generate_trace_report

    ctx = _minimal_ctx()
    ctx["recommendation"] = {
        "id": str(_RID),
        "crop_id": "maiz",
        "provider": "template",
        "generated_at": "2026-06-18T12:00:00+00:00",
        "fragment_ids": [],
        "text": "Recomendacion para maiz.",
    }
    generate_trace_report(tmp_path, ctx)
    report = (tmp_path / "trace_report.md").read_text(encoding="utf-8")
    assert "AVISO" in report or "evidencia" in report.lower()


# ─── Category 13: No prohibited dependencies ──────────────────────────────────


def test_no_asyncpg_or_async_engine_in_recommendation_bc() -> None:
    forbidden = ["asyncpg", "create_async_engine", "AsyncSession", "aiohttp", "celery", "redis", "rabbitmq", "kafka"]
    rec_dir = ROOT / "via" / "bounded_contexts" / "recommendation"
    offenders: list[str] = []
    for path in rec_dir.rglob("*.py"):
        src = path.read_text(encoding="utf-8").lower()
        for term in forbidden:
            if term in src:
                offenders.append(f"{path.relative_to(ROOT)} contains {term}")
    assert offenders == [], f"Prohibited dependencies found: {offenders}"


def test_no_hardcoded_secrets_or_coordinates_in_recommendation_bc() -> None:
    suspicious_patterns = ["api_key =", "secret =", "password =", "AAAA", "-77.365", "-11.202"]
    rec_dir = ROOT / "via" / "bounded_contexts" / "recommendation"
    offenders: list[str] = []
    for path in rec_dir.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for pat in suspicious_patterns:
            if pat in src:
                offenders.append(f"{path.relative_to(ROOT)} contains '{pat}'")
    assert offenders == [], f"Suspicious hardcoded values found: {offenders}"


def test_main_py_imports_recommendation_query_service_override() -> None:
    src = (ROOT / "via" / "main.py").read_text(encoding="utf-8")
    assert "get_recommendation_query_service" in src
    assert "_wire_recommendation_dependencies" in src


def test_main_py_calls_wire_recommendation_dependencies_in_create_app() -> None:
    src = (ROOT / "via" / "main.py").read_text(encoding="utf-8")
    assert "_wire_recommendation_dependencies(app, session_factory)" in src


def test_recommendation_orm_model_has_provider_column() -> None:
    assert hasattr(RecommendationModel, "provider")


def test_recommendation_repository_accepts_provider_param() -> None:
    import inspect
    sig = inspect.signature(SQLAlchemyRecommendationRepository.__init__)
    assert "provider" in sig.parameters


# ─── test doubles ─────────────────────────────────────────────────────────────


class _FakeQueryPort:
    def __init__(self, *, by_id=None, by_evaluation=None, final=None):
        self._by_id = by_id
        self._by_evaluation = by_evaluation or []
        self._final = final or FinalRecommendationResult(evaluation_found=False, recommendation=None)

    def find_by_id(self, rid):
        return self._by_id

    def find_by_evaluation_id(self, eid):
        return self._by_evaluation

    def find_final_for_evaluation(self, eid):
        return self._final


class _FakeQueryService:
    def __init__(self, *, recommendation=None, evaluation_list=None, final_result=None):
        self._rec = recommendation
        self._list = evaluation_list or []
        self._final = final_result or FinalRecommendationResult(evaluation_found=False, recommendation=None)

    def get_recommendation(self, rid):
        return self._rec

    def get_recommendations_for_evaluation(self, eid):
        return self._list

    def get_final_recommendation(self, eid):
        return self._final


class _FakeEvaluationPort:
    def __init__(self, data: EvaluationRecommendationData):
        self.data = data

    def get_results_for_recommendation(self, eid):
        return self.data


class _FakeEvidencePort:
    def __init__(self, evidence=None):
        self._evidence = evidence if evidence is not None else []

    def search_evidence(self, crop_id, gaps, max_fragments):
        return self._evidence[:max_fragments]


class _FakeSession:
    def __init__(self):
        self.added: list = []
        self.add_order: list[str] = []
        self.processed: set[tuple] = set()
        self.commits = 0
        self.rollbacks = 0

    def add(self, model):
        self.added.append(model)
        if isinstance(model, RecommendationModel):
            self.add_order.append("recommendation")
        if isinstance(model, OutboxMessageModel):
            self.add_order.append(model.message_type)
        if isinstance(model, ProcessedMessageIdModel):
            self.processed.add((model.message_id, model.consumer))
            self.add_order.append("processed")

    def get(self, model_type, key):
        if model_type is ProcessedMessageIdModel and key in self.processed:
            return object()
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


# ─── factories ────────────────────────────────────────────────────────────────


def _read_model(
    recommendation_id: UUID = _RID,
    evaluation_id: UUID = _EID,
) -> RecommendationReadModel:
    return RecommendationReadModel(
        recommendation_id=recommendation_id,
        evaluation_id=evaluation_id,
        parcel_id=_PID,
        crop_id="maiz",
        status="GENERATED",
        title="Recomendación para maiz",
        fragment_ids=[],
        created_at=_NOW,
        provider="template",
    )


def _fake_query_service(**kwargs) -> _FakeQueryService:
    return _FakeQueryService(**kwargs)


def _fake_query_port(**kwargs) -> _FakeQueryPort:
    return _FakeQueryPort(**kwargs)


def _crop_result(
    crop_id: str = "maiz",
    score: float = 0.45,
    rank_position: int | None = 1,
    viability_category: str = "CONDICIONAL",
    gaps: list | None = None,
    limiting_factors: list | None = None,
) -> CropEvaluationResultData:
    return CropEvaluationResultData(
        crop_id=crop_id,
        score=score,
        rank_position=rank_position,
        calc_condition="DEFINITIVO",
        viability_category=viability_category,
        gaps=gaps if gaps is not None else [
            GapData(
                criterion_id="agua",
                phase_id="floracion",
                most_limiting_period="p1",
                observed_value=400.0,
                optimal_limit=600.0,
                gap_value=-200.0,
            )
        ],
        limiting_factors=limiting_factors if limiting_factors is not None else [],
    )


def _draft_context(
    crop_result: CropEvaluationResultData | None = None,
    evidence: list | None = None,
) -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=_EID,
        crop_result=crop_result or _crop_result(),
        evidence=evidence if evidence is not None else [],
    )


def _cmd_message(crop_id: str = "maiz") -> Message:
    return Message.command(
        GENERAR_RECOMENDACION_SOLICITADA,
        {"evaluation_id": str(_EID), "crop_id": crop_id, "max_fragments": 5},
        correlation_id=_EID,
    )


def _msg_service(session: _FakeSession, provider_name: str = "template") -> RecommendationMessageCommandService:
    data = EvaluationRecommendationData(
        evaluation_id=_EID,
        crop_results=[_crop_result()],
    )

    def factory(s):
        return RecommendationCommandService(
            evaluation_results_port=_FakeEvaluationPort(data),
            evidence_port=_FakeEvidencePort(evidence=[]),
            drafting_provider=TemplateRecommendationDraftingProvider(),
            repository=SQLAlchemyRecommendationRepository(s, provider=provider_name),
        )

    return RecommendationMessageCommandService(
        session_factory=lambda: session,
        service_factory=factory,
    )


def _recs(session: _FakeSession) -> list[RecommendationModel]:
    return [m for m in session.added if isinstance(m, RecommendationModel)]


def _outbox(session: _FakeSession) -> list[OutboxMessageModel]:
    return [m for m in session.added if isinstance(m, OutboxMessageModel)]


def _minimal_ctx() -> dict:
    return {
        "geojson_file": "examples/parcels/parcela_demo.geojson",
        "crops": ["demo_maiz"],
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "parcel_id": str(_PID),
        "evaluation_id": str(_EID),
        "user_id": "user-123",
        "parcel_snapshot": {},
        "rulebooks": [],
        "rulebook_details": {},
        "outbox_timeline": {"before": [], "after": []},
        "saga_timeline": {"before": {}, "after": {}, "transitions": [], "final_status": "EVALUACION_COMPLETADA"},
        "agroenv_vector": {},
        "agroenv_entries": [],
        "eval_results": [],
        "criterion_details": [],
        "final_api_result": {},
        "final_status": "EVALUACION_COMPLETADA",
        "recommendation": None,
    }
