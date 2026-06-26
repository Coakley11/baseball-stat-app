"""Canonical Historical Explorer page state — filters and stat minimums."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

try:
    from page_transfers import _TRANSFER_STAT_COLS as HISTORICAL_STAT_COLUMNS
except ImportError:
    HISTORICAL_STAT_COLUMNS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]

HISTORICAL_PAGE = "Historical Explorer"

HISTORICAL_DIRTY_KEY = "historical_state_dirty"
HISTORICAL_LOCAL_EDIT_TS_KEY = "historical_state_last_local_edit_ts"
HISTORICAL_PENDING_SYNC_KEY = "_historical_filters_pending_sync"

HISTORICAL_FILTER_KEYS = (
    "historical_year_range_filter",
    "historical_sort_stat_filter",
    "historical_sort_order_filter",
    "historical_batting_hand_filter",
    "historical_position_filter_mode",
    "historical_position_filter",
    "historical_team_filter",
    "historical_combine_split_seasons_filter",
)

HISTORICAL_STAT_MIN_KEYS = tuple(f"hist_{col}_min" for col in HISTORICAL_STAT_COLUMNS)
HISTORICAL_ALL_STATE_KEYS = HISTORICAL_FILTER_KEYS + HISTORICAL_STAT_MIN_KEYS
HISTORICAL_TEAM_PSEUDO_OPTIONS = frozenset({"All Teams", "American League", "National League"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_historical_state_key(key: str) -> bool:
    k = str(key or "")
    return k in HISTORICAL_ALL_STATE_KEYS or (k.startswith("hist_") and k.endswith("_min"))


def normalize_historical_year_range(
    value: Any,
    *,
    min_year: int | None = None,
    max_year: int | None = None,
    default: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    from year_range_state import sanitize_year_range

    if value is None:
        return None
    if min_year is not None and max_year is not None:
        if default is None:
            default = (int(min_year), int(max_year))
        return sanitize_year_range(value, int(min_year), int(max_year), default)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return (int(value[0]), int(value[1]))
        except (TypeError, ValueError):
            return None
    return None


def _normalize_team_filter(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(x).strip() for x in value if str(x).strip()]


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key == "historical_year_range_filter":
        return normalize_historical_year_range(value)
    if key == "historical_team_filter":
        return _normalize_team_filter(value)
    if key in ("historical_batting_hand_filter", "historical_position_filter"):
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value).strip()] if str(value).strip() else []
        return [str(x).strip() for x in value if str(x).strip()]
    if key == "historical_combine_split_seasons_filter":
        return bool(value)
    return copy.deepcopy(value)


def _migrate_legacy_historical_keys(session: dict[str, Any]) -> None:
    legacy_map = {
        "hist_year": "historical_year_range_filter",
        "hist_sort_stat": "historical_sort_stat_filter",
        "hist_sort_order": "historical_sort_order_filter",
        "hist_bats": "historical_batting_hand_filter",
        "hist_position_filter_mode": "historical_position_filter_mode",
        "hist_pos": "historical_position_filter",
        "hist_team": "historical_team_filter",
        "hist_combine_split_seasons": "historical_combine_split_seasons_filter",
    }
    for old, new in legacy_map.items():
        if new not in session and session.get(old) is not None:
            session[new] = _normalize_filter_value(new, session.get(old))


def is_historical_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(HISTORICAL_DIRTY_KEY))


def mark_historical_local_edit(session: dict[str, Any]) -> None:
    session[HISTORICAL_DIRTY_KEY] = True
    session[HISTORICAL_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_historical_local_edit(session: dict[str, Any]) -> None:
    session.pop(HISTORICAL_DIRTY_KEY, None)
    session.pop(HISTORICAL_LOCAL_EDIT_TS_KEY, None)


def _extract_filters_from_session(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in HISTORICAL_ALL_STATE_KEYS:
        if key in session:
            out[key] = _normalize_filter_value(key, session[key])
    for key, val in session.items():
        if is_historical_state_key(str(key)) and key not in out:
            out[str(key)] = _normalize_filter_value(str(key), val)
    return out


def _filters_from_block(block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inner = block.get("historical_state")
    if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
        for key, val in inner["filters"].items():
            if is_historical_state_key(key):
                out[key] = _normalize_filter_value(key, val)
    for key, val in block.items():
        if key == "historical_state":
            continue
        if is_historical_state_key(key):
            out[key] = _normalize_filter_value(key, val)
    return out


def _historical_filters_from_blob(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    hs = state.get("historical_state")
    if isinstance(hs, dict) and isinstance(hs.get("filters"), dict):
        out = {k: _normalize_filter_value(k, v) for k, v in hs["filters"].items() if is_historical_state_key(k)}
        if out:
            return out
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(HISTORICAL_PAGE)
        if isinstance(block, dict):
            out = _filters_from_block(block)
            if out:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict) and isinstance(ws.get("historical_filters"), dict):
        return {
            k: _normalize_filter_value(k, v)
            for k, v in ws["historical_filters"].items()
            if is_historical_state_key(k)
        }
    return {}


def canonical_historical_filters(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("historical_state")
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        return {k: _normalize_filter_value(k, v) for k, v in meta["filters"].items() if is_historical_state_key(k)}
    return None


def record_historical_field_write(
    session: dict[str, Any],
    field: str,
    source: str,
    old: Any = None,
    new: Any = None,
) -> None:
    session[f"_historical_last_write_{field}"] = source
    if old is not None:
        session[f"_historical_prev_{field}"] = old
    if new is not None:
        session[f"_historical_new_{field}"] = new


def _sync_page_filter_historical_block(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(HISTORICAL_PAGE, {})
    if not isinstance(block, dict):
        block = {}
        pf[HISTORICAL_PAGE] = block
    meta = session.get("historical_state")
    if isinstance(meta, dict):
        block["historical_state"] = {
            "filters": copy.deepcopy(meta.get("filters") or {}),
            "last_write_reason": meta.get("last_write_reason"),
        }
    filt = filters
    if filt is None and isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filt = meta["filters"]
    if isinstance(filt, dict):
        for key, val in filt.items():
            if is_historical_state_key(key):
                block[key] = _normalize_filter_value(key, val)


def write_canonical_historical_state(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    raw = dict(filters) if isinstance(filters, dict) else _extract_filters_from_session(session)
    filt = {k: _normalize_filter_value(k, v) for k, v in raw.items() if is_historical_state_key(k)}
    meta = session.get("historical_state")
    if not isinstance(meta, dict):
        meta = {}
    meta["filters"] = copy.deepcopy(filt)
    meta["last_write_reason"] = reason or None
    session["historical_state"] = meta
    if sync_widget_keys:
        for key, val in filt.items():
            session[key] = _normalize_filter_value(key, val)
            record_historical_field_write(session, key, reason or "canonical", new=val)
    else:
        for key, val in filt.items():
            record_historical_field_write(session, key, reason or "canonical_meta", new=val)
    _sync_page_filter_historical_block(session, filters=filt)
    session["_suite_last_cloud_payload_historical_filters"] = copy.deepcopy(filt)
    if local_edit:
        mark_historical_local_edit(session)
    return meta


def _historical_widget_drift(session: dict[str, Any]) -> bool:
    widget = _extract_filters_from_session(session)
    canonical = canonical_historical_filters(session) or {}
    if not widget:
        return False
    for key, val in widget.items():
        if canonical.get(key) != val:
            return True
    return False


def gather_historical_filters(session: dict[str, Any]) -> dict[str, Any]:
    _migrate_legacy_historical_keys(session)
    widget = _extract_filters_from_session(session)
    canonical = canonical_historical_filters(session) or {}
    if is_historical_locally_dirty(session) or session.get(HISTORICAL_PENDING_SYNC_KEY) or _historical_widget_drift(session):
        return {**canonical, **widget}
    if widget:
        return {**canonical, **widget}
    if canonical:
        return dict(canonical)
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(HISTORICAL_PAGE)
        if isinstance(block, dict):
            block_filters = _filters_from_block(block)
            if block_filters:
                return block_filters
    blob = _historical_filters_from_blob(session)
    if blob:
        return blob
    return {}


def prepare_historical_explorer_page(session: dict[str, Any]) -> dict[str, Any]:
    _migrate_legacy_historical_keys(session)
    widget = _extract_filters_from_session(session)
    canonical = canonical_historical_filters(session) or {}
    drift = _historical_widget_drift(session) or bool(session.get(HISTORICAL_PENDING_SYNC_KEY))
    if is_historical_locally_dirty(session) or drift:
        filt = {**canonical, **widget}
        return write_canonical_historical_state(
            session,
            filters=filt,
            reason="local_edit_preserve" if is_historical_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
    if canonical:
        filt = {**canonical, **widget}
        return write_canonical_historical_state(
            session,
            filters=filt,
            reason="canonical_preserve",
            sync_widget_keys=not bool(widget),
        )
    filt = gather_historical_filters(session)
    return write_canonical_historical_state(
        session,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_historical_explorer_filters(session: dict[str, Any]) -> None:
    try:
        from hall_of_fame_data import ensure_hof_case_scope_ui_state

        ensure_hof_case_scope_ui_state(session)
    except ImportError:
        pass
    if is_historical_locally_dirty(session):
        return
    meta = session.get("historical_state")
    filters: dict[str, Any] = {}
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filters = meta["filters"]
    pf = session.get("page_filter_state")
    block = pf.get(HISTORICAL_PAGE) if isinstance(pf, dict) else None
    if not isinstance(block, dict):
        block = {}
    block_filters = _filters_from_block(block)
    merged = {**block_filters, **{k: v for k, v in filters.items() if is_historical_state_key(k)}}
    for key in HISTORICAL_ALL_STATE_KEYS:
        if key in session:
            continue
        if key in merged:
            session[key] = _normalize_filter_value(key, merged[key])
            record_historical_field_write(session, key, "historical_state.filters", new=merged[key])


def prepare_historical_year_range(
    session: dict[str, Any],
    min_year: int,
    max_year: int,
    default: tuple[int, int],
) -> tuple[int, int]:
    from year_range_state import sanitize_year_range

    key = "historical_year_range_filter"
    _migrate_legacy_historical_keys(session)
    canonical = (canonical_historical_filters(session) or {}).get(key)
    raw = session.get(key) if key in session else None
    if raw is None and canonical is not None:
        raw = canonical
    preserve_default = default
    if is_historical_locally_dirty(session) or session.get(HISTORICAL_PENDING_SYNC_KEY) or _historical_widget_drift(session):
        if raw is not None:
            preserve_default = normalize_historical_year_range(raw) or default
    sanitized = sanitize_year_range(raw, int(min_year), int(max_year), preserve_default)
    if sanitized is None:
        sanitized = (int(min_year), int(max_year))
    session[key] = (int(sanitized[0]), int(sanitized[1]))
    return session[key]


def prepare_historical_multiselect_filter(
    session: dict[str, Any],
    key: str,
    options: list[str],
    default: list[str] | None = None,
) -> list[str]:
    opts = [str(x) for x in options]
    default_list = _normalize_filter_value(key, default or [])
    canonical = (canonical_historical_filters(session) or {}).get(key)
    if key not in session:
        if canonical is not None:
            session[key] = _normalize_filter_value(key, canonical)
        else:
            session[key] = list(default_list)
    elif not isinstance(session.get(key), list):
        session[key] = list(default_list)
    current = _normalize_filter_value(key, session.get(key))
    preserve = set(current)
    if isinstance(canonical, list):
        preserve.update(canonical)
    merged_opts = list(dict.fromkeys(opts + list(preserve)))
    if is_historical_locally_dirty(session) or session.get(HISTORICAL_PENDING_SYNC_KEY) or _historical_widget_drift(session):
        session[key] = [x for x in current if x in merged_opts or x in preserve]
        if not session[key] and current:
            session[key] = list(current)
    elif session.get("_transfer_just_applied_to") != session.get("active_page"):
        session[key] = [x for x in current if x in opts]
    else:
        session[key] = [x for x in current if x in merged_opts]
    return merged_opts


def mark_historical_filter_pending_sync(session: dict[str, Any]) -> None:
    session[HISTORICAL_PENDING_SYNC_KEY] = True


def flush_historical_filter_edits(session: dict[str, Any], st_obj: Any = None, *, reason: str = "filter_change") -> bool:
    pending = bool(session.pop(HISTORICAL_PENDING_SYNC_KEY, False))
    current = _extract_filters_from_session(session)
    prev = canonical_historical_filters(session) or {}
    if not current and not pending:
        return False
    changed = current != prev
    if not pending and not changed:
        return False
    write_canonical_historical_state(
        session,
        filters={**prev, **current},
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="historical_edit")
        except Exception:
            pass
    return True


def sync_historical_filter_change(session: dict[str, Any], *, reason: str = "filter_change") -> None:
    mark_historical_filter_pending_sync(session)


def restore_historical_explorer_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_historical_locally_dirty(session):
        record_historical_field_write(session, "page_filter_restore", "blocked_local_dirty")
        return False
    snapshot = store.get(HISTORICAL_PAGE) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    for key, value in snapshot.items():
        if key == "historical_state":
            continue
        if not is_historical_state_key(key):
            continue
        old = session.get(key)
        session[key] = _normalize_filter_value(key, value)
        record_historical_field_write(session, key, "page_filter_state", old, value)
    inner = snapshot.get("historical_state")
    if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
        write_canonical_historical_state(
            session,
            filters=inner["filters"],
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    elif snapshot:
        write_canonical_historical_state(
            session,
            filters=_filters_from_block(snapshot),
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    return True


def apply_cloud_historical_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_historical_locally_dirty(session):
        return False
    filters = _historical_filters_from_blob(state)
    if not filters:
        return False
    write_canonical_historical_state(session, filters=filters, reason="cloud_restore", local_edit=False)
    clear_historical_local_edit(session)
    session["_historical_restored_filters"] = copy.deepcopy(filters)
    session["_historical_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    return True


def apply_historical_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    wp = dict(source_state.get("widget_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    merged = {**wp, **ent, **filt}
    filters = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if is_historical_state_key(k)
    }
    write_canonical_historical_state(session, filters=filters, reason="ami_return", local_edit=False)
    clear_historical_local_edit(session)
    snap = (source_state.get("chart_params") or {}).get("historical_snapshot")
    if isinstance(snap, dict):
        session["_ami_historical_snapshot"] = copy.deepcopy(snap)


def render_historical_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("historical_state")
    if not isinstance(meta, dict):
        meta = {}
    canonical = meta.get("filters") if isinstance(meta.get("filters"), dict) else {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get(HISTORICAL_PAGE)
        if isinstance(block, dict):
            pf_block = block
    cloud_payload = session.get("_suite_last_cloud_payload_historical_filters")
    rows = {
        "historical_state_dirty": session.get(HISTORICAL_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "last_force_save_reason": session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
        "raw historical_year_range widget": session.get("historical_year_range_filter"),
        "canonical historical_year_range": canonical.get("historical_year_range_filter"),
        "page_filter_state historical_year_range": pf_block.get("historical_year_range_filter"),
        "cloud_payload historical_year_range": (cloud_payload or {}).get("historical_year_range_filter")
        if isinstance(cloud_payload, dict)
        else None,
        "raw historical_team_filter widget": session.get("historical_team_filter"),
        "canonical historical_team_filter": canonical.get("historical_team_filter"),
        "page_filter_state historical_team_filter": pf_block.get("historical_team_filter"),
        "cloud_payload historical_team_filter": (cloud_payload or {}).get("historical_team_filter")
        if isinstance(cloud_payload, dict)
        else None,
        "pending_sync": session.get(HISTORICAL_PENDING_SYNC_KEY),
        "restored_filters": session.get("_historical_restored_filters"),
        "restore_source": session.get("_historical_restore_source"),
        "canonical historical_state.filters": canonical,
        "page_filter_state historical keys": _filters_from_block(pf_block),
    }
    with st.sidebar.expander("Historical Explorer state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")
