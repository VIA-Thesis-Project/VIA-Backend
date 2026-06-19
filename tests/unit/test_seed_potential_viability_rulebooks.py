"""Tests for seed_potential_viability_rulebooks.py — VIABILIDAD POTENCIAL CON CLIMA Y SUELO.

Valida:
- 12 criterios por cultivo: 5 climáticos + 2 estructurales + 4 edáficos + 1 auxiliar NDVI
- Pesos AHP: clima 0.48, suelo 0.27, topografía 0.20, auxiliar 0.05 → suma = 1.00
- Bindings climáticos: ERA5-Land (temperatura, PET) y CHIRPS (precipitación)
- Bindings edáficos: OpenLandMap v02 (~250m, topsoil_0_30cm_mean)
- NDVI como criterio auxiliar (sin política crítica, peso 0.05)
- Políticas críticas solo en criterios estructurales (altitudinal, topográfico)
- Metadato VIABILIDAD POTENCIAL
- Sin uso de IDAHO_EPSCOR/TERRACLIMATE en ningún binding
- Suma de pesos = 1.00 por cultivo
- Clima es el grupo más pesado (0.48 > suelo 0.27 > topo 0.20 > aux 0.05)
"""
from __future__ import annotations

import math
from uuid import UUID

import pytest

from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import CriticalPolicy


# ─── In-memory repository ─────────────────────────────────────────────────────

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
        pass

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


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def repo() -> InMemoryRulebookRepository:
    return InMemoryRulebookRepository()


@pytest.fixture()
def seeded(repo: InMemoryRulebookRepository):
    from scripts.seed_potential_viability_rulebooks import create_and_publish_potential_viability_rulebooks
    return create_and_publish_potential_viability_rulebooks(repo)


@pytest.fixture()
def all_rulebooks(repo: InMemoryRulebookRepository, seeded) -> list[Rulebook]:
    return list(repo._store.values())


@pytest.fixture()
def rulebook_map(repo: InMemoryRulebookRepository, seeded) -> dict[str, Rulebook]:
    return {rb.crop_id: rb for rb in repo._store.values()}


# ─── Helper functions ──────────────────────────────────────────────────────────

def _deg(pct: float) -> float:
    return round(math.atan(pct / 100.0) * (180.0 / math.pi), 2)


def _get_criterion(rulebook: Rulebook, name: str):
    for c in rulebook.criteria:
        if c.name == name:
            return c
    raise KeyError(f"Criterion {name!r} not in {rulebook.crop_id}")


def _get_requirements(rulebook: Rulebook, criterion_name: str):
    crit = _get_criterion(rulebook, criterion_name)
    return [r for r in rulebook.phase_requirements if r.criterion_id == crit.id]


def _first_trap(rb: Rulebook, criterion_name: str) -> tuple:
    reqs = _get_requirements(rb, criterion_name)
    mf = reqs[0].membership_fn
    return (mf.a, mf.b, mf.c, mf.d)


# ─── 1. Structure ─────────────────────────────────────────────────────────────

def test_five_crops_seeded(seeded):
    assert len(seeded) == 5


def test_twelve_criteria_per_crop(all_rulebooks):
    for rb in all_rulebooks:
        assert len(rb.criteria) == 12, f"{rb.crop_id} has {len(rb.criteria)} criteria"


def test_four_phases_per_crop(all_rulebooks):
    for rb in all_rulebooks:
        assert len(rb.phases) == 4, f"{rb.crop_id} has {len(rb.phases)} phases"


def test_forty_eight_requirements_per_crop(all_rulebooks):
    for rb in all_rulebooks:
        assert len(rb.phase_requirements) == 48, f"{rb.crop_id} has {len(rb.phase_requirements)} reqs"


def test_all_rulebooks_active(all_rulebooks):
    for rb in all_rulebooks:
        assert rb.status.value == "ACTIVE"


# ─── 2. Nombres de criterios ───────────────────────────────────────────────────

