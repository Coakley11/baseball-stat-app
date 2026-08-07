"""Bridge suite_sid resolution precedence for Stage 1A production gates."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pytest

from playwright_auth_bridge_restore_harness import (  # noqa: E402
    BridgeSuiteSidConflictError,
    resolve_bridge_suite_sid,
    resolve_bridge_suite_sid_with_source,
)


@pytest.fixture(autouse=True)
def _clear_bridge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("STAGE1_BRIDGE_SUITE_SID", "ROOT_AUDIT_BRIDGE_SUITE_SID", "STAGE1_USE_CAPTURE_BRIDGE"):
        monkeypatch.delenv(key, raising=False)


def test_stage1_bridge_wins_over_root_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGE1_BRIDGE_SUITE_SID", "c00617f9-d1e2-46f2-ac65-fc6a06630726")
    monkeypatch.setenv("ROOT_AUDIT_BRIDGE_SUITE_SID", "1f872452-53df-45c6-88ea-ea3d39db1404")
    sid, src = resolve_bridge_suite_sid_with_source()
    assert sid == "c00617f9-d1e2-46f2-ac65-fc6a06630726"
    assert src == "STAGE1_BRIDGE_SUITE_SID"
    assert resolve_bridge_suite_sid() == sid


def test_conflicting_explicit_values_fail_in_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGE1_BRIDGE_SUITE_SID", "aaaaaaaa-1111-1111-1111-111111111111")
    monkeypatch.setenv("ROOT_AUDIT_BRIDGE_SUITE_SID", "bbbbbbbb-2222-2222-2222-222222222222")
    monkeypatch.setenv("STAGE1_BRIDGE_SID_STRICT", "1")
    with pytest.raises(BridgeSuiteSidConflictError):
        resolve_bridge_suite_sid_with_source()


def test_stage1_still_wins_when_root_differs_without_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGE1_BRIDGE_SUITE_SID", "c00617f9-d1e2-46f2-ac65-fc6a06630726")
    monkeypatch.setenv("ROOT_AUDIT_BRIDGE_SUITE_SID", "1f872452-53df-45c6-88ea-ea3d39db1404")
    sid, src = resolve_bridge_suite_sid_with_source()
    assert sid.startswith("c00617f9")
    assert src == "STAGE1_BRIDGE_SUITE_SID"


def test_root_audit_used_when_stage1_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROOT_AUDIT_BRIDGE_SUITE_SID", "1f872452-53df-45c6-88ea-ea3d39db1404")
    sid, src = resolve_bridge_suite_sid_with_source()
    assert sid.startswith("1f872452")
    assert src == "ROOT_AUDIT_BRIDGE_SUITE_SID"
