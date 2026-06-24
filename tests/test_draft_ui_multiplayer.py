"""Smoke tests for shared draft room multiplayer panel."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_room_context import create_and_host_shared_room, prepare_global_draft_context
from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY, ACTIVE_PARTICIPANT_TEAM_KEY
from draft_room_shared_state import LocalFileSharedRoomStore
from draft_ui_multiplayer import render_shared_draft_room_panel
from live_draft_state import LIVE_DRAFT_ROOM_KEY
from suite_auth import AUTH_USER_ID_KEY


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class _FakeStreamlit:
    def __init__(self, *, button_clicks: set[str] | None = None) -> None:
        self._button_clicks = button_clicks or set()

    @contextmanager
    def container(self, **kwargs: object):
        yield self

    def markdown(self, *_args: object, **_kwargs: object) -> None:
        return None

    def caption(self, *_args: object, **_kwargs: object) -> None:
        return None

    def warning(self, *_args: object, **_kwargs: object) -> None:
        return None

    def success(self, *_args: object, **_kwargs: object) -> None:
        return None

    def error(self, *_args: object, **_kwargs: object) -> None:
        return None

    def info(self, *_args: object, **_kwargs: object) -> None:
        return None

    def text_input(self, *_args: object, **kwargs: object) -> str:
        return str(kwargs.get("value") or "")

    def checkbox(self, *_args: object, **kwargs: object) -> bool:
        return bool(kwargs.get("value", False))

    def button(self, *_args: object, **kwargs: object) -> bool:
        return str(kwargs.get("key") or "") in self._button_clicks

    def columns(self, spec: object) -> list["_FakeStreamlit"]:
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_FakeStreamlit(button_clicks=self._button_clicks) for _ in range(n)]

    def form(self, *_args: object, **_kwargs: object):
        return self

    def form_submit_button(self, *_args: object, **_kwargs: object) -> bool:
        return False

    def expander(self, *_args: object, **_kwargs: object):
        return self

    def __enter__(self) -> "_FakeStreamlit":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class DraftUiMultiplayerSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.session = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-host-uuid",
            AUTH_USER_ID_KEY: "auth-host-uuid",
        }
        self._store_patch = patch(
            "draft_room_shared_state.get_shared_room_store",
            return_value=self.store,
        )
        self._backend_patch = patch(
            "draft_room_shared_state.shared_room_backend_name",
            return_value="local",
        )
        self._auth_patch = patch(
            "draft_room_membership.shared_room_requires_auth",
            return_value=False,
        )
        self._store_patch.start()
        self._backend_patch.start()
        self._auth_patch.start()

    def tearDown(self) -> None:
        self._auth_patch.stop()
        self._backend_patch.stop()
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def _bootstrap_multiplayer_session(self) -> None:
        code, _ = create_and_host_shared_room(
            self.session,
            _sample_live_room(),
            store=self.store,
        )
        self.assertTrue(code)
        prepare_global_draft_context(self.session)

    @patch("suite_workspace.can_show_developer_tools", return_value=True)
    @patch("draft_room_supabase_health.render_shared_room_supabase_health")
    @patch("draft_room_join_trace.render_join_trace_panel")
    @patch("draft_room_join_trace.render_shared_room_auth_diagnostics")
    @patch("draft_room_diagnostics.render_shared_room_diagnostics")
    @patch("draft_room_diagnostics.render_compact_pool_diagnostics")
    @patch("draft_room_diagnostics.render_shared_room_create_diagnostics")
    def test_reset_membership_button_does_not_raise(
        self,
        _create_diag: object,
        _compact_diag: object,
        _room_diag: object,
        _auth_diag: object,
        _join_trace: object,
        _health: object,
        _dev_tools: object,
    ) -> None:
        self._bootstrap_multiplayer_session()
        self.session[ACTIVE_PARTICIPANT_TEAM_KEY] = "Team 1"
        st = _FakeStreamlit(button_clicks={"shared_draft_reset_membership_btn"})
        rerun = render_shared_draft_room_panel(st, self.session)
        self.assertTrue(rerun)
        self.assertNotIn(ACTIVE_PARTICIPANT_TEAM_KEY, self.session)

    @patch("draft_room_supabase_health.render_shared_room_supabase_health")
    @patch("draft_room_join_trace.render_join_trace_panel")
    @patch("draft_room_join_trace.render_shared_room_auth_diagnostics")
    def test_create_join_panel_renders_without_error(
        self,
        _auth_diag: object,
        _join_trace: object,
        _health: object,
    ) -> None:
        self.session[LIVE_DRAFT_ROOM_KEY] = _sample_live_room()
        st = _FakeStreamlit()
        rerun = render_shared_draft_room_panel(st, self.session)
        self.assertFalse(rerun)


if __name__ == "__main__":
    unittest.main()
