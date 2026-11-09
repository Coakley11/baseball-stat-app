"""Live Draft → Simulator handoff, Restore Previous Mock Draft, and hypothetical continuation
(owner workflow brief, 2026-11-09, items 1-5 and 7)."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_room_state import (
    DRAFT_ROOM_TABLE_KEY,
    apply_programmatic_board_update,
    coerce_board_table,
    ensure_live_draft_synced_to_canonical_board,
    sync_live_draft_room_to_canonical_board,
    undo_last_simulator_pick,
)
from simulator_board_edit import (
    add_board_rounds,
    board_provenance,
    pad_partial_last_round,
    pick_origin_labels,
    replace_board_pick,
)
from simulator_board_history import (
    LIVE_HANDOFF_KEY,
    PREVIOUS_BOARDS_KEY,
    list_previous_boards,
    restore_previous_board,
)

LIVE = ["Aaron Judge", "Francisco Lindor", "Juan Soto", "Ronald Acuna"]
MOCK = ["Mookie Betts", "Freddie Freeman", "Shohei Ohtani", "Kyle Tucker",
        "Corey Seager", "Pete Alonso", "Bobby Witt Jr.", "Gunnar Henderson"]


def _snake(teams: list[str], rounds: int, players: list[str]) -> pd.DataFrame:
    rows, pick = [], 1
    for rnd in range(1, rounds + 1):
        for team in (teams if rnd % 2 else list(reversed(teams))):
            rows.append({"Round": rnd, "Pick": pick, "Team": team,
                         "Player": players[pick - 1] if pick <= len(players) else ""})
            pick += 1
    return pd.DataFrame(rows)


def _room(status: str, picks: int = 4, room_id: str = "room-qa-1") -> dict:
    order = _snake(["Dave", "Barry"], 2, [])
    return {
        "draft_room_id": room_id,
        "status": status,
        "teams": ["Dave", "Barry"],
        "config": {"picks_per_team": 2, "user_team": "Dave"},
        "pick_order": [{"Round": r.Round, "Pick": r.Pick, "Team": r.Team} for r in order.itertuples()],
        "draft_board": [
            {"Pick": r.Pick, "Round": r.Round, "Team": r.Team, "fullName": LIVE[r.Pick - 1],
             "playerID": f"id{r.Pick}"}
            for r in order.itertuples() if r.Pick <= picks
        ],
    }


def _session_with_mock(user: str = "qa-user-a") -> dict:
    session: dict = {"_suite_auth_user_id": user, "room_team_names": "Ann\nBen\nCal\nDee", "room_rounds": 3,
                     "room_team_count": 4}
    apply_programmatic_board_update(session, _snake(["Ann", "Ben", "Cal", "Dee"], 3, MOCK), reason="draft_room_pick")
    return session


def _players(session: dict) -> list[str]:
    t = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    return [p for p in t["Player"].astype(str).tolist() if p.strip()]


class HandoffKeepsThePreviousBoard(unittest.TestCase):
    def test_live_draft_takes_board_and_keeps_unfinished_mock(self) -> None:
        session = _session_with_mock()
        room = _room("in_progress", picks=2)
        session["live_draft_room"] = room
        sync_live_draft_room_to_canonical_board(session, room)
        self.assertEqual(_players(session), LIVE[:2])
        kept = list_previous_boards(session)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["pick_count"], 8)
        self.assertEqual(kept[0]["teams"], ["Ann", "Ben", "Cal", "Dee"])
        # More picks in the same room do not add more copies.
        room = _room("in_progress", picks=3)
        session["live_draft_room"] = room
        sync_live_draft_room_to_canonical_board(session, room)
        self.assertEqual(len(list_previous_boards(session)), 1)

    def test_completed_live_draft_hands_off_once_even_over_a_different_board(self) -> None:
        session = _session_with_mock()
        room = _room("complete")
        session["live_draft_room"] = room
        ensure_live_draft_synced_to_canonical_board(session, reason="test")
        self.assertEqual(_players(session), LIVE)
        self.assertEqual(list_previous_boards(session)[0]["pick_count"], 8)
        self.assertEqual(board_provenance(session)["kind"], "live_draft")

    def test_restore_previous_mock_and_no_stale_resync(self) -> None:
        session = _session_with_mock()
        room = _room("complete")
        session["live_draft_room"] = room
        ensure_live_draft_synced_to_canonical_board(session, reason="test")
        entry = list_previous_boards(session)[0]
        res = restore_previous_board(session, entry["entry_id"])
        self.assertTrue(res["ok"], res)
        self.assertEqual(_players(session), MOCK)
        self.assertEqual(session["room_team_names"], "Ann\nBen\nCal\nDee")
        # The Live Draft board it replaced is now the one kept, so nothing is destroyed.
        kept = list_previous_boards(session)
        self.assertEqual([e["pick_count"] for e in kept], [4])
        # Reruns and background syncs do not switch back to the Live Draft.
        for _ in range(3):
            ensure_live_draft_synced_to_canonical_board(session, reason="rerun")
            sync_live_draft_room_to_canonical_board(session, room)
        self.assertEqual(_players(session), MOCK)
        # The completed Live Draft itself is untouched.
        self.assertEqual([r["fullName"] for r in room["draft_board"]], LIVE)
        self.assertEqual(room["status"], "complete")

    def test_restore_is_blocked_while_live_draft_runs(self) -> None:
        session = _session_with_mock()
        room = _room("in_progress", picks=2)
        session["live_draft_room"] = room
        sync_live_draft_room_to_canonical_board(session, room)
        res = restore_previous_board(session, list_previous_boards(session)[0]["entry_id"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "live_draft_in_progress")
        self.assertEqual(_players(session), LIVE[:2])

    def test_kept_boards_are_account_scoped(self) -> None:
        session = _session_with_mock("qa-user-a")
        room = _room("complete")
        session["live_draft_room"] = room
        ensure_live_draft_synced_to_canonical_board(session, reason="test")
        entry_id = list_previous_boards(session)[0]["entry_id"]
        session["_suite_auth_user_id"] = "qa-user-b"
        self.assertEqual(list_previous_boards(session), [])
        self.assertFalse(restore_previous_board(session, entry_id)["ok"])

    def test_history_keys_are_saved_with_the_workspace(self) -> None:
        from baseball_persistent_state import _WORKFLOW_KEYS
        from workspace_cloud_guard import BOARD_MUTATION_REASONS, PROTECTED_WORKSPACE_KEYS

        for key in (PREVIOUS_BOARDS_KEY, LIVE_HANDOFF_KEY, "live_draft_override_snapshot"):
            self.assertIn(key, _WORKFLOW_KEYS)
        self.assertIn(PREVIOUS_BOARDS_KEY, PROTECTED_WORKSPACE_KEYS)
        self.assertIn("restore_previous_board", BOARD_MUTATION_REASONS)


class HypotheticalContinuation(unittest.TestCase):
    def _handed_off(self) -> tuple[dict, dict]:
        session: dict = {"_suite_auth_user_id": "qa-user-a"}
        room = _room("complete")
        session["live_draft_room"] = room
        ensure_live_draft_synced_to_canonical_board(session, reason="test")
        return session, room

    def test_replacing_a_pick_forks_and_labels_picks(self) -> None:
        session, room = self._handed_off()
        res = replace_board_pick(session, pick_number=1, player_name="Mookie Betts")
        self.assertTrue(res["ok"], res)
        prov = board_provenance(session)
        self.assertEqual(prov["kind"], "hypothetical")
        self.assertEqual(prov["changed_picks"], [1])
        labels = pick_origin_labels(session)
        self.assertEqual(labels[1], "Hypothetical")
        self.assertEqual(labels[2], "Live Draft")
        self.assertTrue(session[LIVE_HANDOFF_KEY]["forked"])
        ensure_live_draft_synced_to_canonical_board(session, reason="rerun")
        self.assertEqual(_players(session)[0], "Mookie Betts")
        self.assertEqual([r["fullName"] for r in room["draft_board"]], LIVE)

    def test_soto_instead_of_judge(self) -> None:
        session, _ = self._handed_off()
        self.assertFalse(replace_board_pick(session, pick_number=1, player_name="Juan Soto")["ok"])  # on pick 3
        self.assertTrue(replace_board_pick(session, pick_number=3, player_name="Mookie Betts")["ok"])
        self.assertTrue(replace_board_pick(session, pick_number=1, player_name="Juan Soto")["ok"])
        players = _players(session)
        self.assertIn("Juan Soto", players)
        self.assertNotIn("Aaron Judge", players)
        # Draft Assistant (Simulator Override) now treats Soto as drafted and Judge as available.
        from draft_assistant_board import board_player_keys, exclude_drafted_players, resolve_draft_assistant_board

        board = resolve_draft_assistant_board(session, context_mode="simulator_board")["board"]
        ids, names = board_player_keys(board)
        pool = pd.DataFrame({"fullName": ["Aaron Judge", "Juan Soto"], "playerID": ["x1", "x2"]})
        self.assertEqual(exclude_drafted_players(pool, names=names, ids=ids)["fullName"].tolist(), ["Aaron Judge"])

    def test_add_round_continues_snake_order(self) -> None:
        session, _ = self._handed_off()
        res = add_board_rounds(session, 1)
        self.assertTrue(res["ok"], res)
        t = coerce_board_table(session[DRAFT_ROOM_TABLE_KEY])
        self.assertEqual(len(t), 6)
        new = t[t["Round"] == 3]
        self.assertEqual(new["Pick"].tolist(), [5, 6])
        self.assertEqual(new["Team"].tolist(), ["Dave", "Barry"])
        self.assertEqual(session["room_rounds"], 3)
        self.assertEqual(board_provenance(session)["kind"], "hypothetical")
        from draft_room_state import ensure_simulator_board_for_settings

        ensure_simulator_board_for_settings(session)
        self.assertEqual(len(coerce_board_table(session[DRAFT_ROOM_TABLE_KEY])), 6)

    def test_undo_on_finished_live_board_is_hypothetical(self) -> None:
        from simulator_board_edit import fork_if_live_board

        session, room = self._handed_off()
        fork_if_live_board(session, reason="undo_last_pick")
        self.assertTrue(undo_last_simulator_pick(session)["ok"])
        self.assertEqual(_players(session), LIVE[:3])
        ensure_live_draft_synced_to_canonical_board(session, reason="rerun")
        self.assertEqual(_players(session), LIVE[:3])
        self.assertEqual(len(room["draft_board"]), 4)


class ImportedBoardsContinue(unittest.TestCase):
    def test_ten_of_twelve_picks_opens_eleven_and_twelve(self) -> None:
        teams = ["T1", "T2", "T3", "T4", "T5", "T6"]
        imported = _snake(teams, 2, [f"P{i}" for i in range(1, 11)]).iloc[:10]
        padded = pad_partial_last_round(imported)
        self.assertEqual(len(padded), 12)
        self.assertEqual(padded["Player"].tolist()[:10], [f"P{i}" for i in range(1, 11)])
        tail = padded.iloc[10:]
        self.assertEqual(tail["Pick"].tolist(), [11, 12])
        self.assertEqual(tail["Team"].tolist(), ["T2", "T1"])  # snake round 2
        self.assertEqual(tail["Player"].tolist(), ["", ""])

    def test_full_rounds_are_not_padded(self) -> None:
        board = _snake(["A", "B"], 2, ["p1", "p2", "p3", "p4"])
        self.assertEqual(len(pad_partial_last_round(board)), 4)


class LiveRecordIsNeverRewritten(unittest.TestCase):
    def test_mock_save_with_identical_picks_creates_its_own_entry(self) -> None:
        from draft_archive_state import DRAFT_TYPE_LIVE, DRAFT_TYPE_SIMULATOR, list_draft_archives, save_draft_archive

        session: dict = {"_suite_auth_user_id": "qa-user-a"}
        rosters = {"Dave": {"team_name": "Dave", "players": [{"player_name": "Aaron Judge", "player_key": "aaron judge"}]}}
        live = save_draft_archive(session, draft_type=DRAFT_TYPE_LIVE, draft_name="QA Live", team_name="Dave",
                                  config={}, roster_rows=[], pick_rows=[], draft_board_rows=[],
                                  league_rosters=rosters)
        mock = save_draft_archive(session, draft_type=DRAFT_TYPE_SIMULATOR, draft_name="QA Mock", team_name="Dave",
                                  config={}, roster_rows=[], pick_rows=[], draft_board_rows=[],
                                  league_rosters=rosters)
        self.assertNotEqual(live["draft_id"], mock["draft_id"])
        by_id = {e["draft_id"]: e for e in list_draft_archives(session)}
        self.assertEqual(by_id[live["draft_id"]]["draft_type"], DRAFT_TYPE_LIVE)
        self.assertEqual(by_id[live["draft_id"]]["draft_name"], "QA Live")


class MockPickBesideFinishedLiveDraft(unittest.TestCase):
    def test_a_mock_pick_marks_the_finished_live_draft_as_superseded(self) -> None:
        from simulator_board_history import LIVE_HANDOFF_KEY, before_live_board_mirror, note_mock_pick_beside_finished_live

        session = {"live_draft_room": {"draft_room_id": "room-x", "status": "complete", "draft_board": [{"Pick": 1}]}}
        note_mock_pick_beside_finished_live(session)
        self.assertTrue(session[LIVE_HANDOFF_KEY]["superseded"])
        self.assertFalse(before_live_board_mirror(session, session["live_draft_room"]))

    def test_an_in_progress_room_is_left_alone(self) -> None:
        from simulator_board_history import LIVE_HANDOFF_KEY, note_mock_pick_beside_finished_live

        session = {"live_draft_room": {"draft_room_id": "room-x", "status": "in_progress"}}
        note_mock_pick_beside_finished_live(session)
        self.assertNotIn(LIVE_HANDOFF_KEY, session)


class RuntimeClearsKeepThisAccountsHistory(unittest.TestCase):
    """Browser QA 2026-11-09: creating a Shared room, or a board-ownership re-check after Reset,
    erased the kept boards and the handoff record, so an unsaved mock was lost and a finished
    Live Draft took the board again."""

    def test_creating_a_shared_room_keeps_the_mock_restorable(self) -> None:
        from live_draft_navigation import clear_private_baseball_simulator_runtime

        session = _session_with_mock()
        clear_private_baseball_simulator_runtime(session, reason="shared_room_create")
        kept = list_previous_boards(session)
        self.assertEqual([k["pick_count"] for k in kept], [8])

    def test_an_ownership_recheck_keeps_history_and_handoff(self) -> None:
        from live_draft_navigation import clear_private_baseball_simulator_runtime
        from simulator_board_history import before_live_board_mirror

        session = _session_with_mock()
        room = _room("complete")
        session["live_draft_room"] = room
        ensure_live_draft_synced_to_canonical_board(session, reason="test")  # handoff; mock kept
        clear_private_baseball_simulator_runtime(session, reason="legacy_unowned_board_rejected")
        self.assertIn(LIVE_HANDOFF_KEY, session)
        self.assertEqual(len(list_previous_boards(session)), 1)
        # The cleared (reset) board is not the handed-off one, so the finished Live Draft stays out.
        apply_programmatic_board_update(session, _snake(["Ann", "Ben"], 20, []), reason="reset_simulator")
        self.assertFalse(before_live_board_mirror(session, room))

    def test_signing_out_still_drops_the_records(self) -> None:
        from live_draft_navigation import clear_private_baseball_simulator_runtime

        session = _session_with_mock()
        session["live_draft_room"] = _room("complete")
        ensure_live_draft_synced_to_canonical_board(session, reason="test")
        clear_private_baseball_simulator_runtime(session, reason="auth_sign_out")
        self.assertNotIn(PREVIOUS_BOARDS_KEY, session)
        self.assertNotIn(LIVE_HANDOFF_KEY, session)


if __name__ == "__main__":
    unittest.main()
