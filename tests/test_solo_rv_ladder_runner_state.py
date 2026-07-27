"""Unit tests for runner-only RV1 ladder state classification."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from live_draft_solo_rv_control_probe import RV_LEDGER_B64_PREFIX
from solo_rv_ladder_runner_state import (
    classify_page_shell,
    classify_rv1_ledger_after_ready,
    filter_timeline_after_epoch,
    ledger_ready,
    page_state_to_invalid_reason,
    should_begin_instrumentation_epoch,
    verify_rv1_control_url,
)


def _row(event: str, **kwargs):
    return {"event": event, **kwargs}


def test_empty_ledger_prevents_instrumentation_epoch() -> None:
    ok, verdict, reason = should_begin_instrumentation_epoch(
        page_state="READY_PENDING",
        rows=[],
        harness_room_id="ABCD1234",
    )
    assert not ok
    assert verdict == "INVALID"
    assert reason == "INVALID_RV_CONTROL_PAGE_NOT_OBSERVED"


def test_app_error_classified() -> None:
    state = classify_page_shell(
        page_text="Traceback most recent call",
        dom={"has_st_exception": True, "has_streamlit_app": True},
        rows=[],
    )
    assert state == "APP_ERROR"
    assert page_state_to_invalid_reason(state) == "INVALID_RV_CONTROL_APP_ERROR"


def test_auth_lost_classified() -> None:
    state = classify_page_shell(
        page_text="Not signed in. Please sign in.",
        dom={"has_login": True, "has_streamlit_app": True},
        rows=[],
    )
    assert state == "AUTH_LOST"


def test_route_not_entered_classified() -> None:
    state = classify_page_shell(
        page_text="Live Draft Room\nPause Draft\nDraft board",
        dom={"has_streamlit_app": True, "has_live_draft_heading": True},
        rows=[],
    )
    assert state == "ROUTE_NOT_ENTERED"


def test_hydration_failure_distinct_from_declaration_failure() -> None:
    _, v1, r1 = classify_rv1_ledger_after_ready(
        [
            _row("script_begin"),
            _row("rv_entrypoint_entered"),
            _row("rv_real_room_hydration_failed", extra={"reason": "room_not_in_session"}),
        ],
        harness_room_id="ABCD1234",
    )
    assert v1 == "INVALID"
    assert r1 == "INVALID_RV_REAL_ROOM_HYDRATION_room_not_in_session"

    _, v2, r2 = classify_rv1_ledger_after_ready(
        [
            _row("real_room_hydrated", room_id="ABCD1234", pick_index=0, deadline=1.0, expected_token="ABCD1234|0|1.0"),
        ],
        harness_room_id="ABCD1234",
    )
    assert v2 == "INVALID"
    assert "INVALID_RV_PRODUCTION_ROOM_CREATION_missing" in r2


def test_ready_hydrated_allows_epoch() -> None:
    rows = [
        _row("script_begin"),
        _row("rv_entrypoint_entered"),
        _row("production_room_creation_attempted"),
        _row(
            "production_room_created",
            room_id="ABCD1234",
            extra={"creation_event_id": "c1", "room_fingerprint": "fp1"},
        ),
        _row("production_draft_started", room_id="ABCD1234", extra={"draft_start_event_id": "s1"}),
        _row("production_setup_owner_established", room_id="ABCD1234", extra={"room_fingerprint": "fp1"}),
        _row("production_room_reused", room_id="ABCD1234", script_run_seq=2),
        _row("real_room_hydrated", room_id="ABCD1234", pick_index=0, deadline=99.0, expected_token="ABCD1234|0|99.0"),
        _row("room_state_source", extra={"room_state_source": "same_session_production_create"}),
        _row("declaration_attempt", expected_token="ABCD1234|0|99.0", script_run_seq=2),
        _row("declaration_returned", expected_token="ABCD1234|0|99.0", script_run_seq=2),
    ]
    text = RV_LEDGER_B64_PREFIX + "e30="
    assert ledger_ready(rows, page_text=text)
    ok, verdict, reason = should_begin_instrumentation_epoch(
        page_state="READY",
        rows=rows,
        harness_room_id="ABCD1234",
    )
    assert ok
    assert verdict == ""


def test_filter_timeline_excludes_pre_navigation() -> None:
    timeline = [{"ts": 100.0, "stage": "timer_armed"}, {"ts": 5000.0, "stage": "timer_armed"}]
    out = filter_timeline_after_epoch(timeline, 4000.0)
    assert len(out) == 1
    assert out[0]["ts"] == 5000.0


def test_verify_rv1_control_url() -> None:
    url = (
        "https://example.test/?active_page=Live+Draft+Room&solo_rv_ladder=RV1"
        "&solo_rv_run_id=run-1"
        "&solo_delivery_diag=1&solo_component_diag=1&solo_diag_timer=10&suite_sid=secret"
    )
    v = verify_rv1_control_url(url, run_id="run-1")
    assert v["ok"]
