"""Durable timer authority lease + expired-pick watchdog for Live Draft rooms."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

TIMER_AUTHORITY_KEY = "timer_authority"
TIMER_AUTHORITY_LEASE_SEC = 8.0
TIMER_AUTHORITY_HEARTBEAT_SEC = 3.0
WATCHDOG_STALL_SEC = 2.0
WATCHDOG_DIAG_KEY = "_live_draft_timer_watchdog_diag"


def _utc_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _utc_iso(ts: float | None = None) -> str:
    t = float(ts if ts is not None else _utc_now())
    return datetime.fromtimestamp(t, tz=timezone.utc).replace(microsecond=0).isoformat()


def _viewer_user_id(session: dict[str, Any]) -> str:
    try:
        from suite_auth import AUTH_USER_ID_KEY

        uid = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if uid:
            return uid
    except ImportError:
        pass
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return str(session.get("draft_room_participant_id") or "").strip()


def normalize_timer_authority(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    user_id = str(raw.get("user_id") or "").strip()
    if not user_id:
        return None
    try:
        lease = float(raw.get("lease_expires_at") or 0)
    except (TypeError, ValueError):
        lease = 0.0
    try:
        heartbeat = float(raw.get("heartbeat_at") or 0)
    except (TypeError, ValueError):
        heartbeat = 0.0
    return {
        "user_id": user_id,
        "lease_expires_at": lease,
        "heartbeat_at": heartbeat,
        "updated_at": str(raw.get("updated_at") or ""),
    }


def authority_from_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(document, dict):
        return None
    return normalize_timer_authority(document.get(TIMER_AUTHORITY_KEY))


def authority_is_active(authority: dict[str, Any] | None, *, now: float | None = None) -> bool:
    auth = normalize_timer_authority(authority)
    if not auth:
        return False
    t = float(now if now is not None else _utc_now())
    return float(auth.get("lease_expires_at") or 0) > t


def viewer_holds_authority(
    session: dict[str, Any],
    document: dict[str, Any] | None = None,
    *,
    now: float | None = None,
) -> bool:
    uid = _viewer_user_id(session)
    if not uid:
        return False
    auth = authority_from_document(document)
    if not authority_is_active(auth, now=now):
        return False
    assert auth is not None
    return str(auth.get("user_id") or "").strip().lower() == uid.lower()


def build_authority_lease(session: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    t = float(now if now is not None else _utc_now())
    return {
        "user_id": _viewer_user_id(session),
        "lease_expires_at": t + TIMER_AUTHORITY_LEASE_SEC,
        "heartbeat_at": t,
        "updated_at": _utc_iso(t),
    }


def try_acquire_timer_authority(
    session: dict[str, Any],
    *,
    store: Any = None,
    prefer_host: bool = True,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Compare-and-swap timer authority onto the shared room document.

    Returns (acquired_or_held, reason, document).
    """
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_membership import is_room_host
        from draft_room_shared_state import (
            ACTIVE_SHARED_ROOM_CODE_KEY,
            get_shared_room_store,
            invalidate_shared_room_document_cache,
        )
    except ImportError:
        return True, "solo_or_import_missing", None

    if not is_multiplayer_draft_active(session):
        return True, "solo_local", None

    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not code:
        return False, "no_room_code", None

    backend = store or get_shared_room_store()
    invalidate_shared_room_document_cache(session, code)
    document = backend.load(code)
    if not isinstance(document, dict):
        return False, "document_missing", None

    now = _utc_now()
    uid = _viewer_user_id(session)
    if not uid:
        return False, "no_user_id", document

    current = authority_from_document(document)
    if authority_is_active(current, now=now):
        assert current is not None
        if str(current.get("user_id") or "").strip().lower() == uid.lower():
            # Renew lease.
            lease = build_authority_lease(session, now=now)
            document = dict(document)
            document[TIMER_AUTHORITY_KEY] = lease
            expected = int(document.get("revision") or 0)
            # Authority renewals must not bump board revision — write sidecar only.
            ok, saved = _save_authority_sidecar(backend, document, expected_revision=expected)
            if ok and isinstance(saved, dict):
                return True, "renewed", saved
            return True, "held_renew_failed", document
        return False, "held_by_other", document

    # Prefer host when lease is free and viewer is not host.
    if prefer_host and not is_room_host(session, document):
        # Non-host may still acquire when lease is expired (watchdog takeover).
        pass

    lease = build_authority_lease(session, now=now)
    if not lease.get("user_id"):
        return False, "empty_user", document
    outgoing = dict(document)
    outgoing[TIMER_AUTHORITY_KEY] = lease
    expected = int(document.get("revision") or 0)
    ok, saved = _save_authority_sidecar(backend, outgoing, expected_revision=expected)
    if ok and isinstance(saved, dict):
        return True, "acquired", saved
    # Conflict — reload and check if we somehow hold it.
    latest = backend.load(code)
    if viewer_holds_authority(session, latest, now=_utc_now()):
        return True, "acquired_after_conflict", latest if isinstance(latest, dict) else None
    return False, "cas_conflict", latest if isinstance(latest, dict) else document