EXPECTED_CRITERIA = {
    "aptitud_termica",
    "riesgo_frio",
    "riesgo_calor",
    "disponibilidad_hidrica",
    "deficit_hidrico",
    "aptitud_altitudinal",
    "aptitud_topografica",
    "reaccion_suelo_ph",
    "contenido_arcilla",
    "contenido_arena",
    "carbono_organico_suelo",
    "cobertura_actual_auxiliar",
}

CLIMATE_CRITERIA = {
    "aptitud_termica",
    "riesgo_frio",
    "riesgo_calor",
    "disponibilidad_hidrica",
    "deficit_hidrico",
}

SOIL_CRITERIA = {
    "reaccion_suelo_ph",
    "contenido_arcilla",
    "contenido_arena",
    "carbono_organico_suelo",
}

STRUCTURAL_CRITERIA = {"aptitud_altitudinal", "aptitud_topografica"}

AUXILIARY_CRITERIA = {"cobertura_actual_auxiliar"}


def test_twelve_criteria_names_correct(all_rulebooks):
    for rb in all_rulebooks:
        names = {c.name for c in rb.criteria}
        assert names == EXPECTED_CRITERIA, f"{rb.crop_id}: {names}"


def test_no_old_criteria_names(all_rulebooks):
    forbidden = {"vegetacion_vigor", "cobertura_vegetal_ajustada", "estres_hidrico",
                 "cobertura_actual", "cobertura_suelo_ajustada", "humedad_vegetacion_auxiliar"}
    for rb in all_rulebooks:
        names = {c.name for c in rb.criteria}
        overlap = names & forbidden
        assert not overlap, f"{rb.crop_id} has unexpected criteria: {overlap}"


# ─── 3. Pesos AHP ─────────────────────────────────────────────────────────────

EXPECTED_WEIGHTS = {
    "aptitud_termica":           0.12,
    "riesgo_frio":               0.07,
    "riesgo_calor":              0.07,
    "disponibilidad_hidrica":    0.12,
    "deficit_hidrico":           0.10,
    "aptitud_altitudinal":       0.12,
    "aptitud_topografica":       0.08,
    "reaccion_suelo_ph":         0.10,
    "contenido_arcilla":         0.07,
    "contenido_arena":           0.06,
    "carbono_organico_suelo":    0.04,
    "cobertura_actual_auxiliar": 0.05,
}


