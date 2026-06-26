"""Command service for viability evaluation execution."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.viability_evaluation.application.ports import (
    AgroenvVectorData,
    IEvaluationRepository,
    IAgroenvVectorPort,
    IRulebookEvaluationPort,
    RulebookEvaluationData,
)
from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.entropy_weights import EntropyWeightsService
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.domain.hybrid_weights import HybridWeightsService
from via.bounded_contexts.viability_evaluation.domain.mcda_basic import TrapezoidalMembershipFunction, build_criterion_detail
from via.bounded_contexts.viability_evaluation.domain.mcda_completion import BasicCropEvaluationService
from via.bounded_contexts.viability_evaluation.domain.mcda_policy import (
    CriticalCriterionTrace,
    CriticalPolicyService,
    GapCalculationService,
    PhaseGapTrace,
    RankingService,
)
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, ViabilityCategory
from via.config import Settings
from via.shared.event_bus.message import Message
from via.shared.idempotency.processed_message_store import IdempotentConsumerMixin
from via.shared.orchestration.evaluation_process_manager.commands import EJECUTAR_EVALUACION_VIABILIDAD
from via.shared.orchestration.evaluation_process_manager.events import (
    EVALUACION_VIABILIDAD_COMPLETADA,
    EVALUACION_VIABILIDAD_FALLIDA,
    VECTOR_BRECHAS_GENERADO,
)
from via.shared.outbox.outbox_writer import OutboxWriter


VIABILITY_EVALUATION_CONSUMER = "viability-evaluation-consumer"
AGGREGATE_TYPE = "Evaluation"

# Data-sufficiency policy: if the total AHP weight of missing criteria meets or exceeds
# this threshold, the result is NO_CONCLUYENTE regardless of the partial score.
# At 0.30, any two or more climate criteria missing (total climate weight = 0.67) triggers it.
_MISSING_WEIGHT_THRESHOLD: float = 0.30

# Topographic criteria are structural: a conclusion requires them even when their combined
# weight (0.28) falls below the generic threshold.
_STRUCTURAL_CRITERIA: frozenset[str] = frozenset({"aptitud_altitudinal", "aptitud_topografica"})
_SITE_STATIC_CRITERIA: frozenset[str] = frozenset(
    {
        "aptitud_altitudinal",
        "aptitud_topografica",
        "reaccion_suelo_ph",
        "contenido_arcilla",
        "contenido_arena",
        "carbono_organico_suelo",
        "profundidad_suelo",
        "salinidad_suelo",
        "cobertura_actual_auxiliar",
    }
)


@dataclass(frozen=True)
class McdaRuntimeSettings:
    """MCDA knobs injected by the application layer."""

    mcda_alpha: float
    mcda_min_temporal_series_length: int
    mcda_entropy_min_divergence: float
    mcda_viable_threshold: float
    mcda_condicional_threshold: float
    mcda_penalize_epsilon: float
    mcda_non_critical_membership_floor: float = 0.05

    @classmethod
    def from_settings(cls, settings: Settings) -> "McdaRuntimeSettings":
        """Build MCDA runtime settings from centralized VIA settings."""

        return cls(
            mcda_alpha=settings.mcda_alpha,
            mcda_min_temporal_series_length=settings.mcda_min_temporal_series_length,
            mcda_entropy_min_divergence=settings.mcda_entropy_min_divergence,
            mcda_viable_threshold=settings.mcda_viable_threshold,
            mcda_condicional_threshold=settings.mcda_condicional_threshold,
            mcda_penalize_epsilon=settings.mcda_penalize_epsilon,
            mcda_non_critical_membership_floor=settings.mcda_non_critical_membership_floor,
        )


@dataclass(frozen=True)
class ExecuteEvaluationCommand:
    """Application command parsed from the saga message payload."""

    evaluation_id: UUID
    extraction_result: dict

    @classmethod
    def from_payload(cls, payload: dict) -> "ExecuteEvaluationCommand":
        """Deserialize an EjecutarEvaluacionViabilidad payload."""

        return cls(evaluation_id=UUID(str(payload["evaluation_id"])), extraction_result=dict(payload.get("extraction_result", {})))


@dataclass(frozen=True)
class PhaseEvaluationTrace:
    """Application trace needed to build gaps and critical-factor inputs."""

    criterion_id: str
    phase_id: str
    membership_fn: TrapezoidalMembershipFunction
    aggregated_membership: float
    period_memberships: dict[str, float]
    observed_values: dict[str, float]
    optimal_limits: dict[str, float]
    critical_policy: str
    penalty_factor: float | None
    doc_source: str | None


class IMcdaEvaluationEngine(Protocol):
    """Pure MCDA engine port used by the command service."""

    def evaluate(
        self,
        command: ExecuteEvaluationCommand,
        vector: AgroenvVectorData,
        rulebooks: list[RulebookEvaluationData],
        settings: McdaRuntimeSettings,
    ) -> Evaluation:
        """Return a computed evaluation aggregate."""


class ViabilityEvaluationCommandService(IdempotentConsumerMixin):
    """Execute viability evaluation commands with idempotency and outbox events."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        rulebook_port: IRulebookEvaluationPort,
        agroenv_vector_port: IAgroenvVectorPort,
        repository_factory: Callable[[Session], IEvaluationRepository],
        settings: McdaRuntimeSettings,
        engine: IMcdaEvaluationEngine | None = None,
        outbox_writer: OutboxWriter | None = None,
    ) -> None:
        """Create the command service with application and infrastructure ports."""

        self._session_factory = session_factory
        self._rulebook_port = rulebook_port
        self._agroenv_vector_port = agroenv_vector_port
        self._repository_factory = repository_factory
        self._settings = settings
        self._engine = engine or PureMcdaEvaluationEngine()
        self._outbox_writer = outbox_writer or OutboxWriter()

    def handle_execute_command(self, message: Message, consumer_name: str = VIABILITY_EVALUATION_CONSUMER) -> None:
        """Consume one EjecutarEvaluacionViabilidad command idempotently."""

        command = ExecuteEvaluationCommand.from_payload(message.payload)
        with self._transaction() as session:
            if self.is_already_processed(session, message.id, consumer_name):
                return

            try:
                vector = self._agroenv_vector_port.get_vector_for_evaluation(command.evaluation_id)
                crop_candidates = _crop_candidates(command, vector)
                rulebooks = [self._rulebook_port.get_active_rulebook(crop_id) for crop_id in crop_candidates]
                evaluation = self._engine.evaluate(command, vector, rulebooks, self._settings)
                self._repository_factory(session).save(evaluation, {rulebook.crop_id: rulebook.version for rulebook in rulebooks})
                for event in _success_events(evaluation):
                    self._outbox_writer.write(session, event, AGGREGATE_TYPE, evaluation.id)
            except Exception as exc:
                failure = Message.event(
                    EVALUACION_VIABILIDAD_FALLIDA,
                    {"evaluation_id": str(command.evaluation_id), "failure_cause": str(exc)},
                    correlation_id=command.evaluation_id,
                )
                self._outbox_writer.write(session, failure, "EvaluationSaga", command.evaluation_id)

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


