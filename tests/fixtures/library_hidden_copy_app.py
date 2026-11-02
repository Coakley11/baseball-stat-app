"""Renders the real Saved Draft Library page for a seeded account (test fixture).

The shared league is supplied through the session (_fx_shared); every save the page attempts is
counted, not performed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

import fantasy_shared_league_authz as authz  # noqa: E402
from draft_archive_ui import render_saved_draft_library_page  # noqa: E402

shared = st.session_state.get("_fx_shared")
saves: list[str] = []


def _count_save(*_args, **kwargs):
    saves.append(str(kwargs.get("reason") or ""))
    return True


with patch.object(authz, "checked_load", return_value=(authz.LOAD_FOUND, shared)), patch(
    "fantasy_shared_league_store.load_shared_league", return_value=shared
), patch("baseball_persistent_state.force_save_baseball_state", side_effect=_count_save):
    render_saved_draft_library_page(st, st.session_state)

st.session_state["_fx_save_reasons"] = list(st.session_state.get("_fx_save_reasons") or []) + saves
