"""Canonical Career Totals page state — filters, stat minimums, sort, by-team toggle."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

try:
    from page_transfers import _TRANSFER_STAT_COLS as CAREER_STAT_COLUMNS
except ImportError:
    CAREER_STAT_COLUMNS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]

CAREER_DIRTY_KEY = "career_state_dirty"
CAREER_LOCAL_EDIT_TS_KEY = "career_state_last_local_edit_ts"

CAREER_FILTER_KEYS = (
    "career_year_range_filter",
    "career_sort_stat_filter",
    "career_batting_hand_filter",
    "career_position_filter_mode",
    "career_position_filter",
    "career_team_filter",
    "career_by_team_toggle_filter",
)

CAREER_STAT_MIN_KEYS = tuple(f"career_{col}_min" for col in CAREER_STAT_COLUMNS)

CAREER_ALL_STATE_KEYS = CAREER_FILTER_KEYS + CAREER_STAT_MIN_KEYS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_career_state_key(key: str) -> bool:
    k = str(key or "")
    return k in CAREER_ALL_STATE_KEYS or (k.startswith("career_") and k.endswith("_min"))


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key == "career_year_range_filter" and value is not None:
        try:
            lo, hi = value
            return (int(lo), int(hi))
        except (TypeError, ValueError):
            return copy.deepcopy(value)
    return copy.deepcopy(value)


def is_career_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(CAREER_DIRTY_KEY))


def mark_career_local_edit(session: dict[str, Any]) -> None:
    session[CAREER_DIRTY_KEY] = True
    session[CAREER_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_career_local_edit(session: dict[str, Any]) -> None:
    session.pop(CAREER_DIRTY_KEY, None)
    session.pop(CAREER_LOCAL_EDIT_TS_KEY, None)


def _extract_filters_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """Read all Career Totals filter keys from session; zero/False/empty are valid values."""
    out: dict[str, Any] = {}
    for key in CAREER_ALL_STATE_KEYS:
        if key in session:
            out[key] = _normalize_filter_value(key, session[key])
    for key, val in session.items():
        if is_career_state_key(str(key)) and key not in out:
            out[str(key)] = _normalize_filter_value(str(key), val)
    return out


def _filters_from_block(block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inner = block.get("career_state")
    if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
        for key, val in inner["filters"].items():
            if is_career_state_key(key):
                out[key] = _normalize_filter_value(key, val)
    for key, val in block.items():
        if key == "career_state":
            continue
        if is_career_state_key(key):
            out[key] = _normalize_filter_value(key, val)
    return out


def canonical_career_filters(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("career_state")
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        return {k: _normalize_filter_value(k, v) for k, v in meta["filters"].items() if is_career_state_key(k)}
    return None


def record_career_field_write(
    session: dict[str, Any],
    field: str,
    source: str,
    old: Any = None,
    new: Any = None,
) -> None:
    session[f"_career_last_write_{field}"] = source
    if old is not None:
        session[f"_career_prev_{field}"] = old
    if new is not None:
        session[f"_career_new_{field}"] = new


def _sync_page_filter_career_block(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault("Career Totals", {})
    if not isinstance(block, dict):
        block = {}
        pf["Career Totals"] = block
    meta = session.get("career_state")
    if isinstance(meta, dict):
        block["career_state"] = {
            "filters": copy.deepcopy(meta.get("filters") or {}),
            "last_write_reason": meta.get("last_write_reason"),
        }
    filt = filters
    if filt is None and isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filt = meta["filters"]
    if isinstance(filt, dict):
        for key, val in filt.items():
            if is_career_state_key(key):
                block[key] = _normalize_filter_value(key, val)


def write_canonical_career_state(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    """Write canonical career_state; optionally mirror filter widget keys (pre-render only)."""
    raw = dict(filters) if isinstance(filters, dict) else _extract_filters_from_session(session)
    filt = {k: _normalize_filter_value(k, v) for k, v in raw.items() if is_career_state_key(k)}
    meta = session.get("career_state")
    if not isinstance(meta, dict):
        meta = {}
    meta["filters"] = copy.deepcopy(filt)
    meta["last_write_reason"] = reason or None
    session["career_state"] = meta
    if sync_widget_keys:
        for key, val in filt.items():
            session[key] = _normalize_filter_value(key, val)
            record_career_field_write(session, key, reason or "canonical", new=val)
    else:
        for key, val in filt.items():
            record_career_field_write(session, key, reason or "canonical_meta", new=val)
    _sync_page_filter_career_block(session, filters=filt)
    session["_suite_last_cloud_payload_career_filters"] = copy.deepcopy(filt)
    if local_edit:
        mark_career_local_edit(session)
    return meta


def gather_career_filters(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_filters_from_session(session)
    canonical = canonical_career_filters(session) or {}

    if is_career_locally_dirty(session):
        return {**canonical, **widget}

    if canonical:
        return dict(canonical)

    if widget:
        return widget

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Career Totals")
        if isinstance(block, dict):
            block_filters = _filters_from_block(block)
            if block_filters:
                return block_filters
    return {}


def prepare_career_totals_page(session: dict[str, Any]) -> dict[str, Any]:
    """Reconcile Career Totals filters before widgets render."""
    if is_career_locally_dirty(session):
        filt = gather_career_filters(session)
        return write_canonical_career_state(
            session,
            filters=filt,
            reason="local_edit_preserve",
            local_edit=True,
        )

    if canonical_career_filters(session) is not None:
        filt = gather_career_filters(session)
        return write_canonical_career_state(session, filters=filt, reason="canonical_preserve")

    filt = gather_career_filters(session)
    return write_canonical_career_state(
        session,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_career_totals_filters(session: dict[str, Any]) -> None:
    """Seed filter widget keys from canonical career_state when not locally dirty."""
    if is_career_locally_dirty(session):
        return
    meta = session.get("career_state")
    filters: dict[str, Any] = {}
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filters = meta["filters"]
    pf = session.get("page_filter_state")
    block = pf.get("Career Totals") if isinstance(pf, dict) else None
    if not isinstance(block, dict):
        block = {}
    block_filters = _filters_from_block(block)
    merged = {**block_filters, **{k: v for k, v in filters.items() if is_career_state_key(k)}}
    for key in CAREER_ALL_STATE_KEYS:
        if key in session:
            continue
        if key in merged:
            session[key] = _normalize_filter_value(key, merged[key])
            record_career_field_write(session, key, "career_state.filters", new=merged[key])


def restore_career_totals_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_career_locally_dirty(session):
        record_career_field_write(session, "page_filter_restore", "blocked_local_dirty")
        return False
    snapshot = store.get("Career Totals") if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    for key, value in snapshot.items():
        if key == "career_state":
            continue
        if not is_career_state_key(key):
            continue
        old = session.get(key)
        session[key] = _normalize_filter_value(key, value)
        record_career_field_write(session, key, "page_filter_state", old, value)
    inner = snapshot.get("career_state")
    if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
        write_canonical_career_state(
            session,
            filters=inner["filters"],
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    elif snapshot:
        write_canonical_career_state(
            session,
            filters=_filters_from_block(snapshot),
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    return True


def sync_career_filter_change(session: dict[str, Any], *, reason: str = "filter_change") -> None:
    """on_change handler: read widget values, update canonical only (never write widget keys)."""
    current = _extract_filters_from_session(session)
    write_canonical_career_state(
        session,
        filters=current,
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )


def commit_career_filters_from_session(session: dict[str, Any], *, reason: str = "widget_rerun") -> None:
    """Persist widget values into canonical career_state without mutating widget keys."""
    current = _extract_filters_from_session(session)
    prev = canonical_career_filters(session) or {}
    changed = current != prev
    write_canonical_career_state(
        session,
        filters=current,
        reason=reason,
        local_edit=changed or is_career_locally_dirty(session),
        sync_widget_keys=False,
    )


def apply_cloud_career_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_career_locally_dirty(session):
        return False
    filters: dict[str, Any] = {}
    cs = state.get("career_state")
    if isinstance(cs, dict) and isinstance(cs.get("filters"), dict):
        filters = {k: v for k, v in cs["filters"].items() if is_career_state_key(k)}
    if not filters:
        pf = state.get("page_filter_state")
        if isinstance(pf, dict):
            block = pf.get("Career Totals")
            if isinstance(block, dict):
                filters = _filters_from_block(block)
    if not filters:
        ws = state.get("baseball_workspace_state")
        if isinstance(ws, dict) and isinstance(ws.get("career_filters"), dict):
            filters = {k: v for k, v in ws["career_filters"].items() if is_career_state_key(k)}
    if not filters:
        return False
    write_canonical_career_state(session, filters=filters, reason="cloud_restore")
    clear_career_local_edit(session)
    session["_career_restored_filters"] = copy.deepcopy(filters)
    session["_career_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    return True


def apply_career_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    """Restore Career Totals filters from Applied Math return."""
    wp = dict(source_state.get("widget_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    merged = {**wp, **filt}
    filters = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if is_career_state_key(k)
    }
    write_canonical_career_state(session, filters=filters, reason="ami_return", local_edit=False)
    clear_career_local_edit(session)


def render_career_totals_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("career_state")
    if not isinstance(meta, dict):
        meta = {}
    canonical = meta.get("filters") if isinstance(meta.get("filters"), dict) else {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get("Career Totals")
        if isinstance(block, dict):
            pf_block = block
    widget_values = {k: session.get(k) for k in CAREER_ALL_STATE_KEYS if k in session}
    rows = {
        "career_state_dirty": session.get(CAREER_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "last_force_save_reason": session.get("_suite_pending_save_reason") or session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
        "cloud_payload_career_filters": session.get("_suite_last_cloud_payload_career_filters"),
        "restored_filters": session.get("_career_restored_filters"),
        "restore_source": session.get("_career_restore_source"),
        "canonical career_state.filters": canonical,
        "page_filter_state.career_state": pf_block.get("career_state"),
        "page_filter_state career keys": _filters_from_block(pf_block),
        "raw widget values": widget_values,
    }
    with st.sidebar.expander("Career Totals state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")
