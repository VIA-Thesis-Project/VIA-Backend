"""Static architecture checks for VIA Lote 4 IAM."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IAM = ROOT / "via" / "bounded_contexts" / "iam"


def test_iam_domain_has_no_framework_infrastructure_or_crypto_imports() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "jwt",
        "bcrypt",
        "passlib",
        "via.bounded_contexts.iam.infrastructure",
        "via.bounded_contexts.iam.interfaces",
    )
    offenders = []
    for path in (IAM / "domain").glob("*.py"):
        for imported_name in _imports_from(path):
            if any(imported_name == prefix or imported_name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                offenders.append(f"{path.relative_to(ROOT).as_posix()} imports {imported_name}")

    assert offenders == []


def test_password_and_token_ports_live_in_application_layer() -> None:
    text = (IAM / "application" / "ports.py").read_text(encoding="utf-8")

    assert "class IPasswordHasher" in text
    assert "class ITokenService" in text
    assert "class IUserRepository" in text


def test_concrete_password_and_token_adapters_live_in_infrastructure() -> None:
    password_text = (IAM / "infrastructure" / "password_hasher.py").read_text(encoding="utf-8")
    jwt_text = (IAM / "infrastructure" / "jwt_adapter.py").read_text(encoding="utf-8")

    assert "bcrypt" in password_text
    assert "import hashlib" not in password_text
    assert "import hmac" not in password_text
    assert "import jwt" in jwt_text
    assert "class JWTTokenService" in jwt_text


def test_auth_router_exposes_only_login_endpoint() -> None:
    tree = ast.parse((IAM / "interfaces" / "auth_router.py").read_text(encoding="utf-8"))
    route_functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "login"]
    text = (IAM / "interfaces" / "auth_router.py").read_text(encoding="utf-8")

    assert route_functions == ["login"]
    assert "prefix=\"/auth\"" in text
    assert "@router.post(\"/login\"" in text


def test_lote4_does_not_use_forbidden_infrastructure_stack() -> None:
    tokens = ("async" + "pg", "Async" + "Session", "create_" + "async_" + "engine", "Cel" + "ery", "Kaf" + "ka", "Rabbit" + "MQ", "Re" + "dis")
    offenders = []
    for path in IAM.rglob("*.py"):
        if any(token in path.read_text(encoding="utf-8") for token in tokens):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
