"""Redact secrets from Solo diagnostic JSON before writing artifacts."""

from __future__ import annotations

import copy
import re
from typing import Any

_REDACT_KEY = re.compile(
    r"(password|token|cookie|secret|credential|authorization|refresh|access_token|"
    r"storage_state|local_storage|session_storage|auth_email|user_email|email)",
    re.I,
)

_BOUNDARY_FIELDS = (
    "checkpoint",
    "ts",
    "streamlit_session_id",
    "script_run",
    "live_draft_room_present",
    "live_draft_room_id",
    "live_draft_room_status",
    "live_draft_state_room_id",
    "live_draft_state_status",
    "page_filter_room_id",
    "page_filter_room_status",
    "post_create_open",
    "auth_enabled",
    "authenticated",
    "auth_user_id_prefix",
    "suite_workspace_id",
    "session_key_set_hash",
    "session_key_count",
    "session_mapping_id",
    "session_state_proxy_id",
    "runtime_session_state_id",
    "prior_run_end_hint",
    "warm_startup_skipped",
    "restore_blocked_reason",
    "active_page",
    "seq",
    "source",
    "bridge_st_stop_expected",
)


def _redact_value(key: str, val: Any) -> Any:
    if _REDACT_KEY.search(key):
        if val is None or val == "":
            return val
        return "[redacted]"
    return val


def sanitize_obj(obj: Any, *, depth: int = 0) -> Any:
    if depth > 32:
        return "[truncated]"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            sk = str(k)
            if sk in ("provenance_b64", "paired_transition_b64", "key_ownership_b64"):
                out[sk] = "[omitted_b64]"
                continue
            if sk in ("token_provenance",) and isinstance(v, list):
                out[sk] = [sanitize_obj(x, depth=depth + 1) for x in v[:20]]
                continue
            out[sk] = sanitize_obj(_redact_value(sk, v), depth=depth + 1)
        return out
    if isinstance(obj, list):
        return [sanitize_obj(x, depth=depth + 1) for x in obj[:500]]
    if isinstance(obj, str) and len(obj) > 4000 and "eyJ" in obj[:20]:
        return "[redacted_jwt_like]"
    return obj


def slim_checkpoint(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    out = {k: row.get(k) for k in _BOUNDARY_FIELDS if k in row}
    pf = row.get("anchor_keys_present")
    if isinstance(pf, dict):
        out["anchor_keys_present"] = pf
    hint = row.get("prior_run_end_hint")
    if isinstance(hint, dict):
        out["prior_run_end_hint"] = {
            "reason": hint.get("reason"),
            "detail": hint.get("detail"),
            "script_run": hint.get("script_run"),
        }
    auth = {
        "auth_enabled": row.get("auth_enabled"),
        "authenticated": row.get("authenticated"),
        "suite_workspace_id": row.get("suite_workspace_id"),
    }
    if any(v is not None for v in auth.values()):
        out["auth"] = auth
    return out


def boundary_from_a0(a0: dict[str, Any]) -> dict[str, Any]:
    pt = a0.get("paired_transition_analysis") or {}
    if not isinstance(pt, dict):
        pt = {}
    if not pt and isinstance(a0.get("paired_transition"), dict):
        pt = a0["paired_transition"].get("paired_transition") or {}
    last = slim_checkpoint(pt.get("last_present") if isinstance(pt, dict) else None)
    first = slim_checkpoint(pt.get("first_absent") if isinstance(pt, dict) else None)
    if not last or not first:
        ko = a0.get("key_ownership") if isinstance(a0.get("key_ownership"), dict) else {}
        rbl = ko.get("run_boundary_loss") if isinstance(ko, dict) else {}
        if isinstance(rbl, dict):
            lp = rbl.get("last_present_run_end") or {}
            fa = rbl.get("first_absent_script_begin") or {}
            if lp and not last:
                last = slim_checkpoint(
                    {
                        "checkpoint": lp.get("source") or "bridge_ldr_entry_end",
                        "streamlit_session_id": lp.get("streamlit_session_id"),
                        "script_run": lp.get("script_run"),
                        "live_draft_room_present": lp.get("live_draft_room_present"),
                        "live_draft_room_id": lp.get("live_draft_room_id"),
                        "live_draft_room_status": lp.get("live_draft_room_status"),
                        "live_draft_state_room_id": lp.get("live_draft_state_room_id"),
                        "live_draft_state_status": lp.get("live_draft_state_status"),
                        "page_filter_room_id": lp.get("page_filter_room_id"),
                        "page_filter_room_status": lp.get("page_filter_room_status"),
                        "post_create_open": lp.get("post_create_open"),
                        "auth_enabled": lp.get("auth_enabled"),
                        "authenticated": lp.get("authenticated"),
                        "active_page": lp.get("active_page"),
                        "seq": lp.get("seq"),
                        "source": lp.get("source"),
                    }
                )
            if fa and not first:
                first = slim_checkpoint(
                    {
                        "checkpoint": fa.get("checkpoint") or "script_beginning",
                        "streamlit_session_id": fa.get("streamlit_session_id"),
                        "script_run": fa.get("script_run"),
                        "live_draft_room_present": fa.get("live_draft_room_present"),
                        "live_draft_room_id": fa.get("live_draft_room_id"),
                        "live_draft_room_status": fa.get("live_draft_room_status"),
                        "live_draft_state_room_id": fa.get("live_draft_state_room_id"),
                        "live_draft_state_status": fa.get("live_draft_state_status"),
                        "page_filter_room_id": fa.get("page_filter_room_id"),
                        "page_filter_room_status": fa.get("page_filter_room_status"),
                        "post_create_open": fa.get("post_create_open"),
                        "auth_enabled": fa.get("auth_enabled"),
                        "authenticated": fa.get("authenticated"),
                        "active_page": fa.get("active_page"),
                        "seq": fa.get("seq"),
                    }
                )
    ka = pt.get("key_analysis") if isinstance(pt, dict) else {}
    if not isinstance(ka, dict):
        ka = {}
    return {
        "last_present": last,
        "first_absent": first,
        "first_absent_ultra_early": _find_checkpoint(a0, "ultra_early_post_page_config", after_seq=last.get("seq")),
        "key_analysis": {
            "only_live_draft_room_runtime_lost": ka.get("only_live_draft_room_runtime_lost"),
            "broad_session_replacement_suspected": ka.get("broad_session_replacement_suspected"),
            "key_set_hash_changed": ka.get("key_set_hash_changed"),
            "key_count_delta": ka.get("key_count_delta"),
            "session_mapping_id_same": ka.get("session_mapping_id_same"),
            "runtime_session_state_id_same": ka.get("runtime_session_state_id_same"),
        },
        "restore_blocked_reason_at_loss": first.get("restore_blocked_reason") or last.get("restore_blocked_reason"),
    }


def _find_checkpoint(a0: dict[str, Any], name: str, *, after_seq: Any) -> dict[str, Any]:
    pt = a0.get("paired_transition")
    if not isinstance(pt, dict):
        return {}
    rows = pt.get("rows") or []
    if not isinstance(rows, list):
        return {}
    try:
        min_seq = int(after_seq or 0)
    except (TypeError, ValueError):
        min_seq = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("checkpoint") or "") != name:
            continue
        if int(row.get("seq") or 0) <= min_seq:
            continue
        return slim_checkpoint(row)
    return {}
