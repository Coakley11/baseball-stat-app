"""AppSession.request_rerun ingress diagnostics (read-only, solo diag)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

APPSESSION_INGRESS_IMPL_REV = "stage1_appsession_ingress_diag_v1"
APPSESSION_PATCHED_KEY = "_stage1_appsession_ingress_patched"
APPSESSION_LEDGER_SESSION_KEY = "_stage1_appsession_ingress_ledger"

_APPSESSION_INGRESS_BY_STREAMLIT_SESSION: dict[str, list[dict[str, Any]]] = {}
_LEDGER_LOCK = threading.Lock()


def _streamlit_session_id_from_ctx() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _fragment_storage_snapshot(fragment_storage: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"stored_fragment_ids": [], "contains_fn": bool(fragment_storage)}
    if fragment_storage is None:
        return out
    try:
        if hasattr(fragment_storage, "order_fragment_ids"):
            ids = list(fragment_storage.order_fragment_ids())
    except Exception:
        ids = []
    out["stored_fragment_ids"] = [str(x) for x in ids[:32]]
    return out


def _sibling_in_client_state(client_state: Any, *, exact_id: str, user_key_suffix: str) -> dict[str, Any]:
    out: dict[str, Any] = {"sibling_present": False, "sibling_proto": {}, "incoming_widget_count": 0}
    if client_state is None:
        return out
    try:
        if not client_state.HasField("widget_states"):
            return out
        widgets = list(client_state.widget_states.widgets)
    except Exception:
        return out
    out["incoming_widget_count"] = len(widgets)
    suffix = f"-{user_key_suffix}" if user_key_suffix else ""
    for ws in widgets:
        wid = str(getattr(ws, "id", "") or "")
        if exact_id and wid == exact_id:
            out["sibling_present"] = True
            out["sibling_proto"] = {
                "id": wid,
                "trigger_value": bool(getattr(ws, "trigger_value", False)),
            }
            return out
        if suffix and (wid.endswith(suffix) or suffix in wid):
            out["sibling_present"] = True
            out["sibling_proto"] = {
                "id": wid,
                "trigger_value": bool(getattr(ws, "trigger_value", False)),
            }
            return out
    return out


def append_appsession_ingress_event(
    streamlit_session_id: str,
    session: dict[str, Any] | None,
    **fields: Any,
) -> dict[str, Any]:
    sid = str(streamlit_session_id or _streamlit_session_id_from_ctx())[:64]
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "phase": "APPSESSION_REQUEST_RERUN_ENTRY",
        "streamlit_session_id": sid,
        **{k: v for k, v in fields.items() if v is not None},
    }
    with _LEDGER_LOCK:
        book = list(_APPSESSION_INGRESS_BY_STREAMLIT_SESSION.get(sid) or [])
        book.append(dict(row))
        _APPSESSION_INGRESS_BY_STREAMLIT_SESSION[sid] = book[-48:]
    if isinstance(session, dict):
        sess_book = list(session.get(APPSESSION_LEDGER_SESSION_KEY) or [])
        sess_book.append(dict(row))
        session[APPSESSION_LEDGER_SESSION_KEY] = sess_book[-48:]
    return row


def appsession_ingress_export(session: dict[str, Any] | None = None) -> dict[str, Any]:
    sid = _streamlit_session_id_from_ctx()
    with _LEDGER_LOCK:
        rows = list(_APPSESSION_INGRESS_BY_STREAMLIT_SESSION.get(sid) or [])
    if isinstance(session, dict):
        sess_rows = list(session.get(APPSESSION_LEDGER_SESSION_KEY) or [])
        if len(sess_rows) > len(rows):
            rows = sess_rows
    return {"event_count": len(rows), "rows": rows[-32:], "impl_rev": APPSESSION_INGRESS_IMPL_REV}


def install_appsession_request_rerun_probe(st: Any | None, session: dict[str, Any]) -> None:
    if session.get(APPSESSION_PATCHED_KEY):
        return
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    try:
        from streamlit.runtime.app_session import AppSession
    except ImportError:
        return

    if getattr(AppSession.request_rerun, "_solo_appsession_ingress_wrapped", False):
        session[APPSESSION_PATCHED_KEY] = True
        return

    original = AppSession.request_rerun

    def wrapped_request_rerun(self: Any, client_state: Any | None = None) -> Any:
        sid = _streamlit_session_id_from_ctx()
        watch_key = str(session.get("_stage1_s3_server_watch_user_key") or "")
        exact_id = str(session.get("_stage1_s3_strict_wire_widget_id") or "")
        frag_id = ""
        page_hash = ""
        sibling_found: dict[str, Any] = {}
        storage_snap: dict[str, Any] = {}
        target_exists = False
        would_fail = False
        appsession_id = str(getattr(self, "id", "") or "")[:64] or str(id(self))

        if client_state is not None:
            try:
                frag_id = str(getattr(client_state, "fragment_id", "") or "")
            except Exception:
                pass
            try:
                page_hash = str(getattr(client_state, "page_script_hash", "") or "")[:64]
            except Exception:
                pass
            sibling_found = _sibling_in_client_state(client_state, exact_id=exact_id, user_key_suffix=watch_key)
            try:
                fs = getattr(self, "_fragment_storage", None)
                storage_snap = _fragment_storage_snapshot(fs)
                if frag_id and fs is not None and hasattr(fs, "contains"):
                    target_exists = bool(fs.contains(frag_id))
                would_fail = bool(frag_id) and fs is not None and hasattr(fs, "contains") and not fs.contains(frag_id)
            except Exception:
                pass

        runner_state = ""
        try:
            runner = getattr(self, "_scriptrunner", None) or getattr(self, "script_runner", None)
            if runner is not None:
                runner_state = str(getattr(runner, "state", "") or getattr(runner, "_state", ""))[:48]
        except Exception:
            pass

        append_appsession_ingress_event(
            sid,
            session,
            appsession_id=appsession_id,
            client_state_fragment_id=frag_id,
            page_script_hash=page_hash,
            target_fragment_exists=target_exists,
            would_fail_streamlit_fragment_storage_guard=would_fail,
            fragment_storage_ids=storage_snap.get("stored_fragment_ids"),
            script_runner_state=runner_state,
            **sibling_found,
        )
        return original(self, client_state)

    wrapped_request_rerun._solo_appsession_ingress_wrapped = True  # type: ignore[attr-defined]
    AppSession.request_rerun = wrapped_request_rerun  # type: ignore[method-assign]
    session[APPSESSION_PATCHED_KEY] = True
