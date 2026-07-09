"""Unit tests for viability evaluation result repository mapping."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from via.bounded_contexts.viability_evaluation.domain.agronomy_gap import AgronomyGap
from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.domain.limiting_factor import LimitingFactor
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, ViabilityCategory
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_repository import EvaluationRepository
from via.bounded_contexts.viability_evaluation.infrastructure.orm_models import (
    AgronomyGapModel,
    EvaluationCriterionDetailModel,
    EvaluationResultModel,
    LimitingFactorModel,
)


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "via" / "bounded_contexts" / "viability_evaluation" / "domain"
MIGRATION = ROOT / "migrations" / "versions" / "20260614_0002_initial_tables.py"


def test_repository_saves_complete_evaluation_result_traceability() -> None:
    """Persist a full crop result with details, gap and limiting factor rows."""

    session = FakeSession()
    evaluation = _evaluation(_complete_crop_result())

    EvaluationRepository(session).save(evaluation, {"cacao": 3})  # type: ignore[arg-type]

    result = session.one(EvaluationResultModel)
    detail = session.one(EvaluationCriterionDetailModel)
    gap = session.one(AgronomyGapModel)
    factor = session.one(LimitingFactorModel)

    assert result.evaluation_id == evaluation.id
    assert result.crop_id == "cacao"
    assert str(result.score) == "0.8123"
    assert result.rank_position == 1
    assert result.rulebook_version == 3
    assert result.entropy_used is True
    assert detail.result_id == result.id
    assert detail.entropy_fallback_reason == "entropy_fallback: incomplete_or_invalid_series"
    assert detail.w_entropy is None
    assert str(detail.w_hybrid) == "0.7"
    assert gap.result_id == result.id
    assert gap.most_limiting_period == "2026-02"
    assert factor.result_id == result.id
    assert factor.policy == "PENALIZE"
    assert str(factor.penalty_factor) == "0.5"


def test_repository_saves_rank_position_none_for_unranked_results() -> None:
    """Persist rank_position NULL for non-rankable crop results."""

    session = FakeSession()
    result = _complete_crop_result(rank_position=None, viability_category=ViabilityCategory.NO_VIABLE)

    EvaluationRepository(session).save(_evaluation(result), {"cacao": 1})  # type: ignore[arg-type]

    assert session.one(EvaluationResultModel).rank_position is None


def test_repository_saves_score_none_for_no_concluyente() -> None:
    """Persist score NULL for inconclusive crop calculations."""

    session = FakeSession()
    result = _complete_crop_result(score=None, rank_position=None, calc_condition=CalcCondition.NO_CONCLUYENTE)

    EvaluationRepository(session).save(_evaluation(result), {"cacao": 1})  # type: ignore[arg-type]

    persisted = session.one(EvaluationResultModel)
    assert persisted.score is None
    assert persisted.rank_position is None


def test_orm_columns_match_initial_migration_for_evaluation_result_tables() -> None:
    """Check critical ORM columns are backed by the initial migration DDL."""

    migration_text = MIGRATION.read_text(encoding="utf-8")

    expected_columns = {
        EvaluationResultModel: {
            "id",
            "evaluation_id",
            "crop_id",
            "score",
            "calc_condition",
            "viability_category",
            "rank_position",
            "rulebook_version",
            "entropy_used",
            "computed_at",
        },
        EvaluationCriterionDetailModel: {
            "id",
            "result_id",
            "criterion_id",
            "memberships_by_period",
            "aggregated_by_phase",
            "aggregated_membership",
            "w_ahp",
            "w_entropy",
            "w_hybrid",
            "entropy_series_used",
            "entropy_fallback_reason",
        },
        AgronomyGapModel: {
            "id",
            "result_id",
            "criterion_id",
            "phase_id",
            "most_limiting_period",
            "observed_value",
            "optimal_limit",
            "gap_value",
            "membership",
        },
        LimitingFactorModel: {
            "id",
            "result_id",
            "criterion_id",
            "phase_id",
            "policy",
            "penalty_factor",
            "observed_value",
            "optimal_limit",
            "membership",
            "doc_source",
        },
    }

    for model, columns in expected_columns.items():
        assert set(model.__table__.columns.keys()) == columns
        for column in columns:
            assert column in migration_text
        assert model.__table__.schema == "transactional"


def test_evaluation_domain_has_no_forbidden_imports() -> None:
    """Ensure persistence implementation does not leak into the evaluation domain."""

    forbidden_prefixes = (
        "sqlalchemy",
        "via.shared.database",
        "via.bounded_contexts.viability_evaluation.infrastructure",
    )
    offenders: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


class FakeSession:
    """Session double that records ORM instances."""

    def __init__(self) -> None:
        """Create an empty recording session."""

        self.added: list[object] = []

    def add(self, instance: object) -> None:
        """Record an ORM instance added by the repository."""

        self.added.append(instance)

    def flush(self) -> None:
        pass

    def one(self, model_type: type[object]) -> object:
        """Return the single recorded instance of the requested type."""

        matches = [item for item in self.added if isinstance(item, model_type)]
        assert len(matches) == 1
        return matches[0]


def _evaluation(crop_result: CropResult) -> Evaluation:
    return Evaluation(
        id=uuid4(),
        parcel_id=uuid4(),
        requested_by=uuid4(),
        crop_candidates=["cacao"],
        temporal_window={"start": "2026-01-01", "end": "2026-03-31"},
        crop_results=[crop_result],
    )


def _complete_crop_result(
    *,
    score: float | None = 0.8123,
    rank_position: int | None = 1,
    calc_condition: CalcCondition = CalcCondition.DEFINITIVO,
    viability_category: ViabilityCategory = ViabilityCategory.VIABLE,
) -> CropResult:
    return CropResult(
        crop_id="cacao",
        score=score,
        rank_position=rank_position,
        calc_condition=calc_condition,
        viability_category=viability_category,
        criterion_details=[
            CriterionDetail(
                criterion_id="temperatura",
                memberships_by_period={"2026-01": 0.8, "2026-02": 0.7},
                aggregated_by_phase={"floracion": 0.75},
                aggregated_membership=0.75,
                w_ahp=0.6,
                w_entropy=None,
                w_hybrid=0.7,
                entropy_used=False,
                entropy_fallback_reason="entropy_fallback: incomplete_or_invalid_series",
            )
        ],
        gaps=[
            AgronomyGap(
                criterion_id="temperatura",
                phase_id="floracion",
                most_limiting_period="2026-02",
                observed_value=18.0,
                optimal_limit=22.0,
                gap_value=-4.0,
                membership=0.4,
            )
        ],
        limiting_factors=[
            LimitingFactor(
                criterion_id="temperatura",
                phase_id="floracion",
                policy=CriticalPolicy.PENALIZE,
                penalty_factor=0.5,
                observed_value=18.0,
                optimal_limit=22.0,
                membership=0.0,
                doc_source="INIA",
            )
        ],
        entropy_series_sufficient=True,
    )


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
