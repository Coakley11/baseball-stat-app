"""Paired run-N-end → run-N+1-begin transition forensics (outside session_state)."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import time
import traceback
from typing import Any

from live_draft_callback_boundary_diag import _ledger_store

TARGET_KEY = "live_draft_room"
LIVE_DRAFT_STATE_KEY = "live_draft_state"
LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"
LEDGER_SUFFIX = "_paired_transition"
MAX_ROWS = 500

ANCHOR_KEYS = (
    TARGET_KEY,
    LIVE_DRAFT_STATE_KEY,
    "page_filter_state",
    "active_page",
    "_solo_delivery_diag_enabled",
    "_solo_bridge_transition_enabled",
    "_solo_bridge_transition_control",
    "_live_draft_post_create_open",
    "_baseball_warm_startup_skipped",
    "_suite_cloud_workspace_applied",
)


def _ledger_key(session_id: str) -> str:
    return f"{session_id}{LEDGER_SUFFIX}"


def diag_enabled(session: dict[str, Any]) -> bool:
    if session.get("_ldr_paired_transition_force"):
        return True
    if session.get("_solo_delivery_diag_enabled"):
        return True
    if session.get("_solo_bridge_transition_enabled"):
        return True
    return False


def enable_paired_transition_diag(session: dict[str, Any]) -> None:
    session["_ldr_paired_transition_force"] = True


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
    return str(session.get("_live_draft_room_mutation_script_run") or "")


def _room_id_status(room: Any) -> tuple[str, str]:
    if not isinstance(room, dict):
        return "", ""
    return (
        str(room.get("draft_room_id") or room.get("draft_id") or "").strip(),
        str(room.get("status") or "").strip().lower(),
    )


def _key_digest(session: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(str(k) for k in session.keys())
    joined = "|".join(keys)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]
    return {
        "session_key_count": len(keys),
        "session_key_set_hash": digest,
        "session_keys_sample": keys[:40],
        "session_keys_tail": keys[-20:] if len(keys) > 40 else [],
    }


def _session_identity(session: dict[str, Any], st: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"session_mapping_id": id(session)}
    if st is not None:
        try:
            out["session_state_proxy_id"] = id(st.session_state)
        except Exception:
            pass
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and getattr(ctx, "session_state", None):
            out["runtime_session_state_id"] = id(ctx.session_state)
    except Exception:
        pass
    return out


def _rooms_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    room = session.get(TARGET_KEY)
    rid, rst = _room_id_status(room)
    canon = session.get(LIVE_DRAFT_STATE_KEY)
    cid, cst = _room_id_status(canon if isinstance(canon, dict) else None)
    pf = session.get("page_filter_state")
    pf_room = None
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            pf_room = block.get(TARGET_KEY)
    pid, pst = _room_id_status(pf_room)
    return {
        "live_draft_room_present": isinstance(room, dict) and bool(rid or room.get("draft_board") is not None),
        "live_draft_room_key_in_session": TARGET_KEY in session,
        "live_draft_room_id": rid,
        "live_draft_room_status": rst,
        "live_draft_state_room_id": cid,
        "live_draft_state_status": cst,
        "page_filter_room_id": pid,
        "page_filter_room_status": pst,
        "post_create_open": bool(session.get("_live_draft_post_create_open")),
        "anchor_keys_present": {k: k in session for k in ANCHOR_KEYS},
    }


def _auth_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    out = {
        "auth_enabled": False,
        "authenticated": False,
        "auth_user_id_prefix": "",
        "suite_workspace_id": "",
    }
    try:
        from suite_auth import AUTH_USER_ID_KEY, is_auth_enabled, is_authenticated

        out["auth_enabled"] = bool(is_auth_enabled())
        out["authenticated"] = bool(is_authenticated(session))
        uid = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if uid:
            out["auth_user_id_prefix"] = uid[:8]
        out["suite_workspace_id"] = str(
            session.get("suite_workspace_id") or session.get("_suite_active_workspace_id") or ""
        )[:40]
    except ImportError:
        pass
    return out


def note_run_end_hint(session: dict[str, Any], *, reason: str, detail: str = "") -> None:
    if not diag_enabled(session):
        return
    session["_ldr_paired_run_end_hint"] = {
        "ts": time.time(),
        "reason": reason,
        "detail": detail,
        "script_run": _script_run_label(session),
    }


def record_paired_checkpoint(
    session: dict[str, Any],
    checkpoint: str,
    *,
    st: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not diag_enabled(session):
        return {}
    sid = _streamlit_session_id() or str(session.get("_solo_bridge_transition_streamlit_session_id") or "unknown")
    row: dict[str, Any] = {
        "checkpoint": checkpoint,
        "ts": time.time(),
        "streamlit_session_id": sid,
        "script_run": _script_run_label(session),
        "active_page": str(session.get("active_page") or ""),
        **_session_identity(session, st=st),
        **_rooms_snapshot(session),
        **_key_digest(session),
        **_auth_snapshot(session),
        "prior_run_end_hint": dict(session.get("_ldr_paired_run_end_hint") or {}),
        "warm_startup_skipped": bool(session.get("_baseball_warm_startup_skipped")),
        "restore_blocked_reason": str(session.get("_live_draft_restore_blocked_reason") or ""),
    }
    if extra:
        row.update(extra)
    row["caller"] = inspect.stack()[1].function if len(inspect.stack()) > 1 else ""
    row["stack_tail"] = [line.strip() for line in traceback.format_stack(limit=5)[:-2]][-3:]
    store = _ledger_store()
    lk = _ledger_key(sid)
    ledger = list(store.get(lk) or [])
    row["seq"] = len(ledger) + 1
    ledger.append(row)
    store[lk] = ledger[-MAX_ROWS:]
    return row


def get_paired_ledger(session_id: str) -> list[dict[str, Any]]:
    return list(_ledger_store().get(_ledger_key(session_id)) or [])


def analyze_paired_transition(session_id: str) -> dict[str, Any]:
    rows = get_paired_ledger(session_id)
    present_end: dict[str, Any] | None = None
    first_absent: dict[str, Any] | None = None
    end_checkpoints = frozenset(
        {
            "bridge_ldr_entry_end",
            "active_room_script_run_end",
            "before_prepare_baseball_workspace",
            "after_prepare_baseball_workspace",
        }
    )
    for row in rows:
        cp = str(row.get("checkpoint") or "")
        if row.get("live_draft_room_present") and (
            cp in end_checkpoints or cp == "script_beginning" or cp == "ultra_early_post_page_config"
        ):
            present_end = row
        if (
            present_end
            and not first_absent
            and cp in ("ultra_early_post_page_config", "script_beginning", "script_beginning_ownership")
            and not row.get("live_draft_room_present")
            and int(row.get("seq") or 0) > int(present_end.get("seq") or 0)
        ):
            first_absent = row
            break
    if present_end and not first_absent:
        for i, row in enumerate(rows):
            if i == 0:
                continue
            prev = rows[i - 1]
            if prev.get("live_draft_room_present") and not row.get("live_draft_room_present"):
                present_end = prev
                first_absent = row
                break
    key_analysis: dict[str, Any] = {}
    if present_end and first_absent:
        prev_hash = str(present_end.get("session_key_set_hash") or "")
        next_hash = str(first_absent.get("session_key_set_hash") or "")
        prev_count = int(present_end.get("session_key_count") or 0)
        next_count = int(first_absent.get("session_key_count") or 0)
        only_ldr = (
            prev_hash != next_hash
            and present_end.get("live_draft_state_room_id")
            and first_absent.get("live_draft_state_room_id")
            and present_end.get("page_filter_room_id")
            and first_absent.get("page_filter_room_id")
        )
        key_analysis = {
            "key_set_hash_changed": prev_hash != next_hash,
            "key_count_delta": next_count - prev_count,
            "only_live_draft_room_runtime_lost": bool(
                present_end.get("live_draft_room_present")
                and not first_absent.get("live_draft_room_present")
                and present_end.get("live_draft_state_room_id")
                == first_absent.get("live_draft_state_room_id")
                and present_end.get("page_filter_room_id") == first_absent.get("page_filter_room_id")
            ),
            "broad_session_replacement_suspected": abs(next_count - prev_count) > 5 and prev_hash != next_hash,
            "session_mapping_id_same": present_end.get("session_mapping_id")
            == first_absent.get("session_mapping_id"),
            "runtime_session_state_id_same": present_end.get("runtime_session_state_id")
            == first_absent.get("runtime_session_state_id"),
        }
    return {
        "last_present": present_end,
        "first_absent": first_absent,
        "key_analysis": key_analysis,
        "row_count": len(rows),
    }


def paired_payload_for_session(session: dict[str, Any]) -> dict[str, Any]:
    sid = _streamlit_session_id() or str(session.get("_solo_bridge_transition_streamlit_session_id") or "")
    rows = get_paired_ledger(sid)
    return {
        "streamlit_session_id": sid,
        "rows": rows[-150:],
        "paired_transition": analyze_paired_transition(sid),
    }


def paired_transition_b64_for_session(session: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(paired_payload_for_session(session), default=str).encode("utf-8")).decode(
        "ascii"
    )


def render_paired_transition_probe(st: Any, session: dict[str, Any]) -> None:
    if not diag_enabled(session):
        return
    b64 = paired_transition_b64_for_session(session)
    st.markdown(
        f'<div id="solo-paired-transition-diag" data-present="1" data-paired-transition-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )
