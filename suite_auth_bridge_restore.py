"""Single-flight bridge restore, rotation-safe persistence, AUTH_HYDRATE3B handling."""

from __future__ import annotations

import time
import uuid
from typing import Any

from suite_auth_bridge_token_meta import REFRESH_FP_KEY, bridge_payload_meta, token_fingerprint

RESTORE_INFLIGHT_KEY = "_suite_auth_bridge_restore_inflight"
RESTORE_FINAL_3B_KEY = "_suite_auth_bridge_restore_final_3b"
RESTORE_APPLIED_GEN_KEY = "_suite_auth_bridge_applied_generation"
RESTORE_LOADED_GEN_KEY = "_suite_auth_bridge_loaded_generation"
RESTORE_LOADED_REFRESH_FP_KEY = "_suite_auth_bridge_loaded_refresh_fp"
RESTORE_RETRY_ONCE_KEY = "_suite_auth_bridge_restore_retry_once_used"

INFLIGHT_TTL_S = 45.0


def _streamlit_session_id(st: Any | None) -> str:
    try:
        from live_draft_auth_prestart_stage1_diag import _streamlit_session_id as _sid

        return str(_sid() or "")[:64]
    except Exception:
        return ""


def _restore_run_id(session_state: dict[str, Any]) -> str:
    try:
        from live_draft_auth_prestart_stage1_diag import ensure_stage1_run_id

        return str(ensure_stage1_run_id(session_state) or "")[:64]
    except Exception:
        return ""


