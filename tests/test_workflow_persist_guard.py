"""Tests for workflow partial-save protection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow_persist_guard import (
    ACTIVE_DRAFT_ARCHIVE_KEY,
    ACTIVE_DRAFT_RESTORE_TRACE_KEY,
    AUTH_RESTORE_CYCLE_COMPLETE_KEY,
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    STARTUP_CANONICAL_SYNC_COMPLETE_KEY,
    WORKFLOW_PERSIST_ALLOW_CLEAR_KEY,
    build_saved_draft_library_diagnostics,
    build_persistence_probe_panel,
    build_startup_restore_snapshot,
    evaluate_cloud_durability_status,
    hydrate_session_workflow_from_disk,
    infer_restore_persistence_verdict,
    merge_protected_workflow_into_save,
    merge_protected_workflow_on_restore,
    inject_session_draft_library_into_save_state,
    is_draft_library_mutation_save_reason,
    probe_cloud_workflow_for_workspace,
    record_startup_restore_snapshot,
    restore_active_draft_archive_selection,
    should_keep_session_workflow_over_blob,
    should_skip_empty_blob_workflow_over_persisted,
    workflow_empty_save_blocked_reason,
    enrich_cloud_restore_state,
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

    def test_should_skip_empty_blob_when_cloud_has_drafts(self) -> None:
        st = MagicMock()
        cloud = {DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud01", "draft_name": "Cloud Draft"}]}
        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value=cloud):
                self.assertTrue(
                    should_skip_empty_blob_workflow_over_persisted(
                        DRAFT_ARCHIVE_KEY,
                        [],
                        app_id="baseball",
                        st=st,
                    )
                )
        self.assertFalse(
            should_skip_empty_blob_workflow_over_persisted(
                DRAFT_ARCHIVE_KEY,
                [{"draft_id": "live01"}],
                app_id="baseball",
                st=st,
            )
        )

    def test_enrich_cloud_restore_state_merges_fallback_archives(self) -> None:
        st = MagicMock()
        primary = {"active_page": "Historical Explorer", DRAFT_ARCHIVE_KEY: []}
        enriched = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "fb01", "draft_name": "Fallback Draft"}],
            "active_page": "Saved Draft Library",
        }
        with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value=enriched):
            out = enrich_cloud_restore_state("baseball", st, primary)
        self.assertEqual(len(out.get(DRAFT_ARCHIVE_KEY) or []), 1)
        self.assertEqual(out["draft_archive_teams"][0]["draft_id"], "fb01")
        self.assertEqual(out.get("active_page"), "Saved Draft Library")

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
                "auth_enabled": True,
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
        self.assertIn("yes", probe["cloud_restore_attempted_label"])
        self.assertIn("Yes", probe["diagnosis"]["Did cloud restore run?"])

    def test_build_persistence_probe_panel_includes_migration_fields(self) -> None:
        session = {
            "_suite_auth_session": True,
            "_suite_auth_user_id": "uid-daniel",
            "_suite_auth_external_id": "daniel",
        }
        with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
            mock_diag.return_value = {
                "auth_enabled": True,
                "authenticated": True,
                "account_email": "daniel@example.com",
                "account_user_id": "uid-daniel",
                "workspace_id": "daniel",
                "owned_workspace_id": "daniel",
                "cloud_app_key": "baseball",
                "draft_archive_count": 0,
                "cloud_saved_draft_count_active": 0,
                "disk_saved_draft_count": 0,
                "cloud_enabled": True,
                "migration_recoverable_draft_count": 2,
                "migration_sources": [
                    {
                        "source_type": "cloud",
                        "cloud_app_key": "baseball",
                        "user_id": None,
                        "draft_count": 2,
                        "draft_names": ["Uploaded trial League", "Second draft"],
                    }
                ],
                "migration_best_source": {
                    "source_type": "cloud",
                    "cloud_app_key": "baseball",
                    "user_id": None,
                    "draft_count": 2,
                },
                "historical_suite_users": [{"id": "old-uuid", "external_id": "daniel"}],
            }
            with patch("workflow_persist_guard._resolve_probe_deploy_commit", return_value="51b46cc"):
                probe = build_persistence_probe_panel(session)
        self.assertEqual(probe["migration_recoverable_draft_count"], 2)
        self.assertEqual(len(probe["migration_sources"]), 1)
        self.assertEqual(probe["deploy_commit"], "51b46cc")
        self.assertIn("Migration scan (all cloud user_ids + disk paths)", probe["diagnosis"])
        self.assertIn("2", probe["diagnosis"]["Migration scan (all cloud user_ids + disk paths)"])

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
                "auth_enabled": True,
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

    def _probe_diag_stub(self) -> dict:
        return {
            "auth_enabled": True,
            "authenticated": True,
            "account_email": "chris@example.com",
            "account_user_id": "uid-123",
            "workspace_id": "coakley11",
            "owned_workspace_id": "coakley11",
            "cloud_app_key": "baseball__coakley11",
            "draft_archive_count": 1,
            "cloud_saved_draft_count_active": 1,
            "disk_saved_draft_count": 0,
            "cloud_enabled": True,
        }

    def test_build_persistence_probe_panel_missing_active_trace(self) -> None:
        """No _suite_active_draft_restore_trace key at all must not raise (f540bb2 crash)."""
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "My League"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "x1",
        }
        with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
            mock_diag.return_value = self._probe_diag_stub()
            probe = build_persistence_probe_panel(session)
        self.assertEqual(probe["active_restore_source"], "—")
        self.assertEqual(probe["active_restore_reason"], "—")
        self.assertFalse(probe["active_restore_needs_prompt"])

    def test_build_persistence_probe_panel_none_active_trace(self) -> None:
        """Explicit None trace value must normalize to {} before .get()."""
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "My League"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "x1",
            ACTIVE_DRAFT_RESTORE_TRACE_KEY: None,
            "_suite_startup_restore_snapshot": None,
        }
        with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
            mock_diag.return_value = self._probe_diag_stub()
            probe = build_persistence_probe_panel(session)
        self.assertEqual(probe["active_restore_source"], "—")
        self.assertEqual(probe["active_restore_reason"], "—")

    def test_build_persistence_probe_panel_malformed_active_trace(self) -> None:
        """Non-dict trace/startup values (list/str) must not crash and fall back cleanly."""
        for bad_value in (["not", "a", "dict"], "trace-string", 42):
            session = {
                DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "My League"}],
                ACTIVE_DRAFT_ARCHIVE_KEY: "x1",
                ACTIVE_DRAFT_RESTORE_TRACE_KEY: bad_value,
                "_suite_startup_restore_snapshot": bad_value,
            }
            with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
                mock_diag.return_value = self._probe_diag_stub()
                probe = build_persistence_probe_panel(session)
            self.assertEqual(probe["active_restore_source"], "—")
            self.assertEqual(probe["active_restore_reason"], "—")
            self.assertFalse(probe["active_restore_needs_prompt"])

    def test_build_persistence_probe_panel_valid_active_trace(self) -> None:
        """Well-formed trace still surfaces source/reason/prompt fields."""
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1", "draft_name": "My League"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "x1",
            ACTIVE_DRAFT_RESTORE_TRACE_KEY: {
                "active_source": "cloud",
                "restore_reason": "matched_cloud_active_to_visible_archive",
                "needs_set_active_prompt": True,
            },
        }
        with patch("workflow_persist_guard.build_saved_draft_library_diagnostics") as mock_diag:
            mock_diag.return_value = self._probe_diag_stub()
            probe = build_persistence_probe_panel(session)
        self.assertEqual(probe["active_restore_source"], "cloud")
        self.assertEqual(probe["active_restore_reason"], "matched_cloud_active_to_visible_archive")
        self.assertTrue(probe["active_restore_needs_prompt"])

    def test_inject_session_draft_library_into_save_state(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "inj1", "draft_name": "Injected"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "inj1",
        }
        state = {"active_page": "Saved Draft Library"}
        out = inject_session_draft_library_into_save_state(state, session)
        self.assertEqual(len(out[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(out[ACTIVE_DRAFT_ARCHIVE_KEY], "inj1")

    def test_is_draft_library_mutation_save_reason(self) -> None:
        self.assertTrue(is_draft_library_mutation_save_reason("simulator_league_context_saved"))
        self.assertTrue(is_draft_library_mutation_save_reason("draft_archive_saved"))
        self.assertFalse(is_draft_library_mutation_save_reason("page_change"))

    def test_merge_protected_workflow_authoritative_injects_session_archives(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "auth1"}],
            WORKFLOW_PERSIST_ALLOW_CLEAR_KEY: True,
        }
        state = {"active_page": "Saved Draft Library"}
        out = merge_protected_workflow_into_save(state, session, save_reason="simulator_league_context_saved")
        self.assertEqual(len(out[DRAFT_ARCHIVE_KEY]), 1)

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

    def test_page_change_blocked_when_empty_session_cloud_has_drafts(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        state = {DRAFT_ARCHIVE_KEY: [], "comparison_state": {"players": []}}
        st = MagicMock()
        st.session_state = {}
        with patch("suite_workspace.get_active_workspace_id", return_value="daniel"):
            with patch(
                "workflow_persist_guard.read_live_cloud_draft_probe",
                return_value={"draft_archive_count": 1, "cloud_app_key": "baseball__daniel"},
            ):
                with patch(
                    "workflow_persist_guard.probe_cloud_workflow_for_workspace",
                    return_value={"draft_archive_count": 1, "row_found": True},
                ):
                    with patch(
                        "workflow_persist_guard._disk_migration_candidate_workspace_ids",
                        return_value=["daniel"],
                    ):
                        with patch("workflow_persist_guard._load_disk_workflow_at_workspace", return_value={}):
                            with patch(
                                "workflow_persist_guard._load_durable_workflow_snapshot",
                                return_value={DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01"}]},
                            ):
                                with patch(
                                    "workflow_persist_guard.discover_workflow_migration_sources",
                                    return_value={"recoverable_draft_count": 0},
                                ):
                                    reason = _cloud_autosave_blocked_reason(st, "baseball", state, save_reason="page_change")
        self.assertEqual(reason, "page_change_empty_draft_archive_live_cloud_blocked")

    def test_preserve_cloud_drafts_on_page_change(self) -> None:
        from suite_user_persistence import _preserve_cloud_widget_fields_on_page_change

        cloud_state = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01", "draft_name": "Keep"}],
            "fantasy_league_context_state": {
                "active_league_context_id": "ctx1",
                "contexts": {"ctx1": {"league_context_id": "ctx1", "my_team_name": "Daniel"}},
            },
            "active_draft_archive_id": "keep01",
        }
        state = {DRAFT_ARCHIVE_KEY: [], "active_page": "Historical Explorer"}
        with patch("suite_cloud_state.load_cloud_full_session", return_value=(cloud_state, "ts")):
            out = _preserve_cloud_widget_fields_on_page_change("baseball", state)
        self.assertEqual(len(out.get(DRAFT_ARCHIVE_KEY) or []), 1)
        self.assertEqual(out.get("active_draft_archive_id"), "keep01")

    def test_ensure_session_workflow_hydrated_from_cloud(self) -> None:
        from workflow_persist_guard import ensure_session_workflow_hydrated

        st = MagicMock()
        st.session_state = {"active_page": "Historical Explorer"}
        cloud_state = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01", "draft_name": "Keep"}],
            "active_page": "Saved Draft Library",
        }
        with patch(
            "workflow_persist_guard._load_cloud_workflow_snapshot",
            return_value=cloud_state,
        ):
            with patch(
                "workflow_persist_guard._load_disk_workflow_snapshot",
                return_value={},
            ):
                result = ensure_session_workflow_hydrated(st, "baseball", cloud_state=cloud_state)
        self.assertTrue(result.get("hydrated"))
        self.assertEqual(result.get("source"), "cloud")
        self.assertEqual(len(st.session_state.get(DRAFT_ARCHIVE_KEY) or []), 1)
        self.assertEqual(st.session_state.get("active_page"), "Saved Draft Library")
        self.assertEqual(
            st.session_state.get("_suite_empty_startup_write_blocked"),
            "hydrated_from_cloud_before_autosave",
        )

    def test_force_save_reason_cannot_erase_recoverable_cloud_drafts(self) -> None:
        st = MagicMock()
        st.session_state = {}
        state = {DRAFT_ARCHIVE_KEY: []}
        cloud_state = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud01", "draft_name": "Cloud Draft"}],
            LEAGUE_CONTEXT_STATE_KEY: {
                "active_league_context_id": "ctx:cloud01",
                "contexts": {"ctx:cloud01": {"league_context_id": "ctx:cloud01"}},
            },
        }
        with patch("workflow_persist_guard.read_live_cloud_draft_probe", return_value={"draft_archive_count": 1}):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value=cloud_state):
                with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}):
                    reason = workflow_empty_save_blocked_reason(
                        st,
                        "baseball",
                        state,
                        save_reason="fantasy_edit",
                    )

        self.assertEqual(reason, "empty_outgoing_would_erase_live_cloud_drafts")
        self.assertTrue(st.session_state.get("_suite_draft_archive_wipe_guard", {}).get("blocked"))

    def test_startup_read_only_gate_blocks_page_change(self) -> None:
        from workflow_persist_guard import activate_startup_read_only_gate, startup_read_only_blocked_reason

        st = MagicMock()
        st.session_state = {"_suite_active_workspace_id": "coakley11"}
        activate_startup_read_only_gate(st.session_state, "baseball")
        reason = startup_read_only_blocked_reason(st, "baseball", "page_change")
        self.assertEqual(reason, "startup_read_only_gate_active")

    def test_recoverable_shared_league_evidence_blocks_empty_save(self) -> None:
        st = MagicMock()
        st.session_state = {
            "_suite_active_workspace_id": "coakley11",
            "_suite_auth_user_id": "user:seal11",
            AUTH_RESTORE_CYCLE_COMPLETE_KEY: True,
            STARTUP_CANONICAL_SYNC_COMPLETE_KEY: True,
        }
        state = {DRAFT_ARCHIVE_KEY: []}
        memberships = [
            {
                "league_id": "league:test01",
                "reasons": ["team_ownership", "pending_trade"],
                "owned_teams": ["Team 2"],
            }
        ]
        with patch("workflow_persist_guard.read_live_cloud_draft_probe", return_value={"draft_archive_count": 0}):
            with patch("workflow_persist_guard.summarize_durable_draft_sources", return_value={"max_draft_count": 0, "disk_max": 0}):
                with patch("workflow_persist_guard.summarize_recoverable_workflow_evidence", return_value={"recoverable": True, "team_ownership": True}):
                    with patch("fantasy_shared_league_startup_sync.discover_shared_league_memberships_for_session", return_value=memberships):
                        reason = workflow_empty_save_blocked_reason(
                            st,
                            "baseball",
                            state,
                            save_reason="fantasy_edit",
                        )
        self.assertEqual(reason, "empty_outgoing_would_erase_recoverable_shared_league_evidence")

    def test_probe_auth_labels_unsigned_with_cloud_user(self) -> None:
        from workflow_persist_guard import _resolve_probe_auth_labels

        labels = _resolve_probe_auth_labels(
            {},
            {
                "auth_enabled": True,
                "authenticated": False,
                "account_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b",
                "workspace_id": "daniel",
            },
        )
        self.assertEqual(labels["signed_in_label"], "no")
        self.assertIn("Not signed in this session", labels["auth_scope_label"])
        self.assertIn("f66b85aa", labels["user_id_display"])

    def test_probe_cloud_restore_labels_when_source_cloud(self) -> None:
        from workflow_persist_guard import _resolve_cloud_restore_probe_labels

        effective, label, detail = _resolve_cloud_restore_probe_labels(
            {"_suite_persist_last_restore_source": "cloud"},
            restore_pick_source="cloud",
            restore_applied=False,
            restore_skip="",
            session_draft_count=1,
            workflow_hydrate_source="",
        )
        self.assertTrue(effective)
        self.assertIn("yes", label)
        self.assertIn("cloud", detail.lower())

    def test_restore_active_from_cloud_after_merge(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud01", "draft_name": "Upload Test Demo"}],
        }
        cloud = {ACTIVE_DRAFT_ARCHIVE_KEY: "cloud01"}
        trace = restore_active_draft_archive_selection(
            session,
            cloud_state=cloud,
            disk_state={},
            phase="test",
        )
        self.assertEqual(session.get(ACTIVE_DRAFT_ARCHIVE_KEY), "cloud01")
        self.assertEqual(trace.get("active_source"), "cloud")
        self.assertEqual(trace.get("restore_reason"), "matched_cloud_active_to_visible_archive")

    def test_restore_prefers_session_active_over_stale_cloud(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "a1", "draft_name": "A"},
                {"draft_id": "a2", "draft_name": "B"},
            ],
            ACTIVE_DRAFT_ARCHIVE_KEY: "a2",
        }
        cloud = {ACTIVE_DRAFT_ARCHIVE_KEY: "a1"}
        trace = restore_active_draft_archive_selection(
            session,
            cloud_state=cloud,
            disk_state={},
            phase="test",
        )
        self.assertEqual(session.get(ACTIVE_DRAFT_ARCHIVE_KEY), "a2")
        self.assertEqual(trace.get("active_source"), "session")

    def test_restore_active_auto_sets_single_visible_draft(self) -> None:
        session = {DRAFT_ARCHIVE_KEY: [{"draft_id": "only01", "draft_name": "Only"}]}
        trace = restore_active_draft_archive_selection(session, cloud_state={}, disk_state={}, phase="test")
        self.assertEqual(session.get(ACTIVE_DRAFT_ARCHIVE_KEY), "only01")
        self.assertEqual(trace.get("restore_reason"), "single_visible_draft_auto_active")

    def test_restore_active_prompt_when_multiple_drafts_no_active(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "a1", "draft_name": "A"},
                {"draft_id": "a2", "draft_name": "B"},
            ]
        }
        trace = restore_active_draft_archive_selection(session, cloud_state={}, disk_state={}, phase="test")
        self.assertNotIn(ACTIVE_DRAFT_ARCHIVE_KEY, session)
        self.assertTrue(session.get("_suite_active_draft_restore_prompt"))
        self.assertEqual(trace.get("restore_reason"), "multiple_visible_drafts_no_persisted_active")

    def test_merge_protected_workflow_on_restore_sets_active_from_cloud(self) -> None:
        session: dict = {}
        incoming = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud01", "draft_name": "League"}],
            ACTIVE_DRAFT_ARCHIVE_KEY: "cloud01",
        }
        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value=incoming):
                with patch(
                    "draft_archive_visibility.sanitize_workflow_library_for_account",
                    side_effect=lambda s, **_: None,
                ):
                    merge_protected_workflow_on_restore(session, incoming)
        self.assertEqual(session.get(ACTIVE_DRAFT_ARCHIVE_KEY), "cloud01")


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
