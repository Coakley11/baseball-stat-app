"""End Draft / Start New Draft on a completed Shared Draft room closes the session only (QA 2026-11-05).

In QA the host's End Draft marked completed room GGLKIU "deleted" for everyone: it left the
completed-room recovery list although the page said saved drafts and leagues are preserved. Ending a
completed room now changes nothing in the shared room; deleting stays the separate, confirmed
"End/Delete Draft for Everyone".
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

import tests.test_shared_draft_recovery as rec
from live_draft_termination import permanently_delete_live_draft, permanently_end_live_draft
from shared_draft_recovery import list_recoverable_rooms


class EndCompletedSharedRoomTests(rec._Case):
    def host_session(self, *, complete: bool = True) -> dict:
        doc = rec.room_document(complete=complete)
        self.write_room(doc)
        session = rec.signed_in("danny")
        session["active_shared_draft_room_code"] = rec.CODE
        session["live_draft_room"] = json.loads(json.dumps(doc["room"]))
        session["live_draft_room"]["room_code"] = rec.CODE
        return session

    def end(self, session: dict) -> dict:
        with mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store), mock.patch(
            "live_draft_termination.session_may_close_backend_shared_room", return_value=True
        ):
            return permanently_end_live_draft(session)

    def test_ending_a_completed_room_leaves_the_shared_room_unchanged_and_recoverable(self) -> None:
        session = self.host_session()
        before = self.room_bytes()
        out = self.end(session)
        self.assertEqual((out["operation"], out["backend_closed"]), ("close_completed", False))
        self.assertEqual(self.room_bytes(), before)  # status, picks and seats exactly as they were
        self.assertNotIn("live_draft_room", session)
        self.assertNotIn("active_shared_draft_room_code", session)
        fresh = rec.signed_in("danny")
        self.assertEqual([r["room_code"] for r in list_recoverable_rooms(fresh, store=self.store)], [rec.CODE])
        barry = rec.signed_in("barry")
        self.assertEqual([r["room_code"] for r in list_recoverable_rooms(barry, store=self.store)], [rec.CODE])

    def test_ending_does_not_reopen_the_finished_room_in_this_account(self) -> None:
        from live_draft_termination import load_durable_tombstones

        session = self.host_session()
        self.end(session)
        self.assertIn(rec.CODE, load_durable_tombstones(session)["room_codes"])  # account-local only

    def test_explicit_delete_for_everyone_still_deletes(self) -> None:
        session = self.host_session()
        with mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store), mock.patch(
            "live_draft_termination.session_may_close_backend_shared_room", return_value=True
        ), mock.patch("live_draft_termination._close_backend_room") as close:
            permanently_delete_live_draft(session)
        close.assert_called_once()
        self.assertEqual(close.call_args.kwargs.get("terminal_status"), "deleted")

    def test_ending_an_unfinished_room_still_discards_as_before(self) -> None:
        session = self.host_session(complete=False)
        with mock.patch("live_draft_termination.discard_live_draft_and_start_over",
                        return_value={"ok": True, "operation": "discard"}) as discard:
            out = permanently_end_live_draft(session)
        discard.assert_called_once()
        self.assertEqual(out["operation"], "discard")


if __name__ == "__main__":
    unittest.main()