def _emit_restore_diag(
    session_state: dict[str, Any],
    checkpoint: str,
    *,
    st: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

        emit_prestart_hydration_checkpoint(session_state, checkpoint, st=st, extra=extra or {})
    except ImportError:
        pass


def _is_refresh_already_used(exc: BaseException) -> bool:
    code = str(getattr(exc, "code", "") or "").strip().lower()
    if code == "refresh_token_already_used":
        return True
    msg = str(exc).lower()
    return "refresh_token_already_used" in msg or "already used" in msg


def _clear_inflight(session_state: dict[str, Any], *, reason: str) -> None:
    inflight = session_state.pop(RESTORE_INFLIGHT_KEY, None)
    if inflight:
        _emit_restore_diag(
            session_state,
            "bridge_restore_single_flight_release",
            extra={
                "single_flight_owner": str(inflight.get("owner") or "")[:64],
                "restore_attempt_id": str(inflight.get("attempt_id") or "")[:64],
                "release_reason": str(reason or "")[:80],
            },
        )


def _acquire_single_flight(session_state: dict[str, Any], *, st: Any | None) -> tuple[bool, str]:
    now = time.time()
    inflight = session_state.get(RESTORE_INFLIGHT_KEY)
    if isinstance(inflight, dict):
        started = float(inflight.get("started_ts") or 0)
        if now - started < INFLIGHT_TTL_S:
            _emit_restore_diag(
                session_state,
                "bridge_restore_single_flight_skip",
                st=st,
                extra={
                    "single_flight_owner": str(inflight.get("owner") or "")[:64],
                    "restore_attempt_id": str(inflight.get("attempt_id") or "")[:64],
                    "waiting_skipped_attempt": True,
                    "skip_reason": "restore_in_progress",
                },
            )
            return False, "restore_single_flight_in_progress"
        session_state.pop(RESTORE_INFLIGHT_KEY, None)
    attempt_id = str(uuid.uuid4())[:36]
    owner = _streamlit_session_id(st) or _restore_run_id(session_state) or attempt_id
    session_state[RESTORE_INFLIGHT_KEY] = {
        "owner": owner,
        "attempt_id": attempt_id,
        "started_ts": now,
        "restore_generation": int(session_state.get(RESTORE_LOADED_GEN_KEY) or 0),
    }
    _emit_restore_diag(
        session_state,
        "bridge_restore_single_flight_acquire",
        st=st,
        extra={
            "single_flight_owner": owner[:64],
            "restore_attempt_id": attempt_id,
            "restore_generation": int(session_state.get(RESTORE_LOADED_GEN_KEY) or 0),
        },
    )
    return True, ""


def load_bridge_tokens_with_meta(st: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return _load_bridge_tokens_with_meta(st)


def _load_bridge_tokens_with_meta(st: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    from suite_auth_browser import sync_suite_sid_from_query

    sid = sync_suite_sid_from_query(st)
    if not sid:
        return None, {}
    try:
        from suite_storage_supabase import load_browser_auth_session_record

        rec = load_browser_auth_session_record(sid)
    except (ImportError, RuntimeError):
        try:
            from suite_storage_supabase import load_browser_auth_session

            tokens = load_browser_auth_session(sid)
        except (ImportError, RuntimeError):
            tokens = None
        if not tokens:
            return None, {}
        meta = {
            "token_generation": 0,
            "refresh_fp": token_fingerprint(str(tokens.get("refresh_token") or "")),
        }
        return tokens, meta
    if not rec:
        return None, {}
    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    meta = bridge_payload_meta(payload)
    meta["row_id_prefix"] = str(rec.get("row_id") or "")[:8]
    tokens = {
        "access_token": str(payload.get("access_token") or "").strip(),
        "refresh_token": str(payload.get("refresh_token") or "").strip(),
        "expires_at": int(payload.get("expires_at") or 0),
    }
    if not tokens["access_token"] or not tokens["refresh_token"]:
        return None, meta
    return tokens, meta


def _persist_rotated_tokens_immediately(
    st: Any,
    session_state: dict[str, Any],
    tokens: dict[str, Any],
    *,
    expected_generation: int,
    auth_user_id: str,
) -> dict[str, Any]:
    uid = str(auth_user_id or session_state.get("_suite_auth_user_id") or "").strip()
    from suite_auth_browser import sync_suite_sid_from_query

    sid = sync_suite_sid_from_query(st)
    out: dict[str, Any] = {
        "persistence_attempted": True,
        "expected_generation": int(expected_generation),
    }
    if not sid or not uid:
        out["failure_reason"] = "sid_or_user_missing"
        return out
    try:
        from suite_storage_supabase import save_browser_auth_session_versioned

        write = save_browser_auth_session_versioned(
            sid,
            user_id=uid,
            tokens=tokens,
            expected_generation=expected_generation,
        )
        out.update(
            {
                k: write.get(k)
                for k in (
                    "write_committed",
                    "write_mode",
                    "token_generation",
                    "prior_generation",
                    "stale_generation_rejected",
                    "refresh_fp",
                    "row_id_prefix",
                )
            }
        )
        if write.get("write_committed"):
            session_state[RESTORE_APPLIED_GEN_KEY] = int(write.get("token_generation") or 0)
            session_state[RESTORE_LOADED_GEN_KEY] = int(write.get("token_generation") or 0)
            session_state[RESTORE_LOADED_REFRESH_FP_KEY] = str(write.get("refresh_fp") or "")
            try:
                from suite_auth_browser_bridge_diag import readback_after_browser_auth_save

                rb = readback_after_browser_auth_save(
                    sid,
                    expected_user_id=uid,
                    save_reported_success=True,
                )
                out["readback_row_id_prefix"] = str(rb.get("matching_row_id") or "")[:8]
                out["readback_generation"] = int(
                    (rb.get("payload_meta") or {}).get("token_generation") or write.get("token_generation") or 0
                )
            except Exception:
                pass
    except Exception as exc:
        out["failure_reason"] = f"save_error:{type(exc).__name__}"
    _emit_restore_diag(
        session_state,
        "bridge_restore_rotation_persist",
        st=st,
        extra={
            "expected_generation": int(expected_generation),
            "result_generation": int(out.get("token_generation") or 0),
            "prior_generation": int(out.get("prior_generation") or 0),
            "write_committed": bool(out.get("write_committed")),
            "stale_generation_rejected": bool(out.get("stale_generation_rejected")),
            "refresh_fp_prefix": str(out.get("refresh_fp") or "")[:16],
        },
    )
    return out


def execute_bridge_set_session_restore(
    session_state: dict[str, Any],
    *,
    st: Any | None,
    tokens: dict[str, Any],
    token_meta: dict[str, Any],
    auth_before: bool,
    finish,
) -> bool | None:
    """
    Run set_session + immediate rotation persist + apply.
    Returns True/False when handled, None when caller should fall through.
    """
    if st is None:
        return None
    if session_state.get(RESTORE_FINAL_3B_KEY):
        return finish(False, "auth_hydrate_3b_final")

    try:
        from suite_auth_bridge_handoff import is_handoff_frozen

        if is_handoff_frozen(session_state):
            # Capture FINAL_HANDOFF already sealed the unused refresh for production.
            # Do not set_session (would consume it) and do not mark a violation — freeze is intentional.
            return finish(False, "handoff_frozen_no_set_session")
    except ImportError:
        pass

    loaded_gen = int(token_meta.get("token_generation") or 0)
    loaded_fp = str(token_meta.get("refresh_fp") or token_fingerprint(str(tokens.get("refresh_token") or "")))
    session_state[RESTORE_LOADED_GEN_KEY] = loaded_gen
    session_state[RESTORE_LOADED_REFRESH_FP_KEY] = loaded_fp

    applied_gen = int(session_state.get(RESTORE_APPLIED_GEN_KEY) or 0)
    if applied_gen >= loaded_gen and applied_gen > 0:
        try:
            from suite_auth import auth_session_complete

            if auth_session_complete(session_state):
                _emit_restore_diag(
                    session_state,
                    "bridge_restore_single_flight_skip",
                    st=st,
                    extra={
                        "skip_reason": "already_applied_generation",
                        "applied_generation": applied_gen,
                        "loaded_generation": loaded_gen,
                        "successful_owner": _streamlit_session_id(st)[:64],
                    },
                )
                return finish(True, "already_applied_generation")
        except ImportError:
            pass

    acquired, skip_reason = _acquire_single_flight(session_state, st=st)
    if not acquired:
        return finish(False, skip_reason)

    try:
        from suite_auth import (
            _apply_authenticated_user,
            _auth_api,
            _tokens_from_auth_response,
            _user_from_auth_response,
            _user_from_obj,
            auth_session_complete,
        )

        auth = _auth_api(session_state)
        resp = auth.set_session(str(tokens["access_token"]), str(tokens["refresh_token"]))
        user = _user_from_auth_response(resp)
        if user is None:
            user_resp = auth.get_user()
            user = _user_from_obj(getattr(user_resp, "user", None))
        if user is None:
            from suite_auth import _clear_auth_session

            _clear_auth_session(session_state, st=st, invalidate_bridge=False)
            return finish(False, "user_missing")
        auth_user_id = str(getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else "") or "")
        refreshed = _tokens_from_auth_response(resp)
        if refreshed:
            tokens = refreshed
        from suite_auth import AUTH_TOKENS_KEY

        session_state[AUTH_TOKENS_KEY] = dict(tokens)
        persist = _persist_rotated_tokens_immediately(
            st,
            session_state,
            tokens,
            expected_generation=loaded_gen,
            auth_user_id=auth_user_id,
        )
        if not persist.get("write_committed"):
            pass  # local session still holds rotated tokens; bridge may catch up on next save
        _apply_authenticated_user(session_state, user, tokens=tokens, st=st)
        _clear_inflight(session_state, reason="restore_ok")
        return finish(True, "ok")
    except Exception as exc:
        from suite_auth import AUTH_LAST_RESTORE_ERROR_KEY, _clear_auth_session

        session_state[AUTH_LAST_RESTORE_ERROR_KEY] = str(exc)
        try:
            from suite_auth_restore_diag import emit_restore_auth_exception_checkpoint

            emit_restore_auth_exception_checkpoint(session_state, exc, phase="set_session", st=st)
        except ImportError:
            pass
        _clear_inflight(session_state, reason="restore_exception")
        if _is_refresh_already_used(exc):
            return _handle_refresh_already_used(
                session_state,
                st=st,
                auth_before=auth_before,
                finish=finish,
                prior_generation=loaded_gen,
                prior_refresh_fp=loaded_fp,
            )
        _clear_auth_session(session_state, st=st, invalidate_bridge=False)
        return finish(False, f"exception:{type(exc).__name__}")


def _handle_refresh_already_used(
    session_state: dict[str, Any],
    *,
    st: Any,
    auth_before: bool,
    finish,
    prior_generation: int,
    prior_refresh_fp: str,
) -> bool:
    from suite_auth import _clear_auth_session

    _clear_auth_session(session_state, st=st, invalidate_bridge=False)
    if session_state.get(RESTORE_RETRY_ONCE_KEY):
        session_state[RESTORE_FINAL_3B_KEY] = True
        _emit_restore_diag(
            session_state,
            "bridge_restore_3b_final",
            st=st,
            extra={
                "auth_hydrate_3b": True,
                "recovery_attempted": True,
                "recovery_succeeded": False,
                "prior_generation": prior_generation,
            },
        )
        return finish(False, "auth_hydrate_3b_final")
    tokens, meta = _load_bridge_tokens_with_meta(st)
    new_gen = int(meta.get("token_generation") or 0)
    new_fp = str(meta.get("refresh_fp") or "")
    if tokens and (new_gen > prior_generation or (new_fp and new_fp != prior_refresh_fp)):
        session_state[RESTORE_RETRY_ONCE_KEY] = True
        _emit_restore_diag(
            session_state,
            "bridge_restore_3b_recovery_retry",
            st=st,
            extra={
                "prior_generation": prior_generation,
                "new_generation": new_gen,
                "prior_refresh_fp_prefix": prior_refresh_fp[:16],
                "new_refresh_fp_prefix": new_fp[:16],
            },
        )
        from suite_auth import AUTH_TOKENS_KEY

        session_state[AUTH_TOKENS_KEY] = dict(tokens)
        return execute_bridge_set_session_restore(
            session_state,
            st=st,
            tokens=tokens,
            token_meta=meta,
            auth_before=auth_before,
            finish=finish,
        )
    session_state[RESTORE_FINAL_3B_KEY] = True
    _emit_restore_diag(
        session_state,
        "bridge_restore_3b_final",
        st=st,
        extra={
            "auth_hydrate_3b": True,
            "recovery_attempted": False,
            "prior_generation": prior_generation,
            "bridge_generation_unchanged": new_gen,
        },
    )
    return finish(False, "auth_hydrate_3b_final")
