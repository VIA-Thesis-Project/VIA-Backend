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
        """Return normalized hybrid weights for one crop.

        ``w_entropy`` is the GLOBAL entropy vector (over the criteria that
        qualified across all candidate crops) and may cover only a SUBSET of
        this crop's criteria. Blending happens on the intersection S:

            for j in S:      hybrid_j = [alpha*ahp_j' + (1-alpha)*entropy_j'] * mass(S)
            for j not in S:  hybrid_j = ahp_j            (pure AHP fallback)

        where ahp_j' and entropy_j' are renormalized within S. Restricting the
        blend to S and scaling by the AHP mass of S preserves the total weight
        that this crop's AHP already assigned to the qualified criteria, so
        criteria that did not qualify keep exactly their AHP weight instead of
        being penalised. For a full matrix (S = all criteria, mass = 1) this
        reduces to the classic ``alpha*ahp + (1-alpha)*entropy``.
        """

        self._validate_weight_map(w_ahp, "w_ahp")
        ensure_unit_interval(alpha, "alpha")
        if w_entropy is None:
            return self._normalize({criterion_id: float(weight) for criterion_id, weight in w_ahp.items()})

        self._validate_weight_map(w_entropy, "w_entropy")
        shared = [criterion_id for criterion_id in w_ahp if criterion_id in w_entropy]
        ahp_mass = sum(float(w_ahp[criterion_id]) for criterion_id in shared)
        entropy_mass = sum(float(w_entropy[criterion_id]) for criterion_id in shared)
        if not shared or ahp_mass <= 0.0 or entropy_mass <= 0.0:
            # No qualified criterion for this crop: fall back to pure AHP.
            return self._normalize({criterion_id: float(weight) for criterion_id, weight in w_ahp.items()})

        raw_weights: dict[str, float] = {}
        for criterion_id, weight in w_ahp.items():
            if criterion_id in w_entropy:
                ahp_share = float(weight) / ahp_mass
                entropy_share = float(w_entropy[criterion_id]) / entropy_mass
                blended = alpha * ahp_share + (1.0 - alpha) * entropy_share
                raw_weights[criterion_id] = blended * ahp_mass
            else:
                raw_weights[criterion_id] = float(weight)

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