class PureMcdaEvaluationEngine:
    """Compose the already implemented pure MCDA domain services."""

    def __init__(
        self,
        entropy_service: EntropyWeightsService | None = None,
        hybrid_service: HybridWeightsService | None = None,
        crop_service: BasicCropEvaluationService | None = None,
        critical_policy_service: CriticalPolicyService | None = None,
        gap_service: GapCalculationService | None = None,
        ranking_service: RankingService | None = None,
    ) -> None:
        """Create the pure engine with domain service dependencies."""

        self._entropy_service = entropy_service or EntropyWeightsService()
        self._hybrid_service = hybrid_service or HybridWeightsService()
        self._crop_service = crop_service or BasicCropEvaluationService()
        self._critical_policy_service = critical_policy_service or CriticalPolicyService()
        self._gap_service = gap_service or GapCalculationService()
        self._ranking_service = ranking_service or RankingService()

    def evaluate(
        self,
        command: ExecuteEvaluationCommand,
        vector: AgroenvVectorData,
        rulebooks: list[RulebookEvaluationData],
        settings: McdaRuntimeSettings,
    ) -> Evaluation:
        """Return an evaluation aggregate calculated from ACL DTOs."""

        crop_results: list[CropResult] = []
        for rulebook in rulebooks:
            details, phase_traces, missing_criteria, unrecognized_variables = _criterion_details_for_crop(rulebook, vector)
            w_ahp = {detail.criterion_id: float(detail.w_ahp) for detail in details}
            # Full AHP weights for ALL criteria in the rulebook (including those with missing data).
            # Used by the data-sufficiency policy to compute missing_weight correctly.
            all_ahp_weights = {
                criterion_id: float(
                    next(spec.w_ahp for spec in rulebook.criteria if spec.criterion_id == criterion_id)
                )
                for criterion_id in dict.fromkeys(spec.criterion_id for spec in rulebook.criteria)
            }
            entropy_result = self._entropy_service.calculate(
                {detail.criterion_id: [float(value) for value in detail.memberships_by_period.values()] for detail in details},
                min_series_length=settings.mcda_min_temporal_series_length,
                min_divergence=settings.mcda_entropy_min_divergence,
            )
            w_hybrid = self._hybrid_service.combine(w_ahp, entropy_result.weights, alpha=settings.mcda_alpha)
            enriched_details = [
                detail.with_entropy_weights(
                    w_entropy=None if entropy_result.weights is None else entropy_result.weights[detail.criterion_id],
                    w_hybrid=w_hybrid[detail.criterion_id],
                    entropy_used=entropy_result.entropy_used,
                    entropy_fallback_reason=entropy_result.fallback_reason,
                )
                for detail in details
            ]
            aggregated = {detail.criterion_id: float(detail.aggregated_membership) for detail in enriched_details}
            critical_criteria = {
                criterion.criterion_id
                for criterion in rulebook.criteria
                if criterion.critical_policy in {CriticalPolicy.NO_VIABLE.value, CriticalPolicy.PENALIZE.value}
            }
            basic_result = self._crop_service.evaluate(
                crop_id=rulebook.crop_id,
                aggregated_memberships=aggregated,
                hybrid_weights=w_hybrid,
                missing_criteria=missing_criteria,
                critical_criteria=critical_criteria,
                unrecognized_variables=unrecognized_variables,
                viable_threshold=settings.mcda_viable_threshold,
                condicional_threshold=settings.mcda_condicional_threshold,
                non_critical_membership_floor=settings.mcda_non_critical_membership_floor,
            )
            critical_result = self._critical_policy_service.apply(
                aggregated_memberships=aggregated,
                hybrid_weights=w_hybrid,
                calc_condition=basic_result.calc_condition,
                critical_traces=_critical_traces(phase_traces),
                critical_criteria=critical_criteria,
                penalize_epsilon=settings.mcda_penalize_epsilon,
                non_critical_membership_floor=settings.mcda_non_critical_membership_floor,
                viable_threshold=settings.mcda_viable_threshold,
                condicional_threshold=settings.mcda_condicional_threshold,
            )
            gaps = self._gap_service.calculate(_phase_gap_traces(phase_traces))

            final_score, final_condition, final_category = _apply_sufficiency_policy(
                basic_result=basic_result,
                critical_result=critical_result,
                all_ahp_weights=all_ahp_weights,
            )

            crop_results.append(
                CropResult(
                    crop_id=rulebook.crop_id,
                    score=final_score,
                    rank_position=None,
                    calc_condition=final_condition,
                    viability_category=final_category,
                    criterion_details=enriched_details,
                    gaps=gaps,
                    limiting_factors=critical_result.limiting_factors,
                    missing_criteria=basic_result.missing_criteria,
                    unrecognized_variables=basic_result.unrecognized_variables,
                    entropy_series_sufficient=entropy_result.entropy_used,
                )
            )

        ranked_results = self._ranking_service.assign_rank_positions(crop_results)
        return Evaluation(
            id=command.evaluation_id,
            parcel_id=vector.parcel_id,
            requested_by=command.evaluation_id,
            crop_candidates=[rulebook.crop_id for rulebook in rulebooks],
            temporal_window=dict(command.extraction_result.get("temporal_window", {})),
            crop_results=ranked_results,
        )


