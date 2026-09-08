"""Focused regression tests for Live Draft core interactions (no scoring changes)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]


class LiveDraftCoreInteractionContractTests(unittest.TestCase):
    def test_solo_early_viewport_does_not_rerun_mid_page_after_cards(self) -> None:
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = "Solo first-viewport landing: full player recommendation cards"
        block = src.split(marker, 1)[1].split(
            'ldr_section(st.session_state, "room_controls_timer"', 1
        )[0]
        self.assertIn("Do NOT attach/rebuild the projection pool or st.rerun()", block)
        self.assertNotIn("maybe_build_deferred_full_pool(", block)
        # Manual-pick success may still request a rerun; projection upgrade must not.
        self.assertNotIn("solo_projection_direct_attach", block)
        self.assertNotIn("_solo_projection_grade_rerun_done", block)

    def test_expire_not_blocked_by_projection_grade_flag(self) -> None:
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        # Historical bug: holding expire while grades upgrade left Auto Pick stuck.
        self.assertNotIn(
            'if st.session_state.get("_solo_needs_projection_player_grades"):\n'
            "            _process_expired_or_timer = False",
            src,
        )
        self.assertIn(
            "Never block timer auto-pick on projection-grade upgrade",
            src,
        )

    def test_manual_draft_panel_available_on_solo_early_path(self) -> None:
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = "Solo first-viewport landing: full player recommendation cards"
        block = src.split(marker, 1)[1].split(
            'ldr_section(st.session_state, "room_controls_timer"', 1
        )[0]
        self.assertIn("render_live_manual_draft_panel", block)
        self.assertIn("Manual Draft", block)
        self.assertIn("not limited to the recommendation cards", block)

    def test_horizontal_rec_cards_use_three_column_rows(self) -> None:
        src = (_REPO / "live_draft_room_ui.py").read_text(encoding="utf-8")
        self.assertIn("cols_per_row = 3 if horizontal else 1", src)
        self.assertIn("horizontal_grid_3", src)
        self.assertNotIn("column_slots = st.columns(len(rows)) if horizontal", src)

    def test_sticky_submitting_cleared_without_pending_pick(self) -> None:
        from live_draft_pick_timer import clear_pick_submit_state, is_pick_submitting
        from live_draft_room_ui import render_live_draft_rec_cards

        rec = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "playerID": "j1",
                    "Primary Position": "OF",
                    "Team": "NYY",
                    "Fantasy Edge": 0.0,
                    "Decision Score": 0.95,
                    "Positional Fit": 0.8,
                    "Expected Fantasy Value": 0.91,
                    "Survival Probability": 0.2,
                    "Draft Fit Score": 1.5,
                }
            ]
        )
        room = {
            "draft_room_id": "SOLOINT",
            "current_pick_index": 0,
            "status": "in_progress",
            "config": {"your_team": "Team A", "slots": {"OF": 3}},
            "pool": rec.copy(),
            "teams": ["Team A", "Team B"],
            "rosters": {"Team A": [], "Team B": []},
            "pick_order": [{"Team": "Team A"}, {"Team": "Team B"}],
        }
        session: dict = {
            "draft_queue": [],
            "_live_draft_pick_submitting": True,
            "live_draft_room": room,
        }
        st = MagicMock()
        container = MagicMock()
        container.__enter__ = MagicMock(return_value=container)
        container.__exit__ = MagicMock(return_value=False)
        st.container.return_value = container
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)

        def _cols(n, *a, **k):
            count = len(n) if isinstance(n, (list, tuple)) else int(n)
            return [col] * count

        st.columns.side_effect = _cols
        expander = MagicMock()
        expander.__enter__ = MagicMock(return_value=expander)
        expander.__exit__ = MagicMock(return_value=False)
        st.expander.return_value = expander
        st.button.return_value = False

        with patch("live_draft_room_ui.record_rec_card_diagnostics"), patch(
            "draft_actions.resolve_manual_draft_panel_gate",
            return_value={"draft_enabled": True, "draft_complete": False},
        ), patch(
            "draft_actions.resolve_player_draft_gate",
            return_value={"allowed": True, "disable_message": ""},
        ):
            render_live_draft_rec_cards(
                st, session, room, rec, max_cards=1, layout="horizontal", dense=False
            )
        self.assertFalse(is_pick_submitting(session))

    def test_canonical_pick_commit_still_present(self) -> None:
        from live_draft_pick_commit import commit_manual_live_pick, commit_live_draft_pick
        from live_draft_autopick import live_draft_auto_pick
        from draft_state import add_player_to_draft_queue

        self.assertTrue(callable(commit_manual_live_pick))
        self.assertTrue(callable(commit_live_draft_pick))
        self.assertTrue(callable(live_draft_auto_pick))
        self.assertTrue(callable(add_player_to_draft_queue))

    def test_add_to_queue_mutates_visible_session_queue(self) -> None:
        from draft_state import add_player_to_draft_queue

        session: dict = {"draft_queue": []}
        add_player_to_draft_queue(session, "Aaron Judge")
        self.assertIn("Aaron Judge", session.get("draft_queue") or [])
        add_player_to_draft_queue(session, "Aaron Judge")
        # No duplicate names.
        self.assertEqual(
            [x for x in session["draft_queue"] if str(x).strip().lower() == "aaron judge"],
            ["Aaron Judge"],
        )

    def test_rec_rankings_painted_above_quick_draft_tools_only(self) -> None:
        """Only allowed layout move: recommendation rankings sit above Quick Draft Tools."""
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        body_marker = "def _paint_heavy_recommendations_body() -> None:"
        body = src.split(body_marker, 1)[1].split(
            "def _paint_live_recommendation_interactive_only()", 1
        )[0]
        rankings_idx = body.find('st.expander("Recommendation rankings"')
        qt_idx = body.find("render_live_draft_quick_nav_compact")
        self.assertNotEqual(rankings_idx, -1)
        self.assertNotEqual(qt_idx, -1)
        self.assertLess(rankings_idx, qt_idx)
        self.assertIn("include_quick_tools=False", body)
        # Draft Queue panel must not be relocated between rankings and Quick Tools.
        # (Quick Draft Tools itself may mention "Draft Queue" as a jump button.)
        between = body[rankings_idx:qt_idx]
        self.assertNotIn("render_live_draft_queue", between)
        self.assertNotIn("Draft Queue ·", between)

    def test_recommended_players_user_facing_intro(self) -> None:
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn('st.markdown("##### Recommended Players")', src)
        self.assertIn(
            "Compare the best options for your current pick based on player quality",
            src,
        )
        self.assertNotIn("Players the engine recommends for this pick", src)

    def test_deferred_pool_skipped_on_light_interactive_runs(self) -> None:
        src = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("live_draft_light_rerun_active", src)
        self.assertIn("Never run the blocking projection rebuild on the same ScriptRun", src)

    def test_patch_after_pick_filters_interactive_snapshot(self) -> None:
        from live_draft_rec_live_paint import INTERACTIVE_TOP_REC_SNAPSHOT_KEY
        from live_draft_ui_cache import patch_live_draft_caches_after_pick

        session = {
            INTERACTIVE_TOP_REC_SNAPSHOT_KEY: {
                "room_id": "R1",
                "top_rec": pd.DataFrame(
                    [
                        {"fullName": "Aaron Judge", "playerID": "judge"},
                        {"fullName": "Shohei Ohtani", "playerID": "ohtani"},
                    ]
                ),
            },
            "_live_draft_rec_cache": {
                "top_rec": pd.DataFrame(
                    [
                        {"fullName": "Aaron Judge", "playerID": "judge"},
                        {"fullName": "Shohei Ohtani", "playerID": "ohtani"},
                    ]
                ),
                "best_avail": pd.DataFrame(),
                "pos_fit": pd.DataFrame(),
                "value_sleep": pd.DataFrame(),
            },
        }
        room = {
            "draft_room_id": "R1",
            "draft_board": [{"Player": "Aaron Judge", "playerID": "judge"}],
            "config": {},
        }
        patch_live_draft_caches_after_pick(
            session, room, player_id="judge", player_name="Aaron Judge"
        )
        snap = session.get(INTERACTIVE_TOP_REC_SNAPSHOT_KEY) or {}
        top = snap.get("top_rec")
        self.assertIsNotNone(top)
        names = [str(x).lower() for x in top["fullName"].tolist()]
        self.assertNotIn("aaron judge", names)
        self.assertIn("shohei ohtani", names)

    def test_expire_ownership_stamped_only_after_success(self) -> None:
        src = (_REPO / "live_draft_solo_heartbeat.py").read_text(encoding="utf-8")
        # Ownership stamp must follow a confirmed advance, not precede expire_current_pick.
        attempt = src.find("phase=f\"{source}_expire_attempt\"")
        stamp = src.find("note_solo_fragment_owned_expire(session)")
        committed = src.find('if result.ok and (result.advanced or result.complete):')
        self.assertNotEqual(attempt, -1)
        self.assertNotEqual(stamp, -1)
        self.assertNotEqual(committed, -1)
        self.assertGreater(stamp, committed)
        self.assertGreater(stamp, attempt)


if __name__ == "__main__":
    unittest.main()
