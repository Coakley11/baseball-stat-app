"""Stage 1A production-path diagnostic ledger (solo_component_diag; not RV3 ladder)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

STAGE1_LEDGER_KEY = "_solo_stage1_production_ledger"
STAGE1_LEDGER_MERGED_KEY = "_solo_stage1_production_ledger_merged"
STAGE1_SCRIPT_SEQ_KEY = "_solo_stage1_script_run_seq"
STAGE1_EVENT_SEQ_KEY = "_solo_stage1_event_seq"
STAGE1_RUN_ID_KEY = "_solo_stage1_run_id"
STAGE1_PROBE_ID = "solo-stage1-production-ledger"
MAX_ROWS = 400


def stage1_production_ledger_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    if str(session.get("_solo_rv_ladder_step") or "").strip():
        return False
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return False


def bump_stage1_script_run_seq(session: dict[str, Any]) -> int:
    n = int(session.get(STAGE1_SCRIPT_SEQ_KEY) or 0) + 1
    session[STAGE1_SCRIPT_SEQ_KEY] = n
    return n


def ensure_stage1_run_id(session: dict[str, Any]) -> str:
    rid = str(session.get(STAGE1_RUN_ID_KEY) or "").strip()
    if rid:
        return rid
    import uuid

    rid = uuid.uuid4().hex[:16]
    session[STAGE1_RUN_ID_KEY] = rid
    return rid


def _next_event_id(session: dict[str, Any], event: str) -> str:
    n = int(session.get(STAGE1_EVENT_SEQ_KEY) or 0) + 1
    session[STAGE1_EVENT_SEQ_KEY] = n
    run_id = ensure_stage1_run_id(session)
    return f"{run_id}:{n}:{event}"


def _room_fields(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    pick = live.get("current_pick_index")
    deadline = None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        if live:
            deadline = live_draft_timer_deadline(live)
    except ImportError:
        pass
    rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
    tok = str(session.get("_solo_persistent_wake_last_token") or session.get("_solo_parity_expected_token") or "")
    return {
        "room_id": rid,
        "pick_index": pick,
        "deadline": deadline,
        "expected_token": tok,
        "room_status": str(live.get("status") or ""),
    }


def note_stage1_event(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None = None,
    room: dict[str, Any] | None = None,
    widget_key: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not stage1_production_ledger_enabled(st, session):
        return {}
    row: dict[str, Any] = {
        "event_id": _next_event_id(session, str(event)),
        "ts": time.time(),
        "event": str(event),
        "script_run_seq": int(session.get(STAGE1_SCRIPT_SEQ_KEY) or 0),
        "run_id": ensure_stage1_run_id(session),
        "widget_key": str(widget_key or ""),
        **_room_fields(session, room),
    }
    if extra:
        row.update(extra)
    log = list(session.get(STAGE1_LEDGER_KEY) or [])
    log.append(row)
    session[STAGE1_LEDGER_KEY] = log[-MAX_ROWS:]
    merged = list(session.get(STAGE1_LEDGER_MERGED_KEY) or [])
    seen = {str(r.get("event_id") or "") for r in merged if isinstance(r, dict)}
    eid = str(row.get("event_id") or "")
    if eid and eid not in seen:
        merged.append(row)
    elif not eid:
        merged.append(row)
    session[STAGE1_LEDGER_MERGED_KEY] = merged[-MAX_ROWS:]
    return row


def note_stage1_declaration_returned(
    session: dict[str, Any],
    *,
    st: Any | None,
    room: dict[str, Any] | None,
    widget_key: str,
    expected_token: str,
    direct_return: Any,
    coalesced: str,
    raw_received: bool,
    delivered: bool,
) -> None:
    ss_val = ""
    if st is not None and widget_key in st.session_state:
        ss_val = repr(st.session_state.get(widget_key))[:400]
    note_stage1_event(
        session,
        "production_stage1_declaration_returned",
        st=st,
        room=room,
        widget_key=widget_key,
        extra={
            "direct_component_return": repr(direct_return)[:400] if direct_return is not None else "",
            "session_state_value": ss_val,
            "coalesced_value": coalesced,
            "raw_received": raw_received,
            "delivered": delivered,
            "expected_token_match": bool(expected_token and coalesced == expected_token)
            or (expected_token in ss_val),
        },
    )


def note_stage1_token_claim(
    session: dict[str, Any],
    *,
    st: Any | None,
    room: dict[str, Any] | None,
    token: str,
    source: str,
    accepted: bool,
    reject_code: str,
) -> None:
    note_stage1_event(
        session,
        "production_stage1_token_claim_attempt",
        st=st,
        room=room,
        extra={"token": str(token or "")[:400], "source": source},
    )
    note_stage1_event(
        session,
        "production_stage1_token_claim_result",
        st=st,
        room=room,
        extra={
            "token": str(token or "")[:400],
            "source": source,
            "accepted": accepted,
            "reject_code": reject_code or "",
        },
    )


def ledger_rows_for_export(session: dict[str, Any]) -> list[dict[str, Any]]:
    merged = list(session.get(STAGE1_LEDGER_MERGED_KEY) or [])
    if merged:
        return merged[-MAX_ROWS:]
    return list(session.get(STAGE1_LEDGER_KEY) or [])[-MAX_ROWS:]


def render_stage1_production_ledger_probe(st: Any, session: dict[str, Any]) -> None:
    if not stage1_production_ledger_enabled(st, session):
        return
    rows = ledger_rows_for_export(session)
    payload = {
        "run_id": ensure_stage1_run_id(session),
        "script_run_seq": int(session.get(STAGE1_SCRIPT_SEQ_KEY) or 0),
        "rows": rows,
    }
    raw = json.dumps(payload, default=str)[:48000]
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    st.markdown(
        f'<div id="{STAGE1_PROBE_ID}" data-b64="{b64}" data-rows="{len(rows)}" '
        f'data-run-id="{payload["run_id"]}"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<script>try{{window.__soloStage1LedgerB64={json.dumps(b64)};}}catch(e){{}}</script>',
        unsafe_allow_html=True,
    )
