"""Renders the real Saved Draft Library page for Shared League invite tests (test fixture).

The signed-in account comes from session keys (_suite_cloud_user_id, _suite_auth_external_id,
_suite_owned_workspace_id). Shared Leagues are a local-file store at _fx_league_root; usernames
resolve from _fx_suite_users; account saves are counted in _fx_saves, not performed."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from draft_archive_ui import render_saved_draft_library_page  # noqa: E402
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store  # noqa: E402

ss = st.session_state
set_shared_league_store(LocalFileSharedLeagueStore(root=Path(ss["_fx_league_root"])))
uid = str(ss.get("_suite_cloud_user_id") or "")
username = str(ss.get("_suite_auth_external_id") or "")
workspace = str(ss.get("_suite_owned_workspace_id") or "")
users = list(ss.get("_fx_suite_users") or [])


def _save(*_a, **kw):
    ss["_fx_saves"] = list(ss.get("_fx_saves") or []) + [str(kw.get("reason") or "")]
    return True


def _find(*, external_id: str = "", email: str = ""):
    return [dict(r) for r in users if external_id and r.get("external_id") == external_id]


with patch("baseball_persistent_state.force_save_baseball_state", side_effect=_save), patch(
    "suite_user.get_account_user_id", return_value=uid
), patch("fantasy_league_team_ownership._resolve_user_id", return_value=uid), patch(
    "fantasy_league_invites._resolve_external_id", return_value=username
), patch("fantasy_league_invites._resolve_workspace_id", return_value=workspace), patch(
    "suite_workspace.get_active_workspace_id", return_value=workspace
), patch("suite_storage_supabase.find_user_rows", side_effect=_find), patch(
    "fantasy_shared_league_store._anonymous_guest", return_value=False
):
    render_saved_draft_library_page(st, ss)
