"""Replay run 55e14bce — canonical setup authority (harness only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from p8_focused_setup_classify import (  # noqa: E402
    SETUPTRACE1,
    CANONICAL_SETUP_PASS,
    evaluate_canonical_setup_pass,
    classify_focused_setup_boundary,
    legacy_abort_would_fire,
)


def _load_55e14bce() -> dict:
    art = ROOT / "data" / "production_p8_binding_diagnostic.json"
    if not art.is_file():
        return {}
    raw = json.loads(art.read_text(encoding="utf-8"))
    if raw.get("harness_run_id") != "55e14bcebec84a75":
        return {}
    return raw


def test_55e14bce_replay_canonical_setup_pass() -> None:
    raw = _load_55e14bce()
    if not raw:
        return
    start = dict(raw.get("production_setup") or {})
    latch = dict(raw.get("artifact_latch_replay") or {})
    auth = evaluate_canonical_setup_pass(start, artifact_latch_replay=latch)
    assert auth["canonical_setup_pass"] is True
    assert auth["setup_authority"] == CANONICAL_SETUP_PASS
    assert auth["room_id"] == "35EC1387"
    assert auth["server_in_progress"] is True
    assert auth["room_latch_pass_reconciled"] is True
    assert auth["expected_token"] == "35EC1387|0|1785723093.074"
    assert auth["setuptrace_classification"] == SETUPTRACE1
    cls = classify_focused_setup_boundary(start_result=start)
    assert cls.get("reason") == "setup_pass_server_status"
    assert not (cls.get("focused_p8_outcome") or "").strip()
    assert legacy_abort_would_fire(start_valid=bool(start.get("valid")), setup_cls=cls)


def test_55e14bce_legacy_abort_condition_identified() -> None:
    raw = _load_55e14bce()
    if not raw:
        return
    start = raw.get("production_setup") or {}
    assert start.get("valid") is False
    assert start.get("room_latch_pass") is True
    cls = classify_focused_setup_boundary(start_result=start)
    assert legacy_abort_would_fire(start_valid=False, setup_cls=cls)


def test_canonical_failure_no_room_aborts() -> None:
    auth = evaluate_canonical_setup_pass({"click_count": 1, "room_id": "", "room_latch_pass": False})
    assert not auth["canonical_setup_pass"]
    assert "room_id_missing" in auth["failures"]


def test_canonical_failure_multiple_clicks_aborts() -> None:
    auth = evaluate_canonical_setup_pass(
        {
            "click_count": 2,
            "room_id": "ABCD1234",
            "room_latch_pass": True,
            "handler_entered": True,
            "status": "in_progress",
            "pre_expiration_resolution": {
                "status": "in_progress",
                "pick_index": 0,
                "expected_token": "ABCD1234|0|1.0",
            },
            "room_status_authority": {"status_in_progress_server": True},
        }
    )
    assert not auth["canonical_setup_pass"]
    assert "click_count_not_one" in auth["failures"]


def test_later_clear_aborts() -> None:
    auth = evaluate_canonical_setup_pass(
        {
            "click_count": 1,
            "room_id": "ABCD1234",
            "room_latch_pass": True,
            "handler_entered": True,
            "status": "in_progress",
            "pre_expiration_resolution": {
                "status": "in_progress",
                "pick_index": 0,
                "expected_token": "ABCD1234|0|1.0",
            },
            "room_status_authority": {"status_in_progress_server": True},
        },
        artifact_latch_replay={"server_latch_bundle": {"checks": {"later_clear": True}}},
    )
    assert not auth["canonical_setup_pass"]
    assert "room_later_cleared" in auth["failures"]


def test_legacy_false_flags_do_not_block_canonical_pass() -> None:
    auth = evaluate_canonical_setup_pass(
        {
            "click_count": 1,
            "valid": False,
            "pre_expiration_ready": False,
            "first_missing_pre_expiration": "deadline_already_expired",
            "start_boundary": "START10 — OTHER",
            "room_id": "35EC1387",
            "room_latch_pass": True,
            "handler_entered": True,
            "status": "in_progress",
            "pre_expiration_resolution": {
                "status": "in_progress",
                "pick_index": 0,
                "deadline": 1785723093.0736902,
                "expected_token": "35EC1387|0|1785723093.074",
                "consistency": {"deadline_not_expired": False},
            },
            "room_status_authority": {"status_in_progress_server": True},
        },
        artifact_latch_replay={"room_latch_pass_reconciled": True, "room_id": "35EC1387"},
    )
    assert auth["canonical_setup_pass"]
    assert auth["warnings"]
