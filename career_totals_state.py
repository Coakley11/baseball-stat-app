"""Canonical Career Totals page state — filters, sort, by-team toggle."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_career_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(CAREER_DIRTY_KEY))


def mark_career_local_edit(session: dict[str, Any]) -> None:
    session[CAREER_DIRTY_KEY] = True
    session[CAREER_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_career_local_edit(session: dict[str, Any]) -> None:
    session.pop(CAREER_DIRTY_KEY, None)
    session.pop(CAREER_LOCAL_EDIT_TS_KEY, None)


def _extract_filters_from_session(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in CAREER_FILTER_KEYS:
        if key in session:
            out[key] = copy.deepcopy(session[key])
    return out


def canonical_career_filters(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("career_state")
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        return dict(meta["filters"])
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


def _sync_page_filter_career_block(session: dict[str, Any]) -> None:
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
    for key in CAREER_FILTER_KEYS:
        if key in session:
            block[key] = copy.deepcopy(session[key])


def write_canonical_career_state(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
    reason: str = "",
    local_edit: bool = False,
) -> dict[str, Any]:
    """Write canonical career_state and mirror filter widget keys."""
    filt = dict(filters) if isinstance(filters, dict) else _extract_filters_from_session(session)
    meta = session.get("career_state")
    if not isinstance(meta, dict):
        meta = {}
    meta["filters"] = copy.deepcopy(filt)
    meta["last_write_reason"] = reason or None
    session["career_state"] = meta
    for key, val in filt.items():
        session[key] = copy.deepcopy(val)
        record_career_field_write(session, key, reason or "canonical", new=val)
    _sync_page_filter_career_block(session)
    if local_edit:
        mark_career_local_edit(session)
    return meta


def gather_career_filters(session: dict[str, Any]) -> dict[str, Any]:
    if is_career_locally_dirty(session):
        widget = _extract_filters_from_session(session)
        if widget:
            return widget
        canonical = canonical_career_filters(session)
        return dict(canonical) if canonical else {}

    canonical = canonical_career_filters(session)
    if canonical is not None:
        return dict(canonical)

    widget = _extract_filters_from_session(session)
    if widget:
        return widget

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Career Totals")
        if isinstance(block, dict):
            inner = block.get("career_state")
            if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
                return dict(inner["filters"])
            out = {k: block[k] for k in CAREER_FILTER_KEYS if k in block}
            if out:
                return out
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
    for key in CAREER_FILTER_KEYS:
        if key in session:
            continue
        if key in filters:
            session[key] = copy.deepcopy(filters[key])
            record_career_field_write(session, key, "career_state.filters", new=filters[key])
        elif key in block:
            session[key] = copy.deepcopy(block[key])
            record_career_field_write(session, key, "page_filter_state", new=block[key])


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
        if key not in CAREER_FILTER_KEYS:
            continue
        old = session.get(key)
        try:
            session[key] = copy.deepcopy(value)
        except Exception:
            session[key] = value
        record_career_field_write(session, key, "page_filter_state", old, value)
    inner = snapshot.get("career_state")
    if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
        write_canonical_career_state(
            session,
            filters=inner["filters"],
            reason="page_filter_restore",
            local_edit=False,
        )
    return True


def commit_career_filters_from_session(session: dict[str, Any], *, reason: str = "widget_rerun") -> None:
    """Persist current widget values to canonical career_state (marks dirty when changed)."""
    current = _extract_filters_from_session(session)
    if not current:
        return
    prev = canonical_career_filters(session) or {}
    changed = current != prev
    write_canonical_career_state(
        session,
        filters=current,
        reason=reason,
        local_edit=changed or is_career_locally_dirty(session),
    )


def apply_cloud_career_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_career_locally_dirty(session):
        return False
    filters: dict[str, Any] = {}
    cs = state.get("career_state")
    if isinstance(cs, dict) and isinstance(cs.get("filters"), dict):
        filters = dict(cs["filters"])
    if not filters:
        pf = state.get("page_filter_state")
        if isinstance(pf, dict):
            block = pf.get("Career Totals")
            if isinstance(block, dict):
                inner = block.get("career_state")
                if isinstance(inner, dict) and isinstance(inner.get("filters"), dict):
                    filters = dict(inner["filters"])
                else:
                    filters = {k: block[k] for k in CAREER_FILTER_KEYS if k in block}
    if not filters:
        ws = state.get("baseball_workspace_state")
        if isinstance(ws, dict) and isinstance(ws.get("career_filters"), dict):
            filters = dict(ws["career_filters"])
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
    filters = {k: copy.deepcopy(merged[k]) for k in CAREER_FILTER_KEYS if k in merged}
    if not filters:
        filters = {
            k: copy.deepcopy(v)
            for k, v in merged.items()
            if str(k).startswith("career_")
        }
    write_canonical_career_state(session, filters=filters, reason="ami_return", local_edit=False)
    clear_career_local_edit(session)


def render_career_totals_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("career_state")
    if not isinstance(meta, dict):
        meta = {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get("Career Totals")
        if isinstance(block, dict):
            pf_block = block
    rows = {
        "career_state.filters": meta.get("filters"),
        "last_write_reason": meta.get("last_write_reason"),
        "career_state_dirty": session.get(CAREER_DIRTY_KEY),
        "widget year_range": session.get("career_year_range_filter"),
        "widget sort": session.get("career_sort_stat_filter"),
        "widget by_team_toggle": session.get("career_by_team_toggle_filter"),
        "page_filter_state.career_state": pf_block.get("career_state"),
        "restored_filters": session.get("_career_restored_filters"),
        "restore_source": session.get("_career_restore_source"),
        "last_save_reason": session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
    }
    with st.sidebar.expander("Career Totals state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False:
                st.text(f"{k}: {v}")
