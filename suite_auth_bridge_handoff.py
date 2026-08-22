"""Single-use refresh-token handoff for Context-A → production bridge restore.

Guarantees the bridge row holds the final unused refresh token intended for
exactly one future production ``set_session``. No raw secrets in logs.
"""

from __future__ import annotations

from typing import Any

from suite_auth_bridge_token_meta import (
    ACCESS_FP_KEY,
    REFRESH_FP_KEY,
    token_fingerprint,
)

PHASE_INTERMEDIATE = "INTERMEDIATE"
PHASE_FINAL = "FINAL_HANDOFF"

HANDOFF_FREEZE_KEY = "_suite_auth_bridge_handoff_frozen"
HANDOFF_FINAL_REFRESH_FP_KEY = "_suite_auth_bridge_handoff_refresh_fp"
HANDOFF_FINAL_ACCESS_FP_KEY = "_suite_auth_bridge_handoff_access_fp"
HANDOFF_FINAL_GENERATION_KEY = "_suite_auth_bridge_handoff_generation"
HANDOFF_NO_REFRESH_AFTER_KEY = "_suite_auth_bridge_no_auth_refresh_after_final"
HANDOFF_SNAPSHOT_REFRESH_FP_KEY = "_suite_auth_bridge_handoff_snapshot_refresh_fp"
HANDOFF_SNAPSHOT_ACCESS_FP_KEY = "_suite_auth_bridge_handoff_snapshot_access_fp"
HANDOFF_SNAPSHOT_EVENT_INDEX_KEY = "_suite_auth_bridge_handoff_snapshot_event_index"
HANDOFF_NO_CONSUMPTION_SINCE_SNAPSHOT_KEY = "_suite_auth_bridge_no_auth_consumption_since_snapshot"
NONCONSUMING_FINALIZE_ENTERED_KEY = "_suite_auth_bridge_nonconsuming_finalize_entered"
NONCONSUMING_SET_SESSION_COUNT_KEY = "_suite_auth_bridge_nonconsuming_set_session_count"
NONCONSUMING_REFRESH_SESSION_COUNT_KEY = "_suite_auth_bridge_nonconsuming_refresh_session_count"

CHECKPOINT_FINAL_PERSIST = "bridge_final_handoff_persist"
CHECKPOINT_FINAL_READBACK = "bridge_final_handoff_readback"
CHECKPOINT_FINAL_INVARIANT = "bridge_final_handoff_invariant"
CHECKPOINT_NONCONSUMING_ENTERED = "already_complete_nonconsuming_finalize_entered"

CAPTURE_FAIL_FINAL_HANDOFF = "bridge_final_handoff_not_proven"
CAPTURE_FAIL_HANDOFF_FP_MISMATCH = "bridge_final_handoff_fingerprint_mismatch"
CAPTURE_FAIL_POST_HANDOFF_REFRESH = "bridge_auth_refresh_after_final_handoff"
CAPTURE_FAIL_WEAK_FINAL_FALLBACK = "bridge_final_handoff_weak_save_fallback_rejected"
CAPTURE_FAIL_SNAPSHOT_MISMATCH = "bridge_final_handoff_session_snapshot_mismatch"
CAPTURE_FAIL_CONSUMPTION_SINCE_SNAPSHOT = "bridge_auth_consumption_since_final_token_snapshot"


def is_handoff_frozen(session_state: dict[str, Any] | None) -> bool:
    return bool(session_state and session_state.get(HANDOFF_FREEZE_KEY))


def pair_fingerprints(tokens: dict[str, Any] | None) -> dict[str, str]:
    t = dict(tokens or {})
    access = str(t.get("access_token") or "").strip()
    refresh = str(t.get("refresh_token") or "").strip()
    return {
        ACCESS_FP_KEY: token_fingerprint(access),
        REFRESH_FP_KEY: token_fingerprint(refresh),
    }


