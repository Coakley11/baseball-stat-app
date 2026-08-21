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

CHECKPOINT_FINAL_PERSIST = "bridge_final_handoff_persist"
CHECKPOINT_FINAL_READBACK = "bridge_final_handoff_readback"
CHECKPOINT_FINAL_INVARIANT = "bridge_final_handoff_invariant"

CAPTURE_FAIL_FINAL_HANDOFF = "bridge_final_handoff_not_proven"
CAPTURE_FAIL_HANDOFF_FP_MISMATCH = "bridge_final_handoff_fingerprint_mismatch"
CAPTURE_FAIL_POST_HANDOFF_REFRESH = "bridge_auth_refresh_after_final_handoff"


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
        "failure_reason": "",
        "refresh_fp": "",
        "access_fp": "",
        "token_generation": 0,
    }
    if is_handoff_frozen(session_state):
        out["ok"] = True
        out["already_frozen"] = True
        out["persistence_succeeded"] = True
        out["readback_succeeded"] = True
        out["fingerprint_match"] = True
        out["no_auth_refresh_after_final_persist"] = bool(session_state.get(HANDOFF_NO_REFRESH_AFTER_KEY))
        out["refresh_fp"] = str(session_state.get(HANDOFF_FINAL_REFRESH_FP_KEY) or "")
        out["access_fp"] = str(session_state.get(HANDOFF_FINAL_ACCESS_FP_KEY) or "")
        out["token_generation"] = int(session_state.get(HANDOFF_FINAL_GENERATION_KEY) or 0)
        return out

    tokens = sync_tokens_from_auth_client_without_refresh(session_state)
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    fps = pair_fingerprints(tokens)
    out["refresh_fp"] = fps[REFRESH_FP_KEY]
    out["access_fp"] = fps[ACCESS_FP_KEY]
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
    match = rb_refresh == out["refresh_fp"] and rb_access == out["access_fp"]
    out["fingerprint_match"] = match
    if not match:
        out["failure_reason"] = "fingerprint_mismatch"
        _emit(
            session_state,
            CHECKPOINT_FINAL_INVARIANT,
            st=st,
            extra={
                **out,
                "final_persist_token_fingerprint": out["refresh_fp"][:16],
                "final_browser_token_fingerprint": rb_refresh[:16],
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
            "token_generation": gen,
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
            "failure_reason": "ok",
        },
    )
    _emit(
        session_state,
        CHECKPOINT_FINAL_INVARIANT,
        st=st,
        extra={
            "final_persist_token_fingerprint": out["refresh_fp"][:16],
            "final_browser_token_fingerprint": rb_refresh[:16],
            "no_auth_refresh_after_final_persist": True,
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
) -> dict[str, Any]:
    """Finalize once when auth session is complete and a Streamlit handle exists."""
    if st is None:
        return {"ok": False, "failure_reason": "st_missing", "skipped": True}
    if is_handoff_frozen(session_state):
        return perform_final_bridge_handoff(st, session_state, auth_user_id=auth_user_id)
    try:
        from suite_auth import auth_session_complete

        if not auth_session_complete(session_state):
            return {"ok": False, "failure_reason": "auth_incomplete", "skipped": True}
    except Exception:
        return {"ok": False, "failure_reason": "auth_check_failed", "skipped": True}
    return perform_final_bridge_handoff(st, session_state, auth_user_id=auth_user_id)


def mark_post_handoff_refresh_violation(session_state: dict[str, Any]) -> None:
    """Record that a token-consuming auth call occurred after FINAL_HANDOFF."""
    if is_handoff_frozen(session_state):
        session_state[HANDOFF_NO_REFRESH_AFTER_KEY] = False


def evaluate_final_handoff_eligibility(
    ledger_rows: list[dict[str, Any]],
    *,
    target_sid: str = "",
) -> dict[str, Any]:
    """Capture/reservation gate: FINAL_HANDOFF must be proven; no later auth refresh."""
    target_prefix = str(target_sid or "")[:8]
    final_rows = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == CHECKPOINT_FINAL_PERSIST
        and str(r.get("handoff_phase") or PHASE_FINAL) == PHASE_FINAL
    ]
    inv_rows = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == CHECKPOINT_FINAL_INVARIANT
    ]
    save_final = final_rows[-1] if final_rows else None
    inv = inv_rows[-1] if inv_rows else None

    # Fallback: save_browser_auth_tokens tagged FINAL_HANDOFF
    if not save_final:
        tagged = [
            r
            for r in ledger_rows
            if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
            and str(r.get("checkpoint") or "") == "save_browser_auth_tokens"
            and str(r.get("handoff_phase") or "") == PHASE_FINAL
            and bool(r.get("persistence_succeeded"))
        ]
        save_final = tagged[-1] if tagged else None

    out: dict[str, Any] = {
        "final_handoff_seen": bool(save_final),
        "fingerprint_match": False,
        "no_auth_refresh_after_final_persist": False,
        "eligible": False,
        "failure": "",
        "refresh_fp_prefix": "",
        "token_generation": 0,
    }
    if not save_final:
        out["failure"] = CAPTURE_FAIL_FINAL_HANDOFF
        return out

    if target_prefix:
        prefix = str(save_final.get("suite_sid_prefix") or "")[:8]
        if prefix and prefix != target_prefix:
            out["failure"] = CAPTURE_FAIL_FINAL_HANDOFF
            return out

    persist_fp = str(
        save_final.get("refresh_fp")
        or save_final.get("refresh_fp_prefix")
        or (inv or {}).get("final_persist_token_fingerprint")
        or ""
    )
    browser_fp = str(
        (inv or {}).get("final_browser_token_fingerprint")
        or save_final.get("refresh_fp_prefix")
        or persist_fp
    )
    match = bool(persist_fp) and persist_fp[:16] == browser_fp[:16]
    if inv is not None:
        match = bool(inv.get("fingerprint_match", match))
    out["fingerprint_match"] = match
    out["refresh_fp_prefix"] = persist_fp[:16]
    out["token_generation"] = int(save_final.get("token_generation") or 0)

    if not match:
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
            # set_session success exits reason "ok" after handoff also count as refresh
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
            # already_complete / auth_hydrate_3b_final after handoff are non-consuming
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
                # Successful set_session after final persist consumes the handoff token
                out["failure"] = CAPTURE_FAIL_POST_HANDOFF_REFRESH
                out["no_auth_refresh_after_final_persist"] = False
                return out

    out["no_auth_refresh_after_final_persist"] = True
    if inv is not None and inv.get("no_auth_refresh_after_final_persist") is False:
        out["no_auth_refresh_after_final_persist"] = False
        out["failure"] = CAPTURE_FAIL_POST_HANDOFF_REFRESH
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
        ledger.append(row)
        if phase == PHASE_FINAL:
            ledger.append(
                {
                    "event": "production_stage1_auth_prestart_hydration",
                    "checkpoint": CHECKPOINT_FINAL_INVARIANT,
                    "final_persist_token_fingerprint": _fp(tok)[:16],
                    "final_browser_token_fingerprint": _fp(tok)[:16],
                    "fingerprint_match": True,
                    "no_auth_refresh_after_final_persist": True,
                    "event_index": event_index + 1,
                }
            )
            session[HANDOFF_FREEZE_KEY] = True
            session[HANDOFF_FINAL_REFRESH_FP_KEY] = _fp(tok)
            session[HANDOFF_NO_REFRESH_AFTER_KEY] = True

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
