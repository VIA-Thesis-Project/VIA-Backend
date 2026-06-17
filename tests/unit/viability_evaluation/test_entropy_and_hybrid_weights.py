"""Unit tests for Lote 8B.2 entropy and hybrid weights."""

from __future__ import annotations

import pytest

from via.bounded_contexts.viability_evaluation.domain.criterion_detail import CriterionDetail
from via.bounded_contexts.viability_evaluation.domain.entropy_weights import (
    ENTROPY_FALLBACK_INVALID_SERIES,
    ENTROPY_FALLBACK_ZERO_DIVERGENCE,
    EntropyWeightsService,
)
from via.bounded_contexts.viability_evaluation.domain.hybrid_weights import HybridWeightsService


def test_sufficient_series_produces_normalized_entropy_weights() -> None:
    result = EntropyWeightsService().calculate(
        {
            "uniform": [0.5, 0.5, 0.5],
            "concentrated": [1.0, 0.0, 0.0],
        }
    )

    assert result.entropy_used is True
    assert result.fallback_reason is None
    assert result.weights is not None
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_uniform_series_receives_less_entropy_weight_than_concentrated_series() -> None:
    result = EntropyWeightsService().calculate(
        {
            "uniform": [0.5, 0.5, 0.5],
            "concentrated": [1.0, 0.0, 0.0],
        }
    )

    assert result.weights is not None
    assert result.weights["uniform"] == pytest.approx(0.0)
    assert result.weights["concentrated"] == pytest.approx(1.0)


def test_empty_series_triggers_invalid_series_fallback() -> None:
    result = EntropyWeightsService().calculate({"rain": []})

    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_INVALID_SERIES


def test_short_series_triggers_invalid_series_fallback() -> None:
    result = EntropyWeightsService().calculate({"rain": [0.1, 0.2]})

    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_INVALID_SERIES


def test_all_zero_series_triggers_invalid_series_fallback() -> None:
    result = EntropyWeightsService().calculate({"rain": [0.0, 0.0, 0.0]})

    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_INVALID_SERIES


def test_zero_total_divergence_triggers_zero_divergence_fallback() -> None:
    result = EntropyWeightsService().calculate(
        {
            "rain": [0.5, 0.5, 0.5],
            "temp": [0.8, 0.8, 0.8],
        }
    )

    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_ZERO_DIVERGENCE


def test_fallback_is_total_when_any_criterion_fails() -> None:
    result = EntropyWeightsService().calculate(
        {
            "rain": [0.5, 0.2, 0.1],
            "temp": [0.3, 0.3],
        }
    )

    assert result.weights is None
    assert result.fallback_reason == ENTROPY_FALLBACK_INVALID_SERIES


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

