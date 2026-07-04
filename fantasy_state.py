"""Canonical Fantasy cluster page state — Sleepers, Standings, Lineup."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

FANTASY_SLEEPERS_PAGE = "Fantasy Sleepers & Busts"
FANTASY_STANDINGS_PAGE = "Fantasy Standings Tracker"
FANTASY_LINEUP_PAGE = "Fantasy Lineup Assistant"

FANTASY_PAGES = frozenset({FANTASY_SLEEPERS_PAGE, FANTASY_STANDINGS_PAGE, FANTASY_LINEUP_PAGE})

FANTASY_DIRTY_KEY = "fantasy_state_dirty"
FANTASY_LOCAL_EDIT_TS_KEY = "fantasy_state_last_local_edit_ts"
FANTASY_PENDING_SYNC_PREFIX = "_fantasy_filters_pending_sync_"

SLEEPERS_FILTER_KEYS = (
    "fantasy_market_window",
    "fantasy_market_format",
    "fantasy_market_min_g",
    "fantasy_market_min_ab",
    "fantasy_market_top_n",
    "fantasy_market_positions",
    "fantasy_market_age_range",
    "sleeper_max_market_rank",
    "sleeper_max_model_rank",
    "sleeper_min_proj_hr",
    "sleeper_min_expected_value",
    "sleeper_use_draft_room_needs",
    "sleeper_sync_team",
    "sleeper_focus_needed_positions",
    "fantasy_market_scatter_color",
    "fantasy_market_scatter_size",
    "fantasy_edge_scatter_view_mode",
    "fantasy_market_edge_trendline_type",
    "fantasy_pts_r",
    "fantasy_pts_rbi",
    "fantasy_pts_hr",
    "fantasy_pts_sb",
    "fantasy_pts_bb",
    "fantasy_pts_h",
    "fantasy_pts_xbh",
    "fantasy_pts_ab_penalty",
)

SLEEPERS_ENTITY_KEYS = ("fantasy_market_selected_player",)

STANDINGS_FILTER_KEYS = (
    "standings_scoring_format",
    "standings_stats_source",
    "standings_api_season",
)

LINEUP_FILTER_KEYS = (
    "lineup_team",
    "lineup_format",
    "lineup_bench_rows",
    "lineup_include_util",
    "lineup_custom_slots",
    "lineup_diagnosis_rate_col",
    "lineup_trade_my_team",
    "lineup_trade_other_team",
    "lineup_trade_give_players",
    "lineup_trade_get_players",
    "lineup_trade_idea_mode",
    "lineup_trade_ideas_forced_give",
    "lineup_trade_ideas_forced_get",
    "lineup_pts_r",
    "lineup_pts_rbi",
    "lineup_pts_hr",
    "lineup_pts_sb",
    "lineup_pts_h",
    "lineup_pts_bb",
    "lineup_pts_ops",
)

SECTION_KEYS: dict[str, tuple[str, ...]] = {
    "sleepers": SLEEPERS_FILTER_KEYS + SLEEPERS_ENTITY_KEYS,
    "standings": STANDINGS_FILTER_KEYS,
    "lineup": LINEUP_FILTER_KEYS,
}

PAGE_TO_SECTION = {
    FANTASY_SLEEPERS_PAGE: "sleepers",
    FANTASY_STANDINGS_PAGE: "standings",
    FANTASY_LINEUP_PAGE: "lineup",
}


def _draft_shared_filter_keys() -> frozenset[str]:
    try:
        from shared_draft_context import DRAFT_SHARED_WIDGET_KEYS

        return frozenset(
            k
            for k in DRAFT_SHARED_WIDGET_KEYS
            if k
            in {
                "fantasy_market_window",
                "fantasy_market_format",
                "standings_scoring_format",
                "draft_window",
                "draft_lab_window",
                "draft_lab_scoring_type",
                "live_draft_proj_window",
                "live_draft_proj_style",
                "draft_lab_projection_style",
                "live_draft_scoring",
            }
        )
    except ImportError:
        return frozenset(
            {
                "fantasy_market_window",
                "fantasy_market_format",
                "standings_scoring_format",
            }
        )


def _strip_draft_shared_from_filters(filt: dict[str, Any]) -> dict[str, Any]:
    shared = _draft_shared_filter_keys()
    return {k: v for k, v in filt.items() if k not in shared}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def section_for_page(page: str) -> str | None:
    return PAGE_TO_SECTION.get(str(page or "").strip())


def _pending_key(section: str) -> str:
    return f"{FANTASY_PENDING_SYNC_PREFIX}{section}"


def is_fantasy_sleepers_state_key(key: str) -> bool:
    k = str(key or "")
    if k in SLEEPERS_FILTER_KEYS or k in SLEEPERS_ENTITY_KEYS:
        return True
    return k.startswith(("fantasy_market_", "sleeper_", "fantasy_pts_"))


def is_fantasy_standings_state_key(key: str) -> bool:
    k = str(key or "")
    return k in STANDINGS_FILTER_KEYS or k.startswith("standings_")


def _is_ephemeral_lineup_widget_key(key: str) -> bool:
    try:
        from page_state import _is_ephemeral_widget_key

        return _is_ephemeral_widget_key(key)
    except ImportError:
        k = str(key or "")
        return "_remove_trade_" in k or "_remove_acquire_" in k


def is_fantasy_lineup_state_key(key: str) -> bool:
    k = str(key or "")
    if _is_ephemeral_lineup_widget_key(k):
        return False
    if k in LINEUP_FILTER_KEYS:
        return True
    return k.startswith("lineup_") and not k.startswith("lineup_context_")


def is_fantasy_state_key(key: str) -> bool:
    return (
        is_fantasy_sleepers_state_key(key)
        or is_fantasy_standings_state_key(key)
        or is_fantasy_lineup_state_key(key)
    )


def _is_key_in_section(key: str, section: str) -> bool:
    if section == "sleepers":
        return is_fantasy_sleepers_state_key(key)
    if section == "standings":
        return is_fantasy_standings_state_key(key)
    if section == "lineup":
        return is_fantasy_lineup_state_key(key)
    return False


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key in (
        "fantasy_market_window",
        "fantasy_market_min_g",
        "fantasy_market_min_ab",
        "fantasy_market_top_n",
        "sleeper_max_market_rank",
        "sleeper_max_model_rank",
        "sleeper_min_proj_hr",
        "standings_api_season",
        "lineup_bench_rows",
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key == "sleeper_min_expected_value":
        try:
            from draft_score_display import coerce_sleeper_min_player_grade

            return coerce_sleeper_min_player_grade(value)
        except ImportError:
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
    if key in (
        "fantasy_pts_r",
        "fantasy_pts_rbi",
        "fantasy_pts_hr",
        "fantasy_pts_sb",
        "fantasy_pts_bb",
        "fantasy_pts_h",
        "fantasy_pts_xbh",
        "fantasy_pts_ab_penalty",
        "lineup_pts_r",
        "lineup_pts_rbi",
        "lineup_pts_hr",
        "lineup_pts_sb",
        "lineup_pts_h",
        "lineup_pts_bb",
        "lineup_pts_ops",
    ):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if key in ("sleeper_use_draft_room_needs", "lineup_include_util"):
        return bool(value)
    if key in ("fantasy_market_positions", "sleeper_focus_needed_positions", "lineup_trade_give_players", "lineup_trade_get_players", "lineup_trade_ideas_forced_give", "lineup_trade_ideas_forced_get"):
        if isinstance(value, list):
            return [copy.deepcopy(x) for x in value]
        return value
    if key == "fantasy_market_age_range":
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return (int(value[0]), int(value[1]))
        return value
    if key == "fantasy_market_selected_player":
        return str(value).strip() if value not in (None, "") else None
    return copy.deepcopy(value)


def is_fantasy_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(FANTASY_DIRTY_KEY))


def mark_fantasy_local_edit(session: dict[str, Any]) -> None:
    session[FANTASY_DIRTY_KEY] = True
    session[FANTASY_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def mark_sleepers_filter_local_edit(session: dict[str, Any]) -> None:
    """Persist sleeper filter widget values to canonical state on user change."""
    mark_fantasy_local_edit(session)
    mark_fantasy_filter_pending_sync(session, "sleepers")
    filt = _extract_section_from_session(session, "sleepers")
    if filt:
        write_canonical_fantasy_section(
            session,
            "sleepers",
            filters=filt,
            reason="filter_widget_change",
            local_edit=True,
            sync_widget_keys=False,
        )


def clear_fantasy_local_edit(session: dict[str, Any]) -> None:
    session.pop(FANTASY_DIRTY_KEY, None)
    session.pop(FANTASY_LOCAL_EDIT_TS_KEY, None)


def _ensure_meta(session: dict[str, Any]) -> dict[str, Any]:
    meta = session.get("fantasy_state")
    if not isinstance(meta, dict):
        meta = {}
        session["fantasy_state"] = meta
    for section in ("sleepers", "standings", "lineup"):
        block = meta.get(section)
        if not isinstance(block, dict):
            meta[section] = {"filters": {}}
        elif not isinstance(block.get("filters"), dict):
            block["filters"] = {}
    return meta


def _section_block(meta: dict[str, Any], section: str) -> dict[str, Any]:
    block = meta.setdefault(section, {"filters": {}})
    if not isinstance(block.get("filters"), dict):
        block["filters"] = {}
    return block


def _extract_section_from_session(session: dict[str, Any], section: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SECTION_KEYS.get(section, ()):
        if key in session:
            out[key] = _normalize_filter_value(key, session[key])
    for key, val in session.items():
        if _is_key_in_section(str(key), section) and key not in out:
            out[str(key)] = _normalize_filter_value(str(key), val)
    return out


def _filters_from_page_block(block: dict[str, Any], section: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inner = block.get("fantasy_state")
    if isinstance(inner, dict):
        sec = inner.get(section)
        if isinstance(sec, dict) and isinstance(sec.get("filters"), dict):
            for key, val in sec["filters"].items():
                if _is_key_in_section(key, section):
                    out[key] = _normalize_filter_value(key, val)
            sp = sec.get("selected_player")
            if section == "sleepers" and sp:
                out["fantasy_market_selected_player"] = _normalize_filter_value("fantasy_market_selected_player", sp)
    for key, val in block.items():
        if key == "fantasy_state":
            continue
        if _is_key_in_section(key, section):
            out[key] = _normalize_filter_value(key, val)
    return out


def _section_filters_from_blob(state: dict[str, Any], section: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    meta = state.get("fantasy_state")
    if isinstance(meta, dict):
        block = meta.get(section)
        if isinstance(block, dict) and isinstance(block.get("filters"), dict):
            out = {
                k: _normalize_filter_value(k, v)
                for k, v in block["filters"].items()
                if _is_key_in_section(k, section)
            }
            if section == "sleepers" and block.get("selected_player"):
                out["fantasy_market_selected_player"] = _normalize_filter_value(
                    "fantasy_market_selected_player", block["selected_player"]
                )
            if out:
                return out
    page = {
        "sleepers": FANTASY_SLEEPERS_PAGE,
        "standings": FANTASY_STANDINGS_PAGE,
        "lineup": FANTASY_LINEUP_PAGE,
    }[section]
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(page)
        if isinstance(block, dict):
            out = _filters_from_page_block(block, section)
            if out:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict):
        env_key = f"fantasy_{section}_filters"
        env = ws.get(env_key)
        if isinstance(env, dict):
            return {
                k: _normalize_filter_value(k, v)
                for k, v in env.items()
                if _is_key_in_section(k, section)
            }
    return {}


def canonical_fantasy_section(session: dict[str, Any], section: str) -> dict[str, Any] | None:
    meta = _ensure_meta(session)
    block = _section_block(meta, section)
    filt = block.get("filters")
    if not isinstance(filt, dict) or not filt:
        return None
    out = {k: _normalize_filter_value(k, v) for k, v in filt.items() if _is_key_in_section(k, section)}
    if section == "sleepers" and block.get("selected_player"):
        out["fantasy_market_selected_player"] = _normalize_filter_value(
            "fantasy_market_selected_player", block["selected_player"]
        )
    return out or None


def gather_fantasy_section(session: dict[str, Any], section: str) -> dict[str, Any]:
    widget = _extract_section_from_session(session, section)
    canonical = canonical_fantasy_section(session, section) or {}
    pending = bool(session.get(_pending_key(section)))
    drift = _section_widget_drift(session, section)
    if is_fantasy_locally_dirty(session) or pending or drift:
        return {**canonical, **widget}
    if widget:
        return {**canonical, **widget}
    if canonical:
        return dict(canonical)
    page = {
        "sleepers": FANTASY_SLEEPERS_PAGE,
        "standings": FANTASY_STANDINGS_PAGE,
        "lineup": FANTASY_LINEUP_PAGE,
    }[section]
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(page)
        if isinstance(block, dict):
            block_filters = _filters_from_page_block(block, section)
            if block_filters:
                return block_filters
    blob = _section_filters_from_blob(session, section)
    if blob:
        return blob
    return {}


def _filter_values_differ(key: str, canonical_val: Any, widget_val: Any) -> bool:
    if canonical_val == widget_val:
        return False
    if key in ("fantasy_market_positions", "sleeper_focus_needed_positions") and isinstance(canonical_val, list) and isinstance(widget_val, list):
        return set(canonical_val) != set(widget_val)
    if key == "fantasy_market_age_range" and isinstance(canonical_val, (list, tuple)) and isinstance(widget_val, (list, tuple)):
        return tuple(canonical_val[:2]) != tuple(widget_val[:2])
    return True


def _section_widget_drift(session: dict[str, Any], section: str) -> bool:
    widget = _extract_section_from_session(session, section)
    canonical = canonical_fantasy_section(session, section) or {}
    if not widget:
        return False
    for key, val in widget.items():
        if _filter_values_differ(key, canonical.get(key), val):
            return True
    return False


def _split_section_flat(flat: dict[str, Any], section: str) -> tuple[dict[str, Any], str | None]:
    filters: dict[str, Any] = {}
    selected: str | None = None
    for key, val in flat.items():
        if section == "sleepers" and key == "fantasy_market_selected_player":
            selected = _normalize_filter_value(key, val)
        elif _is_key_in_section(key, section):
            filters[key] = _normalize_filter_value(key, val)
    return filters, selected


def _sync_page_filter_block(session: dict[str, Any], section: str, *, filters: dict[str, Any] | None = None, selected: str | None = None) -> None:
    page = {
        "sleepers": FANTASY_SLEEPERS_PAGE,
        "standings": FANTASY_STANDINGS_PAGE,
        "lineup": FANTASY_LINEUP_PAGE,
    }[section]
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(page, {})
    if not isinstance(block, dict):
        block = {}
        pf[page] = block
    meta = _ensure_meta(session)
    block["fantasy_state"] = copy.deepcopy(meta)
    filt = filters
    if filt is None:
        sec = meta.get(section) or {}
        if isinstance(sec, dict):
            filt = sec.get("filters")
    if isinstance(filt, dict):
        for key, val in filt.items():
            if _is_key_in_section(key, section):
                block[key] = _normalize_filter_value(key, val)
    if section == "sleepers" and selected is not None:
        block["fantasy_market_selected_player"] = selected


def write_canonical_fantasy_section(
    session: dict[str, Any],
    section: str,
    *,
    filters: dict[str, Any] | None = None,
    selected_player: str | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    raw = dict(filters) if isinstance(filters, dict) else _extract_section_from_session(session, section)
    filt, auto_selected = _split_section_flat(raw, section)
    filt = _strip_draft_shared_from_filters(filt)
    sp = selected_player if selected_player is not None else auto_selected
    meta = _ensure_meta(session)
    block = _section_block(meta, section)
    block["filters"] = copy.deepcopy(filt)
    if section == "sleepers":
        block["selected_player"] = sp
    meta["last_write_reason"] = reason or None
    session["fantasy_state"] = meta
    if sync_widget_keys:
        shared = _draft_shared_filter_keys()
        for key, val in filt.items():
            if key in shared:
                continue
            session[key] = _normalize_filter_value(key, val)
        if section == "sleepers" and sp is not None:
            session["fantasy_market_selected_player"] = sp
    _sync_page_filter_block(session, section, filters=filt, selected=sp)
    session[f"_suite_last_cloud_payload_fantasy_{section}_filters"] = copy.deepcopy({**filt, **({"fantasy_market_selected_player": sp} if section == "sleepers" and sp else {})})
    if local_edit:
        mark_fantasy_local_edit(session)
    return block


def _section_has_widget_keys(session: dict[str, Any], section: str) -> bool:
    return any(k in session for k in SECTION_KEYS.get(section, ()))


def prepare_fantasy_section_page(session: dict[str, Any], section: str) -> dict[str, Any]:
    widget = _extract_section_from_session(session, section)
    canonical = canonical_fantasy_section(session, section) or {}
    drift = _section_widget_drift(session, section) or bool(session.get(_pending_key(section)))
    has_widgets = _section_has_widget_keys(session, section)
    if is_fantasy_locally_dirty(session) or drift:
        filt = {**canonical, **widget}
        return write_canonical_fantasy_section(
            session,
            section,
            filters=filt,
            reason="local_edit_preserve" if is_fantasy_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
    if widget and canonical:
        return _section_block(_ensure_meta(session), section)
    if canonical and not has_widgets:
        filt = {**canonical, **widget}
        return write_canonical_fantasy_section(
            session,
            section,
            filters=filt,
            reason="canonical_preserve",
            sync_widget_keys=False,
        )
    if canonical and has_widgets:
        filt = {**canonical, **widget}
        return write_canonical_fantasy_section(
            session,
            section,
            filters=filt,
            reason="widget_keys_present",
            sync_widget_keys=False,
        )
    filt = gather_fantasy_section(session, section)
    return write_canonical_fantasy_section(
        session,
        section,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_fantasy_section_filters(session: dict[str, Any], section: str) -> None:
    if is_fantasy_locally_dirty(session) or _section_widget_drift(session, section):
        return
    meta = _ensure_meta(session)
    block = _section_block(meta, section)
    filters: dict[str, Any] = dict(block.get("filters") or {})
    if section == "sleepers" and block.get("selected_player"):
        filters["fantasy_market_selected_player"] = block["selected_player"]
    page = {
        "sleepers": FANTASY_SLEEPERS_PAGE,
        "standings": FANTASY_STANDINGS_PAGE,
        "lineup": FANTASY_LINEUP_PAGE,
    }[section]
    pf = session.get("page_filter_state")
    page_block = pf.get(page) if isinstance(pf, dict) else None
    if not isinstance(page_block, dict):
        page_block = {}
    merged = {**_filters_from_page_block(page_block, section), **{k: v for k, v in filters.items() if _is_key_in_section(k, section)}}
    merged = _strip_draft_shared_from_filters(merged)
    for key in SECTION_KEYS.get(section, ()):
        if key in _draft_shared_filter_keys():
            continue
        if key in session:
            continue
        if _is_ephemeral_lineup_widget_key(key):
            continue
        if key in merged:
            session[key] = _normalize_filter_value(key, merged[key])
    try:
        from shared_draft_context import apply_draft_shared_settings_to_widgets

        page = {
            "sleepers": FANTASY_SLEEPERS_PAGE,
            "standings": FANTASY_STANDINGS_PAGE,
            "lineup": FANTASY_LINEUP_PAGE,
        }.get(section, "")
        apply_draft_shared_settings_to_widgets(session, active_page=page)
    except ImportError:
        pass


def prepare_fantasy_sleepers_page(session: dict[str, Any]) -> dict[str, Any]:
    return prepare_fantasy_section_page(session, "sleepers")


def prepare_fantasy_sleepers_filters(session: dict[str, Any]) -> None:
    prepare_fantasy_section_filters(session, "sleepers")


def read_sleepers_canonical_filters(session: dict[str, Any]) -> dict[str, Any]:
    from sleepers_filter_defaults import read_sleepers_canonical_filters as _read

    return _read(session)


def default_sleepers_age_range(session: dict[str, Any], *, age_hi: int) -> tuple[int, int]:
    from sleepers_filter_defaults import default_sleepers_age_range as _default

    return _default(session, age_hi=age_hi)


def resolve_sleepers_position_age_defaults(session: dict[str, Any], *, age_hi: int = 45) -> dict[str, Any]:
    from sleepers_filter_defaults import resolve_sleepers_position_age_defaults as _resolve

    return _resolve(session, age_hi=age_hi)


def prepare_fantasy_standings_page(session: dict[str, Any]) -> dict[str, Any]:
    return prepare_fantasy_section_page(session, "standings")


def prepare_fantasy_standings_filters(session: dict[str, Any]) -> None:
    prepare_fantasy_section_filters(session, "standings")


def prepare_fantasy_lineup_page(session: dict[str, Any]) -> dict[str, Any]:
    block = prepare_fantasy_section_page(session, "lineup")
    try:
        from global_fantasy_settings_state import sync_lineup_format_from_canonical

        sync_lineup_format_from_canonical(session, force=True)
    except ImportError:
        pass
    return block


def prepare_fantasy_lineup_filters(session: dict[str, Any]) -> None:
    prepare_fantasy_section_filters(session, "lineup")
    try:
        from global_fantasy_settings_state import sync_lineup_format_from_canonical

        sync_lineup_format_from_canonical(session, force=True)
    except ImportError:
        pass


def mark_fantasy_filter_pending_sync(session: dict[str, Any], section: str) -> None:
    session[_pending_key(section)] = True


def flush_fantasy_section_edits(
    session: dict[str, Any],
    section: str,
    st_obj: Any = None,
    *,
    reason: str = "filter_change",
) -> bool:
    pending = bool(session.pop(_pending_key(section), False))
    current = _extract_section_from_session(session, section)
    prev = canonical_fantasy_section(session, section) or {}
    if not current and not pending:
        return False
    if not pending and current == prev:
        return False
    write_canonical_fantasy_section(
        session,
        section,
        filters={**prev, **current},
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="fantasy_edit")
        except Exception:
            pass
    return True


def restore_fantasy_page_filters(session: dict[str, Any], store: dict[str, Any], page_name: str) -> bool:
    section = section_for_page(page_name)
    if not section:
        return False
    if is_fantasy_locally_dirty(session):
        return False
    snapshot = store.get(page_name) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    for key, value in snapshot.items():
        if key == "fantasy_state":
            continue
        if not _is_key_in_section(key, section):
            continue
        try:
            from shared_draft_context import is_draft_shared_session_key

            if is_draft_shared_session_key(key):
                continue
        except ImportError:
            if key in _draft_shared_filter_keys():
                continue
        session[key] = _normalize_filter_value(key, value)
    flat = _filters_from_page_block(snapshot, section)
    if flat:
        filt, sp = _split_section_flat(flat, section)
        write_canonical_fantasy_section(
            session,
            section,
            filters=filt,
            selected_player=sp,
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    try:
        from shared_draft_context import apply_draft_shared_settings_to_widgets

        apply_draft_shared_settings_to_widgets(session, active_page=page_name)
    except ImportError:
        pass
    return True


def apply_cloud_fantasy_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_fantasy_locally_dirty(session):
        return False
    applied = False
    for section in ("sleepers", "standings", "lineup"):
        filters = _section_filters_from_blob(state, section)
        if not filters:
            continue
        filt, sp = _split_section_flat(filters, section)
        write_canonical_fantasy_section(
            session,
            section,
            filters=filt,
            selected_player=sp,
            reason="cloud_restore",
            local_edit=False,
            sync_widget_keys=not _section_has_widget_keys(session, section),
        )
        applied = True
    if applied:
        clear_fantasy_local_edit(session)
        session["_fantasy_restored_filters"] = {
            s: _section_filters_from_blob(state, s) for s in ("sleepers", "standings", "lineup")
        }
        session["_fantasy_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    try:
        from shared_draft_context import (
            apply_draft_shared_settings_to_widgets,
            hydrate_canonical_draft_settings_from_session,
            record_cloud_draft_settings_snapshot,
        )

        record_cloud_draft_settings_snapshot(session, state)
        hydrate_canonical_draft_settings_from_session(session)
        apply_draft_shared_settings_to_widgets(session)
    except ImportError:
        pass
    return applied


def apply_fantasy_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    page = str(source_state.get("source_page") or "").strip()
    section = section_for_page(page)
    if not section:
        return
    wp = dict(source_state.get("widget_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    merged = {**wp, **filt, **ent}
    filters = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if _is_key_in_section(k, section)
    }
    flat, sp = _split_section_flat(filters, section)
    write_canonical_fantasy_section(
        session,
        section,
        filters=flat,
        selected_player=sp,
        reason="ami_return",
        local_edit=False,
    )
    try:
        from shared_draft_context import apply_draft_shared_settings_to_widgets, write_canonical_draft_settings

        kwargs: dict[str, Any] = {"source_page": page, "reason": "ami_return"}
        if "fantasy_market_window" in filters:
            kwargs["lookback_window"] = int(filters["fantasy_market_window"])
        if "fantasy_market_format" in filters:
            kwargs["fantasy_format"] = str(filters["fantasy_market_format"])
        if "standings_scoring_format" in filters:
            kwargs["fantasy_format"] = str(filters["standings_scoring_format"])
        if len(kwargs) > 2:
            write_canonical_draft_settings(session, **kwargs)
            apply_draft_shared_settings_to_widgets(session, active_page=page)
    except ImportError:
        pass
    clear_fantasy_local_edit(session)


def _flat_from_meta_for_envelope(session: dict[str, Any], section: str) -> dict[str, Any] | None:
    meta = session.get("fantasy_state")
    if not isinstance(meta, dict):
        return None
    block = meta.get(section)
    if not isinstance(block, dict):
        return None
    out = dict(block.get("filters") or {})
    if section == "sleepers" and block.get("selected_player"):
        out["fantasy_market_selected_player"] = block["selected_player"]
    return out or None


def render_fantasy_state_debug(st: Any, session: dict[str, Any], active_page: str) -> None:
    section = section_for_page(active_page)
    if not section:
        return
    meta = session.get("fantasy_state")
    if not isinstance(meta, dict):
        meta = {}
    block = meta.get(section) if isinstance(meta.get(section), dict) else {}
    canonical = block.get("filters") if isinstance(block.get("filters"), dict) else {}
    cloud_payload = session.get(f"_suite_last_cloud_payload_fantasy_{section}_filters")
    rows = {
        "fantasy_state_dirty": session.get(FANTASY_DIRTY_KEY),
        "section": section,
        "last_write_reason": meta.get("last_write_reason"),
        "pending_sync": session.get(_pending_key(section)),
        "restored_filters": (session.get("_fantasy_restored_filters") or {}).get(section),
        "canonical filters": canonical,
        "cloud_payload": cloud_payload,
    }
    with st.sidebar.expander(f"Fantasy state ({section})", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")
