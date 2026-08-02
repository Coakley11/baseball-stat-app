"""Durable production countdown callback→wrapper handoff (VALUE9 transport surface)."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

HANDOFF_KEY_PREFIX = "_solo_prod_callback_handoff_"
HANDOFF_MAX_AGE_S = 600.0
STATUS_PENDING = "pending"
STATUS_CONSUMED = "consumed"
STATUS_REJECTED = "rejected"
STATUS_CLEARED = "cleared"
STATUS_STALE = "stale"
STATUS_TERMINAL = frozenset({STATUS_CONSUMED, STATUS_REJECTED, STATUS_CLEARED, STATUS_STALE})

EVENT_WRITTEN = "production_stage1_callback_handoff_written"
EVENT_READ = "production_stage1_callback_handoff_read"
EVENT_SELECTED = "production_stage1_callback_handoff_selected"
EVENT_REJECTED = "production_stage1_callback_handoff_rejected"
EVENT_RETAINED = "production_stage1_callback_handoff_retained"
EVENT_CLEARED = "production_stage1_callback_handoff_cleared"
EVENT_TERMINAL = "production_stage1_callback_handoff_terminal"


def handoff_storage_key(widget_key: str) -> str:
    wk = str(widget_key or "").strip()
    return f"{HANDOFF_KEY_PREFIX}{wk}"


def _parse_token_parts(raw_token: str) -> dict[str, Any]:
    tok = str(raw_token or "").strip()
    out: dict[str, Any] = {
        "raw_token": tok,
        "room_id": "",
        "pick_index": None,
        "deadline": None,
        "parse_ok": False,
    }
    if not tok:
        return out
    try:
        from solo_countdown_component import parse_solo_expire_token

        parsed = parse_solo_expire_token(tok)
        if isinstance(parsed, dict):
            out["room_id"] = str(parsed.get("room_id") or parsed.get("draft_room_id") or "").strip().upper()
            out["pick_index"] = parsed.get("pick_index")
            out["deadline"] = parsed.get("deadline")
            out["parse_ok"] = bool(out["room_id"])
            return out
    except ImportError:
        pass
    parts = tok.split("|")
    if len(parts) >= 3:
        out["room_id"] = str(parts[0] or "").strip().upper()
        try:
            out["pick_index"] = int(parts[1])
        except (TypeError, ValueError):
            out["pick_index"] = None
        try:
            out["deadline"] = float(parts[2])
        except (TypeError, ValueError):
            out["deadline"] = None
        out["parse_ok"] = bool(out["room_id"])
    return out


def _deployment_sha(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_post_bind_flush import deployment_sha_for_session

        return deployment_sha_for_session(session)
    except ImportError:
        return str(session.get("_solo_stage1_deployment_sha") or "")[:7]


def _streamlit_session_id(st: Any | None, session: dict[str, Any]) -> str:
    sid = str(session.get("_solo_stage1_streamlit_session_id") or "")
    if sid:
        return sid
    try:
        if st is not None and hasattr(st, "session_state"):
            return str(getattr(st.session_state, "session_id", "") or "")
    except Exception:
        pass
    return ""


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _declaration_fingerprint(session: dict[str, Any]) -> str:
    try:
        from live_draft_solo_declaration_room_context import get_declaration_context

        ctx = get_declaration_context(session)
        if isinstance(ctx, dict):
            return str(ctx.get("room_fingerprint") or "")[:120]
    except ImportError:
        pass
    return str(session.get("_solo_stage1_declaration_fingerprint") or "")[:120]


def _internal_widget_id(session: dict[str, Any], widget_key: str) -> str:
    for k in (
        f"_solo_stage1_authoritative_widget_id_{widget_key}",
        "_solo_stage1_last_authoritative_widget_id",
        "_solo_persistent_wake_internal_widget_id",
    ):
        v = str(session.get(k) or "").strip()
        if v:
            return v[:200]
    return ""


def _note_handoff_event(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None = None,
    widget_key: str,
    record: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    rec = record if isinstance(record, dict) else {}
    payload: dict[str, Any] = {
        "raw_token": str(rec.get("raw_token") or "")[:400],
        "token_fingerprint": str(rec.get("raw_token") or "")[:400],
        "widget_user_key": str(rec.get("widget_user_key") or widget_key)[:80],
        "room_id": str(rec.get("room_id") or "")[:32],
        "pick_index": rec.get("pick_index"),
        "deadline": rec.get("deadline"),
        "callback_invocation_id": str(rec.get("callback_invocation_id") or "")[:32],
        "script_run_seq": rec.get("script_run_seq"),
        "diagnostic_run_id": str(rec.get("diagnostic_run_id") or "")[:40],
        "declaration_fingerprint": str(rec.get("declaration_fingerprint") or "")[:120],
        "deployment_sha": str(rec.get("deployment_sha") or "")[:7],
        "status": str(rec.get("status") or "")[:32],
        "equals_expected": rec.get("equals_expected"),
        "selected_binding_surface": str((extra or {}).get("selected_binding_surface") or "")[:80],
        "clear_reason": str((extra or {}).get("clear_reason") or "")[:120],
        "reject_reason": str((extra or {}).get("reject_reason") or "")[:120],
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in payload})
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        note_stage1_event(
            session,
            event,
            st=st,
            widget_key=widget_key,
            extra=payload,
        )
    except ImportError:
        pass


def get_handoff_record(session: dict[str, Any], widget_key: str) -> dict[str, Any] | None:
    raw = session.get(handoff_storage_key(widget_key))
    return deepcopy(raw) if isinstance(raw, dict) else None


def _is_acceptable_raw(raw: Any, *, expected_token: str = "") -> tuple[bool, str]:
    from live_draft_solo_heartbeat import _coerce_wake_token
    from live_draft_solo_persistent_wake import SOLO_INERT_EXPIRE_TOKEN

    if raw is None:
        return False, "raw_none"
    coerced = str(_coerce_wake_token(raw) or "").strip()
    if not coerced or coerced == SOLO_INERT_EXPIRE_TOKEN:
        return False, "raw_empty_or_inert"
    if expected_token and coerced != str(expected_token).strip():
        return False, "raw_not_expected"
    return True, coerced


def write_callback_handoff_from_on_change(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    raw_value: Any,
    expected_token: str,
    callback_invocation_id: str,
    production_room: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ok, coerced_or_reason = _is_acceptable_raw(raw_value, expected_token=expected_token)
    if not ok:
        _note_handoff_event(
            session,
            EVENT_REJECTED,
            st=st,
            widget_key=widget_key,
            extra={"reject_reason": coerced_or_reason, "phase": "callback_write"},
        )
        return None
    raw_token = str(coerced_or_reason)
    parsed = _parse_token_parts(raw_token)
    storage_key = handoff_storage_key(widget_key)
    existing = session.get(storage_key)
    now = time.time()
    if isinstance(existing, dict):
        ex_ts = float(existing.get("created_ts") or 0)
        ex_tok = str(existing.get("raw_token") or "")
        ex_status = str(existing.get("status") or "")
        if ex_status in STATUS_TERMINAL and ex_tok == raw_token:
            _note_handoff_event(
                session,
                EVENT_REJECTED,
                st=st,
                widget_key=widget_key,
                record=existing,
                extra={"reject_reason": "terminal_duplicate_token", "phase": "callback_write"},
            )
            return None
        if ex_tok == raw_token and ex_ts > now - 0.05:
            _note_handoff_event(
                session,
                EVENT_RETAINED,
                st=st,
                widget_key=widget_key,
                record=existing,
                extra={"retain_reason": "duplicate_write_same_token"},
            )
            return existing
        if ex_ts > now and str(existing.get("callback_invocation_id") or "") != callback_invocation_id:
            if ex_tok != raw_token:
                _note_handoff_event(
                    session,
                    EVENT_RETAINED,
                    st=st,
                    widget_key=widget_key,
                    record=existing,
                    extra={"retain_reason": "newer_handoff_exists"},
                )
                return existing

    room_id = parsed.get("room_id") or ""
    if not room_id and isinstance(production_room, dict):
        room_id = str(production_room.get("draft_room_id") or production_room.get("draft_id") or "").upper()

    record: dict[str, Any] = {
        "raw_token": raw_token,
        "widget_user_key": widget_key,
        "authoritative_internal_widget_id": _internal_widget_id(session, widget_key),
        "room_id": room_id,
        "pick_index": parsed.get("pick_index"),
        "deadline": parsed.get("deadline"),
        "callback_invocation_id": str(callback_invocation_id or "")[:32],
        "streamlit_session_id": _streamlit_session_id(st, session),
        "script_run_seq": _script_run_seq(session),
        "diagnostic_run_id": str(session.get("_solo_stage1_run_id") or "")[:40],
        "declaration_fingerprint": _declaration_fingerprint(session),
        "deployment_sha": _deployment_sha(session),
        "created_ts": now,
        "status": STATUS_PENDING,
        "equals_expected": bool(expected_token and raw_token == str(expected_token).strip()),
    }
    session[storage_key] = record
    session["_solo_stage1_last_callback_handoff_token"] = raw_token
    _note_handoff_event(
        session,
        EVENT_WRITTEN,
        st=st,
        widget_key=widget_key,
        record=record,
        extra={"equals_expected": record["equals_expected"]},
    )
    return record


def validate_handoff_for_declaration(
    session: dict[str, Any],
    *,
    widget_key: str,
    expected_token: str,
    declaration_snapshot: dict[str, Any] | None = None,
    st: Any | None = None,
) -> tuple[dict[str, Any] | None, str]:
    record = get_handoff_record(session, widget_key)
    if not record:
        return None, "handoff_missing"
    _note_handoff_event(session, EVENT_READ, st=st, widget_key=widget_key, record=record)
    status = str(record.get("status") or "")
    if status in STATUS_TERMINAL:
        return None, f"handoff_terminal:{status}"
    age = time.time() - float(record.get("created_ts") or 0)
    if age > HANDOFF_MAX_AGE_S:
        mark_handoff_terminal(session, widget_key, raw_token=str(record.get("raw_token") or ""), reason="expired_age", st=st)
        return None, "handoff_expired"
    raw_token = str(record.get("raw_token") or "").strip()
    expected = str(expected_token or "").strip()
    if expected and raw_token != expected:
        return None, "handoff_token_mismatch"
    if str(record.get("widget_user_key") or "") != widget_key:
        return None, "handoff_widget_key_mismatch"
    dep = str(record.get("deployment_sha") or "")[:7]
    live_dep = _deployment_sha(session)[:7]
    if dep and live_dep and dep != live_dep:
        return None, "handoff_deployment_mismatch"
    snap = declaration_snapshot if isinstance(declaration_snapshot, dict) else None
    if snap is None:
        try:
            from live_draft_solo_declaration_room_context import get_declaration_context

            snap = get_declaration_context(session)
        except ImportError:
            snap = None
    if isinstance(snap, dict):
        snap_room = str(snap.get("room_id") or "").strip().upper()
        snap_pick = snap.get("pick_index")
        snap_fp = str(snap.get("room_fingerprint") or "")
        if snap_room and str(record.get("room_id") or "").upper() != snap_room:
            return None, "handoff_room_mismatch"
        if snap_pick is not None and record.get("pick_index") is not None and int(snap_pick) != int(
            record.get("pick_index")
        ):
            return None, "handoff_pick_mismatch"
        rec_fp = str(record.get("declaration_fingerprint") or "")
        if snap_fp and rec_fp and snap_fp != rec_fp:
            return None, "handoff_fingerprint_mismatch"
    try:
        live = session.get("live_draft_room")
        if isinstance(live, dict):
            live_room = str(live.get("draft_room_id") or live.get("draft_id") or "").upper()
            live_pick = live.get("current_pick_index")
            if live_room and str(record.get("room_id") or "").upper() != live_room:
                mark_handoff_terminal(session, widget_key, raw_token=raw_token, reason="stale_room", st=st)
                return None, "handoff_stale_room"
            if live_pick is not None and record.get("pick_index") is not None and int(live_pick) != int(
                record.get("pick_index")
            ):
                mark_handoff_terminal(session, widget_key, raw_token=raw_token, reason="stale_pick", st=st)
                return None, "handoff_stale_pick"
    except Exception:
        pass
    try:
        from live_draft_stage1_expire_audit import is_token_action_complete

        if is_token_action_complete(session, raw_token):
            mark_handoff_terminal(session, widget_key, raw_token=raw_token, reason="token_already_complete", st=st)
            return None, "handoff_token_complete"
    except ImportError:
        pass
    return record, ""


def mark_handoff_terminal(
    session: dict[str, Any],
    widget_key: str,
    *,
    raw_token: str,
    reason: str,
    st: Any | None = None,
    status: str = STATUS_CLEARED,
) -> None:
    storage_key = handoff_storage_key(widget_key)
    rec = session.get(storage_key)
    if not isinstance(rec, dict):
        return
    if raw_token and str(rec.get("raw_token") or "") != str(raw_token).strip():
        _note_handoff_event(
            session,
            EVENT_RETAINED,
            st=st,
            widget_key=widget_key,
            record=rec,
            extra={"retain_reason": "clear_token_mismatch", "attempted_clear": raw_token[:400]},
        )
        return
    rec = dict(rec)
    rec["status"] = status if status in STATUS_TERMINAL else STATUS_CLEARED
    rec["terminal_reason"] = reason[:120]
    rec["terminal_ts"] = time.time()
    session[storage_key] = rec
    _note_handoff_event(
        session,
        EVENT_TERMINAL if status != STATUS_CLEARED else EVENT_CLEARED,
        st=st,
        widget_key=widget_key,
        record=rec,
        extra={"clear_reason": reason},
    )


def coalesce_expiration_token_candidates(
    *,
    expected_token: str,
    direct_raw: str,
    session_state_raw: str,
    cache_raw: str,
    handoff_raw: str,
) -> tuple[str, str, str]:
    """Returns (selected_token, binding_surface, decision)."""
    expected = str(expected_token or "").strip()
    candidates: dict[str, str] = {}
    if direct_raw:
        candidates["direct_component_return"] = direct_raw
    if session_state_raw:
        candidates["same_key_session_state"] = session_state_raw
    if cache_raw:
        candidates["raw_return_cache"] = cache_raw
    if handoff_raw:
        candidates["durable_callback_handoff"] = handoff_raw

    matching = {k: v for k, v in candidates.items() if expected and v == expected}
    if not expected:
        return "", "", "reject_no_expected_token"
    if not matching:
        return "", "", "reject_no_exact_candidate"
    distinct = set(matching.values())
    if len(distinct) > 1:
        return "", "", "reject_candidate_conflict"
    surface = sorted(matching.keys())[0]
    if len(matching) > 1:
        surface = "durable_callback_handoff" if "durable_callback_handoff" in matching else surface
    return expected, surface, "pass_exact_token"


def handoff_token_for_gate(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    expected_token: str,
) -> tuple[str, dict[str, Any] | None, str]:
    from live_draft_solo_heartbeat import _coerce_wake_token

    record, reject = validate_handoff_for_declaration(
        session,
        widget_key=widget_key,
        expected_token=expected_token,
        st=st,
    )
    if not record:
        return "", None, reject
    tok = str(_coerce_wake_token(record.get("raw_token")) or "").strip()
    if tok != str(expected_token or "").strip():
        return "", record, "handoff_coerce_mismatch"
    _note_handoff_event(
        session,
        EVENT_SELECTED,
        st=st,
        widget_key=widget_key,
        record=record,
        extra={"selected_binding_surface": "durable_callback_handoff", "equals_expected": True},
    )
    return tok, record, ""


def emit_callback_handoff_selected(
    session: dict[str, Any],
    *,
    st: Any | None,
    widget_key: str,
    record: dict[str, Any],
) -> None:
    _note_handoff_event(
        session,
        EVENT_SELECTED,
        st=st,
        widget_key=widget_key,
        record=record,
        extra={"selected_binding_surface": "durable_callback_handoff", "equals_expected": True},
    )


def clear_handoff_after_successful_processing(
    session: dict[str, Any],
    *,
    widget_key: str,
    raw_token: str,
    st: Any | None = None,
    reason: str = "processing_terminal",
) -> None:
    mark_handoff_terminal(
        session,
        widget_key,
        raw_token=raw_token,
        reason=reason,
        st=st,
        status=STATUS_CONSUMED,
    )
