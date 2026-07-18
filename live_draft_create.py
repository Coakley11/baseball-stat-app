"""Canonical Live Draft create results — Solo and Shared.

The Streamlit start handler still owns pool build; these helpers normalize the
durable success/failure contract and cleanup rules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def creation_result(
    *,
    success: bool,
    mode: str,
    draft_id: str = "",
    room_id: str = "",
    room_code: str = "",
    room_generation: Any = None,
    commissioner_participant_id: str = "",
    lifecycle: str = "",
    setup_preferences_saved: bool = False,
    error: str = "",
    step: str = "",
    partial_created: bool = False,
) -> dict[str, Any]:
    return {
        "success": bool(success),
        "mode": str(mode or ""),
        "draft_id": str(draft_id or "").strip(),
        "room_id": str(room_id or draft_id or "").strip(),
        "room_code": str(room_code or "").strip().upper(),
        "room_generation": room_generation,
        "commissioner_participant_id": str(commissioner_participant_id or "").strip(),
        "lifecycle": str(lifecycle or ""),
        "setup_preferences_saved": bool(setup_preferences_saved),
        "creation_timestamp": _utc_now(),
        "error": str(error or ""),
        "step": str(step or ""),
        "partial_created": bool(partial_created),
    }


def cleanup_partial_create(session: dict[str, Any], *, room_code: str = "") -> None:
    """Best-effort cleanup when Shared create fails after a partial write."""
    code = str(room_code or session.get("active_shared_draft_room_code") or "").strip().upper()
    session.pop("live_draft_room", None)
    session.pop("live_draft_state", None)
    session.pop("active_shared_draft_room_code", None)
    if not code:
        return
    try:
        from draft_room_shared_state import get_shared_room_store

        store = get_shared_room_store()
        if hasattr(store, "delete"):
            store.delete(code)
        elif hasattr(store, "remove"):
            store.remove(code)
    except Exception:
        pass


def result_from_session_room(
    session: dict[str, Any],
    *,
    success: bool,
    mode: str,
    lifecycle: str = "",
    error: str = "",
    step: str = "",
    setup_preferences_saved: bool = False,
) -> dict[str, Any]:
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    draft_id = str(room.get("draft_room_id") or room.get("draft_id") or "").strip()
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code and isinstance(room, dict):
        code = str(room.get("room_code") or (room.get("config") or {}).get("room_code") or "").strip().upper()
    commissioner = str(session.get("draft_room_participant_id") or "").strip()
    generation = None
    try:
        from draft_room_shared_state import load_shared_room_document

        doc = load_shared_room_document(session, code) if code else None
        if isinstance(doc, dict):
            generation = doc.get("revision") or doc.get("generation") or doc.get("deletion_generation")
            commissioner = str(
                doc.get("commissioner_participant_id") or commissioner or ""
            ).strip()
    except Exception:
        pass
    return creation_result(
        success=success,
        mode=mode,
        draft_id=draft_id,
        room_id=draft_id,
        room_code=code,
        room_generation=generation,
        commissioner_participant_id=commissioner,
        lifecycle=lifecycle,
        setup_preferences_saved=setup_preferences_saved,
        error=error,
        step=step,
        partial_created=bool(room) and not success,
    )
