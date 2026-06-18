"""Minimal unit tests for scripts/seed_admin_user.py."""

from __future__ import annotations

import importlib
import sys
import types


def _load_module() -> types.ModuleType:
    """Import seed_admin_user without executing main()."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parents[2] / "scripts" / "seed_admin_user.py"
    spec = importlib.util.spec_from_file_location("seed_admin_user", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_require_env_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("_VIA_NONEXISTENT_VAR_", raising=False)
    mod = _load_module()
    with __import__("pytest").raises(SystemExit) as exc_info:
        mod._require_env("_VIA_NONEXISTENT_VAR_")
    assert exc_info.value.code == 1


def test_require_env_returns_value(monkeypatch) -> None:
    monkeypatch.setenv("_VIA_TEST_VAR_", "  hello  ")
    mod = _load_module()
    assert mod._require_env("_VIA_TEST_VAR_") == "hello"


def test_admin_role_value() -> None:
    from via.bounded_contexts.iam.domain.role import Role
    assert Role.ADMINISTRADOR == "ADMINISTRADOR"
    assert Role.ADMINISTRADOR.includes(Role.ESPECIALISTA_TECNICO)
    assert Role.ADMINISTRADOR.includes(Role.USUARIO_AGRICOLA)
