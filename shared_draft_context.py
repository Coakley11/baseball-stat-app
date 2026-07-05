"""Canonical draft settings shared across draft-related pages (lookback, style, format)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Session blob — single source of truth (also mirrored to legacy top-level keys for cloud compat).
CANONICAL_SETTINGS_KEY = "draft_shared_settings"

# Legacy top-level keys (persisted in cloud blob; kept in sync with canonical blob).
GLOBAL_WINDOW_KEY = "room_window"
GLOBAL_PROJECTION_STYLE_KEY = "fantasy_draft_projection_style"

DEFAULT_LOOKBACK = 3
DEFAULT_PROJECTION_STYLE = "Balanced"
DEFAULT_FANTASY_FORMAT = "5x5 Roto"
DEFAULT_ML_BLEND_ENABLED = True
DEFAULT_ML_SIGNAL_WEIGHT = 0.12
DEFAULT_ML_MIN_RECENT_GAMES = 50
DEFAULT_MIN_GAMES = 50
DEFAULT_MIN_AT_BATS = 150

GLOBAL_ML_BLEND_KEY = "draft_use_ml_blend"
GLOBAL_ML_WEIGHT_KEY = "draft_ml_blend_weight"
GLOBAL_ML_MIN_GAMES_KEY = "draft_ml_min_games_signal"
GLOBAL_MIN_GAMES_KEY = "fantasy_sample_min_games"
GLOBAL_MIN_AB_KEY = "fantasy_sample_min_ab"

MIN_GAMES_ALIASES: tuple[str, ...] = (
    "trend_min_g",
    "value_min_g",
    "ml_min_games",
    "fantasy_market_min_g",
)

MIN_AB_ALIASES: tuple[str, ...] = (
    "ml_min_ab",
    "fantasy_market_min_ab",
)

WINDOW_ALIASES: dict[str, str] = {
    "draft_window": GLOBAL_WINDOW_KEY,
    "live_draft_proj_window": GLOBAL_WINDOW_KEY,
    "draft_lab_window": GLOBAL_WINDOW_KEY,
    "fantasy_market_window": GLOBAL_WINDOW_KEY,
}

PROJECTION_STYLE_ALIASES: dict[str, str] = {
    "live_draft_proj_style": GLOBAL_PROJECTION_STYLE_KEY,
    "draft_lab_projection_style": GLOBAL_PROJECTION_STYLE_KEY,
    "ml_projection_style": GLOBAL_PROJECTION_STYLE_KEY,
}

LOOKBACK_ANALYTICS_ALIASES: tuple[str, ...] = (
    "trend_lag",
    "value_lag",
    "ml_lookback",
)

_ALL_ALIASES: dict[str, str] = {**WINDOW_ALIASES, **PROJECTION_STYLE_ALIASES}

DRAFT_SYNC_PAGES: frozenset[str] = frozenset(
    {
        "Live Draft Room",
        "Draft Assistant Simulator",
        "Draft Room Simulator",
        "Draft Simulation Test Mode",
        "Draft Lab / Simulation",
        "Comparison Tool",
        "Trend Value",
        "Valuation",
        "Fantasy Sleepers & Busts",
        "Fantasy Lineup Assistant",
        "Fantasy Standings Tracker",
    }
)

_SHARED_CONTEXT_DIAG_KEY = "_shared_draft_context_diag"
_LAST_RESUME_KEY = "_suite_last_consumed_resume_key"
_CLOUD_SETTINGS_KEY = "_suite_last_cloud_draft_shared_settings"

# Widget keys owned by canonical draft settings — must not be restored from page snapshots.
DRAFT_SHARED_WIDGET_KEYS: frozenset[str] = frozenset(
    {
        GLOBAL_WINDOW_KEY,
        GLOBAL_PROJECTION_STYLE_KEY,
        GLOBAL_ML_BLEND_KEY,
        GLOBAL_ML_WEIGHT_KEY,
        GLOBAL_ML_MIN_GAMES_KEY,
        GLOBAL_MIN_GAMES_KEY,
        GLOBAL_MIN_AB_KEY,
        *MIN_GAMES_ALIASES,
        *MIN_AB_ALIASES,
        "sync_draft_assistant_position_needs",
        "trend_position_filter",
        "value_position_filter",
        "ml_position_filter",
        "fantasy_market_positions",
        *WINDOW_ALIASES.keys(),
        *PROJECTION_STYLE_ALIASES.keys(),
        *LOOKBACK_ANALYTICS_ALIASES,
        "draft_format",
        "fantasy_market_format",
        "draft_lab_scoring_type",
        "standings_scoring_format",
        "live_draft_scoring",
        "room_format",
    }
)

ML_BLEND_OFF_ROSTER_FIT_NOTE = (
    "ML projection blend is off. To include ML projection signal in roster fit, "
    "enable it in Draft Assistant Simulator → Advanced Scoring Settings."
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_draft_sync_page(active_page: str) -> bool:
    return str(active_page or "").strip() in DRAFT_SYNC_PAGES


def is_draft_shared_session_key(key: str) -> bool:
    return str(key or "") in DRAFT_SHARED_WIDGET_KEYS


def shared_draft_context_snapshot_excluded_keys() -> frozenset[str]:
    return frozenset({CANONICAL_SETTINGS_KEY, *DRAFT_SHARED_WIDGET_KEYS})


def _normalize_format(val: Any) -> str:
    try:
        from global_fantasy_settings_state import normalize_league_format

        return normalize_league_format(val)
    except ImportError:
        s = str(val or "").strip()
        return s or DEFAULT_FANTASY_FORMAT


def _normalize_projection_style_canonical(style: Any) -> str:
    s = str(style or "").strip()
    if not s:
        return DEFAULT_PROJECTION_STYLE
    if s == "Aggressive":
        return "Aggressive / Upside"
    if s in ("Conservative", "Balanced", "Aggressive / Upside"):
        return s
    if "Aggressive" in s:
        return "Aggressive / Upside"
    return DEFAULT_PROJECTION_STYLE


def _projection_style_for_widget_alias(canonical_style: str, alias_key: str) -> str:
    canonical = _normalize_projection_style_canonical(canonical_style)
    if alias_key == "ml_projection_style":
        return "Aggressive" if canonical == "Aggressive / Upside" else canonical
    return canonical


def _read_min_games(session: dict[str, Any], blob: dict[str, Any]) -> int:
    if blob.get("min_games") is not None:
        return int(blob["min_games"])
    for key in MIN_GAMES_ALIASES:
        if session.get(key) is not None:
            return int(session[key])
    return DEFAULT_MIN_GAMES


def _read_min_at_bats(session: dict[str, Any], blob: dict[str, Any]) -> int:
    if blob.get("min_at_bats") is not None:
        return int(blob["min_at_bats"])
    for key in MIN_AB_ALIASES:
        if session.get(key) is not None:
            return int(session[key])
    return DEFAULT_MIN_AT_BATS


def _coerce_bool(val: Any, default: bool) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return default


def _read_ml_blend_enabled(session: dict[str, Any], blob: dict[str, Any]) -> bool:
    if "ml_blend_enabled" in blob:
        return _coerce_bool(blob.get("ml_blend_enabled"), DEFAULT_ML_BLEND_ENABLED)
    if session.get(GLOBAL_ML_BLEND_KEY) is not None:
        return _coerce_bool(session.get(GLOBAL_ML_BLEND_KEY), DEFAULT_ML_BLEND_ENABLED)
    return DEFAULT_ML_BLEND_ENABLED


def _read_ml_signal_weight(session: dict[str, Any], blob: dict[str, Any]) -> float:
    if blob.get("ml_signal_weight") is not None:
        return float(blob["ml_signal_weight"])
    if session.get(GLOBAL_ML_WEIGHT_KEY) is not None:
        return float(session[GLOBAL_ML_WEIGHT_KEY])
    return DEFAULT_ML_SIGNAL_WEIGHT


def _read_ml_min_recent_games(session: dict[str, Any], blob: dict[str, Any]) -> int:
    if blob.get("ml_min_recent_games") is not None:
        return int(blob["ml_min_recent_games"])
    if session.get(GLOBAL_ML_MIN_GAMES_KEY) is not None:
        return int(session[GLOBAL_ML_MIN_GAMES_KEY])
    return DEFAULT_ML_MIN_RECENT_GAMES


def read_canonical_draft_settings(session: dict[str, Any]) -> dict[str, Any]:
    """Return canonical lookback / projection style / fantasy format / ML scoring."""
    blob = session.get(CANONICAL_SETTINGS_KEY)
    if not isinstance(blob, dict):
        blob = {}
    lookback = blob.get("lookback_window")
    if lookback is None:
        lookback = session.get(GLOBAL_WINDOW_KEY)
    if lookback is None:
        for alias in (*WINDOW_ALIASES, *LOOKBACK_ANALYTICS_ALIASES):
            if session.get(alias) is not None:
                lookback = session.get(alias)
                break
    style = blob.get("projection_style")
    if style is None:
        style = session.get(GLOBAL_PROJECTION_STYLE_KEY)
    if style is None:
        for alias in PROJECTION_STYLE_ALIASES:
            if session.get(alias) is not None:
                style = session.get(alias)
                break
    fmt = blob.get("fantasy_format")
    if fmt is None:
        fmt = session.get("room_format")
    return {
        "lookback_window": int(lookback) if lookback is not None else DEFAULT_LOOKBACK,
        "projection_style": _normalize_projection_style_canonical(style),
        "fantasy_format": _normalize_format(fmt),
        "ml_blend_enabled": _read_ml_blend_enabled(session, blob),
        "ml_signal_weight": _read_ml_signal_weight(session, blob),
        "ml_min_recent_games": _read_ml_min_recent_games(session, blob),
        "min_games": _read_min_games(session, blob),
        "min_at_bats": _read_min_at_bats(session, blob),
        "sync_position_needs_to_research": _coerce_bool(
            blob.get("sync_position_needs_to_research", session.get("sync_draft_assistant_position_needs")),
            False,
        ),
        "updated_at": blob.get("updated_at"),
        "updated_by_page": blob.get("updated_by_page"),
    }


def read_draft_scoring_settings(session: dict[str, Any]) -> dict[str, Any]:
    """Alias for canonical draft + ML scoring settings (pool builders, profile cards)."""
    return read_canonical_draft_settings(session)


def draft_pool_kwargs_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """Keyword args for ``get_cached_unified_projection_pool`` from session/canonical settings."""
    cur = read_draft_scoring_settings(session)
    return {
        "draft_window": int(cur["lookback_window"]),
        "fantasy_format": str(cur["fantasy_format"]),
        "projection_style": str(cur["projection_style"]),
        "use_ml_blend": bool(cur["ml_blend_enabled"]),
        "ml_blend_weight": float(cur["ml_signal_weight"]),
        "ml_min_games_for_signal": int(cur["ml_min_recent_games"]),
    }


def hydrate_canonical_draft_settings_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """Build/sync canonical blob from top-level session keys (e.g. after cloud restore)."""
    prev_blob = session.get(CANONICAL_SETTINGS_KEY)
    if not isinstance(prev_blob, dict):
        prev_blob = {}
    cur = read_canonical_draft_settings(session)
    blob = {
        "lookback_window": cur["lookback_window"],
        "projection_style": cur["projection_style"],
        "fantasy_format": cur["fantasy_format"],
        "ml_blend_enabled": cur["ml_blend_enabled"],
        "ml_signal_weight": cur["ml_signal_weight"],
        "ml_min_recent_games": cur["ml_min_recent_games"],
        "min_games": cur["min_games"],
        "min_at_bats": cur["min_at_bats"],
        "sync_position_needs_to_research": cur.get("sync_position_needs_to_research"),
        "updated_at": cur.get("updated_at"),
        "updated_by_page": cur.get("updated_by_page"),
    }
    for extra in ("draft_assistant_position_needs", "research_position_filters"):
        if extra in prev_blob:
            blob[extra] = prev_blob[extra]
    session[CANONICAL_SETTINGS_KEY] = blob
    if cur.get("sync_position_needs_to_research") is not None:
        session["sync_draft_assistant_position_needs"] = bool(cur["sync_position_needs_to_research"])
    return cur


def _mirror_window_and_style_aliases(session: dict[str, Any], *, lookback: int, style: str) -> None:
    canonical_style = _normalize_projection_style_canonical(style)
    session[GLOBAL_PROJECTION_STYLE_KEY] = canonical_style
    for alias, canonical in _ALL_ALIASES.items():
        if canonical == GLOBAL_WINDOW_KEY:
            session[alias] = int(lookback)
        else:
            session[alias] = _projection_style_for_widget_alias(canonical_style, alias)
    session[GLOBAL_WINDOW_KEY] = int(lookback)
    for alias in LOOKBACK_ANALYTICS_ALIASES:
        session[alias] = int(lookback)


def _mirror_sample_size_aliases(session: dict[str, Any], *, min_games: int, min_at_bats: int) -> None:
    session[GLOBAL_MIN_GAMES_KEY] = int(min_games)
    session[GLOBAL_MIN_AB_KEY] = int(min_at_bats)
    for alias in MIN_GAMES_ALIASES:
        session[alias] = int(min_games)
    for alias in MIN_AB_ALIASES:
        session[alias] = int(min_at_bats)


def _mirror_ml_aliases(
    session: dict[str, Any],
    *,
    ml_blend_enabled: bool,
    ml_signal_weight: float,
    ml_min_recent_games: int,
) -> None:
    session[GLOBAL_ML_BLEND_KEY] = bool(ml_blend_enabled)
    session[GLOBAL_ML_WEIGHT_KEY] = float(ml_signal_weight)
    session[GLOBAL_ML_MIN_GAMES_KEY] = int(ml_min_recent_games)


def _mirror_format_aliases(session: dict[str, Any], fmt: str) -> None:
    try:
        from global_fantasy_settings_state import write_canonical_global_fantasy_settings

        write_canonical_global_fantasy_settings(session, format_=fmt, reason="draft_shared_settings")
    except ImportError:
        session["room_format"] = _normalize_format(fmt)


def write_canonical_draft_settings(
    session: dict[str, Any],
    *,
    lookback_window: int | None = None,
    projection_style: str | None = None,
    fantasy_format: str | None = None,
    ml_blend_enabled: bool | None = None,
    ml_signal_weight: float | None = None,
    ml_min_recent_games: int | None = None,
    min_games: int | None = None,
    min_at_bats: int | None = None,
    lookback: int | None = None,
    format_: str | None = None,
    source_page: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Single write path for all draft shared settings."""
    if lookback is not None:
        lookback_window = lookback
    if format_ is not None:
        fantasy_format = format_
    cur = read_canonical_draft_settings(session)
    if lookback_window is not None:
        cur["lookback_window"] = int(lookback_window)
    if projection_style is not None:
        cur["projection_style"] = _normalize_projection_style_canonical(projection_style)
    if fantasy_format is not None:
        cur["fantasy_format"] = _normalize_format(fantasy_format)
    if ml_blend_enabled is not None:
        cur["ml_blend_enabled"] = bool(ml_blend_enabled)
    if ml_signal_weight is not None:
        cur["ml_signal_weight"] = float(ml_signal_weight)
    if ml_min_recent_games is not None:
        cur["ml_min_recent_games"] = int(ml_min_recent_games)
    if min_games is not None:
        cur["min_games"] = int(min_games)
    if min_at_bats is not None:
        cur["min_at_bats"] = int(min_at_bats)
    now = _utc_now_iso()
    cur["updated_at"] = now
    cur["updated_by_page"] = str(source_page or "").strip() or None
    prev_blob = session.get(CANONICAL_SETTINGS_KEY)
    if isinstance(prev_blob, dict):
        for extra in ("draft_assistant_position_needs", "research_position_filters", "sync_position_needs_to_research"):
            if extra not in cur and extra in prev_blob:
                cur[extra] = prev_blob[extra]
    session[CANONICAL_SETTINGS_KEY] = dict(cur)
    _mirror_window_and_style_aliases(
        session,
        lookback=cur["lookback_window"],
        style=cur["projection_style"],
    )
    _mirror_format_aliases(session, cur["fantasy_format"])
    _mirror_ml_aliases(
        session,
        ml_blend_enabled=cur["ml_blend_enabled"],
        ml_signal_weight=cur["ml_signal_weight"],
        ml_min_recent_games=cur["ml_min_recent_games"],
    )
    _mirror_sample_size_aliases(
        session,
        min_games=cur["min_games"],
        min_at_bats=cur["min_at_bats"],
    )
    session["_shared_draft_context_last_update_reason"] = reason or None
    _record_diag(session, step=f"write:{reason or 'unspecified'}", active_page=source_page)
    return cur


