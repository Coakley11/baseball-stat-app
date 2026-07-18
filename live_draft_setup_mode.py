"""Live Draft Room setup mode — solo vs shared multiplayer."""

from __future__ import annotations

from typing import Any

LIVE_DRAFT_SETUP_MODE_KEY = "live_draft_setup_mode"
SETUP_MODE_SOLO = "solo"
SETUP_MODE_SHARED = "shared_multiplayer"
DRAFT_SETUP_MODE_CONFIG_KEY = "draft_setup_mode"
LAST_PERSISTED_SETUP_MODE_KEY = "_live_draft_setup_mode_last_persisted"
MODE_TRACE_KEY = "_live_draft_setup_mode_trace"
# Programmatic mode change after st.radio — applied next run before the widget binds.
PENDING_LIVE_DRAFT_SETUP_MODE_KEY = "_pending_live_draft_setup_mode"
# True after Draft Mode radio is created in this Streamlit run.
WIDGET_MODE_LOCKED_KEY = "_live_draft_setup_mode_widget_locked"
# Legacy competing Streamlit radio key — never write/read this for mode again.
LEGACY_MODE_RADIO_LABEL_KEY = "_live_draft_mode_radio_label"

SETUP_MODE_OPTIONS = (SETUP_MODE_SOLO, SETUP_MODE_SHARED)
SETUP_MODE_LABELS = {
    SETUP_MODE_SOLO: "Solo Draft — you control all teams (no room code)",
    SETUP_MODE_SHARED: "Shared Multiplayer Draft Room — room code, other users join",
}


def normalize_setup_mode(mode: str | None) -> str:
    raw = str(mode or "").strip().lower()
    if raw in (SETUP_MODE_SHARED, "multiplayer", "shared"):
        return SETUP_MODE_SHARED
    if "shared" in raw and "multiplayer" in raw:
        return SETUP_MODE_SHARED
    if raw.startswith("shared"):
        return SETUP_MODE_SHARED
    return SETUP_MODE_SOLO


def get_live_draft_setup_mode(session: dict[str, Any], *, room: dict[str, Any] | None = None) -> str:
    """Return Draft Mode with setup-safe precedence.

    1) Explicit session/widget ``live_draft_setup_mode`` (user click wins)
    2) Active picking room stamp (in_progress / paused only)
    3) Default solo

    Lobby/not_started/completed room stamps must not override the widget —
    that caused Shared → Solo snap-back when a leftover solo lobby existed.
    """
    session_mode = session.get(LIVE_DRAFT_SETUP_MODE_KEY)
    if str(session_mode or "").strip():
        return normalize_setup_mode(session_mode)

    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        status = str(live.get("status") or "").strip()
        cfg = live.get("config") or {}
        stored = str(cfg.get(DRAFT_SETUP_MODE_CONFIG_KEY) or "").strip()
        if stored and status in ("in_progress", "paused"):
            return normalize_setup_mode(stored)
    return SETUP_MODE_SOLO


def _stamp_room_setup_mode(session: dict[str, Any], normalized: str) -> None:
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return
    status = str(room.get("status") or "").strip()
    if status not in ("", "not_started", "in_progress", "paused"):
        return
    cfg = dict(room.get("config") or {})
    cfg[DRAFT_SETUP_MODE_CONFIG_KEY] = normalized
    room["config"] = cfg


def is_setup_mode_widget_locked(session: dict[str, Any]) -> bool:
    """True after ``st.radio(key=live_draft_setup_mode)`` in the current run."""
    return bool(session.get(WIDGET_MODE_LOCKED_KEY))


def mark_setup_mode_widget_locked(session: dict[str, Any]) -> None:
    session[WIDGET_MODE_LOCKED_KEY] = True


def persist_live_draft_setup_mode_preference(
    session: dict[str, Any],
    mode: str,
    *,
    st: Any = None,
) -> str:
    """Persist Draft Mode to preferences without assigning the widget session key."""
    normalized = normalize_setup_mode(mode)
    _stamp_room_setup_mode(session, normalized)
    if session.get("_live_draft_setup_seeding"):
        session[LAST_PERSISTED_SETUP_MODE_KEY] = normalized
        return normalized
    try:
        from live_draft_setup_persist import mark_live_draft_setup_dirty
        from user_page_preferences import (
            PAGE_KEY_LIVE_DRAFT_SETUP,
            collect_live_draft_setup_settings,
            save_user_page_preferences,
        )

        last_raw = session.get(LAST_PERSISTED_SETUP_MODE_KEY)
        if last_raw is not None and normalize_setup_mode(last_raw) == normalized:
            return normalized
        mark_live_draft_setup_dirty(session)
        uid = str(session.get("auth_user_id") or "").strip()
        wid = str(
            session.get("_suite_active_workspace_id")
            or session.get("_suite_owned_workspace_id")
            or session.get("workspace_id")
            or ""
        ).strip()
        settings = collect_live_draft_setup_settings(session)
        settings[LIVE_DRAFT_SETUP_MODE_KEY] = normalized
        save_user_page_preferences(
            uid,
            wid,
            PAGE_KEY_LIVE_DRAFT_SETUP,
            settings,
            session=session,
            st=st,
            force_disk=bool(st is not None),
        )
        session[LAST_PERSISTED_SETUP_MODE_KEY] = normalized
    except ImportError:
        session[LAST_PERSISTED_SETUP_MODE_KEY] = normalized
    return normalized


