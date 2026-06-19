"""Unit tests for viability evaluation command service and consumer."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from via.bounded_contexts.viability_evaluation.application.command_service import (
    VIABILITY_EVALUATION_CONSUMER,
    ExecuteEvaluationCommand,
    McdaRuntimeSettings,
    PureMcdaEvaluationEngine,
    ViabilityEvaluationCommandService,
    _success_events,
)
from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVariableData,
    AgroenvVectorData,
    EvaluationCriterionSpec,
    RulebookEvaluationData,
)
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, ViabilityCategory
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_consumer import ViabilityEvaluationConsumer
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import ProcessedMessageIdModel
from via.shared.orchestration.evaluation_process_manager.commands import EJECUTAR_EVALUACION_VIABILIDAD
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_VIABILIDAD_COMPLETADA,
    EVALUACION_VIABILIDAD_FALLIDA,
    VECTOR_BRECHAS_GENERADO,
)
from via.shared.outbox.models import OutboxMessageModel


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "via" / "bounded_contexts" / "viability_evaluation" / "domain"


def test_consumer_ignores_messages_that_are_not_execute_evaluation() -> None:
    service = FakeCommandService()
    consumer = ViabilityEvaluationConsumer(service)  # type: ignore[arg-type]
    ignored = Message.command("OtroComando", {})
    handled = _message()

    consumer.handle(ignored)
    consumer.handle(handled)

    assert service.messages == [handled]


def test_command_service_processes_valid_command_and_persists_once() -> None:
    session = FakeSession()
    engine = FakeEngine(_evaluation(UUID(_EVALUATION_ID)))
    service = _service(session, engine=engine)
    message = _message()

    service.handle_execute_command(message)

    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.saved_evaluations) == 1
    assert session.saved_versions == [{"cacao": 2}]
    assert engine.settings_seen == _settings()
    assert engine.command_seen.evaluation_id == UUID(_EVALUATION_ID)


def test_outbox_receives_success_events_with_evaluation_correlation_id() -> None:
    session = FakeSession()
    service = _service(session, engine=FakeEngine(_evaluation(UUID(_EVALUATION_ID))))
    message = _message()

    service.handle_execute_command(message)

    outbox = _outbox(session)
    assert [item.message_type for item in outbox] == [EVALUACION_VIABILIDAD_COMPLETADA, VECTOR_BRECHAS_GENERADO]
    assert all(item.correlation_id == UUID(_EVALUATION_ID) for item in outbox)
    assert outbox[0].payload_json["evaluation_id"] == _EVALUATION_ID
    assert outbox[1].payload_json["evaluation_id"] == _EVALUATION_ID


def test_failure_generates_evaluation_failure_event() -> None:
    session = FakeSession()
    service = _service(session, engine=FailingEngine())
    message = _message()

    service.handle_execute_command(message)

    assert session.saved_evaluations == []
    outbox = _outbox(session)
    assert len(outbox) == 1
    assert outbox[0].message_type == EVALUACION_VIABILIDAD_FALLIDA
    assert outbox[0].correlation_id == UUID(_EVALUATION_ID)
    assert outbox[0].payload_json["failure_cause"] == "boom"


def test_duplicate_does_not_repeat_persistence_or_outbox() -> None:
    session = FakeSession()
    message = _message()
    session.processed.add((message.id, VIABILITY_EVALUATION_CONSUMER))
    service = _service(session, engine=FakeEngine(_evaluation(UUID(_EVALUATION_ID))))

    service.handle_execute_command(message)

    assert session.saved_evaluations == []
    assert _outbox(session) == []


def test_idempotency_is_marked_in_the_same_transaction_after_effects() -> None:
    session = FakeSession()
    message = _message()
    service = _service(session, engine=FakeEngine(_evaluation(UUID(_EVALUATION_ID))))

    service.handle_execute_command(message)

    assert (message.id, VIABILITY_EVALUATION_CONSUMER) in session.processed
    assert session.add_order[-1] == "processed"
    assert session.commits == 1


def test_pure_engine_generates_real_deficit_gap_with_most_limiting_period_and_optimal_limit() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(_command(), _vector([("2026-01", 5.0), ("2026-02", 15.0)]), [_rulebook()], _settings())
    result = evaluation.crop_results[0]

    assert len(result.gaps) == 1
    assert result.gaps[0].most_limiting_period == "2026-01"
    assert result.gaps[0].optimal_limit == 10.0
    assert result.gaps[0].gap_value == -5.0


def test_pure_engine_generates_real_excess_gap_with_derived_upper_optimal_limit() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(_command(), _vector([("2026-01", 25.0), ("2026-02", 15.0)]), [_rulebook()], _settings())
    gap = evaluation.crop_results[0].gaps[0]

    assert gap.most_limiting_period == "2026-01"
    assert gap.optimal_limit == 20.0
    assert gap.gap_value == 5.0


def test_critical_no_viable_generates_limiting_factor_and_is_excluded_from_ranking() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(),
        _vector([("2026-01", 0.0)]),
        [_rulebook(critical_policy=CriticalPolicy.NO_VIABLE.value, penalty_factor=None)],
        _settings(),
    )
    result = evaluation.crop_results[0]

    assert result.viability_category == ViabilityCategory.NO_VIABLE
    assert result.rank_position is None
    assert result.limiting_factors[0].policy == CriticalPolicy.NO_VIABLE
    assert result.limiting_factors[0].observed_value == 0.0
    assert result.limiting_factors[0].optimal_limit == 10.0
    assert result.limiting_factors[0].doc_source == "manual"


def test_critical_penalize_generates_limiting_factor_and_penalty_factor_changes_score() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(),
        _vector([("2026-01", 0.0)]),
        [_rulebook(critical_policy=CriticalPolicy.PENALIZE.value, penalty_factor=0.5)],
        _settings(),
    )
    result = evaluation.crop_results[0]

    assert result.limiting_factors[0].policy == CriticalPolicy.PENALIZE
    assert result.limiting_factors[0].penalty_factor == 0.5
    assert result.score == pytest.approx(0.005)
    assert result.viability_category == ViabilityCategory.NO_VIABLE


def test_non_critical_deficit_hidrico_zero_creates_gap_without_automatic_no_viable() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(),
        _multi_vector(
            {
                "temperatura": 20.0,
                "pendiente": 3.0,
                "deficit_hidrico": 1200.0,
            }
        ),
        [
            _multi_rulebook(
                [
                    _spec("temperatura", "temperatura", 0.45, {"a": 10.0, "b": 15.0, "c": 25.0, "d": 30.0}),
                    _spec("pendiente", "pendiente", 0.45, {"a": 0.0, "b": 0.0, "c": 8.0, "d": 15.0}),
                    _spec("deficit_hidrico", "deficit_hidrico", 0.10, {"a": 0.0, "b": 0.0, "c": 200.0, "d": 800.0}),
                ]
            )
        ],
        _settings(),
    )
    result = evaluation.crop_results[0]

    assert result.score == pytest.approx(0.05**0.10)
    assert result.viability_category != ViabilityCategory.NO_VIABLE
    assert result.rank_position == 1
    assert result.limiting_factors == []
    assert [gap.criterion_id for gap in result.gaps] == ["deficit_hidrico"]
    assert result.gaps[0].observed_value == 1200.0


def test_papa_altitudinal_critical_zero_still_forces_no_viable() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(
        _command(),
        _multi_vector(
            {
                "temperatura": 20.0,
                "aptitud_altitudinal": 422.49,
            },
            crop_id="demo_papa",
        ),
        [
            _multi_rulebook(
                [
                    _spec("temperatura", "temperatura", 0.5, {"a": 10.0, "b": 15.0, "c": 25.0, "d": 30.0}),
                    _spec(
                        "aptitud_altitudinal",
                        "elevacion_m",
                        0.5,
                        {"a": 1000.0, "b": 2800.0, "c": 3500.0, "d": 4000.0},
                        critical_policy=CriticalPolicy.NO_VIABLE.value,
                    ),
                ],
                crop_id="demo_papa",
            )
        ],
        _settings(),
    )
    result = evaluation.crop_results[0]

    assert result.crop_id == "demo_papa"
    assert result.score == 0.0
    assert result.viability_category == ViabilityCategory.NO_VIABLE
    assert result.rank_position is None
    assert result.limiting_factors[0].criterion_id == "aptitud_altitudinal"


def test_vector_brechas_generado_contains_real_calculated_gaps() -> None:
    evaluation = PureMcdaEvaluationEngine().evaluate(_command(), _vector([("2026-01", 5.0), ("2026-02", 15.0)]), [_rulebook()], _settings())

    gap_event = _success_events(evaluation)[1]

    assert gap_event.type == VECTOR_BRECHAS_GENERADO
    assert gap_event.payload["gaps"] != []
    assert gap_event.payload["gaps"][0]["most_limiting_period"] == "2026-01"


def test_domain_does_not_import_config_or_infrastructure() -> None:
    offenders: list[str] = []
    forbidden_prefixes = (
        "via.config",
        "sqlalchemy",
        "via.shared.outbox",
        "via.shared.event_bus",
        "via.bounded_contexts.viability_evaluation.infrastructure",
    )
    for path in DOMAIN.rglob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


class FakeCommandService:
    """Command service double for consumer tests."""

    def __init__(self) -> None:
        """Create an empty message recorder."""

        self.messages: list[Message] = []

    def handle_execute_command(self, message: Message) -> None:
        """Record handled messages."""

        self.messages.append(message)


class FakeEngine:
    """MCDA engine double that records settings received from application."""

    def __init__(self, evaluation: Evaluation) -> None:
        """Create the engine with a deterministic evaluation result."""

        self.evaluation = evaluation
        self.settings_seen: McdaRuntimeSettings | None = None
        self.command_seen: ExecuteEvaluationCommand | None = None

    def evaluate(
        self,
        command: ExecuteEvaluationCommand,
        vector: AgroenvVectorData,
        rulebooks: list[RulebookEvaluationData],
        settings: McdaRuntimeSettings,
    ) -> Evaluation:
        """Return the configured evaluation and record MCDA settings."""

        self.command_seen = command
        self.settings_seen = settings
        return self.evaluation


class FailingEngine:
    """MCDA engine double that simulates calculation failure."""

    def evaluate(
        self,
        command: ExecuteEvaluationCommand,
        vector: AgroenvVectorData,
        rulebooks: list[RulebookEvaluationData],
        settings: McdaRuntimeSettings,
    ) -> Evaluation:
        """Raise an evaluation failure."""

        raise RuntimeError("boom")


class FakeRulebookPort:
    """Rulebook ACL port double."""

    def get_active_rulebook(self, crop_id: str) -> RulebookEvaluationData:
        """Return a minimal active rulebook DTO."""

        return RulebookEvaluationData(
            crop_id=crop_id,
            rulebook_id=uuid4(),
            version=2,
            criteria=[
                EvaluationCriterionSpec(
                    criterion_id="rain",
                    crop_id=crop_id,
                    phase_id="flowering",
                    variable_name="rain",
                    w_ahp=1.0,
                    phase_weight=1.0,
                    temporal_periods=[{"period_key": "2026-01", "temporal_weight": 1.0}],
                    membership_fn={"type": "TRAPEZOIDAL", "a": 0.0, "b": 10.0, "c": 20.0, "d": 30.0},
                    critical_policy="PENALIZE",
                    penalty_factor=0.5,
                    doc_source="manual",
                )
            ],
        )


class FakeAgroenvPort:
    """Agroenvironmental vector ACL port double."""

    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        """Return vector data for one crop candidate."""

        return AgroenvVectorData(evaluation_id=evaluation_id, parcel_id=uuid4(), variables=[])


class FakeRepository:
    """Repository double recording persisted evaluations."""

    def __init__(self, session: "FakeSession") -> None:
        """Keep the fake session used by the command service."""

        self._session = session

    def save(self, evaluation: Evaluation, rulebook_versions: dict[str, int]) -> None:
        """Record repository persistence calls."""

        self._session.saved_evaluations.append(evaluation)
        self._session.saved_versions.append(rulebook_versions)


class FakeSession:
    """Session double used to verify transactional side effects."""

    def __init__(self) -> None:
        """Create an empty fake session."""

        self.added: list[object] = []
        self.add_order: list[str] = []
        self.processed: set[tuple[object, str]] = set()
        self.saved_evaluations: list[Evaluation] = []
        self.saved_versions: list[dict[str, int]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def add(self, model: object) -> None:
        """Record added models and processed-message markers."""

        self.added.append(model)
        if isinstance(model, ProcessedMessageIdModel):
            self.processed.add((model.message_id, model.consumer))
            self.add_order.append("processed")
        if isinstance(model, OutboxMessageModel):
            self.add_order.append(model.message_type)

    def get(self, model_type: type, key: tuple[object, str]) -> object | None:
        """Return an idempotency marker when already processed."""

        if model_type is ProcessedMessageIdModel and key in self.processed:
            return object()
        return None

    def commit(self) -> None:
        """Record a commit."""

        self.commits += 1

    def rollback(self) -> None:
        """Record a rollback."""

        self.rollbacks += 1

    def close(self) -> None:
        """Record session close."""

        self.closed = True


_EVALUATION_ID = "00000000-0000-0000-0000-000000000123"


def _service(session: FakeSession, engine: object) -> ViabilityEvaluationCommandService:
    return ViabilityEvaluationCommandService(
        session_factory=lambda: session,
        rulebook_port=FakeRulebookPort(),
        agroenv_vector_port=FakeAgroenvPort(),
        repository_factory=FakeRepository,
        settings=_settings(),
        engine=engine,  # type: ignore[arg-type]
    )


def _settings() -> McdaRuntimeSettings:
    return McdaRuntimeSettings(
        mcda_alpha=0.7,
        mcda_min_temporal_series_length=3,
        mcda_entropy_min_divergence=1e-9,
        mcda_viable_threshold=0.70,
        mcda_condicional_threshold=0.40,
        mcda_penalize_epsilon=0.01,
    )


def _message() -> Message:
    evaluation_id = UUID(_EVALUATION_ID)
    return Message.command(
        EJECUTAR_EVALUACION_VIABILIDAD,
        {
            "evaluation_id": str(evaluation_id),
            "extraction_result": {"crop_candidates": ["cacao"], "temporal_window": {"start": "2026-01-01"}},
        },
        correlation_id=evaluation_id,
    )


def _command() -> ExecuteEvaluationCommand:
    return ExecuteEvaluationCommand.from_payload(_message().payload)


def _rulebook(critical_policy: str = CriticalPolicy.PENALIZE.value, penalty_factor: float | None = 0.5) -> RulebookEvaluationData:
    return RulebookEvaluationData(
        crop_id="cacao",
        rulebook_id=uuid4(),
        version=2,
        criteria=[
            EvaluationCriterionSpec(
                criterion_id="rain",
                crop_id="cacao",
                phase_id="flowering",
                variable_name="rain",
                w_ahp=1.0,
                phase_weight=1.0,
                temporal_periods=[
                    {"period_key": "2026-01", "temporal_weight": 0.5},
                    {"period_key": "2026-02", "temporal_weight": 0.5},
                ],
                membership_fn={"type": "TRAPEZOIDAL", "a": 0.0, "b": 10.0, "c": 20.0, "d": 30.0},
                critical_policy=critical_policy,
                penalty_factor=penalty_factor,
                doc_source="manual",
            )
        ],
    )


def _multi_rulebook(specs: list[EvaluationCriterionSpec], crop_id: str = "cacao") -> RulebookEvaluationData:
    return RulebookEvaluationData(crop_id=crop_id, rulebook_id=uuid4(), version=2, criteria=specs)


def _spec(
    criterion_id: str,
    variable_name: str,
    w_ahp: float,
    membership_fn: dict,
    critical_policy: str = "NONE",
    penalty_factor: float | None = None,
) -> EvaluationCriterionSpec:
    return EvaluationCriterionSpec(
        criterion_id=criterion_id,
        crop_id="cacao",
        phase_id="potencial",
        variable_name=variable_name,
        w_ahp=w_ahp,
        phase_weight=1.0,
        temporal_periods=[{"period_key": "anual", "temporal_weight": 1.0}],
        membership_fn={"type": "TRAPEZOIDAL", **membership_fn},
        critical_policy=critical_policy,
        penalty_factor=penalty_factor,
        doc_source="manual",
    )


def _vector(period_values: list[tuple[str, float]]) -> AgroenvVectorData:
    return AgroenvVectorData(
        evaluation_id=UUID(_EVALUATION_ID),
        parcel_id=uuid4(),
        variables=[
            AgroenvVariableData(
                variable_name="rain",
                criterion_id="rain",
                crop_id="cacao",
                phase_id="flowering",
                period_key=period_key,
                value=value,
                unit="mm",
                status="OK",
                dataset_key="gee",
                band="rain",
                source="stub",
            )
            for period_key, value in period_values
        ],
    )


def _multi_vector(criterion_values: dict[str, float], crop_id: str = "cacao") -> AgroenvVectorData:
    return AgroenvVectorData(
        evaluation_id=UUID(_EVALUATION_ID),
        parcel_id=uuid4(),
        variables=[
            AgroenvVariableData(
                variable_name=criterion_id,
                criterion_id=criterion_id,
                crop_id=crop_id,
                phase_id="potencial",
                period_key="anual",
                value=value,
                unit="demo",
                status="OK",
                dataset_key="gee",
                band=criterion_id,
                source="stub",
            )
            for criterion_id, value in criterion_values.items()
        ],
    )


def _evaluation(evaluation_id: UUID) -> Evaluation:
    return Evaluation(
        id=evaluation_id,
        parcel_id=uuid4(),
        requested_by=uuid4(),
        crop_candidates=["cacao"],
        temporal_window={"start": "2026-01-01"},
        crop_results=[
            CropResult(
                crop_id="cacao",
                score=0.8,
                rank_position=1,
                calc_condition=CalcCondition.DEFINITIVO,
                viability_category=ViabilityCategory.VIABLE,
            )
        ],
    )


def _outbox(session: FakeSession) -> list[OutboxMessageModel]:
    return [model for model in session.added if isinstance(model, OutboxMessageModel)]


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
