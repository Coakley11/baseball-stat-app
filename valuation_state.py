"""Canonical Valuation page state — filters, stat minimums, selected player."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

try:
    from page_transfers import _TRANSFER_STAT_COLS as VALUATION_STAT_COLUMNS
except ImportError:
    VALUATION_STAT_COLUMNS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]

VALUATION_PAGE = "Valuation"

VALUATION_DIRTY_KEY = "valuation_state_dirty"
VALUATION_LOCAL_EDIT_TS_KEY = "valuation_state_last_local_edit_ts"
VALUATION_PENDING_SYNC_KEY = "_valuation_filters_pending_sync"

VALUATION_FILTER_KEYS = (
    "value_lag",
    "value_min_g",
    "value_position_filter",
    "value_use_draft_room_sync",
    "value_sync_team_for_draft",
    "value_w_current",
    "value_w_trend",
)

VALUATION_ENTITY_KEYS = ("valuation_selected_player",)
VALUATION_STAT_MIN_KEYS = tuple(f"value_{col}_min" for col in VALUATION_STAT_COLUMNS)
VALUATION_ALL_STATE_KEYS = VALUATION_FILTER_KEYS + VALUATION_STAT_MIN_KEYS + VALUATION_ENTITY_KEYS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_valuation_state_key(key: str) -> bool:
    k = str(key or "")
    return k in VALUATION_ALL_STATE_KEYS or (k.startswith("value_") and k.endswith("_min"))


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key in ("value_use_draft_room_sync",):
        return bool(value)
    if key in ("value_lag", "value_min_g"):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key in ("value_w_current", "value_w_trend"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if key == "valuation_selected_player":
        return str(value).strip() if value not in (None, "") else None
    return copy.deepcopy(value)


def is_valuation_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(VALUATION_DIRTY_KEY))


def mark_valuation_local_edit(session: dict[str, Any]) -> None:
    session[VALUATION_DIRTY_KEY] = True
    session[VALUATION_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_valuation_local_edit(session: dict[str, Any]) -> None:
    session.pop(VALUATION_DIRTY_KEY, None)
    session.pop(VALUATION_LOCAL_EDIT_TS_KEY, None)


def _extract_state_from_session(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in VALUATION_ALL_STATE_KEYS:
        if key in session:
            out[key] = _normalize_filter_value(key, session[key])
    for key, val in session.items():
        if is_valuation_state_key(str(key)) and key not in out:
            out[str(key)] = _normalize_filter_value(str(key), val)
    return out


def _split_filters_and_entity(flat: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    filters: dict[str, Any] = {}
    selected: str | None = None
    for key, val in flat.items():
        if key == "valuation_selected_player":
            selected = _normalize_filter_value(key, val)
        elif is_valuation_state_key(key):
            filters[key] = _normalize_filter_value(key, val)
    return filters, selected


def _filters_from_block(block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inner = block.get("valuation_state")
    if isinstance(inner, dict):
        if isinstance(inner.get("filters"), dict):
            for key, val in inner["filters"].items():
                if is_valuation_state_key(key):
                    out[key] = _normalize_filter_value(key, val)
        sp = inner.get("selected_player")
        if sp:
            out["valuation_selected_player"] = _normalize_filter_value("valuation_selected_player", sp)
    for key, val in block.items():
        if key == "valuation_state":
            continue
        if is_valuation_state_key(key):
            out[key] = _normalize_filter_value(key, val)
    return out


def _valuation_state_from_blob(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    vs = state.get("valuation_state")
    if isinstance(vs, dict):
        flat: dict[str, Any] = {}
        if isinstance(vs.get("filters"), dict):
            for k, v in vs["filters"].items():
                if is_valuation_state_key(k):
                    flat[k] = _normalize_filter_value(k, v)
        if vs.get("selected_player"):
            flat["valuation_selected_player"] = _normalize_filter_value(
                "valuation_selected_player", vs["selected_player"]
            )
        if flat:
            return flat
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(VALUATION_PAGE)
        if isinstance(block, dict):
            out = _filters_from_block(block)
            if out:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict) and isinstance(ws.get("valuation_filters"), dict):
        return {
            k: _normalize_filter_value(k, v)
            for k, v in ws["valuation_filters"].items()
            if is_valuation_state_key(k)
        }
    return {}


def canonical_valuation_state(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("valuation_state")
    if not isinstance(meta, dict):
        return None
    out: dict[str, Any] = {}
    if isinstance(meta.get("filters"), dict):
        for k, v in meta["filters"].items():
            if is_valuation_state_key(k):
                out[k] = _normalize_filter_value(k, v)
    if meta.get("selected_player"):
        out["valuation_selected_player"] = _normalize_filter_value(
            "valuation_selected_player", meta["selected_player"]
        )
    return out or None


def _sync_page_filter_valuation_block(session: dict[str, Any], *, flat: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(VALUATION_PAGE, {})
    if not isinstance(block, dict):
        block = {}
        pf[VALUATION_PAGE] = block
    meta = session.get("valuation_state")
    if isinstance(meta, dict):
        block["valuation_state"] = {
            "filters": copy.deepcopy(meta.get("filters") or {}),
            "selected_player": meta.get("selected_player"),
            "last_write_reason": meta.get("last_write_reason"),
        }
    data = flat
    if data is None:
        data = canonical_valuation_state(session) or {}
    for key, val in data.items():
        if is_valuation_state_key(key):
            block[key] = _normalize_filter_value(key, val)


def write_canonical_valuation_state(
    session: dict[str, Any],
    *,
    filters: dict[str, Any] | None = None,
    selected_player: str | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    raw = dict(filters) if isinstance(filters, dict) else _extract_state_from_session(session)
    filt, entity = _split_filters_and_entity(raw)
    if selected_player is not None:
        entity = _normalize_filter_value("valuation_selected_player", selected_player)
    meta = session.get("valuation_state")
    if not isinstance(meta, dict):
        meta = {}
    meta["filters"] = copy.deepcopy(filt)
    meta["selected_player"] = entity
    meta["last_write_reason"] = reason or None
    session["valuation_state"] = meta
    flat = {**filt}
    if entity:
        flat["valuation_selected_player"] = entity
    if sync_widget_keys:
        for key, val in flat.items():
            session[key] = _normalize_filter_value(key, val)
    _sync_page_filter_valuation_block(session, flat=flat)
    payload = copy.deepcopy(filt)
    if entity:
        payload["valuation_selected_player"] = entity
    session["_suite_last_cloud_payload_valuation_filters"] = payload
    if local_edit:
        mark_valuation_local_edit(session)
    return meta


def _valuation_widget_drift(session: dict[str, Any]) -> bool:
    widget = _extract_state_from_session(session)
    canonical = canonical_valuation_state(session) or {}
    if not widget:
        return False
    for key, val in widget.items():
        if canonical.get(key) != val:
            return True
    return False


def gather_valuation_state(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_state_from_session(session)
    canonical = canonical_valuation_state(session) or {}
    if is_valuation_locally_dirty(session) or session.get(VALUATION_PENDING_SYNC_KEY) or _valuation_widget_drift(session):
        return {**canonical, **widget}
    if widget:
        return {**canonical, **widget}
    if canonical:
        return dict(canonical)
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(VALUATION_PAGE)
        if isinstance(block, dict):
            block_state = _filters_from_block(block)
            if block_state:
                return block_state
    blob = _valuation_state_from_blob(session)
    if blob:
        return blob
    return {}


def prepare_valuation_page(session: dict[str, Any]) -> dict[str, Any]:
    widget = _extract_state_from_session(session)
    canonical = canonical_valuation_state(session) or {}
    drift = _valuation_widget_drift(session) or bool(session.get(VALUATION_PENDING_SYNC_KEY))
    if is_valuation_locally_dirty(session) or drift:
        filt = {**canonical, **widget}
        return write_canonical_valuation_state(
            session,
            filters=filt,
            reason="local_edit_preserve" if is_valuation_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
    if canonical:
        filt = {**canonical, **widget}
        return write_canonical_valuation_state(
            session,
            filters=filt,
            reason="canonical_preserve",
            sync_widget_keys=not bool(widget),
        )
    filt = gather_valuation_state(session)
    return write_canonical_valuation_state(
        session,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_valuation_filters(session: dict[str, Any]) -> None:
    if is_valuation_locally_dirty(session):
        return
    meta = session.get("valuation_state")
    filters: dict[str, Any] = {}
    if isinstance(meta, dict) and isinstance(meta.get("filters"), dict):
        filters = meta["filters"]
    pf = session.get("page_filter_state")
    block = pf.get(VALUATION_PAGE) if isinstance(pf, dict) else None
    if not isinstance(block, dict):
        block = {}
    block_state = _filters_from_block(block)
    merged = {**block_state, **{k: v for k, v in filters.items() if is_valuation_state_key(k)}}
    if meta and meta.get("selected_player") and "valuation_selected_player" not in merged:
        merged["valuation_selected_player"] = meta["selected_player"]
    for key in VALUATION_ALL_STATE_KEYS:
        if key in session:
            continue
        if key in merged:
            session[key] = _normalize_filter_value(key, merged[key])


def mark_valuation_filter_pending_sync(session: dict[str, Any]) -> None:
    session[VALUATION_PENDING_SYNC_KEY] = True


def flush_valuation_filter_edits(session: dict[str, Any], st_obj: Any = None, *, reason: str = "filter_change") -> bool:
    pending = bool(session.pop(VALUATION_PENDING_SYNC_KEY, False))
    current = _extract_state_from_session(session)
    prev = canonical_valuation_state(session) or {}
    if not current and not pending:
        return False
    changed = current != prev
    if not pending and not changed:
        return False
    write_canonical_valuation_state(
        session,
        filters={**prev, **current},
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="valuation_edit")
        except Exception:
            pass
    return True


def restore_valuation_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_valuation_locally_dirty(session):
        return False
    snapshot = store.get(VALUATION_PAGE) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    for key, value in snapshot.items():
        if key == "valuation_state":
            continue
        if not is_valuation_state_key(key):
            continue
        session[key] = _normalize_filter_value(key, value)
    inner = snapshot.get("valuation_state")
    if isinstance(inner, dict):
        flat = _filters_from_block(snapshot)
        write_canonical_valuation_state(
            session,
            filters=flat,
            selected_player=flat.get("valuation_selected_player"),
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    elif snapshot:
        write_canonical_valuation_state(
            session,
            filters=_filters_from_block(snapshot),
            reason="page_filter_restore",
            local_edit=False,
            sync_widget_keys=False,
        )
    return True


def apply_cloud_valuation_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_valuation_locally_dirty(session):
        return False
    flat = _valuation_state_from_blob(state)
    if not flat:
        return False
    write_canonical_valuation_state(
        session,
        filters=flat,
        selected_player=flat.get("valuation_selected_player"),
        reason="cloud_restore",
        local_edit=False,
    )
    clear_valuation_local_edit(session)
    session["_valuation_restored_filters"] = copy.deepcopy(flat)
    session["_valuation_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    return True


def apply_valuation_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    wp = dict(source_state.get("widget_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    merged = {**wp, **ent, **filt}
    flat = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if is_valuation_state_key(k)
    }
    sp = ent.get("valuation_selected_player") or merged.get("valuation_selected_player")
    write_canonical_valuation_state(
        session,
        filters=flat,
        selected_player=sp,
        reason="ami_return",
        local_edit=False,
    )
    clear_valuation_local_edit(session)


def render_valuation_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("valuation_state")
    if not isinstance(meta, dict):
        meta = {}
    canonical = canonical_valuation_state(session) or {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get(VALUATION_PAGE)
        if isinstance(block, dict):
            pf_block = block
    cloud_payload = session.get("_suite_last_cloud_payload_valuation_filters")
    rows = {
        "valuation_state_dirty": session.get(VALUATION_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "last_force_save_reason": session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
        "raw value_lag": session.get("value_lag"),
        "canonical value_lag": canonical.get("value_lag"),
        "page_filter_state value_lag": pf_block.get("value_lag"),
        "cloud_payload value_lag": (cloud_payload or {}).get("value_lag") if isinstance(cloud_payload, dict) else None,
        "selected_player": session.get("valuation_selected_player"),
        "canonical selected_player": meta.get("selected_player"),
        "pending_sync": session.get(VALUATION_PENDING_SYNC_KEY),
        "restored_filters": session.get("_valuation_restored_filters"),
        "restore_source": session.get("_valuation_restore_source"),
        "canonical filters": meta.get("filters"),
        "page_filter_state keys": _filters_from_block(pf_block),
    }
    with st.sidebar.expander("Valuation state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")
