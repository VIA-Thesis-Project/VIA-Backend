"""22A: Static checks — integration tests must not use async infrastructure.

VIA uses synchronous SQLAlchemy + psycopg2 exclusively.
These tests are purely static (AST-based) and do not require a live database.
"""

from __future__ import annotations

import ast
import pathlib

_POSTGRES_TEST_DIR = pathlib.Path(__file__).parent

_TEST_FILES = [
    p for p in _POSTGRES_TEST_DIR.glob("test_postgres_*.py")
    if p.name != "test_postgres_no_async.py"
]

_BANNED_NAMES = {
    "asyncpg",
    "AsyncSession",
    "create_async_engine",
    "AsyncEngine",
    "async_sessionmaker",
}


def _gather_imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.append(module)
            for alias in node.names:
                names.append(f"{module}.{alias.name}")
    return names


def _has_async_def(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))


def _has_await(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.Await) for node in ast.walk(tree))


def _has_banned_name(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in _BANNED_NAMES:
            found.add(node.attr)
    return found


def test_no_async_def_in_integration_tests() -> None:
    for path in _TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not _has_async_def(tree), (
            f"{path.name}: contains 'async def'. "
            "Integration tests must be synchronous (VIA uses psycopg2, not asyncpg)."
        )


def test_no_await_in_integration_tests() -> None:
    for path in _TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not _has_await(tree), (
            f"{path.name}: contains 'await'. "
            "Integration tests must be synchronous."
        )


def test_no_asyncpg_or_async_session_imported() -> None:
    for path in _TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        banned = _has_banned_name(tree)
        assert not banned, (
            f"{path.name}: references banned async names: {sorted(banned)}. "
            "VIA does not use asyncpg or AsyncSession."
        )


def test_no_asyncpg_in_imports() -> None:
    for path in _TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = _gather_imports(tree)
        async_imports = [i for i in imports if "asyncpg" in i or "async_session" in i.lower()]
        assert not async_imports, (
            f"{path.name}: imports async infrastructure: {async_imports}"
        )


def test_database_url_comes_from_environment_not_hardcoded() -> None:
    conftest_path = _POSTGRES_TEST_DIR / "conftest.py"
    source = conftest_path.read_text(encoding="utf-8")
    assert "os.environ" in source or "os.getenv" in source, (
        "conftest.py must read DATABASE_URL from os.environ, not hardcode it."
    )


def test_no_sqlite_in_integration_tests() -> None:
    for path in list(_TEST_FILES) + [_POSTGRES_TEST_DIR / "conftest.py"]:
        source = path.read_text(encoding="utf-8")
        assert "sqlite" not in source.lower(), (
            f"{path.name}: contains 'sqlite'. Integration tests must use real PostgreSQL."
        )


def test_no_mock_in_integration_tests() -> None:
    mock_indicators = ["unittest.mock", "from unittest import mock", "pytest.mock", "MagicMock", "Mock("]
    for path in _TEST_FILES:
        source = path.read_text(encoding="utf-8")
        for indicator in mock_indicators:
            assert indicator not in source, (
                f"{path.name}: uses mock ({indicator!r}). "
                "PostgreSQL integration tests must use real database infrastructure."
            )