def _criterion_details_for_crop(
    rulebook: RulebookEvaluationData,
    vector: AgroenvVectorData,
) -> tuple[list[CriterionDetail], list[PhaseEvaluationTrace], list[str], list[str]]:
    details: list[CriterionDetail] = []
    phase_traces: list[PhaseEvaluationTrace] = []
    missing_criteria: list[str] = []
    recognized = {criterion.criterion_id for criterion in rulebook.criteria}
    unrecognized = sorted(
        {
            variable.variable_name
            for variable in vector.variables
            if variable.crop_id == rulebook.crop_id and variable.criterion_id not in recognized and variable.status != "CRITERIO_FALTANTE"
        }
    )

    for criterion_id in dict.fromkeys(criterion.criterion_id for criterion in rulebook.criteria):
        criterion_specs = [criterion for criterion in rulebook.criteria if criterion.criterion_id == criterion_id]
        memberships_by_phase: dict[str, dict[str, float]] = {}
        temporal_weights_by_phase: dict[str, dict[str, float]] = {}
        phase_weights: dict[str, float] = {}
        w_ahp = criterion_specs[0].w_ahp
        criterion_missing = False

        for spec in criterion_specs:
            phase_variables = [
                variable
                for variable in vector.variables
                if variable.crop_id == rulebook.crop_id
                and variable.criterion_id == criterion_id
                and variable.phase_id == spec.phase_id
            ]
            if not phase_variables or any(variable.status == "CRITERIO_FALTANTE" or variable.value is None for variable in phase_variables):
                criterion_missing = True
                continue
            membership_fn = TrapezoidalMembershipFunction.from_mapping(spec.membership_fn)
            phase_memberships = {variable.period_key: membership_fn.membership(float(variable.value)) for variable in phase_variables}
            memberships_by_phase[spec.phase_id] = phase_memberships
            temporal_weights_by_phase[spec.phase_id] = _temporal_weights(spec, phase_memberships)
            phase_weights[spec.phase_id] = spec.phase_weight
            observed_values = {variable.period_key: float(variable.value) for variable in phase_variables if variable.value is not None}
            phase_traces.append(
                PhaseEvaluationTrace(
                    criterion_id=criterion_id,
                    phase_id=spec.phase_id,
                    membership_fn=membership_fn,
                    aggregated_membership=_aggregate_phase_for_trace(phase_memberships, temporal_weights_by_phase[spec.phase_id]),
                    period_memberships=phase_memberships,
                    observed_values=observed_values,
                    optimal_limits={
                        period_key: _nearest_optimal_limit(observed_value, membership_fn)
                        for period_key, observed_value in observed_values.items()
                    },
                    critical_policy=spec.critical_policy,
                    penalty_factor=spec.penalty_factor,
                    doc_source=spec.doc_source,
                )
            )

        if criterion_missing:
            missing_criteria.append(criterion_id)
        if memberships_by_phase:
            details.append(
                build_criterion_detail(
                    criterion_id=criterion_id,
                    memberships_by_phase_period=memberships_by_phase,
                    temporal_weights_by_phase=temporal_weights_by_phase,
                    phase_weights=_normalize(phase_weights),
                    w_ahp=w_ahp,
                )
            )

    return details, phase_traces, missing_criteria, unrecognized


