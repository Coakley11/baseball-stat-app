"""Effective fantasy source and Research Mode stay aligned across pages."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pandas as pd

from account_fantasy_preferences import (
    FANTASY_RESEARCH_MODE_SELECTION_KEY,
    PREFS_DOC_KEY,
    install_test_cloud_store,
    prefs_settings_app,
    reassert_account_preferences_after_hydration,
    write_account_fantasy_preferences,
)
from fantasy_context_source import (
    SOURCE_ACTIVE_DRAFT,
    SOURCE_LIVE_DRAFT,
    SOURCE_SIMULATOR_BOARD,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    fantasy_context_using_caption,
    fantasy_drafted_pool_filter_applies,
    get_effective_fantasy_context,
    resolve_fantasy_context_source,
)
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
    _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
    _prepare_context_checkbox_widget,
    apply_research_mode_toggle_from_widget,
)
from fantasy_waiver_wire import filter_unrostered_players
from player_trade_handoff import resolve_active_league_player_trade_eligibility


def _four_pick_board() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Round": [1, 1, 1, 1],
            "Pick": [1, 2, 3, 4],
            "Team": ["Daniel", "Team 2", "Daniel", "Team 2"],
            "Player": ["Aaron Judge", "Francisco Lindor", "Juan Soto", "Mookie Betts"],
        }
    )


def _session() -> dict:
    return {
        "_suite_auth_user_id": "daniel",
        "_suite_active_workspace_id": "daniel",
        "_suite_device_id": "phone",
        "draft_room_table": _four_pick_board(),
        "room_your_team": "Daniel",
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
        "active_draft_archive_id": "saved-draft",
        "fantasy_league_context_state": {
            "active_league_context_id": "ctx_saved",
            "contexts": {
                "ctx_saved": {
                    "league_context_id": "ctx_saved",
                    "context_type": "real_league",
                    "display_name": "My Fantasy League",
                    "my_team_name": "Daniel",
                    "league_rosters": {
                        "Daniel": {"team_name": "Daniel", "players": [{"player_name": "Old League Guy"}]}
                    },
                }
            },
        },
    }


class FantasySourceResearchConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def test_simulator_override_is_effective_source_not_saved_league(self) -> None:
        session = _session()
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_SIMULATOR_BOARD)
        caption = fantasy_context_using_caption(session)
        self.assertIn("Simulator", caption)
        self.assertNotIn("My Fantasy League", caption)
        effective = get_effective_fantasy_context(session)
        self.assertEqual(effective.get("league_context_id"), "__ephemeral_simulator__")
        self.assertEqual(session.get("active_draft_archive_id"), "saved-draft")

    def test_override_on_does_not_fall_back_when_board_is_temporarily_empty(self) -> None:
        session = _session()
        session["draft_room_table"] = pd.DataFrame(columns=["Round", "Pick", "Team", "Player"])
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_SIMULATOR_BOARD)
        effective = get_effective_fantasy_context(session)
        self.assertNotEqual(str((effective or {}).get("display_name") or ""), "My Fantasy League")
        self.assertEqual(session.get("active_draft_archive_id"), "saved-draft")

    def test_research_mode_on_excludes_four_drafted_players(self) -> None:
        session = _session()
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        pool = pd.DataFrame(
            {
                "fullName": [
                    "Francisco Lindor",
                    "Cal Raleigh",
                    "Aaron Judge",
                    "Juan Soto",
                    "Mookie Betts",
                ]
            }
        )
        for page in ("Fantasy Sleepers & Busts", "Trend Value", "Valuation", "Comparison Tool"):
            self.assertTrue(fantasy_drafted_pool_filter_applies(session, page))
            filtered = filter_unrostered_players(session, pool, name_col="fullName", page_name=page)
            self.assertNotIn("Francisco Lindor", set(filtered["fullName"]))
            self.assertIn("Cal Raleigh", set(filtered["fullName"]))

    def test_research_mode_off_keeps_drafted_players_visible(self) -> None:
        session = _session()
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        pool = pd.DataFrame({"fullName": ["Francisco Lindor", "Cal Raleigh"]})
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, "Trend Value"))
        filtered = filter_unrostered_players(session, pool, name_col="fullName", page_name="Trend Value")
        self.assertIn("Francisco Lindor", set(filtered["fullName"]))

    def test_historical_pages_stay_unfiltered(self) -> None:
        session = _session()
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, "Historical Explorer"))
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, "Career Totals"))

    def test_saved_draft_used_when_override_off(self) -> None:
        session = _session()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_ACTIVE_DRAFT)

    def test_simulator_context_disables_league_transactions(self) -> None:
        session = _session()
        eligibility = resolve_active_league_player_trade_eligibility(session, "Cal Raleigh")
        self.assertFalse(eligibility["trade_away_enabled"])
        self.assertFalse(eligibility["acquire_enabled"])
        self.assertFalse(eligibility["plan_add_enabled"])
        self.assertFalse(eligibility["plan_drop_enabled"])
        self.assertIn("simulator", eligibility["block_message"].lower())

    def test_research_mode_survives_stale_cloud_and_refresh(self) -> None:
        session = _session()
        write_account_fantasy_preferences(session, reason="bootstrap")
        session[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        apply_research_mode_toggle_from_widget(session)
        doc = (self.store.get(prefs_settings_app(session)) or {}).get(PREFS_DOC_KEY) or {}
        doc["research_mode_enabled"] = False
        doc["updated_at"] = "2020-01-01T00:00:00+00:00"
        session.pop(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY, None)
        reassert_account_preferences_after_hydration(session)
        self.assertTrue(session[FANTASY_RESEARCH_SYNC_KEY])
        _prepare_context_checkbox_widget(
            session,
            persisted_key=FANTASY_RESEARCH_SYNC_KEY,
            widget_key=_RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
        )
        self.assertTrue(session[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY])

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        st = MagicMock()
        st.session_state = session
        blob = build_baseball_disk_state(st)
        self.assertTrue(blob[FANTASY_RESEARCH_MODE_SELECTION_KEY]["enabled"])
        restored = {"_suite_auth_user_id": "daniel", "_suite_active_workspace_id": "daniel"}
        st2 = MagicMock()
        st2.session_state = restored
        apply_baseball_disk_state(st2, blob)
        self.assertTrue(restored[FANTASY_RESEARCH_SYNC_KEY])

    def test_other_account_research_mode_does_not_apply(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state

        blob = {
            FANTASY_RESEARCH_MODE_SELECTION_KEY: {
                "user_id": "ariel",
                "workspace_id": "ariel",
                "enabled": True,
                "selected_at": "2026-10-28T00:00:00+00:00",
                "seen_revision": 1,
                "local_seq": 1,
            }
        }
        restored = {"_suite_auth_user_id": "daniel", "_suite_active_workspace_id": "daniel"}
        st = MagicMock()
        st.session_state = restored
        apply_baseball_disk_state(st, blob)
        self.assertNotIn(FANTASY_RESEARCH_MODE_SELECTION_KEY, restored)
        self.assertFalse(bool(restored.get(FANTASY_RESEARCH_SYNC_KEY)))

    def test_active_live_draft_still_preempts_simulator_override(self) -> None:
        session = _session()
        session["live_draft_room"] = {"status": "in_progress", "draft_board": [{"Player": "Someone"}]}
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_LIVE_DRAFT)


if __name__ == "__main__":
    unittest.main()
