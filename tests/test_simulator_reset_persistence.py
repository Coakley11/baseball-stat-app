"""Reset Draft Room Simulator after a completed Live Draft (owner decision 2026-11-10).

Browser QA traced the old picks returning after Reset to the storage layer: every full-session
write keeps a richer stored board over an empty incoming one, so the approved reset write was
merged back to the Live Draft board, and every later save copied it again. A reset the cloud
guard approves is now stamped, and the storage merge honours a new stamp (only that write).
"""

from __future__ import annotations

import copy
import unittest

import suite_cloud_state as scs
import suite_storage_supabase as sss
from tests.test_workspace_cloud_guard import TS, GuardTests, Store, _board
from workspace_cloud_guard import (
    BOARD_RESET_MARKER_KEY,
    authorize_explicit_reset,
    filled_pick_count,
    note_cloud_revision_seen,
)


class StorageMergingStore(Store):
    """Fake store that applies the production full-session merge on every write."""

    def save_current_state(self, app_key, *, page, summary, metrics, skip_metrics_merge_read=False, expected_updated_at=None):
        prior = copy.deepcopy(self.blob) if isinstance(self.blob, dict) else {}
        metrics = dict(metrics)
        metrics[scs.FULL_SESSION_KEY] = sss._merge_full_session_preserve_richer_draft(
            prior, metrics[scs.FULL_SESSION_KEY]
        )
        return super().save_current_state(
            app_key,
            page=page,
            summary=summary,
            metrics=metrics,
            skip_metrics_merge_read=skip_metrics_merge_read,
            expected_updated_at=expected_updated_at,
        )


def _empty_board_state() -> dict:
    return _board(0)


class StorageMergeHonoursOnlyANewReset(unittest.TestCase):
    def test_accidental_empty_write_keeps_the_stored_board(self):
        merged = sss._merge_full_session_preserve_richer_draft(_board(4), _empty_board_state())
        self.assertEqual(filled_pick_count(merged), 4)

    def test_new_reset_stamp_writes_the_empty_board(self):
        incoming = _empty_board_state()
        incoming[BOARD_RESET_MARKER_KEY] = {"reason": "reset_canonical_board", "at": "2026-11-10T03:16:13.000001+00:00"}
        merged = sss._merge_full_session_preserve_richer_draft(_board(4), incoming)
        self.assertEqual(filled_pick_count(merged), 0)

    def test_an_old_stamp_does_not_bypass_the_protection(self):
        stamp = {"reason": "reset_canonical_board", "at": "2026-11-10T03:16:13.000001+00:00"}
        prior = _board(4)
        prior[BOARD_RESET_MARKER_KEY] = dict(stamp)
        incoming = _empty_board_state()
        incoming[BOARD_RESET_MARKER_KEY] = dict(stamp)
        self.assertEqual(filled_pick_count(sss._merge_full_session_preserve_richer_draft(prior, incoming)), 4)


class ResetSurvivesEverySaveAfterIt(unittest.TestCase):
    """Reset, the handler's second save, a page change, then new mock picks: all persist."""

    _run = GuardTests._run

    def test_reset_then_new_mock_persists(self):
        store = StorageMergingStore(_board(4))  # the completed Live Draft handed to the Simulator
        session: dict = {}
        note_cloud_revision_seen(session, TS)
        authorize_explicit_reset(session, reason="reset_simulator_board")
        authorize_explicit_reset(session, reason="reset_canonical_board")
        for reason in ("reset_canonical_board", "reset_simulator_board", "page_change"):
            ok, _ = self._run(store, session, _empty_board_state(), reason=reason)
            self.assertTrue(ok, reason)
            self.assertEqual(filled_pick_count(store.blob), 0, reason)
        # The previous board stays recoverable in the verified snapshot (existing rule).
        self.assertTrue(store.snapshot.get("cleared"))
        self.assertEqual(store.snapshot.get("previous_verified", {}).get("pick_count"), 4)
        for reason in ("draft_room_pick", "page_change", "draft_edit"):
            ok, _ = self._run(store, session, _board(3), reason=reason)
            self.assertTrue(ok, reason)
            self.assertEqual(filled_pick_count(store.blob), 3, reason)

    def test_without_an_approved_reset_an_empty_save_cannot_erase_the_board(self):
        store = StorageMergingStore(_board(4))
        session: dict = {}
        note_cloud_revision_seen(session, TS)
        ok, _ = self._run(store, session, _empty_board_state(), reason="page_change")
        self.assertTrue(ok)
        self.assertEqual(filled_pick_count(store.blob), 4)


