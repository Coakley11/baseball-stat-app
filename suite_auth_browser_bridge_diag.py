"""Non-secret Supabase browser-auth bridge diagnostics (ledger + probes).

Intended bridge semantics (durability contract):
- Reusable across multiple independent browser/Streamlit contexts that share ``suite_sid``.
- Bound to opaque ``item_key`` (= suite_sid), not a single Streamlit session id.
- Not consume-on-read: lookup and readback are side-effect free.
- Invalidated only by explicit sign-out, confirmed token rejection, security mismatch,
  or configured TTL expiration — not by transient restore/hydration failure.
- ``expires_at`` in payload is advisory; row ``valid`` flag is authoritative until TTL enforcement.
"""

from __future__ import annotations

import hashlib
from typing import Any

_AUTH_BROWSER_APP = "_auth_browser"
_AUTH_SESSION_ITEM_TYPE = "browser_session"


def supabase_environment_fingerprint() -> dict[str, Any]:
    try:
        from suite_storage_config import get_cloud_config, probe_secrets

        cfg = get_cloud_config()
        probe = probe_secrets()
    except Exception as exc:
        return {"configured": False, "error": type(exc).__name__}
    if cfg is None:
        return {
            "configured": False,
            "resolved_source": getattr(probe, "resolved_source", "") or "none",
        }
    url = str(cfg.url or "")
    ref = ""
    if "://" in url:
        ref = url.split("://", 1)[-1].split(".")[0]
    key = str(cfg.key or "")
    return {
        "configured": True,
        "table": "suite_saved_items",
        "project_ref_prefix": ref[:12],
        "url_fingerprint": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
        "credential_fingerprint": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "resolved_source": getattr(probe, "resolved_source", "") or "",
        "conflict_key": "user_id,app,item_type,item_key",
        "lookup_app": _AUTH_BROWSER_APP,
        "lookup_item_type": _AUTH_SESSION_ITEM_TYPE,
    }


def _stable_hash(value: str, *, nbytes: int = 8) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[: nbytes * 2]


def _deployment_sha() -> str:
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:7]
    except Exception:
        return ""


def _session_diag_ids(session_state: dict[str, Any] | None, st: Any | None) -> dict[str, str]:
    out = {"streamlit_session_id": "", "diagnostic_run_id": ""}
    try:
        from live_draft_auth_prestart_stage1_diag import _streamlit_session_id, ensure_stage1_run_id

        out["streamlit_session_id"] = str(_streamlit_session_id() or "")[:64]
        if session_state is not None:
            out["diagnostic_run_id"] = str(ensure_stage1_run_id(session_state) or "")[:64]
    except Exception:
        pass
    return out


def _env_fingerprint_match(current: dict[str, Any], stored: dict[str, Any] | None) -> str:
    if not stored:
        return "not_compared"
    cur_url = str(current.get("url_fingerprint") or "")
    st_url = str(stored.get("url_fingerprint") or "")
    if not cur_url or not st_url:
        return "incomplete"
    return "match" if cur_url == st_url else "mismatch"


def _payload_token_flags(payload: Any) -> dict[str, bool]:
    if not isinstance(payload, dict):
        return {"access_token_present": False, "refresh_token_present": False}
    return {
        "access_token_present": bool(str(payload.get("access_token") or "").strip()),
        "refresh_token_present": bool(str(payload.get("refresh_token") or "").strip()),
    }


def probe_browser_auth_storage(
    session_id: str,
    *,
    expected_user_id: str = "",
    use_cache: bool = False,
) -> dict[str, Any]:
    """Production-parity lookup diagnostics (no token values)."""
    from suite_storage_supabase import _TABLE_SAVED, _request

    sid = str(session_id or "").strip()
    out: dict[str, Any] = {
        "suite_sid_prefix": sid[:8] if sid else "",
        "environment": supabase_environment_fingerprint(),
        "cache_enabled": bool(use_cache),
        "production_query_row_count": 0,
        "production_row_found": False,
        "production_row_valid": False,
        "production_record_complete": False,
        "row_id": "",
        "owner_id_prefix": "",
        "owner_match": None,
        "updated_at": "",
        "expires_at": 0,
        "invalid_rows_for_key": 0,
        "wrong_app_rows": 0,
        "query_exception": "",
        "rejection_reason": "",
    }
    if not sid:
        out["rejection_reason"] = "suite_sid_missing"
        return out
    prod_params = {
        "select": "id,user_id,app,item_type,item_key,valid,updated_at,payload",
        "app": f"eq.{_AUTH_BROWSER_APP}",
        "item_type": f"eq.{_AUTH_SESSION_ITEM_TYPE}",
        "item_key": f"eq.{sid}",
        "valid": "eq.true",
        "limit": "1",
    }
    try:
        rows = _request(
            "GET",
            _TABLE_SAVED,
            params=prod_params,
            prefer="return=representation",
            use_cache=use_cache,
        )
    except Exception as exc:
        out["query_exception"] = type(exc).__name__
        out["rejection_reason"] = "query_exception"
        return out
    if isinstance(rows, list):
        out["production_query_row_count"] = len(rows)
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        row = rows[0]
        out["production_row_found"] = True
        out["production_row_valid"] = bool(row.get("valid"))
        out["row_id"] = str(row.get("id") or "")[:64]
        uid = str(row.get("user_id") or "")
        out["owner_id_prefix"] = uid[:8] if uid else ""
        exp_uid = str(expected_user_id or "").strip()
        if exp_uid and uid:
            out["owner_match"] = uid == exp_uid
        flags = _payload_token_flags(row.get("payload"))
        out.update(flags)
        out["production_record_complete"] = bool(
            flags["access_token_present"] and flags["refresh_token_present"]
        )
        out["updated_at"] = str(row.get("updated_at") or "")[:32]
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        out["expires_at"] = int(payload.get("expires_at") or 0)
        out["rejection_reason"] = "" if out["production_record_complete"] else "token_record_incomplete"
    else:
        out["rejection_reason"] = "token_record_missing"
    try:
        invalid = _request(
            "GET",
            _TABLE_SAVED,
            params={
                "select": "id,valid,app",
                "item_type": f"eq.{_AUTH_SESSION_ITEM_TYPE}",
                "item_key": f"eq.{sid}",
                "valid": "eq.false",
                "limit": "5",
            },
            prefer="return=representation",
            use_cache=False,
        )
        if isinstance(invalid, list):
            out["invalid_rows_for_key"] = len(invalid)
            if invalid and not out["production_row_found"]:
                out["rejection_reason"] = "record_invalidated"
    except Exception:
        pass
    return out


