"""Unit tests for scripts/seed_demo_rulebooks.py."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from uuid import UUID

from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import RulebookStatus


def _load_module() -> types.ModuleType:
    """Import seed_demo_rulebooks without executing main()."""

    path = pathlib.Path(__file__).parents[2] / "scripts" / "seed_demo_rulebooks.py"
    spec = importlib.util.spec_from_file_location("seed_demo_rulebooks", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_builds_five_complete_demo_rulebooks_with_requirements_per_phase() -> None:
    mod = _load_module()

    for crop_id in mod.DEMO_CROPS:
        criteria, phases, requirements = mod.build_demo_rulebook_parts(crop_id)

        assert len(criteria) == 5
        assert len(phases) == 4
        assert len(requirements) == len(criteria) * len(phases)
        for criterion in criteria:
            criterion_requirements = [item for item in requirements if item.criterion_id == criterion.id]
            assert len(criterion_requirements) == len(phases)
            assert not hasattr(criterion, "membership_fn")
            assert all(item.membership_fn.function_type == "TRAPEZOIDAL" for item in criterion_requirements)
            assert all(item.extraction_binding.variable_name == "nir_reflectancia" for item in criterion_requirements)


def test_create_and_publish_demo_rulebooks_leaves_five_active_rulebooks() -> None:
    mod = _load_module()
    store = FakeRulebookStore()

    seeded = mod.create_and_publish_demo_rulebooks(FakeRulebookRepository(store))

    assert len(seeded) == 5
    assert len(store.rulebooks) == 5
    assert {item.crop_id for item in seeded} == set(mod.DEMO_CROPS)
    assert all(item.status == RulebookStatus.ACTIVE.value for item in seeded)
    assert all(rulebook.status == RulebookStatus.ACTIVE for rulebook in store.rulebooks)


def test_seed_demo_rulebooks_is_idempotent_when_run_twice() -> None:
    mod = _load_module()
    store = FakeRulebookStore()

    def session_factory() -> FakeSession:
        return FakeSession()

    def cleanup_func(_session: FakeSession) -> None:
        store.remove_demo_rulebooks(set(mod.DEMO_CROPS))

    def repository_factory(_session: FakeSession) -> FakeRulebookRepository:
        return FakeRulebookRepository(store)

    first = mod.seed_demo_rulebooks(session_factory, cleanup_func, repository_factory)
    second = mod.seed_demo_rulebooks(session_factory, cleanup_func, repository_factory)

    assert len(first) == 5
    assert len(second) == 5
    assert len(store.rulebooks) == 5
    assert sorted(rulebook.crop_id for rulebook in store.rulebooks) == sorted(mod.DEMO_CROPS)
    assert all(rulebook.status == RulebookStatus.ACTIVE for rulebook in store.rulebooks)


class FakeSession:
    """Minimal session double used by the seed unit tests."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        """Record commit."""

        self.commits += 1

    def rollback(self) -> None:
        """Record rollback."""

        self.rollbacks += 1

    def close(self) -> None:
        """Record close."""

        self.closed = True


class FakeRulebookStore:
    """Shared in-memory rulebook store."""

    def __init__(self) -> None:
        self.rulebooks: list[Rulebook] = []

    def remove_demo_rulebooks(self, crop_ids: set[str]) -> None:
        """Remove demo crops from the in-memory store."""

        self.rulebooks = [rulebook for rulebook in self.rulebooks if rulebook.crop_id not in crop_ids]


class FakeRulebookRepository:
    """Rulebook repository double implementing the seed's required methods."""

    def __init__(self, store: FakeRulebookStore) -> None:
        self._store = store

    def next_version_for_crop(self, crop_id: str) -> int:
        """Return next version for one crop."""

        versions = [rulebook.version for rulebook in self._store.rulebooks if rulebook.crop_id == crop_id]
        return max(versions, default=0) + 1

    def add(self, rulebook: Rulebook) -> None:
        """Add a rulebook to the store."""

        self._store.rulebooks.append(rulebook)

    def get_by_id(self, rulebook_id: UUID) -> Rulebook | None:
        """Return one rulebook by id."""

        return next((rulebook for rulebook in self._store.rulebooks if rulebook.id == rulebook_id), None)

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        """Deactivate active rulebooks for a crop."""

        for rulebook in self._store.rulebooks:
            if rulebook.crop_id == crop_id and rulebook.status == RulebookStatus.ACTIVE:
                rulebook.deactivate()

    def save(self, rulebook: Rulebook) -> None:
        """Save a rulebook state change."""

        if self.get_by_id(rulebook.id) is None:
            self._store.rulebooks.append(rulebook)