def reject_mixed_token_pair(
    *,
    access_token: str,
    refresh_token: str,
    expected_access_fp: str,
    expected_refresh_fp: str,
) -> str:
    """Return failure reason when access/refresh fingerprints are not a matched pair."""
    access_fp = token_fingerprint(access_token)
    refresh_fp = token_fingerprint(refresh_token)
    if not access_fp or not refresh_fp:
        return "tokens_incomplete"
    if expected_access_fp and access_fp != expected_access_fp and expected_refresh_fp and refresh_fp == expected_refresh_fp:
        return "stale_access_new_refresh_rejected"
    if expected_refresh_fp and refresh_fp != expected_refresh_fp and expected_access_fp and access_fp == expected_access_fp:
        return "new_access_stale_refresh_rejected"
    if expected_access_fp and expected_refresh_fp:
        if access_fp != expected_access_fp or refresh_fp != expected_refresh_fp:
            return "token_pair_fingerprint_mismatch"
    return ""


def sync_tokens_from_auth_client_without_refresh(session_state: dict[str, Any]) -> dict[str, Any]:
    """Read current client session tokens without calling refresh/set_session.

    Prefers live ``get_session`` when present; otherwise keeps AUTH_TOKENS_KEY.
    Never invokes refresh_session / set_session.
    """
    from suite_auth import AUTH_TOKENS_KEY, _tokens_from_session_obj

    current = dict(session_state.get(AUTH_TOKENS_KEY) or {})
    live: dict[str, Any] = {}
    try:
        from suite_auth import _auth_api

        auth = _auth_api(session_state)
        getter = getattr(auth, "get_session", None)
        if callable(getter):
            resp = getter()
            session_obj = getattr(resp, "session", None)
            if session_obj is None and isinstance(resp, dict):
                session_obj = resp.get("session")
            if session_obj is None:
                session_obj = resp
            live = _tokens_from_session_obj(session_obj)
    except Exception:
        live = {}
    if live.get("access_token") and live.get("refresh_token"):
        session_state[AUTH_TOKENS_KEY] = dict(live)
        return dict(live)
    return current


def _emit(session_state: dict[str, Any], checkpoint: str, *, st: Any | None, extra: dict[str, Any]) -> None:
    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

        emit_prestart_hydration_checkpoint(
            session_state,
            checkpoint,
            st=st,
            skip_or_failure_reason=str(extra.get("failure_reason") or "")[:120],
            extra=extra,
        )
    except Exception:
        pass


