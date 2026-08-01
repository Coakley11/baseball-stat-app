"""Streamlit internal widget metadata + callback dispatch diagnostics (observability only)."""

from __future__ import annotations

import inspect
import time
from typing import Any

INTERNAL_METADATA_REGISTERED = "production_stage1_internal_widget_metadata_registered"
BACKEND_WIDGET_STATE = "production_stage1_backend_widget_state_after_backmsg"
CALLBACK_DISPATCH_EVALUATED = "production_stage1_callback_dispatch_evaluated"

METADATA_HISTORY_KEY = "_solo_stage1_widget_metadata_history"
WATCH_USER_KEYS_KEY = "_solo_stage1_metadata_watch_user_keys"
CALLBACKS_PATCHED_KEY = "_solo_stage1_call_callbacks_patched"


def _diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except ImportError:
        return False


def _fn_identity(fn: Any) -> str:
    if fn is None:
        return ""
    try:
        return f"{getattr(fn, '__module__', '')}.{getattr(fn, '__name__', repr(fn))}"[:200]
    except Exception:
        return "unknown"


def _metadata_type_name(metadata: Any) -> str:
    if metadata is None:
        return ""
    return type(metadata).__name__


def get_streamlit_session_state(st: Any | None) -> Any | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_state", None) is not None:
            inner = ctx.session_state
            if hasattr(inner, "_new_widget_state"):
                return inner
    except Exception:
        pass
    if st is None:
        return None
    try:
        ss = getattr(st, "session_state", None)
        if ss is not None and hasattr(ss, "_new_widget_state"):
            return ss
    except Exception:
        pass
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_state", None) is not None:
            return ctx.session_state
    except Exception:
        pass
    return None


def resolve_authoritative_widget_id(
    st: Any | None, user_key: str, *, component_name: str = ""
) -> tuple[str, str]:
    if not user_key:
        return "", "missing_user_key"
    ss = get_streamlit_session_state(st)
    if ss is not None:
        try:
            meta_map = ss._new_widget_state.widget_metadata
            suffix = f"-{user_key}"
            matches = [wid for wid in meta_map if str(wid).endswith(suffix) or suffix in str(wid)]
            if matches:
                return matches[-1], "widget_metadata_key_suffix"
        except Exception:
            pass
    try:
        from live_draft_stage1_widget_identity import read_actual_registered_widget_id

        wid, src = read_actual_registered_widget_id(st, user_key)
        if wid:
            return wid, src
    except ImportError:
        pass
    if component_name == "solo_countdown_wake":
        try:
            from live_draft_stage1_widget_identity import predict_solo_countdown_component_element_id

            predicted = predict_solo_countdown_component_element_id(user_key)
            if predicted:
                if not predicted.startswith("$$"):
                    predicted = f"$$ID-{predicted}"
                return predicted, "predicted_id"
        except ImportError:
            pass
    return "", "unresolved"


def snapshot_widget_metadata(ss: Any, widget_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "authoritative_widget_id": widget_id,
        "metadata_object_type": "",
        "metadata_callback_present": False,
        "metadata_callback_identity": "",
        "metadata_callbacks_present": False,
        "metadata_callbacks_keys": [],
        "metadata_callbacks_identities": {},
        "callback_args_repr": "",
        "callback_kwargs_repr": "",
        "value_type": "",
        "deserializer_identity": "",
        "serializer_identity": "",
        "fragment_id": "",
        "metadata_missing": True,
    }
    if not widget_id or ss is None:
        return out
    try:
        metadata = ss._get_widget_metadata(widget_id)
    except Exception:
        metadata = None
    if metadata is None:
        return out
    out["metadata_missing"] = False
    out["metadata_object_type"] = _metadata_type_name(metadata)
    out["value_type"] = str(getattr(metadata, "value_type", "") or "")
    out["fragment_id"] = str(getattr(metadata, "fragment_id", "") or "")[:80]
    cb = getattr(metadata, "callback", None)
    out["metadata_callback_present"] = cb is not None
    out["metadata_callback_identity"] = _fn_identity(cb)
    cbs = getattr(metadata, "callbacks", None)
    if isinstance(cbs, dict) and cbs:
        out["metadata_callbacks_present"] = True
        out["metadata_callbacks_keys"] = sorted(str(k) for k in cbs.keys())[:40]
        out["metadata_callbacks_identities"] = {
            str(k): _fn_identity(v) for k, v in list(cbs.items())[:20]
        }
    args = getattr(metadata, "callback_args", None)
    kwargs = getattr(metadata, "callback_kwargs", None)
    try:
        out["callback_args_repr"] = repr(args)[:300]
        out["callback_kwargs_repr"] = repr(kwargs)[:300]
    except Exception:
        pass
    try:
        out["deserializer_identity"] = _fn_identity(getattr(metadata, "deserializer", None))
        out["serializer_identity"] = _fn_identity(getattr(metadata, "serializer", None))
    except Exception:
        pass
    try:
        from streamlit.runtime.state.common import user_key_from_element_id

        out["user_key"] = str(user_key_from_element_id(widget_id) or "")[:160]
    except Exception:
        out["user_key"] = ""
    return out


