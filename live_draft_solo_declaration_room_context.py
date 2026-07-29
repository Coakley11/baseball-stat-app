"""Production countdown declaration room snapshot for post-rerun token processing."""

from __future__ import annotations

import copy
import time
from typing import Any

SOLO_DECLARATION_ROOM_CONTEXT_KEY = "_solo_persistent_wake_declaration_room_context"
SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY = "solo_countdown_wake_solo_persistent"


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
        ):
            clear_declaration_room_context(session, reason="room_pick_or_deadline_changed")
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
    }
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
        if is_runtime_room(live):
            return live
        blob = session.get(LIVE_DRAFT_STATE_KEY)
        if isinstance(blob, dict) and blob.get("draft_room_id"):
            if is_runtime_room(blob):
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
    if isinstance(ctx, dict):
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
    return True, ""


def resolve_effective_production_room(
    st: Any | None,
    session: dict[str, Any],
    *,
    declaration_room: dict[str, Any] | None,
    token: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    """Resolve live room: session state, canonical, then validated declaration snapshot."""
    meta: dict[str, Any] = {
        "live_room_id": "",
        "canonical_room_id": "",
        "declaration_room_id": _room_id(declaration_room) if isinstance(declaration_room, dict) else "",
        "supplied_token": str(token or "")[:400],
    }
    st_room = _room_from_st_session_state(st)
    if st_room is not None:
        meta["resolution_source"] = "st_session_state_live_draft_room"
        meta["resolved_room_id"] = _room_id(st_room)
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
    reg = get_registered_declaration_room(session)
    decl = declaration_room if isinstance(declaration_room, dict) else reg
    if decl is not None:
        ok, reason = validate_declaration_room_for_token(
            session,
            declaration_room=decl,
            token=token,
            widget_key=SOLO_PRODUCTION_COUNTDOWN_WIDGET_KEY,
        )
        meta["declaration_validation_ok"] = ok
        meta["declaration_validation_reason"] = reason
        if ok:
            meta["resolution_source"] = "validated_declaration_room"
            meta["resolved_room_id"] = _room_id(decl)
            return copy.deepcopy(decl), meta["resolution_source"], meta
        meta["resolution_source"] = "declaration_room_rejected"
        meta["resolved_room_id"] = ""
        return None, meta["resolution_source"], meta
    meta["resolution_source"] = "none"
    meta["resolved_room_id"] = ""
    return None, meta["resolution_source"], meta


def restore_production_room_from_declaration(
    st: Any | None,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    token: str,
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
            reason="declaration_room_restore_for_expire_token",
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
