"""Unit tests for Recommendation 10A base."""

from __future__ import annotations

import ast
from pathlib import Path
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
    assert session.added[0].fragment_ids == [str(item) for item in recommendation.fragment_ids]


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


def _service(
    evaluation_id: UUID,
    crop_result: CropEvaluationResultData | None = None,
    evaluation_data: EvaluationRecommendationData | None = None,
    evidence_port: FakeEvidencePort | None = None,
    drafting_provider: FakeDraftingProvider | None = None,
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
