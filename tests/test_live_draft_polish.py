"""Live Draft Room polish — cards, queue, why column, draft flow updates."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from draft_ui import format_queue_player_metrics_line
from live_draft_category_outlook import compute_category_outlook
from live_draft_navigation import LIVE_DRAFT_QUICK_NAV_PAGES, render_live_draft_quick_nav
from live_draft_roster_tracker import build_team_roster_tracker
from live_draft_room_ui import add_why_this_pick_column, build_why_this_pick_summary
from live_draft_state import live_draft_get_available
from live_draft_pick_engine import live_draft_make_pick


def _config() -> dict:
    return {
        "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0},
        "scoring_type": "Roto (5x5)",
    }


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playerID": "p1",
                "fullName": "Kyle Schwarber",
                "Primary Position": "OF",
                "Team": "PHI",
                "Expected Fantasy Value": 0.88,
                "Decision Score": 0.91,
                "Draft Fit Score": 8.4,
                "Model Rank": 17,
                "Market Rank": 32,
                "Fantasy Edge": 15,
                "Positional Fit": 0.82,
                "Category Need Bonus": 0.06,
                "Scarcity Score": 0.55,
                "proj_HR": 40,
                "proj_RBI": 95,
                "proj_R": 80,
                "proj_SB": 5,
                "proj_BA": 0.240,
            },
            {
                "playerID": "p2",
                "fullName": "Bobby Witt Jr.",
                "Primary Position": "SS",
                "Team": "KC",
                "Expected Fantasy Value": 0.95,
                "Decision Score": 0.94,
                "Draft Fit Score": 9.1,
                "Model Rank": 5,
                "Market Rank": 6,
                "Fantasy Edge": 1,
                "Positional Fit": 0.75,
                "proj_HR": 25,
                "proj_RBI": 85,
                "proj_R": 95,
                "proj_SB": 30,
                "proj_BA": 0.290,
            },
            {
                "playerID": "p3",
                "fullName": "Aaron Judge",
                "Primary Position": "OF",
                "Team": "NYY",
                "Expected Fantasy Value": 0.97,
                "Decision Score": 0.96,
                "Draft Fit Score": 9.5,
                "Model Rank": 2,
                "Market Rank": 2,
                "Fantasy Edge": 0,
                "Positional Fit": 0.70,
                "proj_HR": 45,
                "proj_RBI": 110,
                "proj_R": 100,
                "proj_SB": 8,
                "proj_BA": 0.300,
            },
        ]
    )


def _room(**overrides) -> dict:
    room = {
        "status": "in_progress",
        "current_pick_index": 0,
        "config": _config(),
        "teams": ["Danny", "Amiel"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Danny"},
            {"Pick": 2, "Round": 1, "Team": "Amiel"},
            {"Pick": 3, "Round": 2, "Team": "Amiel"},
            {"Pick": 4, "Round": 2, "Team": "Danny"},
            {"Pick": 5, "Round": 3, "Team": "Danny"},
        ],
        "draft_board": [],
        "rosters": {"Danny": [], "Amiel": []},
        "drafted_player_ids": [],
        "pool": _pool(),
    }
    room.update(overrides)
    return room


class RecCardMetricsTests(unittest.TestCase):
    def test_rec_card_html_includes_core_metrics(self) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        st = mock.MagicMock()
        st.container.return_value.__enter__ = mock.Mock(return_value=mock.MagicMock())
        st.container.return_value.__exit__ = mock.Mock(return_value=False)
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {"live_draft_room": _room()}
        rec_df = _pool().head(1).copy()
        with mock.patch("draft_actions.resolve_manual_draft_panel_gate") as gate_fn, mock.patch(
            "draft_actions.draft_action_context"
        ), mock.patch("draft_actions._live_player_available", return_value=(True, "")):
            gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
            render_live_draft_rec_cards(st, session, session["live_draft_room"], rec_df, max_cards=1)
        html = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("ld-rec-card-header", html)
        self.assertIn("Decision Score", html)
        self.assertIn("Player Grade", html)
        self.assertIn("Roster Fit Score", html)
        self.assertIn("Fantasy Edge", html)
        self.assertIn("Proj:", html)
        self.assertNotIn("Market Rank", html)
        self.assertNotIn("Model Rank", html)

    def test_why_summary_mentions_drivers_not_proj_prose(self) -> None:
        row = _pool().iloc[0]
        why = build_why_this_pick_summary(row, "OF", gaps=["OF"], category_needs=["HR"], strengths=["HR", "RBI"])
        self.assertIn("HR", why)
        self.assertNotIn("Proj:", why)
        self.assertNotIn("fills OF need", why)

    def test_why_column_added_to_table(self) -> None:
        rec = _pool().head(2)
        out = add_why_this_pick_column(rec, gaps=["OF"], category_needs=["HR"], pool_df=_pool(), config=_config())
        self.assertIn("Why this pick", out.columns)
        self.assertTrue(str(out.iloc[0]["Why this pick"]).strip())


class QueueMetricsTests(unittest.TestCase):
    def test_queue_metrics_line_uses_canonical_proj(self) -> None:
        line = format_queue_player_metrics_line(_pool().iloc[0])
        self.assertIn("Proj:", line)
        self.assertIn("Decision Score", line)
        self.assertIn("Roster Fit", line)


class QuickNavTests(unittest.TestCase):
    def test_quick_nav_pages_complete(self) -> None:
        from live_draft_navigation import LIVE_DRAFT_QUICK_NAV_QUEUE_ACTION

        labels = {label for _page, label, _sub, _theme in LIVE_DRAFT_QUICK_NAV_PAGES}
        labels.add(LIVE_DRAFT_QUICK_NAV_QUEUE_ACTION[1])
        self.assertEqual(labels, {"Draft Assistant", "Sleepers", "Queue"})
        self.assertNotIn("Trends", labels)
        self.assertNotIn("ML Projections", labels)

    def test_quick_nav_renders_buttons(self) -> None:
        from live_draft_navigation import LIVE_DRAFT_QUICK_NAV_QUEUE_ACTION

        st = mock.MagicMock()
        session: dict = {}
        cols = [mock.MagicMock() for _ in range(3)]
        st.columns.return_value = cols
        with mock.patch("shared_draft_context.prepare_canonical_scoring_context"):
            render_live_draft_quick_nav(st, session)
        button_calls = sum(col.button.call_count for col in cols)
        self.assertEqual(button_calls, len(LIVE_DRAFT_QUICK_NAV_PAGES) + 1)
        self.assertEqual(LIVE_DRAFT_QUICK_NAV_QUEUE_ACTION[1], "Queue")
        st.caption.assert_called()


class DraftFlowUpdateTests(unittest.TestCase):
    def test_multi_pick_updates_roster_needs_category_and_available(self) -> None:
        room = _room()
        pool = _pool()

        ok, _ = live_draft_make_pick(room, pool.iloc[2].to_dict(), verdict="Test pick 1")
        self.assertTrue(ok)

        tracker = build_team_roster_tracker(room, "Danny")
        self.assertEqual(tracker["filled"], 1)
        open_after_one = set(tracker["open_positions"] + tracker["gaps"])
        self.assertTrue(open_after_one)

        avail = live_draft_get_available(room)
        drafted_ids = {str(x) for x in (room.get("drafted_player_ids") or [])}
        self.assertIn("p3", drafted_ids)
        if not avail.empty and "playerID" in avail.columns:
            self.assertFalse((avail["playerID"].astype(str) == "p3").any())

        roster_df = pd.DataFrame(room["rosters"]["Danny"])
        outlook_before = compute_category_outlook(
            roster_df, avail, config=_config(), roster_gaps=tracker["gaps"]
        )

        ok2, _ = live_draft_make_pick(room, pool.iloc[1].to_dict(), verdict="Test pick 2")
        self.assertTrue(ok2)

        ok3, _ = live_draft_make_pick(room, pool.iloc[0].to_dict(), verdict="Test pick 3")
        self.assertTrue(ok3)

        tracker2 = build_team_roster_tracker(room, "Amiel")
        self.assertEqual(tracker2["filled"], 2)

        avail2 = live_draft_get_available(room)
        drafted_ids = {str(x) for x in (room.get("drafted_player_ids") or [])}
        self.assertEqual(len(drafted_ids), 3)
        if not avail2.empty and "playerID" in avail2.columns:
            overlap = avail2["playerID"].astype(str).isin(drafted_ids)
            self.assertFalse(bool(overlap.any()))

        roster_amiel = pd.DataFrame(room["rosters"]["Amiel"])
        outlook_after = compute_category_outlook(
            roster_amiel, avail2, config=_config(), roster_gaps=tracker2["gaps"]
        )
        self.assertTrue(outlook_before["bars"] or outlook_after["bars"])

    def test_drafted_players_excluded_from_recommendations(self) -> None:
        try:
            from streamlit_app import live_draft_recommendations
        except (ImportError, TypeError):
            self.skipTest("streamlit_app module-level chrome not available in unit test context")
        except Exception as exc:
            if "ScriptRunContext" in str(exc) or "context manager" in str(exc):
                self.skipTest(f"streamlit_app import requires runtime: {exc}")
            raise

        room = _room()
        pool = _pool()
        live_draft_make_pick(room, pool.iloc[2].to_dict())
        room["drafted_player_ids"] = list(room.get("drafted_player_ids") or [])
        top, _best, _pos, _sleep = live_draft_recommendations(room, top_n=5)
        if not top.empty and "fullName" in top.columns:
            self.assertNotIn("Aaron Judge", top["fullName"].astype(str).tolist())


if __name__ == "__main__":
    unittest.main()
