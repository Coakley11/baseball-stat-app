"""Renders the real Saved Draft Library page with a temp shared-room store (test fixture).
Account saves are counted in _fx_saves, not performed. The app's account-id helper returns this
session's cloud account id, as it does for a signed-in account in the hosted app."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from draft_room_shared_state import LocalFileSharedRoomStore  # noqa: E402
from draft_archive_ui import render_saved_draft_library_page  # noqa: E402

store = LocalFileSharedRoomStore(root=Path(st.session_state["_fx_room_root"]))
uid = str(st.session_state.get("_suite_cloud_user_id") or "")


def _save(*_a, **kw):
    st.session_state["_fx_saves"] = list(st.session_state.get("_fx_saves") or []) + [str(kw.get("reason") or "")]
    return True


with patch("draft_room_shared_state.get_shared_room_store", return_value=store), patch(
    "baseball_persistent_state.force_save_baseball_state", side_effect=_save
), patch("suite_user.get_account_user_id", return_value=uid), patch(
    "fantasy_league_team_ownership._resolve_user_id", return_value=uid
):
    render_saved_draft_library_page(st, st.session_state)