def apply_draft_shared_settings_to_widgets(
    session: dict[str, Any],
    *,
    active_page: str = "",
    force_all_pages: bool = False,
) -> dict[str, Any]:
    """Force canonical values into every draft-page widget alias (pre-render)."""
    if active_page and not force_all_pages and not is_draft_sync_page(active_page):
        return read_canonical_draft_settings(session)
    cur = hydrate_canonical_draft_settings_from_session(session)
    _mirror_window_and_style_aliases(
        session,
        lookback=cur["lookback_window"],
        style=cur["projection_style"],
    )
    _mirror_format_aliases(session, cur["fantasy_format"])
    _mirror_ml_aliases(
        session,
        ml_blend_enabled=cur["ml_blend_enabled"],
        ml_signal_weight=cur["ml_signal_weight"],
        ml_min_recent_games=cur["ml_min_recent_games"],
    )
    _mirror_sample_size_aliases(
        session,
        min_games=cur["min_games"],
        min_at_bats=cur["min_at_bats"],
    )
    if cur.get("sync_position_needs_to_research") is not None:
        session["sync_draft_assistant_position_needs"] = bool(cur["sync_position_needs_to_research"])
    try:
        from global_fantasy_settings_state import prepare_global_fantasy_settings

        prepare_global_fantasy_settings(session, force_mirror=True)
    except ImportError:
        pass
    _record_diag(session, step=f"apply_widgets:{active_page or 'global'}", active_page=active_page)
    return cur