def request_live_draft_setup_mode(
    session: dict[str, Any],
    mode: str,
    *,
    persist: bool = False,
    st: Any = None,
) -> str:
    """Programmatic mode change that is safe before or after the Draft Mode radio.

    If the radio already owns ``live_draft_setup_mode`` this run, queue a pending
    value applied at the start of the next rerun (before ``st.radio``).
    """
    normalized = normalize_setup_mode(mode)
    if is_setup_mode_widget_locked(session):
        session[PENDING_LIVE_DRAFT_SETUP_MODE_KEY] = normalized
    else:
        session[LIVE_DRAFT_SETUP_MODE_KEY] = normalized
    _stamp_room_setup_mode(session, normalized)
    if persist:
        persist_live_draft_setup_mode_preference(session, normalized, st=st)
    return normalized


def apply_pending_live_draft_setup_mode(session: dict[str, Any]) -> str | None:
    """Apply queued mode at the start of a run, before the radio is created."""
    session.pop(WIDGET_MODE_LOCKED_KEY, None)
    pending = session.pop(PENDING_LIVE_DRAFT_SETUP_MODE_KEY, None)
    if pending is None:
        return None
    normalized = normalize_setup_mode(pending)
    session[LIVE_DRAFT_SETUP_MODE_KEY] = normalized
    return normalized


def set_live_draft_setup_mode(
    session: dict[str, Any],
    mode: str,
    *,
    persist: bool = False,
    st: Any = None,
    write_session: bool = True,
) -> str:
    """Set Draft Mode.

    Classification:
      - pre-widget init: write_session=True (default) while unlocked
      - radio response: use ``commit_live_draft_mode_from_widget`` (never writes key)
      - post-widget programmatic: auto-defers via pending when locked
    """
    normalized = normalize_setup_mode(mode)
    if write_session:
        if is_setup_mode_widget_locked(session):
            return request_live_draft_setup_mode(session, normalized, persist=persist, st=st)
        session[LIVE_DRAFT_SETUP_MODE_KEY] = normalized
    _stamp_room_setup_mode(session, normalized)
    if persist:
        persist_live_draft_setup_mode_preference(session, normalized, st=st)
    return normalized


def seed_live_draft_setup_mode_before_widget(session: dict[str, Any]) -> str:
    """Seed canonical mode once before radio creation. Never overwrites an existing value."""
    session.pop(LEGACY_MODE_RADIO_LABEL_KEY, None)
    apply_pending_live_draft_setup_mode(session)

    existing = session.get(LIVE_DRAFT_SETUP_MODE_KEY)
    if str(existing or "").strip():
        if existing not in SETUP_MODE_OPTIONS:
            # Migrate legacy display-label values into canonical tokens before bind.
            session[LIVE_DRAFT_SETUP_MODE_KEY] = normalize_setup_mode(existing)
        return normalize_setup_mode(session.get(LIVE_DRAFT_SETUP_MODE_KEY))

    preferred = SETUP_MODE_SOLO
    try:
        from user_page_preferences import PAGE_KEY_LIVE_DRAFT_SETUP, get_user_page_preferences

        uid = str(session.get("auth_user_id") or "").strip()
        wid = str(
            session.get("_suite_active_workspace_id")
            or session.get("_suite_owned_workspace_id")
            or session.get("workspace_id")
            or ""
        ).strip()
        settings = get_user_page_preferences(uid, wid, PAGE_KEY_LIVE_DRAFT_SETUP, session=session) or {}
        preferred = normalize_setup_mode(settings.get(LIVE_DRAFT_SETUP_MODE_KEY))
    except ImportError:
        preferred = SETUP_MODE_SOLO

    session[LIVE_DRAFT_SETUP_MODE_KEY] = preferred
    return preferred


def commit_live_draft_mode_from_widget(
    session: dict[str, Any],
    selected: str,
    *,
    st: Any = None,
) -> str:
    """After radio render: stamp room + persist. Do not reassign the widget key."""
    normalized = normalize_setup_mode(selected)
    mark_setup_mode_widget_locked(session)
    _stamp_room_setup_mode(session, normalized)
    persist_live_draft_setup_mode_preference(session, normalized, st=st)
    return normalized