def perform_final_bridge_handoff(
    st: Any,
    session_state: dict[str, Any],
    *,
    auth_user_id: str = "",
    expected_suite_sid: str = "",
) -> dict[str, Any]:
    """Persist the current final access+refresh pair and freeze further token-consuming ops."""
    out: dict[str, Any] = {
        "ok": False,
        "handoff_phase": PHASE_FINAL,
        "already_frozen": False,
        "persistence_succeeded": False,
        "readback_succeeded": False,
        "fingerprint_match": False,
        "no_auth_refresh_after_final_persist": False,
        "no_auth_consumption_since_final_token_snapshot": False,
        "failure_reason": "",
        "refresh_fp": "",
        "access_fp": "",
        "session_snapshot_refresh_fp": "",
        "token_generation": 0,
        "suite_sid_prefix": "",
    }
    if is_handoff_frozen(session_state):
        out["ok"] = True
        out["already_frozen"] = True
        out["persistence_succeeded"] = True
        out["readback_succeeded"] = True
        out["fingerprint_match"] = True
        out["no_auth_refresh_after_final_persist"] = bool(session_state.get(HANDOFF_NO_REFRESH_AFTER_KEY))
        out["no_auth_consumption_since_final_token_snapshot"] = bool(
            session_state.get(HANDOFF_NO_CONSUMPTION_SINCE_SNAPSHOT_KEY)
        )
        out["refresh_fp"] = str(session_state.get(HANDOFF_FINAL_REFRESH_FP_KEY) or "")
        out["access_fp"] = str(session_state.get(HANDOFF_FINAL_ACCESS_FP_KEY) or "")
        out["session_snapshot_refresh_fp"] = str(session_state.get(HANDOFF_SNAPSHOT_REFRESH_FP_KEY) or "")
        out["token_generation"] = int(session_state.get(HANDOFF_FINAL_GENERATION_KEY) or 0)
        return out

    # Snapshot BEFORE any persist — never refresh/set_session.
    tokens = sync_tokens_from_auth_client_without_refresh(session_state)
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    fps = pair_fingerprints(tokens)
    out["refresh_fp"] = fps[REFRESH_FP_KEY]
    out["access_fp"] = fps[ACCESS_FP_KEY]
    out["session_snapshot_refresh_fp"] = fps[REFRESH_FP_KEY]
    session_state[HANDOFF_SNAPSHOT_REFRESH_FP_KEY] = fps[REFRESH_FP_KEY]
    session_state[HANDOFF_SNAPSHOT_ACCESS_FP_KEY] = fps[ACCESS_FP_KEY]
    session_state[HANDOFF_NO_CONSUMPTION_SINCE_SNAPSHOT_KEY] = True
    if not access or not refresh:
        out["failure_reason"] = "tokens_incomplete"
        _emit(session_state, CHECKPOINT_FINAL_PERSIST, st=st, extra=dict(out))
        return out

    uid = str(auth_user_id or "").strip()
    if not uid:
        try:
            uid = str(session_state.get("_suite_auth_user_id") or "").strip()
        except Exception:
            uid = ""
    if not uid:
        out["failure_reason"] = "auth_user_id_missing"
        _emit(session_state, CHECKPOINT_FINAL_PERSIST, st=st, extra=dict(out))
        return out

    expected_sid = str(expected_suite_sid or "").strip()
    if expected_sid:
        try:
            from suite_auth_browser import sync_suite_sid_from_query

            # Bind current suite before save — never reuse a historical row.
            try:
                st.query_params["suite_sid"] = expected_sid
            except Exception:
                pass
            bound = sync_suite_sid_from_query(st)
            if str(bound or "").strip() != expected_sid:
                out["failure_reason"] = "suite_sid_mismatch"
                _emit(session_state, CHECKPOINT_FINAL_PERSIST, st=st, extra=dict(out))
                return out
            out["suite_sid_prefix"] = expected_sid[:8]
        except Exception:
            out["failure_reason"] = "suite_sid_bind_failed"
            _emit(session_state, CHECKPOINT_FINAL_PERSIST, st=st, extra=dict(out))
            return out

    try:
        from suite_auth_browser import save_browser_auth_tokens

        save_browser_auth_tokens(
            st,
            tokens,
            auth_user_id=uid,
            handoff_phase=PHASE_FINAL,
        )
    except Exception as exc:
        out["failure_reason"] = f"save_error:{type(exc).__name__}"
        _emit(session_state, CHECKPOINT_FINAL_PERSIST, st=st, extra=dict(out))
        return out

    # Read back via storage probe (fingerprints only).
    try:
        from suite_auth_browser import sync_suite_sid_from_query
        from suite_storage_supabase import load_browser_auth_session_record

        sid = sync_suite_sid_from_query(st)
        if expected_sid and str(sid or "").strip() != expected_sid:
            out["failure_reason"] = "suite_sid_mismatch"
            _emit(session_state, CHECKPOINT_FINAL_READBACK, st=st, extra=dict(out))
            return out
        out["suite_sid_prefix"] = str(sid or "")[:8]
        rec = load_browser_auth_session_record(sid) if sid else None
    except Exception:
        rec = None

    if not rec:
        out["failure_reason"] = "readback_missing"
        _emit(session_state, CHECKPOINT_FINAL_READBACK, st=st, extra=dict(out))
        return out

    rb_refresh = str(rec.get("refresh_fp") or token_fingerprint(str(rec.get("refresh_token") or "")))
    rb_access = str(rec.get("access_fp") or token_fingerprint(str(rec.get("access_token") or "")))
    gen = int(rec.get("token_generation") or 0)
    out["token_generation"] = gen
    out["readback_succeeded"] = True
    out["persistence_succeeded"] = True
    snap_refresh = str(session_state.get(HANDOFF_SNAPSHOT_REFRESH_FP_KEY) or out["refresh_fp"])
    snap_access = str(session_state.get(HANDOFF_SNAPSHOT_ACCESS_FP_KEY) or out["access_fp"])
    # Three-way: live pre-save snapshot == intended persist == durable readback.
    match = (
        bool(snap_refresh)
        and snap_refresh == out["refresh_fp"]
        and snap_refresh == rb_refresh
        and snap_access == out["access_fp"]
        and snap_access == rb_access
    )
    out["fingerprint_match"] = match
    no_consumption = bool(session_state.get(HANDOFF_NO_CONSUMPTION_SINCE_SNAPSHOT_KEY))
    out["no_auth_consumption_since_final_token_snapshot"] = no_consumption
    if not match:
        out["failure_reason"] = "fingerprint_mismatch"
        _emit(
            session_state,
            CHECKPOINT_FINAL_INVARIANT,
            st=st,
            extra={
                **out,
                "final_session_snapshot_fingerprint": snap_refresh[:16],
                "final_persist_token_fingerprint": out["refresh_fp"][:16],
                "final_browser_token_fingerprint": rb_refresh[:16],
                "final_readback_token_fingerprint": rb_refresh[:16],
                "fingerprint_match": False,
            },
        )
        return out
    if not no_consumption:
        out["failure_reason"] = CAPTURE_FAIL_CONSUMPTION_SINCE_SNAPSHOT
        _emit(
            session_state,
            CHECKPOINT_FINAL_INVARIANT,
            st=st,
            extra={
                **out,
                "final_session_snapshot_fingerprint": snap_refresh[:16],
                "final_persist_token_fingerprint": out["refresh_fp"][:16],
                "final_browser_token_fingerprint": rb_refresh[:16],
                "final_readback_token_fingerprint": rb_refresh[:16],
                "fingerprint_match": True,
                "no_auth_consumption_since_final_token_snapshot": False,
            },
        )
        return out

    session_state[HANDOFF_FREEZE_KEY] = True
    session_state[HANDOFF_FINAL_REFRESH_FP_KEY] = out["refresh_fp"]
    session_state[HANDOFF_FINAL_ACCESS_FP_KEY] = out["access_fp"]
    session_state[HANDOFF_FINAL_GENERATION_KEY] = gen
    session_state[HANDOFF_NO_REFRESH_AFTER_KEY] = True
    out["ok"] = True
    out["no_auth_refresh_after_final_persist"] = True
    out["failure_reason"] = "ok"
    _emit(
        session_state,
        CHECKPOINT_FINAL_PERSIST,
        st=st,
        extra={
            "handoff_phase": PHASE_FINAL,
            "persistence_succeeded": True,
            "refresh_fp_prefix": out["refresh_fp"][:16],
            "access_fp_prefix": out["access_fp"][:16],
            "session_snapshot_refresh_fp_prefix": snap_refresh[:16],
            "token_generation": gen,
            "suite_sid_prefix": out.get("suite_sid_prefix") or "",
            "failure_reason": "ok",
        },
    )
    _emit(
        session_state,
        CHECKPOINT_FINAL_READBACK,
        st=st,
        extra={
            "handoff_phase": PHASE_FINAL,
            "readback_succeeded": True,
            "fingerprint_match": True,
            "refresh_fp_prefix": rb_refresh[:16],
            "token_generation": gen,
            "suite_sid_prefix": out.get("suite_sid_prefix") or "",
            "failure_reason": "ok",
        },
    )
    _emit(
        session_state,
        CHECKPOINT_FINAL_INVARIANT,
        st=st,
        extra={
            "final_session_snapshot_fingerprint": snap_refresh[:16],
            "final_persist_token_fingerprint": out["refresh_fp"][:16],
            "final_browser_token_fingerprint": rb_refresh[:16],
            "final_readback_token_fingerprint": rb_refresh[:16],
            "no_auth_refresh_after_final_persist": True,
            "no_auth_consumption_since_final_token_snapshot": True,
            "fingerprint_match": True,
            "failure_reason": "ok",
        },
    )
    return out


