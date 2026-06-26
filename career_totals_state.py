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
CAREER_PENDING_SYNC_KEY = "_career_filters_pending_sync"

CAREER_FILTER_KEYS = (
    "career_year_range_filter",
    "career_sort_stat_filter",
    "career_batting_hand_filter",
    "career_position_filter_mode",
    "career_position_filter",
    "career_team_filter",
    "career_by_team_toggle_filter",
)

# HOF player-scope is Case Mode only — not part of canonical career filter sync.
CAREER_HOF_SCOPE_FILTER_KEY = "career_hof_membership_filter"

CAREER_STAT_MIN_KEYS = tuple(f"career_{col}_min" for col in CAREER_STAT_COLUMNS)

CAREER_ALL_STATE_KEYS = CAREER_FILTER_KEYS + CAREER_STAT_MIN_KEYS

def _career_page_filter_block(session: dict[str, Any]) -> dict[str, Any]:
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Career Totals")
        if isinstance(block, dict):
            return block
    return {}


def _career_filters_from_blob(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    cs = state.get("career_state")
    if isinstance(cs, dict) and isinstance(cs.get("filters"), dict):
        out = {k: _normalize_filter_value(k, v) for k, v in cs["filters"].items() if is_career_state_key(k)}
        if out:
            return out
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Career Totals")
        if isinstance(block, dict):
            out = _filters_from_block(block)
            if out:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict) and isinstance(ws.get("career_filters"), dict):
        return {
            k: _normalize_filter_value(k, v)
            for k, v in ws["career_filters"].items()
            if is_career_state_key(k)
        }
    return {}


def snapshot_career_sync_layers(session: dict[str, Any]) -> dict[str, Any]:
    """Capture year range + franchise/league at every persistence layer."""
    canonical = canonical_career_filters(session) or {}
    pf_block = _career_page_filter_block(session)
    payload = session.get("_suite_last_cloud_payload_career_filters")
    if not isinstance(payload, dict):
        payload = {}
    return {
        "career_year_range_widget": session.get("career_year_range_filter"),
        "career_year_range_canonical": canonical.get("career_year_range_filter"),
        "career_year_range_page_filter_state": pf_block.get("career_year_range_filter"),
        "career_year_range_cloud_payload": payload.get("career_year_range_filter"),
        "career_team_filter_widget": session.get("career_team_filter"),
        "career_team_filter_canonical": canonical.get("career_team_filter"),
        "career_team_filter_page_filter_state": pf_block.get("career_team_filter"),
        "career_team_filter_cloud_payload": payload.get("career_team_filter"),
        "pending_edit_flag": bool(session.get(CAREER_PENDING_SYNC_KEY)),
        "dirty_flag": bool(session.get(CAREER_DIRTY_KEY)),
        "force_save_attempted": session.get("_career_last_force_save_attempted"),
        "force_save_success": session.get("_career_last_force_save_success"),
        "cloud_updated_at": session.get("_suite_cloud_fetch_updated_at")
        or session.get("_suite_applied_cloud_ts_baseball"),
        "cloud_save": session.get("_suite_persist_last_save_cloud"),
        "cloud_block_reason": session.get("_suite_autosave_cloud_blocked_reason"),
        "last_write_reason": (session.get("career_state") or {}).get("last_write_reason")
        if isinstance(session.get("career_state"), dict)
        else None,
        "last_force_save_reason": session.get("_suite_persist_last_save_reason"),
    }


def load_live_cloud_career_snapshot(app_id: str = "baseball") -> dict[str, Any]:
    try:
        from suite_cloud_state import load_cloud_full_session

        cloud_state, cloud_ts = load_cloud_full_session(app_id)
        if not isinstance(cloud_state, dict):
            return {"cloud_fetch_success": False}
        filt = _career_filters_from_blob(cloud_state)
        return {
            "cloud_fetch_success": True,
            "cloud_updated_at": cloud_ts,
            "cloud_career_year_range": filt.get("career_year_range_filter"),
            "cloud_career_team_filter": filt.get("career_team_filter"),
            "cloud_career_filters": filt,
        }
    except Exception as exc:
        return {"cloud_fetch_success": False, "cloud_fetch_error": str(exc)}


