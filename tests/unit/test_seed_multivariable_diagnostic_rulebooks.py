"""Tests for seed_multivariable_diagnostic_rulebooks.py — VIABILIDAD POTENCIAL DE PARCELA.

Valida:
- 5 criterios con los nombres correctos (viabilidad potencial, no estado actual)
- Pesos AHP: altitudinal=0.40, topografica=0.30, auxiliares=0.10 c/u
- Trapecios auxiliares amplios (NDVI/SAVI/NDMI) — no colapsan en barbecho
- Trapecios per-cultivo bibliográficos para elevacion/pendiente
- Políticas críticas SOLO en criterios estructurales (altitudinal, topografica)
- NDVI/SAVI/NDMI sin políticas críticas (son variables auxiliares)
- Conversión % → grados para pendiente
- 4 fases fenológicas y pesos de fase
- Metadato VIABILIDAD POTENCIAL
"""
from __future__ import annotations

import math
from uuid import UUID

import pytest

from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import CriticalPolicy


# ─── In-memory repository fixture ─────────────────────────────────────────────

class InMemoryRulebookRepository:
    def __init__(self) -> None:
        self._store: dict[UUID, Rulebook] = {}

    def next_version_for_crop(self, crop_id: str) -> int:
        versions = [rb.version for rb in self._store.values() if rb.crop_id == crop_id]
        return max(versions, default=0) + 1

    def add(self, rulebook: Rulebook) -> None:
        self._store[rulebook.id] = rulebook

    def get_by_id(self, rulebook_id: UUID) -> Rulebook | None:
        return self._store.get(rulebook_id)

    def get_active_by_crop(self, crop_id: str) -> Rulebook | None:
        for rb in self._store.values():
            if rb.crop_id == crop_id and rb.status.value == "ACTIVE":
                return rb
        return None

    def list_all(self) -> list[Rulebook]:
        return list(self._store.values())

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        pass  # no-op for tests — each crop only gets one rulebook

    def save(self, rulebook: Rulebook) -> None:
        self._store[rulebook.id] = rulebook


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def repo() -> InMemoryRulebookRepository:
    return InMemoryRulebookRepository()


@pytest.fixture()
def seeded(repo: InMemoryRulebookRepository):
    from scripts.seed_multivariable_diagnostic_rulebooks import create_and_publish_multivariable_rulebooks
    return create_and_publish_multivariable_rulebooks(repo)


@pytest.fixture()
def all_rulebooks(repo: InMemoryRulebookRepository, seeded):
    return list(repo._store.values())


@pytest.fixture()
def rulebook_map(repo: InMemoryRulebookRepository, seeded) -> dict[str, Rulebook]:
    return {rb.crop_id: rb for rb in repo._store.values()}


# ─── Helper ───────────────────────────────────────────────────────────────────

def _deg(pct: float) -> float:
    return round(math.atan(pct / 100.0) * (180.0 / math.pi), 2)


def _get_criterion(rulebook: Rulebook, name: str):
    for c in rulebook.criteria:
        if c.name == name:
            return c
    raise KeyError(f"Criterion {name!r} not found in {rulebook.crop_id}")


def _get_requirements(rulebook: Rulebook, criterion_name: str):
    crit = _get_criterion(rulebook, criterion_name)
    return [r for r in rulebook.phase_requirements if r.criterion_id == crit.id]


# ─── 1. Structure ─────────────────────────────────────────────────────────────

def test_five_crops_seeded(seeded):
    assert len(seeded) == 5


def test_five_criteria_per_crop(all_rulebooks):
    for rb in all_rulebooks:
        assert len(rb.criteria) == 5, f"{rb.crop_id} has {len(rb.criteria)} criteria"


def test_four_phases_per_crop(all_rulebooks):
    for rb in all_rulebooks:
        assert len(rb.phases) == 4, f"{rb.crop_id} has {len(rb.phases)} phases"


def test_twenty_requirements_per_crop(all_rulebooks):
    for rb in all_rulebooks:
        assert len(rb.phase_requirements) == 20, f"{rb.crop_id} has {len(rb.phase_requirements)} reqs"


