"""Unit tests for cross-crop entropy and hybrid weights.

Entropy is computed over the decision matrix (crops x criteria): each criterion
is weighted by how strongly its aggregated memberships diverge ACROSS the
candidate crops. This replaced an earlier formulation that measured the entropy
of a single crop's temporal series, which zeroed the weight of site-static
criteria (soil, altitude) even when they discriminated strongly between crops.
See docs/entropia_cross_cultivo.md.
"""

from __future__ import annotations

import pytest

from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.entropy_weights import (
    ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES,
    ENTROPY_FALLBACK_ZERO_DIVERGENCE,
    EntropyWeightsService,
)
from via.bounded_contexts.viability_evaluation.domain.hybrid_weights import HybridWeightsService
from via.bounded_contexts.viability_evaluation.domain.value_objects import EvaluationDomainError


# ── decision-matrix helpers ────────────────────────────────────────────────────


def _matrix(**criteria: dict[str, float]) -> dict[str, dict[str, float]]:
    """Build a decision matrix {criterion: {crop: membership}}."""

    return dict(criteria)


# ── basic entropy behavior ─────────────────────────────────────────────────────


def test_sufficient_matrix_produces_normalized_entropy_weights() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(
            uniform={"c1": 0.5, "c2": 0.5, "c3": 0.5},
            concentrated={"c1": 1.0, "c2": 0.0, "c3": 0.0},
        )
    )

    assert result.entropy_used is True
    assert result.fallback_reason is None
    assert result.weights is not None
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_criterion_that_does_not_discriminate_receives_less_weight() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(
            uniform={"c1": 0.5, "c2": 0.5, "c3": 0.5},
            concentrated={"c1": 1.0, "c2": 0.0, "c3": 0.0},
        )
    )

    assert result.weights is not None
    assert result.weights["uniform"] == pytest.approx(0.0)
    assert result.weights["concentrated"] == pytest.approx(1.0)


def test_zero_total_divergence_triggers_zero_divergence_fallback() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(
            c_a={"c1": 0.5, "c2": 0.5, "c3": 0.5},
            c_b={"c1": 0.8, "c2": 0.8, "c3": 0.8},
        )
    )

    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_ZERO_DIVERGENCE


def test_min_alternatives_below_two_is_rejected() -> None:
    with pytest.raises(EvaluationDomainError, match="min_alternatives"):
        EntropyWeightsService().calculate(_matrix(c={"a": 0.5, "b": 0.5}), min_alternatives=1)


# ── NEW 1: static-but-discriminating criterion receives entropy weight ──────────


def test_static_criterion_that_discriminates_between_crops_receives_weight() -> None:
    """Regression guard for the temporal-entropy bug.

    A site-static soil criterion whose value differs across crops (clay tolerated
    by maize, not by passionfruit) must receive a positive entropy weight — the
    exact case the old temporal formulation zeroed.
    """
    result = EntropyWeightsService().calculate(
        _matrix(
            contenido_arcilla={
                "maiz": 0.90,
                "mandarina": 0.65,
                "maracuya": 0.15,
                "palta": 0.40,
                "uva": 0.15,
            },
            aptitud_termica={
                "maiz": 0.85,
                "mandarina": 0.63,
                "maracuya": 0.00,
                "palta": 0.94,
                "uva": 0.90,
            },
        )
    )

    assert result.weights is not None
    assert result.weights["contenido_arcilla"] > 0.3
    # clay discriminates about as much as climate at this site
    assert result.weights["contenido_arcilla"] == pytest.approx(result.weights["aptitud_termica"], abs=0.1)


# ── NEW 2: non-discriminating criterion earns zero, regardless of level ─────────