def record_career_sync_trace(session: dict[str, Any], phase: str, **extra: Any) -> None:
    event = {"at": _utc_now_iso(), "phase": phase, **snapshot_career_sync_layers(session), **extra}
    session[CAREER_SYNC_TRACE_KEY] = event
    log = session.setdefault(CAREER_SYNC_TRACE_LOG_KEY, [])
    if isinstance(log, list):
        log.append(event)
        if len(log) > 40:
            del log[:-40]
    session["_career_sync_failure_class"] = classify_career_sync_failure(session)


def classify_career_sync_failure(session: dict[str, Any]) -> str | None:
    """
    A) phone not writing cloud
    B) phone wrote cloud but Dell fetch does not match phone payload
    C) Dell fetched cloud but restore skipped/rejected
    D) restore applied but page render overwrote values
    """
    if session.get("_career_sync_failure_class_manual"):
        return str(session["_career_sync_failure_class_manual"])
    if session.get("_career_render_overwrite_detected"):
        return "D"
    if session.get("_career_restore_skipped_reason"):
        return "C"
    if session.get("_career_cloud_fetch_mismatch"):
        return "B"
    if session.get("_career_last_force_save_attempted") and not session.get("_career_last_force_save_success"):
        return "A"
    if session.get("_career_last_force_save_attempted") and not session.get("_suite_persist_last_save_cloud"):
        block = session.get("_suite_autosave_cloud_blocked_reason")
        if block:
            return "A"
    return None


def record_career_force_save_result(session: dict[str, Any], *, attempted: bool, success: bool, reason: str) -> None:
    session["_career_last_force_save_attempted"] = attempted
    session["_career_last_force_save_success"] = success
    record_career_sync_trace(
        session,
        "force_save",
        save_reason=reason,
        force_save_attempted=attempted,
        force_save_success=success,
    )


def record_career_cloud_restore_trace(
    session: dict[str, Any],
    *,
    applied: bool,
    skipped_reason: str = "",
    cloud_snapshot: dict[str, Any] | None = None,
) -> None:
    if skipped_reason:
        session["_career_restore_skipped_reason"] = skipped_reason
    elif applied:
        session.pop("_career_restore_skipped_reason", None)
    live = cloud_snapshot or load_live_cloud_career_snapshot()
    phone_payload = session.get("_suite_last_cloud_payload_career_filters")
    if (
        isinstance(phone_payload, dict)
        and live.get("cloud_fetch_success")
        and live.get("cloud_career_year_range") is not None
        and phone_payload.get("career_year_range_filter") is not None
        and live.get("cloud_career_year_range") != phone_payload.get("career_year_range_filter")
    ):
        session["_career_cloud_fetch_mismatch"] = True
    record_career_sync_trace(
        session,
        "cloud_restore",
        restore_applied=applied,
        restore_skipped_reason=skipped_reason or None,
        **live,
    )
CAREER_SYNC_TRACE_KEY = "_career_totals_sync_trace"
CAREER_SYNC_TRACE_LOG_KEY = "_career_totals_sync_trace_log"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_career_state_key(key: str) -> bool:
    k = str(key or "")
    return k in CAREER_ALL_STATE_KEYS or (k.startswith("career_") and k.endswith("_min"))


def _normalize_filter_value(key: str, value: Any) -> Any:
    if key == "career_year_range_filter":
        return normalize_career_year_range(value)
    if key == "career_team_filter":
        return _normalize_team_filter(value)
    if key == "career_batting_hand_filter" or key == "career_position_filter":
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value).strip()] if str(value).strip() else []
        return [str(x).strip() for x in value if str(x).strip()]
    if key == "career_by_team_toggle_filter":
        return bool(value)
    return copy.deepcopy(value)


