"""Tests for workflow partial-save protection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow_persist_guard import (
    ACTIVE_DRAFT_ARCHIVE_KEY,
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    WORKFLOW_PERSIST_ALLOW_CLEAR_KEY,
    build_saved_draft_library_diagnostics,
    build_persistence_probe_panel,
    build_startup_restore_snapshot,
    evaluate_cloud_durability_status,
    hydrate_session_workflow_from_disk,
    infer_restore_persistence_verdict,
    merge_protected_workflow_into_save,
    merge_protected_workflow_on_restore,
    probe_cloud_workflow_for_workspace,
    record_startup_restore_snapshot,
    should_keep_session_workflow_over_blob,
)


class WorkflowPersistGuardTests(unittest.TestCase):
    def test_partial_save_merges_draft_archives_from_disk(self) -> None:
        persisted = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "abc123", "draft_name": "Home League", "players": [{"player_name": "Judge"}]},
            ],
            LEAGUE_CONTEXT_STATE_KEY: {
                "contexts": {"ctx:abc123": {"league_context_id": "ctx:abc123", "display_name": "Home"}},
                "active_league_context_id": "ctx:abc123",
            },
        }
        session: dict = {"use_active_league_context_waiver_filter": True}
        state: dict = {"page_filter_state": {}}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                out = merge_protected_workflow_into_save(
                    state,
                    session,
                    save_reason="waiver_pending_pair",
                )

        self.assertEqual(len(out[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(out[DRAFT_ARCHIVE_KEY][0]["draft_id"], "abc123")
        self.assertEqual(len(out[LEAGUE_CONTEXT_STATE_KEY]["contexts"]), 1)
        self.assertIn(DRAFT_ARCHIVE_KEY, session)
        merged = session.get("_suite_workflow_persist_merged_keys") or []
        self.assertIn(DRAFT_ARCHIVE_KEY, merged)
        self.assertIn(LEAGUE_CONTEXT_STATE_KEY, merged)

    def test_intentional_empty_archive_not_merged_when_authoritative(self) -> None:
        persisted = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123", "draft_name": "Old"}],
        }
        session = {DRAFT_ARCHIVE_KEY: [], WORKFLOW_PERSIST_ALLOW_CLEAR_KEY: True}
        state = {DRAFT_ARCHIVE_KEY: []}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="waiver_pending_pair")

        self.assertEqual(out[DRAFT_ARCHIVE_KEY], [])
        self.assertNotIn(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY, session)

    def test_explicit_clear_reason_skips_merge(self) -> None:
        persisted = {DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123"}]}
        session: dict = {}
        state: dict = {}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="draft_archive_cleared")

        self.assertNotIn(DRAFT_ARCHIVE_KEY, out)

    def test_empty_lazy_league_context_merges_from_disk(self) -> None:
        persisted = {
            LEAGUE_CONTEXT_STATE_KEY: {
                "contexts": {"ctx:1": {"league_context_id": "ctx:1"}},
                "active_league_context_id": "ctx:1",
            },
        }
        session = {
            LEAGUE_CONTEXT_STATE_KEY: {"contexts": {}, "active_league_context_id": "", "schema_version": 1},
        }
        state = {LEAGUE_CONTEXT_STATE_KEY: session[LEAGUE_CONTEXT_STATE_KEY]}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="waiver_filter_changed")

        self.assertEqual(len(out[LEAGUE_CONTEXT_STATE_KEY]["contexts"]), 1)

    def test_empty_session_archives_merge_from_disk_on_save(self) -> None:
        persisted = {DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123", "draft_name": "Home League"}]}
        session = {DRAFT_ARCHIVE_KEY: []}
        state = {DRAFT_ARCHIVE_KEY: []}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="page_change")

        self.assertEqual(len(out[DRAFT_ARCHIVE_KEY]), 1)

    def test_restore_merge_recover_archives_from_disk(self) -> None:
        incoming = {DRAFT_ARCHIVE_KEY: []}
        disk = {DRAFT_ARCHIVE_KEY: [{"draft_id": "restore01", "draft_name": "Recovered"}]}
        session: dict = {DRAFT_ARCHIVE_KEY: []}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=disk):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                merge_protected_workflow_on_restore(session, incoming)

        self.assertEqual(len(session[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(session[DRAFT_ARCHIVE_KEY][0]["draft_id"], "restore01")

    def test_restore_merge_respects_deleted_draft_tombstones(self) -> None:
        incoming = {DRAFT_ARCHIVE_KEY: [{"draft_id": "gone01", "draft_name": "Deleted"}]}
        disk = {DRAFT_ARCHIVE_KEY: [{"draft_id": "gone01", "draft_name": "Deleted"}]}
        session: dict = {
            DRAFT_ARCHIVE_KEY: [],
            "_deleted_draft_archive_ids": ["gone01"],
        }

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=disk):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                merge_protected_workflow_on_restore(session, incoming)

        self.assertEqual(session.get(DRAFT_ARCHIVE_KEY), [])

    def test_should_keep_session_workflow_over_empty_blob(self) -> None:
        session_archives = [{"draft_id": "a1"}, {"draft_id": "a2"}]
        self.assertTrue(
            should_keep_session_workflow_over_blob(DRAFT_ARCHIVE_KEY, session_archives, [])
        )
        self.assertFalse(
            should_keep_session_workflow_over_blob(DRAFT_ARCHIVE_KEY, [], session_archives)
        )

    def test_build_saved_draft_library_diagnostics(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1"}],
            LEAGUE_CONTEXT_STATE_KEY: {"contexts": {"ctx:1": {}}},
            "_suite_persist_last_restore_source": "cloud",
            "_suite_persist_last_restore_at": "2026-07-05T00:00:00+00:00",
        }
        diag = build_saved_draft_library_diagnostics(session)
        self.assertEqual(diag["draft_archive_count"], 1)
        self.assertEqual(diag["league_context_count"], 1)
        self.assertEqual(diag["restore_source"], "cloud")
        self.assertIn("cloud", diag["restore_source_label"].lower())

    def test_build_persistence_probe_panel_fields(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "My League"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "x1",
            "_suite_startup_restore_snapshot": {
                "persistence_verdict": "ok",
                "cloud_saved_draft_count": 1,
                "disk_saved_draft_count": 0,
                "restored_workspace_id": "coakley11",
            },
            "_suite_restore_decision": "applied",
            "_suite_restore_pick_source": "cloud",
            "_suite_persist_last_restore_source": "cloud",
        }
        with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
            mock_diag.return_value = {
                "authenticated": True,
                "account_email": "chris@example.com",
                "account_user_id": "uid-123",
                "workspace_id": "coakley11",
                "owned_workspace_id": "coakley11",
                "cloud_app_key": "baseball__coakley11",
                "draft_archive_count": 1,
                "cloud_saved_draft_count_active": 1,
                "disk_saved_draft_count": 0,
                "cloud_saved_draft_count_owned": 1,
                "cloud_saved_draft_count_legacy": 0,
                "restore_source": "cloud",
                "cloud_enabled": True,
            }
            probe = build_persistence_probe_panel(session)
        self.assertEqual(probe["signed_in_label"], "yes")
        self.assertEqual(probe["account_email"], "chris@example.com")
        self.assertEqual(probe["user_id"], "uid-123")
        self.assertEqual(probe["session_draft_count"], 1)
        self.assertEqual(probe["cloud_draft_count"], 1)
        self.assertEqual(probe["active_draft_name"], "My League")
        self.assertEqual(probe["persistence_verdict"], "ok")
        self.assertIn("Yes — cloud blob applied", probe["diagnosis"]["Did cloud restore run?"])

    def test_build_persistence_probe_panel_restore_failure(self) -> None:
        session = {
            "_suite_startup_restore_snapshot": {
                "persistence_verdict": "B_restore_failed",
                "cloud_saved_draft_count": 2,
                "disk_saved_draft_count": 0,
                "restored_workspace_id": "coakley11",
            },
            "_suite_restore_decision": "applied",
            "_suite_restore_pick_source": "cloud",
        }
        with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
            mock_diag.return_value = {
                "authenticated": True,
                "account_email": "chris@example.com",
                "account_user_id": "uid-123",
                "workspace_id": "coakley11",
                "owned_workspace_id": "daniel",
                "cloud_app_key": "baseball__coakley11",
                "draft_archive_count": 0,
                "cloud_saved_draft_count_active": 2,
                "disk_saved_draft_count": 0,
                "cloud_saved_draft_count_owned": 0,
                "cloud_saved_draft_count_legacy": 3,
                "restore_source": "cloud",
                "cloud_enabled": True,
            }
            probe = build_persistence_probe_panel(session)
        self.assertEqual(probe["persistence_verdict"], "B_restore_failed")
        self.assertIn("≠ owned", probe["diagnosis"]["Did the reboot load a different workspace?"])
        self.assertIn("storage has drafts", probe["diagnosis"]["Were my drafts ever successfully persisted?"])

    def test_diagnostics_durable_when_cloud_has_verified_drafts(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1"}],
            "_suite_draft_library_readback_ok": True,
            "_suite_draft_library_readback_count": 1,
        }
        with patch("suite_storage_config.cloud_storage_enabled", return_value=True):
            with patch("suite_auth.is_auth_enabled", return_value=True):
                with patch("suite_auth.is_authenticated", return_value=True):
                    with patch(
                        "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                        return_value={"row_found": True, "draft_archive_count": 1},
                    ):
                        diag = build_saved_draft_library_diagnostics(session)
        self.assertTrue(diag["durable_persistence"])
        self.assertTrue(diag["cloud_write_verified"])
        self.assertIn("Durable", diag["durability_label"])

    def test_diagnostics_not_durable_on_last_cloud_save_alone(self) -> None:
        session = {DRAFT_ARCHIVE_KEY: [], "_suite_persist_last_save_cloud": True, "_suite_last_cloud_payload_bytes": 173780}
        with patch("suite_storage_config.cloud_storage_enabled", return_value=True):
            with patch("suite_auth.is_auth_enabled", return_value=True):
                with patch("suite_auth.is_authenticated", return_value=True):
                    with patch(
                        "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                        return_value={"row_found": True, "draft_archive_count": 0},
                    ):
                        diag = build_saved_draft_library_diagnostics(session)
        self.assertFalse(diag["durable_persistence"])
        self.assertIn("Not durable", diag["durability_label"])

    def test_diagnostics_local_demo_never_claims_full_durable(self) -> None:
        session = {DRAFT_ARCHIVE_KEY: [{"draft_id": "x1"}], "_suite_persist_last_save_cloud": True}
        with patch("suite_storage_config.cloud_storage_enabled", return_value=True):
            with patch("suite_auth.is_auth_enabled", return_value=True):
                with patch("suite_auth.is_authenticated", return_value=False):
                    with patch(
                        "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                        return_value={"row_found": True, "draft_archive_count": 1},
                    ):
                        status = evaluate_cloud_durability_status(session)
        self.assertFalse(status["durable_persistence"])
        self.assertIn("Demo mode", status["durability_label"])

    def test_diagnostics_not_durable_when_cloud_enabled_but_unverified(self) -> None:
        session = {DRAFT_ARCHIVE_KEY: [{"draft_id": "x1"}]}
        with patch("suite_storage_config.cloud_storage_enabled", return_value=True):
            with patch(
                "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                return_value={"row_found": False, "draft_archive_count": 0},
            ):
                diag = build_saved_draft_library_diagnostics(session)
        self.assertFalse(diag["durable_persistence"])
        self.assertFalse(diag.get("cloud_write_verified"))
        self.assertIn("Not durable yet", diag["durability_label"])

    def test_diagnostics_not_durable_when_cloud_disabled(self) -> None:
        session = {DRAFT_ARCHIVE_KEY: [{"draft_id": "x1"}]}
        with patch("suite_storage_config.cloud_storage_enabled", return_value=False):
            diag = build_saved_draft_library_diagnostics(session)
        self.assertFalse(diag["durable_persistence"])
        self.assertFalse(diag["cloud_write_expected"])
        self.assertIn("Temporary local session only", diag["durability_warning"])

    def test_hydrate_session_workflow_from_disk_restores_archives(self) -> None:
        session: dict = {}
        disk_state = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123", "draft_name": "Recovered"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "abc123",
        }
        with patch("suite_user_persistence._load_raw", return_value=(disk_state, "/tmp/state.json", "ts")):
            out = hydrate_session_workflow_from_disk(session, draft_id="abc123")
        self.assertTrue(out["hydrated"])
        self.assertEqual(len(session[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(session[ACTIVE_DRAFT_ARCHIVE_KEY], "abc123")

    def test_startup_restore_snapshot_flags_restore_failure(self) -> None:
        session = {
            "active_page": "Historical Explorer",
            "_suite_restore_decision": "applied",
            "workflow_recently_viewed": [],
        }
        cloud = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud01"}],
            "active_draft_archive_id": "cloud01",
            "active_page": "Live Draft Room",
            "workflow_recently_viewed": ["Judge", "Ohtani"],
        }
        snap = build_startup_restore_snapshot(session, cloud_state=cloud, disk_state={}, phase="post_resume")
        self.assertEqual(snap["restored_workspace_id"], "daniel")
        self.assertEqual(snap["restored_active_page"], "Historical Explorer")
        self.assertEqual(snap["session_saved_draft_count"], 0)
        self.assertEqual(snap["cloud_saved_draft_count"], 1)
        self.assertEqual(snap["cloud_active_draft_id"], "cloud01")
        self.assertEqual(snap["cloud_tracked_player_count"], 2)
        self.assertEqual(snap["persistence_verdict"], "B_restore_failed")

    def test_infer_restore_persistence_verdict_ok(self) -> None:
        self.assertEqual(
            infer_restore_persistence_verdict(
                cloud_draft_count=1,
                session_draft_count=1,
                restore_applied=True,
            ),
            "ok",
        )

    def test_record_startup_restore_snapshot_writes_session_keys(self) -> None:
        st = MagicMock()
        st.session_state = {DRAFT_ARCHIVE_KEY: [{"draft_id": "s1"}], "active_page": "Live Draft Room"}
        snap = record_startup_restore_snapshot(st, cloud_state={}, disk_state={}, phase="during_sync")
        self.assertEqual(st.session_state["_suite_startup_restore_snapshot"], snap)
        self.assertEqual(st.session_state["_suite_startup_session_saved_draft_count"], 1)

    def test_blank_draft_archive_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        state = {DRAFT_ARCHIVE_KEY: [], "comparison_state": {"players": []}}
        st = MagicMock()
        st.session_state = {}
        with patch("suite_workspace.get_active_workspace_id", return_value="daniel"):
            with patch(
                "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                return_value={"draft_archive_count": 1, "row_found": True},
            ):
                reason = _cloud_autosave_blocked_reason(st, "baseball", state, save_reason="autosave")
        self.assertEqual(reason, "blank_draft_archive_would_erase_cloud")

    def test_draft_archive_save_reason_not_cloud_blocked(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        state = {DRAFT_ARCHIVE_KEY: []}
        cloud_state = {DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01"}]}
        st = MagicMock()
        st.session_state = {"_suite_workspace_sync_skipped_no_apply": True}
        with patch("suite_cloud_state.load_cloud_full_session", return_value=(cloud_state, "ts")):
            reason = _cloud_autosave_blocked_reason(
                st, "baseball", state, save_reason="draft_archive_saved"
            )
        self.assertIsNone(reason)

    def test_build_disk_state_applies_merge(self) -> None:
        from baseball_persistent_state import build_baseball_disk_state

        persisted = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01", "draft_name": "Keep"}],
        }
        st = MagicMock()
        st.session_state = {"page_filter_state": {}, "_suite_pending_save_reason": "waiver_pending_pair"}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                blob = build_baseball_disk_state(st)

        self.assertEqual(len(blob.get(DRAFT_ARCHIVE_KEY) or []), 1)


class WorkflowPersistGuardDiskRoundtripTests(unittest.TestCase):
    def test_save_after_partial_session_preserves_disk_archives(self) -> None:
        from baseball_persistent_state import build_baseball_disk_state

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            ws_dir = data / "workspaces" / "daniel"
            ws_dir.mkdir(parents=True)
            payload = {
                "version": 1,
                "app": "baseball",
                "saved_at": "2026-07-01T00:00:00+00:00",
                "state": {
                    DRAFT_ARCHIVE_KEY: [{"draft_id": "disk01", "draft_name": "Disk Draft"}],
                    LEAGUE_CONTEXT_STATE_KEY: {
                        "contexts": {"ctx:disk01": {"league_context_id": "ctx:disk01"}},
                    },
                },
            }
            (ws_dir / "baseball_user_state.json").write_text(json.dumps(payload), encoding="utf-8")

            st = MagicMock()
            st.session_state = {
                "page_filter_state": {},
                "_suite_pending_save_reason": "waiver_filter_changed",
            }

            with patch("suite_workspace.DATA_DIR", data), patch("suite_user_persistence.DATA_DIR", data):
                with patch("suite_workspace.load_persisted_workspace_id", return_value="daniel"):
                    blob = build_baseball_disk_state(st)

            self.assertEqual(len(blob.get(DRAFT_ARCHIVE_KEY) or []), 1)
            self.assertEqual(blob[DRAFT_ARCHIVE_KEY][0]["draft_id"], "disk01")


if __name__ == "__main__":
    unittest.main()
