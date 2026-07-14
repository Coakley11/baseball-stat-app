"""Regression: draft-origin diagnostics must not import streamlit_app."""

from __future__ import annotations

import builtins
import importlib
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE, get_draft_archive
from draft_archive_ui import draft_type_display, render_saved_draft_library_page
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    DRAFT_ORIGIN_REPAIR_DIAG_KEY,
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    SOURCE_IMPORTED_DRAFT,
    SOURCE_LIVE_DRAFT_ROOM,
    render_draft_origin_repair_diagnostics,
    repair_archive_draft_types_from_contexts,
    resolve_archive_draft_type_with_reason,
)
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from tests.test_live_draft_workspace_isolation import _cio11_session, _daniel_session


LEAGUE_ID = "league:c4eefe793c8abac4764346d6"
DRAFT_ID = "c6810611c73e"
CONTEXT_ID = f"archive:{DRAFT_ID}"


def _rosters() -> dict:
    return {
        "Donny": {"players": [{"player_name": "D1"}]},
        "Team B": {"players": [{"player_name": "B1"}]},
    }


def _poisoned_shared_doc() -> dict:
    return {
        "league_id": LEAGUE_ID,
        "draft_id": DRAFT_ID,
        "source": SOURCE_IMPORTED_DRAFT,
        "source_draft_type": DRAFT_TYPE_IMPORTED,
        "team_ownership": {
            "Donny": {"user_id": "user:daniel"},
            "Team B": {"user_id": "user:coakley11"},
        },
        "league_rosters": _rosters(),
        "league_invites": [],
        "commissioner_user_id": "user:daniel",
        "revision": 2,
    }


def _poisoned_context() -> dict:
    return {
        "league_context_id": CONTEXT_ID,
        "context_type": CONTEXT_TYPE_REAL_LEAGUE,
        "source": SOURCE_IMPORTED_DRAFT,
        "display_name": "Robins Fantasy — Donny vs Team B",
        "my_team_name": "Team B",
        "league_rosters": _rosters(),
        "metadata": {
            "league_id": LEAGUE_ID,
            "source_draft_id": DRAFT_ID,
            "source_draft_type": DRAFT_TYPE_IMPORTED,
            "joined_via_live_draft": True,
            "preassigned_live_draft_owner": True,
            "commissioner_user_id": "user:daniel",
        },
    }


def _mock_st() -> MagicMock:
    st = MagicMock()
    st.markdown = MagicMock()
    st.caption = MagicMock()
    st.metric = MagicMock()
    st.info = MagicMock()
    st.success = MagicMock()
    st.warning = MagicMock()
    st.error = MagicMock()
    st.json = MagicMock()
    st.toast = MagicMock()
    st.divider = MagicMock()
    st.container = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )
    )
    st.expander = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )
    )
    st.columns = MagicMock(side_effect=lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))])
    st.button = MagicMock(return_value=False)
    st.checkbox = MagicMock(return_value=False)
    st.rerun = MagicMock()
    st.session_state = {}
    return st