def _save_authority_sidecar(
    backend: Any,
    document: dict[str, Any],
    *,
    expected_revision: int,
) -> tuple[bool, dict[str, Any] | None]:
    """Persist timer_authority without bumping board revision when possible."""
    payload = dict(document)
    # Keep revision stable so authority heartbeats do not thrash guests.
    payload["revision"] = int(expected_revision)
    payload["updated_at"] = _utc_iso()
    try:
        save_if = getattr(backend, "save_if_revision", None)
        if callable(save_if):
            return save_if(payload, expected_revision=expected_revision)
        saved = backend.save(payload)
        return True, saved if isinstance(saved, dict) else payload
    except Exception:
        return False, None


def multiparty_may_run_autopick(session: dict[str, Any]) -> bool:
    """True when this client should attempt expiration (host preferred, lease takeover allowed)."""
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_membership import is_room_host
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, load_shared_room_document

        if not is_multiplayer_draft_active(session):
            return True
        code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        document = load_shared_room_document(session, code) if code else None
        if viewer_holds_authority(session, document):
            try_acquire_timer_authority(session)  # renew
            return True
        auth = authority_from_document(document)
        if authority_is_active(auth):
            return False
        # Lease free/expired — host first, otherwise any joined participant for watchdog.
        if is_room_host(session, document):
            ok, _reason, _doc = try_acquire_timer_authority(session, prefer_host=True)
            return ok
        # Watchdog takeover path.
        if expired_pick_needs_watchdog(session, session.get("live_draft_room") or {}):
            ok, _reason, _doc = try_acquire_timer_authority(session, prefer_host=False)
            return ok
        return False
    except ImportError:
        return True


def expired_pick_needs_watchdog(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """True when deadline passed by WATCHDOG_STALL_SEC and pick has not advanced."""
    if not isinstance(room, dict):
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        deadline = float(room.get("timer_deadline") or 0)
    except (TypeError, ValueError):
        return False
    if deadline <= 0:
        return False
    stall = _utc_now() - deadline
    if stall < WATCHDOG_STALL_SEC:
        return False
    return True


def record_watchdog_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    diag = dict(session.get(WATCHDOG_DIAG_KEY) or {})
    diag.update({k: v for k, v in fields.items() if v is not None})
    diag["recorded_at"] = _utc_iso()
    session[WATCHDOG_DIAG_KEY] = diag
    return diag


def extract_live_head_fields(document: dict[str, Any] | None) -> dict[str, Any]:
    """Lightweight fields used by the room poller (no pool / projections)."""
    if not isinstance(document, dict):
        return {}
    room = document.get("room")
    if not isinstance(room, dict):
        room = document.get("live_room") if isinstance(document.get("live_room"), dict) else {}
    pick_order = list((room or {}).get("pick_order") or [])
    idx = int((room or {}).get("current_pick_index") or 0)
    team = ""
    if 0 <= idx < len(pick_order) and isinstance(pick_order[idx], dict):
        team = str(pick_order[idx].get("Team") or "").strip()
    if not team:
        team = str((room or {}).get("on_clock_team") or "").strip()
    deadline = (room or {}).get("timer_deadline")
    try:
        deadline_f = float(deadline) if deadline is not None else None
    except (TypeError, ValueError):
        deadline_f = None
    auth = normalize_timer_authority(document.get(TIMER_AUTHORITY_KEY))
    return {
        "room_revision": int(document.get("revision") or 0),
        "status": str(document.get("status") or (room or {}).get("status") or ""),
        "room_status": str((room or {}).get("status") or ""),
        "current_pick_index": idx,
        "current_team": team,
        "timer_deadline": deadline_f,
        "updated_at": str(document.get("updated_at") or ""),
        "timer_authority_user_id": str((auth or {}).get("user_id") or ""),
        "timer_authority_lease_expires_at": float((auth or {}).get("lease_expires_at") or 0) or None,
    }
