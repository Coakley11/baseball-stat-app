"""Regression tests for Saved Draft Library save / restore tracing."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_archive_state import DRAFT_ARCHIVE_KEY, list_draft_archives
from draft_library_save_trace import (
    DRAFT_SAVE_BUTTON_TRACE_KEY,
    begin_save_trace,
    draft_id_in_archives,
    finalize_save_trace,
    record_library_load_trace,
    record_restore_trace,
    record_save_button_click,
    resolve_draft_in_session,
    save_trace_checklist,
)
from fantasy_league_context import save_simulator_league_context
from workflow_persist_guard import build_saved_draft_library_diagnostics


def _mock_board(picks: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(picks):
        rows.append(
            {
                "Pick": i + 1,
                "Team": "Daniel" if i % 2 == 0 else "Rival",
                "Player": f"Player {i + 1}",
                "Position": "OF",
            }
        )
    return pd.DataFrame(rows)


class DraftLibrarySaveTraceTests(unittest.TestCase):
    def test_begin_and_finalize_save_trace(self) -> None:
        session: dict = {
            "room_your_team": "Daniel",
            "draft_shared_settings": {},
            "active_draft_archive_id": "real-draft",
            "fantasy_league_context_state": {
                "schema_version": 1,
                "contexts": {"real-context": {"league_context_id": "real-context"}},
                "active_league_context_id": "real-context",
            },
        }
        begin_save_trace(session, source="draft_room_simulator", reason="simulator_league_context_saved")
        entry, _ctx = save_simulator_league_context(
            session,
            _mock_board(),
            my_team_name="Daniel",
            defer_activation=True,
            save_only=True,
            reuse_session_draft_id=False,
        )
        before = {"draft_archive_count": 0, "league_context_count": 0}
        after = {"draft_archive_count": len(list_draft_archives(session)), "league_context_count": 1}
        diag = finalize_save_trace(
            session,
            reason="simulator_league_context_saved",
            before=before,
            after=after,
            persist_ok=True,
            entry=entry,
            cloud_write_ok=True,
            disk_write_ok=True,
            probe_cloud=False,
        )
        self.assertTrue(diag.get("save_request_received"))
        self.assertTrue(diag.get("draft_id"))
        self.assertEqual(diag.get("active_draft_before_save"), "real-draft")
        self.assertEqual(diag.get("active_draft_after_save"), "real-draft")
        self.assertEqual(diag.get("active_league_before_save"), "real-context")
        self.assertEqual(diag.get("active_league_after_save"), "real-context")
        self.assertFalse(diag.get("active_draft_changed_during_save"))
        self.assertFalse(diag.get("active_league_changed_during_save"))
        self.assertFalse(diag.get("pending_active_draft_changed_during_save"))
        self.assertFalse(diag.get("pending_active_league_changed_during_save"))
        self.assertEqual(int(diag.get("draft_archive_count_after") or 0), 1)
        checklist = save_trace_checklist(diag)
        labels = [row[0] for row in checklist]
        self.assertIn("Save request received", labels)
        self.assertIn("Archive id written", labels)
        self.assertIn("Active draft unchanged by save", labels)
        self.assertIn("Persist OK (overall)", labels)

    def test_draft_id_in_archives(self) -> None:
        archives = [{"draft_id": "abc123", "draft_name": "Test"}]
        self.assertTrue(draft_id_in_archives("abc123", archives))
        self.assertFalse(draft_id_in_archives("missing", archives))

    def test_record_library_and_restore_trace(self) -> None:
        session: dict = {"_suite_restore_pick_source": "disk"}
        load = record_library_load_trace(session)
        self.assertIn("library_load_count_session", load)
        restore = record_restore_trace(
            session,
            draft_id="d1",
            entry={"draft_id": "d1", "draft_name": "Mock", "players": ["A", "B"]},
            context={"league_context_id": "lc1"},
        )
        self.assertEqual(restore.get("draft_id"), "d1")
        self.assertEqual(restore.get("restore_source"), "disk")

    def test_record_save_button_click_writes_trace_before_persist(self) -> None:
        session: dict = {"room_your_team": "Daniel", "sim_draft_archive_name_input": "Mock League"}
        payload = record_save_button_click(
            session,
            source="draft_room_simulator",
            team_name="Daniel",
            key_prefix="sim_draft_archive",
            reason="simulator_league_context_saved",
        )
        self.assertTrue(payload.get("save_requested"))
        self.assertTrue(session.get(DRAFT_SAVE_BUTTON_TRACE_KEY, {}).get("save_requested"))
        self.assertEqual(session[DRAFT_SAVE_BUTTON_TRACE_KEY].get("archive_count_before"), 0)
        self.assertTrue(session.get("_draft_library_save_diag", {}).get("save_request_received"))

    @patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 1, "draft_ids": ["x1"], "row_found": True})
    @patch("draft_library_save_trace.probe_disk_workflow_for_workspace", return_value={"draft_archive_count": 1, "disk_found": True})
    def test_finalize_marks_cloud_readback(self, _disk: MagicMock, _cloud: MagicMock) -> None:
        session: dict = {
            "_draft_library_save_diag": {"save_request_received": True, "steps": ["save_request_received"]},
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "T", "players": []}],
            "_suite_persist_last_save_cloud": True,
            "_suite_persist_last_save_disk": True,
        }
        diag = finalize_save_trace(
            session,
            reason="simulator_league_context_saved",
            before={"draft_archive_count": 0, "league_context_count": 0},
            after={"draft_archive_count": 1, "league_context_count": 1},
            persist_ok=True,
            entry={"draft_id": "x1", "draft_name": "T"},
            probe_cloud=True,
        )
        self.assertTrue(diag.get("draft_in_session"))
        self.assertIn("cloud_readback_has_archive", diag.get("steps") or [])

    @patch("draft_library_save_trace.save_persist_mode_context", return_value={"cloud_write_expected": False, "auth_mode": "local_demo", "demo_disk_only_ok": True, "cloud_blocked_reason": ""})
    @patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 0, "draft_ids": [], "row_found": False})
    @patch("draft_library_save_trace.probe_disk_workflow_for_workspace", return_value={"draft_archive_count": 1, "disk_found": True})
    def test_finalize_demo_mode_skips_cloud_failure(self, _disk: MagicMock, _cloud: MagicMock, _mode: MagicMock) -> None:
        session: dict = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "T", "players": []}],
            "_suite_persist_last_save_cloud": False,
            "_suite_persist_last_save_disk": True,
        }
        diag = finalize_save_trace(
            session,
            reason="simulator_league_context_saved",
            before={"draft_archive_count": 0, "league_context_count": 0},
            after={"draft_archive_count": 1, "league_context_count": 1},
            persist_ok=False,
            entry={"draft_id": "x1", "draft_name": "T"},
            probe_cloud=True,
        )
        self.assertTrue(diag.get("draft_in_session"))
        self.assertTrue(diag.get("persist_ok"))
        checklist = dict((label, status) for label, status, _ in save_trace_checklist(diag))
        self.assertEqual(checklist.get("Cloud write"), "pending")

    def test_resolve_draft_in_session_uses_library_source(self) -> None:
        session: dict = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123", "draft_name": "Mock", "players": []}],
        }
        self.assertTrue(resolve_draft_in_session(session, "abc123"))
        self.assertFalse(resolve_draft_in_session(session, "missing"))

    def test_session_checklist_passes_when_disk_confirms(self) -> None:
        diag = {
            "save_request_received": True,
            "draft_id": "x1",
            "draft_in_session": False,
            "draft_in_disk": True,
            "persist_ok": True,
            "disk_write_success": True,
        }
        checklist = dict((label, status) for label, status, _ in save_trace_checklist(diag))
        self.assertEqual(checklist.get("Session has archive"), "pass")

    def test_finalize_treats_disk_confirmed_archive_as_session_recoverable(self) -> None:
        session: dict = {
            DRAFT_ARCHIVE_KEY: [],
            "_suite_persist_last_save_cloud": False,
            "_suite_persist_last_save_disk": True,
        }
        with patch("draft_library_save_trace.save_persist_mode_context") as mode_mock:
            mode_mock.return_value = {
                "cloud_write_expected": True,
                "demo_disk_only_ok": False,
                "auth_mode": "local_demo",
                "cloud_blocked_reason": "",
            }
            with patch(
                "draft_library_save_trace.probe_disk_workflow_for_workspace",
                return_value={"draft_archive_count": 3, "disk_found": True},
            ):
                with patch(
                    "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                    return_value={"row_found": False, "draft_archive_count": 0, "draft_ids": []},
                ):
                    with patch(
                        "draft_library_save_trace.probe_persisted_draft_id",
                        return_value={"in_disk": False, "in_cloud": False, "in_session": False},
                    ):
                        diag = finalize_save_trace(
                            session,
                            reason="live_draft_league_context_saved",
                            before={"draft_archive_count": 2, "league_context_count": 2},
                            after={"draft_archive_count": 2, "league_context_count": 2},
                            persist_ok=False,
                            entry={"draft_id": "abc123"},
                            cloud_write_ok=False,
                            disk_write_ok=True,
                        )
        self.assertTrue(diag["draft_in_session"])
        self.assertFalse(diag["persist_ok"])


if __name__ == "__main__":
    unittest.main()