def test_all_rulebooks_published(all_rulebooks):
    for rb in all_rulebooks:
        assert rb.status.value == "ACTIVE", f"{rb.crop_id} not ACTIVE"


# ─── 2. Nombres de criterios correctos (viabilidad potencial) ─────────────────

EXPECTED_CRITERIA = {
    "cobertura_actual",
    "cobertura_suelo_ajustada",
    "humedad_vegetacion_auxiliar",
    "aptitud_topografica",
    "aptitud_altitudinal",
}

FORBIDDEN_CRITERIA = {
    "vegetacion_vigor",
    "cobertura_vegetal_ajustada",
    "estres_hidrico",
}


def test_criteria_names_viabilidad_potencial(all_rulebooks):
    for rb in all_rulebooks:
        names = {c.name for c in rb.criteria}
        assert names == EXPECTED_CRITERIA, f"{rb.crop_id}: {names}"


def test_no_old_criteria_names(all_rulebooks):
    for rb in all_rulebooks:
        names = {c.name for c in rb.criteria}
        overlap = names & FORBIDDEN_CRITERIA
        assert not overlap, f"{rb.crop_id} still has old names: {overlap}"


# ─── 3. Pesos AHP ─────────────────────────────────────────────────────────────

EXPECTED_WEIGHTS = {
    "aptitud_altitudinal":         0.40,
    "aptitud_topografica":         0.30,
    "cobertura_actual":            0.10,
    "cobertura_suelo_ajustada":    0.10,
    "humedad_vegetacion_auxiliar": 0.10,
}


