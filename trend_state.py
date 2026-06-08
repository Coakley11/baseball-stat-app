"""Canonical Trend Value page state — chart player, multi players, chart + filters."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

_TEAM_SUFFIX = re.compile(r"^(.+?)\s+\(([A-Z]{2,4})\)$")

TREND_DIRTY_KEY = "trend_state_dirty"
TREND_LOCAL_EDIT_TS_KEY = "trend_state_last_local_edit_ts"

TREND_PLAYER_KEYS = (
    "single_trend_dashboard_player",
    "trend_players_multi",
)

TREND_CHART_KEYS = (
    "single_trend_dashboard_stats",
    "single_trend_dashboard_mode",
    "single_trend_dashboard_smooth_window",
    "trend_plot_stat",
    "trend_chart_mode",
    "trend_smooth_window",
)

TREND_FILTER_KEYS = (
    "trend_lag",
    "trend_min_g",
    "trend_position_filter",
    "trend_sort_col",
    "trend_use_draft_room_sync",
    "trend_sync_team_for_draft",
)

ResolveFn = Callable[[str, dict[str, Any]], str | None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_trend_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(TREND_DIRTY_KEY))


def mark_trend_local_edit(session: dict[str, Any]) -> None:
    session[TREND_DIRTY_KEY] = True
    session[TREND_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_trend_local_edit(session: dict[str, Any]) -> None:
    session.pop(TREND_DIRTY_KEY, None)
    session.pop(TREND_LOCAL_EDIT_TS_KEY, None)


def normalize_trend_label(
    raw: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in label_map:
        return s
    resolved = resolve_fn(s, label_map)
    if resolved and resolved in label_map:
        return resolved
    m = _TEAM_SUFFIX.match(s)
    if m:
        base = m.group(1).strip()
        resolved = resolve_fn(base, label_map)
        if resolved and resolved in label_map:
            return resolved
    return None


def reconcile_trend_player_list(
    raw_list: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
    *,
    max_players: int = 6,
) -> list[str]:
    if not isinstance(raw_list, list):
        return []
    out: list[str] = []
    for item in raw_list:
        lbl = normalize_trend_label(item, label_map, resolve_fn)
        if lbl and lbl not in out:
            out.append(lbl)
        if len(out) >= max_players:
            break
    return out


def canonical_chart_player(session: dict[str, Any]) -> str | None:
    """Return chart player when trend_state.chart_player key exists (empty string is valid)."""
    meta = session.get("trend_state")
    if isinstance(meta, dict) and "chart_player" in meta:
        val = meta.get("chart_player")
        return None if val is None else str(val)
    return None


def canonical_players_multi(session: dict[str, Any]) -> list[str] | None:
    meta = session.get("trend_state")
    if isinstance(meta, dict) and isinstance(meta.get("players_multi"), list):
        return list(meta["players_multi"])
    return None


def record_trend_field_write(
    session: dict[str, Any],
    field: str,
    source: str,
    old: Any = None,
    new: Any = None,
) -> None:
    session[f"_trend_last_write_{field}"] = source
    if old is not None:
        session[f"_trend_prev_{field}"] = old
    if new is not None:
        session[f"_trend_new_{field}"] = new


def _sync_chart_meta(session: dict[str, Any]) -> None:
    meta = session.get("trend_state")
    if not isinstance(meta, dict):
        return
    chart = {k: session[k] for k in TREND_CHART_KEYS if k in session}
    if chart:
        meta["chart"] = chart
    filters = {k: session[k] for k in TREND_FILTER_KEYS if k in session}
    if filters:
        meta["filters"] = filters


def _sync_page_filter_trend_block(session: dict[str, Any]) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault("Trend Value", {})
    if not isinstance(block, dict):
        block = {}
        pf["Trend Value"] = block
    meta = session.get("trend_state")
    if isinstance(meta, dict):
        block["trend_state"] = {
            "chart_player": meta.get("chart_player"),
            "players_multi": list(meta.get("players_multi") or []),
            "last_write_reason": meta.get("last_write_reason"),
        }
    cp = session.get("single_trend_dashboard_player")
    if cp is not None:
        block["single_trend_dashboard_player"] = cp
    multi = session.get("trend_players_multi")
    if isinstance(multi, list):
        block["trend_players_multi"] = list(multi)
    for ck in TREND_CHART_KEYS + TREND_FILTER_KEYS:
        if ck in session:
            block[ck] = session[ck]


def write_canonical_trend_state(
    session: dict[str, Any],
    *,
    chart_player: str | None = None,
    players_multi: list[str] | None = None,
    reason: str = "",
    local_edit: bool = False,
    update_chart_player: bool = True,
    update_players_multi: bool = True,
) -> dict[str, Any]:
    """Write canonical trend_state and mirror widget keys."""
    meta = session.get("trend_state")
    if not isinstance(meta, dict):
        meta = {}

    if update_chart_player and chart_player is not None:
        lbl = str(chart_player).strip() if chart_player else ""
        meta["chart_player"] = lbl or None
        if lbl:
            session["single_trend_dashboard_player"] = lbl
        else:
            session.pop("single_trend_dashboard_player", None)

    if update_players_multi and players_multi is not None:
        clean_multi = [str(p).strip() for p in players_multi if p][:6]
        meta["players_multi"] = list(clean_multi)
        session["trend_players_multi"] = list(clean_multi)

    meta["last_write_reason"] = reason or None
    session["trend_state"] = meta
    _sync_chart_meta(session)
    _sync_page_filter_trend_block(session)
    if local_edit:
        mark_trend_local_edit(session)
    if update_chart_player:
        record_trend_field_write(
            session, "single_trend_dashboard_player", reason or "canonical", new=meta.get("chart_player")
        )
    if update_players_multi:
        record_trend_field_write(
            session, "trend_players_multi", reason or "canonical", new=meta.get("players_multi")
        )
    return meta


def gather_trend_players_multi(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    if is_trend_locally_dirty(session):
        widget = session.get("trend_players_multi")
        if isinstance(widget, list):
            return reconcile_trend_player_list(widget, label_map, resolve_fn)
        canonical = canonical_players_multi(session)
        if canonical is not None:
            return reconcile_trend_player_list(canonical, label_map, resolve_fn)
        return []

    canonical = canonical_players_multi(session)
    if canonical is not None:
        return reconcile_trend_player_list(canonical, label_map, resolve_fn)

    widget = session.get("trend_players_multi")
    if isinstance(widget, list) and widget:
        return reconcile_trend_player_list(widget, label_map, resolve_fn)

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Trend Value")
        if isinstance(block, dict):
            cp = block.get("trend_players_multi")
            if isinstance(cp, list) and cp:
                return reconcile_trend_player_list(cp, label_map, resolve_fn)
    return []


def gather_chart_player(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> str | None:
    if is_trend_locally_dirty(session):
        raw = session.get("single_trend_dashboard_player")
        if raw:
            return normalize_trend_label(raw, label_map, resolve_fn)
        canonical = canonical_chart_player(session)
        if canonical is not None:
            return normalize_trend_label(canonical, label_map, resolve_fn) if canonical else None
        return None

    canonical = canonical_chart_player(session)
    if canonical is not None:
        return normalize_trend_label(canonical, label_map, resolve_fn) if canonical else None

    raw = session.get("single_trend_dashboard_player")
    if raw:
        return normalize_trend_label(raw, label_map, resolve_fn)

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Trend Value")
        if isinstance(block, dict):
            cp = block.get("single_trend_dashboard_player")
            if cp:
                return normalize_trend_label(cp, label_map, resolve_fn)
    return None


def prepare_trend_value_page(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> dict[str, Any]:
    """Reconcile trend keys before widgets render; preserve local widget edits."""
    if is_trend_locally_dirty(session):
        chart_lbl = gather_chart_player(session, label_map, resolve_fn)
        multi = gather_trend_players_multi(session, label_map, resolve_fn)
        return write_canonical_trend_state(
            session,
            chart_player=chart_lbl or "",
            players_multi=multi,
            reason="local_edit_preserve",
            local_edit=True,
        )

    pending_multi = session.get("pending_trend_players")
    if isinstance(pending_multi, list) and pending_multi:
        multi = reconcile_trend_player_list(pending_multi, label_map, resolve_fn)
        pending_single = session.pop("pending_trend_player", None)
        chart_lbl = (
            normalize_trend_label(pending_single, label_map, resolve_fn)
            if pending_single
            else (multi[0] if multi else None)
        )
        session.pop("pending_trend_players", None)
        return write_canonical_trend_state(
            session,
            chart_player=chart_lbl or "",
            players_multi=multi,
            reason="pending_trend",
        )

    if canonical_chart_player(session) is not None or canonical_players_multi(session) is not None:
        chart_lbl = gather_chart_player(session, label_map, resolve_fn)
        multi = gather_trend_players_multi(session, label_map, resolve_fn)
        return write_canonical_trend_state(
            session,
            chart_player=chart_lbl or "",
            players_multi=multi,
            reason="canonical_preserve",
        )

    chart_lbl = gather_chart_player(session, label_map, resolve_fn)
    multi = gather_trend_players_multi(session, label_map, resolve_fn)
    return write_canonical_trend_state(
        session,
        chart_player=chart_lbl or "",
        players_multi=multi,
        reason="reconcile_on_load" if (chart_lbl or multi) else "empty",
    )


def prepare_trend_chart_options(session: dict[str, Any]) -> None:
    if is_trend_locally_dirty(session):
        return
    meta = session.get("trend_state")
    chart: dict[str, Any] = {}
    filters: dict[str, Any] = {}
    if isinstance(meta, dict):
        if isinstance(meta.get("chart"), dict):
            chart = meta["chart"]
        if isinstance(meta.get("filters"), dict):
            filters = meta["filters"]
    pf = session.get("page_filter_state")
    block = pf.get("Trend Value") if isinstance(pf, dict) else None
    if not isinstance(block, dict):
        block = {}
    for key in TREND_CHART_KEYS + TREND_FILTER_KEYS:
        if key in session:
            continue
        if key in chart:
            session[key] = chart[key]
            record_trend_field_write(session, key, "trend_state.chart", new=chart[key])
        elif key in filters:
            session[key] = filters[key]
            record_trend_field_write(session, key, "trend_state.filters", new=filters[key])
        elif key in block:
            session[key] = block[key]
            record_trend_field_write(session, key, "page_filter_state", new=block[key])


def restore_trend_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_trend_locally_dirty(session):
        record_trend_field_write(session, "page_filter_restore", "blocked_local_dirty")
        return False
    snapshot = store.get("Trend Value") if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    import copy

    for key, value in snapshot.items():
        if key == "trend_state":
            continue
        old = session.get(key)
        try:
            session[key] = copy.deepcopy(value)
        except Exception:
            session[key] = value
        record_trend_field_write(session, key, "page_filter_state", old, value)
    return True


def sync_trend_chart_player_change(
    session: dict[str, Any],
    selected: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> str | None:
    lbl = normalize_trend_label(selected, label_map, resolve_fn)
    write_canonical_trend_state(
        session,
        chart_player=lbl or "",
        players_multi=canonical_players_multi(session) or session.get("trend_players_multi") or [],
        reason="chart_player_change",
        local_edit=True,
        update_players_multi=False,
    )
    return lbl


def sync_trend_multi_change(
    session: dict[str, Any],
    selected: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    players = reconcile_trend_player_list(selected, label_map, resolve_fn)
    write_canonical_trend_state(
        session,
        chart_player=canonical_chart_player(session) or session.get("single_trend_dashboard_player") or "",
        players_multi=players,
        reason="multi_change",
        local_edit=True,
        update_chart_player=False,
    )
    return players


def sync_trend_settings_change(session: dict[str, Any], *, reason: str = "settings_change") -> None:
    mark_trend_local_edit(session)
    meta = session.get("trend_state")
    if not isinstance(meta, dict):
        meta = {}
        session["trend_state"] = meta
    meta["last_write_reason"] = reason
    _sync_chart_meta(session)
    _sync_page_filter_trend_block(session)
    for key in TREND_CHART_KEYS + TREND_FILTER_KEYS:
        if key in session:
            record_trend_field_write(session, key, "widget", new=session[key])


def apply_trend_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    """Restore Trend page snapshot from Applied Math return without wiping unrelated keys."""
    wp = dict(source_state.get("widget_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    chart = dict(source_state.get("chart_params") or {})
    filt = dict(source_state.get("filter_params") or {})

    chart_player = ent.get("player_label") or wp.get("single_trend_dashboard_player") or chart.get("anchor_player")
    multi = chart.get("trend_players_multi") or ent.get("trend_players_multi") or chart.get("players")
    if not isinstance(multi, list):
        multi = []

    write_canonical_trend_state(
        session,
        chart_player=str(chart_player).strip() if chart_player else "",
        players_multi=multi,
        reason="ami_return",
        local_edit=False,
    )
    clear_trend_local_edit(session)

    if chart.get("stats"):
        session["single_trend_dashboard_stats"] = list(chart["stats"])
    for fk in TREND_CHART_KEYS + TREND_FILTER_KEYS:
        if fk in filt:
            session[fk] = filt[fk]
        elif fk in wp:
            session[fk] = wp[fk]
    _sync_chart_meta(session)
    _sync_page_filter_trend_block(session)


def render_trend_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("trend_state")
    if not isinstance(meta, dict):
        meta = {}
    rows = {
        "trend_state.chart_player": meta.get("chart_player"),
        "trend_state.players_multi": meta.get("players_multi"),
        "widget chart_player": session.get("single_trend_dashboard_player"),
        "widget players_multi": session.get("trend_players_multi"),
        "trend_state_dirty": session.get(TREND_DIRTY_KEY),
        "last_write_chart_player": session.get("_trend_last_write_single_trend_dashboard_player"),
        "last_write_players_multi": session.get("_trend_last_write_trend_players_multi"),
        "last_write_plot_stat": session.get("_trend_last_write_trend_plot_stat"),
        "last_write_chart_mode": session.get("_trend_last_write_trend_chart_mode"),
    }
    with st.sidebar.expander("Trend Value state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