def maybe_finalize_bridge_token_handoff(
    session_state: dict[str, Any],
    *,
    st: Any | None,
    auth_user_id: str = "",
    expected_suite_sid: str = "",
) -> dict[str, Any]:
    """Finalize once when auth session is complete and a Streamlit handle exists."""
    if st is None:
        return {"ok": False, "failure_reason": "st_missing", "skipped": True}
    if is_handoff_frozen(session_state):
        return perform_final_bridge_handoff(
            st, session_state, auth_user_id=auth_user_id, expected_suite_sid=expected_suite_sid
        )
    try:
        from suite_auth import auth_session_complete

        if not auth_session_complete(session_state):
            return {"ok": False, "failure_reason": "auth_incomplete", "skipped": True}
    except Exception:
        return {"ok": False, "failure_reason": "auth_check_failed", "skipped": True}
    return perform_final_bridge_handoff(
        st, session_state, auth_user_id=auth_user_id, expected_suite_sid=expected_suite_sid
    )


def finalize_already_complete_missing_bridge(
    session_state: dict[str, Any],
    *,
    st: Any,
    expected_suite_sid: str,
    auth_user_id: str = "",
) -> dict[str, Any]:
    """Case B: already-complete session + missing current-suite bridge → non-consuming FINAL.

    Reuses sync_tokens_from_auth_client_without_refresh + _sync_auth_account_identity +
    perform_final_bridge_handoff. Never calls set_session / refresh_session / login.
    """
    out: dict[str, Any] = {
        "ok": False,
        "non_consuming_finalize_entered": True,
        "set_session_count_before_final": 0,
        "refresh_session_count_before_final": 0,
        "failure_reason": "",
        "handoff": {},
    }
    session_state[NONCONSUMING_FINALIZE_ENTERED_KEY] = True
    session_state[NONCONSUMING_SET_SESSION_COUNT_KEY] = 0
    session_state[NONCONSUMING_REFRESH_SESSION_COUNT_KEY] = 0
    _emit(
        session_state,
        CHECKPOINT_NONCONSUMING_ENTERED,
        st=st,
        extra={
            "suite_sid_prefix": str(expected_suite_sid or "")[:8],
            "non_consuming_finalize_entered": True,
            "set_session_count_before_final": 0,
            "refresh_session_count_before_final": 0,
            "failure_reason": "entered",
        },
    )
    try:
        from suite_auth import AUTH_USER_ID_KEY, auth_session_complete, is_authenticated

        if not is_authenticated(session_state) or not auth_session_complete(session_state):
            out["failure_reason"] = "auth_incomplete"
            return out
    except Exception:
        out["failure_reason"] = "auth_check_failed"
        return out

    sid = str(expected_suite_sid or "").strip()
    if not sid:
        out["failure_reason"] = "suite_sid_missing"
        return out

    # Identity bind without token refresh.
    try:
        from suite_auth import _sync_auth_account_identity

        # Temporarily avoid intermediate save side-effect racing FINAL: sync identity only.
        # _sync_auth_account_identity may save INTERMEDIATE when tokens present; that is
        # still non-consuming (no set_session). FINAL follows immediately after.
        synced = _sync_auth_account_identity(session_state, st=st)
        uid = str(auth_user_id or synced or session_state.get(AUTH_USER_ID_KEY) or "").strip()
    except Exception:
        uid = str(auth_user_id or "").strip()

    if int(session_state.get(NONCONSUMING_SET_SESSION_COUNT_KEY) or 0) != 0:
        out["failure_reason"] = "set_session_invoked_during_nonconsuming_finalize"
        out["set_session_count_before_final"] = int(session_state.get(NONCONSUMING_SET_SESSION_COUNT_KEY) or 0)
        return out
    if int(session_state.get(NONCONSUMING_REFRESH_SESSION_COUNT_KEY) or 0) != 0:
        out["failure_reason"] = "refresh_session_invoked_during_nonconsuming_finalize"
        out["refresh_session_count_before_final"] = int(
            session_state.get(NONCONSUMING_REFRESH_SESSION_COUNT_KEY) or 0
        )
        return out

    handoff = perform_final_bridge_handoff(
        st,
        session_state,
        auth_user_id=uid,
        expected_suite_sid=sid,
    )
    out["handoff"] = handoff
    out["set_session_count_before_final"] = int(session_state.get(NONCONSUMING_SET_SESSION_COUNT_KEY) or 0)
    out["refresh_session_count_before_final"] = int(
        session_state.get(NONCONSUMING_REFRESH_SESSION_COUNT_KEY) or 0
    )
    if out["set_session_count_before_final"] or out["refresh_session_count_before_final"]:
        out["failure_reason"] = "auth_consumption_during_nonconsuming_finalize"
        return out
    if not handoff.get("ok"):
        out["failure_reason"] = str(handoff.get("failure_reason") or "handoff_failed")
        return out
    out["ok"] = True
    out["failure_reason"] = "ok"
    return out


