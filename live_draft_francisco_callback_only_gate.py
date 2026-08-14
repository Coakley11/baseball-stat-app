"""Solo/stage-1 diagnostic fence: prove Francisco Add-to-Queue callback before mutation.

Lifecycle (explicit harness only):

UNARMED → ARMED → CONSUMED_LOCKED → (explicit clear only) → UNARMED

Absent/unarmed by default. Normal Add-to-Queue is unchanged. After the first
exact Francisco premutation STOP, the session stays fail-closed until
``clear_francisco_callback_only_gate``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

FRANCISCO_LINDOR_PLAYER_NAME = "Francisco Lindor"
FRANCISCO_LINDOR_TEST_PLAYER_ID = "592789"

GATE_ARMED_KEY = "_stage1_francisco_callback_only_gate_armed"
GATE_TARGET_KEY = "_stage1_francisco_callback_only_gate_target"
GATE_STATE_KEY = "_stage1_francisco_callback_only_gate_state"
GATE_EVENTS_KEY = "_stage1_francisco_callback_only_events"
GATE_LAST_KEY = "_stage1_francisco_callback_only_last"
MAX_GATE_EVENTS = 16

STATE_UNARMED = "unarmed"
STATE_ARMED = "armed"
STATE_CONSUMED_LOCKED = "consumed_locked"

PHASE_PREMUTATION_STOP = "FRANCISCO_QUEUE_CALLBACK_PREMUTATION_STOP"
PHASE_PREMUTATION_MISMATCH = "FRANCISCO_QUEUE_CALLBACK_PREMUTATION_MISMATCH"
PHASE_GATE_CONSUMED_BLOCKED = "FRANCISCO_QUEUE_CALLBACK_GATE_CONSUMED_BLOCKED"
PHASE_ARMED_FROM_RUNTIME_CARD = "FRANCISCO_CALLBACK_ONLY_GATE_ARMED_FROM_RUNTIME_CARD"
PHASE_ARMING_REFUSED_ALREADY_QUEUED = "FRANCISCO_CALLBACK_ONLY_ARMING_REFUSED_ALREADY_QUEUED"
PHASE_ARMING_SKIPPED_CONSUMED_LOCKED = "FRANCISCO_CALLBACK_ONLY_ARMING_SKIPPED_CONSUMED_LOCKED"
REASON_ALREADY_CONSUMED = "diagnostic_gate_already_consumed"

QP_FRANCISCO_CALLBACK_ONLY = "stage1_francisco_callback_only"
QUERY_LATCH_KEY = "_stage1_francisco_callback_only_query_latch"
QUERY_LATCH_NOT_REQUESTED = "not_requested"
QUERY_LATCH_REQUESTED = "requested"
QUERY_LATCH_ARMED_ONCE = "armed_once"
QUERY_LATCH_CONSUMED = "consumed"
QUERY_LATCH_REFUSED_ALREADY_QUEUED = "refused_already_queued"

CLASSIFICATION_PROVEN_PREMUTATION = "FRANCISCO_ADD_TO_QUEUE_CALLBACK_EXECUTION_PROVEN_PREMUTATION"
CLASSIFICATION_NOT_PROVEN = "FRANCISCO_ADD_TO_QUEUE_CALLBACK_EXECUTION_NOT_PROVEN"

CALLBACK_ID = "_on_rec_queue_click"


def _stage1_diag_path_enabled(session: dict[str, Any]) -> bool:
    if session.get("_solo_component_diag_enabled"):
        return True
    if str(session.get("_solo_stage1_run_id") or "").strip():
        return True
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(None, session))
    except ImportError:
        return False


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    return str(
        session.get("_solo_stage1_run_id")
        or session.get("diagnostic_run_id")
        or session.get("application_diagnostic_run_id")
        or ""
    )[:64]


def _full_app_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _recommendation_fragment_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_recommendation_fragment_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _norm(value: Any) -> str:
    return str(value or "").strip()


def query_latch_state(session: dict[str, Any]) -> str:
    raw = str(session.get(QUERY_LATCH_KEY) or "").strip().lower()
    if raw in (
        QUERY_LATCH_REQUESTED,
        QUERY_LATCH_ARMED_ONCE,
        QUERY_LATCH_CONSUMED,
        QUERY_LATCH_REFUSED_ALREADY_QUEUED,
    ):
        return raw
    return QUERY_LATCH_NOT_REQUESTED


def _francisco_callback_only_query_flag(st: Any | None) -> bool:
    if st is None:
        return False
    try:
        from live_draft_cloud_diagnostics import _qp_flag

        return bool(_qp_flag(st, QP_FRANCISCO_CALLBACK_ONLY))
    except Exception:
        return False


def _draft_queue_names(session: dict[str, Any]) -> list[str]:
    return [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]


def _canonical_queue_names(session: dict[str, Any]) -> list[str]:
    ds = session.get("draft_state") if isinstance(session.get("draft_state"), dict) else {}
    return [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]


def _persist_dirty_value(session: dict[str, Any]) -> Any:
    try:
        from live_draft_queue_persist import DRAFT_QUEUE_PERSIST_DIRTY_KEY

        return session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY)
    except ImportError:
        return session.get("_draft_queue_persist_dirty")


def gate_lifecycle(session: dict[str, Any]) -> str:
    raw = str(session.get(GATE_STATE_KEY) or "").strip().lower()
    if raw == STATE_CONSUMED_LOCKED:
        return STATE_CONSUMED_LOCKED
    if raw == STATE_ARMED or bool(session.get(GATE_ARMED_KEY)):
        return STATE_ARMED
    return STATE_UNARMED


def gate_is_armed(session: dict[str, Any]) -> bool:
    return gate_lifecycle(session) == STATE_ARMED


def gate_is_consumed_locked(session: dict[str, Any]) -> bool:
    return gate_lifecycle(session) == STATE_CONSUMED_LOCKED


def arm_francisco_callback_only_gate(
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    diagnostic_run_id: str = "",
) -> dict[str, Any]:
    """Explicit one-shot arming. Refuses unless solo/stage-1 diag path is on."""
    name = _norm(player_name)
    key = _norm(widget_key)
    if not _stage1_diag_path_enabled(session):
        return {"armed": False, "reason": "solo_stage1_diag_path_required"}
    if name != FRANCISCO_LINDOR_PLAYER_NAME:
        return {"armed": False, "reason": "player_name_must_be_francisco_lindor"}
    if not key:
        return {"armed": False, "reason": "widget_key_required"}
    if gate_lifecycle(session) == STATE_CONSUMED_LOCKED:
        return {"armed": False, "reason": "consumed_locked_release_required"}
    target = {
        "room_id": _norm(room_id),
        "pick_index": int(pick_index),
        "player_id": _norm(player_id),
        "player_name": FRANCISCO_LINDOR_PLAYER_NAME,
        "widget_key": key,
        "diagnostic_run_id": str(diagnostic_run_id or _diagnostic_run_id(session))[:64],
        "armed_ts": time.time(),
    }
    session[GATE_ARMED_KEY] = True
    session[GATE_STATE_KEY] = STATE_ARMED
    session[GATE_TARGET_KEY] = dict(target)
    return {"armed": True, "state": STATE_ARMED, "target": dict(target)}


def maybe_arm_francisco_callback_only_from_runtime_card(
    st: Any | None,
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    already_queued: bool,
) -> dict[str, Any]:
    """One-shot diagnostic latch: arm from the live Francisco rec-card identity.

    No-op unless solo/stage-1 diagnostics are enabled AND
    ``?stage1_francisco_callback_only=1`` is present. Never mutates the queue.
    Never calls ``clear_francisco_callback_only_gate``. Never re-arms after
    ``armed_once`` or ``consumed_locked``.
    """
    name = _norm(player_name)
    if name != FRANCISCO_LINDOR_PLAYER_NAME:
        return {"armed": False, "reason": "not_francisco"}
    if not _stage1_diag_path_enabled(session):
        return {"armed": False, "reason": "solo_stage1_diag_path_required"}
    if not _francisco_callback_only_query_flag(st):
        return {"armed": False, "reason": "query_absent"}

    latch = query_latch_state(session)
    if latch == QUERY_LATCH_NOT_REQUESTED:
        session[QUERY_LATCH_KEY] = QUERY_LATCH_REQUESTED
        latch = QUERY_LATCH_REQUESTED

    lifecycle = gate_lifecycle(session)
    queue_before = _draft_queue_names(session)
    canonical_before = _canonical_queue_names(session)
    persist_dirty_before = _persist_dirty_value(session)
    key = _norm(widget_key)
    pid = _norm(player_id)

    if lifecycle == STATE_CONSUMED_LOCKED:
        if latch != QUERY_LATCH_CONSUMED:
            _emit_arming_event(
                session,
                phase=PHASE_ARMING_SKIPPED_CONSUMED_LOCKED,
                room_id=room_id,
                pick_index=pick_index,
                player_id=pid,
                player_name=name,
                widget_key=key,
                queue_before=queue_before,
                canonical_queue_before=canonical_before,
                persist_dirty_before=persist_dirty_before,
                already_queued=bool(already_queued),
                target_match=False,
                gate_state_before=STATE_CONSUMED_LOCKED,
                gate_state_after=STATE_CONSUMED_LOCKED,
            )
            session[QUERY_LATCH_KEY] = QUERY_LATCH_CONSUMED
        return {
            "armed": False,
            "reason": "consumed_locked",
            "state": STATE_CONSUMED_LOCKED,
            "latch": QUERY_LATCH_CONSUMED,
        }

    if latch == QUERY_LATCH_ARMED_ONCE or lifecycle == STATE_ARMED:
        session[QUERY_LATCH_KEY] = QUERY_LATCH_ARMED_ONCE
        return {
            "armed": True,
            "reason": "already_armed",
            "state": STATE_ARMED,
            "latch": QUERY_LATCH_ARMED_ONCE,
            "target": dict(session.get(GATE_TARGET_KEY) or {}),
        }

    if already_queued:
        if latch != QUERY_LATCH_REFUSED_ALREADY_QUEUED:
            _emit_arming_event(
                session,
                phase=PHASE_ARMING_REFUSED_ALREADY_QUEUED,
                room_id=room_id,
                pick_index=pick_index,
                player_id=pid,
                player_name=name,
                widget_key=key,
                queue_before=queue_before,
                canonical_queue_before=canonical_before,
                persist_dirty_before=persist_dirty_before,
                already_queued=True,
                target_match=False,
                gate_state_before=lifecycle,
                gate_state_after=lifecycle,
            )
            session[QUERY_LATCH_KEY] = QUERY_LATCH_REFUSED_ALREADY_QUEUED
        return {
            "armed": False,
            "reason": "already_queued",
            "state": lifecycle,
            "latch": QUERY_LATCH_REFUSED_ALREADY_QUEUED,
        }

    if not key:
        return {"armed": False, "reason": "widget_key_required", "state": lifecycle, "latch": latch}

    armed = arm_francisco_callback_only_gate(
        session,
        room_id=room_id,
        pick_index=pick_index,
        player_id=pid,
        player_name=name,
        widget_key=key,
    )
    if not armed.get("armed"):
        return {
            "armed": False,
            "reason": str(armed.get("reason") or "arm_refused"),
            "state": gate_lifecycle(session),
            "latch": latch,
        }
    session[QUERY_LATCH_KEY] = QUERY_LATCH_ARMED_ONCE
    _emit_arming_event(
        session,
        phase=PHASE_ARMED_FROM_RUNTIME_CARD,
        room_id=room_id,
        pick_index=pick_index,
        player_id=pid,
        player_name=name,
        widget_key=key,
        queue_before=queue_before,
        canonical_queue_before=canonical_before,
        persist_dirty_before=persist_dirty_before,
        already_queued=False,
        target_match=True,
        gate_state_before=STATE_UNARMED,
        gate_state_after=STATE_ARMED,
    )
    return {
        "armed": True,
        "reason": "armed_from_runtime_card",
        "state": STATE_ARMED,
        "latch": QUERY_LATCH_ARMED_ONCE,
        "target": dict(armed.get("target") or {}),
    }


def consume_francisco_callback_only_gate(session: dict[str, Any]) -> None:
    """Transition ARMED → CONSUMED_LOCKED. Does not restore product mutation."""
    session[GATE_ARMED_KEY] = False
    session[GATE_STATE_KEY] = STATE_CONSUMED_LOCKED


def clear_francisco_callback_only_gate(session: dict[str, Any]) -> dict[str, Any]:
    """Explicit harness release: CONSUMED_LOCKED/ARMED → UNARMED. Not used by the callback."""
    session[GATE_ARMED_KEY] = False
    session[GATE_STATE_KEY] = STATE_UNARMED
    session.pop(GATE_TARGET_KEY, None)
    return {"armed": False, "state": STATE_UNARMED}


def match_francisco_callback_only_target(
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
) -> tuple[bool, list[str]]:
    armed = session.get(GATE_TARGET_KEY)
    if not isinstance(armed, dict):
        return False, ["armed_target_missing"]
    mismatches: list[str] = []
    expected_name = _norm(armed.get("player_name"))
    if expected_name != FRANCISCO_LINDOR_PLAYER_NAME:
        mismatches.append("armed_player_name_not_francisco")
    if _norm(player_name) != FRANCISCO_LINDOR_PLAYER_NAME:
        mismatches.append("callback_player_name_not_francisco")
    if _norm(player_name) != expected_name:
        mismatches.append("player_name")
    expected_key = _norm(armed.get("widget_key"))
    if not expected_key:
        mismatches.append("armed_widget_key_missing")
    elif expected_key != _norm(widget_key):
        mismatches.append("widget_key")
    expected_room = _norm(armed.get("room_id"))
    if expected_room and expected_room != _norm(room_id):
        mismatches.append("room_id")
    expected_pid = _norm(armed.get("player_id"))
    if expected_pid and expected_pid != _norm(player_id):
        mismatches.append("player_id")
    if "pick_index" in armed and armed.get("pick_index") is not None:
        try:
            if int(armed.get("pick_index")) != int(pick_index):
                mismatches.append("pick_index")
        except (TypeError, ValueError):
            mismatches.append("pick_index")
    return (not mismatches, mismatches)


def _retain_event(session: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    book = list(session.get(GATE_EVENTS_KEY) or [])
    book.append(dict(row))
    session[GATE_EVENTS_KEY] = book[-MAX_GATE_EVENTS:]
    session[GATE_LAST_KEY] = dict(row)
    sid = str(row.get("streamlit_session_id") or "")[:64]
    try:
        from live_draft_stage1_s3_process_global_diag import append_module_event

        append_module_event(
            sid,
            str(row.get("phase") or "")[:64],
            **{k: v for k, v in row.items() if k not in ("phase", "streamlit_session_id")},
        )
    except ImportError:
        pass
    return row


def _emit_arming_event(
    session: dict[str, Any],
    *,
    phase: str,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    queue_before: list[str],
    canonical_queue_before: list[str],
    persist_dirty_before: Any,
    already_queued: bool,
    target_match: bool,
    gate_state_before: str,
    gate_state_after: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "phase": str(phase or "")[:64],
        "streamlit_session_id": _streamlit_session_id(),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "full_app_run_seq": _full_app_run_seq(session),
        "recommendation_fragment_run_seq": _recommendation_fragment_run_seq(session),
        "room_id": _norm(room_id),
        "pick_index": int(pick_index),
        "player_id": _norm(player_id),
        "player_name": _norm(player_name),
        "widget_key": _norm(widget_key),
        "callback_id": CALLBACK_ID,
        "callback_entered": False,
        "query_latch_requested": True,
        "already_queued": bool(already_queued),
        "target_match": bool(target_match),
        "gate_state_before": str(gate_state_before or "")[:32],
        "gate_state_after": str(gate_state_after or "")[:32],
        "lifecycle_state": str(gate_state_after or "")[:32],
        "queue_before": list(queue_before)[:20],
        "canonical_queue_before": list(canonical_queue_before)[:20],
        "persist_dirty_before": persist_dirty_before,
        "mutation_attempted": False,
        "mutation_completed": False,
        "gate_armed": gate_state_after == STATE_ARMED,
        "gate_consumed": gate_state_after == STATE_CONSUMED_LOCKED,
    }
    return _retain_event(session, row)


def _emit_gate_event(
    session: dict[str, Any],
    *,
    phase: str,
    event_id: str,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    queue_before: list[str],
    target_match: bool,
    gate_consumed: bool,
    lifecycle_state: str,
    mismatch_fields: list[str] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    eid = str(event_id or "").strip()[:24] or uuid.uuid4().hex[:12]
    row: dict[str, Any] = {
        "event_id": eid,
        "ts": time.time(),
        "phase": str(phase or "")[:64],
        "streamlit_session_id": _streamlit_session_id(),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "full_app_run_seq": _full_app_run_seq(session),
        "recommendation_fragment_run_seq": _recommendation_fragment_run_seq(session),
        "room_id": _norm(room_id),
        "pick_index": int(pick_index),
        "player_id": _norm(player_id),
        "player_name": _norm(player_name),
        "widget_key": _norm(widget_key),
        "callback_id": CALLBACK_ID,
        "callback_entered": True,
        "queue_before_mutation": list(queue_before)[:20],
        "mutation_attempted": False,
        "mutation_completed": False,
        "gate_armed": lifecycle_state == STATE_ARMED,
        "lifecycle_state": str(lifecycle_state or "")[:32],
        "target_match": bool(target_match),
        "gate_consumed": bool(gate_consumed),
    }
    if mismatch_fields:
        row["mismatch_fields"] = list(mismatch_fields)[:12]
    if reason:
        row["reason"] = str(reason)[:80]
    return _retain_event(session, row)


def maybe_premutation_stop_rec_queue_click(
    session: dict[str, Any],
    *,
    event_id: str,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    queue_before: list[str],
) -> bool:
    """Return True if the production callback must return before queue mutation.

    Unarmed / non-diag sessions: False (normal product path).
    ARMED + exact Francisco match: emit STOP, CONSUMED_LOCKED, True.
    ARMED + mismatch: emit MISMATCH, fail-closed, leave ARMED.
    CONSUMED_LOCKED: emit GATE_CONSUMED_BLOCKED, fail-closed, stay locked.
    """
    state = gate_lifecycle(session)
    if state == STATE_CONSUMED_LOCKED:
        _emit_gate_event(
            session,
            phase=PHASE_GATE_CONSUMED_BLOCKED,
            event_id=event_id,
            room_id=room_id,
            pick_index=pick_index,
            player_id=player_id,
            player_name=player_name,
            widget_key=widget_key,
            queue_before=queue_before,
            target_match=False,
            gate_consumed=True,
            lifecycle_state=STATE_CONSUMED_LOCKED,
            reason=REASON_ALREADY_CONSUMED,
        )
        return True
    if not _stage1_diag_path_enabled(session):
        return False
    if state != STATE_ARMED:
        return False
    matched, mismatches = match_francisco_callback_only_target(
        session,
        room_id=room_id,
        pick_index=pick_index,
        player_id=player_id,
        player_name=player_name,
        widget_key=widget_key,
    )
    if matched:
        consume_francisco_callback_only_gate(session)
        _emit_gate_event(
            session,
            phase=PHASE_PREMUTATION_STOP,
            event_id=event_id,
            room_id=room_id,
            pick_index=pick_index,
            player_id=player_id,
            player_name=player_name,
            widget_key=widget_key,
            queue_before=queue_before,
            target_match=True,
            gate_consumed=True,
            lifecycle_state=STATE_CONSUMED_LOCKED,
        )
        return True
    _emit_gate_event(
        session,
        phase=PHASE_PREMUTATION_MISMATCH,
        event_id=event_id,
        room_id=room_id,
        pick_index=pick_index,
        player_id=player_id,
        player_name=player_name,
        widget_key=widget_key,
        queue_before=queue_before,
        target_match=False,
        gate_consumed=False,
        lifecycle_state=STATE_ARMED,
        mismatch_fields=mismatches,
    )
    return True


def last_gate_event(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(GATE_LAST_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def gate_events(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in list(session.get(GATE_EVENTS_KEY) or []) if isinstance(r, dict)]


def find_premutation_stop_event(session: dict[str, Any]) -> dict[str, Any]:
    return find_gate_event_by_phase(session, PHASE_PREMUTATION_STOP)


def find_gate_event_by_phase(session: dict[str, Any], phase: str) -> dict[str, Any]:
    want = str(phase or "")
    for row in reversed(gate_events(session)):
        if str(row.get("phase") or "") == want:
            return dict(row)
    last = last_gate_event(session)
    if str(last.get("phase") or "") == want:
        return last
    return {}


def classify_francisco_callback_only_proof(
    session: dict[str, Any],
    *,
    expected_widget_key: str,
    expected_player_id: str = FRANCISCO_LINDOR_TEST_PLAYER_ID,
    expected_room_id: str = "",
) -> dict[str, Any]:
    """Local/harness classifier. Not production proof by itself.

    A later CONSUMED_BLOCKED event does not invalidate the first STOP proof.
    """
    reasons: list[str] = []
    try:
        from live_draft_rec_fragment_exec_diag import FRAGMENT_CALLBACK_LEDGER_KEY

        ledger = list(session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or [])
    except ImportError:
        ledger = list(session.get("_live_draft_rec_fragment_callback_ledger") or [])
    entry = None
    for row in reversed(ledger):
        if not isinstance(row, dict):
            continue
        if str(row.get("callback_id") or "") != CALLBACK_ID:
            continue
        if _norm(row.get("player_name")) != FRANCISCO_LINDOR_PLAYER_NAME:
            continue
        if expected_widget_key and _norm(row.get("widget_key")) != _norm(expected_widget_key):
            continue
        entry = row
        break
    if not entry:
        reasons.append("callback_entry_missing")
    else:
        if not entry.get("callback_entered"):
            reasons.append("callback_entered_false")
        if _norm(entry.get("player_name")) != FRANCISCO_LINDOR_PLAYER_NAME:
            reasons.append("callback_entry_name")
        if expected_widget_key and _norm(entry.get("widget_key")) != _norm(expected_widget_key):
            reasons.append("callback_entry_widget_key")
        if expected_player_id and _norm(entry.get("player_id")) != _norm(expected_player_id):
            reasons.append("callback_entry_player_id")
        if expected_room_id and _norm(entry.get("room_id")) != _norm(expected_room_id):
            reasons.append("callback_entry_room_id")
    stop = find_premutation_stop_event(session)
    if str(stop.get("phase") or "") != PHASE_PREMUTATION_STOP:
        reasons.append("premutation_stop_missing")
    else:
        if not stop.get("target_match"):
            reasons.append("target_match_false")
        if stop.get("mutation_attempted") or stop.get("mutation_completed"):
            reasons.append("mutation_flag_set")
        if not stop.get("gate_consumed"):
            reasons.append("gate_not_consumed")
        if _norm(stop.get("player_name")) != FRANCISCO_LINDOR_PLAYER_NAME:
            reasons.append("stop_player_name")
        if expected_widget_key and _norm(stop.get("widget_key")) != _norm(expected_widget_key):
            reasons.append("stop_widget_key")
        if expected_player_id and _norm(stop.get("player_id")) != _norm(expected_player_id):
            reasons.append("stop_player_id")
        before = list(stop.get("queue_before_mutation") or [])
        after = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]
        if before != after:
            reasons.append("queue_changed")
        ds = session.get("draft_state") if isinstance(session.get("draft_state"), dict) else {}
        ds_q = [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]
        if ds_q and ds_q != after:
            reasons.append("canonical_queue_mismatch")
    if gate_lifecycle(session) != STATE_CONSUMED_LOCKED:
        reasons.append("not_consumed_locked")
    classification = CLASSIFICATION_PROVEN_PREMUTATION if not reasons else CLASSIFICATION_NOT_PROVEN
    return {
        "classification": classification,
        "reasons": reasons,
        "production_proof": False,
    }
