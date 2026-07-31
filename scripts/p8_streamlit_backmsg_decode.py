"""Safe Streamlit BackMsg / ForwardMsg decode for harness comparison (no secrets)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

WIDGET_ID_RE = re.compile(r"\$\$ID-([a-f0-9]{32})-([^\x00-\x1f\\]+?)(?:[\x00-\x1f]|\\|$)", re.I)
USER_KEY_SUFFIX_RE = re.compile(
    r"(solo_countdown_wake[^\x00-\x1f]*|solo_countdown_wake_transport_minimal|minimal_wake[^\x00-\x1f]*)",
    re.I,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_widget_ids_from_bytes(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8", errors="ignore")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in WIDGET_ID_RE.finditer(text):
        wid = m.group(1).lower()
        suffix = m.group(2).strip()
        if wid in seen:
            continue
        seen.add(wid)
        out.append({"internal_id_hash": wid, "user_key_suffix": suffix[:120]})
    return out


def _safe_widget_state_row(ws: Any) -> dict[str, Any]:
    row: dict[str, Any] = {}
    try:
        row["id"] = str(getattr(ws, "id", "") or "")
    except Exception:
        pass
    try:
        row["string_value_preview"] = str(getattr(ws, "string_value", "") or "")[:400]
    except Exception:
        pass
    try:
        row["trigger_value"] = bool(getattr(ws, "trigger_value", False))
    except Exception:
        pass
    try:
        row["set_value"] = bool(getattr(ws, "set_value", False))
    except Exception:
        pass
    try:
        jsv = getattr(ws, "json_value", None)
        if jsv is not None:
            row["json_value_preview"] = str(jsv)[:400]
    except Exception:
        pass
    return row


def try_parse_backmsg(data: bytes) -> dict[str, Any]:
    """Parse BackMsg from raw WebSocket payload; redact and summarize."""
    base: dict[str, Any] = {
        "byte_len": len(data),
        "sha256": _sha256(data),
        "parsed": False,
        "widget_ids_in_binary": extract_widget_ids_from_bytes(data),
    }
    if not data:
        return base
    try:
        from streamlit.proto.BackMsg_pb2 import BackMsg
    except ImportError:
        base["parse_error"] = "BackMsg_pb2_unavailable"
        return base

    msg = BackMsg()
    parsed_at: int | None = None
    for skip in (0, 1, 2, 3, 4, 5):
        if skip >= len(data):
            break
        try:
            msg.ParseFromString(data[skip:])
            parsed_at = skip
            break
        except Exception:
            msg = BackMsg()
            continue
    if parsed_at is None:
        base["parse_error"] = "protobuf_parse_failed"
        base["frame_type_hint"] = _frame_hint_from_bytes(data)
        return base

    base["parsed"] = True
    base["parse_skip_bytes"] = parsed_at
    which = msg.WhichOneof("type")
    base["backmsg_oneof_type"] = which or ""
    base["frame_type_hint"] = "backmsg_protobuf"

    if which == "rerun_script":
        base["backmsg_fields"] = ["rerun_script"]
        cs = msg.rerun_script
        base["client_state"] = _client_state_summary(cs)
        if cs.HasField("widget_states"):
            wss = cs.widget_states
            rows = [_safe_widget_state_row(ws) for ws in list(wss.widgets)[:40]]
            base["widget_state_count"] = len(list(wss.widgets))
            base["widget_states"] = rows
            base["widget_state_ids"] = [str(r.get("id") or "") for r in rows if r.get("id")]
    elif which == "app_heartbeat":
        base["backmsg_fields"] = ["app_heartbeat"]
    elif which == "backend_operation_request":
        base["backmsg_fields"] = ["backend_operation_request"]
        bor = msg.backend_operation_request
        base["backend_operation_request"] = {
            "request_id_prefix": str(getattr(bor, "request_id", "") or "")[:16],
            "session_id_prefix": str(getattr(bor, "session_id", "") or "")[:16],
        }
    else:
        base["backmsg_fields"] = [which] if which else []

    return base


def _client_state_summary(cs: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["page_script_hash"] = str(getattr(cs, "page_script_hash", "") or "")[:64]
        out["page_name"] = str(getattr(cs, "page_name", "") or "")[:80]
        out["fragment_id"] = str(getattr(cs, "fragment_id", "") or "")[:80]
        out["query_string_preview"] = str(getattr(cs, "query_string", "") or "")[:200]
        out["is_auto_rerun"] = bool(getattr(cs, "is_auto_rerun", False))
    except Exception:
        pass
    return out


def try_parse_forwardmsg(data: bytes) -> dict[str, Any]:
    base: dict[str, Any] = {
        "byte_len": len(data),
        "sha256": _sha256(data),
        "parsed": False,
        "widget_ids_in_binary": extract_widget_ids_from_bytes(data),
    }
    try:
        from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    except ImportError:
        base["parse_error"] = "ForwardMsg_pb2_unavailable"
        return base
    msg = ForwardMsg()
    for skip in (0, 1, 2, 3):
        if skip >= len(data):
            break
        try:
            msg.ParseFromString(data[skip:])
            base["parsed"] = True
            base["parse_skip_bytes"] = skip
            base["frame_type_hint"] = "forwardmsg_protobuf"
            if msg.HasField("new_session"):
                base["category"] = "new_session"
            elif msg.HasField("script_finished"):
                base["category"] = "script_finished"
                sf = msg.script_finished
                base["script_finished"] = {
                    "page_script_hash": str(getattr(sf, "page_script_hash", "") or "")[:64],
                    "fragment_id": str(getattr(sf, "fragment_id", "") or "")[:80],
                }
            elif msg.HasField("delta"):
                base["category"] = "delta"
                delta = msg.delta
                base["delta"] = {
                    "page_script_hash": str(getattr(delta, "page_script_hash", "") or "")[:64],
                    "new_element_count": len(list(getattr(delta, "new_element", [])))
                    if hasattr(delta, "new_element")
                    else None,
                }
            elif msg.HasField("session_status_changed"):
                base["category"] = "session_status_changed"
                ssc = msg.session_status_changed
                base["session_status"] = str(getattr(ssc, "run_on_save", ""))[:40]
            elif msg.HasField("session_event"):
                base["category"] = "session_event"
            elif msg.HasField("auth_redirect"):
                base["category"] = "auth_redirect"
            else:
                base["category"] = "forwardmsg_other"
            meta = getattr(msg, "metadata", None)
            if meta is not None:
                base["metadata"] = {
                    "active_script_hash": str(getattr(meta, "active_script_hash", "") or "")[:64],
                    "is_fragment_run": bool(getattr(meta, "is_fragment_run", False)),
                }
            text = data.decode("utf-8", errors="ignore").lower()
            if "exception" in text or "error" in text:
                base["exception_or_error_hint"] = True
            return base
        except Exception:
            msg = ForwardMsg()
    base["parse_error"] = "forwardmsg_parse_failed"
    base["frame_type_hint"] = _frame_hint_from_bytes(data)
    return base


def summarize_first_meaningful_inbound(data: bytes) -> dict[str, Any]:
    """Decode inbound frame for symmetric acceptance comparison."""
    dec = classify_inbound_frame(data)
    text = data.decode("utf-8", errors="ignore")
    page_hash = ""
    for m in re.finditer(r'[\w]{32}', text):
        if len(m.group(0)) == 32:
            page_hash = m.group(0)
            break
    if dec.get("parsed") and dec.get("category"):
        kind = str(dec.get("category"))
        if kind == "delta":
            kind = "forward_delta_rerun_paint"
        elif kind == "script_finished":
            kind = "script_finished"
        elif kind == "new_session":
            kind = "session_metadata"
        dec["interpretation"] = kind
    else:
        hint = str(dec.get("frame_type_hint") or "")
        if "rerun" in hint or "rerun" in text.lower():
            dec["interpretation"] = "rerun_request_or_config_forward"
        elif dec.get("byte_len", 0) < 500 and "streamlit" in text.lower():
            dec["interpretation"] = "session_metadata"
        else:
            dec["interpretation"] = "streamlit_binary_or_other"
    if dec.get("delta", {}).get("page_script_hash"):
        page_hash = dec["delta"]["page_script_hash"]
    if dec.get("script_finished", {}).get("page_script_hash"):
        page_hash = dec["script_finished"]["page_script_hash"]
    if dec.get("metadata", {}).get("active_script_hash"):
        page_hash = page_hash or dec["metadata"]["active_script_hash"]
    dec["page_script_hash_hint"] = page_hash[:64]
    dec["fragment_id_hint"] = str(
        (dec.get("script_finished") or {}).get("fragment_id")
        or (dec.get("metadata") or {}).get("fragment_id")
        or ""
    )[:80]
    return dec


def _frame_hint_from_bytes(data: bytes) -> str:
    text = data.decode("utf-8", errors="ignore").lower()
    if "rerun" in text:
        return "rerun_hint"
    if "widget" in text or "backmsg" in text:
        return "widget_state_hint"
    if len(data) <= 8:
        return "heartbeat_or_control"
    return "streamlit_binary_or_other"


def classify_inbound_frame(data: bytes) -> dict[str, Any]:
    fwd = try_parse_forwardmsg(data)
    if fwd.get("parsed"):
        return {"direction": "inbound", **fwd}
    return {"direction": "inbound", **try_parse_backmsg(data), "inbound_fallback": True}


def compare_backmsg_summaries(control: dict[str, Any], production: dict[str, Any]) -> dict[str, Any]:
    c_fields = set(control.get("backmsg_fields") or [])
    p_fields = set(production.get("backmsg_fields") or [])
    c_ids = set(control.get("widget_state_ids") or [])
    p_ids = set(production.get("widget_state_ids") or [])
    return {
        "control_has_widget_states": bool(control.get("widget_state_count")),
        "production_has_widget_states": bool(production.get("widget_state_count")),
        "control_has_rerun_script": "rerun_script" in c_fields or control.get("backmsg_oneof_type") == "rerun_script",
        "production_has_rerun_script": "rerun_script" in p_fields or production.get("backmsg_oneof_type") == "rerun_script",
        "field_set_symmetric_difference": sorted(c_fields ^ p_fields),
        "widget_state_id_overlap": sorted(c_ids & p_ids),
        "production_only_widget_state_ids": sorted(p_ids - c_ids),
        "control_only_widget_state_ids": sorted(c_ids - p_ids),
        "structures_match": c_fields == p_fields and bool(c_fields),
    }
