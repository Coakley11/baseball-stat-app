"""Draft Simulation Test Mode widget state — seed keys before save/on_change."""

from __future__ import annotations

import copy
from typing import Any

DRAFT_LAB_PAGE = "Draft Simulation Test Mode"

# Post-draft results tabs (no Trade Simulator — trade ideas stay in exports only).
DRAFT_LAB_RESULT_TABS: tuple[str, ...] = (
    "Draft Board",
    "Team Rosters",
    "Team Analysis",
    "Best / Questionable Picks",
    "Exports",
)

_LAB_WINDOW_OPTIONS = [3, 4, 5]
_LAB_FORMAT_OPTIONS = ["5x5 Roto", "Points League"]

DRAFT_LAB_WIDGET_DEFAULTS: dict[str, Any] = {
    "draft_lab_window": 3,
    "draft_lab_scoring_type": "5x5 Roto",
    "draft_lab_format": "5x5 Roto",
    "draft_lab_projection_style": "Balanced",
    "draft_lab_picks_per_team": 15,
    "draft_lab_roster_team": "All Teams",
}

DRAFT_LAB_SNAPSHOT_KEYS = tuple(DRAFT_LAB_WIDGET_DEFAULTS.keys())

PENDING_DRAFT_LAB_HANDOFF_KEY = "_pending_draft_lab_handoff"
DRAFT_LAB_HANDOFF_WIDGET_KEYS: tuple[str, ...] = (
    "draft_lab_window",
    "draft_lab_scoring_type",
    "draft_lab_format",
    "draft_lab_projection_style",
    "draft_lab_picks_per_team",
    "draft_lab_team_count",
)


def stage_draft_lab_handoff_settings(session: dict[str, Any], keys: dict[str, Any]) -> None:
    """Queue restored Draft Lab widget values for pre-widget application."""
    if not keys:
        return
    pending = dict(session.get(PENDING_DRAFT_LAB_HANDOFF_KEY) or {})
    for key, val in keys.items():
        if key not in DRAFT_LAB_HANDOFF_WIDGET_KEYS:
            continue
        if val is None or str(val).strip() == "":
            continue
        pending[key] = val
    if pending:
        session[PENDING_DRAFT_LAB_HANDOFF_KEY] = pending


def has_pending_draft_lab_handoff(session: dict[str, Any]) -> bool:
    pending = session.get(PENDING_DRAFT_LAB_HANDOFF_KEY)
    return isinstance(pending, dict) and bool(pending)


def apply_pending_draft_lab_widget_keys(session: dict[str, Any]) -> bool:
    """Apply staged handoff values — only call before Draft Lab widgets are created."""
    pending = session.pop(PENDING_DRAFT_LAB_HANDOFF_KEY, None)
    if not isinstance(pending, dict) or not pending:
        return False
    coercers: dict[str, Any] = {
        "draft_lab_window": _coerce_window,
        "draft_lab_scoring_type": _coerce_format,
        "draft_lab_format": _coerce_format,
        "draft_lab_projection_style": str,
        "draft_lab_picks_per_team": _coerce_picks,
        "draft_lab_team_count": lambda v: max(1, int(v)),
    }
    for key, val in pending.items():
        if key not in DRAFT_LAB_HANDOFF_WIDGET_KEYS:
            continue
        coerce = coercers.get(key, str)
        try:
            session[key] = coerce(val) if coerce is not str else str(val)
        except (TypeError, ValueError):
            continue
    return True


def prepare_draft_lab_page_widgets(session: dict[str, Any]) -> None:
    """Apply pending handoff then seed any missing widget keys before render."""
    apply_pending_draft_lab_widget_keys(session)
    ensure_draft_lab_widget_keys(session)


def _page_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    pf = session.get("page_filter_state")
    if not isinstance(pf, dict):
        return {}
    block = pf.get(DRAFT_LAB_PAGE)
    return block if isinstance(block, dict) else {}