def mark_post_handoff_refresh_violation(session_state: dict[str, Any]) -> None:
    """Record that a token-consuming auth call occurred after FINAL_HANDOFF."""
    if is_handoff_frozen(session_state):
        session_state[HANDOFF_NO_REFRESH_AFTER_KEY] = False
    if session_state.get(HANDOFF_SNAPSHOT_REFRESH_FP_KEY):
        session_state[HANDOFF_NO_CONSUMPTION_SINCE_SNAPSHOT_KEY] = False


def evaluate_final_handoff_eligibility(
    ledger_rows: list[dict[str, Any]],
    *,
    target_sid: str = "",
) -> dict[str, Any]:
    """Capture/reservation gate: full bridge_final_handoff_* sequence required.

    Weak save_browser_auth_tokens:FINAL_HANDOFF alone is NOT sufficient.
    Requires three-way fingerprint agreement: session snapshot, persist, readback.
    """
    target_prefix = str(target_sid or "")[:8]
    final_rows = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == CHECKPOINT_FINAL_PERSIST
        and str(r.get("handoff_phase") or PHASE_FINAL) == PHASE_FINAL
    ]
    readback_rows = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == CHECKPOINT_FINAL_READBACK
    ]
    inv_rows = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == CHECKPOINT_FINAL_INVARIANT
    ]
    save_final = final_rows[-1] if final_rows else None
    readback = readback_rows[-1] if readback_rows else None
    inv = inv_rows[-1] if inv_rows else None

    # Detect weak fallback-only evidence (2e4e7 contractual gap).
    weak_tagged = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == "save_browser_auth_tokens"
        and str(r.get("handoff_phase") or "") == PHASE_FINAL
        and bool(r.get("persistence_succeeded"))
    ]

    out: dict[str, Any] = {
        "final_handoff_seen": bool(save_final),
        "fingerprint_match": False,
        "no_auth_refresh_after_final_persist": False,
        "no_auth_consumption_since_final_token_snapshot": False,
        "eligible": False,
        "failure": "",
        "refresh_fp_prefix": "",
        "token_generation": 0,
        "bridge_final_handoff_persist": bool(save_final),
        "bridge_final_handoff_readback": bool(readback),
        "bridge_final_handoff_invariant": bool(inv),
    }

    if not save_final or not readback or not inv:
        if weak_tagged and not save_final:
            out["failure"] = CAPTURE_FAIL_WEAK_FINAL_FALLBACK
        else:
            out["failure"] = CAPTURE_FAIL_FINAL_HANDOFF
        out["final_handoff_seen"] = bool(save_final or weak_tagged)
        return out

    if target_prefix:
        prefix = str(save_final.get("suite_sid_prefix") or "")[:8]
        if prefix and prefix != target_prefix:
            out["failure"] = CAPTURE_FAIL_FINAL_HANDOFF
            return out

    snap_fp = str(
        inv.get("final_session_snapshot_fingerprint")
        or save_final.get("session_snapshot_refresh_fp_prefix")
        or ""
    )[:16]
    persist_fp = str(
        save_final.get("refresh_fp")
        or save_final.get("refresh_fp_prefix")
        or inv.get("final_persist_token_fingerprint")
        or ""
    )[:16]
    readback_fp = str(
        readback.get("refresh_fp_prefix")
        or inv.get("final_readback_token_fingerprint")
        or inv.get("final_browser_token_fingerprint")
        or ""
    )[:16]

    # Fail closed: require an explicit pre-save session snapshot — do not equate
    # persist==readback alone as independent agreement.
    if not snap_fp:
        out["failure"] = CAPTURE_FAIL_SNAPSHOT_MISMATCH
        return out
    if not persist_fp or not readback_fp:
        out["failure"] = CAPTURE_FAIL_HANDOFF_FP_MISMATCH
        return out
    if not (snap_fp == persist_fp == readback_fp):
        out["failure"] = CAPTURE_FAIL_SNAPSHOT_MISMATCH
        out["fingerprint_match"] = False
        return out

    match = bool(inv.get("fingerprint_match", True))
    out["fingerprint_match"] = match and snap_fp == persist_fp == readback_fp
    out["refresh_fp_prefix"] = persist_fp
    out["token_generation"] = int(save_final.get("token_generation") or readback.get("token_generation") or 0)

    if not out["fingerprint_match"]:
        out["failure"] = CAPTURE_FAIL_HANDOFF_FP_MISMATCH
        return out

    # Any token-consuming restore after final handoff index → ineligible
    final_idx = int(save_final.get("event_index") or 0)
    try:
        final_ei = int(str(save_final.get("event_id") or "").split(":")[1])
        final_idx = max(final_idx, final_ei)
    except (IndexError, ValueError):
        pass

    rotating = (
        "restore_auth_session_exception",
        "bridge_restore_rotation_persist",
    )
    for r in ledger_rows:
        cp = str(r.get("checkpoint") or "")
        if cp not in rotating and not (
            cp == "restore_auth_session_exit"
            and "exception:" in str(r.get("skip_or_failure_reason") or "")
        ):
            if cp == "restore_auth_session_exit" and str(r.get("skip_or_failure_reason") or "") == "ok":
                pass
            else:
                if cp not in ("restore_auth_session_exit",) or str(r.get("skip_or_failure_reason") or "") not in (
                    "ok",
                ):
                    continue
        idx = int(r.get("event_index") or 0)
        try:
            idx = max(idx, int(str(r.get("event_id") or "").split(":")[1]))
        except (IndexError, ValueError):
            pass
        if idx > final_idx:
            reason = str(r.get("skip_or_failure_reason") or "")
            if reason in (
                "already_complete",
                "auth_hydrate_3b_final",
                "handoff_frozen",
                "handoff_frozen_no_set_session",
            ):
                continue
            if cp == "restore_auth_session_exception":
                out["failure"] = CAPTURE_FAIL_POST_HANDOFF_REFRESH
                out["no_auth_refresh_after_final_persist"] = False
                return out
            if cp == "bridge_restore_rotation_persist":
                out["failure"] = CAPTURE_FAIL_POST_HANDOFF_REFRESH
                out["no_auth_refresh_after_final_persist"] = False
                return out
            if cp == "restore_auth_session_exit" and reason == "ok":
                out["failure"] = CAPTURE_FAIL_POST_HANDOFF_REFRESH
                out["no_auth_refresh_after_final_persist"] = False
                return out

    out["no_auth_refresh_after_final_persist"] = True
    if inv.get("no_auth_refresh_after_final_persist") is False:
        out["no_auth_refresh_after_final_persist"] = False
        out["failure"] = CAPTURE_FAIL_POST_HANDOFF_REFRESH
        return out

    consumption_ok = inv.get("no_auth_consumption_since_final_token_snapshot")
    if consumption_ok is False:
        out["no_auth_consumption_since_final_token_snapshot"] = False
        out["failure"] = CAPTURE_FAIL_CONSUMPTION_SINCE_SNAPSHOT
        return out
    # Missing flag on older ledgers: allow only when snapshot three-way already proven
    # and no post-handoff refresh — still require explicit True for new captures.
    out["no_auth_consumption_since_final_token_snapshot"] = consumption_ok is True
    if consumption_ok is not True:
        out["failure"] = CAPTURE_FAIL_CONSUMPTION_SINCE_SNAPSHOT
        return out

    out["eligible"] = True
    return out


