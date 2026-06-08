"""Canonical Leaderboards page state — year range, weights, stat minimums."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

try:
    from page_transfers import _TRANSFER_STAT_COLS as LEADERBOARDS_STAT_COLUMNS
except ImportError:
    LEADERBOARDS_STAT_COLUMNS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]

LEADERBOARDS_PAGE = "Leaderboards"

LEADERBOARDS_DIRTY_KEY = "leaderboards_state_dirty"
LEADERBOARDS_LOCAL_EDIT_TS_KEY = "leaderboards_state_last_local_edit_ts"
LEADERBOARDS_PENDING_SYNC_KEY = "_leaderboards_filters_pending_sync"

LEADERBOARDS_FILTER_KEYS = (
    "leaders_year_range_filter",
    "leaders_top_n_filter",
    "leaders_sort_stat_filter",
)

LEADERBOARDS_STAT_MIN_KEYS = tuple(f"leaders_{col}_min" for col in LEADERBOARDS_STAT_COLUMNS)
LEADERBOARDS_WEIGHT_KEYS = tuple(f"leaders_w_{col}" for col in LEADERBOARDS_STAT_COLUMNS)
LEADERBOARDS_ALL_STATE_KEYS = LEADERBOARDS_FILTER_KEYS + LEADERBOARDS_STAT_MIN_KEYS + LEADERBOARDS_WEIGHT_KEYS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_leaderboards_state_key(key: str) -> bool:
    k = str(key or "")
    if k in LEADERBOARDS_ALL_STATE_KEYS:
        return True
    if k.startswith("leaders_w_"):
        return True
    return k.startswith("leaders_") and k.endswith("_min")


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key == "leaders_year_range_filter":
        from historical_state import normalize_historical_year_range

        return normalize_historical_year_range(value)
    if key in ("leaders_top_n_filter",):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key.startswith("leaders_w_") or key.endswith("_min"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return copy.deepcopy(value)


def is_leaderboards_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(LEADERBOARDS_DIRTY_KEY))


def mark_leaderboards_local_edit(session: dict[str, Any]) -> None:
    session[LEADERBOARDS_DIRTY_KEY] = True
    session[LEADERBOARDS_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_leaderboards_local_edit(session: dict[str, Any]) -> None:
    session.pop(LEADERBOARDS_DIRTY_KEY, None)
    session.pop(LEADERBOARDS_LOCAL_EDIT_TS_KEY, None)


def _extract_filters_from_session(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in LEADERBOARDS_ALL_STATE_KEYS:
        if key in session:
            out[key] = _normalize_filter_value(key, session[key])
    for key, val in session.items():
        if is_leaderboards_state_key(str(key)) and key not in out:
            out[str(key)] = _normalize_filter_value(str(key), val)
    return out


def _filters_from_block(block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inner = block.get("leaderboards_state")
    if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
        for key, val in inner["filters"].items():
            if is_leaderboards_state_key(key):
                out[key] = _normalize_filter_value(key, val)
    for key, val in block.items():
        if key == "leaderboards_state":
            continue
        if is_leaderboards_state_key(key):
            out[key] = _normalize_filter_value(key, val)
    return out


def _leaderboards_filters_from_blob(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    ls = state.get("leaderboards_state")
    if isinstance(ls, dict) and isinstance(ls.get("filters"), dict):
        out = {k: _normalize_filter_value(k, v) for k, v in ls["filters"].items() if is_leaderboards_state_key(k)}
        if out:
            return out
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LEADERBOARDS_PAGE)
        if isinstance(block, dict):
            out = _filters_from_block(block)
            if out:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict) and isinstance(ws.get("leaderboards_filters"), dict):
        return {
            k: _normalize_filter_value(k, v)
            for k, v in ws["leaderboards_filters"].items()
            if is_leaderboards_state_key(k)
        }
    return {}


def canonical_leaderboards_filters(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("leaderboards_state")
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        out = {k: _normalize_filter_value(k, v) for k, v in meta["filters"].items() if is_leaderboards_state_key(k)}
        return out or None
    return None


def _sync_page_filter_leaderboards_block(session: dict[str, Any], *, filters: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(LEADERBOARDS_PAGE, {})
    if not isinstance(block, dict):
        block = {}
        pf[LEADERBOARDS_PAGE] = block
    meta = session.get("leaderboards_state")
    if isinstance(meta, dict):
        block["leaderboards_state"] = {
            "filters": copy.deepcopy(meta.get("filters") or {}),
            "last_write_reason": meta.get("last_write_reason"),
        }
    filt = filters
    if filt is None and isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filt = meta["filters"]
    if isinstance(filt, dict):
        for key, val in filt.items():
            if is_leaderboards_state_key(key):
                block[key] = _normalize_filter_value(key, val)


def write_canonical_leaderboards_state(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    raw = dict(filters) if isinstance(filters, dict) else _extract_filters_from_session(session)
    filt = {k: _normalize_filter_value(k, v) for k, v in raw.items() if is_leaderboards_state_key(k)}
    meta = session.get("leaderboards_state")
    if not isinstance(meta, dict):
        meta = {}
    meta["filters"] = copy.deepcopy(filt)
    meta["last_write_reason"] = reason or None
    session["leaderboards_state"] = meta
    if sync_widget_keys:
        for key, val in filt.items():
            session[key] = _normalize_filter_value(key, val)
    _sync_page_filter_leaderboards_block(session, filters=filt)
    session["_suite_last_cloud_payload_leaderboards_filters"] = copy.deepcopy(filt)
    if local_edit:
        mark_leaderboards_local_edit(session)
    return meta


def _leaderboards_widget_drift(session: dict[str, Any]) -> bool:
    widget = _extract_filters_from_session(session)
    canonical = canonical_leaderboards_filters(session) or {}
    if not widget:
        return False
    for key, val in widget.items():
        if canonical.get(key) != val:
            return True
    return False


def gather_leaderboards_filters(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_filters_from_session(session)
    canonical = canonical_leaderboards_filters(session) or {}
    if is_leaderboards_locally_dirty(session) or session.get(LEADERBOARDS_PENDING_SYNC_KEY) or _leaderboards_widget_drift(session):
        return {**canonical, **widget}
    if widget:
        return {**canonical, **widget}
    if canonical:
        return dict(canonical)
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LEADERBOARDS_PAGE)
        if isinstance(block, dict):
            block_filters = _filters_from_block(block)
            if block_filters:
                return block_filters
    blob = _leaderboards_filters_from_blob(session)
    if blob:
        return blob
    return {}


def prepare_leaderboards_page(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_filters_from_session(session)
    canonical = canonical_leaderboards_filters(session) or {}
    drift = _leaderboards_widget_drift(session) or bool(session.get(LEADERBOARDS_PENDING_SYNC_KEY))
    if is_leaderboards_locally_dirty(session) or drift:
        filt = {**canonical, **widget}
        return write_canonical_leaderboards_state(
            session,
            filters=filt,
            reason="local_edit_preserve" if is_leaderboards_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
    if canonical:
        filt = {**canonical, **widget}
        return write_canonical_leaderboards_state(
            session,
            filters=filt,
            reason="canonical_preserve",
            sync_widget_keys=not bool(widget),
        )
    filt = gather_leaderboards_filters(session)
    return write_canonical_leaderboards_state(
        session,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_leaderboards_filters(session: dict[str, Any]) -> None:
    if is_leaderboards_locally_dirty(session):
        return
    meta = session.get("leaderboards_state")
    filters: dict[str, Any] = {}
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filters = meta["filters"]
    pf = session.get("page_filter_state")
    block = pf.get(LEADERBOARDS_PAGE) if isinstance(pf, dict) else None
    if not isinstance(block, dict):
        block = {}
    merged = {**_filters_from_block(block), **{k: v for k, v in filters.items() if is_leaderboards_state_key(k)}}
    for key in LEADERBOARDS_ALL_STATE_KEYS:
        if key in session:
            continue
        if key in merged:
            session[key] = _normalize_filter_value(key, merged[key])


def prepare_leaderboards_year_range(
    session: dict[str, Any],
    min_year: int,
    max_year: int,
    default: tuple[int, int],
) -> tuple[int, int]:
    from year_range_state import sanitize_year_range

    key = "leaders_year_range_filter"
    canonical = (canonical_leaderboards_filters(session) or {}).get(key)
    raw = session.get(key) if key in session else None
    if raw is None and canonical is not None:
        raw = canonical
    preserve_default = default
    if is_leaderboards_locally_dirty(session) or session.get(LEADERBOARDS_PENDING_SYNC_KEY) or _leaderboards_widget_drift(session):
        if raw is not None:
            from historical_state import normalize_historical_year_range

            preserve_default = normalize_historical_year_range(raw) or default
    sanitized = sanitize_year_range(raw, int(min_year), int(max_year), preserve_default)
    if sanitized is None:
        sanitized = (int(min_year), int(max_year))
    session[key] = (int(sanitized[0]), int(sanitized[1]))
    return session[key]


def mark_leaderboards_filter_pending_sync(session: dict[str, Any]) -> None:
    session[LEADERBOARDS_PENDING_SYNC_KEY] = True


def flush_leaderboards_filter_edits(session: dict[str, Any], st_obj: Any = None, *, reason: str = "filter_change") -> bool:
    pending = bool(session.pop(LEADERBOARDS_PENDING_SYNC_KEY, False))
    current = _extract_filters_from_session(session)
    prev = canonical_leaderboards_filters(session) or {}
    if not current and not pending:
        return False
    if not pending and current == prev:
        return False
    write_canonical_leaderboards_state(
        session,
        filters={**prev, **current},
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="leaderboards_edit")
        except Exception:
            pass
    return True


def restore_leaderboards_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_leaderboards_locally_dirty(session):
        return False
    snapshot = store.get(LEADERBOARDS_PAGE) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    for key, value in snapshot.items():
        if key == "leaderboards_state":
            continue
        if not is_leaderboards_state_key(key):
            continue
        session[key] = _normalize_filter_value(key, value)
    flat = _filters_from_block(snapshot)
    if flat:
        write_canonical_leaderboards_state(
            session,
            filters=flat,
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    return True


def apply_cloud_leaderboards_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_leaderboards_locally_dirty(session):
        return False
    filters = _leaderboards_filters_from_blob(state)
    if not filters:
        return False
    write_canonical_leaderboards_state(session, filters=filters, reason="cloud_restore", local_edit=False)
    clear_leaderboards_local_edit(session)
    session["_leaderboards_restored_filters"] = copy.deepcopy(filters)
    session["_leaderboards_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    return True


def apply_leaderboards_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    wp = dict(source_state.get("widget_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    merged = {**wp, **filt}
    filters = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if is_leaderboards_state_key(k)
    }
    write_canonical_leaderboards_state(session, filters=filters, reason="ami_return", local_edit=False)
    clear_leaderboards_local_edit(session)


def render_leaderboards_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("leaderboards_state")
    if not isinstance(meta, dict):
        meta = {}
    canonical = meta.get("filters") if isinstance(meta.get("filters"), dict) else {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get(LEADERBOARDS_PAGE)
        if isinstance(block, dict):
            pf_block = block
    cloud_payload = session.get("_suite_last_cloud_payload_leaderboards_filters")
    rows = {
        "leaderboards_state_dirty": session.get(LEADERBOARDS_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "raw leaders_year_range": session.get("leaders_year_range_filter"),
        "canonical leaders_year_range": canonical.get("leaders_year_range_filter"),
        "cloud_payload leaders_year_range": (cloud_payload or {}).get("leaders_year_range_filter")
        if isinstance(cloud_payload, dict)
        else None,
        "pending_sync": session.get(LEADERBOARDS_PENDING_SYNC_KEY),
        "restored_filters": session.get("_leaderboards_restored_filters"),
        "canonical filters": canonical,
    }
    with st.sidebar.expander("Leaderboards state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")