def _handoff_picks(session: dict[str, Any]) -> int | None:
    results = session.get("draft_lab_results")
    if isinstance(results, dict):
        handoff = results.get("handoff")
        if isinstance(handoff, dict) and handoff.get("picks_per_team") is not None:
            try:
                return int(handoff["picks_per_team"])
            except (TypeError, ValueError):
                pass
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = room.get("config") or {}
        try:
            return int(cfg.get("picks_per_team"))
        except (TypeError, ValueError):
            pass
    try:
        return int(session.get("live_draft_picks_per_team"))
    except (TypeError, ValueError):
        return None


def draft_lab_roster_view_options(session: dict[str, Any]) -> list[str]:
    stored = session.get("_draft_lab_team_names")
    if isinstance(stored, list) and stored:
        return [str(x) for x in stored]
    results = session.get("draft_lab_results")
    if isinstance(results, dict):
        handoff = results.get("handoff")
        if isinstance(handoff, dict) and handoff.get("team_names"):
            try:
                from draft_lab_analysis import draft_lab_roster_team_options

                return draft_lab_roster_team_options(list(handoff.get("team_names") or []))
            except ImportError:
                names = ["All Teams"] + [str(t) for t in handoff.get("team_names") or []]
                return names
        draft = results.get("draft")
        if draft is not None and hasattr(draft, "columns") and "Fantasy Team" in draft.columns:
            teams = sorted(draft["Fantasy Team"].dropna().astype(str).unique().tolist())
            try:
                from draft_lab_analysis import draft_lab_roster_team_options

                return draft_lab_roster_team_options(teams)
            except ImportError:
                return ["All Teams"] + teams
    n = session.get("draft_lab_team_count")
    try:
        count = int(n)
    except (TypeError, ValueError):
        count = 4
    return ["All Teams"] + [f"Team {i + 1}" for i in range(max(1, count))]


def _coerce_window(val: Any) -> int:
    try:
        w = int(val)
    except (TypeError, ValueError):
        return DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_window"]
    return w if w in _LAB_WINDOW_OPTIONS else DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_window"]


def _coerce_format(val: Any) -> str:
    try:
        from global_fantasy_settings_state import normalize_league_format

        return normalize_league_format(val)
    except ImportError:
        s = str(val or "").strip()
        if s in _LAB_FORMAT_OPTIONS:
            return s
        return DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_scoring_type"]


def _coerce_picks(val: Any) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_picks_per_team"]
    return max(1, min(25, n))


def _coerce_roster_view(val: Any, options: list[str]) -> str:
    s = str(val or "").strip()
    if s in options:
        return s
    if s and s != "All Teams":
        return s
    return options[0] if options else "All Teams"


def ensure_draft_lab_widget_keys(session: dict[str, Any]) -> None:
    """Populate missing draft-lab widget keys from page snapshot, then defaults."""
    snap = _page_snapshot(session)
    roster_options = draft_lab_roster_view_options(session)

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
            snap.get("draft_lab_window", session.get("draft_lab_window", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_window"]))
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
        picks = _handoff_picks(session)
        if picks is None:
            picks = snap.get("draft_lab_picks_per_team", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_picks_per_team"])
        session["draft_lab_picks_per_team"] = _coerce_picks(picks)
    else:
        session["draft_lab_picks_per_team"] = _coerce_picks(session["draft_lab_picks_per_team"])

    if "draft_lab_roster_team" not in session:
        session["draft_lab_roster_team"] = _coerce_roster_view(
            snap.get("draft_lab_roster_team", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_roster_team"]),
            roster_options,
        )
    else:
        session["draft_lab_roster_team"] = _coerce_roster_view(session["draft_lab_roster_team"], roster_options)


def sync_draft_lab_session_before_save(session: dict[str, Any]) -> None:
    ensure_draft_lab_widget_keys(session)
