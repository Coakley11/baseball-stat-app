"""RV3 diagnostic-only room continuity checkpoints and canonical restore."""

from __future__ import annotations

import re
from typing import Any

RV3_MOUNT_OK_THIS_RUN_KEY = "_solo_rv_rv3_mount_ok_this_run"
RV3_MOUNT_BLOCK_REASON_KEY = "_solo_rv_rv3_mount_block_reason"

_MICRO_CYCLE_COMPONENT_RETURN_RE = re.compile(
    r"component_return=(?:'([^']*)'|None)",
)
_MICRO_CYCLE_TOKEN_RE = re.compile(r"token='([^']*)'")


def snapshot_rv3_room_presence(session: dict[str, Any]) -> dict[str, Any]:
    from live_draft_state import LIVE_DRAFT_STATE_KEY

    live = session.get("live_draft_room")
    live_id = ""
    live_fp = ""
    if isinstance(live, dict):
        live_id = str(live.get("draft_room_id") or "").strip().upper()
        try:
            from live_draft_solo_rv_production_room_setup import room_state_fingerprint

            live_fp = room_state_fingerprint(live)
        except ImportError:
            pass
    blob = session.get(LIVE_DRAFT_STATE_KEY)
    canon_id = ""
    if isinstance(blob, dict):
        canon_id = str(blob.get("draft_room_id") or "").strip().upper()
    owner_id = ""
    owner_fp = ""
    owner_run = ""
    try:
        from live_draft_solo_rv_production_room_setup import RV1_SETUP_OWNER_KEY

        owner = session.get(RV1_SETUP_OWNER_KEY) or {}
        if isinstance(owner, dict):
            owner_id = str(owner.get("room_id") or "").strip().upper()
            owner_fp = str(owner.get("room_fingerprint") or "")
            owner_run = str(owner.get("owner_run_id") or "")
    except ImportError:
        pass
    return {
        "live_draft_room_present": isinstance(live, dict) and bool(live_id),
        "live_draft_room_id": live_id,
        "live_draft_room_fingerprint": live_fp,
        "canonical_live_draft_present": isinstance(blob, dict) and bool(canon_id),
        "canonical_live_draft_room_id": canon_id,
        "setup_owner_room_id": owner_id,
        "setup_owner_fingerprint": owner_fp,
        "setup_owner_run_id": owner_run,
    }


def record_rv3_room_checkpoint(
    st: Any,
    session: dict[str, Any],
    checkpoint: str,
    *,
    probe_placeholder: Any = None,
) -> dict[str, Any]:
    snap = snapshot_rv3_room_presence(session)
    try:
        from live_draft_solo_rv_control_probe import append_control_event, render_native_control_probe

        append_control_event(
            st,
            session,
            "rv3_room_checkpoint",
            control_name="RV3",
            extra={"checkpoint": checkpoint, **snap},
        )
        if probe_placeholder is not None:
            render_native_control_probe(st, session, probe_placeholder)
    except ImportError:
        pass
    return snap


def first_rv3_room_loss_checkpoint(rows: list[dict[str, Any]], *, room_id: str) -> str:
    """First checkpoint where tracked room id disappears (runner-only helper)."""
    rid = str(room_id or "").strip().upper()
    if not rid:
        return ""
    last_seen = ""
    for row in rows:
        if str(row.get("event") or "") != "rv3_room_checkpoint":
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        cp = str(extra.get("checkpoint") or "")
        for key in ("live_draft_room_id", "canonical_live_draft_room_id", "setup_owner_room_id"):
            val = str(extra.get(key) or "").strip().upper()
            if val == rid:
                last_seen = cp
                break
        live_present = bool(extra.get("live_draft_room_present"))
        canon_present = bool(extra.get("canonical_live_draft_present"))
        owner_id = str(extra.get("setup_owner_room_id") or "").strip().upper()
        if owner_id == rid and not live_present and not canon_present and last_seen:
            return cp or "unknown"
    return ""


