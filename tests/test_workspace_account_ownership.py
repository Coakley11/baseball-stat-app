"""Acceptance tests — one owned workspace per authenticated account."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from suite_auth import allowed_workspaces_for_user, enforce_workspace_ownership
from suite_workspace import (
    bootstrap_suite_workspace,
    get_active_workspace_id,
    init_suite_workspace,
    load_persisted_workspace_id,
    persist_active_workspace_id,
    set_active_workspace_id,
)
from suite_workspace_registry import (
    ensure_owned_workspace_for_session,
    get_owned_workspace_id,
    get_registry_record,
    workspace_access_allowed,
)


def _auth_session(*, user_id: str, email: str, external_id: str) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": user_id,
        "_suite_auth_user_email": email,
        "_suite_auth_external_id": external_id,
    }


class _FakeSt:
    def __init__(self, session: dict | None = None, *, query: dict | None = None) -> None:
        self.session_state: dict = dict(session or {})
        self.query_params = dict(query or {})


class TestWorkspaceAccountOwnership(unittest.TestCase):
    def test_daniel_admin_can_access_all_presets(self) -> None:
        allowed = allowed_workspaces_for_user("daniel")
        self.assertIn("daniel", allowed)
        self.assertIn("ariel", allowed)
        self.assertIn("guest", allowed)

    def test_ariel_account_only_sees_ariel_workspace(self) -> None:
        allowed = allowed_workspaces_for_user("ariel")
        self.assertEqual(allowed, ("ariel",))
        self.assertNotIn("daniel", allowed)
        self.assertNotIn("guest", allowed)

    def test_new_account_gets_single_owned_workspace(self) -> None:
        allowed = allowed_workspaces_for_user("coakley11")
        self.assertEqual(allowed, ("coakley11",))
        self.assertNotIn("guest", allowed)
        self.assertNotIn("test_user", allowed)

    def test_auto_provision_owned_workspace_on_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            reg = data / "workspaces" / "_ownership_registry.json"
            with patch("suite_workspace_registry.DATA_DIR", data), patch(
                "suite_workspace_registry.REGISTRY_FILE", reg
            ), patch("suite_workspace_registry.ACTIVE_DIR", data / "workspaces" / "_active"), patch(
                "suite_workspace.DATA_DIR", data
            ):
                session = _auth_session(
                    user_id="uuid-ariel",
                    email="ariel@example.com",
                    external_id="ariel",
                )
                record = ensure_owned_workspace_for_session(session)
                self.assertEqual(record["workspace_id"], "ariel")
                self.assertEqual(record["owner_user_id"], "uuid-ariel")
                stored = get_registry_record("uuid-ariel")
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored["workspace_id"], "ariel")

    def test_refresh_restores_same_owned_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            active_dir = data / "workspaces" / "_active"
            reg = data / "workspaces" / "_ownership_registry.json"
            with patch("suite_workspace_registry.DATA_DIR", data), patch(
                "suite_workspace_registry.REGISTRY_FILE", reg
            ), patch("suite_workspace_registry.ACTIVE_DIR", active_dir), patch(
                "suite_workspace.DATA_DIR", data
            ), patch("suite_workspace._PERSISTED_FILE", data / "suite_active_workspace.json"):
                session = _auth_session(
                    user_id="uuid-daniel",
                    email="daniel@example.com",
                    external_id="daniel",
                )
                with patch("suite_auth.is_auth_enabled", return_value=True), patch(
                    "suite_auth.is_authenticated", return_value=True
                ):
                    ensure_owned_workspace_for_session(session)
                    persist_active_workspace_id("daniel", session_state=session)
                    reloaded = load_persisted_workspace_id(session_state=session)
                    self.assertEqual(reloaded, "daniel")
                    active_file = active_dir / "uuid-daniel.json"
                    self.assertTrue(active_file.is_file())

    def test_stale_foreign_workspace_rejected(self) -> None:
        session = _auth_session(
            user_id="uuid-ariel",
            email="ariel@example.com",
            external_id="ariel",
        )
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_workspace_registry.ensure_owned_workspace_for_session") as ensure_mock:
            ensure_mock.return_value = {
                "owner_user_id": "uuid-ariel",
                "workspace_id": "ariel",
                "label": "Ariel",
            }
            with patch("suite_workspace_registry.get_owned_workspace_id", return_value="ariel"):
                self.assertFalse(workspace_access_allowed("daniel", session_state=session))
                self.assertTrue(workspace_access_allowed("ariel", session_state=session))

    def test_enforce_clamps_foreign_active_workspace(self) -> None:
        st = _FakeSt(_auth_session(user_id="uuid-ariel", email="ariel@example.com", external_id="ariel"))
        st.session_state["_suite_active_workspace_id"] = "daniel"
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_auth.resolve_auth_external_id", return_value="ariel"), patch(
            "suite_auth.allowed_workspaces_for_session", return_value=("ariel",)
        ), patch("suite_workspace_registry.ensure_owned_workspace_for_session") as ensure_mock, patch(
            "suite_workspace_registry.get_owned_workspace_id", return_value="ariel"
        ), patch("suite_workspace.persist_active_workspace_id", return_value=True):
            ensure_mock.return_value = {"workspace_id": "ariel", "owner_user_id": "uuid-ariel"}
            enforce_workspace_ownership(st.session_state)
            self.assertEqual(get_active_workspace_id(st), "ariel")

    def test_init_suite_ignores_foreign_query_workspace(self) -> None:
        st = _FakeSt(
            _auth_session(user_id="uuid-ariel", email="ariel@example.com", external_id="ariel"),
            query={"suite_workspace": "daniel"},
        )
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_workspace_registry.workspace_access_allowed", return_value=False), patch(
            "suite_workspace_registry.get_owned_workspace_id", return_value="ariel"
        ), patch("suite_auth.enforce_workspace_ownership") as enforce_mock, patch(
            "suite_workspace.load_persisted_workspace_id", return_value="ariel"
        ), patch("suite_workspace.persist_active_workspace_id", return_value=True):
            ws = init_suite_workspace(st)
            self.assertEqual(ws, "ariel")
            self.assertGreaterEqual(enforce_mock.call_count, 1)

    def test_bootstrap_auth_before_workspace_coakley11(self) -> None:
        """Startup smoke: stale daniel session + foreign URL → coakley11 after bootstrap."""
        session = _auth_session(
            user_id="uuid-coakley",
            email="coakley11@aol.com",
            external_id="coakley11",
        )
        session["_suite_active_workspace_id"] = "daniel"
        st = _FakeSt(session, query={"suite_workspace": "daniel"})
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            reg = data / "workspaces" / "_ownership_registry.json"
            active_dir = data / "workspaces" / "_active"
            global_persist = data / "suite_active_workspace.json"
            global_persist.write_text(
                json.dumps({"workspace_id": "daniel", "label": "Daniel"}),
                encoding="utf-8",
            )
            with patch("suite_auth.is_auth_enabled", return_value=True), patch(
                "suite_auth.is_authenticated", return_value=True
            ), patch("suite_auth.restore_auth_session", return_value=True), patch(
                "suite_workspace_registry.DATA_DIR", data
            ), patch("suite_workspace_registry.REGISTRY_FILE", reg), patch(
                "suite_workspace_registry.ACTIVE_DIR", active_dir
            ), patch("suite_workspace.DATA_DIR", data), patch(
                "suite_workspace._PERSISTED_FILE", global_persist
            ):
                ws = bootstrap_suite_workspace(st)
                self.assertEqual(ws, "coakley11")
                self.assertEqual(get_active_workspace_id(st), "coakley11")
                self.assertNotEqual(get_active_workspace_id(st), "daniel")

    def test_no_recursion_resolving_owned_workspace(self) -> None:
        """Regression: account-aware and legacy paths must not call each other."""
        session = _auth_session(
            user_id="uuid-coakley",
            email="coakley11@aol.com",
            external_id="coakley11",
        )
        st = _FakeSt(session, query={"suite_workspace": "daniel"})
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            reg = data / "workspaces" / "_ownership_registry.json"
            active_dir = data / "workspaces" / "_active"
            # Lower the recursion limit so any accidental cycle fails fast/loudly.
            prior_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(200)
            try:
                with patch("suite_auth.is_auth_enabled", return_value=True), patch(
                    "suite_auth.is_authenticated", return_value=True
                ), patch("suite_auth.restore_auth_session", return_value=True), patch(
                    "suite_workspace_registry.DATA_DIR", data
                ), patch("suite_workspace_registry.REGISTRY_FILE", reg), patch(
                    "suite_workspace_registry.ACTIVE_DIR", active_dir
                ), patch("suite_workspace.DATA_DIR", data), patch(
                    "suite_workspace._PERSISTED_FILE", data / "suite_active_workspace.json"
                ):
                    # Direct resolution (this used to RecursionError).
                    resolved = load_persisted_workspace_id(session_state=session)
                    self.assertEqual(resolved, "coakley11")
                    # Full startup path, incl. ownership enforcement + foreign URL reject.
                    ws = bootstrap_suite_workspace(st)
                    self.assertEqual(ws, "coakley11")
                    self.assertEqual(get_active_workspace_id(st), "coakley11")
            except RecursionError as exc:  # pragma: no cover - explicit failure
                self.fail(f"Workspace resolution recursed: {exc}")
            finally:
                sys.setrecursionlimit(prior_limit)

    def test_legacy_path_no_delegation_when_unauthenticated(self) -> None:
        """Unauthenticated resolution stays on the legacy global file (no account callback)."""
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            persist = data / "suite_active_workspace.json"
            persist.write_text(json.dumps({"workspace_id": "guest", "label": "Guest"}), encoding="utf-8")
            with patch("suite_auth.is_auth_enabled", return_value=False), patch(
                "suite_workspace.DATA_DIR", data
            ), patch("suite_workspace._PERSISTED_FILE", persist):
                self.assertEqual(load_persisted_workspace_id(session_state=None), "guest")
                self.assertEqual(load_persisted_workspace_id(session_state={}), "guest")

    def test_bootstrap_refresh_stays_coakley11(self) -> None:
        """Second bootstrap (refresh) keeps coakley11 owned workspace."""
        session = _auth_session(
            user_id="uuid-coakley",
            email="coakley11@aol.com",
            external_id="coakley11",
        )
        st = _FakeSt(session)
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            reg = data / "workspaces" / "_ownership_registry.json"
            active_dir = data / "workspaces" / "_active"
            with patch("suite_auth.is_auth_enabled", return_value=True), patch(
                "suite_auth.is_authenticated", return_value=True
            ), patch("suite_auth.restore_auth_session", return_value=True), patch(
                "suite_workspace_registry.DATA_DIR", data
            ), patch("suite_workspace_registry.REGISTRY_FILE", reg), patch(
                "suite_workspace_registry.ACTIVE_DIR", active_dir
            ), patch("suite_workspace.DATA_DIR", data), patch(
                "suite_workspace._PERSISTED_FILE", data / "suite_active_workspace.json"
            ):
                first = bootstrap_suite_workspace(st)
                persist_active_workspace_id(first, session_state=st.session_state)
                st.session_state.pop("_suite_workspace_initialized", None)
                second = bootstrap_suite_workspace(st)
                self.assertEqual(first, "coakley11")
                self.assertEqual(second, "coakley11")


if __name__ == "__main__":
    unittest.main()
