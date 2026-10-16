"""League setup integrity: button clicks survive the ephemeral-key cleanup, lineup format
keeps Utility, open lineup spots point at the roster before the waiver wire, the draft
banner reads progress from the board, and a new local workspace can save."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import page_state
from draft_import_pipeline import imported_league_saved_flash
from fantasy_league_context import resolve_context_lineup_slots
from fantasy_league_lineup_format import apply_lineup_format_to_context
from fantasy_lineup_ui import build_slot_key_labels
from fantasy_weekly_lineup import resolve_weekly_lineup_slots
from fantasy_weekly_lineup_ui import build_open_slot_prompts

ROOT = Path(__file__).resolve().parents[1]


class ButtonClickSurvivesEphemeralCleanupTests(unittest.TestCase):
    """The run-level cleanup used to pop every *_btn key, deleting the pending click."""

    SCRIPT = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, {root!r})
        import streamlit as st
        import page_state
        st.session_state.setdefault("clicks", 0)
        page_state.purge_restored_ephemeral_widget_keys(st.session_state)
        if st.button("Save", key="lineup_format_save_btn"):
            st.session_state["clicks"] += 1
        """
    )

    def test_keyed_button_rendered_after_cleanup_fires(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_string(self.SCRIPT.format(root=str(ROOT))).run()
        for expected in (1, 2):
            at.button(key="lineup_format_save_btn").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["clicks"], expected)

    def test_restored_button_value_is_still_dropped(self):
        from streamlit.testing.v1 import AppTest

        script = self.SCRIPT.replace(
            "page_state.purge_restored_ephemeral_widget_keys",
            "st.session_state['lineup_format_save_btn'] = True  # snapshot restore\n"
            "page_state.purge_restored_ephemeral_widget_keys",
        )
        at = AppTest.from_string(script.format(root=str(ROOT))).run()
        self.assertFalse(at.exception)  # st.button would refuse an assigned value

    def test_app_uses_the_narrow_cleanup(self):
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("pg_state.purge_restored_ephemeral_widget_keys(st.session_state)", src)
        self.assertNotIn("st.session_state.pop(_ephemeral_key, None)", src)


class PurgeRulesTests(unittest.TestCase):
    def test_only_assigned_ephemeral_keys_are_dropped(self):
        session = {
            "lineup_format_save_btn": True,   # assigned (restored) → drop
            "waiver_confirm_button": False,   # live widget → keep
            "draft_room_import_uploader": [],  # uploader → never touched
            "lineup_team": "Team 1",          # not ephemeral → keep
        }
        assigned = {"lineup_format_save_btn", "draft_room_import_uploader", "lineup_team"}
        dropped = page_state.purge_restored_ephemeral_widget_keys(session, is_assigned=assigned.__contains__)
        self.assertEqual(dropped, ["lineup_format_save_btn"])
        self.assertEqual(set(session), {"waiver_confirm_button", "draft_room_import_uploader", "lineup_team"})

    def test_unknown_assignment_state_keeps_the_old_safe_behavior(self):
        with mock.patch("streamlit.runtime.state.get_session_state", side_effect=RuntimeError):
            self.assertTrue(page_state._assigned_through_session_api("x_btn"))


STANDARD = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]


class LineupFormatKeepsUtilityTests(unittest.TestCase):
    def test_utility_survives_into_roster_slots_and_weekly_lineup(self):
        ctx = apply_lineup_format_to_context(
            {"league_context_id": "ctx:qa", "context_type": "real_league"},
            lineup_slots=STANDARD,
            roster_capacity=10,
            configured_by="qa",
            configuration_source="uploaded",
        )
        self.assertEqual(ctx["roster_settings"]["roster_slots"]["DH"], 1)
        self.assertEqual(ctx["roster_settings"]["lineup_format"]["lineup_slots"], STANDARD)
        self.assertEqual(resolve_context_lineup_slots(ctx), STANDARD)
        self.assertEqual(resolve_weekly_lineup_slots(ctx), STANDARD)


