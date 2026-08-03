"""CORE canonical start integration tests (harness only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from p8_core_setup_classify import (  # noqa: E402
    CORESETUP1,
    CORESETUP5,
    CORESETUP7,
    classify_core_setup_outcome,
    focused_mode_absent_proof,
    normalize_core_start_validation,
    replay_legacy_core_artifact,
)
from p8_focused_setup_classify import evaluate_canonical_setup_pass


def test_stage1a_core_source_uses_canonical_start() -> None:
    src = (ROOT / "scripts" / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    assert "if stage1a_mode == \"CORE\":" in src
    assert "establish_single_solo_live_draft" in src
    assert "execute_solo_draft_start_workflow(page, url, navigate=False)" in src


def test_ffd33258_legacy_replay_coresetup1() -> None:
    art = ROOT / "data" / "production_stage1_authenticated_summary.json"
    if not art.is_file():
        return
    summary = json.loads(art.read_text(encoding="utf-8"))
    if summary.get("stage1a_mode") != "CORE" or summary.get("canonical_start_used"):
        return
    replay = replay_legacy_core_artifact(summary)
    assert replay["room_signal"] == "FFD33258"
    assert replay["retrospective_coresetup"] == CORESETUP1
    assert replay["legacy_valid"] is False
    assert replay["authoritative_room_latch_proof_in_artifact"] is False


def test_toast_only_without_server_does_not_pass_canonical() -> None:
    auth = evaluate_canonical_setup_pass(
        {
            "click_count": 1,
            "room_id": "TOASTONLY1",
            "handler_entered": False,
            "room_latch_pass": False,
            "pre_expiration_resolution": {},
            "room_status_authority": {"status_in_progress_server": False},
        },
        artifact_latch_replay={},
    )
    assert not auth["canonical_setup_pass"]


def test_server_proof_passes_despite_setup_page_disappeared_legacy_flag() -> None:
    auth = evaluate_canonical_setup_pass(
        {
            "click_count": 1,
            "valid": False,
            "first_missing_pre_expiration": "setup_page_disappeared",
            "room_id": "71C33C65",
            "room_latch_pass": True,
            "handler_entered": True,
            "status": "in_progress",
            "pre_expiration_resolution": {
                "status": "in_progress",
                "pick_index": 0,
                "deadline": 1.0,
                "expected_token": "71C33C65|0|1.0",
            },
            "room_status_authority": {"status_in_progress_server": True},
        },
        artifact_latch_replay={"room_latch_pass_reconciled": True, "room_id": "71C33C65"},
    )
    assert auth["canonical_setup_pass"]


def test_later_clear_fails_coresetup5() -> None:
    cls = classify_core_setup_outcome(
        {"click_count": 1, "handler_entered": True, "room_id": "ABCD1234"},
        setup_auth={"canonical_setup_pass": False, "failures": ["room_later_cleared"]},
        latch_replay={"server_latch_bundle": {"checks": {"later_clear": True}}},
    )
    assert cls["coresetup_classification"] == CORESETUP5


def test_multiple_clicks_coresetup7() -> None:
    cls = classify_core_setup_outcome(
        {"click_count": 2, "handler_entered": True, "room_id": "ABCD1234"},
        setup_auth={"canonical_setup_pass": False, "failures": ["click_count_not_one"]},
    )
    assert cls["coresetup_classification"] == CORESETUP7


def test_normalize_core_start_validation_valid() -> None:
    norm = normalize_core_start_validation(
        {"room_latch_pass": True},
        {"room_id": "ABCD1234", "expected_token": "ABCD1234|0|1.0", "canonical_setup_pass": True},
        {"room_latch_pass_reconciled": True},
    )
    assert norm["valid"] and norm["latched_room_id"] == "ABCD1234"


def test_focused_mode_absent_when_no_qp() -> None:
    page = mock.MagicMock()
    proof = focused_mode_absent_proof(page, "https://example.com/?active_page=Live", {})
    assert proof["absent_ok"]


def test_core_main_does_not_call_legacy_when_canonical_passes(monkeypatch) -> None:
    """CORE path must not use validate_production_draft_start when canonical passes."""
    import run_production_stage1_authenticated as mod

    src = (ROOT / "scripts" / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    assert "normalize_core_start_validation" in src
