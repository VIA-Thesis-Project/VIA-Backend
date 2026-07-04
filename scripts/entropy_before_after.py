"""Reproduce the cross-crop entropy before/after evidence (docs/entropia_cross_cultivo.md).

Computes, for a Fundo Loreto parcel using the real production-seed trapezoids,
the entropy weights and the maize viability score under the OLD (temporal,
within-crop) vs NEW (cross-crop) formulation.

Usage:
    PYTHONPATH=. python scripts/entropy_before_after.py
"""

from __future__ import annotations

import math

from via.bounded_contexts.viability_evaluation.domain.entropy_weights import EntropyWeightsService
from via.bounded_contexts.viability_evaluation.domain.hybrid_weights import HybridWeightsService

CROPS = ["maiz", "mandarina", "maracuya", "palta", "uva"]

# Aggregated memberships per crop (Fundo Loreto: elev 300m, clay 42%, seasonal T),
# computed from the real seed trapezoids in scripts/seed_prod_rulebooks.py.
AGG = {
    "aptitud_termica": {"maiz": 0.847, "mandarina": 0.632, "maracuya": 0.000, "palta": 0.938, "uva": 0.899},
    "aptitud_altitudinal": {"maiz": 1.000, "mandarina": 1.000, "maracuya": 1.000, "palta": 1.000, "uva": 1.000},
    "contenido_arcilla": {"maiz": 0.900, "mandarina": 0.650, "maracuya": 0.150, "palta": 0.400, "uva": 0.150},
}
AHP = {"aptitud_termica": 0.13, "aptitud_altitudinal": 0.12, "contenido_arcilla": 0.07}
ALPHA = 0.7


def _norm_entropy(values: list[float]) -> float:
    total = sum(values)
    if total == 0.0 or len(values) <= 1:
        return 1.0
    probs = [v / total for v in values if v > 0.0]
    return -sum(p * math.log(p) for p in probs) / math.log(len(values))


# OLD formulation: divergence of each criterion's WITHIN-maize temporal series
# (measured with the real seasonal temperature curve). The dynamic climate
# criterion varies across phases so it earns divergence; the site-static soil and
# altitude criteria are flat across phases so their divergence is 0 — the bug.
OLD_TEMPORAL_DIVERGENCE_MAIZE = {
    "aptitud_termica": 0.0118,
    "aptitud_altitudinal": 0.0,
    "contenido_arcilla": 0.0,
}


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def _wgm(memberships: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    w = {k: v / total for k, v in weights.items()}
    return math.exp(sum(w[k] * math.log(memberships[k]) for k in memberships))


def main() -> None:
    ahp_norm = {k: v / sum(AHP.values()) for k, v in AHP.items()}
    hybrid = HybridWeightsService()

    # NEW cross-crop entropy
    matrix = {crit: AGG[crit] for crit in AHP}
    new_result = EntropyWeightsService().calculate(matrix, min_alternatives=3)
    new_hybrid = hybrid.combine(ahp_norm, new_result.weights, alpha=ALPHA)

    # OLD temporal entropy: normalize the within-maize temporal divergences into
    # an entropy vector, then blend — reproducing the biased weighting.
    old_entropy = _normalize(OLD_TEMPORAL_DIVERGENCE_MAIZE)
    old_hybrid = hybrid.combine(ahp_norm, old_entropy, alpha=ALPHA)

    maize_mu = {crit: AGG[crit]["maiz"] for crit in AHP}
    print("NEW cross-crop entropy divergence (weights):", new_result.weights)
    print(f"\n{'criterio':22s}{'AHPn':>8s}{'hybOLD':>9s}{'hybNEW':>9s}")
    for k in AHP:
        print(f"{k:22s}{ahp_norm[k]:8.3f}{old_hybrid[k]:9.3f}{new_hybrid[k]:9.3f}")

    so, sn = _wgm(maize_mu, old_hybrid), _wgm(maize_mu, new_hybrid)
    print(f"\nscore maiz OLD={so:.4f}  NEW={sn:.4f}  delta={sn - so:+.4f} ({(sn - so) / so * 100:+.2f}%)")


if __name__ == "__main__":
    main()
