"""Supabase state row selection and merge guards."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_storage_supabase import (
    _FULL_SESSION_KEY,
    _merge_full_session_preserve_richer_draft,
    _merge_state_metrics,
    _pick_best_state_row,
    is_transient_supabase_error,
    load_current_states,
    save_current_state_with_result,
)


def _draft_blob(picks: int) -> dict:
    records = []
    for i in range(picks):
        records.append(
            {
                "Round": 1,
                "Pick": i + 1,
                "Team": "Team A",
                "Player": f"Player {i + 1}",
            }
        )
    return {
        "_persist_schema": 1,
        "table_records": records,
        "table_columns": ["Round", "Pick", "Team", "Player"],
        "pick_count": picks,
    }


def _full_session(picks: int, *, page: str = "Draft Room Simulator") -> dict:
    blob = _draft_blob(picks)
    return {
        "active_page": page,
        "draft_room_state": blob,
        "draft_room_table": blob,
    }


class TestSuiteStorageSupabase(unittest.TestCase):
    def test_is_transient_supabase_error(self) -> None:
        err = RuntimeError(
            "Supabase GET suite_app_current_state failed (503): "
            '{"code":"PGRST002","message":"Could not query the database for the schema cache. Retrying."}'
        )
        self.assertTrue(is_transient_supabase_error(err))
        upstream = RuntimeError(
            "Supabase POST suite_app_current_state failed (503): "
            "upstream connect error or disconnect/reset before headers"
        )
        self.assertTrue(is_transient_supabase_error(upstream))
        self.assertFalse(is_transient_supabase_error(RuntimeError("Supabase GET failed (401): denied")))

    def test_request_retries_transient_503(self) -> None:
        from suite_storage_supabase import _request

        with patch("suite_storage_supabase._request_once", side_effect=[
            RuntimeError("Supabase GET suite_app_current_state failed (503): PGRST002"),
            RuntimeError("Supabase GET suite_app_current_state failed (503): PGRST002"),
            [{"app": "baseball"}],
        ]) as mock_once:
            with patch("suite_storage_supabase.time.sleep"):
                out = _request("GET", "suite_app_current_state", params={"app": "eq.baseball"})
        self.assertEqual(out, [{"app": "baseball"}])
        self.assertEqual(mock_once.call_count, 3)

    def test_save_current_state_direct_upsert_skips_prewrite_get(self) -> None:
        with patch("suite_storage_supabase._cloud_user_id", return_value=None):
            with patch("suite_storage_supabase._request") as mock_req:
                result = save_current_state_with_result(
                    "baseball",
                    page="Saved Draft Library",
                    summary="test",
                    metrics={"full_session": _full_session(1)},
                    direct_upsert=True,
                    request_timeout_sec=25.0,
                    write_attempts=2,
                    skip_metrics_merge=True,
                )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("write_mode"), "direct_upsert")
        mock_req.assert_called_once()
        self.assertEqual(mock_req.call_args.kwargs.get("timeout_sec"), 25.0)
        self.assertEqual(mock_req.call_args.args[0], "POST")

    def test_save_current_state_direct_upsert_after_transient_get(self) -> None:
        with patch("suite_storage_supabase._cloud_user_id", return_value=None):
            with patch("suite_storage_supabase._merge_state_metrics", return_value={"full_session": _full_session(1)}):
                with patch(
                    "suite_storage_supabase._request",
                    side_effect=[
                        RuntimeError("Supabase GET suite_app_current_state failed (503): PGRST002"),
                        None,
                    ],
                ) as mock_req:
                    result = save_current_state_with_result(
                        "baseball",
                        page="Saved Draft Library",
                        summary="test",
                        metrics={"full_session": _full_session(1)},
                    )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("write_mode"), "direct_upsert_after_get_retry")
        self.assertEqual(mock_req.call_args_list[-1].args[0], "POST")

    def test_pick_best_state_row_prefers_richer_draft_over_newer_empty(self) -> None:
        rows = [
            {
                "app": "baseball",
                "updated_at": "2026-06-13T12:00:00",
                "metrics": {_FULL_SESSION_KEY: _full_session(0, page="Historical Explorer")},
            },
            {
                "app": "baseball",
                "updated_at": "2026-06-13T11:00:00",
                "metrics": {_FULL_SESSION_KEY: _full_session(3)},
            },
        ]
        best = _pick_best_state_row(rows)
        assert best is not None
        self.assertEqual(best.get("_workflow_score"), 30)

    def test_pick_best_state_row_prefers_saved_drafts_over_newer_empty_page(self) -> None:
        rows = [
            {
                "app": "baseball",
                "updated_at": "2026-07-07T12:00:00",
                "metrics": {
                    _FULL_SESSION_KEY: {
                        "active_page": "Historical Explorer",
                        "draft_archive_teams": [],
                    }
                },
            },
            {
                "app": "baseball",
                "updated_at": "2026-07-07T11:00:00",
                "metrics": {
                    _FULL_SESSION_KEY: {
                        "active_page": "Saved Draft Library",
                        "draft_archive_teams": [{"draft_id": "abc123", "updated_at": "2026-07-07T10:00:00"}],
                        "active_draft_archive_id": "abc123",
                    }
                },
            },
        ]
        best = _pick_best_state_row(rows)
        assert best is not None
        blob = (best.get("metrics") or {}).get(_FULL_SESSION_KEY) or {}
        self.assertEqual(len(blob.get("draft_archive_teams") or []), 1)

    def test_merge_full_session_preserves_richer_draft_room(self) -> None:
        prior = _full_session(3)
        incoming = _full_session(0, page="Historical Explorer")
        merged = _merge_full_session_preserve_richer_draft(prior, incoming)
        self.assertEqual(merged.get("active_page"), "Historical Explorer")
        self.assertEqual(merged["draft_room_state"]["pick_count"], 3)

    def test_merge_does_not_replace_filled_picks_with_empty_row_slots(self) -> None:
        """Prior empty 30-slot board must not clobber incoming 20 filled picks."""
        empty_slots = {
            "_persist_schema": 1,
            "table_records": [
                {"Round": 1, "Pick": i + 1, "Team": "Team A", "Player": ""}
                for i in range(30)
            ],
            "table_columns": ["Round", "Pick", "Team", "Player"],
            "pick_count": 0,
        }
        prior = {
            "active_page": "Draft Room Simulator",
            "draft_room_state": empty_slots,
            "draft_room_table": empty_slots,
        }
        incoming = _full_session(20)
        merged = _merge_full_session_preserve_richer_draft(prior, incoming)
        self.assertEqual(merged["draft_room_state"]["pick_count"], 20)
        self.assertEqual(merged["draft_room_state"]["table_records"][0]["Player"], "Player 1")

    def test_merge_prefers_incoming_when_draft_archives_deleted(self) -> None:
        prior = {
            "draft_archive_teams": [
                {"draft_id": "keep01", "draft_name": "Keep"},
                {"draft_id": "gone01", "draft_name": "Gone"},
            ],
        }
        incoming = {
            "draft_archive_teams": [{"draft_id": "keep01", "draft_name": "Keep"}],
            "_deleted_draft_archive_ids": ["gone01"],
        }
        merged = _merge_full_session_preserve_richer_draft(prior, incoming)
        archives = merged.get("draft_archive_teams") or []
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0]["draft_id"], "keep01")
        self.assertIn("gone01", merged.get("_deleted_draft_archive_ids") or [])
        fake_rows = [
            {
                "app": "baseball",
                "page": "Historical Explorer",
                "summary": "newer empty",
                "updated_at": "2026-06-13T12:00:00",
                "metrics": {_FULL_SESSION_KEY: _full_session(0, page="Historical Explorer")},
            },
            {
                "app": "baseball",
                "page": "Draft Room Simulator",
                "summary": "older rich",
                "updated_at": "2026-06-13T11:00:00",
                "metrics": {_FULL_SESSION_KEY: _full_session(3)},
            },
        ]
        with patch("suite_storage_supabase._request", return_value=fake_rows):
            with patch("suite_workspace.workspace_storage_app_keys", return_value=frozenset({"baseball"})):
                with patch("suite_workspace.logical_storage_app_key", return_value="baseball"):
                    states = load_current_states(include_metrics=True)
        baseball = states.get("baseball") or {}
        blob = (baseball.get("metrics") or {}).get(_FULL_SESSION_KEY) or {}
        self.assertEqual((blob.get("draft_room_state") or {}).get("pick_count"), 3)

    def test_save_current_state_with_result_patch_when_row_exists(self) -> None:
        existing = [
            {
                "app": "baseball",
                "user_id": "user-1",
                "updated_at": "2026-06-13T02:22:32",
                "metrics": {"full_session": _full_session(0)},
            }
        ]
        with patch("suite_storage_supabase._cloud_user_id", return_value="user-1"):
            with patch(
                "suite_storage_supabase._request",
                side_effect=[
                    [],
                    [{"app": "baseball"}],
                    None,
                ],
            ) as mock_req:
                result = save_current_state_with_result(
                    "baseball",
                    page="Draft Room Simulator",
                    summary="test",
                    metrics={"full_session": _full_session(3)},
                )
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("write_mode"), "patch")
        patch_calls = [c for c in mock_req.call_args_list if c.args and c.args[0] == "PATCH"]
        self.assertEqual(len(patch_calls), 1)

    def test_merge_state_metrics_keeps_richer_full_session(self) -> None:
        existing = {
            "metrics": {
                _FULL_SESSION_KEY: _full_session(3),
            }
        }
        incoming = {
            _FULL_SESSION_KEY: _full_session(0, page="Historical Explorer"),
        }
        with patch(
            "suite_storage_supabase._request",
            return_value=[{"metrics": existing["metrics"]}],
        ):
            merged = _merge_state_metrics("baseball", incoming)
        blob = merged.get(_FULL_SESSION_KEY) or {}
        self.assertEqual((blob.get("draft_room_state") or {}).get("pick_count"), 3)


    def test_apply_user_scope_signed_in_strict(self) -> None:
        from suite_storage_supabase import _apply_user_scope_params

        params: dict[str, str] = {}
        with patch("suite_storage_supabase._cloud_user_id", return_value="user-uuid-1"):
            _apply_user_scope_params(params)
        self.assertEqual(params.get("user_id"), "eq.user-uuid-1")
        self.assertNotIn("or", params)

    def test_apply_user_scope_legacy_null_demo(self) -> None:
        from suite_storage_supabase import _apply_user_scope_params

        params: dict[str, str] = {}
        with patch("suite_storage_supabase._cloud_user_id", return_value=None):
            _apply_user_scope_params(params)
        self.assertEqual(params.get("user_id"), "is.null")

    def test_apply_user_scope_signed_in_with_legacy_or(self) -> None:
        from suite_storage_supabase import _apply_user_scope_params

        params: dict[str, str] = {}
        with patch("suite_storage_supabase._cloud_user_id", return_value="user-uuid-1"):
            _apply_user_scope_params(params, include_legacy_null=True)
        self.assertIn("user_id.eq.user-uuid-1", params.get("or", ""))
        self.assertIn("user_id.is.null", params.get("or", ""))

    def test_inspect_cloud_state_rows_reports_selection(self) -> None:
        from suite_storage_supabase import inspect_cloud_state_rows

        rows = [
            {
                "user_id": "user-1",
                "updated_at": "2026-07-07T12:00:00",
                "page": "Saved Draft Library",
                "metrics": {
                    _FULL_SESSION_KEY: {
                        "draft_archive_teams": [{"draft_id": "d1"}],
                        "active_draft_archive_id": "d1",
                    }
                },
            }
        ]
        with patch("suite_storage_supabase._cloud_user_id", return_value="user-1"):
            with patch("suite_storage_supabase._fetch_state_rows_for_storage_app", return_value=rows):
                with patch("suite_workspace.logical_storage_app_key", return_value="baseball"):
                    out = inspect_cloud_state_rows("baseball")
        self.assertEqual(out["selected_row_user_id"], "user-1")
        self.assertEqual(out["selected_draft_count"], 1)
        self.assertEqual(out["row_count"], 1)


if __name__ == "__main__":
    unittest.main()
