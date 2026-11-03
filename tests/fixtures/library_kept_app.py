"""Renders the real Saved Draft Library page for a seeded signed-in account (test fixture).
Account saves are counted in _fx_saves, not performed; the account-id helper returns this
session's cloud id, as it does for a signed-in account in the hosted app."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from draft_archive_ui import render_saved_draft_library_page  # noqa: E402

uid = str(st.session_state.get("_suite_cloud_user_id") or "")


def _save(*_a, **kw):
    st.session_state["_fx_saves"] = list(st.session_state.get("_fx_saves") or []) + [str(kw.get("reason") or "")]
    return True


def _disk(*_a, **_kw):
    return _save(reason="disk_write")


with patch("baseball_persistent_state.force_save_baseball_state", side_effect=_save), patch(
    "suite_user.get_account_user_id", return_value=uid
), patch("fantasy_league_team_ownership._resolve_user_id", return_value=uid), patch(
    "suite_user_persistence.save_user_state", side_effect=_disk
):
    render_saved_draft_library_page(st, st.session_state)
