"""Hybrid AHP and entropy weights for viability evaluation."""

from __future__ import annotations

from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError, ensure_non_empty, ensure_unit_interval


DEFAULT_MCDA_ALPHA = 0.7


class HybridWeightsService:
    """Combine precalculated AHP weights with optional entropy weights."""

    def combine(
        self,
        w_ahp: dict[str, Real],
        w_entropy: dict[str, Real] | None,
        alpha: float = DEFAULT_MCDA_ALPHA,
    ) -> dict[str, float]:
        """Return normalized hybrid weights."""

        self._validate_weight_map(w_ahp, "w_ahp")
        ensure_unit_interval(alpha, "alpha")
        if w_entropy is not None:
            self._validate_weight_map(w_entropy, "w_entropy")
            if set(w_ahp) != set(w_entropy):
                raise EvaluationDomainError("w_ahp and w_entropy must use the same criteria")
            raw_weights = {
                criterion_id: alpha * float(w_ahp[criterion_id]) + (1.0 - alpha) * float(w_entropy[criterion_id])
                for criterion_id in w_ahp
            }
        else:
            raw_weights = {criterion_id: float(weight) for criterion_id, weight in w_ahp.items()}

        return self._normalize(raw_weights)

    def _validate_weight_map(self, weights: dict[str, Real], field_name: str) -> None:
        """Validate one map of criterion weights."""

        if not weights:
            raise EvaluationDomainError(f"{field_name} must not be empty")
        for criterion_id, weight in weights.items():
            ensure_non_empty(criterion_id, "criterion_id")
            ensure_unit_interval(weight, field_name)
        total = sum(float(weight) for weight in weights.values())
        if total <= 0.0:
            raise EvaluationDomainError(f"{field_name} must have positive total weight")

    def _normalize(self, weights: dict[str, float]) -> dict[str, float]:
        """Normalize weights to sum to one."""

        total = sum(weights.values())
        if total <= 0.0:
            raise EvaluationDomainError("hybrid weights must have positive total weight")
        return {criterion_id: weight / total for criterion_id, weight in weights.items()}
