"""Draft Room Simulator pick progression and persistence (hosted phone report 2026-10-26).

Reported: Team A picked, Team B was correctly on the clock, but on returning to the Draft
Board the pick control was gone and the board read as full. Cause: a finished Live Draft
left in the session was mirrored over the Simulator's board on every render (its 4-pick
board replaced the new 4-team x 5-round mock draft), and the Draft Player gate called the
mock draft complete because that Live Draft was.
"""

from __future__ import annotations

import json
import unittest
import unittest.mock

import draft_room_state as drs
from draft_actions import draft_action_context, resolve_player_draft_gate

TEAMS = ["Team A", "Team B", "Team C", "Team D"]
PLAYERS = [f"Player {i:02d}" for i in range(1, 21)]


def _session(**extra) -> dict:
    s = {"room_team_count": 4, "room_team_names": "\n".join(TEAMS), "room_rounds": 5, "room_your_team": "Team A"}
    s.update(extra)
    drs.ensure_simulator_board_for_settings(s)
    return s


def _pick(s: dict, player: str) -> str:
    df = drs.ensure_runtime_draft_board(s)
    label = drs.open_pick_row_options(df)[0][1]
    result = drs.submit_board_pick_assignment(
        s, pick_label=label, player_match=player, pick_row_by_label=drs.pick_label_row_map(df), all_names=PLAYERS
    )
    assert result.get("message", "").startswith("Set "), result
    return label


def _next(s: dict) -> str:
    opens = drs.open_pick_row_options(drs.ensure_runtime_draft_board(s))
    return opens[0][1] if opens else ""


def _completed_live_room() -> dict:
    board = [
        {"Fantasy Team": t, "fullName": p, "Pick": i + 1, "Round": i // 2 + 1, "playerID": f"id{i}"}
        for i, (t, p) in enumerate(
            [("Team A", "Aaron Judge"), ("Team B", "Juan Soto"), ("Team B", "Mike Trout"), ("Team A", "Mookie Betts")]
        )
    ]
    return {
        "draft_room_id": "solo-trial", "status": "complete", "teams": ["Team A", "Team B"],
        "config": {"num_teams": 2, "rounds": 2, "user_team": "Team A", "draft_name": "Trial draft"},
        "draft_board": board, "pick_order": [{"Team": r["Fantasy Team"], "Pick": r["Pick"]} for r in board],
        "current_pick_index": 4, "rosters": {"Team A": [], "Team B": []},
    }


class SnakeProgressionTests(unittest.TestCase):
    def test_four_teams_five_rounds_snake_until_twenty_picks(self) -> None:
        s = _session()
        expected = [f"Pick {n} — {t}" for n, t in zip(range(1, 21), (TEAMS + TEAMS[::-1]) * 3)]
        for n, player in enumerate(PLAYERS):
            self.assertEqual(_next(s), expected[n])
            self.assertFalse(draft_action_context(s).get("draft_complete"), f"complete after {n} picks")
            _pick(s, player)
        self.assertEqual(_next(s), "")
        self.assertTrue(draft_action_context(s).get("draft_complete"))
        self.assertEqual(drs.table_pick_count(drs.ensure_runtime_draft_board(s)), 20)

    def test_controller_records_every_teams_pick_on_the_board(self) -> None:
        s = _session()
        for player in PLAYERS[:4]:
            _pick(s, player)
        df = drs.ensure_runtime_draft_board(s).sort_values("Pick")
        self.assertEqual(df.head(4)["Team"].tolist(), TEAMS)
        self.assertEqual(df.head(4)["Player"].tolist(), PLAYERS[:4])


class FinishedLiveDraftConflictTests(unittest.TestCase):
    def test_finished_live_draft_does_not_replace_the_mock_draft(self) -> None:
        s = _session(live_draft_room=_completed_live_room())
        _pick(s, PLAYERS[0])
        drs.ensure_live_draft_synced_to_canonical_board(s, reason="session_draft_board_df")
        drs.prepare_draft_room_state(s)
        df = drs.ensure_runtime_draft_board(s)
        self.assertEqual(len(df), 20)
        self.assertEqual(drs.table_pick_count(df), 1)
        self.assertEqual(_next(s), "Pick 2 — Team B")

    def test_finished_live_draft_does_not_close_the_mock_drafts_draft_player(self) -> None:
        s = _session(live_draft_room=_completed_live_room())
        for player in PLAYERS[:4]:
            _pick(s, player)  # Pick 5 is Team D's (snake)
        s["room_your_team"] = "Team D"
        gate = resolve_player_draft_gate(s, "Player 05")
        self.assertNotEqual(gate.get("disable_message"), "Draft is complete.")
        self.assertEqual(gate.get("on_clock_team"), "Team D")


class SaveAsMockDraftTests(unittest.TestCase):
    def _save(self, s: dict) -> None:
        from draft_archive_ui import _execute_simulator_league_context_save

        class _St:
            session_state = s

            @staticmethod
            def toast(*_a, **_k):
                return None

        s["sim_draft_archive_name_input"] = "My mock"
        with unittest.mock.patch("draft_archive_ui._persist_archive", return_value=True):
            _execute_simulator_league_context_save(_St(), s, team_name="Team A", key_prefix="sim_draft_archive",
                                                   save_only=True)

    def test_resaving_updates_one_mock_draft_and_a_reset_starts_another(self) -> None:
        from draft_archive_state import draft_type_display, list_draft_archives

        s = _session()
        for player in PLAYERS[:2]:
            _pick(s, player)
        self._save(s)
        _pick(s, PLAYERS[2])
        self._save(s)
        archives = list_draft_archives(s)
        self.assertEqual(len(archives), 1)
        self.assertEqual(draft_type_display(archives[0]), "Mock Draft")
        filled = [r for r in archives[0].get("draft_board") or [] if str(r.get("Player") or "").strip()]
        self.assertEqual([r["Player"] for r in sorted(filled, key=lambda r: int(r["Pick"]))], PLAYERS[:3])
        self.assertIn("as a Mock Draft", (s.get("_draft_save_ui_flash") or {}).get("message", ""))

        drs.reset_simulator_board_only(s)
        _pick(s, PLAYERS[5])
        self._save(s)
        self.assertEqual(len(list_draft_archives(s)), 2)


class PersistenceTests(unittest.TestCase):
    def test_picks_and_clock_survive_a_save_and_restore(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        class _St:
            def __init__(self, ss):
                self.session_state = ss

        s = _session()
        for player in PLAYERS[:6]:
            _pick(s, player)
        blob = json.loads(json.dumps(build_baseball_disk_state(_St(s)), default=str))
        restored: dict = {}
        apply_baseball_disk_state(_St(restored), blob)
        drs.prepare_draft_room_state(restored)
        df = drs.ensure_runtime_draft_board(restored).sort_values("Pick")
        self.assertEqual(drs.table_pick_count(df), 6)
        self.assertEqual(df.head(6)["Player"].tolist(), PLAYERS[:6])
        self.assertEqual(_next(restored), "Pick 7 — Team B")


if __name__ == "__main__":
    unittest.main()
