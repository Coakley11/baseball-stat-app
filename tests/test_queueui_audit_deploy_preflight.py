"""Cloud build preflight for QUEUEUI root audit."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from queueui_audit_deploy_preflight import (  # noqa: E402
    QUEUEUIAUDIT_DEPLOY_BLOCK,
    verify_cloud_build_for_audit,
)


def test_preflight_pass_exact_match() -> None:
    r = verify_cloud_build_for_audit(live_sha="4359938", required_sha="4359938")
    assert r["passed"] is True


def test_preflight_blocks_stale_cloud() -> None:
    r = verify_cloud_build_for_audit(live_sha="007c39a", required_sha="4359938")
    assert r["passed"] is False
    assert r["audit_execution_status"] == "NOT_RUN"
    assert r["first_boundary"] == QUEUEUIAUDIT_DEPLOY_BLOCK


def test_preflight_no_root_on_block() -> None:
    r = verify_cloud_build_for_audit(live_sha="007c39a", required_sha="4359938")
    assert "QUEUEUIROOT" not in str(r.get("first_boundary") or "")
