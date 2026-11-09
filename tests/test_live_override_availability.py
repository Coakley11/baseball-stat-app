"""Effective draft source drives availability (owner workflow brief, 2026-11-09, items 6-9).

- Live Draft Override ON: the selected Live Draft (in progress, paused or completed) is
  authoritative; every player on it is unavailable in Draft Assistant.
- Simulator Override ON: the current Simulator working board is authoritative.
- Neither: the Saved Active Draft / League.
- A larger board from another source never replaces the effective one.
- Research Mode only gates the Insights pages; Draft Assistant always excludes drafted players.
- Historical pages are never filtered.
"""

from __future__ import annotations

import unittest

import pandas as pd

from draft_assistant_board import (
    board_player_keys,
    exclude_drafted_players,
    resolve_draft_assistant_board,
)
from fantasy_context_source import (
    DRAFT_ASSISTANT_PAGE,
    LIVE_OVERRIDE_SNAPSHOT_KEY,
    SOURCE_ACTIVE_DRAFT,
    SOURCE_LIVE_DRAFT,
    SOURCE_SIMULATOR_BOARD,
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    draft_assistant_context_mode,
    fantasy_drafted_pool_filter_applies,
    resolve_fantasy_context_source,
    resolve_live_override_room,
)
from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY

LIVE_PICKS = [
    {"Pick": 1, "Round": 1, "Team": "Dave", "fullName": "Aaron Judge", "playerID": "judgeaa01"},
    {"Pick": 2, "Round": 1, "Team": "Barry", "fullName": "Francisco Lindor", "playerID": "lindofr01"},
    {"Pick": 3, "Round": 2, "Team": "Barry", "fullName": "Juan Soto", "playerID": "sotoju01"},
    {"Pick": 4, "Round": 2, "Team": "Dave", "fullName": "Ronald Acuna", "playerID": "acunaro01"},
]


def _saved_league(players: list[str]) -> dict:
    return {
        "fantasy_league_context_state": {
            "active_league_context_id": "ctx_old",
            "contexts": {
                "ctx_old": {
                    "league_context_id": "ctx_old",
                    "display_name": "Old Saved League",
                    "my_team_name": "Dave",
                    "fantasy_format": "5x5 Roto",
                    "league_rosters": {
                        "Dave": {
                            "team_name": "Dave",
                            "is_user_team": True,
                            "players": [{"player_name": p, "player_key": p.lower()} for p in players],
                        }
                    },
                }
            },
        },
    }


def _live_session(*, status: str = "complete", override: bool = True) -> dict:
    session = _saved_league(["Mookie Betts", "Freddie Freeman", "Shohei Ohtani", "Bobby Witt Jr.",
                             "Corey Seager", "Kyle Tucker"])
    session.update(
        {
            "_suite_auth_user_id": "qa-user-a",
            "live_draft_room": {
                "draft_room_id": "room-qa-1",
                "status": status,
                "config": {"user_team": "Dave", "fantasy_format": "5x5 Roto", "league_name": "QA League"},
                "teams": ["Dave", "Barry"],
                "pick_order": [{"Pick": i + 1, "Team": t} for i, t in enumerate(["Dave", "Barry", "Barry", "Dave"])],
                "draft_board": [dict(r) for r in LIVE_PICKS],
            },
            USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: override,
            USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
            FANTASY_RESEARCH_SYNC_KEY: False,
        }
    )
    return session


def _sim_table(players: list[str]) -> pd.DataFrame:
    teams = ["Dave", "Barry"]
    return pd.DataFrame(
        {
            "Pick": list(range(1, len(players) + 1)),
            "Round": [i // 2 + 1 for i in range(len(players))],
            "Team": [teams[i % 2] for i in range(len(players))],
            "Player": players,
        }
    )


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fullName": ["Aaron Judge", "Francisco Lindor", "Juan Soto", "Ronald Acuña Jr.",
                         "Mookie Betts", "Gunnar Henderson"],
            "playerID": ["judgeaa01", "lindofr01", "sotoju01", "acunaro01", "bettsmo01", "hendegu01"],
        }
    )


