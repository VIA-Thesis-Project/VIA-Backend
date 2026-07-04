"""Shannon entropy objective weights for viability evaluation.

Entropy weights are computed over the DECISION MATRIX (crops x criteria): for
each criterion, the entropy is measured across the candidate crops' aggregated
memberships. A criterion whose value separates the candidate crops strongly
(high divergence from the uniform distribution) receives more objective weight;
one where all crops score alike receives little.

Why cross-crop and not the temporal series of a single crop
-----------------------------------------------------------
An earlier implementation computed the entropy over the temporal membership
series of one crop. That is mathematically well-defined but agronomically
wrong: a site-static criterion (soil texture, altitude, slope) has an identical
membership in every phase, so its temporal series is flat, its divergence is
zero, and it received ~0 entropy weight EVEN WHEN it discriminated strongly
between the candidate crops. The result systematically transferred weight away
from soil/topography toward temporally-varying climate criteria. The classic
entropy method operates across alternatives; that is what this module does now.
See docs/entropia_cross_cultivo.md for the full numerical before/after.

Per-criterion handling (not global fallback)
--------------------------------------------
When the decision matrix is irregular (a criterion is missing for some crops,
so its column has fewer than ``min_alternatives`` valid entries), ONLY that
criterion is excluded from the entropy vector and falls back to its AHP weight.
The rest of the matrix still receives objective weights. This is deliberately
different from the old all-or-nothing global fallback: the original temporal
bug taught us that collapsing the whole weighting because one series is
degenerate throws away good information. A single sparse column must not silence
the objective weighting of every other criterion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Real

from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError, ensure_non_empty, ensure_unit_interval


# Minimum number of candidate crops (alternatives) required for a criterion's
# entropy to be meaningful. With fewer alternatives there is no dispersion to
# measure, so the criterion falls back to its AHP weight. Configurable via
# MCDA_MIN_ALTERNATIVES_FOR_ENTROPY; this is the domain default.
DEFAULT_MIN_ALTERNATIVES = 3
DEFAULT_ENTROPY_MIN_DIVERGENCE = 1e-9
ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES = "entropy_fallback: insufficient_alternatives"
ENTROPY_FALLBACK_ZERO_DIVERGENCE = "entropy_fallback: zero_divergence"


@dataclass(frozen=True)
class EntropyWeightsResult:
    """Objective entropy weights over qualified criteria, or a fallback reason.

    ``weights`` is a GLOBAL map ``{criterion_id: weight}`` summing to 1 over the
    criteria that qualified (had at least ``min_alternatives`` valid crops).
    ``qualified_criteria`` names those criteria; ``excluded_criteria`` maps each
    skipped criterion to the reason it fell back to AHP.
    """

    weights: dict[str, float] | None
    fallback_reason: str | None = None
    qualified_criteria: frozenset[str] = frozenset()
    excluded_criteria: dict[str, str] = field(default_factory=dict)

    @property
    def entropy_used(self) -> bool:
        """Return whether any objective entropy weights were produced."""

        return self.weights is not None


class EntropyWeightsService:
    """Calculate normalized Shannon entropy weights across candidate crops."""

    def calculate(
        self,
        decision_matrix: dict[str, dict[str, Real]],
        min_alternatives: int = DEFAULT_MIN_ALTERNATIVES,
        min_divergence: float = DEFAULT_ENTROPY_MIN_DIVERGENCE,
    ) -> EntropyWeightsResult:
        """Return entropy weights from a crops x criteria decision matrix.

        ``decision_matrix`` maps ``criterion_id -> {crop_id: aggregated_membership}``.
        Each criterion is weighted by how strongly its aggregated memberships
        diverge across the candidate crops. Criteria with fewer than
        ``min_alternatives`` valid crops are excluded individually and fall back
        to their AHP weight (see module docstring); they never silence the rest.
        """

        if min_alternatives < 2:
            raise EvaluationDomainError("min_alternatives must be at least 2")
        if min_divergence < 0:
            raise EvaluationDomainError("min_divergence must be non-negative")
        if not decision_matrix:
            return EntropyWeightsResult(None, ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES)

        divergences: dict[str, float] = {}
        excluded: dict[str, str] = {}
        for criterion_id, column in decision_matrix.items():
            ensure_non_empty(criterion_id, "criterion_id")
            memberships = self._valid_column_values(column)
            if len(memberships) < min_alternatives:
                excluded[criterion_id] = ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES
                continue
            # Clamp to >= 0: normalized entropy can drift a hair above 1.0 in
            # floating point (a perfectly uniform column), which would otherwise
            # yield a tiny negative divergence and a negative weight.
            divergences[criterion_id] = max(0.0, 1.0 - self._normalized_entropy(memberships))

        if not divergences:
            return EntropyWeightsResult(
                None,
                ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES,
                excluded_criteria=excluded,
            )

        total_divergence = sum(divergences.values())
        if total_divergence <= 0.0 or total_divergence < min_divergence:
            return EntropyWeightsResult(
                None,
                ENTROPY_FALLBACK_ZERO_DIVERGENCE,
                excluded_criteria=excluded,
            )

        weights = {
            criterion_id: divergence / total_divergence
            for criterion_id, divergence in divergences.items()
        }
        return EntropyWeightsResult(
            weights,
            None,
            qualified_criteria=frozenset(weights),
            excluded_criteria=excluded,
        )

    def _valid_column_values(self, column: dict[str, Real]) -> list[float]:
        """Return the valid per-crop memberships of one criterion column."""

        values: list[float] = []
        for crop_id, membership in column.items():
            ensure_non_empty(crop_id, "crop_id")
            ensure_unit_interval(membership, "membership")
            values.append(float(membership))
        return values

    def _normalized_entropy(self, memberships: list[Real]) -> float:
        """Calculate normalized Shannon entropy across alternatives.

        Returns 1.0 (maximum entropy, zero divergence) for a degenerate all-zero
        column: when every crop scores 0 on a criterion it provides no power to
        discriminate between them, so it earns no objective weight.
        """

        total = sum(float(membership) for membership in memberships)
        if total == 0.0 or len(memberships) <= 1:
            return 1.0
        probabilities = [float(membership) / total for membership in memberships]
        entropy = -sum(probability * math.log(probability) for probability in probabilities if probability > 0.0)
        return entropy / math.log(len(memberships))
