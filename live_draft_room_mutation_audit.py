"""Append-only audit for live_draft_room session mutations (diagnostic-only, query-gated)."""

from __future__ import annotations

import base64
import inspect
import json
import time
import traceback
from typing import Any

LIVE_DRAFT_ROOM_KEY = "live_draft_room"

MUTATION_LEDGER_KEY = "_live_draft_room_mutation_ledger"
CHECKPOINT_LEDGER_KEY = "_live_draft_room_mutation_checkpoints"
FORCE_KEY = "_live_draft_room_mutation_audit_force"
MAX_MUTATIONS = 400
MAX_CHECKPOINTS = 120


def audit_enabled(session: dict[str, Any]) -> bool:
    if session.get(FORCE_KEY):
        return True
    if session.get("_solo_delivery_diag_enabled"):
        return True
    if session.get("_solo_bridge_transition_enabled"):
        return True
    return False


def enable_room_mutation_audit(session: dict[str, Any]) -> None:
    session[FORCE_KEY] = True


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")
    except Exception:
        return ""


def _script_run_label(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        rid = current_script_run_id(session)
        if rid:
            return str(rid)
    except ImportError:
        pass
    return str(
        session.get("_solo_bridge_transition_script_run_counter")
        or session.get("_live_draft_script_run_id")
        or session.get("_live_draft_room_mutation_script_run")
        or ""
    )


def bump_script_run_marker(session: dict[str, Any]) -> int:
    n = int(session.get("_live_draft_room_mutation_script_run") or 0) + 1
    session["_live_draft_room_mutation_script_run"] = n
    return n


def _room_fields(room: Any) -> tuple[str, str]:
    if not isinstance(room, dict):
        return "", ""
    rid = str(room.get("draft_room_id") or room.get("draft_id") or "").strip()
    status = str(room.get("status") or "").strip().lower()
    return rid, status


def _flags(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_create_open": bool(session.get("_live_draft_post_create_open")),
        "active_page_entered": bool(session.get("_live_draft_active_page_entered")),
        "creation_receipt": bool(session.get("_live_draft_create_receipt")),
        "start_in_flight": bool(session.get("_live_draft_start_in_flight")),
        "start_pending": bool(session.get("_start_live_draft_pending")),
        "manual_pick_in_flight": bool(session.get("_live_draft_manual_pick_in_flight")),
        "deleting": str(session.get("_live_draft_deleting") or ""),
        "restore_blocked_reason": str(session.get("_live_draft_restore_blocked_reason") or ""),
        "bridge_transition": str(session.get("_solo_bridge_transition_control") or ""),
        "bridge_phase": str(session.get("_solo_bridge_transition_phase") or ""),
        "bridge_activated": bool(session.get("_solo_bridge_transition_post_activation")),
    }


def _caller_frame(skip: int = 2) -> tuple[str, str, int]:
    stack = inspect.stack()
    idx = min(skip, len(stack) - 1)
    fr = stack[idx]
    return fr.function, fr.filename, fr.lineno


def _stack_tail(limit: int = 8) -> list[str]:
    return [line.strip() for line in traceback.format_stack(limit=limit + 4)[:-2]][-limit:]


def _append_mutation(session: dict[str, Any], entry: dict[str, Any]) -> None:
    ledger = list(session.get(MUTATION_LEDGER_KEY) or [])
    ledger.append(entry)
    session[MUTATION_LEDGER_KEY] = ledger[-MAX_MUTATIONS:]


def record_mutation(
    session: dict[str, Any],
    operation: str,
    reason: str,
    *,
    st: Any = None,
    prev_room: Any = None,
    new_room: Any = None,
    active_page: str = "",
    function: str = "",
    filename: str = "",
    lineno: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    if not audit_enabled(session):
        return
    if not function:
        function, filename, lineno = _caller_frame(3)
    if prev_room is None and operation not in ("checkpoint",):
        prev_room = session.get(LIVE_DRAFT_ROOM_KEY)
    prev_id, prev_status = _room_fields(prev_room)
    new_id, new_status = _room_fields(new_room)
    page = active_page or str(session.get("active_page") or "")
    entry: dict[str, Any] = {
        "ts": time.time(),
        "streamlit_session_id": _streamlit_session_id(),
        "script_run": _script_run_label(session),
        "operation": operation,
        "prev_room_id": prev_id,
        "prev_status": prev_status,
        "new_room_id": new_id,
        "new_status": new_status,
        "active_page": page,
        "reason": reason,
        "function": function,
        "filename": filename,
        "line": lineno,
        "stack_tail": _stack_tail(),
        "flags": _flags(session),
    }
    if extra:
        entry.update(extra)
    _append_mutation(session, entry)


def room_mutation_checkpoint(
    session: dict[str, Any],
    name: str,
    *,
    st: Any = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if not audit_enabled(session):
        return
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    rid, status = _room_fields(room)
    present = isinstance(room, dict) and bool(rid or room.get("draft_board") is not None)
    fn, filename, lineno = _caller_frame(2)
    entry: dict[str, Any] = {
        "ts": time.time(),
        "kind": "checkpoint",
        "name": name,
        "streamlit_session_id": _streamlit_session_id(),
        "script_run": _script_run_label(session),
        "room_present": present,
        "room_id": rid,
        "room_status": status,
        "active_page": str(session.get("active_page") or ""),
        "caller": fn,
        "filename": filename,
        "line": lineno,
        "flags": _flags(session),
    }
    if extra:
        entry.update(extra)
    cps = list(session.get(CHECKPOINT_LEDGER_KEY) or [])
    cps.append(entry)
    session[CHECKPOINT_LEDGER_KEY] = cps[-MAX_CHECKPOINTS:]
    record_mutation(
        session,
        "checkpoint",
        f"checkpoint:{name}",
        st=st,
        prev_room=room,
        new_room=room,
        active_page=str(session.get("active_page") or ""),
        function=fn,
        filename=filename,
        lineno=lineno,
        extra={"checkpoint": name, "room_present": present},
    )


def audited_assign_live_draft_room(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    reason: str,
    st: Any = None,
) -> None:
    prev = session.get(LIVE_DRAFT_ROOM_KEY)
    prev_id, _ = _room_fields(prev)
    new_id, _ = _room_fields(room)
    if prev_id and new_id and prev_id != new_id:
        op = "replace"
    elif prev_id and not new_id:
        op = "clear"
    elif not prev_id and new_id:
        op = "set"
    elif isinstance(prev, dict) and isinstance(room, dict):
        op = "replace"
    else:
        op = "set"
    record_mutation(
        session,
        op,
        reason,
        st=st,
        prev_room=prev,
        new_room=room,
    )
    if room is None:
        session.pop(LIVE_DRAFT_ROOM_KEY, None)
    else:
        session[LIVE_DRAFT_ROOM_KEY] = room


def audited_pop_live_draft_room(
    session: dict[str, Any],
    *,
    reason: str,
    st: Any = None,
    default: Any = None,
) -> Any:
    prev = session.get(LIVE_DRAFT_ROOM_KEY, default)
    if audit_enabled(session):
        record_mutation(
            session,
            "pop",
            reason,
            st=st,
            prev_room=prev if prev is not default else None,
            new_room=None,
        )
    return session.pop(LIVE_DRAFT_ROOM_KEY, default)


def record_skipped_restore(session: dict[str, Any], *, reason: str, st: Any = None) -> None:
    record_mutation(
        session,
        "skipped_restore",
        reason,
        st=st,
        prev_room=session.get(LIVE_DRAFT_ROOM_KEY),
        new_room=session.get(LIVE_DRAFT_ROOM_KEY),
    )


def audit_before_write_canonical(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    reason: str,
) -> None:
    if not audit_enabled(session):
        return
    prev = session.get(LIVE_DRAFT_ROOM_KEY)
    if room is None:
        if prev is not None:
            record_mutation(
                session,
                "delete",
                f"write_canonical_clear:{reason}",
                prev_room=prev,
                new_room=None,
            )
        return
    prev_id, _ = _room_fields(prev)
    new_id, _ = _room_fields(room)
    op = "set" if not prev_id else ("replace" if prev_id != new_id else "replace")
    record_mutation(
        session,
        op,
        f"write_canonical:{reason}",
        prev_room=prev,
        new_room=room,
    )


def mutation_ledger(session: dict[str, Any]) -> list[dict[str, Any]]:
    return list(session.get(MUTATION_LEDGER_KEY) or [])


def checkpoint_ledger(session: dict[str, Any]) -> list[dict[str, Any]]:
    return list(session.get(CHECKPOINT_LEDGER_KEY) or [])


def first_present_to_absent(session: dict[str, Any]) -> dict[str, Any] | None:
    """First explicit mutation or checkpoint showing room lost."""
    for row in mutation_ledger(session):
        op = str(row.get("operation") or "")
        if op in ("pop", "delete", "clear") or (
            op == "replace" and row.get("prev_room_id") and not row.get("new_room_id")
        ):
            if row.get("prev_room_id"):
                return row
    prev_present = False
    for row in checkpoint_ledger(session):
        present = bool(row.get("room_present"))
        if prev_present and not present:
            return {"kind": "checkpoint_gap", **row}
        prev_present = present
    return None


def _b64_json(payload: Any) -> str:
    return base64.b64encode(json.dumps(payload, default=str).encode("utf-8")).decode("ascii")


def render_room_mutation_audit_probe(st: Any, session: dict[str, Any]) -> None:
    if not audit_enabled(session):
        return
    mut = mutation_ledger(session)[-80:]
    cps = checkpoint_ledger(session)[-40:]
    first_loss = first_present_to_absent(session)
    payload = {
        "mutations": mut,
        "checkpoints": cps,
        "first_present_to_absent": first_loss,
    }
    b64 = _b64_json(payload)
    st.markdown(
        f'<div id="solo-room-mutation-audit" '
        f'data-present="1" '
        f'data-room-mutation-audit-b64="{b64}" '
        f'></div>',
        unsafe_allow_html=True,
    )

