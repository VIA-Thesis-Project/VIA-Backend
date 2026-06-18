"""Unit tests for scripts/process_outbox_for_evaluation.py."""

from __future__ import annotations

import importlib.util
import pathlib
import types
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

_SCRIPT_PATH = pathlib.Path(__file__).parents[2] / "scripts" / "process_outbox_for_evaluation.py"
_VALID_UUID = "c0345c1c-2085-41af-b3ac-82950ab276a2"


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("process_outbox_for_evaluation", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ─── Argument parsing ─────────────────────────────────────────────────────────


def test_parse_args_accepts_valid_uuid() -> None:
    mod = _load_module()
    args = mod._parse_args([_VALID_UUID])
    assert args.evaluation_id == UUID(_VALID_UUID)


def test_parse_args_rejects_invalid_uuid() -> None:
    mod = _load_module()
    with pytest.raises(SystemExit) as exc_info:
        mod._parse_args(["not-a-uuid"])
    assert exc_info.value.code != 0


def test_parse_args_default_values() -> None:
    mod = _load_module()
    args = mod._parse_args([_VALID_UUID])
    assert args.max_rounds == 10
    assert args.pause_seconds == 2.0
    assert args.until_completed is False
    assert args.dry_run is False


def test_parse_args_custom_rounds_and_pause() -> None:
    mod = _load_module()
    args = mod._parse_args([_VALID_UUID, "--max-rounds", "5", "--pause-seconds", "0.5"])
    assert args.max_rounds == 5
    assert args.pause_seconds == 0.5


def test_parse_args_until_completed_flag() -> None:
    mod = _load_module()
    args = mod._parse_args([_VALID_UUID, "--until-completed"])
    assert args.until_completed is True


def test_parse_args_dry_run_flag() -> None:
    mod = _load_module()
    args = mod._parse_args([_VALID_UUID, "--dry-run"])
    assert args.dry_run is True


def test_parse_args_all_flags_together() -> None:
    mod = _load_module()
    args = mod._parse_args([
        _VALID_UUID,
        "--max-rounds", "3",
        "--pause-seconds", "1",
        "--until-completed",
        "--dry-run",
    ])
    assert args.evaluation_id == UUID(_VALID_UUID)
    assert args.max_rounds == 3
    assert args.pause_seconds == 1.0
    assert args.until_completed is True
    assert args.dry_run is True


# ─── UUID helper ──────────────────────────────────────────────────────────────


def test_parse_uuid_accepts_valid() -> None:
    mod = _load_module()
    result = mod._parse_uuid(_VALID_UUID)
    assert result == UUID(_VALID_UUID)


def test_parse_uuid_rejects_garbage() -> None:
    import argparse
    mod = _load_module()
    with pytest.raises(argparse.ArgumentTypeError):
        mod._parse_uuid("not-a-uuid")


# ─── No hardcoded secrets ─────────────────────────────────────────────────────


def test_no_hardcoded_credentials_in_script() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    # Check for actual hardcoded secret values — NOT env-var names such as
    # GEE_PRIVATE_KEY_FILE or JWT_SECRET_KEY, which are legitimate references.
    forbidden_patterns = [
        "BEGIN RSA",
        "BEGIN EC",
        "via_password",
        "Admin123",
        "postgresql+psycopg2://via_user",
        "postgresql+psycopg2://via:",
    ]
    for pattern in forbidden_patterns:
        assert pattern.lower() not in source.lower(), (
            f"El script contiene la cadena sensible '{pattern}' hardcodeada"
        )


# ─── Processing loop ─────────────────────────────────────────────────────────


def _make_saga_session_factory(status: str = "INICIADA"):
    """Build a minimal mock session_factory that returns a saga with the given status."""
    saga = MagicMock()
    saga.status = status

    session = MagicMock()
    session.get.return_value = saga
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=None)

    return MagicMock(return_value=session)


def test_run_rounds_calls_relay_exactly_max_rounds_times() -> None:
    mod = _load_module()
    relay = MagicMock()
    relay.process_batch.return_value = 0

    sf = _make_saga_session_factory("INICIADA")

    with patch.object(mod.time, "sleep"):
        result = mod.run_rounds(
            relay=relay,
            session_factory=sf,
            evaluation_id=UUID(_VALID_UUID),
            max_rounds=4,
            pause_seconds=0,
            until_completed=False,
        )

    assert relay.process_batch.call_count == 4
    assert result == "INICIADA"


def test_run_rounds_stops_early_on_terminal_status() -> None:
    mod = _load_module()
    relay = MagicMock()
    relay.process_batch.return_value = 1

    sf = _make_saga_session_factory("EVALUACION_COMPLETADA")

    with patch.object(mod.time, "sleep"):
        result = mod.run_rounds(
            relay=relay,
            session_factory=sf,
            evaluation_id=UUID(_VALID_UUID),
            max_rounds=10,
            pause_seconds=0,
            until_completed=True,
        )

    # Should have stopped after the first round once terminal status was seen.
    assert relay.process_batch.call_count == 1
    assert result == "EVALUACION_COMPLETADA"


def test_run_rounds_does_not_stop_early_without_until_completed() -> None:
    mod = _load_module()
    relay = MagicMock()
    relay.process_batch.return_value = 0

    sf = _make_saga_session_factory("EVALUACION_COMPLETADA")

    with patch.object(mod.time, "sleep"):
        mod.run_rounds(
            relay=relay,
            session_factory=sf,
            evaluation_id=UUID(_VALID_UUID),
            max_rounds=5,
            pause_seconds=0,
            until_completed=False,
        )

    assert relay.process_batch.call_count == 5


def test_run_rounds_zero_max_rounds_does_not_call_relay() -> None:
    mod = _load_module()
    relay = MagicMock()
    sf = _make_saga_session_factory()

    result = mod.run_rounds(
        relay=relay,
        session_factory=sf,
        evaluation_id=UUID(_VALID_UUID),
        max_rounds=0,
        pause_seconds=0,
        until_completed=False,
    )

    relay.process_batch.assert_not_called()
    assert result is None


# ─── Terminal statuses constant ───────────────────────────────────────────────


def test_terminal_statuses_include_expected_values() -> None:
    mod = _load_module()
    assert "EVALUACION_COMPLETADA" in mod._TERMINAL_STATUSES
    assert "RECOMENDACION_COMPLETADA" in mod._TERMINAL_STATUSES
    assert "FALLIDA" in mod._TERMINAL_STATUSES
    # Non-terminal statuses must NOT be included.
    assert "INICIADA" not in mod._TERMINAL_STATUSES
    assert "EXTRACCION_COMPLETADA" not in mod._TERMINAL_STATUSES