def metadata_stores_callback(metadata_snap: dict[str, Any]) -> bool:
    if metadata_snap.get("metadata_missing"):
        return False
    if metadata_snap.get("metadata_callback_present"):
        return True
    if metadata_snap.get("metadata_callbacks_present"):
        return True
    return False


def _unwrap_json_map(obj: object) -> dict[str, object]:
    if not isinstance(obj, dict):
        return {}
    if set(obj.keys()) == {"value"}:
        value = obj.get("value")
        if isinstance(value, dict):
            return dict(value)
    return dict(obj)


def _json_value_changed(new_val: object, old_val: object) -> bool:
    new_map = _unwrap_json_map(new_val)
    old_map = _unwrap_json_map(old_val)
    if not new_map and not old_map:
        return new_val != old_val
    all_keys = new_map.keys() | old_map.keys()
    return any(old_map.get(k) != new_map.get(k) for k in all_keys)


def snapshot_backend_widget_state(
    ss: Any,
    widget_id: str,
    *,
    expected_token: str = "",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "authoritative_widget_id": widget_id,
        "in_new_widget_state": False,
        "serialized_value_field_type": "",
        "serialized_value_present": False,
        "deserialized_value_repr": "",
        "exact_expiration_token_present": False,
        "in_old_state": False,
        "old_deserialized_value_repr": "",
        "widget_changed": False,
        "user_key_from_mapping": "",
        "widget_considered_active": False,
        "metadata_exists_for_id": False,
    }
    if not widget_id or ss is None:
        return out
    try:
        out["in_new_widget_state"] = widget_id in ss._new_widget_state.states
    except Exception:
        pass
    try:
        serialized = ss._new_widget_state.get_serialized(widget_id)
        if serialized is not None:
            out["serialized_value_present"] = True
            if getattr(serialized, "json_value", None):
                out["serialized_value_field_type"] = "json_value"
            elif getattr(serialized, "string_value", None) is not None:
                out["serialized_value_field_type"] = "string_value"
            else:
                out["serialized_value_field_type"] = type(serialized).__name__
    except Exception:
        pass
    try:
        new_val = ss._new_widget_state.get(widget_id)
        rep = repr(new_val)[:400]
        out["deserialized_value_repr"] = rep
        tok = str(expected_token or "")
        if tok and tok in rep:
            out["exact_expiration_token_present"] = True
    except KeyError:
        pass
    except Exception:
        pass
    try:
        if widget_id in ss._old_state:
            out["in_old_state"] = True
            out["old_deserialized_value_repr"] = repr(ss._old_state.get(widget_id))[:400]
    except Exception:
        pass
    try:
        out["widget_changed"] = bool(ss._widget_changed(widget_id))
    except Exception:
        pass
    try:
        wid_map = ss._key_id_mapper.id_key_mapping
        out["user_key_from_mapping"] = str(wid_map.get(widget_id) or "")[:160]
    except Exception:
        pass
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_state", None) is ss:
            active = getattr(ctx, "widget_ids_this_run", None)
            if active is not None:
                out["widget_considered_active"] = widget_id in active
    except Exception:
        pass
    try:
        out["metadata_exists_for_id"] = ss._get_widget_metadata(widget_id) is not None
    except Exception:
        pass
    return out


