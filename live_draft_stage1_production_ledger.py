"""Stage 1A production-path diagnostic ledger (solo_component_diag; not RV3 ladder)."""

from __future__ import annotations

import base64
import hashlib
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
LEDGER_B64_CHUNK_CHARS = 24000
STAGE1_AUTH_SNAPSHOT_KEY = "_solo_stage1_auth_transition_snapshot"
AUTH_SNAPSHOT_MAX_ROWS = 32
AUTH_EVENTS_FOR_SNAPSHOT = frozenset(
    {
        "production_stage1_auth_state_before_start_control",
        "production_stage1_auth_prestart_hydration",
        "production_stage1_auth_prestart_mutation",
        "production_stage1_auth_state_mutation",
    }
)
HYDRATION_CHECKPOINTS_FOR_SNAPSHOT = frozenset(
    {
        "load_browser_auth_tokens",
        "load_browser_auth_tokens_lookup",
        "save_browser_auth_tokens",
        "save_browser_auth_tokens_readback",
        "restore_auth_session_exit",
        "apply_authenticated_user_exit",
        "apply_authenticated_user_entered",
        "before_start_control_render",
        "auth_session_complete_before_start_control",
    }
)
GATE_A_EXPORT_PINNED_EVENTS = frozenset(
    {
        "production_stage1_cloud_ledger_pipeline_canary",
        "production_stage1_registration_hooks_installed",
        "production_stage1_registration_hook_entered",
        "production_stage1_registration_hook_exited",
        "production_stage1_widget_metadata_at_registration",
        "production_stage1_start_control_rendered",
        "production_stage1_start_button_value",
        "production_stage1_start_callback_entered",
        "production_stage1_start_callback_exited",
        "production_stage1_pending_start_observed",
        "production_stage1_pending_start_consumed",
        "production_stage1_pending_start_absent",
        "production_stage1_start_handler_entered",
        "production_stage1_start_handler_exited",
        "production_stage1_room_creation_entered",
        "production_stage1_room_creation_exited",
        "production_stage1_room_state_write",
        "production_stage1_room_state_clear",
        "production_stage1_room_state_restore",
        "production_stage1_room_state_read",
        "production_stage1_surface_decision",
        "production_stage1_rerun_transition",
        "production_stage1_handler_exit_session_state_proof",
        "production_stage1_queueui_predicate_audit",
        "production_stage1_auth_state_before_start_control",
        "production_stage1_auth_snapshot_capture",
        "production_stage1_auth_snapshot_before_rerun",
        "production_stage1_auth_snapshot_restore_attempt",
        "production_stage1_auth_snapshot_post_restore",
        "production_stage1_auth_state_mutation",
        "production_stage1_auth_prestart_hydration",
        "production_stage1_auth_prestart_mutation",
        "production_live_draft_branch_canary",
        "production_global_script_run_canary",
    }
)


def _auth_snapshot_key(row: dict[str, Any]) -> str:
    ev = str(row.get("event") or "")
    if ev == "production_stage1_auth_prestart_hydration":
        cp = str(row.get("checkpoint") or "")
        return f"{ev}:{cp}"
    return ev


def update_stage1_auth_snapshot(session: dict[str, Any], row: dict[str, Any]) -> None:
    ev = str(row.get("event") or "")
    if ev == "production_stage1_auth_prestart_hydration":
        cp = str(row.get("checkpoint") or "")
        if cp not in HYDRATION_CHECKPOINTS_FOR_SNAPSHOT and not cp.startswith("apply_authenticated"):
            if cp not in ("before_start_control_render", "auth_session_complete_before_start_control"):
                return
    elif ev not in AUTH_EVENTS_FOR_SNAPSHOT:
        return
    snap: dict[str, Any] = dict(session.get(STAGE1_AUTH_SNAPSHOT_KEY) or {})
    snap[_auth_snapshot_key(row)] = dict(row)
    if len(snap) > AUTH_SNAPSHOT_MAX_ROWS:
        ordered = sorted(snap.values(), key=lambda r: float(r.get("ts") or 0))
        snap = {_auth_snapshot_key(r): r for r in ordered[-AUTH_SNAPSHOT_MAX_ROWS:]}
    session[STAGE1_AUTH_SNAPSHOT_KEY] = snap


def auth_snapshot_rows(session: dict[str, Any]) -> list[dict[str, Any]]:
    snap = session.get(STAGE1_AUTH_SNAPSHOT_KEY) or {}
    if not isinstance(snap, dict):
        return []
    rows = [dict(r) for r in snap.values() if isinstance(r, dict)]
    rows.sort(key=lambda r: float(r.get("ts") or 0))
    return rows