def prepare_canonical_scoring_context(
    session: dict[str, Any],
    *,
    active_page: str = "",
) -> dict[str, Any]:
    """Before widgets on any scoring-related page: canonical always wins."""
    return apply_draft_shared_settings_to_widgets(
        session,
        active_page=active_page,
        force_all_pages=True,
    )


def prepare_shared_draft_context(
    session: dict[str, Any],
    *,
    active_page: str = "",
    force_mirror: bool = False,
) -> None:
    """Before widgets on a draft page: canonical always wins."""
    if active_page and not force_mirror and not is_draft_sync_page(active_page):
        return
    apply_draft_shared_settings_to_widgets(
        session,
        active_page=active_page,
        force_all_pages=bool(force_mirror),
    )


# Back-compat aliases
write_shared_draft_context = write_canonical_draft_settings


def on_alias_lookback_changed(session: dict[str, Any], alias_key: str, *, source_page: str = "") -> None:
    val = session.get(alias_key)
    if val is not None:
        write_canonical_draft_settings(
            session,
            lookback_window=int(val),
            source_page=source_page or alias_key,
            reason=f"lookback:{alias_key}",
        )


def on_alias_projection_style_changed(session: dict[str, Any], alias_key: str, *, source_page: str = "") -> None:
    val = session.get(alias_key)
    if val is not None:
        write_canonical_draft_settings(
            session,
            projection_style=str(val),
            source_page=source_page or alias_key,
            reason=f"projection_style:{alias_key}",
        )


def on_alias_format_changed_for_draft(session: dict[str, Any], alias_key: str, *, source_page: str = "") -> None:
    val = session.get(alias_key)
    if val is not None:
        write_canonical_draft_settings(
            session,
            fantasy_format=str(val),
            source_page=source_page or alias_key,
            reason=f"format:{alias_key}",
        )


def on_draft_settings_changed(
    session: dict[str, Any],
    *,
    source_page: str,
    lookback_key: str | None = None,
    style_key: str | None = None,
    format_key: str | None = None,
    ml_blend_key: str | None = None,
    ml_weight_key: str | None = None,
    ml_min_games_key: str | None = None,
    min_games_key: str | None = None,
    min_ab_key: str | None = None,
) -> None:
    kwargs: dict[str, Any] = {"source_page": source_page, "reason": f"widget:{source_page}"}
    if lookback_key and session.get(lookback_key) is not None:
        kwargs["lookback_window"] = int(session[lookback_key])
    if style_key and session.get(style_key) is not None:
        kwargs["projection_style"] = _normalize_projection_style_canonical(session[style_key])
    if format_key and session.get(format_key) is not None:
        kwargs["fantasy_format"] = str(session[format_key])
    if ml_blend_key and ml_blend_key in session:
        kwargs["ml_blend_enabled"] = bool(session[ml_blend_key])
    if ml_weight_key and session.get(ml_weight_key) is not None:
        kwargs["ml_signal_weight"] = float(session[ml_weight_key])
    if ml_min_games_key and session.get(ml_min_games_key) is not None:
        kwargs["ml_min_recent_games"] = int(session[ml_min_games_key])
    if min_games_key and session.get(min_games_key) is not None:
        kwargs["min_games"] = int(session[min_games_key])
    if min_ab_key and session.get(min_ab_key) is not None:
        kwargs["min_at_bats"] = int(session[min_ab_key])
    if len(kwargs) > 2:
        write_canonical_draft_settings(session, **kwargs)


def is_ml_blend_enabled(session: dict[str, Any]) -> bool:
    return bool(read_draft_scoring_settings(session).get("ml_blend_enabled"))


def render_ml_blend_off_note(st: Any, session: dict[str, Any]) -> None:
    """Optional helper when roster fit is shown without ML blend."""
    if is_ml_blend_enabled(session):
        return
    st.caption(ML_BLEND_OFF_ROSTER_FIT_NOTE)


def has_active_draft_context(session: dict[str, Any]) -> bool:
    """True when a live or simulator draft exists (diagnostics only)."""
    try:
        from draft_room_state import DRAFT_ROOM_TABLE_KEY, get_active_draft_status, table_pick_count

        status = get_active_draft_status(session)
        if status.get("active"):
            return True
        if int(status.get("pick_count") or 0) > 0:
            return True
        if table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)) > 0:
            return True
    except ImportError:
        pass
    try:
        from draft_room_state import live_draft_handoff_pick_count
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, has_active_live_draft

        if has_active_live_draft(session):
            return True
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict):
            if str(room.get("status") or "") in ("in_progress", "paused", "complete"):
                return True
            if live_draft_handoff_pick_count(room) > 0:
                return True
    except ImportError:
        room = session.get("live_draft_room")
        if isinstance(room, dict) and str(room.get("status") or "") in (
            "in_progress",
            "paused",
            "complete",
        ):
            return True
    return False


