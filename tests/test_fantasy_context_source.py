"""Fantasy context source-of-truth priority and fingerprint dedupe."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pandas as pd

from fantasy_context_source import (
    DRAFT_ASSISTANT_PAGE,
    SOURCE_ACTIVE_DRAFT,
    SOURCE_LIVE_DRAFT,
    SOURCE_SIMULATOR_BOARD,
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    draft_assistant_context_mode,
    fantasy_context_applies_to_page,
    fantasy_drafted_pool_filter_applies,
    get_effective_fantasy_context,
    is_live_draft_in_progress,
    live_draft_feeds_draft_assistant,
    resolve_fantasy_context_source,
    simulator_feeds_draft_assistant,
)
from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY
from fantasy_league_context import (
    build_league_rosters_from_simulator_board,
    compute_save_draft_fingerprint,
    resolve_canonical_save_ids,
    save_simulator_league_context,
    upsert_league_context,
)


def _saved_context_session(*, team: str = "Daniel", label: str = "Practice Draft") -> dict:
    return {
        "fantasy_league_context_state": {
            "active_league_context_id": "ctx_practice",
            "contexts": {
                "ctx_practice": {
                    "league_context_id": "ctx_practice",
                    "display_name": label,
                    "my_team_name": team,
                    "fantasy_format": "5x5 Roto",
                    "league_rosters": {
                        team: {
                            "team_name": team,
                            "is_user_team": True,
                            "players": [{"player_name": "Aaron Judge", "player_key": "aaron judge"}],
                        }
                    },
                }
            },
        },
        "active_draft_archive_id": "arch1",
        "draft_archive_teams": [
            {
                "draft_id": "arch1",
                "draft_name": label,
                "team_name": team,
                "league_context_id": "ctx_practice",
            }
        ],
    }


def _simulator_board_session() -> dict:
    board = pd.DataFrame(
        {
            "Round": [1, 1],
            "Pick": [1, 2],
            "Team": ["Daniel", "Rivals"],
            "Player": ["Aaron Judge", "Juan Soto"],
        }
    )
    return {
        "draft_room_table": board,
        "room_your_team": "Daniel",
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
        USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: True,
    }


class FantasyContextSourceTests(unittest.TestCase):
    def test_active_draft_wins_when_overrides_off(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_ACTIVE_DRAFT)
        self.assertIn("Practice Draft", source.badge_text)

    def test_active_draft_wins_when_toggles_default_off(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session.pop(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, None)
        session.pop(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, None)
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_ACTIVE_DRAFT)

    def test_simulator_board_wins_when_toggle_enabled(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_SIMULATOR_BOARD)
        self.assertIn("temporary / unsaved", source.badge_text)

    def test_simulator_override_disabled_falls_back_to_active_draft(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_ACTIVE_DRAFT)

    def test_live_draft_wins_when_active(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": "in_progress",
            "config": {"user_team": "Daniel", "fantasy_format": "5x5 Roto"},
            "draft_board": [{"Team": "Daniel", "Player": "Aaron Judge"}],
            "teams": ["Daniel", "Rivals"],
        }
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_LIVE_DRAFT)

    def test_live_in_progress_wins_even_when_live_override_disabled(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": "in_progress",
            "config": {"user_team": "Daniel"},
            "draft_board": [{"Team": "Daniel", "Player": "Aaron Judge"}],
        }
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_LIVE_DRAFT)
        self.assertEqual(source.origin, "active_live")

    def test_temporary_live_my_team_ignores_stale_active_draft_team(self) -> None:
        """Active Draft Team 1 must not leak into Temporary Practice Board Team X."""
        session = _saved_context_session(team="Team 1", label="Fresh 10-Pick Live Test")
        session["room_your_team"] = "Team 1"
        session["draft_room_participant_team"] = "Team 1"
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session["live_draft_room"] = {
            "draft_room_id": "prac1",
            "status": "in_progress",
            "config": {
                "league_name": "Temporary Practice Board",
                "user_team": "Team X",
                "your_team": "Team X",
            },
            "teams": ["Team X", "Team Y"],
            "draft_board": [],
            "rosters": {"Team X": [], "Team Y": []},
        }
        session["live_draft_my_team"] = "Team X"
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_LIVE_DRAFT)
        ctx = get_effective_fantasy_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("my_team_name"), "Team X")
        self.assertNotEqual(ctx.get("my_team_name"), "Team 1")
        from fantasy_workspace_team_identity import (
            resolve_current_account_team_for_live_draft_and_league,
        )

        resolved = resolve_current_account_team_for_live_draft_and_league(
            session, room=session["live_draft_room"]
        )
        self.assertEqual(resolved, "Team X")

    def test_completed_live_without_override_returns_to_active_draft(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": "complete",
            "config": {"user_team": "Daniel"},
            "draft_board": [{"Team": "Daniel", "Player": "Aaron Judge"}],
        }
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_ACTIVE_DRAFT)

    def test_completed_live_with_override_stays_live(self) -> None:
        session = _saved_context_session()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = True
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": "complete",
            "config": {"user_team": "Daniel"},
            "draft_board": [{"Team": "Daniel", "Player": "Aaron Judge"}],
        }
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_LIVE_DRAFT)
        self.assertEqual(source.origin, "override")

    def test_effective_context_uses_saved_when_simulator_disabled(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        ctx = get_effective_fantasy_context(session)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.get("my_team_name"), "Daniel")
        self.assertEqual(ctx.get("display_name"), "Practice Draft")

    def test_context_toggle_keys_persist_in_workspace_blob(self) -> None:
        """Simulator/Live overrides are account-owned — not restored from full_session blob."""
        from unittest.mock import MagicMock

        from account_fantasy_preferences import ACCOUNT_OWNED_SESSION_KEYS
        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        self.assertIn(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, ACCOUNT_OWNED_SESSION_KEYS)
        self.assertIn(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, ACCOUNT_OWNED_SESSION_KEYS)

        session = _saved_context_session()
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        st = MagicMock()
        st.session_state = session
        blob = build_baseball_disk_state(st)
        # Account-owned toggles must not ride the workspace blob (prefs doc is source of truth).
        self.assertNotIn(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, blob)
        self.assertNotIn(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY, blob)
        restored: dict = {}
        st2 = MagicMock()
        st2.session_state = restored
        apply_baseball_disk_state(st2, blob)
        # Defaults may seed False later; the blob must not have carried True across.
        self.assertFalse(bool(restored.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY)))
    def test_simulator_unavailable_when_live_override_enabled(self) -> None:
        from fantasy_context_source import simulator_board_context_available

        session = _simulator_board_session()
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": "in_progress",
            "config": {"user_team": "Daniel"},
            "draft_board": [{"Team": "Daniel", "Player": "Aaron Judge"}],
        }
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = True
        self.assertFalse(simulator_board_context_available(session))

    def test_natural_simulator_without_override_is_generic(self) -> None:
        session = _simulator_board_session()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session.pop("fantasy_league_context_state", None)
        session.pop("draft_archive_teams", None)
        session.pop("active_draft_archive_id", None)
        from fantasy_context_source import SOURCE_GENERIC

        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_GENERIC)

    def test_active_draft_blocks_natural_simulator_without_override(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_ACTIVE_DRAFT)

    def test_persisted_checkbox_seeds_widget_from_persisted_key(self) -> None:
        from fantasy_context_source import USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY
        from fantasy_context_ui import (
            _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
            _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
            render_fantasy_context_sync_control,
        )

        session: dict = {
            USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
            "use_active_league_context_waiver_filter": True,
        }
        st = MagicMock()
        st.markdown = MagicMock()
        st.caption = MagicMock()
        st.checkbox = MagicMock(return_value=True)
        render_fantasy_context_sync_control(st, session)
        self.assertTrue(session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY])
        self.assertTrue(session[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY])
        for call in st.checkbox.call_args_list:
            self.assertNotIn("value", call.kwargs)

    def test_fantasy_context_using_caption_mutually_exclusive_labels(self) -> None:
        from fantasy_context_source import (
            SOURCE_SIMULATOR_BOARD,
            _active_draft_label,
            fantasy_context_using_caption,
            fantasy_context_using_display,
            resolve_fantasy_context_source,
        )

        session = _saved_context_session()
        session.update(_simulator_board_session())
        source = resolve_fantasy_context_source(session)
        self.assertEqual(source.kind, SOURCE_SIMULATOR_BOARD)
        display = fantasy_context_using_display(session)
        self.assertEqual(display["kind"], "temporary_simulator")
        caption = fantasy_context_using_caption(session)
        self.assertTrue(
            ("Temporary Simulator Board" in caption)
            or ("Temporary Draft Board" in caption),
            caption,
        )
        self.assertNotIn("Active Draft", caption)

        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        display = fantasy_context_using_display(session)
        self.assertEqual(display["kind"], "active_draft")
        active_caption = fantasy_context_using_caption(session)
        self.assertIn("Active Draft: Practice Draft", active_caption)
        self.assertNotIn("Temporary", active_caption)
        self.assertNotIn("unsaved", active_caption.lower())

    def test_active_draft_label_prefers_archive_name_over_ephemeral_display_name(self) -> None:
        from fantasy_context_source import _active_draft_label

        session = _saved_context_session()
        ctx = session["fantasy_league_context_state"]["contexts"]["ctx_practice"]
        ctx["display_name"] = "Draft Room Simulator Board (temporary / unsaved)"
        session["draft_archive_teams"] = [
            {
                "draft_id": "arch1",
                "draft_name": "Yahoo Fantasy — Team Daniel",
                "team_name": "Daniel",
                "league_context_id": "ctx_practice",
            }
        ]
        self.assertEqual(_active_draft_label(session, ctx), "Yahoo Fantasy — Team Daniel")

    def test_fantasy_context_using_html_active_and_temporary_cards(self) -> None:
        from fantasy_context_source import fantasy_context_using_html

        session = _saved_context_session()
        active_html = fantasy_context_using_html(session)
        self.assertIn("fantasy-source-card-active", active_html)
        self.assertIn("Active Draft", active_html)
        self.assertIn("Practice Draft", active_html)
        self.assertIn("Daniel", active_html)
        self.assertNotIn("Temporary Practice Board", active_html)

        session.update(_simulator_board_session())
        temp_html = fantasy_context_using_html(session)
        self.assertIn("fantasy-source-card-temporary", temp_html)
        self.assertTrue(
            ("Temporary Practice Board" in temp_html)
            or ("Temporary Draft Board" in temp_html),
            temp_html,
        )
        self.assertTrue(
            ("Draft Room Simulator" in temp_html) or ("Simulator" in temp_html),
            temp_html,
        )
        self.assertNotIn("fantasy-source-card-active", temp_html)

    def test_streamlit_app_has_no_active_fantasy_team_caption_calls(self) -> None:
        """Regression: bare active_fantasy_team_caption() calls caused NameError on deployed builds."""
        from pathlib import Path

        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        source = app_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "active_fantasy_team_caption(",
            source,
            "streamlit_app.py must not call active_fantasy_team_caption(); use render_fantasy_using_caption or fantasy_context_using_caption",
        )

    def test_checkbox_on_change_syncs_persisted_key(self) -> None:
        from fantasy_context_ui import (
            USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
            _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
            _sync_persisted_context_toggles_from_widgets,
        )

        session: dict = {_SIM_CONTEXT_TOGGLE_WIDGET_KEY: True}
        _sync_persisted_context_toggles_from_widgets(session)
        self.assertTrue(session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY])


class FantasyContextRoutingTests(unittest.TestCase):
    def _live_room_session(self, *, status: str = "in_progress") -> dict:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": status,
            "config": {"user_team": "Daniel", "fantasy_format": "5x5 Roto"},
            "draft_board": [{"Team": "Daniel", "Player": "Aaron Judge"}],
            "teams": ["Daniel", "Rivals"],
        }
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = True
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        return session

    def test_active_draft_feeds_das_without_research_sync(self) -> None:
        """Fantasy tools (DAS) follow Effective Source — Research Mode is not required."""
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        self.assertTrue(fantasy_context_applies_to_page(session, "Waiver Wire"))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, "Trend Value"))
        self.assertEqual(draft_assistant_context_mode(session), "active_draft")

    def test_active_draft_research_pages_require_research_sync(self) -> None:
        session = _saved_context_session()
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, "Valuation"))
        self.assertEqual(draft_assistant_context_mode(session), "active_draft")

    def test_simulator_override_management_only_without_research_sync(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_SIMULATOR_BOARD)
        self.assertTrue(fantasy_context_applies_to_page(session, "Trades"))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, "Rankings"))
        self.assertEqual(draft_assistant_context_mode(session), "simulator_board")
        self.assertTrue(simulator_feeds_draft_assistant(session))

    def test_natural_simulator_without_override_does_not_feed_fantasy_pages(self) -> None:
        """Simulator sandbox never auto-becomes effective source without Override."""
        from fantasy_context_source import SOURCE_GENERIC

        session = _simulator_board_session()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session.pop("fantasy_league_context_state", None)
        session.pop("draft_archive_teams", None)
        session.pop("active_draft_archive_id", None)
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_GENERIC)
        self.assertFalse(simulator_feeds_draft_assistant(session))
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertEqual(draft_assistant_context_mode(session), "none")

    def test_simulator_override_required_for_research_feed(self) -> None:
        session = _simulator_board_session()
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        session.pop("fantasy_league_context_state", None)
        session.pop("draft_archive_teams", None)
        session.pop("active_draft_archive_id", None)
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_SIMULATOR_BOARD)
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, "Trend Value"))
        self.assertEqual(draft_assistant_context_mode(session), "simulator_board")

    def test_simulator_override_feeds_research_with_research_sync(self) -> None:
        session = _saved_context_session()
        session.update(_simulator_board_session())
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, "Comparison Tool"))

    def test_live_override_feeds_das_without_research_sync_while_in_progress(self) -> None:
        session = self._live_room_session(status="in_progress")
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        self.assertTrue(is_live_draft_in_progress(session))
        self.assertTrue(live_draft_feeds_draft_assistant(session))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, "Trend Value"))
        self.assertEqual(draft_assistant_context_mode(session), "live_board")

    def test_completed_live_draft_stops_das_special_case_without_research_sync(self) -> None:
        session = self._live_room_session(status="complete")
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        self.assertFalse(is_live_draft_in_progress(session))
        self.assertFalse(live_draft_feeds_draft_assistant(session))
        self.assertFalse(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertEqual(draft_assistant_context_mode(session), "none")

    def test_live_override_feeds_broader_research_only_with_research_sync(self) -> None:
        session = self._live_room_session(status="in_progress")
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, "Fantasy Sleepers & Busts"))


class DraftFingerprintDedupeTests(unittest.TestCase):
    def _board(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Round": [1, 1, 2, 2],
                "Pick": [1, 2, 3, 4],
                "Team": ["Daniel", "Rivals", "Daniel", "Rivals"],
                "Player": ["Aaron Judge", "Juan Soto", "Mike Trout", "Mookie Betts"],
            }
        )

    def test_repeated_save_reuses_single_archive(self) -> None:
        session: dict = {"draft_shared_settings": {"fantasy_format": "5x5 Roto"}, "room_your_team": "Daniel"}
        board = self._board()
        entry1, _ = save_simulator_league_context(session, board, my_team_name="Daniel", draft_name="League A")
        entry2, _ = save_simulator_league_context(session, board, my_team_name="Daniel", draft_name="League A again")
        self.assertEqual(entry1.get("draft_id"), entry2.get("draft_id"))
        archives = session.get("draft_archive_teams") or []
        self.assertEqual(len(archives), 1)

    def test_resolve_canonical_save_ids_stable_for_same_rosters(self) -> None:
        session: dict = {}
        board = self._board()
        rosters = build_league_rosters_from_simulator_board(board, "Daniel")
        fp1 = compute_save_draft_fingerprint(league_rosters=rosters, config={"fantasy_format": "5x5 Roto"})
        fp2 = compute_save_draft_fingerprint(league_rosters=rosters, config={"fantasy_format": "5x5 Roto"})
        self.assertEqual(fp1, fp2)
        self.assertTrue(fp1)


if __name__ == "__main__":
    unittest.main()