def test_criterion_identical_across_crops_earns_zero_divergence() -> None:
    """Altitude at a low site: all crops score 1.0 -> no discrimination -> weight 0.

    High-but-uniform must behave the same as low-but-uniform: it is the lack of
    variation across crops, not the level, that removes discriminating power.
    """
    high = EntropyWeightsService().calculate(
        _matrix(
            altitud={"a": 1.0, "b": 1.0, "c": 1.0},
            arcilla={"a": 0.9, "b": 0.5, "c": 0.2},
        )
    )
    low = EntropyWeightsService().calculate(
        _matrix(
            altitud={"a": 0.2, "b": 0.2, "c": 0.2},
            arcilla={"a": 0.9, "b": 0.5, "c": 0.2},
        )
    )

    assert high.weights is not None and low.weights is not None
    assert high.weights["altitud"] == pytest.approx(0.0)
    assert low.weights["altitud"] == pytest.approx(0.0)
    assert high.weights["arcilla"] == pytest.approx(low.weights["arcilla"])
    # A uniform column must never produce a negative weight from float drift in 1-H,
    # otherwise the hybrid combiner (which validates [0,1]) would reject the vector.
    assert high.weights["altitud"] >= 0.0
    HybridWeightsService().combine({"altitud": 0.5, "arcilla": 0.5}, high.weights)


# ── NEW 3: phase reordering no longer changes entropy weights ───────────────────


def test_entropy_is_invariant_to_temporal_structure() -> None:
    """Cross-crop entropy depends only on aggregated memberships, not on how many
    phases produced them — the property the temporal formulation lacked."""
    result = EntropyWeightsService().calculate(
        _matrix(
            c1={"maiz": 0.8, "palta": 0.4, "uva": 0.2},
            c2={"maiz": 0.5, "palta": 0.5, "uva": 0.9},
        )
    )
    same = EntropyWeightsService().calculate(
        _matrix(
            c1={"uva": 0.2, "maiz": 0.8, "palta": 0.4},
            c2={"palta": 0.5, "uva": 0.9, "maiz": 0.5},
        )
    )

    assert result.weights is not None and same.weights is not None
    for criterion_id in result.weights:
        assert result.weights[criterion_id] == pytest.approx(same.weights[criterion_id])


# ── NEW 4: single crop -> insufficient alternatives -> pure AHP ─────────────────


def test_single_crop_matrix_falls_back_to_pure_ahp() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(c1={"maiz": 0.8}, c2={"maiz": 0.4})
    )

    assert result.entropy_used is False
    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES

    hybrid = HybridWeightsService().combine({"c1": 0.6, "c2": 0.4}, result.weights)
    assert hybrid == {"c1": pytest.approx(0.6), "c2": pytest.approx(0.4)}


# ── NEW 5: two crops with threshold 3 -> fallback ───────────────────────────────


def test_two_crops_below_default_threshold_fall_back() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(c1={"maiz": 0.8, "palta": 0.2}, c2={"maiz": 0.3, "palta": 0.9}),
        min_alternatives=3,
    )

    assert result.entropy_used is False
    assert result.fallback_reason == ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES


def test_two_crops_qualify_when_threshold_lowered_to_two() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(c1={"maiz": 0.8, "palta": 0.2}, c2={"maiz": 0.3, "palta": 0.9}),
        min_alternatives=2,
    )

    assert result.entropy_used is True
    assert result.weights is not None


# ── NEW 6: irregular matrix -> per-criterion exclusion, not global fallback ─────


def test_criterion_with_too_few_crops_is_excluded_but_others_survive() -> None:
    """A sparse column must not silence the objective weighting of the rest.

    contenido_arena appears for only 2 crops (< threshold 3) so it is excluded
    and falls back to AHP; the other two criteria still receive entropy weights.
    This is the deliberate difference from the old all-or-nothing fallback.
    """
    result = EntropyWeightsService().calculate(
        _matrix(
            aptitud_termica={"maiz": 0.9, "palta": 0.5, "uva": 0.2},
            contenido_arcilla={"maiz": 0.8, "palta": 0.4, "uva": 0.6},
            contenido_arena={"maiz": 0.7, "palta": 0.3},
        ),
        min_alternatives=3,
    )

    assert result.weights is not None
    assert "contenido_arena" not in result.weights
    assert result.excluded_criteria["contenido_arena"] == ENTROPY_FALLBACK_INSUFFICIENT_ALTERNATIVES
    assert set(result.qualified_criteria) == {"aptitud_termica", "contenido_arcilla"}
    assert sum(result.weights.values()) == pytest.approx(1.0)