def _aggregate_phase_for_trace(period_memberships: dict[str, float], temporal_weights: dict[str, float]) -> float:
    if any(value == 0.0 for value in period_memberships.values()):
        return 0.0
    result = 1.0
    for period_key, membership in period_memberships.items():
        result *= membership ** temporal_weights[period_key]
    return result


def _nearest_optimal_limit(observed_value: float, membership_fn: TrapezoidalMembershipFunction) -> float:
    if observed_value < float(membership_fn.b):
        return float(membership_fn.b)
    if observed_value > float(membership_fn.c):
        return float(membership_fn.c)
    return observed_value


def _phase_gap_traces(phase_traces: list[PhaseEvaluationTrace]) -> list[PhaseGapTrace]:
    return [
        PhaseGapTrace(
            criterion_id=trace.criterion_id,
            phase_id=trace.phase_id,
            aggregated_membership=trace.aggregated_membership,
            period_memberships=trace.period_memberships,
            observed_values=trace.observed_values,
            optimal_limits=trace.optimal_limits,
        )
        for trace in _dedupe_site_static_traces(phase_traces)
        if trace.aggregated_membership < 1.0
    ]


def _critical_traces(phase_traces: list[PhaseEvaluationTrace]) -> list[CriticalCriterionTrace]:
    traces: list[CriticalCriterionTrace] = []
    for trace in _dedupe_site_static_traces(phase_traces):
        if trace.aggregated_membership != 0.0:
            continue
        if trace.critical_policy not in {CriticalPolicy.NO_VIABLE.value, CriticalPolicy.PENALIZE.value}:
            continue
        period_key = min(trace.period_memberships, key=lambda period: (trace.period_memberships[period], period))
        traces.append(
            CriticalCriterionTrace(
                criterion_id=trace.criterion_id,
                phase_id=trace.phase_id,
                policy=CriticalPolicy(trace.critical_policy),
                penalty_factor=trace.penalty_factor,
                observed_value=trace.observed_values[period_key],
                optimal_limit=trace.optimal_limits[period_key],
                membership=0.0,
                doc_source=trace.doc_source,
            )
        )
    return traces


def _dedupe_site_static_traces(phase_traces: list[PhaseEvaluationTrace]) -> list[PhaseEvaluationTrace]:
    selected_static: dict[str, PhaseEvaluationTrace] = {}
    dynamic_traces: list[PhaseEvaluationTrace] = []

    for trace in phase_traces:
        if trace.criterion_id not in _SITE_STATIC_CRITERIA:
            dynamic_traces.append(trace)
            continue
        current = selected_static.get(trace.criterion_id)
        if current is None or _site_trace_sort_key(trace) < _site_trace_sort_key(current):
            selected_static[trace.criterion_id] = trace

    return dynamic_traces + list(selected_static.values())