def test_ahp_weights_correct(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            expected = EXPECTED_WEIGHTS[crit.name]
            assert abs(crit.ahp_weight - expected) < 1e-9, (
                f"{rb.crop_id}.{crit.name}: {crit.ahp_weight} != {expected}"
            )


def test_ahp_weights_sum_to_one(all_rulebooks):
    for rb in all_rulebooks:
        total = sum(c.ahp_weight for c in rb.criteria)
        assert abs(total - 1.0) < 1e-9, f"{rb.crop_id}: sum={total}"


def test_climate_weight_is_dominant_group(all_rulebooks):
    """Clima (0.48) es el grupo de mayor peso, por encima de suelo (0.27), topo (0.20), aux (0.05)."""
    for rb in all_rulebooks:
        climate_w = sum(_get_criterion(rb, name).ahp_weight for name in CLIMATE_CRITERIA)
        soil_w = sum(_get_criterion(rb, name).ahp_weight for name in SOIL_CRITERIA)
        topo_w = sum(_get_criterion(rb, name).ahp_weight for name in STRUCTURAL_CRITERIA)
        aux_w = _get_criterion(rb, "cobertura_actual_auxiliar").ahp_weight
        assert climate_w > soil_w, f"{rb.crop_id}: climate ({climate_w}) not > soil ({soil_w})"
        assert climate_w > topo_w, f"{rb.crop_id}: climate ({climate_w}) not > topo ({topo_w})"
        assert climate_w > aux_w, f"{rb.crop_id}: climate ({climate_w}) not > aux ({aux_w})"
        assert abs(climate_w - 0.48) < 1e-9, f"{rb.crop_id}: climate weight should be 0.48, got {climate_w}"


def test_auxiliary_weight_is_at_most_015(all_rulebooks):
    for rb in all_rulebooks:
        aux_w = _get_criterion(rb, "cobertura_actual_auxiliar").ahp_weight
        assert aux_w <= 0.15, f"{rb.crop_id}: cobertura weight={aux_w}"


def test_auxiliary_weight_is_less_than_any_climate_criterion(all_rulebooks):
    for rb in all_rulebooks:
        aux_w = _get_criterion(rb, "cobertura_actual_auxiliar").ahp_weight
        for name in CLIMATE_CRITERIA:
            climate_w = _get_criterion(rb, name).ahp_weight
            assert aux_w < climate_w, (
                f"{rb.crop_id}: cobertura ({aux_w}) >= {name} ({climate_w})"
            )


# ─── 4. Políticas críticas ────────────────────────────────────────────────────

def test_ndvi_auxiliar_not_critical(all_rulebooks):
    for rb in all_rulebooks:
        crit = _get_criterion(rb, "cobertura_actual_auxiliar")
        assert not crit.is_critical, f"{rb.crop_id}: cobertura_actual_auxiliar must not be critical"


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


def test_climate_criteria_not_critical_for_maiz(rulebook_map):
    rb = rulebook_map["demo_maiz"]
    for name in CLIMATE_CRITERIA:
        crit = _get_criterion(rb, name)
        assert not crit.is_critical, f"demo_maiz.{name} should not be critical"


# ─── 5. Extraction bindings ────────────────────────────────────────────────────

_ERA5   = "ECMWF/ERA5_LAND/MONTHLY_AGGR"
_CHIRPS = "UCSB-CHG/CHIRPS/DAILY"
_OLM_PH   = "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02"
_OLM_CLAY = "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_SAND = "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"
_OLM_OC   = "OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02"

EXPECTED_BINDINGS = {
    "aptitud_termica":           ("temperatura_media_c",          _ERA5),
    "riesgo_frio":               ("temperatura_minima_c",         _ERA5),
    "riesgo_calor":              ("temperatura_maxima_c",         _ERA5),
    "disponibilidad_hidrica":    ("precipitacion_acumulada_mm",   _CHIRPS),
    "deficit_hidrico":           ("deficit_hidrico_mm",           _ERA5),
    "aptitud_altitudinal":       ("elevacion_m",                  "USGS/SRTMGL1_003"),
    "aptitud_topografica":       ("pendiente_grados",             "USGS/SRTMGL1_003"),
    "reaccion_suelo_ph":         ("ph_suelo",                     _OLM_PH),
    "contenido_arcilla":         ("arcilla_pct",                  _OLM_CLAY),
    "contenido_arena":           ("arena_pct",                    _OLM_SAND),
    "carbono_organico_suelo":    ("carbono_organico_suelo",       _OLM_OC),
    "cobertura_actual_auxiliar": ("ndvi",                         "COPERNICUS/S2_SR_HARMONIZED"),
}


def test_extraction_bindings_variables_correct(all_rulebooks):
    for rb in all_rulebooks:
        for crit_name, (var_name, dataset) in EXPECTED_BINDINGS.items():
            reqs = _get_requirements(rb, crit_name)
            for req in reqs:
                assert req.extraction_binding.variable_name == var_name, (
                    f"{rb.crop_id}.{crit_name}: variable_name={req.extraction_binding.variable_name}"
                )
                assert req.extraction_binding.dataset_key == dataset, (
                    f"{rb.crop_id}.{crit_name}: dataset_key={req.extraction_binding.dataset_key}"
                )


def test_no_climate_binding_uses_terraclimate(all_rulebooks):
    """No binding must reference TerraClimate — it has been replaced by ERA5 + CHIRPS."""
    terraclimate = "IDAHO_EPSCOR/TERRACLIMATE"
    for rb in all_rulebooks:
        for crit in rb.criteria:
            reqs = _get_requirements(rb, crit.name)
            for req in reqs:
                assert req.extraction_binding.dataset_key != terraclimate, (
                    f"{rb.crop_id}.{crit.name}: uses TerraClimate (must use ERA5 or CHIRPS)"
                )


def test_era5_temperature_bindings_use_era5_scale(all_rulebooks):
    """ERA5 temperature and deficit bindings use 11132m (ERA5-Land native scale)."""
    era5_criteria = {"aptitud_termica", "riesgo_frio", "riesgo_calor", "deficit_hidrico"}
    for rb in all_rulebooks:
        for crit_name in era5_criteria:
            reqs = _get_requirements(rb, crit_name)
            for req in reqs:
                assert req.extraction_binding.scale == 11132.0, (
                    f"{rb.crop_id}.{crit_name}: scale={req.extraction_binding.scale} (expected 11132.0)"
                )


def test_chirps_precipitation_binding_uses_chirps_scale(all_rulebooks):
    """CHIRPS precipitation binding uses 5566m (CHIRPS native scale)."""
    for rb in all_rulebooks:
        reqs = _get_requirements(rb, "disponibilidad_hidrica")
        for req in reqs:
            assert req.extraction_binding.scale == 5566.0, (
                f"{rb.crop_id}.disponibilidad_hidrica: scale={req.extraction_binding.scale} (expected 5566.0)"
            )


def test_precipitation_uses_sum_aggregation(all_rulebooks):
    for rb in all_rulebooks:
        reqs = _get_requirements(rb, "disponibilidad_hidrica")
        for req in reqs:
            assert req.extraction_binding.aggregation_method == "sum"


def test_temperature_criteria_use_mean_aggregation(all_rulebooks):
    for rb in all_rulebooks:
        for name in ("aptitud_termica", "riesgo_frio", "riesgo_calor"):
            reqs = _get_requirements(rb, name)
            for req in reqs:
                assert req.extraction_binding.aggregation_method == "mean", (
                    f"{rb.crop_id}.{name}: aggregation_method={req.extraction_binding.aggregation_method}"
                )


# ─── 6. Trapecios climáticos ────────────────────────────────────────────────────

def test_precipitation_starts_at_zero_all_crops(all_rulebooks):
    """Precipitación empieza en a=0 porque VIA no modela irrigación."""
    for rb in all_rulebooks:
        trap = _first_trap(rb, "disponibilidad_hidrica")
        assert trap[0] == 0, f"{rb.crop_id}: precipitacion a={trap[0]}"


def test_deficit_starts_at_zero_all_crops(all_rulebooks):
    """Déficit empieza en a=0: incluso bajo déficit es viable."""
    for rb in all_rulebooks:
        trap = _first_trap(rb, "deficit_hidrico")
        assert trap[0] == 0, f"{rb.crop_id}: deficit a={trap[0]}"


def test_ndvi_auxiliar_is_wide_trap(all_rulebooks):
    """NDVI auxiliar usa trapecio amplio — no colapsa por barbecho."""
    for rb in all_rulebooks:
        trap = _first_trap(rb, "cobertura_actual_auxiliar")
        a, b, c, d = trap
        # Plateau starts before 0.05 so NDVI=0.099 (fallow) is inside
        assert b <= 0.05, f"{rb.crop_id}: NDVI plateau starts at b={b}, too late"
        assert c >= 0.90, f"{rb.crop_id}: NDVI plateau ends at c={c}, too early"


def test_ndvi_fallow_land_in_plateau(all_rulebooks):
    """NDVI=0.099 (barbecho) debe quedar en el plateau del auxiliar (μ=1.0)."""
    ndvi_fallow = 0.099
    for rb in all_rulebooks:
        trap = _first_trap(rb, "cobertura_actual_auxiliar")
        a, b, c, d = trap
        assert b <= ndvi_fallow <= c, (
            f"{rb.crop_id}: NDVI={ndvi_fallow} NOT in plateau [{b}, {c}]"
        )


def test_temperature_traps_are_per_crop(all_rulebooks):
    """Trapecios de temperatura difieren entre cultivos (no son uniformes)."""
    traps = {rb.crop_id: _first_trap(rb, "aptitud_termica") for rb in all_rulebooks}
    unique = set(traps.values())
    assert len(unique) >= 3, f"Temperature traps too uniform: {traps}"


def test_papa_temperature_max_below_30(rulebook_map):
    """Papa tiene tolerancia al calor menor que maíz."""
    papa_trap = _first_trap(rulebook_map["demo_papa"], "riesgo_calor")
    maiz_trap = _first_trap(rulebook_map["demo_maiz"], "riesgo_calor")
    assert papa_trap[3] < maiz_trap[3], (
        f"Papa riesgo_calor d={papa_trap[3]} should be < maiz d={maiz_trap[3]}"
    )


def test_papa_elevation_starts_at_1500(rulebook_map):
    trap = _first_trap(rulebook_map["demo_papa"], "aptitud_altitudinal")
    assert trap[0] == 1500


def test_maiz_elevation_starts_at_zero(rulebook_map):
    trap = _first_trap(rulebook_map["demo_maiz"], "aptitud_altitudinal")
    assert trap[0] == 0


def test_palta_slope_starts_above_zero(rulebook_map):
    """Palta necesita mínimo pendiente 1% para drenaje."""
    trap = _first_trap(rulebook_map["demo_palta"], "aptitud_topografica")
    assert trap[0] > 0, f"Palta slope a={trap[0]} should be > 0"
    assert abs(trap[0] - _deg(1)) < 0.01


def test_arandano_slope_is_restrictive(rulebook_map):
    """Arándano requiere pendiente <12% para fertirriego."""
    trap = _first_trap(rulebook_map["demo_arandano"], "aptitud_topografica")
    assert abs(trap[3] - _deg(12)) < 0.01


# ─── 7. Fases fenológicas ─────────────────────────────────────────────────────

def test_four_phases_correct_names_durations(all_rulebooks):
    expected = {"establecimiento": 30, "desarrollo": 45, "floracion": 35, "maduracion": 40}
    for rb in all_rulebooks:
        found = {p.name: p.duration_days for p in rb.phases}
        assert found == expected, f"{rb.crop_id}: {found}"


def test_phase_weights_sum_to_one(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            reqs = [r for r in rb.phase_requirements if r.criterion_id == crit.id]
            total = sum(r.phase_weight for r in reqs)
            assert abs(total - 1.0) < 1e-9, f"{rb.crop_id}.{crit.name}: sum={total}"


# ─── 8. Metadato viabilidad potencial ─────────────────────────────────────────

def test_doc_source_mentions_viabilidad_potencial(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            src = crit.doc_source.upper()
            assert "VIABILIDAD POTENCIAL" in src, (
                f"{rb.crop_id}.{crit.name}: missing VIABILIDAD POTENCIAL"
            )


def test_doc_source_mentions_era5_and_chirps(all_rulebooks):
    """Climate criteria doc_source must reference ERA5 and CHIRPS — not TerraClimate."""
    for rb in all_rulebooks:
        for crit_name in CLIMATE_CRITERIA:
            crit = _get_criterion(rb, crit_name)
            src = crit.doc_source.upper()
            assert "ERA5" in src, (
                f"{rb.crop_id}.{crit_name}: missing ERA5 reference in doc_source"
            )
            assert "CHIRPS" in src, (
                f"{rb.crop_id}.{crit_name}: missing CHIRPS reference in doc_source"
            )
            assert "TERRACLIMATE" not in src and "IDAHO" not in src, (
                f"{rb.crop_id}.{crit_name}: doc_source still mentions TerraClimate"
            )


def test_evapotranspiracion_real_not_in_criteria(all_rulebooks):
    """evapotranspiracion_real_mm was removed; no binding should reference it."""
    for rb in all_rulebooks:
        for crit in rb.criteria:
            reqs = _get_requirements(rb, crit.name)
            for req in reqs:
                assert req.extraction_binding.variable_name != "evapotranspiracion_real_mm", (
                    f"{rb.crop_id}.{crit.name}: still references evapotranspiracion_real_mm"
                )


def test_doc_source_mentions_fixture(all_rulebooks):
    for rb in all_rulebooks:
        for crit in rb.criteria:
            assert "FIXTURE" in crit.doc_source.upper(), (
                f"{rb.crop_id}.{crit.name}: missing FIXTURE disclaimer"
            )


def test_auxiliary_technical_notes_mention_auxiliar(all_rulebooks):
    for rb in all_rulebooks:
        crit = _get_criterion(rb, "cobertura_actual_auxiliar")
        assert "auxiliar" in crit.technical_notes.lower()


# ─── 9. Stable UUIDs ──────────────────────────────────────────────────────────

def test_criteria_ids_are_deterministic():
    from scripts.seed_potential_viability_rulebooks import create_and_publish_potential_viability_rulebooks
    repo1 = InMemoryRulebookRepository()
    repo2 = InMemoryRulebookRepository()
    create_and_publish_potential_viability_rulebooks(repo1)
    create_and_publish_potential_viability_rulebooks(repo2)
    for crop_id in ("demo_maiz", "demo_papa", "demo_quinua", "demo_palta", "demo_arandano"):
        rb1 = repo1.get_active_by_crop(crop_id)
        rb2 = repo2.get_active_by_crop(crop_id)
        ids1 = {c.name: c.id for c in rb1.criteria}
        ids2 = {c.name: c.id for c in rb2.criteria}
        assert ids1 == ids2, f"{crop_id} criterion IDs differ"


def test_uuid_namespace_differs_from_multivariable_seed():
    """Los IDs de este seed deben diferir de los del seed multivariable."""
    from scripts.seed_potential_viability_rulebooks import create_and_publish_potential_viability_rulebooks
    from scripts.seed_multivariable_diagnostic_rulebooks import create_and_publish_multivariable_rulebooks

    repo_pv = InMemoryRulebookRepository()
    repo_mv = InMemoryRulebookRepository()
    create_and_publish_potential_viability_rulebooks(repo_pv)
    create_and_publish_multivariable_rulebooks(repo_mv)

    pv_rb = repo_pv.get_active_by_crop("demo_maiz")
    mv_rb = repo_mv.get_active_by_crop("demo_maiz")
    pv_ids = {c.name: c.id for c in pv_rb.criteria if c.name in ("aptitud_altitudinal", "aptitud_topografica")}
    mv_ids = {c.name: c.id for c in mv_rb.criteria if c.name in ("aptitud_altitudinal", "aptitud_topografica")}
    assert pv_ids != mv_ids, "Same UUIDs in both seeds — namespace collision"


# ─── 10. Session integration ───────────────────────────────────────────────────

def test_session_factory_integration():
    from scripts.seed_potential_viability_rulebooks import seed_potential_viability_rulebooks

    repo = InMemoryRulebookRepository()
    sessions: list[FakeSession] = []

    def factory():
        s = FakeSession()
        sessions.append(s)
        return s

    result = seed_potential_viability_rulebooks(
        factory,
        cleanup_func=lambda s: None,
        repository_factory=lambda s: repo,
    )
    assert len(result) == 5
    assert sessions[0].committed
    assert sessions[0].closed


def test_session_rollback_on_error():
    from scripts.seed_potential_viability_rulebooks import seed_potential_viability_rulebooks

    repo = InMemoryRulebookRepository()
    sessions: list[FakeSession] = []

    def factory():
        s = FakeSession()
        sessions.append(s)
        return s

    def bad_cleanup(s):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        seed_potential_viability_rulebooks(
            factory,
            cleanup_func=bad_cleanup,
            repository_factory=lambda s: repo,
        )

    assert sessions[0].rolled_back
    assert sessions[0].closed
