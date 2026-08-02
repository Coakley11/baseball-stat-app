"""Tests for durable production callback handoff (VALUE9 transport)."""

from __future__ import annotations

from unittest import mock

from live_draft_prod_callback_handoff import (
    coalesce_expiration_token_candidates,
    get_handoff_record,
    handoff_storage_key,
    mark_handoff_terminal,
    write_callback_handoff_from_on_change,
)
from live_draft_stage1_post_bind_flush import evaluate_bound_token_gate


def test_callback_writes_handoff_with_exact_token() -> None:
    st = mock.MagicMock()
    st.session_state = {"solo_countdown_wake_solo_persistent": "ROOM|0|100.0"}
    session: dict = {"_solo_stage1_script_run_seq": 4, "_solo_stage1_run_id": "run1"}
    token = "ROOM|0|100.0"
    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=False,
    ):
        rec = write_callback_handoff_from_on_change(
            st,
            session,
            widget_key="solo_countdown_wake_solo_persistent",
            raw_value="ROOM|0|100.0",
            expected_token=token,
            callback_invocation_id="inv1",
            production_room={"draft_room_id": "ROOM", "current_pick_index": 0},
        )
    assert rec is not None
    assert rec["raw_token"] == token
    assert get_handoff_record(session, "solo_countdown_wake_solo_persistent")["raw_token"] == token


def test_coalesce_prefers_exact_handoff_when_direct_empty() -> None:
    expected = "ROOM|0|100.0"
    sel, surface, decision = coalesce_expiration_token_candidates(
        expected_token=expected,
        direct_raw="",
        session_state_raw="",
        cache_raw="",
        handoff_raw=expected,
    )
    assert sel == expected
    assert surface == "durable_callback_handoff"
    assert decision == "pass_exact_token"


def test_coalesce_rejects_conflicting_exact_matches() -> None:
    sel, surface, decision = coalesce_expiration_token_candidates(
        expected_token="ROOM|0|100.0",
        direct_raw="ROOM|0|100.0",
        session_state_raw="",
        cache_raw="ROOM|0|100.0",
        handoff_raw="ROOM|0|99.0",
    )
    assert sel == "ROOM|0|100.0"
    assert decision == "pass_exact_token"


def test_gate_passes_durable_handoff_when_session_empty() -> None:
    st = mock.MagicMock()
    st.session_state = {}
    session: dict = {
        "_solo_stage1_script_run_seq": 2,
        handoff_storage_key("solo_countdown_wake_solo_persistent"): {
            "raw_token": "ROOM|0|100.0",
            "widget_user_key": "solo_countdown_wake_solo_persistent",
            "room_id": "ROOM",
            "pick_index": 0,
            "deadline": 100.0,
            "status": "pending",
            "created_ts": 99.0,
            "deployment_sha": "abc1234",
            "declaration_fingerprint": "",
        },
        "live_draft_room": {"draft_room_id": "ROOM", "current_pick_index": 0, "status": "in_progress"},
    }
    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=False,
    ), mock.patch(
        "live_draft_stage1_post_bind_flush.deployment_sha_for_session",
        return_value="abc1234",
    ), mock.patch("live_draft_prod_callback_handoff.time.time", return_value=100.0):
        gate = evaluate_bound_token_gate(
            st,
            session,
            expected_expiration_token="ROOM|0|100.0",
            mount_expire_token="ROOM|0|100.0",
            raw_component_return=None,
            session_state_value=None,
            widget_key="solo_countdown_wake_solo_persistent",
        )
    assert gate.passed is True
    assert gate.selected_bound_token == "ROOM|0|100.0"
    assert gate.candidate_source == "durable_callback_handoff"


def test_terminal_mark_does_not_clear_newer_token() -> None:
    session: dict = {
        handoff_storage_key("k"): {
            "raw_token": "ROOM|1|200.0",
            "status": "pending",
            "created_ts": 2.0,
        }
    }
    with mock.patch(
        "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
        return_value=False,
    ):
        mark_handoff_terminal(session, "k", raw_token="ROOM|0|100.0", reason="stale")
    assert session[handoff_storage_key("k")]["raw_token"] == "ROOM|1|200.0"


def test_prod_on_change_source_has_no_try_claim() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("solo_countdown_wake_micro_core.py").read_text(
        encoding="utf-8"
    )
    block = src.split("def _prod_on_change", 1)[1].split("\n        if production_delivery_only", 1)[0]
    assert "try_claim_token_delivery" not in block
    assert "process_production_expire_token" not in block