# ── NEW 7: entropy vector is a non-negative distribution ────────────────────────


def test_entropy_weights_are_non_negative_and_sum_to_one() -> None:
    result = EntropyWeightsService().calculate(
        _matrix(
            c1={"a": 0.9, "b": 0.1, "c": 0.5, "d": 0.3},
            c2={"a": 0.2, "b": 0.8, "c": 0.4, "d": 0.6},
            c3={"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.4},
        )
    )

    assert result.weights is not None
    assert all(weight >= 0.0 for weight in result.weights.values())
    assert sum(result.weights.values()) == pytest.approx(1.0)


# ── NEW 8: hybrid restricts and mass-preserves the entropy subset ───────────────


def test_hybrid_gives_pure_ahp_to_criteria_outside_the_entropy_subset() -> None:
    """A crop criterion absent from the global entropy vector keeps its AHP share.

    Entropy qualified only c1 and c2; c3 (this crop's third criterion) must be
    governed purely by AHP, and the qualified block must preserve its AHP mass.
    """
    w_ahp = {"c1": 0.5, "c2": 0.3, "c3": 0.2}
    w_entropy = {"c1": 0.75, "c2": 0.25}  # global vector, subset of the crop's criteria

    result = HybridWeightsService().combine(w_ahp, w_entropy, alpha=0.7)

    assert sum(result.values()) == pytest.approx(1.0)
    # c3 keeps exactly its AHP weight (not blended, not penalised)
    assert result["c3"] == pytest.approx(0.2)
    # the qualified block {c1, c2} keeps its combined AHP mass of 0.8
    assert result["c1"] + result["c2"] == pytest.approx(0.8)
    # within the block, the blend shifted mass toward c1 (higher entropy share)
    assert result["c1"] > w_ahp["c1"]


# ── existing hybrid contract (unchanged for the full-matrix case) ───────────────


def test_hybrid_combination_uses_alpha_0_7_and_normalizes() -> None:
    result = HybridWeightsService().combine(
        w_ahp={"rain": 0.6, "temp": 0.4},
        w_entropy={"rain": 0.25, "temp": 0.75},
        alpha=0.7,
    )

    assert result["rain"] == pytest.approx(0.7 * 0.6 + 0.3 * 0.25)
    assert result["temp"] == pytest.approx(0.7 * 0.4 + 0.3 * 0.75)
    assert sum(result.values()) == pytest.approx(1.0)


def test_hybrid_without_entropy_falls_back_to_ahp() -> None:
    result = HybridWeightsService().combine({"rain": 0.6, "temp": 0.4}, None)

    assert result == {"rain": pytest.approx(0.6), "temp": pytest.approx(0.4)}


def test_hybrid_weights_always_sum_to_one_after_normalization() -> None:
    result = HybridWeightsService().combine(
        w_ahp={"rain": 0.3, "temp": 0.3},
        w_entropy={"rain": 0.2, "temp": 0.8},
        alpha=0.7,
    )

    assert sum(result.values()) == pytest.approx(1.0)


def test_positive_ahp_criterion_does_not_become_zero_when_alpha_is_between_zero_and_one() -> None:
    result = HybridWeightsService().combine(
        w_ahp={"rain": 0.01, "temp": 0.99},
        w_entropy={"rain": 0.0, "temp": 1.0},
        alpha=0.7,
    )

    assert result["rain"] > 0.0


def test_criterion_detail_can_be_updated_with_entropy_weights() -> None:
    detail = CriterionDetail(
        criterion_id="rain",
        memberships_by_period={"phase:week_1": 0.5},
        aggregated_by_phase={"phase": 0.5},
        aggregated_membership=0.5,
        w_ahp=0.6,
    )

    updated = detail.with_entropy_weights(
        w_entropy=0.25,
        w_hybrid=0.495,
        entropy_used=True,
        entropy_fallback_reason=None,
    )

    assert updated.w_entropy == 0.25
    assert updated.w_hybrid == 0.495
    assert updated.entropy_used is True
    assert updated.entropy_fallback_reason is None
    assert detail.w_entropy is None