def readback_after_browser_auth_save(
    session_id: str,
    *,
    expected_user_id: str = "",
    save_reported_success: bool = True,
) -> dict[str, Any]:
    probe = probe_browser_auth_storage(session_id, expected_user_id=expected_user_id, use_cache=False)
    return {
        "save_reported_success": bool(save_reported_success),
        "readback_attempted": True,
        "readback_row_found": bool(probe.get("production_row_found")),
        "readback_record_complete": bool(probe.get("production_record_complete")),
        "matching_row_id": str(probe.get("row_id") or "")[:64],
        "suite_sid_prefix_match": True,
        "owner_match": probe.get("owner_match"),
        "environment": probe.get("environment"),
        "expiration_state": probe.get("expires_at") or 0,
        "failure_reason": probe.get("rejection_reason") or ("ok" if probe.get("production_record_complete") else "readback_incomplete"),
        **{k: probe.get(k) for k in ("owner_id_prefix", "updated_at", "invalid_rows_for_key", "query_exception")},
    }


def emit_bridge_storage_checkpoint(
    session_state: dict[str, Any],
    checkpoint: str,
    *,
    st: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

        emit_prestart_hydration_checkpoint(
            session_state,
            str(checkpoint or "")[:80],
            st=st,
            extra=extra or {},
        )
    except Exception:
        pass


def emit_bridge_mutation(
    session_state: dict[str, Any],
    *,
    operation: str,
    sid: str,
    reason: str = "",
    prior_row_id: str = "",
    resulting_row_id: str = "",
    prior_valid: bool | None = None,
    new_valid: bool | None = None,
    mutation_type: str = "",
    invalidation_reason: str = "",
    caller: str = "",
    auth_user_id: str = "",
    token_flags: dict[str, bool] | None = None,
    expires_at_present: bool | None = None,
    environment_fingerprint_result: str = "",
    st: Any | None = None,
) -> None:
    import time

    env = supabase_environment_fingerprint()
    ids = _session_diag_ids(session_state, st)
    uid = str(auth_user_id or "").strip()
    if not uid:
        try:
            uid = str(session_state.get("_suite_auth_user_id") or "").strip()
        except Exception:
            uid = ""
    flags = token_flags or {}
    emit_bridge_storage_checkpoint(
        session_state,
        "browser_auth_bridge_mutation",
        st=st,
        extra={
            "mutation_type": str(mutation_type or operation or "")[:40],
            "operation": str(operation or "")[:40],
            "suite_sid_prefix": sid[:8] if sid else "",
            "item_key_hash": _stable_hash(sid),
            "row_id_prefix": str(prior_row_id or resulting_row_id or "")[:8],
            "prior_row_id": str(prior_row_id or "")[:64],
            "resulting_row_id": str(resulting_row_id or "")[:64],
            "auth_user_id_present": bool(uid),
            "auth_user_id_hash": _stable_hash(uid),
            "prior_valid": prior_valid,
            "new_valid": new_valid,
            "reason": str(reason or "")[:120],
            "invalidation_reason": str(invalidation_reason or reason or "")[:120],
            "caller": str(caller or "")[:80],
            "streamlit_session_id": ids.get("streamlit_session_id", ""),
            "diagnostic_run_id": ids.get("diagnostic_run_id", ""),
            "deployment_sha": _deployment_sha(),
            "mutation_ts": time.time(),
            "access_token_present": bool(flags.get("access_token_present")),
            "refresh_token_present": bool(flags.get("refresh_token_present")),
            "expires_at_present": expires_at_present,
            "environment_fingerprint_result": str(environment_fingerprint_result or "")[:32],
            "environment": env,
        },
    )
