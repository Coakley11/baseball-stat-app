"""Unit tests for RV1 same-session production room setup (diag-only)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_solo_rv_production_room_setup import ensure_rv1_production_solo_room


def test_ensure_rv1_fails_closed_on_setup_validation() -> None:
    st = MagicMock()
    session: dict = {"_solo_rv_run_id": "run-x", "_solo_rv_ladder_step": "RV1"}
    with patch(
        "live_draft_start_setup.fail_closed_setup_check",
        return_value={"ok": False, "error": "bad roster"},
    ):
        result = ensure_rv1_production_solo_room(st, session, probe_placeholder=None)
    assert not result.get("ok")
    assert "INVALID_RV_PRODUCTION_ROOM_CREATION_" in str(result.get("invalid", ""))


def test_ensure_rv1_creates_and_starts_room() -> None:
    st = MagicMock()
    session: dict = {
        "_solo_rv_run_id": "run-y",
        "_solo_rv_ladder_step": "RV1",
        "live_draft_team_count": 2,
        "live_draft_picks_per_team": 4,
        "live_slot_c": 1,
        "live_slot_1b": 1,
        "live_slot_2b": 1,
        "live_slot_3b": 1,
        "live_slot_ss": 1,
        "live_slot_of": 3,
        "live_slot_dh": 1,
        "live_slot_p": 0,
        "live_slot_bench": 5,
    }
    pool = pd.DataFrame({"Player": [f"P{i}" for i in range(500)], "fullName": [f"P{i}" for i in range(500)]})
    room = {
        "draft_room_id": "TEST1234",
        "status": "not_started",
        "pick_order": ["A", "B"],
        "current_pick_index": 0,
        "config": {"timer_seconds": 10},
    }

    def _start(r: dict) -> None:
        r["status"] = "in_progress"
        r["timer_deadline"] = 99999.0

    with patch("live_draft_start_setup.fail_closed_setup_check") as chk:
        chk.return_value = {
            "ok": True,
            "slots_for_room": {
                "C": 1,
                "1B": 1,
                "2B": 1,
                "3B": 1,
                "SS": 1,
                "OF": 3,
                "DH": 1,
                "P": 0,
                "BN": 5,
            },
        }
        with patch("streamlit_app.load_fantasypros_market_data", return_value=pool):
            with patch("streamlit_app.live_draft_init_room", return_value=room):
                with patch("streamlit_app.live_draft_start", side_effect=_start):
                    with patch("live_draft_fast_solo_start.build_fast_market_pool", return_value=pool):
                        result = ensure_rv1_production_solo_room(st, session, probe_placeholder=None)
    assert result.get("ok")
    assert result.get("room_id") == "TEST1234"
    assert session.get("live_draft_room") is room
    assert session.get("_solo_rv_room_state_source") == "same_session_production_create"