def draft_shared_settings_diagnostics(
    session: dict[str, Any],
    *,
    active_page: str = "",
    widget_lookback_key: str | None = None,
    widget_style_key: str | None = None,
    widget_format_key: str | None = None,
) -> dict[str, Any]:
    canonical = read_canonical_draft_settings(session)
    cloud = session.get(_CLOUD_SETTINGS_KEY) if isinstance(session.get(_CLOUD_SETTINGS_KEY), dict) else {}
    w_lookback = session.get(widget_lookback_key) if widget_lookback_key else None
    w_style = session.get(widget_style_key) if widget_style_key else None
    w_format = session.get(widget_format_key) if widget_format_key else None
    page_restore_overwrote = bool(session.get("_draft_shared_page_restore_blocked"))
    return {
        "active_page": active_page,
        "draft_sync_page": is_draft_sync_page(active_page),
        "live_draft_active": has_active_draft_context(session),
        "canonical_lookback_window": canonical["lookback_window"],
        "canonical_projection_style": canonical["projection_style"],
        "canonical_fantasy_format": canonical["fantasy_format"],
        "canonical_ml_blend_enabled": canonical["ml_blend_enabled"],
        "canonical_ml_signal_weight": canonical["ml_signal_weight"],
        "canonical_ml_min_recent_games": canonical["ml_min_recent_games"],
        "widget_lookback": w_lookback,
        "widget_projection_style": w_style,
        "widget_format": w_format,
        "widget_lookback_key": widget_lookback_key,
        "widget_style_key": widget_style_key,
        "widget_format_key": widget_format_key,
        "lookback_matches_canonical": w_lookback is None or int(w_lookback) == int(canonical["lookback_window"]),
        "style_matches_canonical": w_style is None or str(w_style) == str(canonical["projection_style"]),
        "format_matches_canonical": w_format is None or _normalize_format(w_format) == canonical["fantasy_format"],
        "source_used": "canonical",
        "last_updated_page": canonical.get("updated_by_page"),
        "last_updated_at": canonical.get("updated_at"),
        "cloud_lookback": cloud.get("lookback_window"),
        "cloud_projection_style": cloud.get("projection_style"),
        "cloud_fantasy_format": cloud.get("fantasy_format"),
        "local_canonical_blob": session.get(CANONICAL_SETTINGS_KEY),
        "page_restore_blocked_shared_keys": page_restore_overwrote,
        "window_aliases": {a: session.get(a) for a in WINDOW_ALIASES},
        "projection_aliases": {a: session.get(a) for a in PROJECTION_STYLE_ALIASES},
        "last_update_reason": session.get("_shared_draft_context_last_update_reason"),
    }