def evaluate_callback_dispatch(
    ss: Any,
    widget_id: str,
    *,
    prod_entered_count: int = 0,
) -> dict[str, Any]:
    """Mirror Streamlit _call_callbacks selection (diagnostic only; does not invoke)."""
    meta_snap = snapshot_widget_metadata(ss, widget_id)
    state_snap = snapshot_backend_widget_state(ss, widget_id)
    metadata = None
    try:
        metadata = ss._get_widget_metadata(widget_id)
    except Exception:
        pass
    new_val: Any = None
    old_val: Any = None
    new_present = False
    try:
        new_val = ss._new_widget_state.get(widget_id)
        new_present = True
    except KeyError:
        new_present = False
    except Exception:
        new_present = False
    try:
        old_val = ss._old_state.get(widget_id)
    except Exception:
        old_val = None
    changed = False
    try:
        changed = bool(ss._widget_changed(widget_id)) if new_present else False
    except Exception:
        changed = False

    callback_selected = False
    skip_reason = "unknown"
    callback_identity = ""

    if metadata is None:
        skip_reason = "metadata_missing"
    elif not new_present:
        skip_reason = "new_widget_state_missing"
    elif metadata.callback is not None:
        if not changed:
            skip_reason = "widget_value_unchanged"
        else:
            callback_selected = True
            callback_identity = _fn_identity(metadata.callback)
            skip_reason = ""
    elif metadata.callbacks and metadata.value_type == "json_value":
        if _json_value_changed(new_val, old_val):
            for key in _unwrap_json_map(new_val).keys() | _unwrap_json_map(old_val).keys():
                cb = metadata.callbacks.get(key)
                if cb is not None and _unwrap_json_map(new_val).get(key) != _unwrap_json_map(old_val).get(
                    key
                ):
                    callback_selected = True
                    callback_identity = _fn_identity(cb)
                    skip_reason = ""
                    break
            if not callback_selected:
                skip_reason = "callback_missing_from_metadata"
        else:
            skip_reason = "widget_value_unchanged"
    else:
        skip_reason = "callback_missing_from_metadata"

    if callback_selected and prod_entered_count == 0:
        pass  # CM9 detection happens in classifier

    return {
        "widget_id": widget_id,
        "metadata_callback_present": meta_snap.get("metadata_callback_present"),
        "metadata_callbacks_present": meta_snap.get("metadata_callbacks_present"),
        "new_state_present": new_present,
        "old_state_present": state_snap.get("in_old_state"),
        "new_value_repr": repr(new_val)[:400] if new_present else "",
        "old_value_repr": repr(old_val)[:400] if old_val is not None else "",
        "widget_changed_result": changed,
        "callback_selected": callback_selected,
        "callback_identity": callback_identity,
        "skip_reason": skip_reason or ("none" if callback_selected else "unknown"),
        "value_type": meta_snap.get("value_type"),
    }


def register_watch_user_key(session: dict[str, Any], user_key: str) -> None:
    keys = set(session.get(WATCH_USER_KEYS_KEY) or [])
    if user_key:
        keys.add(str(user_key))
    session[WATCH_USER_KEYS_KEY] = list(keys)


def _record_metadata_history(session: dict[str, Any], widget_id: str, snap: dict[str, Any]) -> None:
    hist = dict(session.get(METADATA_HISTORY_KEY) or {})
    rows = list(hist.get(widget_id) or [])
    rows.append(
        {
            "ts": time.time(),
            "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
            **snap,
        }
    )
    hist[widget_id] = rows[-12:]
    session[METADATA_HISTORY_KEY] = hist


