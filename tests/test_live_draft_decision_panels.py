"""Tests for roster tracker, category outlook, and leave/return draft navigation."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from live_draft_category_outlook import compute_category_outlook, player_top_category_strengths
from live_draft_navigation import (
    BROWSING_AWAY_KEY,
    FORCE_SYNC_ON_RETURN_KEY,
    apply_force_sync_on_return,
    get_draft_return_context,
    on_browse_other_pages,
    on_return_to_draft_simulator,
    on_return_to_live_draft,
)
from live_draft_roster_tracker import build_roster_checklist, build_team_roster_tracker


def _config() -> dict:
    return {
        "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0},
        "scoring_type": "Roto (5x5)",
    }


def _room(**overrides) -> dict:
    room = {
        "draft_room_id": "ROOMTEST",
        "status": "in_progress",
        "current_pick_index": 2,
        "config": _config(),
        "teams": ["Danny", "Amiel"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Danny"},
            {"Pick": 2, "Round": 1, "Team": "Amiel"},
            {"Pick": 3, "Round": 2, "Team": "Amiel"},
        ],
        "draft_board": [],
        "rosters": {
            "Danny": [
                {"fullName": "Player A", "Primary Position": "C", "proj_HR": 20, "proj_RBI": 70, "proj_SB": 5, "proj_BA": 0.26, "proj_R": 80},
                {"fullName": "Player B", "Primary Position": "1B", "proj_HR": 30, "proj_RBI": 90, "proj_SB": 3, "proj_BA": 0.28, "proj_R": 85},
                {"fullName": "Player C", "Primary Position": "2B", "proj_HR": 15, "proj_RBI": 60, "proj_SB": 10, "proj_BA": 0.27, "proj_R": 75},
                {"fullName": "Player D", "Primary Position": "OF", "proj_HR": 25, "proj_RBI": 80, "proj_SB": 12, "proj_BA": 0.29, "proj_R": 90},
            ],
            "Amiel": [],
        },
        "pool": pd.DataFrame(
            [
                {"fullName": "Pool 1", "Primary Position": "SS", "proj_HR": 22, "proj_RBI": 75, "proj_SB": 15, "proj_BA": 0.27, "proj_R": 85},
            ]
        ),
    }
    room.update(overrides)
    return room


class RosterTrackerTests(unittest.TestCase):
    def test_checklist_marks_filled_and_open_slots(self) -> None:
        roster = pd.DataFrame(_room()["rosters"]["Danny"])
        checklist = build_roster_checklist(roster, _config())
        self.assertEqual(checklist["filled"], 4)
        self.assertGreater(checklist["target"], checklist["filled"])
        labels = [ln["label"] for ln in checklist["lines"] if not ln["filled"]]
        self.assertIn("SS", labels)
        self.assertTrue(any(str(l).startswith("OF") for l in labels))

    def test_tracker_is_team_specific(self) -> None:
        room = _room()
        danny = build_team_roster_tracker(room, "Danny")
        amiel = build_team_roster_tracker(room, "Amiel")
        self.assertGreater(danny["filled"], 0)
        self.assertEqual(amiel["filled"], 0)


class CategoryOutlookTests(unittest.TestCase):
    def test_outlook_returns_bars_and_needs(self) -> None:
        roster = pd.DataFrame(_room()["rosters"]["Danny"])
        pool = pd.DataFrame(_room()["pool"])
        outlook = compute_category_outlook(roster, pool, config=_config(), roster_gaps=["SS", "OF"])
        self.assertTrue(outlook["bars"])
        self.assertTrue(any("SB" == b["category"] or "HR" == b["category"] for b in outlook["bars"]))

    def test_empty_roster_does_not_crash(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "proj_HR": 20,
                    "proj_RBI": 70,
                    "proj_SB": 10,
                    "proj_BA": 0.260,
                    "proj_R": 75,
                }
            ]
        )
        outlook = compute_category_outlook(pd.DataFrame(), pool, config=_config(), roster_gaps=["C"])
        self.assertTrue(outlook["bars"])
        for bar in outlook["bars"]:
            self.assertIn("expected", bar)
            self.assertEqual(bar["team_value"], 0.0)
            self.assertEqual(bar["ratio"], 0.0)

    def test_partial_roster_missing_columns_is_safe(self) -> None:
        roster = pd.DataFrame([{"fullName": "Player A", "proj_HR": 25}])
        pool = pd.DataFrame([{"proj_HR": 20, "proj_RBI": 70, "proj_SB": 10, "proj_BA": 0.260, "proj_R": 75}])
        outlook = compute_category_outlook(roster, pool, config=_config())
        self.assertTrue(outlook["bars"])
        hr = next(b for b in outlook["bars"] if b["category"] == "HR")
        self.assertGreater(hr["team_value"], 0.0)

    def test_zero_pool_baseline_uses_safe_ratio(self) -> None:
        roster = pd.DataFrame([{"proj_HR": 0, "proj_RBI": 0, "proj_SB": 0, "proj_BA": 0.0, "proj_R": 0}])
        pool = pd.DataFrame([{"proj_HR": 0, "proj_RBI": 0, "proj_SB": 0, "proj_BA": 0.0, "proj_R": 0}])
        outlook = compute_category_outlook(roster, pool, config=_config())
        self.assertTrue(outlook["bars"])
        for bar in outlook["bars"]:
            self.assertEqual(bar["ratio"], 0.0)


class PlayerCategoryStrengthsTests(unittest.TestCase):
    def _pool(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "proj_HR": 20,
                    "proj_RBI": 70,
                    "proj_SB": 10,
                    "proj_R": 75,
                    "proj_BA": 0.255,
                    "proj_OBP": 0.320,
                }
            ]
            * 20
        )

    def test_power_hitter_top_two(self) -> None:
        row = pd.Series(
            {
                "Primary Position": "OF",
                "proj_HR": 40,
                "proj_RBI": 100,
                "proj_SB": 5,
                "proj_R": 70,
                "proj_BA": 0.230,
                "proj_OBP": 0.330,
            }
        )
        strengths = player_top_category_strengths(row, self._pool(), config=_config())
        self.assertLessEqual(len(strengths), 2)
        self.assertIn("HR", strengths)
        self.assertIn("RBI", strengths)

    def test_speed_profile(self) -> None:
        row = pd.Series(
            {
                "Primary Position": "SS",
                "proj_HR": 18,
                "proj_RBI": 65,
                "proj_SB": 35,
                "proj_R": 95,
                "proj_BA": 0.265,
                "proj_OBP": 0.335,
            }
        )
        strengths = player_top_category_strengths(row, self._pool(), config=_config())
        self.assertLessEqual(len(strengths), 2)
        self.assertIn("SB", strengths)
        self.assertIn("Runs", strengths)

    def test_contact_hitter_label(self) -> None:
        row = pd.Series(
            {
                "Primary Position": "2B",
                "proj_HR": 8,
                "proj_RBI": 55,
                "proj_SB": 4,
                "proj_R": 72,
                "proj_BA": 0.310,
                "proj_OBP": 0.360,
            }
        )
        strengths = player_top_category_strengths(row, self._pool(), config=_config())
        self.assertIn("AVG", strengths)
        self.assertTrue("Contact" in strengths or "OBP" in strengths)

    def test_details_includes_top_category_strengths(self) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        st = mock.MagicMock()
        st.container.return_value.__enter__ = mock.Mock(return_value=mock.MagicMock())
        st.container.return_value.__exit__ = mock.Mock(return_value=False)
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {"live_draft_room": _room()}
        rec_df = pd.DataFrame(
            [
                {
                    "fullName": "Kyle Schwarber",
                    "playerID": "ks1",
                    "Primary Position": "OF",
                    "Fantasy Edge": 12,
                    "Survival Probability": 0.34,
                    "Model Rank": 17,
                    "Market Rank": 32,
                    "Draft Fit Score": 8.42,
                    "Decision Score": 9.11,
                    "proj_HR": 40,
                    "proj_RBI": 100,
                    "proj_SB": 5,
                    "proj_R": 70,
                    "proj_BA": 0.230,
                    "proj_OBP": 0.330,
                }
            ]
        )
        with mock.patch("draft_actions.resolve_manual_draft_panel_gate") as gate_fn:
            with mock.patch("draft_actions.draft_action_context"):
                with mock.patch("draft_actions._live_player_available", return_value=(True, "")):
                    gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
                    render_live_draft_rec_cards(st, session, session["live_draft_room"], rec_df, max_cards=1)
        expander_calls = [str(c) for c in st.expander.call_args_list]
        self.assertTrue(any("Why Recommended" in c for c in expander_calls))
        caption_calls = str(st.caption.call_args_list)
        self.assertNotIn("proj_HR", caption_calls)

    def test_reason_references_strengths(self) -> None:
        from live_draft_room_ui import _rec_plain_explanation

        row = pd.Series({"Positional Fit": 0.8})
        reason = _rec_plain_explanation(row, "OF", gaps=["OF"], strengths=["HR", "RBI"])
        self.assertIn("HR/RBI", reason)


class DraftNavigationTests(unittest.TestCase):
    def test_browse_other_pages_does_not_clear_room(self) -> None:
        session = {"live_draft_room": _room(), "active_shared_draft_room_code": "ABC123"}
        on_browse_other_pages(session, target_page="Fantasy Trends")
        self.assertTrue(session.get(BROWSING_AWAY_KEY))
        self.assertEqual(session.get("_navigate_to_page"), "Fantasy Trends")
        self.assertIn("live_draft_room", session)

    def test_return_sets_force_sync(self) -> None:
        session: dict = {}
        on_return_to_live_draft(session)
        self.assertTrue(session.get(FORCE_SYNC_ON_RETURN_KEY))
        self.assertEqual(session.get("_navigate_to_page"), "Live Draft Room")

    def test_return_context_for_active_live_draft(self) -> None:
        session = {
            "live_draft_room": _room(),
            "live_draft_setup_mode": "shared_multiplayer",
            "active_shared_draft_room_code": "ABC123",
            "draft_room_participant_team": "Danny",
        }
        with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
            ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "live_active")
        self.assertEqual(ctx.get("title"), "Return to Live Draft")
        self.assertEqual(ctx.get("user_team"), "Danny")

    def test_return_context_hydrates_from_canonical_blob(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, room_to_persist_dict

        room = _room()
        session = {LIVE_DRAFT_STATE_KEY: room_to_persist_dict(room)}
        with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
            ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("title"), "Return to Live Draft")

    def test_live_draft_priority_over_simulator(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, room_to_persist_dict

        session = {LIVE_DRAFT_STATE_KEY: room_to_persist_dict(_room())}
        sim_status = {
            "active": True,
            "mode": "draft_room_simulator",
            "pick_count": 8,
            "current_round": 2,
            "current_pick": 9,
            "on_clock_team": "Team A",
            "your_team": "Team A",
        }
        with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
            with mock.patch("draft_room_state.get_active_draft_status", return_value=sim_status):
                ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("title"), "Return to Live Draft")
        self.assertNotEqual(ctx.get("kind"), "simulator")

    def test_completed_draft_context(self) -> None:
        session = {
            "live_draft_room": _room(
                status="complete",
                current_pick_index=3,
                draft_board=[{"Pick": 1}, {"Pick": 2}, {"Pick": 3}],
            ),
            "live_draft_setup_mode": "shared_multiplayer",
            "active_shared_draft_room_code": "ABC123",
        }
        with mock.patch("live_draft_state.has_active_live_draft", return_value=False):
            ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "live_complete")

    def test_browse_preserves_room_code(self) -> None:
        session = {
            "live_draft_room": _room(),
            "active_shared_draft_room_code": "ROOM42",
            "draft_room_participant_team": "Danny",
        }
        on_browse_other_pages(session, target_page="Sleepers/Busts")
        self.assertEqual(session.get("active_shared_draft_room_code"), "ROOM42")
        self.assertEqual(session.get("draft_room_participant_team"), "Danny")

    def test_return_from_multiple_pages(self) -> None:
        for page in ("Fantasy Trends", "Sleepers/Busts", "Player Comparison"):
            session = {"active_page": page, "main_sidebar_page": page}
            on_return_to_live_draft(session)
            self.assertEqual(session.get("_navigate_to_page"), "Live Draft Room")

    def test_simulator_return_context(self) -> None:
        session: dict = {}
        status = {
            "active": True,
            "mode": "draft_room_simulator",
            "pick_count": 3,
            "current_round": 2,
            "current_pick": 5,
            "on_clock_team": "Team A",
            "your_team": "Team A",
        }
        with mock.patch("draft_room_state.get_active_draft_status", return_value=status):
            ctx = get_draft_return_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("kind"), "simulator")
        self.assertEqual(ctx.get("title"), "Return to Draft Simulator")

    def test_simulator_return_navigates_to_simulator(self) -> None:
        session = {"active_page": "Fantasy Trends"}
        on_return_to_draft_simulator(session)
        self.assertEqual(session.get("_navigate_to_page"), "Draft Room Simulator")

    def test_force_sync_on_return(self) -> None:
        session = {FORCE_SYNC_ON_RETURN_KEY: True, "live_draft_room": _room()}
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch("draft_room_context.sync_shared_draft_room") as sync_fn:
                with mock.patch("draft_room_context.poll_shared_draft_room") as poll_fn:
                    ok = apply_force_sync_on_return(session)
        self.assertTrue(ok)
        sync_fn.assert_called_once()
        poll_fn.assert_called_once()
        self.assertNotIn(FORCE_SYNC_ON_RETURN_KEY, session)

    def test_recommendations_heading_follows_quick_navigation(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        quick_idx = text.find("render_live_draft_quick_nav(st, st.session_state)")
        heading_idx = text.find('st.markdown("##### Recommendations")')
        self.assertNotEqual(quick_idx, -1)
        self.assertNotEqual(heading_idx, -1)
        self.assertGreater(heading_idx, quick_idx)


_REPO = Path(__file__).resolve().parents[1]


class RecCardBadgeTests(unittest.TestCase):
    def test_badges_include_position_need(self) -> None:
        from live_draft_room_ui import _rec_card_badges

        row = pd.Series(
            {
                "fullName": "Kyle Schwarber",
                "Primary Position": "OF",
                "Fantasy Edge": 12,
                "Positional Fit": 0.8,
                "Scarcity Score": 0.7,
                "Category Need Bonus": 0.05,
            }
        )
        rec_df = pd.DataFrame([row])
        badges = _rec_card_badges(1, row, rec_df, gaps=["OF"], category_needs=["HR"], strengths=["HR"])
        labels = " ".join(b[0] for b in badges)
        self.assertIn("Best Overall", labels)
        self.assertNotIn("Position Need", labels)

    def test_draft_insight_text_does_not_repeat_position_need_badge(self) -> None:
        from live_draft_room_ui import _rec_card_badges, build_draft_insight_text

        row = pd.Series(
            {
                "fullName": "Player A",
                "Primary Position": "SS",
                "Positional Fit": 0.82,
                "Scarcity Score": 0.72,
                "Survival Probability": 0.42,
                "Decision Score": 0.8,
            }
        )
        rec_df = pd.DataFrame([row])
        badges = _rec_card_badges(1, row, rec_df, gaps=["SS"])
        text = build_draft_insight_text(row, badges=badges, strengths=["HR", "SB"], gaps=["SS"], rank=1)
        lower = text.lower()
        self.assertNotIn("fills ss need", lower)
        self.assertNotIn("fills your ss need", lower)
        self.assertNotIn("second best", lower)
        self.assertTrue("strengthens" in lower or "42%" in text or "scarcity" in lower)


if __name__ == "__main__":
    unittest.main()