def render_stage1_auth_transition_probe(st: Any, session: dict[str, Any]) -> None:
    rows = auth_snapshot_rows(session)
    if not rows:
        return
    from live_draft_stage1_current_auth_state import AUTH_TRANSITION_PROBE_ID

    raw = json.dumps({"rows": rows}, default=str).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    run_id = ensure_stage1_run_id(session)
    st.markdown(
        f'<div id="{AUTH_TRANSITION_PROBE_ID}" '
        f'data-row-count="{len(rows)}" '
        f'data-run-id="{run_id}" '
        f'data-b64="{b64[:64000]}"></div>',
        unsafe_allow_html=True,
    )


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
    sha = str(session.get("_solo_stage1_deployment_sha") or "").strip()
    if sha:
        row["deployment_sha"] = sha[:7]
    if str(event) in AUTH_EVENTS_FOR_SNAPSHOT or str(event) == "production_stage1_auth_prestart_hydration":
        update_stage1_auth_snapshot(session, row)
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
    if not merged:
        merged = list(session.get(STAGE1_LEDGER_KEY) or [])
    auth_snap = auth_snapshot_rows(session)
    if not merged and not auth_snap:
        return []
    pinned = [
        dict(r)
        for r in merged
        if isinstance(r, dict) and str(r.get("event") or "") in GATE_A_EXPORT_PINNED_EVENTS
    ]
    snap_ids = {str(r.get("event_id") or "") for r in pinned if r.get("event_id")}
    for r in auth_snap:
        eid = str(r.get("event_id") or "")
        if eid and eid in snap_ids:
            continue
        pinned.append(dict(r))
        if eid:
            snap_ids.add(eid)
    seen = snap_ids.copy()
    tail: list[dict[str, Any]] = []
    for r in reversed(merged):
        if not isinstance(r, dict):
            continue
        eid = str(r.get("event_id") or "")
        if eid and eid in seen:
            continue
        if str(r.get("event") or "") in GATE_A_EXPORT_PINNED_EVENTS:
            continue
        tail.append(dict(r))
        if eid:
            seen.add(eid)
        if len(tail) >= MAX_ROWS:
            break
    tail.reverse()
    return pinned + tail


def _ledger_b64_chunks(b64: str) -> list[str]:
    size = LEDGER_B64_CHUNK_CHARS
    return [b64[i : i + size] for i in range(0, len(b64), size)] if b64 else []


def _streamlit_session_id_for_probe() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def render_stage1_production_ledger_probe(
    st: Any,
    session: dict[str, Any],
    *,
    probe_checkpoint: str = "early_script",
) -> None:
    if not stage1_production_ledger_enabled(st, session):
        return
    rows = ledger_rows_for_export(session)
    run_id = ensure_stage1_run_id(session)
    script_run_seq = int(session.get(STAGE1_SCRIPT_SEQ_KEY) or 0)
    diagnostic_surface = str(session.get("_solo_delivery_diag_surface") or "case_a_control")
    probe_ts = time.time()
    checkpoint = str(probe_checkpoint or "early_script")[:64]
    streamlit_session_id = _streamlit_session_id_for_probe()
    payload = {
        "run_id": run_id,
        "script_run_seq": script_run_seq,
        "rows": rows,
    }
    raw = json.dumps(payload, default=str)
    raw_bytes = raw.encode("utf-8")
    json_len = len(raw_bytes)
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    payload_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    chunks = _ledger_b64_chunks(b64)
    chunk_count = len(chunks)
    chunk_attrs = "".join(f' data-b64-chunk-{i}="{ch}"' for i, ch in enumerate(chunks))
    legacy_b64 = b64 if len(b64) <= 64000 else (chunks[0] if chunks else "")
    st.markdown(
        f'<div id="{STAGE1_PROBE_ID}" '
        f'data-b64="{legacy_b64}" '
        f'data-rows="{len(rows)}" '
        f'data-row-count="{len(rows)}" '
        f'data-run-id="{run_id}" '
        f'data-diagnostic-run-id="{run_id}" '
        f'data-script-run-seq="{script_run_seq}" '
        f'data-b64-chunk-count="{chunk_count}" '
        f'data-chunk-count="{chunk_count}" '
        f'data-payload-b64-len="{len(b64)}" '
        f'data-payload-json-len="{json_len}" '
        f'data-payload-sha256="{payload_sha256}" '
        f'data-diagnostic-surface="{diagnostic_surface}" '
        f'data-probe-checkpoint="{checkpoint}" '
        f'data-probe-ts="{probe_ts}" '
        f'data-streamlit-session-id="{streamlit_session_id}"'
        f"{chunk_attrs}></div>",
        unsafe_allow_html=True,
    )
    chunk_json = json.dumps(chunks)
    st.markdown(
        f"<script>try{{"
        f"window.__soloStage1LedgerB64={json.dumps(b64)};"
        f"window.__soloStage1LedgerB64Chunks={chunk_json};"
        f"window.__soloStage1LedgerExportMeta={{"
        f"run_id:{json.dumps(run_id)},"
        f"script_run_seq:{script_run_seq},"
        f"row_count:{len(rows)},"
        f"payload_b64_len:{len(b64)},"
        f"payload_json_len:{json_len},"
        f"payload_sha256:{json.dumps(payload_sha256)},"
        f"diagnostic_surface:{json.dumps(diagnostic_surface)}"
        f"}};"
        f"}}catch(e){{}}</script>",
        unsafe_allow_html=True,
    )
