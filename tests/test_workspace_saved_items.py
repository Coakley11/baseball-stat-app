"""Workspace isolation for suite_saved_items (Daniel vs Ariel)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from suite_account import load_saved_items, remember_saved_item
from suite_user_persistence import load_user_state, save_user_state, state_file_path
from suite_workspace import scoped_cloud_app_id, set_active_workspace_id


class _FakeSt:
    def __init__(self, workspace: str = "daniel") -> None:
        self.session_state: dict = {}
        self.query_params: dict = {}
        set_active_workspace_id(self, workspace)


class TestScopedCloudAppKeys(unittest.TestCase):
    def test_daniel_uses_legacy_key(self) -> None:
        with patch("suite_workspace.resolve_workspace_id", return_value="daniel"):
            self.assertEqual(scoped_cloud_app_id("baseball"), "baseball")

    def test_ariel_uses_namespaced_key(self) -> None:
        with patch("suite_workspace.resolve_workspace_id", return_value="ariel"):
            self.assertEqual(scoped_cloud_app_id("baseball"), "baseball__ariel")


class TestRememberSavedItemScoping(unittest.TestCase):
    def _mock_storage(self) -> MagicMock:
        storage = MagicMock()
        storage.upsert_saved_item.return_value = {"write_mode": "upsert"}
        storage.load_saved_items.return_value = []
        return storage

    def test_daniel_writes_legacy_app_key(self) -> None:
        storage = self._mock_storage()
        with patch.dict(sys.modules, {"suite_storage": storage}), patch(
            "suite_workspace.resolve_workspace_id", return_value="daniel"
        ):
            remember_saved_item(
                "baseball",
                "applied_math_insight",
                "insight-daniel-1",
                title="Daniel insight",
                payload={"insight_id": "insight-daniel-1"},
            )
        storage.upsert_saved_item.assert_called_once()
        self.assertEqual(storage.upsert_saved_item.call_args[0][0], "baseball")

    def test_ariel_writes_namespaced_app_key(self) -> None:
        storage = self._mock_storage()
        with patch.dict(sys.modules, {"suite_storage": storage}), patch(
            "suite_workspace.resolve_workspace_id", return_value="ariel"
        ):
            remember_saved_item(
                "baseball",
                "applied_math_insight",
                "insight-ariel-1",
                title="Ariel insight",
                payload={"insight_id": "insight-ariel-1"},
            )
        self.assertEqual(storage.upsert_saved_item.call_args[0][0], "baseball__ariel")

    def test_ariel_load_does_not_query_legacy_key(self) -> None:
        storage = self._mock_storage()
        with patch.dict(sys.modules, {"suite_storage": storage}), patch(
            "suite_workspace.resolve_workspace_id", return_value="ariel"
        ):
            load_saved_items(app="baseball", item_type="applied_math_insight", limit=10)
        storage.load_saved_items.assert_called_once_with(
            app="baseball__ariel", item_type="applied_math_insight", limit=10
        )


class TestDanielArielBaseballBlobIsolation(unittest.TestCase):
    """Simulate Daniel vs Ariel draft/compare/watchlist disk isolation."""

    def _save_baseball_blob(self, workspace: str, marker: str) -> None:
        state = {
            "active_page": "Draft Room Simulator",
            "draft_state": {
                "queue": [f"{marker}-player"],
                "watchlist_favorites": [f"{marker}-fav"],
            },
            "comparison_state": {"players": [f"{marker}-A", f"{marker}-B"]},
            "leaderboards_state": {"filters": {"season": marker}},
            "page_filter_state": {"Draft Room Simulator": {"team": marker}},
        }
        with patch("suite_workspace.resolve_workspace_id", return_value=workspace):
            save_user_state("baseball", state)

    def test_daniel_and_ariel_blobs_do_not_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with patch("suite_workspace.DATA_DIR", data), patch("suite_user_persistence.DATA_DIR", data):
                self._save_baseball_blob("daniel", "DANIEL")
                self._save_baseball_blob("ariel", "ARIEL")

                with patch("suite_workspace.resolve_workspace_id", return_value="daniel"):
                    daniel, _ = load_user_state("baseball")
                with patch("suite_workspace.resolve_workspace_id", return_value="ariel"):
                    ariel, _ = load_user_state("baseball")

                self.assertIn("DANIEL", json.dumps(daniel))
                self.assertNotIn("ARIEL", json.dumps(daniel))
                self.assertIn("ARIEL", json.dumps(ariel))
                self.assertNotIn("DANIEL", json.dumps(ariel))

                self.assertNotEqual(
                    state_file_path("baseball", "daniel").read_text(encoding="utf-8"),
                    state_file_path("baseball", "ariel").read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
