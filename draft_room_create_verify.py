"""Post-create verification for shared draft rooms."""

from __future__ import annotations

import string
from typing import Any

from draft_room_shared_state import ROOM_CODE_ALPHABET, ROOM_CODE_LEN, document_to_runtime_room


def normalize_room_code(room_code: str | None) -> str:
    return str(room_code or "").strip().upper()


def is_plausible_share_code(room_code: str | None) -> bool:
    """True for a 6-character shared join code (not an internal draft session id)."""
    code = normalize_room_code(room_code)
    if len(code) != ROOM_CODE_LEN:
        return False
    return all(ch in ROOM_CODE_ALPHABET for ch in code)


def looks_like_internal_draft_session_id(value: str | None) -> bool:
    """Heuristic: uuid[:8] session ids are 8 hex-ish chars — not join codes."""
    raw = normalize_room_code(value)
    if len(raw) != 8:
        return False
    return all(ch in (string.digits + "ABCDEF") for ch in raw)


def share_code_hint(value: str | None) -> str:
    code = normalize_room_code(value)
    if not code:
        return ""
    if is_plausible_share_code(code):
        return ""
    if looks_like_internal_draft_session_id(code):
        return (
            f"**{code}** looks like an internal session ID (8 characters), not a "
            f"**{ROOM_CODE_LEN}-character share code**. Ask the host for the share code shown "
            "after **Create Shared Draft Room** succeeds."
        )
    return f"**{code}** is not a valid {ROOM_CODE_LEN}-character share code."


def init_create_flow_diagnostics(session: dict[str, Any], *, clicked: bool = False) -> dict[str, Any]:
    """Reset/create the host create-flow diagnostic blob."""
    diag: dict[str, Any] = {
        "create_button_clicked": bool(clicked),
        "generated_share_code": "",
        "internal_draft_session_id": "",
        "supabase_save_attempted": False,
        "supabase_save_success": False,
        "immediate_load_success": False,
        "valid_runtime_room": False,
        "shared_room_code_displayed_to_user": False,
    }
    session["_draft_room_create_diag"] = diag
    return diag


def merge_create_flow_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    raw = session.get("_draft_room_create_diag")
    diag = dict(raw) if isinstance(raw, dict) else init_create_flow_diagnostics(session)
    for key, value in fields.items():
        if value is not None:
            diag[key] = value
    session["_draft_room_create_diag"] = diag
    return diag


def shared_room_document_stats(document: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize a shared room document for diagnostics."""
    if not isinstance(document, dict):
        return {
            "room_code": "",
            "revision": None,
            "status": "",
            "pool_count": 0,
            "picks_count": 0,
            "team_count": 0,
            "draft_room_id": "",
            "valid_runtime": False,
        }
    room = document.get("room") if isinstance(document.get("room"), dict) else {}
    board = room.get("draft_board") or []
    pool_records = room.get("pool_records") or []
    teams = room.get("teams") or []
    runtime = document_to_runtime_room(document)
    return {
        "room_code": normalize_room_code(document.get("room_code")),
        "revision": int(document.get("revision") or 0) or None,
        "status": str(document.get("status") or room.get("status") or ""),
        "pool_count": len(pool_records) if isinstance(pool_records, list) else 0,
        "picks_count": len(board) if isinstance(board, list) else 0,
        "team_count": len(teams) if isinstance(teams, list) else 0,
        "draft_room_id": str(document.get("draft_room_id") or room.get("draft_room_id") or ""),
        "valid_runtime": isinstance(runtime, dict) and bool(runtime.get("draft_room_id")),
    }


def validate_shared_room_document(document: dict[str, Any] | None) -> tuple[bool, str]:
    """Return (ok, message) when document is safe to hydrate into session."""
    if not isinstance(document, dict):
        return False, "Shared room document is missing."
    code = normalize_room_code(document.get("room_code"))
    if not code:
        return False, "Shared room document is missing room_code."
    room = document.get("room")
    if not isinstance(room, dict) or not room:
        return False, "Shared room JSON is empty — draft board was not saved."
    draft_room_id = str(document.get("draft_room_id") or room.get("draft_room_id") or "").strip()
    if not draft_room_id:
        return False, "Shared room JSON is missing draft_room_id."
    teams = room.get("teams") or []
    if not isinstance(teams, list) or not teams:
        return False, "Shared room JSON is missing teams."
    board = room.get("draft_board")
    if board is not None and not isinstance(board, list):
        return False, "Shared room draft_board is invalid."
    runtime = document_to_runtime_room(document)
    if runtime is None:
        return False, "Shared room JSON could not be converted to a live draft room."
    if not str(runtime.get("status") or "").strip():
        return False, "Shared room is missing draft status."
    return True, ""


def load_shared_room_with_diagnostics(
    store: Any,
    room_code: str,
) -> dict[str, Any]:
    """Load a room and report whether Supabase returned empty vs query error."""
    code = normalize_room_code(room_code)
    backend = "unknown"
    try:
        from draft_room_shared_state import shared_room_backend_name

        backend = shared_room_backend_name()
    except ImportError:
        pass

    loader = getattr(store, "load_with_diagnostics", None)
    if callable(loader):
        result = loader(code)
        if isinstance(result, dict):
            result.setdefault("backend", backend)
            result.setdefault("room_code_queried", code)
            return result

    try:
        document = store.load(code)
    except Exception as exc:
        return {
            "found": False,
            "document": None,
            "reason": "query_error",
            "query_error": str(exc),
            "backend": backend,
            "room_code_queried": code,
        }
    if not isinstance(document, dict):
        return {
            "found": False,
            "document": None,
            "reason": "not_found",
            "query_error": None,
            "backend": backend,
            "room_code_queried": code,
        }
    return {
        "found": True,
        "document": document,
        "reason": None,
        "query_error": None,
        "backend": backend,
        "room_code_queried": code,
    }


def verify_shared_room_persisted(
    store: Any,
    room_code: str,
    *,
    saved_document: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Confirm create wrote a loadable, valid room row."""
    code = normalize_room_code(room_code)
    load_result = load_shared_room_with_diagnostics(store, code)
    diagnostics: dict[str, Any] = {
        "room_code": code,
        "save_result": shared_room_document_stats(saved_document),
        "load_result": {
            "found": load_result.get("found"),
            "reason": load_result.get("reason"),
            "query_error": load_result.get("query_error"),
            "backend": load_result.get("backend"),
        },
    }
    try:
        from draft_room_shared_state import shared_room_backend_name

        diagnostics["save_result"]["backend"] = shared_room_backend_name()
    except ImportError:
        pass

    if not load_result.get("found"):
        reason = str(load_result.get("reason") or "not_found")
        if reason == "query_error":
            detail = str(load_result.get("query_error") or "Supabase query failed")
            return False, f"Create verification failed: {detail}", diagnostics
        return False, f"Create saved but room **{code}** was not found in Supabase.", diagnostics

    loaded = load_result.get("document")
    ok, msg = validate_shared_room_document(loaded if isinstance(loaded, dict) else None)
    stats = shared_room_document_stats(loaded if isinstance(loaded, dict) else None)
    diagnostics["immediate_load"] = stats
    diagnostics["immediate_load_success"] = bool(load_result.get("found"))
    diagnostics["valid_runtime_room"] = bool(stats.get("valid_runtime"))
    if not ok:
        return False, msg, diagnostics
    return True, "", diagnostics
