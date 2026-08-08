"""Read-only Streamlit fragment / widget ownership snapshots (solo diagnostics)."""

from __future__ import annotations

import time
from typing import Any

MATRIX_IDENTITY_IMPL_REV = "stage1_fragment_identity_runtime_v1"


def _thread_state_fields() -> dict[str, Any]:
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import ThreadState

        ts = ThreadState.get()
        return {
            "thread_state_fragment_id": str(ts.fragment_id or "")[:80],
            "thread_state_delta_path": list(ts.delta_path or [])[:24],
            "thread_state_in_fragment_callback": bool(ts.in_fragment_callback),
            "thread_state_active_script_hash": str(ts.active_script_hash or "")[:64],
            "thread_state_pre_allocated_container_fragment_id": str(
                ts.pre_allocated_container_fragment_id or ""
            )[:80],
            "thread_state_is_parallel_worker": bool(getattr(ts, "is_parallel_worker", False)),
        }
    except Exception as exc:
        return {"thread_state_error": f"{type(exc).__name__}:{exc}"[:120]}


def _fragment_storage_snapshot(storage: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "registration_sequence": None,
        "stored_fragment_ids": [],
        "parent_by_id": {},
    }
    if storage is None:
        return out
    try:
        out["registration_sequence"] = int(storage.registration_sequence())
    except Exception:
        pass
    try:
        seq = int(out["registration_sequence"] or 0)
        out["ids_registered_after_seq_0"] = sorted(storage.ids_registered_after(0))
    except Exception:
        out["ids_registered_after_seq_0"] = []
    try:
        from streamlit.runtime.fragment import MemoryFragmentStorage

        if isinstance(storage, MemoryFragmentStorage):
            with storage._lock:
                out["stored_fragment_ids"] = sorted(storage._fragments.keys())
                out["parent_by_id"] = {
                    str(k): (str(v) if v is not None else None)
                    for k, v in dict(storage._parent_by_id).items()
                }
    except Exception:
        pass
    return out


def snapshot_fragment_identity(*, phase: str, widget_user_key: str = "") -> dict[str, Any]:
    """Capture fragment ownership at render, pre-click scrape, or callback."""
    row: dict[str, Any] = {
        "ts": time.time(),
        "phase": str(phase or "")[:32],
        "impl_rev": MATRIX_IDENTITY_IMPL_REV,
        "widget_user_key": str(widget_user_key or "")[:160],
    }
    row.update(_thread_state_fields())
    ctx = None
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
    except Exception:
        ctx = None
    if ctx is not None:
        row["streamlit_session_id"] = str(getattr(ctx, "session_id", "") or "")[:64]
        row["page_script_hash"] = str(getattr(ctx, "page_script_hash", "") or "")[:64]
        row["fragment_ids_this_run"] = list(getattr(ctx, "fragment_ids_this_run", None) or [])
        row["current_fragment_id_ctx"] = str(getattr(ctx, "current_fragment_id", "") or "")[:80]
        storage = getattr(ctx, "fragment_storage", None)
        row["fragment_storage"] = _fragment_storage_snapshot(storage)
        render_fid = row.get("thread_state_fragment_id") or row.get("current_fragment_id_ctx") or ""
        if render_fid and storage is not None:
            try:
                row["render_fragment_in_storage"] = bool(storage.contains(render_fid))
            except Exception:
                row["render_fragment_in_storage"] = None
    if widget_user_key:
        row["widget_metadata"] = snapshot_widget_metadata_for_user_key(widget_user_key)
        owner, sub = evaluate_widget_owner_fragment_current(row)
        row["widget_owner_fragment_current"] = owner
        row["ownership_subcode"] = sub
        meta_fid = str((row.get("widget_metadata") or {}).get("fragment_id") or "")
        if meta_fid:
            row["metadata_fragment_in_storage"] = fragment_id_exists_in_storage(meta_fid)
    return row


def evaluate_widget_owner_fragment_current(identity: dict[str, Any]) -> tuple[bool | None, str]:
    """True when widget metadata fragment_id is present and still in fragment_storage."""
    meta = identity.get("widget_metadata") if isinstance(identity.get("widget_metadata"), dict) else {}
    meta_fid = str(meta.get("fragment_id") or "").strip()
    if not meta_fid:
        return None, "missing_metadata_fragment_id"
    contained = fragment_id_exists_in_storage(meta_fid)
    if contained is True:
        return True, ""
    if contained is False:
        storage = identity.get("fragment_storage") if isinstance(identity.get("fragment_storage"), dict) else {}
        stored = set(storage.get("stored_fragment_ids") or [])
        if stored and meta_fid not in stored:
            return False, "FRAGMENT_WIDGET_OWNER_STALE"
        return False, "metadata_fragment_not_in_storage"
    return None, "storage_lookup_unavailable"


def snapshot_widget_metadata_for_user_key(user_key: str) -> dict[str, Any]:
    out: dict[str, Any] = {"user_key": str(user_key or "")[:160]}
    try:
        from live_draft_stage1_widget_identity import read_actual_registered_widget_id

        wid, src = read_actual_registered_widget_id(None, user_key)
        out["widget_id"] = wid[:200]
        out["widget_id_source"] = src
    except Exception:
        wid = ""
    if not wid:
        return out
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_state", None) is not None:
            ss = ctx.session_state
            if hasattr(ss, "_get_widget_metadata"):
                meta = ss._get_widget_metadata(wid)
                if meta is not None:
                    from live_draft_streamlit_widget_metadata_diag import (
                        snapshot_from_widget_metadata_object,
                    )

                    out.update(snapshot_from_widget_metadata_object(meta, user_key=user_key))
    except Exception as exc:
        out["metadata_error"] = f"{type(exc).__name__}:{exc}"[:120]
    ts_fid = _thread_state_fields().get("thread_state_fragment_id") or ""
    meta_fid = str(out.get("fragment_id") or "")
    if ts_fid or meta_fid:
        out["fragment_id_matches_thread_state"] = bool(ts_fid and meta_fid and ts_fid == meta_fid)
        out["thread_state_fragment_id_at_snapshot"] = ts_fid
    return out


def fragment_id_exists_in_storage(fragment_id: str) -> bool | None:
    fid = str(fragment_id or "").strip()
    if not fid:
        return None
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "fragment_storage", None) is not None:
            return bool(ctx.fragment_storage.contains(fid))
    except Exception:
        return None
    return None