def _roster(*players: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame([{"Player": n, "Primary Position": p} for n, p in players])


class OpenSlotPromptsUseTheRosterTests(unittest.TestCase):
    def setUp(self):
        self.labels = build_slot_key_labels(["C", "SS", "OF", "OF", "UTIL"])

    def test_rostered_player_means_start_them_not_waivers(self):
        roster = _roster(("Cal Raleigh", "C"), ("Willy Adames", "SS"), ("A", "OF"), ("B", "OF"), ("Jose Ramirez", "3B"))
        rows = build_open_slot_prompts(self.labels, {}, roster)
        self.assertEqual(
            [r["text"] for r in rows],
            [
                "Catcher open — start someone from your roster",
                "Shortstop open — start someone from your roster",
                "Utility open — start someone from your roster",
                "2 outfield spots open — start someone from your roster",
            ],
        )
        self.assertTrue(all(r["button_label"] == "" for r in rows))

    def test_waiver_prompt_only_when_nobody_on_the_roster_fits(self):
        roster = _roster(("Cal Raleigh", "C"), ("A", "OF"))
        rows = {r["position_code"]: r for r in build_open_slot_prompts(self.labels, {"C": "Cal Raleigh"}, roster)}
        self.assertNotIn("C", rows)  # filled
        self.assertEqual(rows["SS"]["text"], "Missing shortstop")
        self.assertEqual(rows["SS"]["button_label"], "Open Waiver Wire for Shortstops")
        self.assertEqual(rows["OF"]["text"], "Missing 1 outfielder — your roster covers 1 of the 2 open spots")
        self.assertTrue(rows["OF"]["button_label"])

    def test_players_already_in_the_lineup_do_not_count(self):
        roster = _roster(("Cal Raleigh", "C"))
        rows = build_open_slot_prompts(build_slot_key_labels(["C", "UTIL"]), {"C": "Cal Raleigh"}, roster)
        self.assertEqual([r["text"] for r in rows], ["Missing utility player"])


def _snake_board(teams: list[str], rounds: int, filled: int) -> pd.DataFrame:
    rows = []
    for rnd in range(1, rounds + 1):
        order = teams if rnd % 2 else list(reversed(teams))
        for team in order:
            pick = len(rows) + 1
            rows.append({"Pick": pick, "Round": rnd, "Team": team, "Player": f"Player {pick}" if pick <= filled else ""})
    return pd.DataFrame(rows)


class DraftBannerProgressTests(unittest.TestCase):
    def _status(self, board: pd.DataFrame, **extra) -> dict:
        from draft_room_state import get_active_draft_status

        return get_active_draft_status({"draft_room_table": board, "room_your_team": "Team 1", **extra})

    def test_complete_imported_board_reads_complete_despite_other_team_count(self):
        status = self._status(_snake_board(["Team 1", "Team 2", "Team 3", "Team 4"], 10, 40), room_team_count=12)
        self.assertTrue(status.get("draft_complete"))

    def test_partial_board_round_uses_the_boards_own_team_count(self):
        status = self._status(_snake_board(["Team 1", "Team 2", "Team 3", "Team 4"], 10, 9), room_team_count=12)
        self.assertFalse(status.get("draft_complete"))
        self.assertEqual(status.get("current_pick"), 10)
        self.assertEqual(status.get("current_round"), 3)

    def test_banner_says_draft_complete(self):
        from draft_room_state import render_active_draft_banner

        st = mock.MagicMock()
        st.sidebar.columns.return_value = (mock.MagicMock(), mock.MagicMock())
        st.button.return_value = False
        with mock.patch(
            "draft_room_state.get_active_draft_status",
            return_value={"active": True, "mode": "simulator", "pick_count": 40, "draft_complete": True,
                          "current_round": 11, "current_pick": 41},
        ):
            render_active_draft_banner(st, {})
        shown = " ".join(str(c.args[0]) for c in st.info.call_args_list if c.args)
        self.assertIn("Draft complete", shown)
        self.assertNotIn("Round **11**", shown)


class ImportedLeagueFlashTests(unittest.TestCase):
    def test_lone_saved_draft_is_called_the_active_league(self):
        msg = imported_league_saved_flash("QA League", "Team 1", saved_count=1, persisted=True)
        self.assertIn("now your **Active League**", msg)
        self.assertNotIn("not active", msg)

    def test_with_other_drafts_points_to_set_active(self):
        msg = imported_league_saved_flash("QA League", "Team 1", saved_count=3, persisted=False)
        self.assertIn("in this session", msg)
        self.assertIn("**Set Active**", msg)


class _FakeSt:
    def __init__(self):
        self.session_state: dict = {}


class NewLocalWorkspaceCanSaveTests(unittest.TestCase):
    def _sync(self, *, cloud_disabled: bool) -> dict:
        import suite_user_persistence as sup

        st = _FakeSt()
        with mock.patch.object(sup, "_cloud_storage_disabled", return_value=cloud_disabled), mock.patch.object(
            sup, "_load_raw", return_value=({}, None, None)
        ), mock.patch("suite_cloud_state.load_cloud_full_session", return_value=({}, None)), mock.patch(
            "suite_cloud_state.reconcile_stale_resume_session_flags", return_value=None
        ), mock.patch("suite_cloud_state.should_skip_workspace_restore_for_resume", return_value=False), mock.patch.object(
            sup, "record_page_navigation_startup_diagnostics"
        ), mock.patch.object(sup, "_record_workspace_sync_trace"), mock.patch.object(
            sup, "_record_startup_restore_diagnostics"
        ):
            applied = sup.sync_workspace_protocol(st, "baseball", apply_state=lambda *_: None)
        self.assertFalse(applied)
        self.assertEqual(st.session_state.get("_suite_persist_restore_skip_reason"), "no workspace blob")
        return st.session_state

    def test_local_empty_workspace_does_not_block_autosave(self):
        import suite_user_persistence as sup

        state = self._sync(cloud_disabled=True)
        self.assertNotIn(sup._autosave_block_key("baseball"), state)

    def test_cloud_empty_read_still_blocks_autosave(self):
        import suite_user_persistence as sup

        state = self._sync(cloud_disabled=False)
        self.assertTrue(state.get(sup._autosave_block_key("baseball")))


class LineupDiagnosisRosterTests(unittest.TestCase):
    def test_team_rows_exist_before_the_cached_diagnosis_branch(self):
        src = (ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        self.assertLess(src.index("_my_team_df = ("), src.index("if isinstance(_cached_diag, dict):"))


if __name__ == "__main__":
    unittest.main()