class LiveDraftOverrideIsAuthoritative(unittest.TestCase):
    def test_completed_live_draft_feeds_draft_assistant_under_override(self) -> None:
        session = _live_session(status="complete")
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_LIVE_DRAFT)
        self.assertEqual(draft_assistant_context_mode(session), "live_board")
        self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE))

    def test_paused_and_in_progress_live_draft_feed_draft_assistant(self) -> None:
        for status in ("in_progress", "paused"):
            session = _live_session(status=status)
            self.assertEqual(draft_assistant_context_mode(session), "live_board", status)

    def test_completed_live_draft_without_override_uses_saved_active_league(self) -> None:
        session = _live_session(status="complete", override=False)
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_ACTIVE_DRAFT)
        self.assertEqual(draft_assistant_context_mode(session), "active_draft")

    def test_live_board_ignores_larger_saved_league_and_simulator_board(self) -> None:
        session = _live_session(status="complete")
        session["draft_room_table"] = _sim_table(
            ["Mookie Betts", "Freddie Freeman", "Shohei Ohtani", "Kyle Tucker", "Corey Seager", "Pete Alonso"]
        )
        res = resolve_draft_assistant_board(
            session,
            live_room=resolve_live_override_room(session),
            context_mode=draft_assistant_context_mode(session),
            active_archive={"draft_id": "old", "snapshot": {"draft_board": [
                {"Pick": i, "Team": "Dave", "Player": f"Old Player {i}"} for i in range(1, 9)
            ]}},
        )
        players = sorted(res["board"]["Player"].tolist())
        self.assertEqual(players, sorted(r["fullName"] for r in LIVE_PICKS))
        self.assertEqual(res["diagnostics"]["board_source_used"], "live_room_draft_board")

    def test_override_survives_cleared_room_via_account_snapshot(self) -> None:
        session = _live_session(status="complete")
        resolve_fantasy_context_source(session)  # remembers the Live Draft it reads
        self.assertIn(LIVE_OVERRIDE_SNAPSHOT_KEY, session)
        session.pop("live_draft_room")  # e.g. the commissioner ended the room
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_LIVE_DRAFT)
        self.assertEqual(draft_assistant_context_mode(session), "live_board")
        room = resolve_live_override_room(session)
        self.assertEqual([r["fullName"] for r in room["draft_board"]], [r["fullName"] for r in LIVE_PICKS])
        self.assertNotIn("pool", room.get("config") or {})

    def test_snapshot_never_crosses_accounts(self) -> None:
        session = _live_session(status="complete")
        resolve_fantasy_context_source(session)
        session.pop("live_draft_room")
        session["_suite_auth_user_id"] = "qa-user-b"
        self.assertIsNone(resolve_live_override_room(session))
        # Account B never reads account A's remembered Live Draft; with no Live Draft of its own
        # loaded, B gets its own Saved Active Draft.
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_ACTIVE_DRAFT)

    def test_turning_override_off_forgets_snapshot(self) -> None:
        from fantasy_context_ui import _LIVE_CONTEXT_TOGGLE_WIDGET_KEY, apply_live_override_toggle_from_widget

        session = _live_session(status="complete")
        resolve_fantasy_context_source(session)
        session[_LIVE_CONTEXT_TOGGLE_WIDGET_KEY] = False
        apply_live_override_toggle_from_widget(session)
        self.assertNotIn(LIVE_OVERRIDE_SNAPSHOT_KEY, session)
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_ACTIVE_DRAFT)


