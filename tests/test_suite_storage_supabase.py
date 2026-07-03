"""Supabase state row selection and merge guards."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_storage_supabase import (
    _FULL_SESSION_KEY,
    _merge_full_session_preserve_richer_draft,
    _merge_state_metrics,
    _pick_best_state_row,
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
        self.assertEqual(best.get("_draft_pick_count"), 3)

    def test_merge_full_session_preserves_richer_draft_room(self) -> None:
        prior = _full_session(3)
        incoming = _full_session(0, page="Historical Explorer")
        merged = _merge_full_session_preserve_richer_draft(prior, incoming)
        self.assertEqual(merged.get("active_page"), "Historical Explorer")
        self.assertEqual(merged["draft_room_state"]["pick_count"], 3)

    def test_load_current_states_uses_richest_row_per_app(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