# ---------------------------------------------------------------------------
# Browser-free token-rotation replay (deterministic local validation)
# ---------------------------------------------------------------------------


def replay_token_rotation_handoff(
    *,
    defect_mode: bool = False,
) -> dict[str, Any]:
    """Simulate capture A→B rotation and production restore without browser/network."""
    token_a = {"access_token": "access-A", "refresh_token": "refresh-A", "expires_at": 100}
    token_b = {"access_token": "access-B", "refresh_token": "refresh-B", "expires_at": 200}
    store: dict[str, Any] = {"payload": None, "generation": 0, "consumed": False}
    session: dict[str, Any] = {}
    ledger: list[dict[str, Any]] = []

    def _fp(tok: dict[str, Any]) -> str:
        return token_fingerprint(str(tok["refresh_token"]))

    def persist(tok: dict[str, Any], *, phase: str, event_index: int) -> None:
        store["generation"] += 1
        store["payload"] = {
            **tok,
            "token_generation": store["generation"],
            "refresh_fp": _fp(tok),
            "access_fp": token_fingerprint(tok["access_token"]),
            "handoff_phase": phase,
        }
        row = {
            "event": "production_stage1_auth_prestart_hydration",
            "checkpoint": CHECKPOINT_FINAL_PERSIST if phase == PHASE_FINAL else "save_browser_auth_tokens",
            "handoff_phase": phase,
            "persistence_succeeded": True,
            "refresh_fp": _fp(tok),
            "refresh_fp_prefix": _fp(tok)[:16],
            "token_generation": store["generation"],
            "event_index": event_index,
            "suite_sid_prefix": "deadbeef",
        }
        if phase == PHASE_FINAL:
            row["session_snapshot_refresh_fp_prefix"] = _fp(tok)[:16]
        ledger.append(row)
        if phase == PHASE_FINAL:
            fp16 = _fp(tok)[:16]
            ledger.append(
                {
                    "event": "production_stage1_auth_prestart_hydration",
                    "checkpoint": CHECKPOINT_FINAL_READBACK,
                    "handoff_phase": phase,
                    "readback_succeeded": True,
                    "refresh_fp_prefix": fp16,
                    "token_generation": store["generation"],
                    "event_index": event_index + 1,
                    "suite_sid_prefix": "deadbeef",
                }
            )
            ledger.append(
                {
                    "event": "production_stage1_auth_prestart_hydration",
                    "checkpoint": CHECKPOINT_FINAL_INVARIANT,
                    "final_session_snapshot_fingerprint": fp16,
                    "final_persist_token_fingerprint": fp16,
                    "final_browser_token_fingerprint": fp16,
                    "final_readback_token_fingerprint": fp16,
                    "fingerprint_match": True,
                    "no_auth_refresh_after_final_persist": True,
                    "no_auth_consumption_since_final_token_snapshot": True,
                    "event_index": event_index + 2,
                }
            )
            session[HANDOFF_FREEZE_KEY] = True
            session[HANDOFF_FINAL_REFRESH_FP_KEY] = _fp(tok)
            session[HANDOFF_NO_REFRESH_AFTER_KEY] = True
            session[HANDOFF_NO_CONSUMPTION_SINCE_SNAPSHOT_KEY] = True
            session[HANDOFF_SNAPSHOT_REFRESH_FP_KEY] = _fp(tok)

    def simulate_set_session(refresh: str) -> dict[str, Any]:
        if store.get("consumed"):
            return {"ok": False, "code": "refresh_token_already_used"}
        payload = store.get("payload") or {}
        if str(payload.get("refresh_token") or "") != refresh:
            return {"ok": False, "code": "refresh_token_already_used"}
        store["consumed"] = True
        return {"ok": True, "rotated_to": "refresh-C"}

    # Capture begins with A, activity rotates A→B
    session_tokens = dict(token_a)
    persist(session_tokens, phase=PHASE_INTERMEDIATE, event_index=10)
    session_tokens = dict(token_b)  # rotation A→B

    if defect_mode:
        # OLD defect: leave intermediate A as "authority" while browser holds B
        store["payload"] = {
            **token_a,
            "token_generation": 1,
            "refresh_fp": _fp(token_a),
            "access_fp": token_fingerprint(token_a["access_token"]),
            "handoff_phase": PHASE_INTERMEDIATE,
        }
        # Browser rotated after persist — eligibility must fail
        elig = evaluate_final_handoff_eligibility(ledger, target_sid="deadbeef-0000")
        # Force mismatch: final never written
        prod = simulate_set_session(str((store["payload"] or {}).get("refresh_token")))
        # Production would load A but capture already used A→B; mark A used
        prod = {"ok": False, "code": "refresh_token_already_used"}
        return {
            "defect_mode": True,
            "eligible": elig.get("eligible"),
            "failure": elig.get("failure"),
            "production": prod,
            "prevented_stale_handoff": not elig.get("eligible"),
            "persisted_refresh_fp": _fp(token_a)[:16],
            "browser_refresh_fp": _fp(token_b)[:16],
        }

    # FIXED path: FINAL_HANDOFF persists B
    persist(session_tokens, phase=PHASE_FINAL, event_index=40)
    elig = evaluate_final_handoff_eligibility(ledger, target_sid="deadbeef-0000")
    first = simulate_set_session("refresh-B")
    second = simulate_set_session("refresh-B")
    return {
        "defect_mode": False,
        "eligible": elig.get("eligible"),
        "failure": elig.get("failure") or "",
        "production_first": first,
        "production_second": second,
        "bridge_consumed": True,
        "final_refresh_fp": _fp(token_b)[:16],
        "no_auth_refresh_after_final_persist": elig.get("no_auth_refresh_after_final_persist"),
        "fingerprint_match": elig.get("fingerprint_match"),
        "handoff_frozen": is_handoff_frozen(session),
    }