class SimulatorOverrideIsAuthoritative(unittest.TestCase):
    def _session(self, players: list[str]) -> dict:
        session = _saved_league(["Mookie Betts"] * 1 + [f"Saved Player {i}" for i in range(10)])
        session.update(
            {
                "draft_room_table": _sim_table(players),
                USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
                USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
                FANTASY_RESEARCH_SYNC_KEY: False,
            }
        )
        return session

    def test_simulator_board_beats_larger_saved_league(self) -> None:
        session = self._session(["Juan Soto", "Mookie Betts"])
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_SIMULATOR_BOARD)
        res = resolve_draft_assistant_board(session, context_mode=draft_assistant_context_mode(session))
        self.assertEqual(sorted(res["board"]["Player"].tolist()), ["Juan Soto", "Mookie Betts"])

    def test_replacing_a_hypothetical_pick_misses_the_cache(self) -> None:
        session = self._session(["Aaron Judge", "Mookie Betts"])
        first = resolve_draft_assistant_board(session, context_mode="simulator_board")
        self.assertIn("Aaron Judge", first["board"]["Player"].tolist())
        from draft_room_state import apply_programmatic_board_update

        # The app's own edit path, same number of picks.
        apply_programmatic_board_update(session, _sim_table(["Juan Soto", "Mookie Betts"]), reason="qa_replace_pick")
        second = resolve_draft_assistant_board(session, context_mode="simulator_board")
        self.assertIn("Juan Soto", second["board"]["Player"].tolist())
        self.assertNotIn("Aaron Judge", second["board"]["Player"].tolist())


class StableIdExclusion(unittest.TestCase):
    def test_ids_catch_name_variations(self) -> None:
        board = pd.DataFrame(LIVE_PICKS).rename(columns={"fullName": "Player"})
        ids, names = board_player_keys(board)
        available = exclude_drafted_players(_pool(), names=names, ids=ids)
        self.assertEqual(sorted(available["fullName"]), ["Gunnar Henderson", "Mookie Betts"])

    def test_names_without_ids_still_exclude_with_normalisation(self) -> None:
        available = exclude_drafted_players(_pool(), names={"Ronald Acuna", "Juan Soto"}, ids=set())
        self.assertNotIn("Ronald Acuña Jr.", available["fullName"].tolist())
        self.assertNotIn("Juan Soto", available["fullName"].tolist())
        self.assertIn("Aaron Judge", available["fullName"].tolist())


class ResearchModeGatesOnlyInsights(unittest.TestCase):
    INSIGHTS = ("Trend Value", "Valuation", "Fantasy Sleepers & Busts", "Comparison Tool")
    HISTORICAL = ("Historical Explorer", "Career Totals", "Leaderboards", "Statistical Leaderboards")

    def _sources(self) -> dict[str, dict]:
        live = _live_session(status="complete")
        sim = _saved_league(["Mookie Betts"])
        sim.update({"draft_room_table": _sim_table(["Juan Soto"]),
                    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
                    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False})
        saved = _saved_league(["Mookie Betts"])
        saved.update({USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
                      USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False})
        return {"live": live, "simulator": sim, "active": saved}

    def test_matrix_three_sources_two_toggle_states(self) -> None:
        for name, session in self._sources().items():
            for research_on in (True, False):
                session[FANTASY_RESEARCH_SYNC_KEY] = research_on
                label = f"{name} research={research_on}"
                self.assertTrue(fantasy_drafted_pool_filter_applies(session, DRAFT_ASSISTANT_PAGE), label)
                for page in self.INSIGHTS:
                    self.assertEqual(fantasy_drafted_pool_filter_applies(session, page), research_on, f"{label} {page}")
                for page in self.HISTORICAL:
                    self.assertFalse(fantasy_drafted_pool_filter_applies(session, page), f"{label} {page}")

    def test_insights_use_the_live_draft_not_a_moved_on_simulator_board(self) -> None:
        from active_team_context import resolve_active_team_context

        session = _live_session(status="complete")
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        session["draft_room_table"] = _sim_table(["Mookie Betts", "Freddie Freeman"])  # a restored mock
        ctx = resolve_active_team_context(session)
        self.assertEqual(sorted(ctx.drafted_names), sorted(r["fullName"] for r in LIVE_PICKS))
        self.assertTrue(ctx.is_unavailable("Ronald Acuña Jr."))
        self.assertFalse(ctx.is_unavailable("Mookie Betts"))


if __name__ == "__main__":
    unittest.main()