def normalize_career_year_range(
    value: Any,
    *,
    min_year: int | None = None,
    max_year: int | None = None,
    default: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    """Stable 2-int tuple; accepts list or tuple; clamp only when bounds provided."""
    from year_range_state import sanitize_year_range

    if value is None:
        return None
    if min_year is not None and max_year is not None:
        if default is None:
            default = (int(min_year), int(max_year))
        return sanitize_year_range(value, int(min_year), int(max_year), default)
    parsed = value
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
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _career_widget_drift(session: dict[str, Any]) -> bool:
    widget = _extract_filters_from_session(session)
    canonical = canonical_career_filters(session) or {}
    if not widget:
        return False
    for key, val in widget.items():
        if canonical.get(key) != val:
            return True
    return False


def _migrate_legacy_career_keys(session: dict[str, Any]) -> None:
    if "career_year_range_filter" not in session and session.get("career_year") is not None:
        yr = normalize_career_year_range(session.get("career_year"))
        if yr is not None:
            session["career_year_range_filter"] = yr
    if "career_team_filter" not in session and session.get("career_team") is not None:
        session["career_team_filter"] = _normalize_team_filter(session.get("career_team"))


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


def _strip_hof_scope_unless_case_mode(session: dict[str, Any], filt: dict[str, Any]) -> dict[str, Any]:
    """HOF player-scope belongs to Case Mode only — never persist it in normal Career Totals."""
    try:
        from hall_of_fame_data import (
            CAREER_HOF_FILTER_KEY,
            career_hof_case_mode_active,
            clear_career_hof_case_scope_state,
        )
    except ImportError:
        return filt
    if career_hof_case_mode_active(session):
        return filt
    out = dict(filt)
    out.pop(CAREER_HOF_FILTER_KEY, None)
    clear_career_hof_case_scope_state(session)
    return out


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
    filt = _strip_hof_scope_unless_case_mode(session, filt)
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
    payload = copy.deepcopy(filt)
    session["_suite_last_cloud_payload_career_filters"] = payload
    if "career_year_range_filter" in payload:
        session["_suite_last_cloud_payload_career_year_range"] = copy.deepcopy(
            payload["career_year_range_filter"]
        )
    if local_edit:
        mark_career_local_edit(session)
    return meta


def gather_career_filters(session: dict[str, Any]) -> dict[str, Any]:
    _migrate_legacy_career_keys(session)
    widget = _extract_filters_from_session(session)
    canonical = canonical_career_filters(session) or {}

    if is_career_locally_dirty(session) or session.get(CAREER_PENDING_SYNC_KEY) or _career_widget_drift(session):
        return {**canonical, **widget}

    if widget:
        return {**canonical, **widget}

    if canonical:
        return dict(canonical)

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
    _migrate_legacy_career_keys(session)
    if session.pop("_hof_case_skip_prepare_reconcile", None) or session.get("_hof_case_workspace_restored"):
        widget = _extract_filters_from_session(session)
        if widget:
            meta = write_canonical_career_state(
                session,
                filters=widget,
                reason="hof_workspace_restore",
                local_edit=False,
                sync_widget_keys=False,
            )
            record_career_sync_trace(session, "prepare_career_totals_page", branch="hof_workspace_restore")
            return meta
        return session.get("career_state") if isinstance(session.get("career_state"), dict) else {}
    widget = _extract_filters_from_session(session)
    canonical = canonical_career_filters(session) or {}
    drift = _career_widget_drift(session) or bool(session.get(CAREER_PENDING_SYNC_KEY))

    if is_career_locally_dirty(session) or drift:
        filt = {**canonical, **widget}
        meta = write_canonical_career_state(
            session,
            filters=filt,
            reason="local_edit_preserve" if is_career_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
        record_career_sync_trace(session, "prepare_career_totals_page", branch="local_edit_or_drift")
        return meta

    if canonical:
        filt = {**canonical, **widget}
        meta = write_canonical_career_state(
            session,
            filters=filt,
            reason="canonical_preserve",
            sync_widget_keys=not bool(widget),
        )
        record_career_sync_trace(session, "prepare_career_totals_page", branch="canonical_preserve")
        return meta

    filt = gather_career_filters(session)
    return write_canonical_career_state(
        session,
        filters=filt,
        reason="reconcile_on_load" if filt else "empty",
    )


def prepare_career_totals_filters(session: dict[str, Any]) -> None:
    """Seed filter widget keys from canonical career_state when not locally dirty."""
    try:
        from hall_of_fame_data import (
            CAREER_HOF_FILTER_KEY,
            HOF_FILTER_ALL,
            career_hof_case_mode_active,
            clear_career_hof_case_scope_state,
            normalize_hof_filter_value,
        )
    except ImportError:
        career_hof_case_mode_active = lambda _s: False  # type: ignore[assignment,misc]
        clear_career_hof_case_scope_state = lambda _s: None  # type: ignore[assignment,misc]
        CAREER_HOF_FILTER_KEY = CAREER_HOF_SCOPE_FILTER_KEY
        HOF_FILTER_ALL = "All Players"

        def normalize_hof_filter_value(value: Any) -> str:  # type: ignore[misc]
            return str(value or HOF_FILTER_ALL)

    if not career_hof_case_mode_active(session):
        clear_career_hof_case_scope_state(session)

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

    if career_hof_case_mode_active(session) and CAREER_HOF_FILTER_KEY not in session:
        for source in (merged, block_filters, block, filters):
            if not isinstance(source, dict):
                continue
            val = source.get(CAREER_HOF_FILTER_KEY)
            if val is not None:
                session[CAREER_HOF_FILTER_KEY] = normalize_hof_filter_value(val)
                record_career_field_write(session, CAREER_HOF_FILTER_KEY, "career_state.filters", new=val)
                break
        else:
            session[CAREER_HOF_FILTER_KEY] = HOF_FILTER_ALL


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


def prepare_career_year_range(
    session: dict[str, Any],
    min_year: int,
    max_year: int,
    default: tuple[int, int],
) -> tuple[int, int]:
    """Seed/clamp year range before slider; never reset a valid in-bounds range to default."""
    from year_range_state import sanitize_year_range

    key = "career_year_range_filter"
    _migrate_legacy_career_keys(session)
    canonical = (canonical_career_filters(session) or {}).get(key)
    raw = session.get(key) if key in session else None
    if raw is None and canonical is not None:
        raw = canonical
    preserve_default = default
    if is_career_locally_dirty(session) or session.get(CAREER_PENDING_SYNC_KEY) or _career_widget_drift(session):
        if raw is not None:
            preserve_default = normalize_career_year_range(raw) or default
    sanitized = sanitize_year_range(raw, int(min_year), int(max_year), preserve_default)
    if sanitized is None:
        sanitized = (int(min_year), int(max_year))
    session[key] = (int(sanitized[0]), int(sanitized[1]))
    return session[key]


def prepare_career_multiselect_filter(
    session: dict[str, Any],
    key: str,
    options: list[str],
    default: list[str] | None = None,
) -> list[str]:
    """Prepare multiselect options/values; preserve valid selections across option rebuilds."""
    opts = [str(x) for x in options]
    default_list = _normalize_filter_value(key, default or [])
    canonical = (canonical_career_filters(session) or {}).get(key)
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

    if is_career_locally_dirty(session) or session.get(CAREER_PENDING_SYNC_KEY) or _career_widget_drift(session):
        session[key] = [x for x in current if x in merged_opts or x in preserve]
        if not session[key] and current:
            session[key] = list(current)
    elif session.get("_transfer_just_applied_to") != session.get("active_page"):
        session[key] = [x for x in current if x in opts]
    else:
        session[key] = [x for x in current if x in merged_opts]
    return merged_opts


def mark_career_filter_pending_sync(session: dict[str, Any]) -> None:
    session[CAREER_PENDING_SYNC_KEY] = True


def flush_career_filter_edits(session: dict[str, Any], st_obj: Any = None, *, reason: str = "filter_change") -> bool:
    """After widgets render: read current session values, update canonical, force-save."""
    pending = bool(session.pop(CAREER_PENDING_SYNC_KEY, False))
    current = _extract_filters_from_session(session)
    prev = canonical_career_filters(session) or {}
    if not current and not pending:
        return False
    changed = current != prev
    if not pending and not changed:
        return False
    write_canonical_career_state(
        session,
        filters={**prev, **current},
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    record_career_sync_trace(session, "phone_after_edit", flush_reason=reason)
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="career_edit")
        except Exception:
            pass
    return True


def sync_career_filter_change(session: dict[str, Any], *, reason: str = "filter_change") -> None:
    """Legacy alias — on_change only marks pending; call flush after widgets render."""
    mark_career_filter_pending_sync(session)


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
    """Restore Career Totals filters and Hall of Fame Case Mode from Applied Math return."""
    wp = dict(source_state.get("widget_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    chart = dict(source_state.get("chart_params") or {})
    merged = {**wp, **filt}
    try:
        from hall_of_fame_data import CAREER_HOF_FILTER_KEY
    except ImportError:
        CAREER_HOF_FILTER_KEY = CAREER_HOF_SCOPE_FILTER_KEY

    filters = {
        k: _normalize_filter_value(k, copy.deepcopy(merged[k]))
        for k in merged
        if is_career_state_key(k) or k == CAREER_HOF_FILTER_KEY
    }
    filters = _strip_hof_scope_unless_case_mode(session, filters)
    write_canonical_career_state(session, filters=filters, reason="ami_return", local_edit=False, sync_widget_keys=True)
    clear_career_local_edit(session)

    try:
        from hall_of_fame_data import (
            CAREER_HOF_CASE_MODE_KEY,
            CAREER_HOF_CASE_TARGET_KEY,
            HOF_CASE_PACKET_KEY,
        )
    except ImportError:
        return

    if ent.get("hof_case_mode"):
        session[CAREER_HOF_CASE_MODE_KEY] = True
    target = ent.get("hof_case_target") or ent.get("target_player")
    if target:
        session[CAREER_HOF_CASE_TARGET_KEY] = str(target).strip()
    packet = ent.get("hof_case_packet")
    if isinstance(packet, dict) and packet.get("mode") == "hall_of_fame_case":
        session[HOF_CASE_PACKET_KEY] = copy.deepcopy(packet)
    snap = chart.get("career_snapshot")
    if isinstance(snap, dict) and snap:
        session["_ami_career_snapshot"] = copy.deepcopy(snap)


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
    cloud_payload = session.get("_suite_last_cloud_payload_career_filters")
    if isinstance(cloud_payload, dict):
        cloud_year = cloud_payload.get("career_year_range_filter")
        cloud_team = cloud_payload.get("career_team_filter")
    else:
        cloud_year = session.get("_suite_last_cloud_payload_career_year_range")
        cloud_team = None
    rows = {
        "career_state_dirty": session.get(CAREER_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "last_force_save_reason": session.get("_suite_pending_save_reason")
        or session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
        "raw career_year_range widget": session.get("career_year_range_filter"),
        "canonical career_year_range": canonical.get("career_year_range_filter"),
        "page_filter_state career_year_range": pf_block.get("career_year_range_filter"),
        "cloud_payload_career_year_range": cloud_year,
        "raw career_team_filter widget": session.get("career_team_filter"),
        "canonical career_team_filter": canonical.get("career_team_filter"),
        "page_filter_state career_team_filter": pf_block.get("career_team_filter"),
        "cloud_payload_career_team_filter": cloud_team,
        "cloud_payload_career_filters": cloud_payload,
        "pending_sync": session.get(CAREER_PENDING_SYNC_KEY),
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


def render_career_totals_sync_trace(st: Any, session: dict[str, Any]) -> None:
    """Dev-mode sidebar trace of Career Totals cloud sync events."""
    trace = session.get(CAREER_SYNC_TRACE_KEY)
    log = session.get(CAREER_SYNC_TRACE_LOG_KEY)
    with st.sidebar.expander("Career Totals sync trace", expanded=False):
        if isinstance(trace, dict):
            st.text("— latest event —")
            for k, v in trace.items():
                if v is not None and v != "" and v is not False and v != {}:
                    st.text(f"{k}: {v}")
        else:
            st.text("no sync trace yet")
        if isinstance(log, list) and log:
            st.text(f"— trace log ({len(log)} events) —")
            for entry in reversed(log[-10:]):
                phase = entry.get("phase", "?")
                at = entry.get("at", "")
                dirty = entry.get("dirty_flag", False)
                pending = entry.get("pending_edit_flag", False)
                st.text(f"{at[:19]} [{phase}] dirty={dirty} pending={pending}")
