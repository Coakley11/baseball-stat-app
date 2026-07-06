"""Tests for Draft Assistant deferred settings persistence and UI caches."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_assistant_setup_persist import (
    DRAFT_ASSISTANT_DIRTY_KEY,
    clear_draft_assistant_settings_dirty,
    flush_draft_assistant_settings_persist,
    is_draft_assistant_settings_dirty,
    mark_draft_assistant_settings_dirty,
    on_draft_assistant_settings_changed,
)
from live_draft_ui_cache import (
    DA_SCORING_CACHE_KEY,
    DA_WHY_CACHE_KEY,
    draft_assistant_board_revision,
    draft_assistant_pool_revision,
    draft_assistant_scoring_cache_key,
    enrich_draft_assistant_recs_with_why,
    invalidate_draft_assistant_ui_caches,
)


class DraftAssistantSetupPersistTests(unittest.TestCase):
    def test_widget_change_marks_dirty_without_force_save(self) -> None:
        session: dict = {
            "draft_window": 3,
            "fantasy_draft_projection_style": "Balanced",
            "draft_format": "5x5 Roto",
            "draft_use_ml_blend": True,
            "draft_ml_blend_weight": 0.12,
            "draft_ml_min_games_signal": 50,
        }
        with patch("shared_draft_context.on_draft_settings_changed") as mock_canon, patch(
            "baseball_persistent_state.force_save_baseball_state"
        ) as mock_save:
            on_draft_assistant_settings_changed(session)
        mock_canon.assert_called_once()
        mock_save.assert_not_called()
        self.assertTrue(is_draft_assistant_settings_dirty(session))

    def test_flush_clears_dirty_and_saves(self) -> None:
        session: dict = {DRAFT_ASSISTANT_DIRTY_KEY: True}
        st = MagicMock()
        st.session_state = session
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as mock_save:
            ok = flush_draft_assistant_settings_persist(st, session, reason="draft_assistant_page_leave")
        self.assertTrue(ok)
        mock_save.assert_called_once()
        self.assertFalse(is_draft_assistant_settings_dirty(session))

    def test_clear_dirty(self) -> None:
        session = {DRAFT_ASSISTANT_DIRTY_KEY: True}
        clear_draft_assistant_settings_dirty(session)
        self.assertFalse(is_draft_assistant_settings_dirty(session))


class DraftAssistantCacheKeyTests(unittest.TestCase):
    def test_scoring_key_changes_when_projection_window_changes(self) -> None:
        base = {
            "draft_window": 3,
            "fantasy_draft_projection_style": "Balanced",
            "draft_format": "5x5 Roto",
            "draft_use_ml_blend": True,
            "draft_ml_blend_weight": 0.12,
            "draft_ml_min_games_signal": 50,
            "_lahman_max_year": 2024,
        }
        kw = dict(
            drafted_names=frozenset(),
            my_roster=[],
            current_pick=1,
            needed_positions=[],
            category_needs=[],
            target_counts={},
            draft_format="5x5 Roto",
            use_ml_blend=True,
            ml_blend_weight=0.12,
            draft_top_n=10,
        )
        s1 = dict(base)
        s2 = dict(base)
        s2["draft_window"] = 5
        k1 = draft_assistant_scoring_cache_key(s1, **kw)
        k2 = draft_assistant_scoring_cache_key(s2, **kw)
        self.assertNotEqual(k1, k2)

    def test_scoring_key_changes_when_board_pick_count_changes(self) -> None:
        session: dict = {
            "draft_window": 3,
            "fantasy_draft_projection_style": "Balanced",
            "draft_format": "5x5 Roto",
            "draft_use_ml_blend": True,
            "draft_ml_blend_weight": 0.12,
            "draft_ml_min_games_signal": 50,
            "_lahman_max_year": 2024,
            "draft_room_table": pd.DataFrame(
                [{"Round": 1, "Pick": 1, "Team": "Daniel", "Player": "A"}]
            ),
        }
        session2 = dict(session)
        session2["draft_room_table"] = pd.DataFrame(
            [
                {"Round": 1, "Pick": 1, "Team": "Daniel", "Player": "A"},
                {"Round": 1, "Pick": 2, "Team": "Team 2", "Player": "B"},
            ]
        )
        kw = dict(
            drafted_names=frozenset({"a"}),
            my_roster=["A"],
            current_pick=2,
            needed_positions=[],
            category_needs=[],
            target_counts={},
            draft_format="5x5 Roto",
            use_ml_blend=True,
            ml_blend_weight=0.12,
            draft_top_n=10,
        )
        self.assertNotEqual(
            draft_assistant_board_revision(session),
            draft_assistant_board_revision(session2),
        )
        self.assertNotEqual(
            draft_assistant_scoring_cache_key(session, **kw),
            draft_assistant_scoring_cache_key(session2, **kw),
        )

    def test_pool_revision_includes_style_and_window(self) -> None:
        s1 = {
            "draft_window": 3,
            "fantasy_draft_projection_style": "Balanced",
            "draft_format": "5x5 Roto",
        }
        s2 = dict(s1)
        s2["fantasy_draft_projection_style"] = "Aggressive"
        self.assertNotEqual(draft_assistant_pool_revision(s1), draft_assistant_pool_revision(s2))

    def test_invalidate_clears_scoring_and_why(self) -> None:
        session = {DA_SCORING_CACHE_KEY: {"key": 1}, DA_WHY_CACHE_KEY: {"key": 1}}
        invalidate_draft_assistant_ui_caches(session)
        self.assertNotIn(DA_SCORING_CACHE_KEY, session)
        self.assertNotIn(DA_WHY_CACHE_KEY, session)

    def test_why_cache_hit_on_second_call(self) -> None:
        session: dict = {}
        recs = pd.DataFrame(
            {
                "fullName": ["Player A"],
                "Primary Position": ["OF"],
                "Draft Fit Score": [90.0],
            }
        )
        cache_key = ("test",)
        with patch(
            "live_draft_room_ui.build_draft_assistant_why_this_pick",
            return_value="Because fit",
        ) as mock_why:
            out1 = enrich_draft_assistant_recs_with_why(
                session, cache_key, recs, draft_format="5x5 Roto"
            )
            out2 = enrich_draft_assistant_recs_with_why(
                session, cache_key, recs, draft_format="5x5 Roto"
            )
        self.assertEqual(mock_why.call_count, 1)
        self.assertIn("Why this pick", out1.columns)
        self.assertEqual(str(out2.iloc[0]["Why this pick"]), "Because fit")


if __name__ == "__main__":
    unittest.main()