def _emit(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None,
    room: dict[str, Any] | None,
    widget_key: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from live_draft_prod_on_change_observability import _emit_row

        return _emit_row(
            session,
            event,
            st=st,
            room=room,
            widget_key=widget_key,
            extra=extra,
        )
    except ImportError:
        return {}


def probe_after_declaration(
    st: Any,
    session: dict[str, Any],
    *,
    user_key: str,
    component_name: str,
    application_on_change: Any,
    declaration_invocation_id: str = "",
    surface: str = "production",
    room: dict[str, Any] | None = None,
    expected_token: str = "",
    mount_guard_result: str = "",
) -> dict[str, Any]:
    """Read Streamlit WidgetMetadata after register_widget (no mutation)."""
    if not _diag_enabled(st, session):
        return {}
    register_watch_user_key(session, user_key)
    ss = get_streamlit_session_state(st)
    widget_id, id_source = resolve_authoritative_widget_id(st, user_key, component_name=component_name)
    meta_snap = snapshot_widget_metadata(ss, widget_id) if ss and widget_id else {}
    meta_snap["authoritative_widget_id"] = widget_id
    meta_snap["widget_id_source"] = id_source
    meta_snap["component_name"] = component_name
    meta_snap["application_on_change_argument_present"] = application_on_change is not None
    meta_snap["application_on_change_identity"] = _fn_identity(application_on_change)
    meta_snap["registration_script_run_sequence"] = int(session.get("_solo_stage1_script_run_seq") or 0)
    meta_snap["registration_timestamp"] = time.time()
    meta_snap["declaration_invocation_id"] = str(declaration_invocation_id or "")
    meta_snap["diagnostic_surface"] = surface
    meta_snap["mount_guard_result"] = str(mount_guard_result or "")[:80]
    meta_snap["callback_registered_in_metadata"] = metadata_stores_callback(meta_snap)
    if widget_id:
        _record_metadata_history(session, widget_id, meta_snap)
    return _emit(
        session,
        INTERNAL_METADATA_REGISTERED,
        st=st,
        room=room,
        widget_key=user_key,
        extra=meta_snap,
    )


def emit_backend_widget_state_probe(
    st: Any,
    session: dict[str, Any],
    *,
    user_key: str,
    widget_id: str,
    expected_token: str = "",
    room: dict[str, Any] | None = None,
    phase: str = "pre_dispatch",
) -> dict[str, Any]:
    if not _diag_enabled(st, session):
        return {}
    ss = get_streamlit_session_state(st)
    if not ss or not widget_id:
        return {}
    snap = snapshot_backend_widget_state(ss, widget_id, expected_token=expected_token)
    snap["phase"] = phase
    snap["diagnostic_surface"] = session.get("_solo_stage1_last_metadata_surface") or ""
    return _emit(
        session,
        BACKEND_WIDGET_STATE,
        st=st,
        room=room,
        widget_key=user_key,
        extra=snap,
    )


def emit_callback_dispatch_evaluated_row(
    st: Any,
    session: dict[str, Any],
    *,
    user_key: str,
    widget_id: str,
    eval_row: dict[str, Any],
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _diag_enabled(st, session):
        return {}
    return _emit(
        session,
        CALLBACK_DISPATCH_EVALUATED,
        st=st,
        room=room,
        widget_key=user_key,
        extra=eval_row,
    )


def install_streamlit_callback_dispatch_probe(st: Any | None, session: dict[str, Any]) -> None:
    """Patch SessionState._call_callbacks once per session (observability only)."""
    if session.get(CALLBACKS_PATCHED_KEY):
        return
    if not _diag_enabled(st, session):
        return
    try:
        from streamlit.runtime.state.session_state import SessionState
    except ImportError:
        return
    if getattr(SessionState._call_callbacks, "_solo_metadata_diag_wrapped", False):
        session[CALLBACKS_PATCHED_KEY] = True
        return
    original = SessionState._call_callbacks

    def wrapped_call_callbacks(self: Any) -> None:
        ss = self
        watch_keys = list(session.get(WATCH_USER_KEYS_KEY) or [])
        expected = str(
            session.get("_solo_persistent_wake_last_token")
            or session.get("_solo_parity_expected_token")
            or ""
        )
        prod_entered = int(session.get("_solo_stage1_prod_on_change_entered_count") or 0)
        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
        for user_key in watch_keys:
            wid, _ = resolve_authoritative_widget_id(st, str(user_key))
            if not wid:
                continue
            emit_backend_widget_state_probe(
                st,
                session,
                user_key=str(user_key),
                widget_id=wid,
                expected_token=expected,
                room=room,
                phase="pre_dispatch",
            )
            eval_row = evaluate_callback_dispatch(ss, wid, prod_entered_count=prod_entered)
            emit_callback_dispatch_evaluated_row(
                st,
                session,
                user_key=str(user_key),
                widget_id=wid,
                eval_row=eval_row,
                room=room,
            )
        return original(self)

    wrapped_call_callbacks._solo_metadata_diag_wrapped = True  # type: ignore[attr-defined]
    SessionState._call_callbacks = wrapped_call_callbacks  # type: ignore[method-assign]
    session[CALLBACKS_PATCHED_KEY] = True


def metadata_history_for_widget(session: dict[str, Any], widget_id: str) -> list[dict[str, Any]]:
    hist = session.get(METADATA_HISTORY_KEY) or {}
    rows = hist.get(widget_id) if isinstance(hist, dict) else None
    return list(rows) if isinstance(rows, list) else []
