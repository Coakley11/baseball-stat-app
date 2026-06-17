"""Draft Simulation Test Mode widget state — seed keys before save/on_change.

Streamlit ``on_change`` callbacks run at the start of a rerun, before the page
block executes ``validate_state_option``. If a widget key is not already in
``session_state`` (e.g. only ``draft_lab_scoring_type`` was restored from the
cloud blob), ``save_page_state`` snapshots only that key. These helpers ensure
all registered draft-lab keys exist before any save.
"""
from __future__ import annotations

import copy
from typing import Any

DRAFT_LAB_PAGE = "Draft Simulation Test Mode"

_LAB_WINDOW_OPTIONS = [3, 4, 5]
_LAB_FORMAT_OPTIONS = ["5x5 Roto", "Points League"]
_LAB_ROSTER_VIEW_OPTIONS = ["All Teams", "Team A", "Team B", "Team C", "Team D"]

DRAFT_LAB_WIDGET_DEFAULTS: dict[str, Any] = {
    "draft_lab_window": 3,
    "draft_lab_scoring_type": "5x5 Roto",
    "draft_lab_format": "5x5 Roto",
    "draft_lab_projection_style": "Balanced",
    "draft_lab_picks_per_team": 15,
    "draft_lab_roster_team": "All Teams",
}

# Keys snapshotted for this page (matches page_state.PAGE_STATE_REGISTRY).
DRAFT_LAB_SNAPSHOT_KEYS = tuple(DRAFT_LAB_WIDGET_DEFAULTS.keys())


def _page_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    pf = session.get("page_filter_state")
    if not isinstance(pf, dict):
        return {}
    block = pf.get(DRAFT_LAB_PAGE)
    return block if isinstance(block, dict) else {}


def _coerce_window(val: Any) -> int:
    try:
        w = int(val)
    except (TypeError, ValueError):
        return DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_window"]
    return w if w in _LAB_WINDOW_OPTIONS else DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_window"]


def _coerce_format(val: Any) -> str:
    s = str(val or "").strip()
    if s in _LAB_FORMAT_OPTIONS:
        return s
    low = s.lower()
    for opt in _LAB_FORMAT_OPTIONS:
        if low == opt.lower() or low in opt.lower() or opt.lower() in low:
            return opt
    return DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_scoring_type"]


def _coerce_picks(val: Any) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_picks_per_team"]
    return max(5, min(25, n))


def _coerce_roster_view(val: Any) -> str:
    s = str(val or "").strip()
    return s if s in _LAB_ROSTER_VIEW_OPTIONS else DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_roster_team"]


def ensure_draft_lab_widget_keys(session: dict[str, Any]) -> None:
    """Populate missing draft-lab widget keys from page snapshot, then defaults.

    Call before ``save_page_state`` inside ``on_change`` (callbacks run before
    widgets render) and at page entry before widgets draw.
    """
    snap = _page_snapshot(session)

    # Scoring format: prefer canonical room_format when no snapshot value.
    if "draft_lab_scoring_type" not in session:
        if "draft_lab_scoring_type" in snap:
            session["draft_lab_scoring_type"] = _coerce_format(snap["draft_lab_scoring_type"])
        elif "draft_lab_format" in snap:
            session["draft_lab_scoring_type"] = _coerce_format(snap["draft_lab_format"])
        elif session.get("room_format"):
            session["draft_lab_scoring_type"] = _coerce_format(session.get("room_format"))
        else:
            session["draft_lab_scoring_type"] = DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_scoring_type"]

    if "draft_lab_format" not in session:
        if "draft_lab_format" in snap:
            session["draft_lab_format"] = _coerce_format(snap["draft_lab_format"])
        else:
            session["draft_lab_format"] = session["draft_lab_scoring_type"]

    if "draft_lab_window" not in session:
        session["draft_lab_window"] = _coerce_window(
            snap.get("draft_lab_window", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_window"])
        )

    if "draft_lab_projection_style" not in session:
        style = snap.get("draft_lab_projection_style")
        if style is not None:
            session["draft_lab_projection_style"] = str(style)
        else:
            session["draft_lab_projection_style"] = str(
                session.get("fantasy_draft_projection_style")
                or DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_projection_style"]
            )

    if "draft_lab_picks_per_team" not in session:
        session["draft_lab_picks_per_team"] = _coerce_picks(
            snap.get("draft_lab_picks_per_team", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_picks_per_team"])
        )

    if "draft_lab_roster_team" not in session:
        session["draft_lab_roster_team"] = _coerce_roster_view(
            snap.get("draft_lab_roster_team", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_roster_team"])
        )


def sync_draft_lab_session_before_save(session: dict[str, Any]) -> None:
    """Ensure all draft-lab keys are in session before disk/cloud snapshot build."""
    ensure_draft_lab_widget_keys(session)