def _site_trace_sort_key(trace: PhaseEvaluationTrace) -> tuple[float, str]:
    return (trace.aggregated_membership, trace.phase_id)


def _apply_sufficiency_policy(
    basic_result: object,
    critical_result: object,
    all_ahp_weights: dict[str, float],
) -> tuple[float | None, CalcCondition, ViabilityCategory]:
    """Return (score, calc_condition, viability_category) after applying the data-sufficiency policy.

    Two conditions trigger NO_CONCLUYENTE:
    1. critical path: basic_result.calc_condition is already NO_CONCLUYENTE
       (a criterion marked critical_policy=NO_VIABLE/PENALIZE had no data).
    2. weight threshold: the sum of AHP weights for missing criteria ≥ 0.30.
    3. structural: any topographic criterion (elevacion, pendiente) is missing,
       regardless of weight, because they are required for a spatial conclusion.

    In all three cases the partial score is preserved for traceability but
    the viability category is set to NO_CONCLUYENTE and rank_position is null.
    all_ahp_weights must contain ALL rulebook criteria (present and missing).
    """
    if basic_result.calc_condition == CalcCondition.NO_CONCLUYENTE:
        return None, CalcCondition.NO_CONCLUYENTE, ViabilityCategory.NO_CONCLUYENTE

    missing_weight = sum(float(all_ahp_weights.get(c, 0.0)) for c in basic_result.missing_criteria)
    missing_structural = bool(set(basic_result.missing_criteria) & _STRUCTURAL_CRITERIA)

    if missing_weight >= _MISSING_WEIGHT_THRESHOLD or missing_structural:
        return (
            critical_result.score,
            CalcCondition.PARCIAL,
            ViabilityCategory.NO_CONCLUYENTE,
        )

    category = (
        critical_result.viability_category
        or basic_result.viability_category
        or ViabilityCategory.NO_VIABLE
    )
    return critical_result.score, basic_result.calc_condition, category


def _temporal_weights(spec: object, memberships: dict[str, float]) -> dict[str, float]:
    raw_weights = {
        str(period["period_key"]): float(period.get("temporal_weight", 0.0))
        for period in getattr(spec, "temporal_periods")
        if str(period.get("period_key")) in memberships
    }
    if set(raw_weights) != set(memberships):
        return {period_key: 1.0 / len(memberships) for period_key in memberships}
    return _normalize(raw_weights)


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0.0:
        return {key: 1.0 / len(weights) for key in weights}
    return {key: value / total for key, value in weights.items()}


def _crop_candidates(command: ExecuteEvaluationCommand, vector: AgroenvVectorData) -> list[str]:
    raw_candidates = command.extraction_result.get("crop_candidates") or command.extraction_result.get("crop_ids")
    if raw_candidates:
        return [str(crop_id) for crop_id in raw_candidates]
    return list(dict.fromkeys(variable.crop_id for variable in vector.variables))


def _success_events(evaluation: Evaluation) -> list[Message]:
    completed_payload = {
        "evaluation_id": str(evaluation.id),
        "results": [
            {
                "crop_id": result.crop_id,
                "score": result.score,
                "calc_condition": result.calc_condition.value,
                "viability_category": result.viability_category.value,
                "rank_position": result.rank_position,
                "missing_criteria": result.missing_criteria,
                "unrecognized_variables": result.unrecognized_variables,
                "limiting_factors": [
                    {
                        "criterion_id": factor.criterion_id,
                        "phase_id": factor.phase_id,
                        "policy": factor.policy.value,
                        "penalty_factor": factor.penalty_factor,
                        "observed_value": factor.observed_value,
                        "optimal_limit": factor.optimal_limit,
                        "membership": factor.membership,
                        "doc_source": factor.doc_source,
                    }
                    for factor in result.limiting_factors
                ],
            }
            for result in evaluation.crop_results
        ],
    }
    gaps_payload = {
        "evaluation_id": str(evaluation.id),
        "gaps": [
            {
                "crop_id": result.crop_id,
                "criterion_id": gap.criterion_id,
                "phase_id": gap.phase_id,
                "most_limiting_period": gap.most_limiting_period,
                "observed_value": gap.observed_value,
                "optimal_limit": gap.optimal_limit,
                "gap_value": gap.gap_value,
            }
            for result in evaluation.crop_results
            for gap in result.gaps
        ],
    }
    return [
        Message.event(EVALUACION_VIABILIDAD_COMPLETADA, completed_payload, correlation_id=evaluation.id),
        Message.event(VECTOR_BRECHAS_GENERADO, gaps_payload, correlation_id=evaluation.id),
    ]