shared_draft_context_diagnostics = draft_shared_settings_diagnostics


def render_draft_shared_settings_diagnostics(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str,
    widget_lookback_key: str | None = None,
    widget_style_key: str | None = None,
    widget_format_key: str | None = None,
) -> None:
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=st):
            return
    except ImportError:
        return
    diag = draft_shared_settings_diagnostics(
        session,
        active_page=active_page,
        widget_lookback_key=widget_lookback_key,
        widget_style_key=widget_style_key,
        widget_format_key=widget_format_key,
    )
    with st.expander("Draft settings sync", expanded=False):
        st.caption(
            f"Canonical: Lookback **{diag['canonical_lookback_window']}** yr · "
            f"Style **{diag['canonical_projection_style']}** · "
            f"Format **{diag['canonical_fantasy_format']}** · "
            f"ML blend **{'on' if diag.get('canonical_ml_blend_enabled') else 'off'}**"
        )
        if diag.get("last_updated_page"):
            st.caption(
                f"Last updated on **{diag['last_updated_page']}** "
                f"at {diag.get('last_updated_at') or '—'}"
            )
        if diag.get("widget_lookback") is not None:
            ok = "✓" if diag.get("lookback_matches_canonical") else "≠ canonical"
            st.text(f"Widget lookback: {diag['widget_lookback']} ({ok})")
        if diag.get("widget_projection_style") is not None:
            ok = "✓" if diag.get("style_matches_canonical") else "≠ canonical"
            st.text(f"Widget style: {diag['widget_projection_style']} ({ok})")
        if diag.get("widget_format") is not None:
            ok = "✓" if diag.get("format_matches_canonical") else "≠ canonical"
            st.text(f"Widget format: {diag['widget_format']} ({ok})")
        if diag.get("cloud_lookback") is not None:
            st.caption(
                f"Cloud: Lookback {diag.get('cloud_lookback')} · "
                f"Style {diag.get('cloud_projection_style')} · "
                f"Format {diag.get('cloud_fantasy_format')}"
            )
        if developer_mode_detail := session.get(_SHARED_CONTEXT_DIAG_KEY):
            st.json(developer_mode_detail)


def record_cloud_draft_settings_snapshot(session: dict[str, Any], cloud_state: dict[str, Any]) -> None:
    cur = read_canonical_draft_settings({**session, **cloud_state})
    session[_CLOUD_SETTINGS_KEY] = {
        "lookback_window": cur["lookback_window"],
        "projection_style": cur["projection_style"],
        "fantasy_format": cur["fantasy_format"],
        "ml_blend_enabled": cur["ml_blend_enabled"],
        "ml_signal_weight": cur["ml_signal_weight"],
        "ml_min_recent_games": cur["ml_min_recent_games"],
    }


def _record_diag(session: dict[str, Any], *, step: str, active_page: str = "") -> None:
    session[_SHARED_CONTEXT_DIAG_KEY] = {
        **draft_shared_settings_diagnostics(session, active_page=active_page),
        "step": step,
    }


def mark_resume_key_consumed(session: dict[str, Any], resume_key: str) -> None:
    session[_LAST_RESUME_KEY] = str(resume_key or "").strip()


def is_fresh_resume_request(session: dict[str, Any], resume_key: str) -> bool:
    key = str(resume_key or "").strip()
    if not key:
        return False
    return key != str(session.get(_LAST_RESUME_KEY) or "").strip()