class DraftOriginDiagnosticsImportTests(unittest.TestCase):
    def test_fantasy_league_context_does_not_reference_streamlit_app(self) -> None:
        import fantasy_league_context as flc

        source = inspect.getsource(flc)
        self.assertNotIn("from streamlit_app import", source)
        self.assertNotIn("import streamlit_app", source)

    def test_importing_fantasy_league_context_does_not_load_streamlit_app(self) -> None:
        tracker: list[str] = []
        original_import = builtins.__import__

        def _tracking_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
            if name == "streamlit_app" or name.endswith(".streamlit_app"):
                tracker.append(name)
            return original_import(name, globals, locals, fromlist, level)

        modules_to_drop = [key for key in list(sys.modules) if key == "fantasy_league_context"]
        saved = {key: sys.modules.pop(key) for key in modules_to_drop}
        try:
            with patch("builtins.__import__", side_effect=_tracking_import):
                importlib.import_module("fantasy_league_context")
        finally:
            sys.modules.update(saved)
        self.assertNotIn("streamlit_app", tracker)

    def test_developer_mode_false_does_not_render_diagnostics(self) -> None:
        st = MagicMock()
        session = {DRAFT_ORIGIN_REPAIR_DIAG_KEY: {"selected_reason": "strong_live_draft_membership"}}
        render_draft_origin_repair_diagnostics(st, session, developer_mode=False)
        st.expander.assert_not_called()

    def test_developer_mode_true_renders_diagnostics_expander_once(self) -> None:
        st = MagicMock()
        session = {DRAFT_ORIGIN_REPAIR_DIAG_KEY: {"selected_reason": "strong_live_draft_membership"}}
        render_draft_origin_repair_diagnostics(st, session, developer_mode=True)
        st.expander.assert_called_once_with(
            "Draft origin repair diagnostics",
            expanded=False,
            key="draft_origin_repair_diag_panel",
        )
        st.json.assert_called_once()

    def test_library_render_does_not_import_streamlit_app(self) -> None:
        tracker: list[str] = []
        original_import = builtins.__import__

        def _tracking_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
            if name == "streamlit_app" or name.endswith(".streamlit_app"):
                tracker.append(name)
            return original_import(name, globals, locals, fromlist, level)

        session = _cio11_session()
        session["draft_archive_teams"] = []
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = {"contexts": {}}
        st = _mock_st()
        with patch("builtins.__import__", side_effect=_tracking_import):
            render_saved_draft_library_page(st, session, developer_mode=False)
        self.assertNotIn("streamlit_app", tracker)

    def test_single_library_render_registers_diagnostics_expander_once(self) -> None:
        session = _cio11_session()
        session[DRAFT_ORIGIN_REPAIR_DIAG_KEY] = {"selected_reason": "strong_live_draft_membership"}
        session["draft_archive_teams"] = []
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = {"contexts": {}}
        st = _mock_st()
        expander_keys: list[str] = []

        def _expander(*_args, **kwargs):
            key = kwargs.get("key")
            if key:
                if key in expander_keys:
                    raise KeyError(f"duplicate Streamlit widget key: {key}")
                expander_keys.append(key)
            return MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False))

        st.expander.side_effect = _expander
        render_saved_draft_library_page(st, session, developer_mode=True)
        self.assertEqual(expander_keys, ["draft_origin_repair_diag_panel"])

    def test_coakley11_live_draft_badge_and_reason_after_library_repair(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        store = LocalFileSharedLeagueStore(root=Path(tmp.name))
        set_shared_league_store(store)
        try:
            store.save(_poisoned_shared_doc())
            session = _cio11_session()
            session[DRAFT_ARCHIVE_KEY] = [
                {
                    "draft_id": DRAFT_ID,
                    "draft_type": DRAFT_TYPE_IMPORTED,
                    "team_name": "Team B",
                    "draft_name": "Robins Fantasy — Donny vs Team B",
                    "league_context_id": CONTEXT_ID,
                    "league_rosters": _rosters(),
                }
            ]
            session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = {
                "active_league_context_id": CONTEXT_ID,
                "contexts": {CONTEXT_ID: _poisoned_context()},
            }
            repair_archive_draft_types_from_contexts(session)
            entry = get_draft_archive(session, DRAFT_ID)
            assert entry is not None
            self.assertEqual(draft_type_display(entry), "Live Draft")
            self.assertEqual(entry.get("team_name"), "Team B")
            diag = session.get(DRAFT_ORIGIN_REPAIR_DIAG_KEY) or {}
            self.assertIn(
                diag.get("selected_reason"),
                {
                    "strong_live_draft_membership",
                    "immutable_creation_origin_live_draft_room",
                    "canonical_created_from_live_draft",
                    "poisoned_import_origin_overridden_by_live_created_from",
                },
            )
            repair_archive_draft_types_from_contexts(session)
            self.assertEqual(draft_type_display(entry), "Live Draft")
            st = _mock_st()
            render_saved_draft_library_page(st, session, developer_mode=False)
            render_saved_draft_library_page(st, session, developer_mode=False)
            self.assertEqual(draft_type_display(get_draft_archive(session, DRAFT_ID) or {}), "Live Draft")
        finally:
            set_shared_league_store(None)
            tmp.cleanup()

    def test_daniel_remains_live_draft_donny(self) -> None:
        session = _daniel_session()
        context = {
            "league_context_id": CONTEXT_ID,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_LIVE_DRAFT_ROOM,
            "my_team_name": "Donny",
            "metadata": {
                "created_from": "live_draft",
                "source_draft_id": DRAFT_ID,
                "league_id": LEAGUE_ID,
            },
        }
        archive = {"draft_id": DRAFT_ID, "draft_type": DRAFT_TYPE_LIVE, "team_name": "Donny"}
        draft_type, reason, _ = resolve_archive_draft_type_with_reason(context=context, archive_entry=archive)
        self.assertEqual(draft_type, DRAFT_TYPE_LIVE)
        self.assertIn(
            reason,
            {
                "context_explicit_live_origin",
                "canonical_shared_live_origin",
                "strong_live_draft_membership",
                "canonical_created_from_live_draft",
            },
        )


if __name__ == "__main__":
    unittest.main()
