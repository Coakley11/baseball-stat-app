"""Solo Live Draft Start Draft click-path regression tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from fantasy_roster_validation import LIVE_DRAFT_SETUP_ERROR
from live_draft_start_setup import (
    SETUP_VALIDATION_ERROR_KEY,
    clear_setup_validation_error,
    evaluate_live_draft_start_setup,
    peek_setup_validation_error,
    record_start_path_diagnostics,
    store_setup_validation_error,
)


def _five_starters() -> dict[str, int]:
    return {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 0, "DH": 0, "P": 0, "BN": 0}


def _tiny_pool(n: int = 40) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF"][i % 6],
                "Expected Fantasy Value": float(100 - i),
                "Model Rank": i + 1,
                "Market Rank": i + 1,
            }
        )
    return pd.DataFrame(rows)


def _solo_start_room(*, picks: int, slots: dict[str, int], teams: list[str] | None = None):
    """Mirror the Solo start path after validation (no Streamlit / shared room)."""
    check = evaluate_live_draft_start_setup(
        {},
        picks_per_team=picks,
        slots=slots,
        solo_mode=True,
    )
    if not check.get("ok"):
        return {"ok": False, "error": check.get("error"), "room": None, "check": check}

    from streamlit_app import live_draft_init_room, live_draft_start

    teams = teams or ["Team A", "Team B"]
    config = {
        "league_name": "Test League",
        "num_teams": len(teams),
        "picks_per_team": picks,
        "teams": teams,
        "user_team": teams[0],
        "your_team": teams[0],
        "slots": dict(check.get("slots_for_room") or slots),
        "timer_seconds": 60,
        "scoring_type": "Roto (5x5)",
        "fantasy_format": "5x5 Roto",
    }
    from live_draft_roster_slots import freeze_slot_instances_on_config

    config = freeze_slot_instances_on_config(config)
    room = live_draft_init_room(config, _tiny_pool())
    live_draft_start(room)
    return {"ok": True, "error": "", "room": room, "check": check}


class SoloStartValidationTests(unittest.TestCase):
    def test_five_required_four_picks_blocks_with_exact_message(self) -> None:
        check = evaluate_live_draft_start_setup(
            {"live_draft_picks_per_team": 4},
            picks_per_team=4,
            slots=_five_starters(),
            solo_mode=True,
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["error"], LIVE_DRAFT_SETUP_ERROR)
        result = _solo_start_room(picks=4, slots=_five_starters())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], LIVE_DRAFT_SETUP_ERROR)
        self.assertIsNone(result["room"])

    def test_five_required_five_picks_starts_with_timer_and_on_clock(self) -> None:
        result = _solo_start_room(picks=5, slots=_five_starters())
        self.assertTrue(result["ok"], result.get("error"))
        room = result["room"]
        assert room is not None
        self.assertEqual(room.get("status"), "in_progress")
        self.assertEqual(int(room.get("current_pick_index") or 0), 0)
        self.assertIsNotNone(room.get("timer_deadline"))
        pick_order = room.get("pick_order") or []
        self.assertGreaterEqual(len(pick_order), 1)
        self.assertEqual(str((pick_order[0] or {}).get("Team") or ""), "Team A")

    def test_five_required_eight_picks_starts_with_bench_extras(self) -> None:
        result = _solo_start_room(picks=8, slots=_five_starters())
        self.assertTrue(result["ok"], result.get("error"))
        room = result["room"]
        assert room is not None
        slots = (room.get("config") or {}).get("slots") or {}
        self.assertEqual(int(slots.get("BN") or 0), 3)
        self.assertEqual(int(slots.get("C") or 0), 1)
        # 2 teams × 8 picks remain available on the board order.
        self.assertEqual(len(room.get("pick_order") or []), 16)

    def test_bench_not_counted_as_required_starters(self) -> None:
        slots = {**_five_starters(), "BN": 10}
        check = evaluate_live_draft_start_setup({}, picks_per_team=5, slots=slots)
        self.assertTrue(check["ok"])
        self.assertEqual(check["required_starting_positions"], 5)
        self.assertEqual(check["bench_slots"], 10)

    def test_validation_failure_persists_for_rerun_display(self) -> None:
        session: dict = {
            "live_draft_picks_per_team": 4,
            "live_slot_c": 1,
            "live_slot_1b": 1,
            "live_slot_2b": 1,
            "live_slot_3b": 1,
            "live_slot_ss": 1,
            "live_slot_of": 0,
            "live_slot_dh": 0,
            "live_slot_p": 0,
            "live_slot_bench": 0,
        }
        check = evaluate_live_draft_start_setup(session, picks_per_team=4, slots=_five_starters())
        self.assertFalse(check["ok"])
        store_setup_validation_error(session, check["error"])
        # Simulate Streamlit rerun: error must still be readable near Start controls.
        self.assertEqual(peek_setup_validation_error(session), LIVE_DRAFT_SETUP_ERROR)
        self.assertEqual(session.get(SETUP_VALIDATION_ERROR_KEY), LIVE_DRAFT_SETUP_ERROR)
        # Setup selections remain.
        self.assertEqual(session["live_draft_picks_per_team"], 4)
        self.assertEqual(session["live_slot_c"], 1)

    def test_start_cannot_fail_silently_records_diagnostics(self) -> None:
        session: dict = {}
        record_start_path_diagnostics(
            session,
            button_clicked=True,
            validation_ok=False,
            validation_error=LIVE_DRAFT_SETUP_ERROR,
            draft_creation_attempted=False,
            final_status="setup_validation_blocked",
        )
        diag = session.get("_live_draft_start_path_diag") or {}
        self.assertTrue(diag.get("button_clicked"))
        self.assertFalse(diag.get("validation_ok"))
        self.assertEqual(diag.get("validation_error"), LIVE_DRAFT_SETUP_ERROR)
        self.assertEqual(diag.get("final_status"), "setup_validation_blocked")

    def test_validation_failure_does_not_clear_setup_selections(self) -> None:
        session = {
            "live_draft_picks_per_team": 4,
            "live_draft_team_count": 2,
            "live_slot_c": 1,
            "live_slot_1b": 1,
            "live_slot_2b": 1,
            "live_slot_3b": 1,
            "live_slot_ss": 1,
            "live_draft_league_name": "Keep Me",
        }
        check = evaluate_live_draft_start_setup(session, picks_per_team=4, slots=_five_starters())
        store_setup_validation_error(session, check["error"])
        self.assertEqual(session["live_draft_league_name"], "Keep Me")
        self.assertEqual(session["live_draft_team_count"], 2)
        self.assertEqual(session["live_slot_ss"], 1)

    def test_solo_start_does_not_require_shared_room(self) -> None:
        result = _solo_start_room(picks=5, slots=_five_starters())
        self.assertTrue(result["ok"])
        room = result["room"]
        assert room is not None
        self.assertFalse(bool(room.get("room_code")))
        self.assertNotIn("active_shared_draft_room_code", room)

    def test_shared_live_draft_still_uses_same_setup_gate(self) -> None:
        # Shared create uses the same picks/slots gate before room create.
        check = evaluate_live_draft_start_setup(
            {},
            picks_per_team=4,
            slots=_five_starters(),
            solo_mode=False,
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["error"], LIVE_DRAFT_SETUP_ERROR)

    def test_simulator_and_uploaded_skip_live_setup_validation(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        lab = (root / "streamlit_app.py").read_text(encoding="utf-8")
        start = lab.find("def simulate_draft_lab")
        self.assertGreater(start, 0)
        self.assertNotIn("evaluate_live_draft_start_setup", lab[start : start + 2500])
        self.assertNotIn("validate_live_draft_setup", lab[start : start + 2500])
        import draft_import_pipeline

        import_src = Path(draft_import_pipeline.__file__).read_text(encoding="utf-8")
        self.assertNotIn("evaluate_live_draft_start_setup", import_src)
        self.assertNotIn("validate_live_draft_setup", import_src)

    def test_clear_error_after_successful_evaluation(self) -> None:
        session = {SETUP_VALIDATION_ERROR_KEY: LIVE_DRAFT_SETUP_ERROR}
        check = evaluate_live_draft_start_setup({}, picks_per_team=5, slots=_five_starters())
        self.assertTrue(check["ok"])
        clear_setup_validation_error(session)
        self.assertEqual(peek_setup_validation_error(session), "")

    def test_admin_diagnostics_hidden_without_developer_tools(self) -> None:
        from live_draft_start_setup import render_start_path_diagnostics

        st = MagicMock()
        session = {"_live_draft_start_path_diag": {"button_clicked": True}}
        with patch(
            "suite_workspace.can_show_developer_tools", return_value=False
        ):
            render_start_path_diagnostics(st, session)
        st.sidebar.expander.assert_not_called()


if __name__ == "__main__":
    unittest.main()
