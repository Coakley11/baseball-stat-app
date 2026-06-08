"""Canonical ML Predictions page state — scope, tuning, display, pipeline flag."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

PROJECTIONS_PAGE = "ML Predictions"

PROJECTIONS_DIRTY_KEY = "projections_state_dirty"
PROJECTIONS_LOCAL_EDIT_TS_KEY = "projections_state_last_local_edit_ts"
PROJECTIONS_PENDING_SYNC_KEY = "_projections_state_pending_sync"

PROJECTIONS_SCOPE_KEYS = (
    "ml_lookback",
    "ml_min_games",
    "ml_min_ab",
    "ml_max_players",
)

PROJECTIONS_TUNING_KEYS = (
    "ml_projection_style",
    "ml_regression_strength",
    "ml_age_strength",
    "ml_comp_weight",
    "ml_k_neighbors",
    "ml_auto_apply_tuning",
)

PROJECTIONS_DISPLAY_KEYS = (
    "ml_position_filter",
    "ml_sort_by",
    "ml_projection_insight_player",
    "ml_age_curve_stat",
    "ml_importance_stat",
)

PROJECTIONS_PIPELINE_KEYS = ("ml_predictions_have_run",)

PROJECTIONS_ALL_STATE_KEYS = (
    PROJECTIONS_SCOPE_KEYS + PROJECTIONS_TUNING_KEYS + PROJECTIONS_DISPLAY_KEYS + PROJECTIONS_PIPELINE_KEYS
)

PROJECTIONS_SKIP_PREFIXES = ("_ml_",)
PROJECTIONS_SKIP_EXACT = frozenset({
    "ml_predictions_df",
    "ml_predictions_status",
    "ml_full_generation_requested",
    "ml_tuning_apply_requested",
    "ml_display_sort",
    "ml_predictions_selected_player",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_projections_state_key(key: str) -> bool:
    k = str(key or "")
    if k in PROJECTIONS_SKIP_EXACT:
        return False
    if any(k.startswith(p) for p in PROJECTIONS_SKIP_PREFIXES):
        return False
    return k in PROJECTIONS_ALL_STATE_KEYS


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key in ("ml_auto_apply_tuning", "ml_predictions_have_run"):
        return bool(value)
    if key in PROJECTIONS_SCOPE_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key in ("ml_regression_strength", "ml_age_strength", "ml_comp_weight"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if key == "ml_k_neighbors":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key in ("ml_projection_insight_player", "ml_age_curve_stat", "ml_importance_stat"):
        return str(value).strip() if value not in (None, "") else None
    return copy.deepcopy(value)


def is_projections_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(PROJECTIONS_DIRTY_KEY))


def mark_projections_local_edit(session: dict[str, Any]) -> None:
    session[PROJECTIONS_DIRTY_KEY] = True
    session[PROJECTIONS_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_projections_local_edit(session: dict[str, Any]) -> None:
    session.pop(PROJECTIONS_DIRTY_KEY, None)
    session.pop(PROJECTIONS_LOCAL_EDIT_TS_KEY, None)


def _section_for_key(key: str) -> str:
    if key in PROJECTIONS_SCOPE_KEYS:
        return "scope"
    if key in PROJECTIONS_TUNING_KEYS:
        return "tuning"
    if key in PROJECTIONS_DISPLAY_KEYS:
        return "display"
    if key in PROJECTIONS_PIPELINE_KEYS:
        return "pipeline"
    return "display"


def _flat_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for section in ("scope", "tuning", "display"):
        block = meta.get(section)
        if isinstance(block, dict):
            for k, v in block.items():
                if is_projections_state_key(k):
                    out[k] = _normalize_filter_value(k, v)
    pipeline = meta.get("pipeline")
    if isinstance(pipeline, dict) and "has_run" in pipeline:
        out["ml_predictions_have_run"] = bool(pipeline["has_run"])
    return out


def _meta_from_flat(flat: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "scope": {},
        "tuning": {},
        "display": {},
        "pipeline": {"has_run": bool(flat.get("ml_predictions_have_run", False))},
    }
    for key, val in flat.items():
        if not is_projections_state_key(key):
            continue
        section = _section_for_key(key)
        if section == "pipeline":
            meta["pipeline"]["has_run"] = bool(val)
        else:
            meta[section][key] = _normalize_filter_value(key, val)
    return meta


def _extract_state_from_session(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in PROJECTIONS_ALL_STATE_KEYS:
        if key in session:
            out[key] = _normalize_filter_value(key, session[key])
    return out


def _filters_from_block(block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inner = block.get("projections_state")
    if isinstance(inner, dict):
        out.update(_flat_from_meta(inner))
    for key, val in block.items():
        if key == "projections_state":
            continue
        if is_projections_state_key(key):
            out[key] = _normalize_filter_value(key, val)
    return out


def _projections_state_from_blob(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    ps = state.get("projections_state")
    if isinstance(ps, dict):
        flat = _flat_from_meta(ps)
        if flat:
            return flat
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(PROJECTIONS_PAGE)
        if isinstance(block, dict):
            out = _filters_from_block(block)
            if out:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict) and isinstance(ws.get("projections_filters"), dict):
        return {
            k: _normalize_filter_value(k, v)
            for k, v in ws["projections_filters"].items()
            if is_projections_state_key(k)
        }
    return {}


def canonical_projections_state(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("projections_state")
    if not isinstance(meta, dict):
        return None
    flat = _flat_from_meta(meta)
    return flat or None


def _sync_page_filter_projections_block(session: dict[str, Any], *, flat: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(PROJECTIONS_PAGE, {})
    if not isinstance(block, dict):
        block = {}
        pf[PROJECTIONS_PAGE] = block
    meta = session.get("projections_state")
    if isinstance(meta, dict):
        block["projections_state"] = copy.deepcopy(meta)
    data = flat if flat is not None else (canonical_projections_state(session) or {})
    for key, val in data.items():
        if is_projections_state_key(key):
            block[key] = _normalize_filter_value(key, val)


def write_canonical_projections_state(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    raw = dict(filters) if isinstance(filters, dict) else _extract_state_from_session(session)
    flat = {k: _normalize_filter_value(k, v) for k, v in raw.items() if is_projections_state_key(k)}
    meta = _meta_from_flat(flat)
    meta["last_write_reason"] = reason or None
    session["projections_state"] = meta
    if sync_widget_keys:
        for key, val in flat.items():
            session[key] = _normalize_filter_value(key, val)
    _sync_page_filter_projections_block(session, flat=flat)
    session["_suite_last_cloud_payload_projections_filters"] = copy.deepcopy(flat)
    if local_edit:
        mark_projections_local_edit(session)
    return meta


def _projections_widget_drift(session: dict[str, Any]) -> bool:
    widget = _extract_state_from_session(session)
    canonical = canonical_projections_state(session) or {}
    if not widget:
        return False
    for key, val in widget.items():
        if canonical.get(key) != val:
            return True
    return False


def gather_projections_state(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_state_from_session(session)
    canonical = canonical_projections_state(session) or {}
    if is_projections_locally_dirty(session) or session.get(PROJECTIONS_PENDING_SYNC_KEY) or _projections_widget_drift(session):
        return {**canonical, **widget}
    if widget:
        return {**canonical, **widget}
    if canonical:
        return dict(canonical)
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(PROJECTIONS_PAGE)
        if isinstance(block, dict):
            block_state = _filters_from_block(block)
            if block_state:
                return block_state
    blob = _projections_state_from_blob(session)
    if blob:
        return blob
    return {}


def prepare_projections_page(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_state_from_session(session)
    canonical = canonical_projections_state(session) or {}
    drift = _projections_widget_drift(session) or bool(session.get(PROJECTIONS_PENDING_SYNC_KEY))
    if is_projections_locally_dirty(session) or drift:
        filt = {**canonical, **widget}
        return write_canonical_projections_state(
            session,
            filters=filt,
            reason="local_edit_preserve" if is_projections_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
    if canonical:
        filt = {**canonical, **widget}
        return write_canonical_projections_state(
            session,
            filters=filt,
            reason="canonical_preserve",
            sync_widget_keys=not bool(widget),
        )
    filt = gather_projections_state(session)
    return write_canonical_projections_state(
        session,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_projections_filters(session: dict[str, Any]) -> None:
    if is_projections_locally_dirty(session):
        return
    flat = canonical_projections_state(session) or {}
    pf = session.get("page_filter_state")
    block = pf.get(PROJECTIONS_PAGE) if isinstance(pf, dict) else None
    if isinstance(block, dict):
        flat = {**_filters_from_block(block), **flat}
    for key in PROJECTIONS_ALL_STATE_KEYS:
        if key in session:
            continue
        if key in flat:
            session[key] = _normalize_filter_value(key, flat[key])


def mark_projections_filter_pending_sync(session: dict[str, Any]) -> None:
    session[PROJECTIONS_PENDING_SYNC_KEY] = True


def mark_projections_pipeline_refresh(session: dict[str, Any]) -> None:
    session["ml_predictions_have_run"] = True
    mark_projections_filter_pending_sync(session)


def flush_projections_filter_edits(session: dict[str, Any], st_obj: Any = None, *, reason: str = "filter_change") -> bool:
    pending = bool(session.pop(PROJECTIONS_PENDING_SYNC_KEY, False))
    current = _extract_state_from_session(session)
    prev = canonical_projections_state(session) or {}
    if not current and not pending:
        return False
    changed = current != prev
    if not pending and not changed:
        return False
    write_canonical_projections_state(
        session,
        filters={**prev, **current},
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="projections_edit")
        except Exception:
            pass
    return True


def restore_projections_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_projections_locally_dirty(session):
        return False
    snapshot = store.get(PROJECTIONS_PAGE) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    for key, value in snapshot.items():
        if key == "projections_state":
            continue
        if not is_projections_state_key(key):
            continue
        session[key] = _normalize_filter_value(key, value)
    flat = _filters_from_block(snapshot)
    if flat:
        write_canonical_projections_state(
            session,
            filters=flat,
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    return True


def apply_cloud_projections_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_projections_locally_dirty(session):
        return False
    flat = _projections_state_from_blob(state)
    if not flat:
        return False
    write_canonical_projections_state(session, filters=flat, reason="cloud_restore", local_edit=False)
    clear_projections_local_edit(session)
    session["_projections_restored_filters"] = copy.deepcopy(flat)
    session["_projections_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    return True


def apply_projections_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    wp = dict(source_state.get("widget_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    merged = {**wp, **ent, **filt}
    flat = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if is_projections_state_key(k)
    }
    write_canonical_projections_state(session, filters=flat, reason="ami_return", local_edit=False)
    clear_projections_local_edit(session)
    snap = (source_state.get("chart_params") or {}).get("ml_snapshot")
    if isinstance(snap, dict):
        session["_ami_ml_snapshot"] = copy.deepcopy(snap)


def render_projections_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("projections_state")
    if not isinstance(meta, dict):
        meta = {}
    canonical = canonical_projections_state(session) or {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get(PROJECTIONS_PAGE)
        if isinstance(block, dict):
            pf_block = block
    cloud_payload = session.get("_suite_last_cloud_payload_projections_filters")
    rows = {
        "projections_state_dirty": session.get(PROJECTIONS_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "last_force_save_reason": session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
        "raw ml_lookback": session.get("ml_lookback"),
        "canonical ml_lookback": canonical.get("ml_lookback"),
        "page_filter_state ml_lookback": pf_block.get("ml_lookback"),
        "cloud_payload ml_lookback": (cloud_payload or {}).get("ml_lookback") if isinstance(cloud_payload, dict) else None,
        "pipeline has_run": canonical.get("ml_predictions_have_run"),
        "pending_sync": session.get(PROJECTIONS_PENDING_SYNC_KEY),
        "restored_filters": session.get("_projections_restored_filters"),
        "restore_source": session.get("_projections_restore_source"),
        "canonical scope": meta.get("scope"),
        "canonical tuning": meta.get("tuning"),
        "canonical display": meta.get("display"),
        "page_filter_state keys": _filters_from_block(pf_block),
    }
    with st.sidebar.expander("ML Predictions state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")
