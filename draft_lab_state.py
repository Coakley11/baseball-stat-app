"""Draft Simulation Test Mode widget state — seed keys before save/on_change."""

from __future__ import annotations

import copy
from typing import Any

DRAFT_LAB_PAGE = "Draft Lab / Simulation"
DRAFT_LAB_PAGE_LEGACY = "Draft Simulation Test Mode"

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
    "draft_lab_active_tab": "Draft Board",
}

DRAFT_LAB_SNAPSHOT_KEYS = tuple(DRAFT_LAB_WIDGET_DEFAULTS.keys())

# Non-widget canonical copies — safe to mutate during save/sync after widgets render.
DRAFT_LAB_CANONICAL_VALUE_KEYS: dict[str, str] = {
    "draft_lab_window": "_draft_lab_window_value",
    "draft_lab_scoring_type": "_draft_lab_scoring_type_value",
    "draft_lab_format": "_draft_lab_format_value",
    "draft_lab_projection_style": "_draft_lab_projection_style_value",
    "draft_lab_picks_per_team": "_draft_lab_picks_per_team_value",
    "draft_lab_roster_team": "_draft_lab_roster_team_value",
    "draft_lab_active_tab": "_draft_lab_active_tab_value",
}

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
    try:
        from shared_draft_context import apply_draft_shared_settings_to_widgets

        apply_draft_shared_settings_to_widgets(session, active_page=DRAFT_LAB_PAGE)
    except ImportError:
        pass
    ensure_draft_lab_widget_keys(session)
    prepare_draft_lab_results_hydration(session)


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


