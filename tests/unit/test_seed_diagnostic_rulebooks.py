"""Unit tests for scripts/seed_diagnostic_rulebooks.py."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from uuid import UUID

import pytest

from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import CriticalPolicy, RulebookStatus


_SCRIPT_PATH = pathlib.Path(__file__).parents[2] / "scripts" / "seed_diagnostic_rulebooks.py"
_DEMO_SCRIPT_PATH = pathlib.Path(__file__).parents[2] / "scripts" / "seed_demo_rulebooks.py"


def _load_module(path: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_diag() -> types.ModuleType:
    return _load_module(_SCRIPT_PATH, "seed_diagnostic_rulebooks")


def _load_demo() -> types.ModuleType:
    return _load_module(_DEMO_SCRIPT_PATH, "seed_demo_rulebooks")


# ─── Structural tests ─────────────────────────────────────────────────────────


def test_builds_five_complete_diagnostic_rulebooks_with_requirements_per_phase() -> None:
    mod = _load_diag()

    for crop_id in mod.DEMO_CROPS:
        criteria, phases, requirements = mod.build_diagnostic_rulebook_parts(crop_id)

        assert len(criteria) == 5, f"{crop_id}: expected 5 criteria"
        assert len(phases) == 4, f"{crop_id}: expected 4 phases"
        assert len(requirements) == 20, f"{crop_id}: expected 20 requirements (5×4)"

        for criterion in criteria:
            crit_reqs = [r for r in requirements if r.criterion_id == criterion.id]
            assert len(crit_reqs) == 4, f"{crop_id}/{criterion.name}: expected 4 phase requirements"
            assert not hasattr(criterion, "membership_fn"), "membership_fn must not be on Criterion"
            assert all(r.membership_fn.function_type == "TRAPEZOIDAL" for r in crit_reqs)
            assert all(r.extraction_binding.variable_name == "nir_reflectancia" for r in crit_reqs)


def test_membership_fn_lives_in_phase_requirement_not_criterion() -> None:
    mod = _load_diag()
    for crop_id in mod.DEMO_CROPS:
        criteria, _, requirements = mod.build_diagnostic_rulebook_parts(crop_id)
        for criterion in criteria:
            assert not hasattr(criterion, "membership_fn")
        for req in requirements:
            assert req.membership_fn is not None
            assert req.membership_fn.function_type == "TRAPEZOIDAL"


def test_each_phase_requirement_has_exactly_one_temporal_period() -> None:
    mod = _load_diag()
    for crop_id in mod.DEMO_CROPS:
        _, _, requirements = mod.build_diagnostic_rulebook_parts(crop_id)
        for req in requirements:
            assert len(req.temporal_periods) == 1
            assert req.temporal_periods[0].temporal_weight == 1.0
            assert req.temporal_periods[0].period_key.endswith("_diag")


# ─── Weight tests ─────────────────────────────────────────────────────────────


def test_ahp_weights_sum_to_one_for_every_crop() -> None:
    mod = _load_diag()
    for crop_id in mod.DEMO_CROPS:
        criteria, _, _ = mod.build_diagnostic_rulebook_parts(crop_id)
        total = sum(c.ahp_weight for c in criteria)
        assert abs(total - 1.0) < 1e-9, f"{crop_id}: AHP weights sum to {total}, not 1.0"


def test_ahp_weights_are_non_uniform() -> None:
    mod = _load_diag()
    criteria, _, _ = mod.build_diagnostic_rulebook_parts("demo_maiz")
    weights = {c.name: c.ahp_weight for c in criteria}
    assert len(set(weights.values())) > 1, "All AHP weights are equal — differentiated rulebook requires non-uniform weights"
    assert weights["vegetacion_vigor"] == pytest.approx(0.35)
    assert weights["estres_hidrico"] == pytest.approx(0.25)
    assert weights["humedad_superficial"] == pytest.approx(0.20)
    assert weights["estabilidad_fenologica"] == pytest.approx(0.12)
    assert weights["aptitud_general"] == pytest.approx(0.08)


def test_phase_weights_sum_to_one_for_every_criterion_in_every_crop() -> None:
    mod = _load_diag()
    for crop_id in mod.DEMO_CROPS:
        criteria, _, requirements = mod.build_diagnostic_rulebook_parts(crop_id)
        for criterion in criteria:
            phase_weights = [r.phase_weight for r in requirements if r.criterion_id == criterion.id]
            assert abs(sum(phase_weights) - 1.0) < 1e-9, (
                f"{crop_id}/{criterion.name}: phase weights sum to {sum(phase_weights)}, not 1.0"
            )


# ─── Critical criteria tests ──────────────────────────────────────────────────


def test_maiz_has_no_critical_criteria() -> None:
    mod = _load_diag()
    criteria, _, _ = mod.build_diagnostic_rulebook_parts("demo_maiz")
    assert not any(c.is_critical for c in criteria), "demo_maiz should have no critical criteria"


@pytest.mark.parametrize("crop_id", ["demo_papa", "demo_quinua", "demo_palta", "demo_arandano"])
def test_crops_with_critical_policy_have_at_least_one_critical_criterion(crop_id: str) -> None:
    mod = _load_diag()
    criteria, _, _ = mod.build_diagnostic_rulebook_parts(crop_id)
    assert any(c.is_critical for c in criteria), f"{crop_id} should have at least one critical criterion"


@pytest.mark.parametrize("crop_id", ["demo_papa", "demo_quinua", "demo_palta"])
def test_estres_hidrico_has_penalize_policy(crop_id: str) -> None:
    mod = _load_diag()
    criteria, _, _ = mod.build_diagnostic_rulebook_parts(crop_id)
    crit = next(c for c in criteria if c.name == "estres_hidrico")
    assert crit.is_critical
    assert crit.critical_policy == CriticalPolicy.PENALIZE
    assert crit.penalty_factor is not None
    assert 0.0 < crit.penalty_factor < 1.0


def test_demo_papa_penalty_factor_is_highest_among_penalize_crops() -> None:
    mod = _load_diag()

    def _get_penalty(crop_id: str) -> float:
        criteria, _, _ = mod.build_diagnostic_rulebook_parts(crop_id)
        crit = next(c for c in criteria if c.name == "estres_hidrico")
        assert crit.penalty_factor is not None
        return crit.penalty_factor

    assert _get_penalty("demo_papa") > _get_penalty("demo_quinua") > _get_penalty("demo_palta")


def test_demo_arandano_vegetacion_vigor_has_no_viable_policy() -> None:
    mod = _load_diag()
    criteria, _, _ = mod.build_diagnostic_rulebook_parts("demo_arandano")
    crit = next(c for c in criteria if c.name == "vegetacion_vigor")
    assert crit.is_critical
    assert crit.critical_policy == CriticalPolicy.NO_VIABLE
    assert crit.penalty_factor is None


def test_demo_arandano_vegetacion_vigor_trapezoids_produce_zero_membership() -> None:
    """All four phases of arandano/veg have a > typical B8 values (~5137)."""
    mod = _load_diag()
    _, _, requirements = mod.build_diagnostic_rulebook_parts("demo_arandano")
    criteria, _, _ = mod.build_diagnostic_rulebook_parts("demo_arandano")

    veg_id = next(c.id for c in criteria if c.name == "vegetacion_vigor")
    veg_reqs = [r for r in requirements if r.criterion_id == veg_id]
    assert len(veg_reqs) == 4

    for req in veg_reqs:
        mfn = req.membership_fn
        # a > 5200 guarantees membership(5137) == 0.0 for any typical B8 value
        assert mfn.a > 5200.0, (
            f"arandano/veg/{req.phase_id}: expected a > 5200, got a={mfn.a}. "
            "This trapezoid will not force zero membership for typical B8 values."
        )


# ─── Differentiation tests ────────────────────────────────────────────────────


def test_trapezoids_differ_between_maiz_and_arandano_for_same_criterion() -> None:
    mod = _load_diag()

    def _get_traps(crop_id: str) -> set[tuple]:
        _, phases, requirements = mod.build_diagnostic_rulebook_parts(crop_id)
        criteria, _, _ = mod.build_diagnostic_rulebook_parts(crop_id)
        veg_id = next(c.id for c in criteria if c.name == "vegetacion_vigor")
        return {
            (r.membership_fn.a, r.membership_fn.b, r.membership_fn.c, r.membership_fn.d)
            for r in requirements
            if r.criterion_id == veg_id
        }

    maiz_traps = _get_traps("demo_maiz")
    arandano_traps = _get_traps("demo_arandano")
    assert maiz_traps != arandano_traps, "demo_maiz and demo_arandano must have different trapezoids for vegetacion_vigor"


def test_all_five_crops_have_distinct_trapezoid_sets_for_vegacion_vigor() -> None:
    mod = _load_diag()

    all_trap_sets: list[frozenset] = []
    for crop_id in mod.DEMO_CROPS:
        criteria, _, requirements = mod.build_diagnostic_rulebook_parts(crop_id)
        veg_id = next(c.id for c in criteria if c.name == "vegetacion_vigor")
        traps = frozenset(
            (r.membership_fn.a, r.membership_fn.b)
            for r in requirements
            if r.criterion_id == veg_id
        )
        all_trap_sets.append(traps)

    unique_sets = len(set(all_trap_sets))
    assert unique_sets >= 3, (
        f"Expected at least 3 distinct (a,b) pairs across 5 crops; got {unique_sets}"
    )


# ─── Disclaimer / metadata tests ─────────────────────────────────────────────


def test_diag_doc_source_contains_diagnostic_disclaimer() -> None:
    mod = _load_diag()
    src = mod.DIAG_DOC_SOURCE.lower()
    assert "diagnós" in src or "diagnos" in src or "fixture" in src.lower()
    assert "inia" in src.lower()


def test_criteria_doc_source_contains_disclaimer_for_all_crops() -> None:
    mod = _load_diag()
    for crop_id in mod.DEMO_CROPS:
        criteria, _, _ = mod.build_diagnostic_rulebook_parts(crop_id)
        for criterion in criteria:
            assert criterion.doc_source is not None
            assert "inia" in criterion.doc_source.lower() or "diagnós" in criterion.doc_source.lower()


# ─── Stable-ID uniqueness tests ───────────────────────────────────────────────


def test_diagnostic_stable_ids_differ_from_demo_stable_ids_for_same_crop() -> None:
    diag = _load_diag()
    demo = _load_demo()

    for crop_id in diag.DEMO_CROPS:
        diag_criteria, _, _ = diag.build_diagnostic_rulebook_parts(crop_id)
        demo_criteria, _, _ = demo.build_demo_rulebook_parts(crop_id)

        diag_ids = {c.id for c in diag_criteria}
        demo_ids = {c.id for c in demo_criteria}
        assert diag_ids.isdisjoint(demo_ids), (
            f"{crop_id}: diagnostic and demo criteria share UUIDs — they would overwrite each other"
        )


# ─── Create-and-publish integration ──────────────────────────────────────────


def test_create_and_publish_diagnostic_rulebooks_leaves_five_active_rulebooks() -> None:
    mod = _load_diag()
    store = FakeRulebookStore()

    seeded = mod.create_and_publish_diagnostic_rulebooks(FakeRulebookRepository(store))

    assert len(seeded) == 5
    assert len(store.rulebooks) == 5
    assert {item.crop_id for item in seeded} == set(mod.DEMO_CROPS)
    assert all(item.status == RulebookStatus.ACTIVE.value for item in seeded)
    assert all(r.status == RulebookStatus.ACTIVE for r in store.rulebooks)


def test_seed_diagnostic_rulebooks_is_idempotent_when_run_twice() -> None:
    mod = _load_diag()
    store = FakeRulebookStore()

    def session_factory() -> FakeSession:
        return FakeSession()

    def cleanup_func(_session: FakeSession) -> None:
        store.remove_demo_rulebooks(set(mod.DEMO_CROPS))

    def repository_factory(_session: FakeSession) -> FakeRulebookRepository:
        return FakeRulebookRepository(store)

    first = mod.seed_diagnostic_rulebooks(session_factory, cleanup_func, repository_factory)
    second = mod.seed_diagnostic_rulebooks(session_factory, cleanup_func, repository_factory)

    assert len(first) == 5
    assert len(second) == 5
    assert len(store.rulebooks) == 5
    assert sorted(r.crop_id for r in store.rulebooks) == sorted(mod.DEMO_CROPS)
    assert all(r.status == RulebookStatus.ACTIVE for r in store.rulebooks)


def test_no_hardcoded_db_credentials_in_script() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    # Check for actual hardcoded secret values — NOT placeholder examples in
    # docstrings (e.g. "$env:DATABASE_URL=...") which are legitimate usage docs.
    forbidden = [
        "BEGIN RSA",
        "BEGIN EC",
        "Admin123",
    ]
    for pattern in forbidden:
        assert pattern.lower() not in source.lower(), (
            f"Script contains hardcoded sensitive string: {pattern!r}"
        )


# ─── Test doubles ─────────────────────────────────────────────────────────────


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeRulebookStore:
    def __init__(self) -> None:
        self.rulebooks: list[Rulebook] = []

    def remove_demo_rulebooks(self, crop_ids: set[str]) -> None:
        self.rulebooks = [r for r in self.rulebooks if r.crop_id not in crop_ids]


class FakeRulebookRepository:
    def __init__(self, store: FakeRulebookStore) -> None:
        self._store = store

    def next_version_for_crop(self, crop_id: str) -> int:
        versions = [r.version for r in self._store.rulebooks if r.crop_id == crop_id]
        return max(versions, default=0) + 1

    def add(self, rulebook: Rulebook) -> None:
        self._store.rulebooks.append(rulebook)

    def get_by_id(self, rulebook_id: UUID) -> Rulebook | None:
        return next((r for r in self._store.rulebooks if r.id == rulebook_id), None)

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        for r in self._store.rulebooks:
            if r.crop_id == crop_id and r.status == RulebookStatus.ACTIVE:
                r.deactivate()

    def save(self, rulebook: Rulebook) -> None:
        if self.get_by_id(rulebook.id) is None:
            self._store.rulebooks.append(rulebook)