class ResetKeepsLiveDraftAndOverridesApart(unittest.TestCase):
    def _session(self) -> dict:
        from tests.test_simulator_board_handoff import _room, _session_with_mock

        session = _session_with_mock()
        session["live_draft_room"] = _room("complete")
        return session

    def test_reset_is_a_new_mock_the_finished_live_draft_never_retakes(self):
        import draft_room_state as drs
        from simulator_board_history import LIVE_HANDOFF_KEY

        session = self._session()
        session.pop(LIVE_HANDOFF_KEY, None)  # even with no handoff record (older account state)
        room_before = copy.deepcopy(session["live_draft_room"])
        drs.reset_simulator_board_only(session)
        for _ in range(3):  # navigation / reruns
            drs.ensure_live_draft_synced_to_canonical_board(session, reason="page_render")
        self.assertEqual(drs.table_pick_count(session[drs.DRAFT_ROOM_TABLE_KEY]), 0)
        for name in ("Mookie Betts", "Freddie Freeman", "Kyle Tucker"):
            drs.add_player_to_next_open_pick(session, name)
        drs.ensure_live_draft_synced_to_canonical_board(session, reason="page_render")
        board = drs.coerce_board_table(session[drs.DRAFT_ROOM_TABLE_KEY])
        self.assertEqual(
            [p for p in board["Player"].astype(str) if p.strip()],
            ["Mookie Betts", "Freddie Freeman", "Kyle Tucker"],
        )
        # The official record is untouched: same picks, same status.
        self.assertEqual(session["live_draft_room"]["draft_board"], room_before["draft_board"])
        self.assertEqual(session["live_draft_room"]["status"], room_before["status"])

    def test_live_override_still_reads_the_completed_live_draft_after_reset(self):
        import draft_room_state as drs
        from fantasy_context_source import (
            SOURCE_LIVE_DRAFT,
            SOURCE_SIMULATOR_BOARD,
            USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
            USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
            resolve_fantasy_context_source,
            resolve_live_override_room,
        )

        session = self._session()
        drs.reset_simulator_board_only(session)
        drs.add_player_to_next_open_pick(session, "Mookie Betts")
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = True
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_LIVE_DRAFT)
        live = resolve_live_override_room(session)
        self.assertEqual(
            [r["fullName"] for r in live["draft_board"]],
            ["Aaron Judge", "Francisco Lindor", "Juan Soto", "Ronald Acuna"],
        )
        # Turning the override on does not write the Live Draft back onto the working board.
        drs.ensure_live_draft_synced_to_canonical_board(session, reason="page_render")
        self.assertEqual(drs.table_pick_count(session[drs.DRAFT_ROOM_TABLE_KEY]), 1)
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = False
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        self.assertEqual(resolve_fantasy_context_source(session).kind, SOURCE_SIMULATOR_BOARD)

    def test_reset_during_a_running_live_draft_never_touches_the_room(self):
        import draft_room_state as drs
        from tests.test_simulator_board_handoff import _room

        session = self._session()
        session["live_draft_room"] = _room("in_progress", picks=2)
        room_before = copy.deepcopy(session["live_draft_room"])
        drs.reset_simulator_board_only(session)
        self.assertEqual(session["live_draft_room"]["draft_board"], room_before["draft_board"])
        self.assertEqual(session["live_draft_room"]["status"], "in_progress")


class BoardStatusNamesAMissingTeam(unittest.TestCase):
    def test_your_team_not_on_the_board_is_said_plainly(self):
        import u4_answers as u4a

        summary = {"filled_picks": 5, "total_picks": 6, "num_teams": 2, "current_pick": 6, "current_round": 3,
                   "your_next_pick": None, "draft_complete": False}
        body = u4a.draft_room_answer(summary, your_team="Daniel", board_teams=["QA Danny Team", "QA Barry Team"])["body"]
        self.assertIn("Your team (Daniel) is not on this board", body)
        self.assertNotIn("has no open picks left", body)
        body = u4a.draft_room_answer(summary, your_team="QA Danny Team", board_teams=["QA Danny Team", "QA Barry Team"])["body"]
        self.assertIn("QA Danny Team has no open picks left.", body)


if __name__ == "__main__":
    unittest.main()
