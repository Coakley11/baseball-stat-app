"""Production countdown declaration room snapshot for post-rerun token processing."""

from __future__ import annotations

import copy
import time
from typing import Any

SOLO_DECLARATION_ROOM_CONTEXT_KEY = "_solo_persistent_wake_declaration_room_context"
SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
SOLO_EXPIRATION_SNAPSHOT_CONSUMED_KEY = "_solo_stage1_expiration_snapshot_consumed_token"


def _script_run_id(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(session) or "")
    except ImportError:
        return str(session.get("_live_draft_script_run_id") or "")


def _room_id(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    return str(room.get("draft_room_id") or room.get("draft_id") or "").strip().upper()


def _room_fingerprint(room: dict[str, Any]) -> str:
    try:
        from live_draft_solo_rv_production_room_setup import room_state_fingerprint

        return str(room_state_fingerprint(room) or "")
    except ImportError:
        rid = _room_id(room)
        pick = int(room.get("current_pick_index") or 0)
        status = str(room.get("status") or "")
        return f"{rid}:{pick}:{status}"


def _deadline_for_room(room: dict[str, Any]) -> float | None:
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        dl = live_draft_timer_deadline(room)
        if dl is not None:
            return float(dl)
    except ImportError:
        pass
    if room.get("timer_deadline") is not None:
        return float(room.get("timer_deadline") or 0.0)
    return None


def _context_meta_from_room(room: dict[str, Any] | None, ctx: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(ctx, dict):
        return {
            "present": True,
            "room_id": str(ctx.get("room_id") or ""),
            "status": str((ctx.get("room") or {}).get("status") or "") if isinstance(ctx.get("room"), dict) else "",
            "pick": ctx.get("pick_index"),
            "deadline": ctx.get("deadline"),
            "fingerprint": str(ctx.get("room_fingerprint") or ""),
            "widget_key": str(ctx.get("widget_key") or ""),
            "declaration_occurrence": str(ctx.get("expected_token") or "")[:400],
        }
    if isinstance(room, dict):
        return {
            "present": True,
            "room_id": _room_id(room),
            "status": str(room.get("status") or ""),
            "pick": room.get("current_pick_index"),
            "deadline": _deadline_for_room(room),
            "fingerprint": _room_fingerprint(room),
            "widget_key": "",
            "declaration_occurrence": "",
        }
    return {
        "present": False,
        "room_id": "",
        "status": "",
        "pick": None,
        "deadline": None,
        "fingerprint": "",
        "widget_key": "",
        "declaration_occurrence": "",
    }


def clear_declaration_room_context(session: dict[str, Any], *, reason: str = "") -> None:
    session.pop(SOLO_DECLARATION_ROOM_CONTEXT_KEY, None)
    if reason:
        session["_solo_declaration_room_context_cleared_reason"] = reason[:200]


def register_production_countdown_declaration_context(
    st: Any | None,
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None,
    expected_token: str,
    widget_key: str,
) -> None:
    """Store the production room snapshot used for the current countdown declaration."""
    if not isinstance(room, dict) or not room:
        return
    if str(widget_key or "") != SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY:
        return
    if str(room.get("status") or "") != "in_progress":
        return
    tok = str(expected_token or "").strip()
    rid = _room_id(room)
    pick = int(room.get("current_pick_index") or 0)
    dl = _deadline_for_room(room)
    fp = _room_fingerprint(room)
    prior = session.get(SOLO_DECLARATION_ROOM_CONTEXT_KEY)
    if isinstance(prior, dict):
        prior_pick = prior.get("pick_index")
        if (
            str(prior.get("room_id") or "") != rid
            or (prior_pick is not None and int(prior_pick) != pick)
            or (
                prior.get("deadline") is not None
                and dl is not None
                and abs(float(prior["deadline"]) - dl) > 0.01
            )
            or (str(prior.get("expected_token") or "") and str(prior.get("expected_token") or "") != tok)
        ):
            clear_declaration_room_context(session, reason="room_pick_deadline_or_token_changed")
    ctx = {
        "room": copy.deepcopy(room),
        "room_id": rid,
        "pick_index": pick,
        "deadline": dl,
        "room_fingerprint": fp,
        "expected_token": tok,
        "widget_key": str(widget_key),
        "registered_at": time.time(),
        "declaration_script_run": _script_run_id(session),
        "declaration_occurrence": tok,
    }
    try:
        from live_draft_stage1_post_bind_flush import deployment_sha_for_session

        ctx["deployment_sha"] = deployment_sha_for_session(session)
    except ImportError:
        ctx["deployment_sha"] = str(session.get("_solo_stage1_deployment_sha") or "")[:7]
    session[SOLO_DECLARATION_ROOM_CONTEXT_KEY] = ctx


def get_registered_declaration_room(session: dict[str, Any]) -> dict[str, Any] | None:
    ctx = session.get(SOLO_DECLARATION_ROOM_CONTEXT_KEY)
    if not isinstance(ctx, dict):
        return None
    room = ctx.get("room")
    return copy.deepcopy(room) if isinstance(room, dict) else None


def get_declaration_context(session: dict[str, Any]) -> dict[str, Any] | None:
    ctx = session.get(SOLO_DECLARATION_ROOM_CONTEXT_KEY)
    return dict(ctx) if isinstance(ctx, dict) else None


def _valid_runtime_room(room: Any) -> bool:
    if not isinstance(room, dict) or not room:
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_state import is_runtime_room

        return bool(is_runtime_room(room))
    except ImportError:
        return bool(_room_id(room))


def _room_from_st_session_state(st: Any | None) -> dict[str, Any] | None:
    if st is None:
        return None
    try:
        live = st.session_state.get("live_draft_room")
        if _valid_runtime_room(live):
            return live
    except Exception:
        pass
    return None


def _room_from_canonical(session: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, LIVE_DRAFT_STATE_KEY, is_runtime_room

        live = session.get(LIVE_DRAFT_ROOM_KEY)
        if _valid_runtime_room(live):
            return live
        blob = session.get(LIVE_DRAFT_STATE_KEY)
        if isinstance(blob, dict) and blob.get("draft_room_id"):
            if str(blob.get("status") or "") == "in_progress" and is_runtime_room(blob):
                return blob
    except ImportError:
        pass
    live = session.get("live_draft_room")
    if _valid_runtime_room(live):
        return live
    return None


def validate_declaration_room_for_token(
    session: dict[str, Any],
    *,
    declaration_room: dict[str, Any],
    token: str,
    widget_key: str,
    stored_context: dict[str, Any] | None = None,
    require_stored_context_match: bool = True,
) -> tuple[bool, str]:
    if str(widget_key or "") != SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY:
        return False, "invalid_widget_key"
    tok = str(token or "").strip()
    if not tok:
        return False, "empty_token"
    try:
        from solo_countdown_component import build_solo_expire_token, parse_solo_expire_token

        parsed = parse_solo_expire_token(tok)
        if not parsed:
            return False, "malformed_token"
    except ImportError:
        return False, "malformed_token"
    if str(declaration_room.get("status") or "") != "in_progress":
        return False, "room_not_in_progress"
    decl_rid = _room_id(declaration_room)
    if decl_rid != str(parsed["draft_id"] or "").strip().upper():
        return False, "declaration_room_id_mismatch"
    if int(declaration_room.get("current_pick_index") or 0) != int(parsed["pick_index"]):
        return False, "declaration_pick_mismatch"
    decl_dl = _deadline_for_room(declaration_room)
    tok_dl = float(parsed.get("deadline") or 0.0)
    if decl_dl is not None and tok_dl > 0 and abs(float(decl_dl) - tok_dl) > 0.75:
        return False, "declaration_deadline_mismatch"
    try:
        from solo_countdown_component import build_solo_expire_token

        expected = str(build_solo_expire_token(declaration_room) or "").strip()
        if expected and tok != expected:
            return False, "declaration_expected_token_mismatch"
    except ImportError:
        pass
    decl_fp = _room_fingerprint(declaration_room)
    ctx = stored_context if isinstance(stored_context, dict) else get_declaration_context(session)
    if require_stored_context_match and isinstance(ctx, dict):
        ctx_tok = str(ctx.get("expected_token") or "").strip()
        if ctx_tok and ctx_tok != tok:
            try:
                p_ctx = parse_solo_expire_token(ctx_tok)
                if p_ctx:
                    if str(p_ctx.get("draft_id") or "").upper() != str(parsed.get("draft_id") or "").upper():
                        return False, "declaration_context_stale_token"
                    if int(p_ctx.get("pick_index") or 0) != int(parsed.get("pick_index") or 0):
                        return False, "declaration_context_stale_token"
                    if abs(float(p_ctx.get("deadline") or 0) - float(parsed.get("deadline") or 0)) > 0.75:
                        return False, "declaration_context_stale_token"
                else:
                    return False, "declaration_context_stale_token"
            except Exception:
                return False, "declaration_context_stale_token"
        if str(ctx.get("room_fingerprint") or "") and str(ctx.get("room_fingerprint") or "") != decl_fp:
            return False, "declaration_fingerprint_mismatch"
        if str(ctx.get("room_id") or "").upper() != decl_rid:
            return False, "declaration_context_room_mismatch"
        ctx_pick = ctx.get("pick_index")
        if ctx_pick is not None and int(ctx_pick) != int(parsed["pick_index"]):
            return False, "declaration_context_pick_stale"
        if str(ctx.get("widget_key") or "") and str(ctx.get("widget_key") or "") != widget_key:
            return False, "declaration_context_widget_mismatch"
    return True, ""


def consume_expiration_validation_snapshot(
    session: dict[str, Any],
    token: str,
    *,
    reason: str = "token_action_complete",
) -> bool:
    """Clear persisted declaration validation context after bind pipeline completes."""
    tok = str(token or "").strip()
    if not tok:
        return False
    ctx = get_declaration_context(session)
    if not isinstance(ctx, dict):
        return False
    if str(ctx.get("expected_token") or "").strip() != tok:
        return False
    session[SOLO_EXPIRATION_SNAPSHOT_CONSUMED_KEY] = tok[:400]
    clear_declaration_room_context(session, reason=reason)
    return True


def validate_expiration_snapshot_for_gate(
    session: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    widget_key: str,
    bound_token: str,
) -> tuple[bool, str]:
    """Validation-only: snapshot must agree with the exact direct/Session-State bind."""
    if str(widget_key or "") != SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY:
        return False, "invalid_widget_key"
    tok = str(bound_token or "").strip()
    snap_tok = str(snapshot.get("expected_token") or "").strip()
    if not tok or not snap_tok or tok != snap_tok:
        return False, "snapshot_token_mismatch"
    if str(snapshot.get("widget_key") or "") and str(snapshot.get("widget_key") or "") != widget_key:
        return False, "snapshot_widget_mismatch"
    try:
        from solo_countdown_component import parse_solo_expire_token

        parsed = parse_solo_expire_token(tok)
        if not parsed:
            return False, "malformed_token"
    except ImportError:
        return False, "malformed_token"
    snap_rid = str(snapshot.get("room_id") or "").strip().upper()
    if snap_rid and snap_rid != str(parsed.get("draft_id") or "").strip().upper():
        return False, "snapshot_room_mismatch"
    snap_pick = snapshot.get("pick_index")
    if snap_pick is not None and int(snap_pick) != int(parsed.get("pick_index") or 0):
        return False, "snapshot_pick_mismatch"
    snap_dl = snapshot.get("deadline")
    tok_dl = float(parsed.get("deadline") or 0.0)
    if snap_dl is not None and tok_dl > 0 and abs(float(snap_dl) - tok_dl) > 0.75:
        return False, "snapshot_deadline_mismatch"
    snap_fp = str(snapshot.get("room_fingerprint") or "")
    room = snapshot.get("room")
    if snap_fp and isinstance(room, dict):
        if _room_fingerprint(room) != snap_fp:
            return False, "snapshot_fingerprint_mismatch"
    try:
        from live_draft_stage1_post_bind_flush import deployment_sha_for_session

        live_sha = deployment_sha_for_session(session)
        snap_sha = str(snapshot.get("deployment_sha") or "")[:7]
        if snap_sha and live_sha and snap_sha != live_sha:
            return False, "snapshot_deployment_sha_mismatch"
    except ImportError:
        pass
    consumed = str(session.get(SOLO_EXPIRATION_SNAPSHOT_CONSUMED_KEY) or "").strip()
    if consumed and consumed == tok:
        return False, "snapshot_already_consumed"
    live = session.get("live_draft_room")
    if isinstance(live, dict) and str(live.get("status") or "") == "in_progress":
        live_rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
        live_pick = int(live.get("current_pick_index") or 0)
        if snap_rid and live_rid and snap_rid == live_rid and snap_pick is not None and live_pick > int(snap_pick):
            return False, "snapshot_superseded_by_room_advance"
        if snap_rid and live_rid and snap_rid != live_rid:
            return False, "snapshot_superseded_by_different_room"
    return True, ""


def resolve_gate_expected_from_declaration_snapshot(
    session: dict[str, Any],
    *,
    widget_key: str,
    direct_token: str,
    session_state_token: str,
) -> tuple[str, str, str]:
    """
    Recover expected expiration token from a prior in-progress declaration.
    Snapshot is validation context only — not a bind source.
    Returns (expected_token, source, rejection_reason).
    """
    snap = get_declaration_context(session)
    if not isinstance(snap, dict):
        return "", "", "snapshot_missing"
    snap_expected = str(snap.get("expected_token") or "").strip()
    if not snap_expected:
        return "", "", "snapshot_expected_token_empty"
    candidate = direct_token or session_state_token
    if not candidate:
        return "", "", "no_bound_python_surface"
    if candidate != snap_expected:
        return "", "", "bound_token_ne_snapshot_expected"
    ok, reason = validate_expiration_snapshot_for_gate(
        session,
        snap,
        widget_key=widget_key,
        bound_token=candidate,
    )
    if not ok:
        return "", "", reason
    return snap_expected, "validated_declaration_snapshot", ""


def validate_registered_declaration_context(
    session: dict[str, Any],
    *,
    token: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    ctx = get_declaration_context(session)
    if not isinstance(ctx, dict):
        return False, "registered_context_missing", None
    run_id = _script_run_id(session)
    ctx_run = str(ctx.get("declaration_script_run") or "")
    if ctx_run and run_id and ctx_run != run_id:
        return False, "registered_context_session_mismatch", None
    room = get_registered_declaration_room(session)
    if not isinstance(room, dict):
        return False, "registered_context_room_missing", None
    ok, reason = validate_declaration_room_for_token(
        session,
        declaration_room=room,
        token=token,
        widget_key=str(ctx.get("widget_key") or SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY),
        stored_context=ctx,
        require_stored_context_match=True,
    )
    if not ok:
        return False, reason, None
    return True, "", room


def resolve_effective_production_room(
    st: Any | None,
    session: dict[str, Any],
    *,
    explicit_declaration_room: dict[str, Any] | None,
    token: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    """Resolve: live session, canonical, registered context, then explicit render prop."""
    reg_ctx = get_declaration_context(session)
    reg_room = get_registered_declaration_room(session)
    meta: dict[str, Any] = {
        "live_room_id": "",
        "canonical_room_id": "",
        "supplied_token": str(token or "")[:400],
    }
    reg_m = _context_meta_from_room(reg_room, reg_ctx if isinstance(reg_ctx, dict) else None)
    exp_m = _context_meta_from_room(
        explicit_declaration_room if isinstance(explicit_declaration_room, dict) else None,
        None,
    )
    meta["registered_context_present"] = reg_m["present"]
    meta["registered_context_room_id"] = reg_m["room_id"]
    meta["registered_context_status"] = reg_m["status"]
    meta["registered_context_pick"] = reg_m["pick"]
    meta["registered_context_deadline"] = reg_m["deadline"]
    meta["registered_context_fingerprint"] = reg_m["fingerprint"]
    meta["registered_context_widget_key"] = reg_m["widget_key"]
    meta["registered_context_declaration_occurrence"] = reg_m["declaration_occurrence"]
    meta["explicit_context_present"] = exp_m["present"]
    meta["explicit_context_room_id"] = exp_m["room_id"]
    meta["explicit_context_status"] = exp_m["status"]
    meta["explicit_context_pick"] = exp_m["pick"]
    meta["explicit_context_deadline"] = exp_m["deadline"]
    meta["explicit_context_fingerprint"] = exp_m["fingerprint"]

    st_room = _room_from_st_session_state(st)
    if st_room is not None:
        meta["resolution_source"] = "st_session_state_live_draft_room"
        meta["resolved_room_id"] = _room_id(st_room)
        meta["live_room_id"] = meta["resolved_room_id"]
        return st_room, meta["resolution_source"], meta
    session_live = session.get("live_draft_room")
    if _valid_runtime_room(session_live):
        meta["resolution_source"] = "session_live_draft_room"
        meta["resolved_room_id"] = _room_id(session_live)
        meta["live_room_id"] = meta["resolved_room_id"]
        return session_live, meta["resolution_source"], meta
    meta["live_room_id"] = _room_id(session_live) if isinstance(session_live, dict) else ""
    canon = _room_from_canonical(session)
    if canon is not None:
        meta["resolution_source"] = "canonical_live_draft_state"
        meta["canonical_room_id"] = _room_id(canon)
        meta["resolved_room_id"] = meta["canonical_room_id"]
        return canon, meta["resolution_source"], meta
    canon_blob = session.get("live_draft_state")
    if isinstance(canon_blob, dict):
        meta["canonical_room_id"] = _room_id(canon_blob)

    reg_ok, reg_reason, reg_validated = validate_registered_declaration_context(session, token=token)
    meta["registered_context_validation_ok"] = reg_ok
    meta["registered_context_validation_reason"] = reg_reason if not reg_ok else ""

    def _annotate_explicit_rejection() -> None:
        if not isinstance(explicit_declaration_room, dict):
            return
        exp_ok, exp_reason = validate_declaration_room_for_token(
            session,
            declaration_room=explicit_declaration_room,
            token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
            stored_context=reg_ctx if isinstance(reg_ctx, dict) else None,
            require_stored_context_match=False,
        )
        meta["explicit_context_validation_ok"] = exp_ok
        meta["explicit_context_rejected"] = not exp_ok
        meta["explicit_context_rejection_reason"] = exp_reason if not exp_ok else ""

    if reg_ok and isinstance(reg_validated, dict):
        _annotate_explicit_rejection()
        meta["resolution_source"] = "validated_registered_declaration_context"
        meta["resolved_room_id"] = _room_id(reg_validated)
        meta["declaration_validation_ok"] = True
        return copy.deepcopy(reg_validated), meta["resolution_source"], meta

    if isinstance(explicit_declaration_room, dict):
        exp_ok, exp_reason = validate_declaration_room_for_token(
            session,
            declaration_room=explicit_declaration_room,
            token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
            stored_context=reg_ctx if isinstance(reg_ctx, dict) else None,
            require_stored_context_match=False,
        )
        meta["explicit_context_validation_ok"] = exp_ok
        meta["explicit_context_rejected"] = not exp_ok
        meta["explicit_context_rejection_reason"] = exp_reason if not exp_ok else ""
        if exp_ok:
            meta["resolution_source"] = "validated_explicit_declaration_room"
            meta["resolved_room_id"] = _room_id(explicit_declaration_room)
            meta["declaration_validation_ok"] = True
            return copy.deepcopy(explicit_declaration_room), meta["resolution_source"], meta

    meta["resolution_source"] = "declaration_context_rejected"
    meta["resolved_room_id"] = ""
    meta["declaration_validation_ok"] = False
    meta["declaration_validation_reason"] = reg_reason if not reg_ok else meta.get("explicit_context_rejection_reason", "")
    return None, meta["resolution_source"], meta


def restore_production_room_from_declaration(
    st: Any | None,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    token: str,
    restoration_label: str = "declaration_room_restore_for_expire_token",
) -> tuple[bool, dict[str, Any]]:
    """Restore full runtime + canonical room from a validated declaration snapshot."""
    before: dict[str, Any] = {
        "live_draft_room_present": bool(session.get("live_draft_room")),
        "canonical_present": bool(session.get("live_draft_state")),
        "live_room_id": _room_id(session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None),
    }
    room_copy = copy.deepcopy(room)
    try:
        from live_draft_state import write_canonical_live_draft_state

        write_canonical_live_draft_state(
            session,
            room_copy,
            reason=restoration_label,
            local_edit=True,
        )
    except ImportError:
        session["live_draft_room"] = room_copy
    if st is not None:
        try:
            st.session_state["live_draft_room"] = session.get("live_draft_room")
        except Exception:
            pass
    after: dict[str, Any] = {
        "live_draft_room_present": bool(session.get("live_draft_room")),
        "canonical_present": bool(session.get("live_draft_state")),
        "live_room_id": _room_id(session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None),
    }
    ok = _valid_runtime_room(session.get("live_draft_room"))
    detail = {
        "room_id": _room_id(room_copy),
        "room_fingerprint": _room_fingerprint(room_copy),
        "pick_index": int(room_copy.get("current_pick_index") or 0),
        "deadline": _deadline_for_room(room_copy),
        "token": str(token or "")[:400],
        "restoration_helper": "write_canonical_live_draft_state",
        "before": before,
        "after": after,
        "restored": ok,
    }
    return ok, detail
