"""Regression tests for Live Draft acceptance blockers."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from draft_room_participant_state import restore_persisted_shared_room_membership, resolve_participant_id
from live_draft_navigation import get_draft_return_context
from live_draft_on_clock_ui import _emit_banner_html, _render_on_clock_banner_html
from live_draft_rerun_scope import (
    TIMER_TICK_KEY,
    force_live_draft_expensive_recompute,
    live_draft_expensive_recompute_required,
    mark_live_draft_timer_tick,
)
from live_draft_state import live_draft_restore_allowed, workspace_blob_owned_by_session
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


class FakeStreamlit:
    def __init__(self) -> None:
        self.html_calls: list[str] = []
        self.markdown_calls: list[tuple] = []
        self.captions: list[str] = []

    def markdown(self, text: str, **kwargs) -> None:
        self.markdown_calls.append((text, kwargs))

    def caption(self, text: str) -> None:
        self.captions.append(str(text))

    def html(self, text: str) -> None:
        self.html_calls.append(str(text))


class RecommendationDeferCacheTests(unittest.TestCase):
    def test_timer_tick_is_one_shot(self) -> None:
        session: dict = {}
        mark_live_draft_timer_tick(session)
        self.assertFalse(live_draft_expensive_recompute_required(session))
        self.assertNotIn(TIMER_TICK_KEY, session)
        # Next call should recompute again.
        self.assertTrue(live_draft_expensive_recompute_required(session))

    def test_poll_forces_expensive_recompute(self) -> None:
        session: dict = {}
        mark_live_draft_timer_tick(session)
        force_live_draft_expensive_recompute(session)
        self.assertTrue(live_draft_expensive_recompute_required(session))


class OnClockBannerRenderTests(unittest.TestCase):
    def test_banner_uses_components_html_not_escaped_markdown(self) -> None:
        st = FakeStreamlit()
        html_blobs: list[str] = []

        def _fake_html(markup: str, height: int = 0) -> None:
            html_blobs.append(markup)

        fake_components = mock.Mock()
        fake_components.html = _fake_html
        with mock.patch.dict("sys.modules", {"streamlit.components.v1": fake_components}):
            with mock.patch("live_draft_on_clock_ui._mount_js_countdown"):
                _render_on_clock_banner_html(
                    st,
                    {"Team": "Team 1", "Round": 1, "Pick": 1},
                    remaining=45,
                    pick_index=0,
                    deadline=None,
                )
        self.assertTrue(html_blobs)
        self.assertIn("On the clock", html_blobs[0])
        self.assertIn("Team 1", html_blobs[0])
        self.assertEqual(st.markdown_calls, [])


class ResumeDiagGateTests(unittest.TestCase):
    def test_resume_diag_hidden_without_developer_mode(self) -> None:
        from live_draft_navigation import _render_return_card

        session = {
            AUTH_USER_ID_KEY: "user:daniel",
            AUTH_EXTERNAL_ID_KEY: "daniel",
            "_suite_active_workspace_id": "daniel",
        }
        ctx = {
            "kind": "live_active",
            "title": "Return to Live Draft",
            "team_label": "Team 1 vs Team 2",
            "room_code": "TEAM02",
            "user_team": "Team 1",
            "round_no": 1,
            "pick_no": 1,
            "on_clock": "Team 1",
            "seconds_remaining": 30,
        }

        class _Sidebar:
            def __init__(self) -> None:
                self.captions: list[str] = []
                self.markdowns: list[str] = []

            def container(self, border: bool = False):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def markdown(self, text: str, **k):
                self.markdowns.append(str(text))

            def caption(self, text: str):
                self.captions.append(str(text))

            def button(self, *a, **k):
                return False

        class _ST:
            def __init__(self) -> None:
                self.sidebar = _Sidebar()
                self.markdowns: list[str] = []
                self.captions: list[str] = []

            def markdown(self, text: str, **k):
                self.markdowns.append(str(text))

            def caption(self, text: str):
                self.captions.append(str(text))

            def button(self, *a, **k):
                return False

        st = _ST()
        with mock.patch(
            "suite_workspace.developer_mode_checkbox_enabled",
            return_value=False,
        ):
            _render_return_card(st, session, ctx, button_key="t1")
        joined = " ".join(st.sidebar.captions + st.captions)
        self.assertIn("Your team", joined)
        self.assertNotIn("acct=", joined)
        self.assertNotIn("sim_ok=", joined)
        self.assertNotIn("Resume ·", joined)


class AnonymousWorkspaceIsolationTests(unittest.TestCase):
    def test_unsigned_participant_id_is_ephemeral_not_daniel(self) -> None:
        session: dict = {"_suite_active_workspace_id": "daniel"}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("suite_auth.is_authenticated", return_value=False):
                pid = resolve_participant_id(session)
        self.assertTrue(pid.startswith("anonymous:"))
        self.assertNotIn("daniel", pid)

    def test_unsigned_does_not_restore_shared_membership(self) -> None:
        session = {
            "active_shared_draft_room_code": "TEAM02",
            "draft_room_participant_team": "Team 2",
            "draft_room_participant_membership": {
                "TEAM02": {"workspace:daniel": {"participant_id": "workspace:daniel", "assigned_team": "Team 2"}}
            },
            "live_draft_room": {"draft_room_id": "x", "status": "in_progress"},
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("suite_auth.is_authenticated", return_value=False):
                code = restore_persisted_shared_room_membership(session)
        self.assertEqual(code, "")
        self.assertNotIn("active_shared_draft_room_code", session)
        self.assertNotIn("live_draft_room", session)

    def test_unsigned_cannot_restore_owned_live_draft_blob(self) -> None:
        session: dict = {}
        blob = {"draft_room_id": "room1", "status": "in_progress"}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("suite_auth.is_authenticated", return_value=False):
                ok, reason = live_draft_restore_allowed(session, blob)
                owned, owned_reason = workspace_blob_owned_by_session(session, {"live_draft_state": blob})
        self.assertFalse(ok)
        self.assertEqual(reason, "auth_required")
        self.assertFalse(owned)
        self.assertEqual(owned_reason, "auth_required")

    def test_unsigned_resolve_workspace_is_guest(self) -> None:
        from suite_workspace import resolve_workspace_id

        class _S:
            session_state = {"_suite_active_workspace_id": "daniel"}

        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with mock.patch("suite_auth.is_authenticated", return_value=False):
                with mock.patch("suite_workspace._sync_account_scoped_workspace", side_effect=lambda ws, **k: ws):
                    ws = resolve_workspace_id(st=_S())
        self.assertEqual(ws, "guest")


if __name__ == "__main__":
    unittest.main()
