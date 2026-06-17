"""Shannon entropy objective weights for viability evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError, ensure_non_empty, ensure_unit_interval


DEFAULT_MIN_SERIES_LENGTH = 3
DEFAULT_ENTROPY_MIN_DIVERGENCE = 1e-9
ENTROPY_FALLBACK_INVALID_SERIES = "entropy_fallback: incomplete_or_invalid_series"
ENTROPY_FALLBACK_ZERO_DIVERGENCE = "entropy_fallback: zero_divergence"


@dataclass(frozen=True)
class EntropyWeightsResult:
    """Objective entropy weights or the total-fallback reason."""

    weights: dict[str, float] | None
    fallback_reason: str | None = None

    @property
    def entropy_used(self) -> bool:
        """Return whether objective entropy weights were produced."""

        return self.weights is not None


class EntropyWeightsService:
    """Calculate normalized Shannon entropy weights for all criteria."""

    def calculate(
        self,
        criterion_memberships: dict[str, list[Real]],
        min_series_length: int = DEFAULT_MIN_SERIES_LENGTH,
        min_divergence: float = DEFAULT_ENTROPY_MIN_DIVERGENCE,
    ) -> EntropyWeightsResult:
        """Return entropy weights or a total fallback when any series is invalid."""

        if min_series_length < 2:
            raise EvaluationDomainError("min_series_length must be at least 2")
        if min_divergence < 0:
            raise EvaluationDomainError("min_divergence must be non-negative")
        if not criterion_memberships:
            return EntropyWeightsResult(None, ENTROPY_FALLBACK_INVALID_SERIES)

        if self._has_invalid_series(criterion_memberships, min_series_length):
            return EntropyWeightsResult(None, ENTROPY_FALLBACK_INVALID_SERIES)

        divergences = {
            criterion_id: 1.0 - self._normalized_entropy(memberships)
            for criterion_id, memberships in criterion_memberships.items()
        }
        total_divergence = sum(divergences.values())
        if total_divergence == 0.0 or total_divergence < min_divergence:
            return EntropyWeightsResult(None, ENTROPY_FALLBACK_ZERO_DIVERGENCE)

        return EntropyWeightsResult(
            {criterion_id: divergence / total_divergence for criterion_id, divergence in divergences.items()},
            None,
        )

    def _has_invalid_series(self, criterion_memberships: dict[str, list[Real]], min_series_length: int) -> bool:
        """Return whether any criterion series forces total fallback."""

        for criterion_id, memberships in criterion_memberships.items():
            ensure_non_empty(criterion_id, "criterion_id")
            if len(memberships) < min_series_length:
                return True
            if all(float(membership) == 0.0 for membership in memberships):
                return True
            for membership in memberships:
                ensure_unit_interval(membership, "membership")
        return False

    def _normalized_entropy(self, memberships: list[Real]) -> float:
        """Calculate normalized Shannon entropy using natural logarithms."""

        total = sum(float(membership) for membership in memberships)
        probabilities = [float(membership) / total for membership in memberships]
        entropy = -sum(probability * math.log(probability) for probability in probabilities if probability > 0.0)
        return entropy / math.log(len(memberships))
