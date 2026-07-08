"""Fantasy context source-of-truth priority and fingerprint dedupe."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_context_source import (
    SOURCE_ACTIVE_DRAFT,
    SOURCE_LIVE_DRAFT,
    SOURCE_SIMULATOR_BOARD,
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    get_effective_fantasy_context,
    resolve_fantasy_context_source,
)
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
        self.assertIn("unsaved workspace", source.badge_text)

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

    def test_live_override_disabled_falls_back_to_simulator(self) -> None:
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
        self.assertEqual(source.kind, SOURCE_SIMULATOR_BOARD)

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
        from unittest.mock import MagicMock

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        session = _saved_context_session()
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        st = MagicMock()
        st.session_state = session
        blob = build_baseball_disk_state(st)
        restored: dict = {}
        st2 = MagicMock()
        st2.session_state = restored
        apply_baseball_disk_state(st2, blob)
        self.assertFalse(restored.get(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY))
        self.assertTrue(restored.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))

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