def test_ahp_weights_correct(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            expected = EXPECTED_WEIGHTS[crit.name]
            assert abs(crit.ahp_weight - expected) < 1e-9, (
                f"{rb.crop_id}.{crit.name}: weight={crit.ahp_weight}, expected={expected}"
            )


def test_ahp_weights_sum_to_one(all_rulebooks):
    for rb in all_rulebooks:
        total = sum(c.ahp_weight for c in rb.criteria)
        assert abs(total - 1.0) < 1e-9, f"{rb.crop_id}: sum={total}"


def test_structural_criteria_outweigh_auxiliaries(all_rulebooks):
    for rb in all_rulebooks:
        alt = _get_criterion(rb, "aptitud_altitudinal").ahp_weight
        top = _get_criterion(rb, "aptitud_topografica").ahp_weight
        ndvi = _get_criterion(rb, "cobertura_actual").ahp_weight
        savi = _get_criterion(rb, "cobertura_suelo_ajustada").ahp_weight
        ndmi = _get_criterion(rb, "humedad_vegetacion_auxiliar").ahp_weight
        assert alt > ndvi and alt > savi and alt > ndmi, rb.crop_id
        assert top > ndvi and top > savi and top > ndmi, rb.crop_id


# ─── 4. Trapecios auxiliares amplios ──────────────────────────────────────────
# NDVI=0.099 (barbecho/suelo preparado) debe dar μ=1.0 (dentro del plateau)

_AUX_NDVI_EXPECTED = (-0.10,  0.05, 0.90, 1.00)
_AUX_SAVI_EXPECTED = (-0.10,  0.05, 0.90, 1.00)
_AUX_NDMI_EXPECTED = (-0.50, -0.10, 0.60, 0.80)


def _check_trap_all_phases(rb: Rulebook, criterion_name: str, expected: tuple) -> None:
    reqs = _get_requirements(rb, criterion_name)
    assert len(reqs) == 4, f"{rb.crop_id}.{criterion_name}: {len(reqs)} reqs"
    for req in reqs:
        mf = req.membership_fn
        trap = (mf.a, mf.b, mf.c, mf.d)
        assert trap == expected, (
            f"{rb.crop_id}.{criterion_name} phase {req.phase_id}: {trap} != {expected}"
        )


def test_ndvi_aux_trap_all_crops(all_rulebooks):
    for rb in all_rulebooks:
        _check_trap_all_phases(rb, "cobertura_actual", _AUX_NDVI_EXPECTED)


def test_savi_aux_trap_all_crops(all_rulebooks):
    for rb in all_rulebooks:
        _check_trap_all_phases(rb, "cobertura_suelo_ajustada", _AUX_SAVI_EXPECTED)


def test_ndmi_aux_trap_all_crops(all_rulebooks):
    for rb in all_rulebooks:
        _check_trap_all_phases(rb, "humedad_vegetacion_auxiliar", _AUX_NDMI_EXPECTED)


def test_aux_traps_uniform_across_crops(all_rulebooks):
    """Los auxiliares deben ser iguales para todos los cultivos."""
    def get_trap(rb: Rulebook, name: str):
        reqs = _get_requirements(rb, name)
        mf = reqs[0].membership_fn
        return (mf.a, mf.b, mf.c, mf.d)

    for criterion_name in ("cobertura_actual", "cobertura_suelo_ajustada", "humedad_vegetacion_auxiliar"):
        traps = {rb.crop_id: get_trap(rb, criterion_name) for rb in all_rulebooks}
        unique = set(traps.values())
        assert len(unique) == 1, f"{criterion_name} not uniform: {traps}"


def test_ndvi_fallow_land_in_plateau():
    """NDVI=0.099 (barbecho) debe estar en el plateau del trapecio auxiliar (μ=1.0)."""
    ndvi_value = 0.099
    a, b, c, d = _AUX_NDVI_EXPECTED
    assert b <= ndvi_value <= c, (
        f"NDVI={ndvi_value} is NOT in plateau [{b}, {c}] — "
        f"this would collapse scores for fallow land"
    )


def test_savi_fallow_land_in_plateau():
    """SAVI=0.148 (barbecho) debe estar en el plateau del trapecio auxiliar (μ=1.0)."""
    savi_value = 0.148
    a, b, c, d = _AUX_SAVI_EXPECTED
    assert b <= savi_value <= c, (
        f"SAVI={savi_value} is NOT in plateau [{b}, {c}]"
    )


def test_ndmi_demo_parcel_in_plateau():
    """NDMI=0.128 (parcela demo) debe estar en el plateau del trapecio auxiliar (μ=1.0)."""
    ndmi_value = 0.128
    a, b, c, d = _AUX_NDMI_EXPECTED
    assert b <= ndmi_value <= c, (
        f"NDMI={ndmi_value} is NOT in plateau [{b}, {c}]"
    )


# ─── 5. Políticas críticas ────────────────────────────────────────────────────
# Solo criterios estructurales tienen políticas críticas.
# NDVI / SAVI / NDMI NO deben tener políticas críticas.

AUXILIARY_CRITERIA = {
    "cobertura_actual",
    "cobertura_suelo_ajustada",
    "humedad_vegetacion_auxiliar",
}


def test_auxiliaries_have_no_critical_policy(all_rulebooks):
    for rb in all_rulebooks:
        for crit_name in AUXILIARY_CRITERIA:
            crit = _get_criterion(rb, crit_name)
            assert not crit.is_critical, (
                f"{rb.crop_id}.{crit_name} must NOT be critical (auxiliary variable)"
            )


def test_papa_altitudinal_no_viable(rulebook_map):
    rb = rulebook_map["demo_papa"]
    crit = _get_criterion(rb, "aptitud_altitudinal")
    assert crit.is_critical
    assert crit.critical_policy == CriticalPolicy.NO_VIABLE


def test_quinua_altitudinal_penalize_060(rulebook_map):
    rb = rulebook_map["demo_quinua"]
    crit = _get_criterion(rb, "aptitud_altitudinal")
    assert crit.is_critical
    assert crit.critical_policy == CriticalPolicy.PENALIZE
    assert abs(crit.penalty_factor - 0.60) < 1e-9


def test_palta_topografica_penalize_080(rulebook_map):
    rb = rulebook_map["demo_palta"]
    crit = _get_criterion(rb, "aptitud_topografica")
    assert crit.is_critical
    assert crit.critical_policy == CriticalPolicy.PENALIZE
    assert abs(crit.penalty_factor - 0.80) < 1e-9


def test_arandano_topografica_penalize_075(rulebook_map):
    rb = rulebook_map["demo_arandano"]
    crit = _get_criterion(rb, "aptitud_topografica")
    assert crit.is_critical
    assert crit.critical_policy == CriticalPolicy.PENALIZE
    assert abs(crit.penalty_factor - 0.75) < 1e-9


def test_maiz_no_critical_criteria(rulebook_map):
    rb = rulebook_map["demo_maiz"]
    critical = [c for c in rb.criteria if c.is_critical]
    assert critical == [], f"demo_maiz should have no critical criteria: {[c.name for c in critical]}"


def test_palta_altitudinal_not_critical(rulebook_map):
    """Palta no tiene política crítica en altitudinal (portainjertos permiten cota 0)."""
    rb = rulebook_map["demo_palta"]
    crit = _get_criterion(rb, "aptitud_altitudinal")
    assert not crit.is_critical


def test_arandano_altitudinal_not_critical(rulebook_map):
    rb = rulebook_map["demo_arandano"]
    crit = _get_criterion(rb, "aptitud_altitudinal")
    assert not crit.is_critical


def test_papa_topografica_not_critical(rulebook_map):
    rb = rulebook_map["demo_papa"]
    crit = _get_criterion(rb, "aptitud_topografica")
    assert not crit.is_critical


# ─── 6. Conversión pendiente % → grados ───────────────────────────────────────

def test_deg_conversion_12pct():
    assert abs(_deg(12) - 6.84) < 0.01


def test_deg_conversion_30pct():
    assert abs(_deg(30) - 16.70) < 0.01


def test_deg_conversion_8pct():
    assert abs(_deg(8) - 4.57) < 0.01


def test_deg_conversion_25pct():
    assert abs(_deg(25) - 14.04) < 0.01


def test_deg_conversion_20pct():
    assert abs(_deg(20) - 11.31) < 0.01


def test_deg_conversion_5pct():
    assert abs(_deg(5) - 2.86) < 0.01


def test_deg_conversion_1pct():
    assert abs(_deg(1) - 0.57) < 0.01


# ─── 7. Trapecios estructurales per-cultivo ───────────────────────────────────


def _first_trap(rb: Rulebook, criterion_name: str) -> tuple:
    reqs = _get_requirements(rb, criterion_name)
    mf = reqs[0].membership_fn
    return (mf.a, mf.b, mf.c, mf.d)


# Papa — elevación
def test_papa_elevation_starts_at_1500m(rulebook_map):
    trap = _first_trap(rulebook_map["demo_papa"], "aptitud_altitudinal")
    assert trap[0] == 1500


def test_papa_elevation_plateau_2800_3800(rulebook_map):
    trap = _first_trap(rulebook_map["demo_papa"], "aptitud_altitudinal")
    assert trap[1] == 2800
    assert trap[2] == 3800


def test_papa_elevation_max_4200m(rulebook_map):
    trap = _first_trap(rulebook_map["demo_papa"], "aptitud_altitudinal")
    assert trap[3] == 4200


# Maíz — elevación
def test_maiz_elevation_starts_at_0m(rulebook_map):
    trap = _first_trap(rulebook_map["demo_maiz"], "aptitud_altitudinal")
    assert trap[0] == 0


def test_maiz_elevation_plateau_0_to_1800(rulebook_map):
    trap = _first_trap(rulebook_map["demo_maiz"], "aptitud_altitudinal")
    assert trap[1] == 0
    assert trap[2] == 1800


def test_maiz_elevation_max_2800m(rulebook_map):
    trap = _first_trap(rulebook_map["demo_maiz"], "aptitud_altitudinal")
    assert trap[3] == 2800


# Quinua — elevación
def test_quinua_elevation_plateau_starts_2800(rulebook_map):
    trap = _first_trap(rulebook_map["demo_quinua"], "aptitud_altitudinal")
    assert trap[1] == 2800


def test_quinua_elevation_max_4100m(rulebook_map):
    trap = _first_trap(rulebook_map["demo_quinua"], "aptitud_altitudinal")
    assert trap[3] == 4100


# Palta — elevación y pendiente
def test_palta_elevation_plateau_800_to_2200(rulebook_map):
    trap = _first_trap(rulebook_map["demo_palta"], "aptitud_altitudinal")
    assert trap[1] == 800
    assert trap[2] == 2200


def test_palta_slope_starts_at_1pct_degrees(rulebook_map):
    trap = _first_trap(rulebook_map["demo_palta"], "aptitud_topografica")
    assert abs(trap[0] - _deg(1)) < 0.01


def test_palta_slope_plateau_from_3pct(rulebook_map):
    trap = _first_trap(rulebook_map["demo_palta"], "aptitud_topografica")
    assert abs(trap[1] - _deg(3)) < 0.01


# Arándano — pendiente
def test_arandano_slope_plateau_0_to_5pct(rulebook_map):
    trap = _first_trap(rulebook_map["demo_arandano"], "aptitud_topografica")
    assert trap[0] == 0.0
    assert trap[1] == 0.0
    assert abs(trap[2] - _deg(5)) < 0.01


def test_arandano_slope_max_12pct_degrees(rulebook_map):
    trap = _first_trap(rulebook_map["demo_arandano"], "aptitud_topografica")
    assert abs(trap[3] - _deg(12)) < 0.01


# Elevaciones per-cultivo son distintas entre sí
def test_elevation_traps_differ_between_crops(rulebook_map):
    traps = {
        crop_id: _first_trap(rulebook_map[crop_id], "aptitud_altitudinal")
        for crop_id in rulebook_map
    }
    unique_traps = set(traps.values())
    assert len(unique_traps) >= 3, f"Elevation traps too uniform: {traps}"


# ─── 8. Fases fenológicas ─────────────────────────────────────────────────────

EXPECTED_PHASES = {
    "establecimiento": 30,
    "desarrollo":      45,
    "floracion":       35,
    "maduracion":      40,
}


def test_phase_names_and_durations(all_rulebooks):
    for rb in all_rulebooks:
        phase_dict = {p.name: p.duration_days for p in rb.phases}
        assert phase_dict == EXPECTED_PHASES, f"{rb.crop_id}: {phase_dict}"


def test_phases_have_sequence_order(all_rulebooks):
    for rb in all_rulebooks:
        orders = sorted(p.sequence_order for p in rb.phases)
        assert orders == list(range(1, 5)), f"{rb.crop_id}: {orders}"


def test_phase_weights_sum_to_one_per_criterion(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            reqs = [r for r in rb.phase_requirements if r.criterion_id == crit.id]
            total = sum(r.phase_weight for r in reqs)
            assert abs(total - 1.0) < 1e-9, (
                f"{rb.crop_id}.{crit.name}: phase_weight sum={total}"
            )


# ─── 9. Extraction bindings ────────────────────────────────────────────────────

EXPECTED_BINDINGS = {
    "cobertura_actual":            ("ndvi",             "COPERNICUS/S2_SR_HARMONIZED"),
    "cobertura_suelo_ajustada":    ("savi",             "COPERNICUS/S2_SR_HARMONIZED"),
    "humedad_vegetacion_auxiliar": ("ndmi",             "COPERNICUS/S2_SR_HARMONIZED"),
    "aptitud_topografica":         ("pendiente_grados", "USGS/SRTMGL1_003"),
    "aptitud_altitudinal":         ("elevacion_m",      "USGS/SRTMGL1_003"),
}


def test_extraction_bindings_correct(all_rulebooks):
    for rb in all_rulebooks:
        for crit_name, (var_name, dataset_key) in EXPECTED_BINDINGS.items():
            reqs = _get_requirements(rb, crit_name)
            for req in reqs:
                binding = req.extraction_binding
                assert binding.variable_name == var_name, (
                    f"{rb.crop_id}.{crit_name}: variable_name={binding.variable_name}"
                )
                assert binding.dataset_key == dataset_key, (
                    f"{rb.crop_id}.{crit_name}: dataset_key={binding.dataset_key}"
                )


# ─── 10. Metadato viabilidad potencial ────────────────────────────────────────

def test_doc_source_mentions_viabilidad_potencial(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            src = crit.doc_source.upper()
            assert "VIABILIDAD POTENCIAL" in src, (
                f"{rb.crop_id}.{crit.name} doc_source missing 'VIABILIDAD POTENCIAL'"
            )


def test_doc_source_mentions_auxiliar(all_rulebooks):
    for rb in all_rulebooks:
        for crit_name in AUXILIARY_CRITERIA:
            crit = _get_criterion(rb, crit_name)
            notes = crit.technical_notes.lower()
            assert "auxiliar" in notes, (
                f"{rb.crop_id}.{crit_name} technical_notes should mention 'auxiliar'"
            )


def test_doc_source_mentions_fixture(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            assert "FIXTURE" in crit.doc_source.upper(), (
                f"{rb.crop_id}.{crit.name} should mention FIXTURE"
            )


# ─── 11. Stable UUIDs ─────────────────────────────────────────────────────────

def test_stable_uuids_deterministic():
    """Criteria, phase, and requirement IDs are uuid5 (stable); rulebook IDs are uuid4 (random)."""
    from scripts.seed_multivariable_diagnostic_rulebooks import create_and_publish_multivariable_rulebooks

    repo1 = InMemoryRulebookRepository()
    repo2 = InMemoryRulebookRepository()
    create_and_publish_multivariable_rulebooks(repo1)
    create_and_publish_multivariable_rulebooks(repo2)

    for crop_id in ("demo_maiz", "demo_papa", "demo_quinua", "demo_palta", "demo_arandano"):
        rb1 = repo1.get_active_by_crop(crop_id)
        rb2 = repo2.get_active_by_crop(crop_id)
        # criteria IDs are uuid5 → deterministic
        ids1 = {c.name: c.id for c in rb1.criteria}
        ids2 = {c.name: c.id for c in rb2.criteria}
        assert ids1 == ids2, f"{crop_id} criterion IDs differ: {ids1} vs {ids2}"
        # phase IDs are uuid5 → deterministic
        pids1 = {p.name: p.id for p in rb1.phases}
        pids2 = {p.name: p.id for p in rb2.phases}
        assert pids1 == pids2, f"{crop_id} phase IDs differ"


# ─── 12. Session factory integration ──────────────────────────────────────────

def test_session_factory_integration():
    from scripts.seed_multivariable_diagnostic_rulebooks import seed_multivariable_diagnostic_rulebooks

    repo = InMemoryRulebookRepository()
    sessions_created: list[FakeSession] = []

    def factory() -> FakeSession:
        s = FakeSession()
        sessions_created.append(s)
        return s

    def cleanup(session) -> None:
        pass

    def repo_factory(session) -> InMemoryRulebookRepository:
        return repo

    result = seed_multivariable_diagnostic_rulebooks(factory, cleanup, repo_factory)
    assert len(result) == 5
    assert sessions_created[0].committed
    assert sessions_created[0].closed


def test_session_rollback_on_error():
    from scripts.seed_multivariable_diagnostic_rulebooks import seed_multivariable_diagnostic_rulebooks

    repo = InMemoryRulebookRepository()
    sessions_created: list[FakeSession] = []

    def factory() -> FakeSession:
        s = FakeSession()
        sessions_created.append(s)
        return s

    def bad_cleanup(session) -> None:
        raise RuntimeError("DB exploded")

    def repo_factory(session) -> InMemoryRulebookRepository:
        return repo

    with pytest.raises(RuntimeError, match="DB exploded"):
        seed_multivariable_diagnostic_rulebooks(factory, bad_cleanup, repo_factory)

    assert sessions_created[0].rolled_back
    assert sessions_created[0].closed
