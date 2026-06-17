"""Domain layer for the Viability Evaluation bounded context."""

from via.bounded_contexts.viability_evaluation.domain.agronomy_gap import AgronomyGap
from via.bounded_contexts.viability_evaluation.domain.mcda_completion import (
    BasicCropEvaluationService,
    MissingCriteriaService,
    MulticriteriaAggregationService,
    ViabilityClassifierService,
)
from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.crop_result import CropResult
from via.bounded_contexts.viability_evaluation.domain.mcda_policy import (
    CriticalCriterionTrace,
    CriticalPolicyService,
    GapCalculationService,
    PhaseGapTrace,
    RankingService,
)
from via.bounded_contexts.viability_evaluation.domain.entropy_weights import EntropyWeightsService
from via.bounded_contexts.viability_evaluation.domain.evaluation import Evaluation
from via.bounded_contexts.viability_evaluation.domain.hybrid_weights import HybridWeightsService
from via.bounded_contexts.viability_evaluation.domain.limiting_factor import LimitingFactor
from via.bounded_contexts.viability_evaluation.domain.mcda_basic import TrapezoidalMembershipFunction
from via.bounded_contexts.viability_evaluation.domain.value_objects import CalcCondition, CriticalPolicy, ViabilityCategory

__all__ = [
    "AgronomyGap",
    "BasicCropEvaluationService",
    "CalcCondition",
    "CriticalCriterionTrace",
    "CriterionDetail",
    "CriticalPolicy",
    "CriticalPolicyService",
    "CropResult",
    "EntropyWeightsService",
    "Evaluation",
    "HybridWeightsService",
    "LimitingFactor",
    "MissingCriteriaService",
    "GapCalculationService",
    "MulticriteriaAggregationService",
    "PhaseGapTrace",
    "RankingService",
    "TrapezoidalMembershipFunction",
    "ViabilityClassifierService",
    "ViabilityCategory",
]