def record_setup_mode_trace(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    trace = dict(session.get(MODE_TRACE_KEY) or {})
    if not isinstance(trace, dict):
        trace = {}
    trace.update({k: v for k, v in fields.items() if v is not None})
    session[MODE_TRACE_KEY] = trace
    return trace


def is_solo_draft_mode(session: dict[str, Any], *, room: dict[str, Any] | None = None) -> bool:
    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            return False
    except ImportError:
        pass
    return get_live_draft_setup_mode(session, room=room) == SETUP_MODE_SOLO


def is_shared_multiplayer_intent(session: dict[str, Any], *, room: dict[str, Any] | None = None) -> bool:
    return get_live_draft_setup_mode(session, room=room) == SETUP_MODE_SHARED


def shared_room_code(session: dict[str, Any]) -> str:
    try:
        from draft_room_context import resolve_shared_room_code

        return str(resolve_shared_room_code(session) or "").strip().upper()
    except ImportError:
        return str(session.get("active_shared_draft_room_code") or "").strip().upper()


def shared_room_ready_for_start(session: dict[str, Any]) -> bool:
    if not shared_room_code(session):
        return False
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        return True
    # Session runtime can be cleared by unrelated persistence helpers; rehydrate
    # from the shared room document so Start Draft still works.
    try:
        from draft_room_shared_state import document_to_runtime_room, load_shared_room

        code = shared_room_code(session)
        doc = load_shared_room(code)
        runtime = document_to_runtime_room(doc) if isinstance(doc, dict) else None
        if isinstance(runtime, dict):
            session["live_draft_room"] = runtime
            return True
    except Exception:
        pass
    return False


def can_start_live_draft(session: dict[str, Any]) -> tuple[bool, str]:
    if is_shared_multiplayer_intent(session):
        if not shared_room_ready_for_start(session):
            return (
                False,
                "Create the shared draft room first — a 6-character room code is required before starting.",
            )
        room = session.get("live_draft_room")
        if not isinstance(room, dict):
            return False, "Draft room is not ready to start."
        if str(room.get("status") or "") not in ("not_started", "in_progress", "paused"):
            return False, "Draft room is not ready to start."
        try:
            from draft_room_shared_state import (
                ACTIVE_SHARED_ROOM_CODE_KEY,
                invalidate_shared_room_document_cache,
                load_shared_room_document,
            )
            from live_draft_presence import (
                count_required_joined,
                mark_participant_present,
                missing_participant_labels,
            )
            from live_draft_team_ownership import distinct_claimed_owner_count, list_room_teams

            code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            # Always reload latest shared room before evaluating the start gate.
            if code:
                invalidate_shared_room_document_cache(session, code)
                try:
                    from draft_room_context import refresh_shared_lobby_authority

                    document = refresh_shared_lobby_authority(session, force_poll=True)
                except ImportError:
                    mark_participant_present(session, force_save=True)
                    document = load_shared_room_document(session, code, force=True)
                else:
                    mark_participant_present(session, force_save=True)
                    if not isinstance(document, dict):
                        document = load_shared_room_document(session, code, force=True)
            else:
                document = None

            from live_draft_team_ownership import list_required_human_teams

            teams = list_required_human_teams(room, document=document if isinstance(document, dict) else None)
            if not teams:
                teams = list_room_teams(room)
            joined, total, rows = count_required_joined(session, room, document=document)
            if total < 1:
                return False, "No claimed managers yet — invite and claim teams before starting."
            if joined < total:
                missing = missing_participant_labels(rows)
                if missing:
                    return (
                        False,
                        f"Waiting for {', '.join(missing)} to join the Live Draft Room "
                        f"({joined} of {total} required participants joined).",
                    )
                waiting = max(0, total - joined)
                return (
                    False,
                    f"Waiting for {waiting} more participant(s) to join before starting "
                    f"({joined} of {total} joined).",
                )
            distinct = distinct_claimed_owner_count(session, room)
            if len(teams) >= 2 and distinct < 2:
                return (
                    False,
                    "Two distinct authenticated managers must claim teams before starting "
                    "(one user cannot control both teams in Phase 1).",
                )
            if total < 2 and len(teams) >= 2:
                return False, "At least two managers must claim teams before starting the draft."
        except ImportError:
            pass
        return True, ""
    return True, ""


def stamp_room_setup_mode(room: dict[str, Any], session: dict[str, Any]) -> None:
    mode = get_live_draft_setup_mode(session)
    cfg = dict(room.get("config") or {})
    cfg[DRAFT_SETUP_MODE_CONFIG_KEY] = mode
    room["config"] = cfg


def start_prepared_shared_room(session: dict[str, Any], st_obj: Any) -> dict[str, Any]:
    """Start an already-prepared not_started shared room without rebuilding the pool."""
    result: dict[str, Any] = {"handled": False, "ok": False, "error": ""}
    if not is_shared_multiplayer_intent(session):
        return result
    code = shared_room_code(session)
    room = session.get("live_draft_room")
    if not code or not isinstance(room, dict) or str(room.get("status") or "") != "not_started":
        return result
    result["handled"] = True
    try:
        from live_draft_timer_logic import live_draft_reset_timer
    except ImportError:
        result["error"] = "Live draft timer helpers unavailable."
        return result

    room["status"] = "in_progress"
    live_draft_reset_timer(room)
    session["live_draft_room"] = room
    user_team = str((room.get("config") or {}).get("your_team") or (room.get("config") or {}).get("user_team") or "")
    if user_team:
        session["room_your_team"] = user_team
    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE, set_canonical_draft_meta

        set_canonical_draft_meta(
            session,
            mode=ACTIVE_DRAFT_MODE_LIVE,
            source="start_prepared_shared_room",
            pick_count=len(room.get("draft_board") or []),
        )
    except ImportError:
        pass
    try:
        from live_draft_state import commit_live_draft_room

        commit_live_draft_room(st_obj, session, room, reason="start_draft")
    except ImportError:
        pass
    try:
        from draft_room_context import commit_shared_room_state, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            ok, msg, _ = commit_shared_room_state(session, room)
            if not ok and msg:
                result["error"] = msg
                result["ok"] = False
                return result
    except ImportError:
        pass
    result["ok"] = True
    session["_live_draft_start_feedback"] = (
        f"Shared multiplayer draft started — Room Code **{code}**. Invite players with this code."
    )
    return result


def setup_is_read_only(room: dict[str, Any]) -> bool:
    """After the first pick, draft setup cannot be edited."""
    board = room.get("draft_board") or []
    return bool(isinstance(board, list) and len(board) > 0)


def is_shared_lobby(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return False
    return is_shared_multiplayer_intent(session, room=live) and str(live.get("status") or "") == "not_started"


def should_show_full_draft_setup(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    """Full setup panel only before any live draft room exists."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    return not isinstance(live, dict)


def should_hide_legacy_shared_panel(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    """Compact lobby/live UI replaces the legacy top shared panel when a room code exists."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return False
    if is_shared_multiplayer_intent(session, room=live) and shared_room_code(session):
        return True
    return False


def finalize_shared_room_create(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    host_team: str,
    store: Any = None,
) -> tuple[str, str]:
    """Create shared room for a not_started live room. Returns (code, error)."""
    # Drop private simulator runtime so Pick N / simulator source cannot override
    # this new Live Draft. Saved Draft Library archives are untouched.
    try:
        from live_draft_navigation import clear_private_baseball_simulator_runtime

        clear_private_baseball_simulator_runtime(session, reason="shared_room_create")
    except ImportError:
        pass
    stamp_room_setup_mode(room, session)
    session["live_draft_room"] = room
    session["room_your_team"] = host_team
    try:
        from draft_room_create_verify import merge_create_flow_diagnostics

        merge_create_flow_diagnostics(
            session,
            room_create_attempted=True,
            shared_draft_room_id=str(room.get("draft_room_id") or "").strip(),
            room_status=str(room.get("status") or "not_started"),
        )
    except ImportError:
        pass
    try:
        from draft_room_context import create_and_host_shared_room

        code, _doc = create_and_host_shared_room(session, room, host_team=host_team, store=store)
    except ImportError as exc:
        return "", str(exc)
    if not code:
        err = str(session.pop("_draft_room_last_error", "") or "").strip()
        err = err or "Could not create shared room. This draft cannot be joined by others."
        try:
            from draft_room_create_verify import merge_create_flow_diagnostics

            merge_create_flow_diagnostics(session, room_create_ok=False, room_create_error=err)
        except ImportError:
            pass
        return "", err
    try:
        from draft_room_create_verify import merge_create_flow_diagnostics
        from live_draft_team_ownership import claimed_team_count, distinct_claimed_owner_count, load_shared_participants

        merge_create_flow_diagnostics(
            session,
            room_create_ok=True,
            room_create_error="",
            join_code=code,
            join_code_present=True,
            cloud_write_ok=True,
            cloud_readback_ok=True,
            shared_draft_room_id=str(room.get("draft_room_id") or "").strip(),
            room_status=str(room.get("status") or "not_started"),
            participant_count=len(load_shared_participants(session)),
            claimed_team_count=claimed_team_count(session, room),
            distinct_owner_count=distinct_claimed_owner_count(session, room),
        )
    except ImportError:
        pass
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(
            type("S", (), {"session_state": session})(),
            reason="shared_draft_room_create",
        )
    except (ImportError, Exception):
        pass
    return code, ""