def restore_rv3_run_scoped_room(session: dict[str, Any]) -> dict[str, Any]:
    """Restore live_draft_room from canonical blob for the RV3 setup owner (no create/start)."""
    from live_draft_state import LIVE_DRAFT_ROOM_KEY, LIVE_DRAFT_STATE_KEY, room_from_persist_dict
    from live_draft_solo_rv_production_room_setup import (
        RV1_SETUP_OWNER_KEY,
        ROOM_STATE_SOURCE_KEY,
        SAME_SESSION_SOURCE,
        _get_setup_owner,
        _room_matches_owner,
    )

    owner = _get_setup_owner(session)
    if not owner.get("setup_completed"):
        return {"ok": False, "reason": "no_setup_owner"}
    run_id = str(session.get("_solo_rv_run_id") or "").strip()
    if run_id and str(owner.get("owner_run_id") or "") != run_id:
        return {"ok": False, "reason": "owner_run_mismatch"}

    owner_rid = str(owner.get("room_id") or "").strip().upper()
    live = session.get(LIVE_DRAFT_ROOM_KEY)
    if isinstance(live, dict) and _room_matches_owner(owner, live):
        session[ROOM_STATE_SOURCE_KEY] = SAME_SESSION_SOURCE
        return {"ok": True, "source": "live_draft_room", "room_id": owner_rid, "room": live}

    blob = session.get(LIVE_DRAFT_STATE_KEY)
    if isinstance(blob, dict):
        blob_rid = str(blob.get("draft_room_id") or "").strip().upper()
        if blob_rid and owner_rid and blob_rid == owner_rid:
            restored = room_from_persist_dict(blob)
            if isinstance(restored, dict):
                session[LIVE_DRAFT_ROOM_KEY] = restored
                session[ROOM_STATE_SOURCE_KEY] = SAME_SESSION_SOURCE
                if _room_matches_owner(owner, restored):
                    return {
                        "ok": True,
                        "source": "canonical_live_draft_state",
                        "room_id": owner_rid,
                        "room": restored,
                    }
                return {"ok": False, "reason": "canonical_owner_mismatch", "room_id": owner_rid}

    return {"ok": False, "reason": "no_restorable_room", "room_id": owner_rid}


def rv3_reuse_owned_room_only(
    st: Any,
    session: dict[str, Any],
    *,
    probe_placeholder: Any = None,
) -> dict[str, Any]:
    """POST_DELIVERY: validate setup owner and reuse — never create or restart draft."""
    from live_draft_solo_rv_production_room_setup import _try_rv1_reuse_owned_room

    restore = restore_rv3_run_scoped_room(session)
    run_id = str(session.get("_solo_rv_run_id") or "").strip()
    step = str(session.get("_solo_rv_ladder_step") or "RV3")
    reused = _try_rv1_reuse_owned_room(
        st, session, run_id=run_id, step=step, probe_placeholder=probe_placeholder
    )
    if reused is not None:
        if reused.get("ok"):
            reused["restore"] = restore
        return reused
    reason = str(restore.get("reason") or "rv3_post_setup_without_live_room")
    return {
        "ok": False,
        "invalid": "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST",
        "reason": reason if reason != "no_setup_owner" else "rv3_post_setup_without_live_room",
        "restore": restore,
    }


def extract_micro_cycle_binding_token(raw: Any) -> str:
    """Parse MicroCycleResult repr or plain token string (runner + probe grading)."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text == "None":
            return ""
        if "|" in text and not text.startswith("MicroCycleResult"):
            return text.strip("'\"")
        m = _MICRO_CYCLE_COMPONENT_RETURN_RE.search(text)
        if m and m.group(1):
            return str(m.group(1)).strip()
        m2 = _MICRO_CYCLE_TOKEN_RE.search(text)
        if m2 and m2.group(1) and "|" in m2.group(1):
            return str(m2.group(1)).strip()
        return ""
    cr = getattr(raw, "component_return", None)
    if isinstance(cr, str) and cr.strip():
        return cr.strip()
    tok = getattr(raw, "token", None)
    if isinstance(tok, str) and "|" in tok:
        return tok.strip()
    return ""
