"""Production Stage 1A expiration callback timeline + pick-commit audit (diag-gated)."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

SOLO_STAGE1_CALLBACK_LOG_KEY = "_solo_stage1_callback_audit"
SOLO_STAGE1_PICK_COMMIT_LOG_KEY = "_solo_stage1_pick_commit_audit"
SOLO_TOKEN_DELIVERY_OWNER_KEY = "_solo_token_delivery_owner"
SOLO_CALLBACK_SEQ_KEY = "_solo_stage1_callback_seq"
SOLO_WAKE_REJECTED_TOKENS_KEY = "_solo_wake_rejected_tokens"
SOLO_LAST_CALLBACK_SEQ_KEY = "_solo_last_callback_seq"
SOLO_STAGE1_ACTION_COMPLETE_KEY = "_solo_stage1_token_action_complete"
MAX_ROWS = 200

HARMLESS_REJECT_CODES = frozenset(
    {
        "delivery_only_observation",
        "post_action_duplicate_suppressed",
        "already_consumed",
        "callback_source_not_allowed",
    }
)

REJECT_REASON_TO_CODE = {
    "bad_token": "malformed_token",
    "duplicate_token": "already_consumed",
    "draft_mismatch": "wrong_room",
    "pick_mismatch": "wrong_pick",
    "not_expired": "early_expiration",
    "not_actionable": "callback_source_not_allowed",
    "inert_token": "malformed_token",
    "no_live_room": "wrong_room",
}

CALLBACK_SOURCES = frozenset(
    {
        "native_component_on_change",
        "native_component_return",
        "return_value_session_bind",
        "late_page_flush",
        "post_mount_session_state_poll",
        "manual_diagnostic_invocation",
        "other",
    }
)


def stage1_expire_audit_active(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_transport_boundary_diag import transport_logging_active

        if transport_logging_active(st, session):
            return True
    except ImportError:
        pass
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return solo_component_diag_enabled(st, session)
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def _next_seq(session: dict[str, Any]) -> int:
    n = int(session.get(SOLO_CALLBACK_SEQ_KEY) or 0) + 1
    session[SOLO_CALLBACK_SEQ_KEY] = n
    session[SOLO_LAST_CALLBACK_SEQ_KEY] = n
    return n


def normalize_callback_source(source: str) -> str:
    s = str(source or "").strip()
    if s in CALLBACK_SOURCES:
        return s
    if s in ("on_change", "component", "persistent_wake"):
        return "native_component_on_change"
    if s == "flush":
        return "late_page_flush"
    return "other" if s else "native_component_on_change"


def canonical_production_source(source: str) -> tuple[str, str]:
    original = str(source or "").strip() or "native_component_on_change"
    return original, normalize_callback_source(original)


def callback_sources_allowlist() -> list[str]:
    return sorted(CALLBACK_SOURCES)


def build_callback_source_boundary_fields(
    source: str,
    *,
    delivery_only: bool = False,
    token: str = "",
    widget_key: str = "",
    call_site: str = "",
    module_name: str = "",
    script_run_seq: int = 0,
    deployment_sha: str = "",
) -> dict[str, Any]:
    original, canonical = canonical_production_source(source)
    allowed = callback_sources_allowlist()
    return {
        "original_source": original,
        "normalized_source": str(source or "").strip(),
        "canonical_source": canonical,
        "repr_original_source": repr(original),
        "repr_canonical_source": repr(canonical),
        "source_type": type(source).__name__,
        "allowed_sources": allowed,
        "membership_result": canonical in CALLBACK_SOURCES,
        "delivery_only": bool(delivery_only),
        "token": str(token or "")[:400],
        "widget_key": str(widget_key or ""),
        "call_site_function": str(call_site or ""),
        "module_name": str(module_name or ""),
        "script_run_seq": int(script_run_seq or 0),
        "deployment_sha": str(deployment_sha or "")[:40],
    }


def _deployment_sha() -> str:
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")
    except ImportError:
        return ""


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def note_callback_source_boundary(
    st: Any | None,
    session: dict[str, Any],
    *,
    source: str,
    delivery_only: bool = False,
    token: str = "",
    widget_key: str = "",
    call_site: str = "",
    module_name: str = "",
    room: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = build_callback_source_boundary_fields(
        source,
        delivery_only=delivery_only,
        token=token,
        widget_key=widget_key,
        call_site=call_site,
        module_name=module_name or __name__,
        script_run_seq=_script_run_seq(session),
        deployment_sha=_deployment_sha(),
    )
    if extra:
        fields.update(extra)
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if stage1_production_ledger_enabled(st, session):
            note_stage1_event(
                session,
                "production_stage1_callback_source_boundary",
                st=st,
                room=room,
                widget_key=widget_key,
                extra=fields,
            )
    except ImportError:
        pass
    return fields


def note_callback_source_rejected(
    st: Any | None,
    session: dict[str, Any],
    *,
    source: str,
    rejection_reason: str,
    delivery_only: bool = False,
    token: str = "",
    widget_key: str = "",
    call_site: str = "",
    module_name: str = "",
    room: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = build_callback_source_boundary_fields(
        source,
        delivery_only=delivery_only,
        token=token,
        widget_key=widget_key,
        call_site=call_site,
        module_name=module_name or __name__,
        script_run_seq=_script_run_seq(session),
        deployment_sha=_deployment_sha(),
    )
    fields["rejection_reason"] = str(rejection_reason or "")
    if extra:
        fields.update(extra)
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if stage1_production_ledger_enabled(st, session):
            note_stage1_event(
                session,
                "production_stage1_callback_source_rejected",
                st=st,
                room=room,
                widget_key=widget_key,
                extra=fields,
            )
    except ImportError:
        pass
    return fields


def authorize_production_callback_source(source: str) -> tuple[bool, str, str]:
    """Canonicalize then verify membership in the production callback-source allowlist."""
    original = str(source or "").strip() or "native_component_on_change"
    canonical = normalize_callback_source(original)
    if canonical not in CALLBACK_SOURCES:
        return False, canonical, "callback_source_not_allowed"
    if canonical == "other" and original != "other":
        return False, canonical, "callback_source_not_allowed"
    return True, canonical, ""


def get_token_action_complete(session: dict[str, Any], token: str) -> dict[str, Any] | None:
    tok = str(token or "").strip()
    if not tok:
        return None
    completed = session.get(SOLO_STAGE1_ACTION_COMPLETE_KEY) or {}
    if not isinstance(completed, dict):
        return None
    row = completed.get(tok)
    return dict(row) if isinstance(row, dict) else None


def is_token_action_complete(session: dict[str, Any], token: str) -> bool:
    return get_token_action_complete(session, token) is not None


def mark_token_action_complete(
    session: dict[str, Any],
    token: str,
    *,
    st: Any | None = None,
    room_id: str = "",
    pick_index_before: int | None = None,
    pick_index_after: int | None = None,
    committed_player: str = "",
    selection_source: str = "",
    claim_source: str = "",
    revision: str = "",
) -> dict[str, Any]:
    tok = str(token or "").strip()
    if not tok:
        return {}
    row = {
        "token": tok[:400],
        "room_id": str(room_id or "")[:80],
        "pick_index_before": pick_index_before,
        "pick_index_after": pick_index_after,
        "pick_number_before": (int(pick_index_before) + 1) if pick_index_before is not None else None,
        "pick_number_after": (int(pick_index_after) + 1) if pick_index_after is not None else None,
        "committed_player": str(committed_player or "")[:120],
        "selection_source": str(selection_source or "")[:80],
        "claim_source": normalize_callback_source(claim_source),
        "revision": str(revision or "")[:120],
        "ts": time.time(),
    }
    completed = dict(session.get(SOLO_STAGE1_ACTION_COMPLETE_KEY) or {})
    completed[tok] = row
    session[SOLO_STAGE1_ACTION_COMPLETE_KEY] = completed
    try:
        from live_draft_stage1_process_token_gate import note_token_action_complete_marker

        note_token_action_complete_marker(session, st=st, marker=row)
    except ImportError:
        pass
    return row


def map_legacy_reject_reason(reason: str) -> str:
    r = str(reason or "").strip()
    if r in REJECT_REASON_TO_CODE:
        return REJECT_REASON_TO_CODE[r]
    if r in (
        "empty_raw",
        "malformed_token",
        "wrong_room",
        "wrong_pick",
        "stale_deadline",
        "early_expiration",
        "already_consumed",
        "room_not_in_progress",
        "callback_source_not_allowed",
    ):
        return r
    return r or "other"


def try_claim_token_delivery(session: dict[str, Any], token: str, source: str) -> tuple[bool, str]:
    """First delivery owner wins for this token; later invocations are rejected."""
    tok = str(token or "").strip()
    _authorized, src, auth_reason = authorize_production_callback_source(source)
    if auth_reason:
        return False, auth_reason
    if not tok:
        return False, "empty_raw"
    if is_token_action_complete(session, tok):
        return False, "post_action_duplicate_suppressed"
    rejected = session.get(SOLO_WAKE_REJECTED_TOKENS_KEY) or {}
    if isinstance(rejected, dict) and tok in rejected:
        return False, map_legacy_reject_reason(str(rejected.get(tok) or "already_consumed"))
    owners = session.setdefault(SOLO_TOKEN_DELIVERY_OWNER_KEY, {})
    if not isinstance(owners, dict):
        owners = {}
        session[SOLO_TOKEN_DELIVERY_OWNER_KEY] = owners
    if tok in owners:
        prev = str(owners.get(tok) or "")
        if prev == src:
            return False, "already_consumed"
        return False, "callback_source_not_allowed"
    owners[tok] = src
    return True, ""


def mark_wake_token_rejected(session: dict[str, Any], token: str, reason: str) -> None:
    tok = str(token or "").strip()
    if not tok:
        return
    rejected = dict(session.get(SOLO_WAKE_REJECTED_TOKENS_KEY) or {})
    rejected[tok] = map_legacy_reject_reason(reason)
    session[SOLO_WAKE_REJECTED_TOKENS_KEY] = rejected


def _room_context(room: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(room, dict):
        return {}
    try:
        from live_draft_timer_logic import live_draft_timer_deadline

        deadline = live_draft_timer_deadline(room)
    except ImportError:
        deadline = room.get("timer_deadline")
    return {
        "room_id": str(room.get("draft_room_id") or room.get("draft_id") or "").strip(),
        "room_status": str(room.get("status") or ""),
        "canonical_pick_index": int(room.get("current_pick_index") or 0),
        "canonical_deadline": float(deadline) if deadline is not None else None,
    }


def _token_fields(token: str, room: dict[str, Any] | None) -> dict[str, Any]:
    raw = str(token or "").strip()
    expected = ""
    parsed: dict[str, Any] | None = None
    if isinstance(room, dict):
        try:
            from solo_countdown_component import build_solo_expire_token, parse_solo_expire_token

            expected = build_solo_expire_token(room)
            parsed = parse_solo_expire_token(raw) if raw else None
        except ImportError:
            pass
    out: dict[str, Any] = {
        "raw_token": raw[:400],
        "expected_canonical_token": expected[:400],
        "token_draft_id": "",
        "token_pick_index": None,
        "token_deadline": None,
    }
    if parsed:
        out["token_draft_id"] = str(parsed.get("draft_id") or "")
        out["token_pick_index"] = int(parsed.get("pick_index") or 0)
        out["token_deadline"] = parsed.get("deadline")
    return out


def record_callback_invocation(
    st: Any | None,
    session: dict[str, Any],
    *,
    callback_source: str,
    raw_value: Any,
    room: dict[str, Any] | None,
    reject_code: str = "",
    token_already_consumed: bool = False,
    committed_pick: bool = False,
    delivery_claimed: bool = True,
) -> dict[str, Any]:
    if not stage1_expire_audit_active(st, session):
        return {}
    from live_draft_solo_heartbeat import _coerce_wake_token

    seq = _next_seq(session)
    token = _coerce_wake_token(raw_value)
    ctx = _room_context(room)
    tf = _token_fields(token, room)
    try:
        from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY

        seen = str(session.get(SOLO_COMPONENT_WAKE_SEEN_KEY) or "")
    except ImportError:
        seen = str(session.get("_solo_component_wake_seen_token") or "")
    raw_reject = str(reject_code or "").strip()
    mapped_reject = map_legacy_reject_reason(raw_reject) if raw_reject else ""
    row: dict[str, Any] = {
        "ts": time.time(),
        "seq": seq,
        "callback_source": normalize_callback_source(callback_source),
        "delivery_claimed": bool(delivery_claimed),
        "raw_reject_code": raw_reject,
        "reject_code": mapped_reject,
        "token_already_consumed": bool(token_already_consumed)
        or (bool(token) and token == seen and not delivery_claimed),
        "committed_pick": bool(committed_pick),
        **tf,
        **ctx,
    }
    log = list(session.get(SOLO_STAGE1_CALLBACK_LOG_KEY) or [])
    log.append(row)
    session[SOLO_STAGE1_CALLBACK_LOG_KEY] = log[-MAX_ROWS:]
    return row


def record_pick_commit_audit(
    st: Any | None,
    session: dict[str, Any],
    *,
    room: dict[str, Any],
    team: str,
    player: str,
    selection_source: str,
    pick_before: int,
    pick_after: int,
    triggering_token: str,
    triggering_callback_seq: int | None,
    harness_manual_action: bool = False,
) -> dict[str, Any]:
    if not stage1_expire_audit_active(st, session):
        return {}
    pick_index_before = int(pick_before) - 1 if pick_before else 0
    pick_index_after = int(pick_after) - 1 if pick_after else pick_index_before + 1
    row: dict[str, Any] = {
        "ts": time.time(),
        "room_id": str(room.get("draft_room_id") or room.get("draft_id") or "").strip(),
        "team": str(team or ""),
        "player": str(player or "")[:120],
        "selection_source": str(selection_source or "unknown"),
        "pick_before": int(pick_before),
        "pick_after": int(pick_after),
        "pick_index_before": pick_index_before,
        "pick_index_after": pick_index_after,
        "pick_number_before": int(pick_before),
        "pick_number_after": int(pick_after),
        "triggering_token": str(triggering_token or "")[:400],
        "triggering_callback_seq": triggering_callback_seq,
        "harness_manual_action": bool(harness_manual_action),
        "revision": str(room.get("revision") or room.get("_revision") or "")[:120],
    }
    log = list(session.get(SOLO_STAGE1_PICK_COMMIT_LOG_KEY) or [])
    log.append(row)
    session[SOLO_STAGE1_PICK_COMMIT_LOG_KEY] = log[-MAX_ROWS:]
    return row


def stage1_audit_summary(session: dict[str, Any]) -> dict[str, Any]:
    callbacks = list(session.get(SOLO_STAGE1_CALLBACK_LOG_KEY) or [])
    commits = list(session.get(SOLO_STAGE1_PICK_COMMIT_LOG_KEY) or [])
    owners = session.get(SOLO_TOKEN_DELIVERY_OWNER_KEY) or {}
    return {
        "callback_count": len(callbacks),
        "pick_commit_count": len(commits),
        "delivery_owners": dict(owners) if isinstance(owners, dict) else {},
        "callbacks": callbacks[-80:],
        "pick_commits": commits[-20:],
    }


def render_stage1_expire_audit_probe(st: Any, session: dict[str, Any]) -> None:
    if not stage1_expire_audit_active(st, session):
        return
    summary = stage1_audit_summary(session)
    payload = json.dumps(summary, default=str)[:12000]
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    st.markdown(
        f'<div id="solo-stage1-expire-audit" data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )


def clear_persistent_wake_widget_value(st: Any, session: dict[str, Any], token: str) -> None:
    """Drop stale Streamlit widget value so post-mount poll does not re-deliver."""
    try:
        from live_draft_solo_persistent_wake import solo_persistent_wake_active, solo_persistent_wake_widget_key
    except ImportError:
        return
    if not solo_persistent_wake_active(session):
        return
    key = solo_persistent_wake_widget_key(session)
    try:
        if key in st.session_state and str(st.session_state.get(key) or "").strip() == str(token or "").strip():
            del st.session_state[key]
    except Exception:
        pass
