"""Tests for suite workspace profiles (Phase 1)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from suite_deep_links import build_resume_action_url
from suite_user_persistence import save_user_state, state_file_path
from suite_workspace import (
    DEFAULT_WORKSPACE_ID,
    append_suite_workspace_param,
    get_active_workspace_id,
    init_suite_workspace,
    migrate_legacy_app_state_to_daniel,
    normalize_workspace_id,
    persist_active_workspace_id,
    set_active_workspace_id,
    workspace_dir,
)


class TestWorkspaceNormalization(unittest.TestCase):
    def test_default_is_daniel(self) -> None:
        self.assertEqual(normalize_workspace_id(""), DEFAULT_WORKSPACE_ID)
        self.assertEqual(normalize_workspace_id(None), DEFAULT_WORKSPACE_ID)

    def test_presets(self) -> None:
        self.assertEqual(normalize_workspace_id("Ariel"), "ariel")
        self.assertEqual(normalize_workspace_id("Test User"), "test_user")


class TestWorkspacePaths(unittest.TestCase):
    def test_different_workspaces_different_paths(self) -> None:
        daniel = state_file_path("baseball", workspace_id="daniel")
        ariel = state_file_path("baseball", workspace_id="ariel")
        self.assertNotEqual(daniel, ariel)
        self.assertIn("workspaces", str(daniel))
        self.assertIn("daniel", str(daniel))
        self.assertIn("ariel", str(ariel))

    def test_legacy_migration_to_daniel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            legacy = data / "baseball_user_state.json"
            legacy.write_text(
                json.dumps({"version": 1, "app": "baseball", "saved_at": "t", "state": {"active_page": "X"}}),
                encoding="utf-8",
            )
            with patch("suite_workspace.DATA_DIR", data), patch("suite_user_persistence.DATA_DIR", data):
                migrated = migrate_legacy_app_state_to_daniel("baseball")
                self.assertTrue(migrated)
                target = workspace_dir("daniel") / "baseball_user_state.json"
                self.assertTrue(target.is_file())
                payload = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(payload["state"]["active_page"], "X")

    def test_ariel_and_daniel_separate_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with patch("suite_workspace.DATA_DIR", data), patch("suite_user_persistence.DATA_DIR", data):
                save_user_state("investment", {"holdings": "daniel"}, workspace_id="daniel")
                save_user_state("investment", {"holdings": "ariel"}, workspace_id="ariel")
                daniel_path = state_file_path("investment", "daniel")
                ariel_path = state_file_path("investment", "ariel")
                self.assertTrue(daniel_path.is_file())
                self.assertTrue(ariel_path.is_file())
                self.assertNotEqual(
                    daniel_path.read_text(encoding="utf-8"),
                    ariel_path.read_text(encoding="utf-8"),
                )


class TestWorkspaceSession(unittest.TestCase):
    def test_set_and_get_active_workspace(self) -> None:
        class FakeState(dict):
            pass

        st = type("St", (), {"session_state": FakeState(), "query_params": {}})()
        set_active_workspace_id(st, "ariel")
        self.assertEqual(get_active_workspace_id(st), "ariel")

    def test_init_reads_query_param_before_restore(self) -> None:
        class FakeState(dict):
            pass

        st = type(
            "St",
            (),
            {"session_state": FakeState(), "query_params": {"suite_workspace": "guest"}},
        )()
        ws = init_suite_workspace(st)
        self.assertEqual(ws, "guest")
        self.assertEqual(get_active_workspace_id(st), "guest")


class TestDeepLinks(unittest.TestCase):
    def test_build_resume_action_url_includes_workspace(self) -> None:
        with patch("suite_workspace.load_persisted_workspace_id", return_value="ariel"):
            url = build_resume_action_url(
                "baseball",
                resume_key="compare:A:B",
                page="Comparison Tool",
                metrics={"player_a": "A", "player_b": "B", "workspace_id": "ariel"},
                base_url="https://example.test/baseball",
            )
            params = parse_qs(urlparse(url).query)
            self.assertEqual(params.get("suite_workspace", [""])[0], "ariel")

    def test_append_suite_workspace_param(self) -> None:
        url = append_suite_workspace_param("https://example.test/app", workspace_id="daniel")
        self.assertIn("suite_workspace=daniel", url)


class TestPersistedWorkspace(unittest.TestCase):
    def test_persist_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with patch("suite_workspace.DATA_DIR", data):
                persist_active_workspace_id("guest")
                from suite_workspace import load_persisted_workspace_id

                self.assertEqual(load_persisted_workspace_id(), "guest")


if __name__ == "__main__":
    unittest.main()
