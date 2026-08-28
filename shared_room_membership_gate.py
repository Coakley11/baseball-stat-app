"""Authoritative Shared Multiplayer membership gate.

A participant may render an active shared draft only when the exact room
document recognizes their canonical participant id. Stale local room codes,
old membership maps, and \"newest room\" lookups must never auto-join.
"""

from __future__ import annotations

from typing import Any

MEMBERSHIP_GATE_DIAG_KEY = "_shared_room_membership_gate_diag"
STALE_REPAIR_DIAG_KEY = "_shared_room_stale_repair_diag"


def _room_code(session: dict[str, Any]) -> str:
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if code:
        return code
    try:
        from draft_room_context import resolve_shared_room_code

        return str(resolve_shared_room_code(session) or "").strip().upper()
    except ImportError:
        return ""


def _participant_id(session: dict[str, Any]) -> str:
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return str(session.get("auth_user_id") or session.get("_suite_auth_user_id") or "").strip()


def _ended_or_deleted_status(status: str) -> bool:
    """Hard-end statuses that must not render an active shared draft.

    Natural ``complete`` / ``completed`` stays reviewable after refresh.
    """
    return str(status or "").strip().lower() in {
        "deleted",
        "ended",
        "closed",
    }


def load_authoritative_shared_document(
    session: dict[str, Any],
    room_code: str = "",
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    code = str(room_code or _room_code(session) or "").strip().upper()
    if not code:
        return None
    try:
        from draft_room_shared_state import (
            invalidate_shared_room_document_cache,
            load_shared_room,
            load_shared_room_document,
        )

        if force:
            invalidate_shared_room_document_cache(session, code)
        doc = load_shared_room_document(session, code)
        if isinstance(doc, dict):
            return doc
        doc = load_shared_room(code)
        return doc if isinstance(doc, dict) else None
    except ImportError:
        return None
    except Exception:
        return None


def participant_in_document(
    document: dict[str, Any] | None,
    participant_id: str,
) -> tuple[bool, str]:
    """Return (ok, assigned_team) when pid is registered on the authoritative doc."""
    pid = str(participant_id or "").strip()
    if not pid or not isinstance(document, dict):
        return False, ""
    parts = document.get("participants")
    if isinstance(parts, dict):
        meta = parts.get(pid)
        if isinstance(meta, dict):
            team = str(
                meta.get("assigned_team")
                or meta.get("team")
                or meta.get("claimed_team")
                or ""
            ).strip()
            return True, team
        # Case-insensitive id match (auth aliases).
        for key, val in parts.items():
            if str(key).strip().lower() == pid.lower() and isinstance(val, dict):
                team = str(
                    val.get("assigned_team") or val.get("team") or val.get("claimed_team") or ""
                ).strip()
                return True, team
    return False, ""


def can_render_shared_live_draft(
    session: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
    require_team_claim: bool = True,
) -> tuple[bool, str]:
    """Gate active shared-room UI. Fail closed when membership is not authoritative."""
    code = _room_code(session)
    if not code:
        return False, "no_room_code"

    try:
        from live_draft_termination import is_live_draft_permanently_retired

        if is_live_draft_permanently_retired(session, room_code=code):
            return False, "tombstoned"
    except ImportError:
        pass

    doc = document if isinstance(document, dict) else load_authoritative_shared_document(session, code)
    if not isinstance(doc, dict):
        return False, "room_missing"

    status = str(doc.get("status") or "").strip().lower()
    room_blob = doc.get("room") if isinstance(doc.get("room"), dict) else {}
    if not status:
        status = str((room_blob or {}).get("status") or "").strip().lower()
    if _ended_or_deleted_status(status):
        return False, f"terminal:{status or 'unknown'}"

    pid = _participant_id(session)
    if not pid:
        return False, "no_participant_id"

    ok, team = participant_in_document(doc, pid)
    if not ok:
        return False, "not_in_document_participants"

    if require_team_claim and not team:
        # Host lobby before start may still be valid if registered without team yet —
        # allow only when document marks them as host.
        host_id = str(
            doc.get("host_participant_id")
            or doc.get("host_user_id")
            or (room_blob or {}).get("host_participant_id")
            or ""
        ).strip()
        if host_id and host_id == pid:
            team = str((room_blob or {}).get("config", {}).get("your_team") or "").strip() or "Host"
        else:
            return False, "no_team_claim"

    local_room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    local_id = str(
        (local_room or {}).get("draft_room_id")
        or (local_room or {}).get("draft_id")
        or ""
    ).strip()
    auth_id = str(
        doc.get("draft_room_id")
        or (room_blob or {}).get("draft_room_id")
        or doc.get("room_id")
        or ""
    ).strip()
    if local_id and auth_id and local_id != auth_id:
        return False, "local_room_id_mismatch"

    local_code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    doc_code = str(doc.get("room_code") or code).strip().upper()
    if local_code and doc_code and local_code != doc_code:
        return False, "local_room_code_mismatch"

    session[MEMBERSHIP_GATE_DIAG_KEY] = {
        "ok": True,
        "room_code": code,
        "participant_id": pid,
        "team": team,
        "draft_room_id": auth_id or None,
        "status": status,
    }
    return True, "ok"


def clear_stale_shared_room_local_state(
    session: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Clear local active-room mirrors without destroying durable preferences."""
    cleared: list[str] = []
    for key in (
        "active_shared_draft_room_code",
        "draft_room_shared_meta",
        "live_draft_room",
        "live_draft_state",
        "draft_room_participant_team",
        "draft_room_participant_id",
        "room_your_team",
        "_shared_draft_poll_ts",
        "_shared_room_doc_soft_cache",
        "_live_draft_queue_fragment_pick",
        "_live_draft_defer_full_rerun",
    ):
        if key in session:
            session.pop(key, None)
            cleared.append(key)
    try:
        from live_draft_state import clear_live_draft_state

        clear_live_draft_state(session, reason=f"stale_membership_repair:{reason}")
        cleared.append("clear_live_draft_state")
    except Exception:
        pass
    try:
        from live_draft_termination import bump_live_draft_page_epoch

        bump_live_draft_page_epoch(session)
    except ImportError:
        pass
    diag = {"reason": reason, "cleared": cleared}
    session[STALE_REPAIR_DIAG_KEY] = diag
    session[MEMBERSHIP_GATE_DIAG_KEY] = {"ok": False, "reason": reason}
    return diag


def _local_membership_markers_present(session: dict[str, Any]) -> bool:
    """True when this browser still looks joined (presence may be offline)."""
    code = _room_code(session)
    if not code:
        return False
    pid = _participant_id(session)
    team = str(
        session.get("draft_room_participant_team")
        or session.get("room_your_team")
        or ""
    ).strip()
    room = session.get("live_draft_room")
    has_room = isinstance(room, dict) and bool(
        room.get("draft_room_id") or room.get("draft_id") or room.get("status")
    )
    return bool(pid or team or has_room)


def _try_reattach_from_document(
    session: dict[str, Any],
    doc: dict[str, Any],
    *,
    code: str,
) -> bool:
    """Restore team/pointers when the participant is still in the authoritative doc."""
    pid = _participant_id(session)
    if not pid:
        # Prefer durable auth id over a freshly minted anonymous: id.
        for key in ("auth_user_id", "_suite_auth_user_id"):
            cand = str(session.get(key) or "").strip()
            if cand and not cand.startswith("anonymous:"):
                pid = cand
                session["draft_room_participant_id"] = pid
                break
    if not pid:
        return False
    ok, team = participant_in_document(doc, pid)
    if not ok:
        return False
    session["active_shared_draft_room_code"] = str(code or "").strip().upper()
    if team:
        session["draft_room_participant_team"] = team
        session["room_your_team"] = team
    try:
        from draft_room_context import publish_shared_room_runtime

        publish_shared_room_runtime(session, doc, reason="membership_reattach")
    except Exception:
        blob = doc.get("room") if isinstance(doc.get("room"), dict) else None
        if isinstance(blob, dict):
            session["live_draft_room"] = dict(blob)
    session[MEMBERSHIP_GATE_DIAG_KEY] = {
        "ok": True,
        "reason": "reattached",
        "room_code": code,
        "participant_id": pid,
        "team": team,
    }
    return True


def repair_stale_shared_room_session(
    session: dict[str, Any],
    *,
    force_document_load: bool = True,
    allow_soft_miss: bool = True,
) -> dict[str, Any]:
    """Wipe local pointers only when membership is confirmed gone (not on soft miss)."""
    code = _room_code(session)
    if not code and not isinstance(session.get("live_draft_room"), dict):
        return {"repaired": False, "reason": "nothing_to_repair"}

    # Solo live drafts have no shared room code — leave them alone.
    if not code:
        room = session.get("live_draft_room")
        if isinstance(room, dict):
            sync = room.get("sync") if isinstance(room.get("sync"), dict) else {}
            if not sync.get("room_code") and not room.get("room_code"):
                return {"repaired": False, "reason": "solo_live_draft"}

    doc = (
        load_authoritative_shared_document(session, code, force=force_document_load)
        if code
        else None
    )
    ok, reason = can_render_shared_live_draft(
        session,
        document=doc if isinstance(doc, dict) else None,
        require_team_claim=False,
    )
    if ok:
        return {"repaired": False, "reason": "membership_valid", "room_code": code}

    # Soft miss: temporary load failure / auth blip — keep membership pointers.
    soft_reasons = {"room_missing", "no_participant_id"}
    if allow_soft_miss and reason in soft_reasons and _local_membership_markers_present(session):
        session[MEMBERSHIP_GATE_DIAG_KEY] = {
            "ok": False,
            "reason": reason,
            "soft_miss": True,
            "kept_membership": True,
            "room_code": code,
        }
        return {
            "repaired": False,
            "reason": f"soft_miss:{reason}",
            "room_code": code,
            "kept_membership": True,
        }

    # Confirmed document load: try reattach before wiping.
    if isinstance(doc, dict) and _try_reattach_from_document(session, doc, code=code):
        return {"repaired": False, "reason": "reattached", "room_code": code}

    # Hard fail only: doc says not a member / terminal / tombstone.
    diag = clear_stale_shared_room_local_state(session, reason=reason)
    diag["repaired"] = True
    diag["prior_room_code"] = code
    return diag


def _resume_lobby_may_render(session: dict[str, Any], reason: str) -> tuple[bool, str] | None:
    """Allow Resume Lobby paint without wiping Continue Saved Draft hydration."""
    try:
        from live_draft_resume_lobby import RESUME_LOBBY_KEY, is_resume_lobby

        in_lobby = bool(session.get(RESUME_LOBBY_KEY)) or is_resume_lobby(session)
    except ImportError:
        in_lobby = bool(session.get("_live_draft_resume_lobby"))
    if not in_lobby:
        return None
    # Terminal / tombstoned rooms must still fail closed.
    if reason == "tombstoned" or str(reason).startswith("terminal:"):
        return None
    soft = {
        "not_in_document_participants",
        "no_team_claim",
        "no_participant_id",
        "room_missing",
        "local_room_id_mismatch",
        "local_room_code_mismatch",
    }
    if reason not in soft:
        return None
    session[MEMBERSHIP_GATE_DIAG_KEY] = {
        "ok": False,
        "reason": reason,
        "deferred_repair": True,
        "resume_lobby": True,
    }
    return True, f"resume_lobby:{reason}"


def assert_or_repair_before_shared_render(session: dict[str, Any]) -> tuple[bool, str]:
    """Call before painting active shared draft UI. Returns (may_render, reason).

    Soft misses (temporary room_missing / auth blip) keep membership and allow
    render. Hard fails (confirmed not in document) clear local pointers.
    """
    code = _room_code(session)
    if not code:
        # No shared code — solo path may still render.
        return True, "solo_or_setup"

    doc = load_authoritative_shared_document(session, code)
    ok, reason = can_render_shared_live_draft(
        session, document=doc if isinstance(doc, dict) else None, require_team_claim=False
    )
    if ok:
        return True, reason

    # Soft miss with local membership still present — do not kick out.
    if reason in {"room_missing", "no_participant_id"} and _local_membership_markers_present(session):
        session[MEMBERSHIP_GATE_DIAG_KEY] = {
            "ok": False,
            "reason": reason,
            "soft_miss": True,
            "kept_membership": True,
            "room_code": code,
        }
        return True, f"soft_miss:{reason}"

    # Authoritative doc available — reattach if still a member under another id key.
    if isinstance(doc, dict) and _try_reattach_from_document(session, doc, code=code):
        return True, "reattached"

    # Continue Saved Draft / Resume Lobby: never wipe hydrated room on soft miss.
    resume_allow = _resume_lobby_may_render(session, reason)
    if resume_allow is not None:
        return resume_allow
    # Brand-new create: do not wipe the room on a transient readback miss.
    try:
        from live_draft_creation_trace import new_room_is_protected

        if new_room_is_protected(session):
            session[MEMBERSHIP_GATE_DIAG_KEY] = {
                "ok": False,
                "reason": reason,
                "deferred_repair": True,
                "protect_new_room": True,
            }
            # Allow lobby paint for the host; next poll can re-verify.
            return True, f"protected_new_room:{reason}"
    except ImportError:
        pass
    # Parked / saved_for_later documents with reserved teams — keep lobby pointers.
    try:
        status = str((doc or {}).get("status") or "").strip().lower() if isinstance(doc, dict) else ""
        reserved = (doc or {}).get("resume_reserved_teams") if isinstance(doc, dict) else None
        if status in ("saved_for_later", "parked", "paused") and isinstance(reserved, dict) and reserved:
            session[MEMBERSHIP_GATE_DIAG_KEY] = {
                "ok": False,
                "reason": reason,
                "deferred_repair": True,
                "saved_for_later": True,
            }
            session["_live_draft_resume_lobby"] = True
            return True, f"saved_for_later:{reason}"
    except Exception:
        pass

    # Confirmed hard failure — wipe only when document loaded and membership gone,
    # or terminal/tombstone. Never wipe solely because one read returned None.
    if reason in {"room_missing"} and _local_membership_markers_present(session):
        return True, f"soft_miss:{reason}"
    repair_stale_shared_room_session(session, allow_soft_miss=False)
    return False, reason