def _coerce_draft_lab_widget_value(key: str, raw: Any, session: dict[str, Any]) -> Any:
    """Coerce a draft-lab widget value without writing back to session."""
    roster_options = draft_lab_roster_view_options(session)
    if key == "draft_lab_window":
        return _coerce_window(raw)
    if key in ("draft_lab_scoring_type", "draft_lab_format"):
        return _coerce_format(raw)
    if key == "draft_lab_projection_style":
        return str(raw or DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_projection_style"])
    if key == "draft_lab_picks_per_team":
        return _coerce_picks(raw)
    if key == "draft_lab_roster_team":
        return _coerce_roster_view(raw, roster_options)
    if key == "draft_lab_active_tab":
        tab = str(raw or DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_active_tab"]).strip()
        return tab if tab in DRAFT_LAB_RESULT_TABS else DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_active_tab"]
    return raw


def _read_draft_lab_widget_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    """Read coerced draft-lab widget values without mutating widget-backed session keys."""
    snap = _page_snapshot(session)
    out: dict[str, Any] = {}
    for key in DRAFT_LAB_SNAPSHOT_KEYS:
        if key in session:
            raw = session[key]
        elif key in snap:
            raw = snap[key]
        elif key == "draft_lab_picks_per_team":
            raw = _handoff_picks(session) or DRAFT_LAB_WIDGET_DEFAULTS[key]
        elif key == "draft_lab_scoring_type" and session.get("room_format"):
            raw = session.get("room_format")
        elif key == "draft_lab_projection_style":
            raw = session.get("fantasy_draft_projection_style") or DRAFT_LAB_WIDGET_DEFAULTS[key]
        else:
            raw = DRAFT_LAB_WIDGET_DEFAULTS.get(key)
        out[key] = _coerce_draft_lab_widget_value(key, raw, session)
    return out


def _write_canonical_draft_lab_values(session: dict[str, Any], snapshot: dict[str, Any]) -> None:
    for widget_key, canonical_key in DRAFT_LAB_CANONICAL_VALUE_KEYS.items():
        if widget_key in snapshot:
            session[canonical_key] = snapshot[widget_key]


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

    if "draft_lab_roster_team" not in session:
        session["draft_lab_roster_team"] = _coerce_roster_view(
            snap.get("draft_lab_roster_team", DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_roster_team"]),
            roster_options,
        )

    if "draft_lab_active_tab" not in session:
        pref = str(session.get("draft_lab_preferred_tab") or snap.get("draft_lab_active_tab") or "").strip()
        if pref in DRAFT_LAB_RESULT_TABS:
            session["draft_lab_active_tab"] = pref
        else:
            session["draft_lab_active_tab"] = DRAFT_LAB_WIDGET_DEFAULTS["draft_lab_active_tab"]


def sync_draft_lab_session_before_save(session: dict[str, Any]) -> None:
    """Persist draft-lab settings/results without mutating widget-backed session keys."""
    snapshot = _read_draft_lab_widget_snapshot(session)
    _write_canonical_draft_lab_values(session, snapshot)
    pf = session.get("page_filter_state")
    if not isinstance(pf, dict):
        pf = {}
        session["page_filter_state"] = pf
    block = dict(pf.get(DRAFT_LAB_PAGE) or {})
    for key, val in snapshot.items():
        try:
            block[key] = copy.deepcopy(val)
        except Exception:
            block[key] = val
    if block:
        pf[DRAFT_LAB_PAGE] = block
    sync_draft_lab_results_state(session, widget_snapshot=snapshot)


DRAFT_LAB_PERSISTED_STATE_KEY = "draft_lab_persisted_state"


def _records_to_df(records: Any):
    import pandas as pd

    if not isinstance(records, list) or not records:
        return pd.DataFrame()
    try:
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()


def sync_draft_lab_results_state(
    session: dict[str, Any],
    *,
    widget_snapshot: dict[str, Any] | None = None,
) -> None:
    """Snapshot draft lab simulation outputs for cloud/disk restore."""
    results = session.get("draft_lab_results")
    if not isinstance(results, dict):
        return
    draft = results.get("draft")
    if draft is None or getattr(draft, "empty", True):
        return
    widget_settings = widget_snapshot if isinstance(widget_snapshot, dict) else _read_draft_lab_widget_snapshot(session)
    try:
        from fantasy_in_season_state import _df_records as _serialize_records
    except ImportError:
        def _serialize_records(df, *, limit: int = 5000):
            if df is None or getattr(df, "empty", True):
                return []
            return df.head(int(limit)).to_dict(orient="records")

    blob: dict[str, Any] = {
        "schema_version": 2,
        "draft_records": _serialize_records(draft, limit=5000),
        "team_summary_records": _serialize_records(results.get("team_summary"), limit=64),
        "strengths_records": _serialize_records(results.get("strengths"), limit=64),
        "pick_analysis_records": _serialize_records(results.get("pick_analysis"), limit=500),
        "gaps_records": _serialize_records(results.get("gaps"), limit=200),
        "trades_records": _serialize_records(results.get("trades"), limit=64),
        "actual_summary_records": _serialize_records(results.get("actual_summary"), limit=64),
        "analysis_context": results.get("analysis_context") if isinstance(results.get("analysis_context"), dict) else {},
        "handoff": results.get("handoff") if isinstance(results.get("handoff"), dict) else {},
        "source": str(results.get("source") or "").strip(),
        "widget_settings": dict(widget_settings),
        "picks_per_team": widget_settings.get("draft_lab_picks_per_team"),
        "active_tab": str(widget_settings.get("draft_lab_active_tab") or session.get("draft_lab_active_tab") or "").strip(),
        "preferred_tab": str(session.get("draft_lab_preferred_tab") or "").strip(),
        "team_names": list(session.get("_draft_lab_team_names") or []),
    }
    session[DRAFT_LAB_PERSISTED_STATE_KEY] = blob


def persist_draft_lab_results(session: dict[str, Any], st_obj: Any, *, reason: str) -> None:
    """Write Draft Lab simulation outputs to session blob and cloud/disk."""
    sync_draft_lab_results_state(session)
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st_obj, reason=reason)
    except Exception:
        pass


def hydrate_draft_lab_results_state(session: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """Restore draft_lab_results from persisted blob when session results are empty."""
    if isinstance(session.get("draft_lab_results"), dict):
        draft = session["draft_lab_results"].get("draft")
        if draft is not None and not getattr(draft, "empty", True):
            return False
    blob: dict[str, Any] | None = None
    if isinstance(state, dict):
        if isinstance(state.get(DRAFT_LAB_PERSISTED_STATE_KEY), dict):
            blob = state.get(DRAFT_LAB_PERSISTED_STATE_KEY)
        elif state.get("draft_records") is not None:
            blob = state
    if blob is None:
        raw = session.get(DRAFT_LAB_PERSISTED_STATE_KEY)
        blob = raw if isinstance(raw, dict) else None
    if not isinstance(blob, dict) or not blob.get("draft_records"):
        return False
    draft_df = _records_to_df(blob.get("draft_records"))
    if draft_df.empty:
        return False
    source = str(blob.get("source") or "").strip()
    session["draft_lab_results"] = {
        "draft": draft_df,
        "team_summary": _records_to_df(blob.get("team_summary_records")),
        "strengths": _records_to_df(blob.get("strengths_records")),
        "pick_analysis": _records_to_df(blob.get("pick_analysis_records")),
        "gaps": _records_to_df(blob.get("gaps_records")),
        "trades": _records_to_df(blob.get("trades_records")),
        "actual_summary": _records_to_df(blob.get("actual_summary_records")),
        "analysis_context": dict(blob.get("analysis_context") or {}),
        "handoff": dict(blob.get("handoff") or {}),
        **({"source": source} if source else {}),
    }
    for key, val in dict(blob.get("widget_settings") or {}).items():
        if key not in session and val is not None:
            session[key] = val
    active_tab = str(blob.get("active_tab") or blob.get("preferred_tab") or "").strip()
    if active_tab in DRAFT_LAB_RESULT_TABS:
        session["draft_lab_active_tab"] = active_tab
    team_names = blob.get("team_names")
    if isinstance(team_names, list) and team_names:
        session["_draft_lab_team_names"] = [str(x) for x in team_names]
    session[DRAFT_LAB_PERSISTED_STATE_KEY] = blob
    session["_draft_lab_restored"] = True
    return True


def prepare_draft_lab_results_hydration(session: dict[str, Any]) -> bool:
    return hydrate_draft_lab_results_state(session)
