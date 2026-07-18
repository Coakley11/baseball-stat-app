"""Single resumable Live Draft slot — distinct from active room and Saved Draft Library."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

RESUMABLE_LIVE_DRAFT_SLOT_KEY = "resumable_live_draft_slot"
REPLACE_RESUMABLE_CONFIRM_KEY = "_live_draft_replace_resumable_confirm"
SAVE_CONTINUE_FLASH_KEY = "_live_draft_save_continue_flash"

# Cleared when parking a draft into the resumable slot (not tombstoned).
PARK_CLEAR_ACTIVE_KEYS = (
    "live_draft_room",
    "live_draft_state",
    "active_shared_draft_room_code",
    "draft_room_shared_meta",
    "draft_room_participant_team",
    "draft_room_participant_id",
    "draft_room_participant_notes",
    "room_your_team",
    "live_draft_my_team",
    "active_draft_source",
    "_active_draft_source",
    "_shared_lobby_authority_doc",
    "_shared_room_doc_soft_cache",
    "_live_draft_rec_cache",
    "_live_draft_timer_expired_pending",
    "_live_draft_page_owns_expired",
    "_live_draft_poll_diag",
    "_live_draft_poll_apply_pending",
    "show_live_draft",
    "draft_started",
    "live_draft_active",
    "_live_draft_start_feedback",
    "_shared_draft_room_created_flash",
    "_draft_join_flash",
    "_simulator_to_live_show_confirm",
    "_live_draft_history_view",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_resumable_live_draft_slot(session: dict[str, Any]) -> dict[str, Any] | None:
    slot = session.get(RESUMABLE_LIVE_DRAFT_SLOT_KEY)
    if not isinstance(slot, dict):
        return None
    if str(slot.get("kind") or "") != "resumable_live_draft_slot":
        return None
    if not slot.get("room") and not slot.get("room_code"):
        return None
    return slot


def clear_resumable_live_draft_slot(session: dict[str, Any]) -> None:
    session.pop(RESUMABLE_LIVE_DRAFT_SLOT_KEY, None)
    session.pop(REPLACE_RESUMABLE_CONFIRM_KEY, None)


def resumable_slot_matches_draft(
    session: dict[str, Any],
    *,
    draft_id: str = "",
    room_code: str = "",
) -> bool:
    slot = get_resumable_live_draft_slot(session)
    if not slot:
        return False
    did = str(draft_id or "").strip()
    code = str(room_code or "").strip().upper()
    if did and str(slot.get("draft_id") or "").strip() == did:
        return True
    if code and str(slot.get("room_code") or "").strip().upper() == code:
        return True
    return False


def resumable_slot_summary(slot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(slot, dict):
        return {}
    summary = dict(slot.get("summary") or {})
    return {
        "mode_label": str(summary.get("mode_label") or slot.get("mode") or "Draft"),
        "num_teams": int(summary.get("num_teams") or 0),
        "current_pick": int(summary.get("current_pick") or 0),
        "total_picks": int(summary.get("total_picks") or 0),
        "league_name": str(summary.get("league_name") or ""),
        "saved_at": str(slot.get("saved_at") or ""),
        "room_code": str(slot.get("room_code") or ""),
        "is_shared": bool(slot.get("is_shared")),
    }


def _room_ids(session: dict[str, Any], room: dict[str, Any]) -> tuple[str, str, str]:
    draft_id = str(
        room.get("draft_room_id")
        or room.get("draft_id")
        or (room.get("config") or {}).get("draft_id")
        or ""
    ).strip()
    room_id = str(room.get("room_id") or draft_id or "").strip()
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        try:
            from draft_room_context import resolve_shared_room_code

            code = str(resolve_shared_room_code(session) or "").strip().upper()
        except ImportError:
            pass
    if not code:
        cfg = dict(room.get("config") or {})
        code = str(room.get("room_code") or cfg.get("room_code") or "").strip().upper()
    return draft_id, room_id, code


def _build_summary(session: dict[str, Any], room: dict[str, Any], *, is_shared: bool) -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    teams = list(room.get("teams") or cfg.get("teams") or [])
    board = room.get("draft_board") if isinstance(room.get("draft_board"), list) else []
    current_pick = int(room.get("current_pick_index") or 0) + 1
    total = int(cfg.get("total_picks") or 0)
    if not total:
        try:
            from live_draft_safe_mode import total_expected_picks

            total = int(total_expected_picks(room) or 0)
        except ImportError:
            rounds = int(cfg.get("num_rounds") or cfg.get("rounds") or 0)
            total = rounds * max(1, len(teams)) if rounds else len(board)
    mode_label = "Shared Multiplayer" if is_shared else "Solo Draft"
    return {
        "mode_label": mode_label,
        "num_teams": len(teams) or int(cfg.get("num_teams") or 0),
        "current_pick": current_pick,
        "total_picks": total or max(current_pick, len(board)),
        "league_name": str(cfg.get("league_name") or room.get("league_name") or "Live Draft").strip(),
        "pick_count": len(board),
        "on_clock_team": str((room.get("pick_order") or [{}])[int(room.get("current_pick_index") or 0)].get("Team") or "")
        if isinstance(room.get("pick_order"), list)
        and room.get("pick_order")
        and int(room.get("current_pick_index") or 0) < len(room.get("pick_order") or [])
        else "",
    }


def _persist_room_blob(room: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_state import room_to_persist_dict

        return room_to_persist_dict(room)
    except ImportError:
        import copy

        blob = copy.deepcopy(room)
        blob.pop("pool", None)
        return blob


def _collect_queues(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "draft_queue": list(session.get("draft_queue") or []),
        "watchlist_focus": list(session.get("watchlist_focus") or []),
        "watchlist_favorites": list(session.get("watchlist_favorites") or []),
    }
    try:
        from draft_room_participant_state import PARTICIPANT_STATE_KEY

        ps = session.get(PARTICIPANT_STATE_KEY)
        if isinstance(ps, dict):
            out["participant_state"] = ps
    except ImportError:
        pass
    return out


def pause_and_persist_for_save(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    """Pause timer and park the shared backend as saved_for_later when applicable."""
    try:
        from live_draft_timer_logic import live_draft_pause_timer

        if str(room.get("status") or "") == "in_progress":
            live_draft_pause_timer(room)
        else:
            room["status"] = "paused"
    except ImportError:
        room["status"] = "paused"

    room["status"] = "saved_for_later"
    room["paused"] = True
    room["timer_paused"] = True
    room.pop("pick_deadline_ts", None)
    session["live_draft_room"] = room
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if code:
        try:
            from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

            doc = load_shared_room(code)
            if isinstance(doc, dict):
                updated = bump_revision(doc)
                try:
                    from live_draft_resume_lobby import stamp_resume_reserved_on_document

                    stamp_resume_reserved_on_document(updated)
                except ImportError:
                    updated["status"] = "saved_for_later"
                updated["room"] = _persist_room_blob(room)
                if isinstance(updated.get("room"), dict):
                    updated["room"]["status"] = "saved_for_later"
                    updated["room"]["paused"] = True
                get_shared_room_store().save(updated)
                try:
                    from draft_room_shared_state import invalidate_shared_room_document_cache

                    invalidate_shared_room_document_cache(session, code)
                except Exception:
                    pass
        except Exception:
            pass
    return room


def build_resumable_slot(
    session: dict[str, Any],
    room: dict[str, Any],
) -> dict[str, Any]:
    draft_id, room_id, code = _room_ids(session, room)
    is_shared = bool(code)
    try:
        from live_draft_setup_mode import resolve_active_live_draft_mode

        active = resolve_active_live_draft_mode(session, authoritative_room=room)
        is_shared = bool(active.get("is_shared_multiplayer")) or is_shared
        mode = "shared_multiplayer" if is_shared else "solo"
    except Exception:
        mode = "shared_multiplayer" if is_shared else "solo"

    slot = {
        "kind": "resumable_live_draft_slot",
        "saved_at": _utc_now_iso(),
        "mode": mode,
        "is_shared": is_shared,
        "draft_id": draft_id,
        "room_id": room_id,
        "room_code": code or None,
        "summary": _build_summary(session, room, is_shared=is_shared),
        "room": _persist_room_blob(room),
        "queues": _collect_queues(session),
        "participant_team": str(session.get("draft_room_participant_team") or "").strip() or None,
        "participant_id": str(session.get("draft_room_participant_id") or "").strip() or None,
    }
    return slot


def save_resumable_live_draft_slot(
    session: dict[str, Any],
    slot: dict[str, Any],
    *,
    st: Any | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Persist the single resumable slot (replaces prior slot when allowed)."""
    existing = get_resumable_live_draft_slot(session)
    if existing and not replace_existing:
        same = (
            str(existing.get("draft_id") or "") == str(slot.get("draft_id") or "")
            and str(existing.get("room_code") or "").upper() == str(slot.get("room_code") or "").upper()
        )
        if not same:
            return {
                "ok": False,
                "needs_replace_confirm": True,
                "existing": existing,
                "message": (
                    "A resumable draft is already saved. Saving this draft will replace it. "
                    "Save the previous draft to Draft Library first if you want a historical copy."
                ),
            }
    session[RESUMABLE_LIVE_DRAFT_SLOT_KEY] = slot
    session.pop(REPLACE_RESUMABLE_CONFIRM_KEY, None)
    try:
        from baseball_persistent_state import force_save_baseball_state

        if st is not None:
            force_save_baseball_state(st, reason="resumable_live_draft_slot")
        else:
            force_save_baseball_state(
                type("S", (), {"session_state": session})(),
                reason="resumable_live_draft_slot",
            )
    except Exception:
        pass
    return {"ok": True, "slot": slot, "replaced": bool(existing)}


def park_active_to_setup_after_save(session: dict[str, Any], *, st: Any | None = None) -> None:
    """Leave the active runtime so setup shows Continue Saved Draft (draft is not deleted)."""
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    for key in PARK_CLEAR_ACTIVE_KEYS:
        session.pop(key, None)
    session.pop("_live_draft_resume_lobby", None)
    try:
        from live_draft_state import clear_live_draft_state

        # Clear active runtime only — resumable slot remains.
        clear_live_draft_state(session, reason="park_resumable_slot")
    except Exception:
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)
    # Soft-leave membership so refresh does not revive the parked room as ACTIVE.
    if code:
        try:
            from draft_room_participant_state import mark_participant_left_room, resolve_participant_id

            mark_participant_left_room(
                session, code, participant_id=resolve_participant_id(session)
            )
        except Exception:
            pass
    # Re-seed setup prefs for the clean setup page.
    try:
        from user_page_preferences import (
            ensure_live_draft_setup_preferences_loaded,
            restore_live_draft_setup_mode_preference,
        )

        session.pop("_prefs_initialized:live_draft_setup", None)
        restore_live_draft_setup_mode_preference(session)
        ensure_live_draft_setup_preferences_loaded(session)
    except ImportError:
        pass
    try:
        from live_draft_state import commit_live_draft_room

        if st is not None:
            commit_live_draft_room(st, session, None, reason="park_resumable_slot")
    except Exception:
        pass


def save_and_continue_later(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Pause, persist into the single resumable slot, and return to setup."""
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return {"ok": False, "error": "no_active_room", "message": "No active Live Draft to save."}

    room = pause_and_persist_for_save(session, room)
    slot = build_resumable_slot(session, room)
    saved = save_resumable_live_draft_slot(
        session, slot, st=st, replace_existing=replace_existing
    )
    if not saved.get("ok"):
        return saved

    park_active_to_setup_after_save(session, st=st)
    summary = resumable_slot_summary(slot)
    session[SAVE_CONTINUE_FLASH_KEY] = {
        "message": (
            f"Draft saved for later — {summary.get('mode_label')} · "
            f"Pick {summary.get('current_pick')} of {summary.get('total_picks')}. "
            "Use **Continue Saved Draft** on this page to resume."
        ),
        "saved_at": slot.get("saved_at"),
    }
    return {"ok": True, "slot": slot, "summary": summary}


def continue_saved_draft(
    session: dict[str, Any],
    *,
    st: Any | None = None,
) -> dict[str, Any]:
    """Explicitly restore the resumable slot into Resume Lobby (shared) or active room (solo)."""
    slot = get_resumable_live_draft_slot(session)
    if not slot:
        return {"ok": False, "error": "no_slot", "message": "No saved draft to continue."}

    draft_id = str(slot.get("draft_id") or "").strip()
    code = str(slot.get("room_code") or "").strip().upper()
    try:
        from live_draft_termination import is_live_draft_permanently_retired

        if is_live_draft_permanently_retired(session, draft_id=draft_id, room_code=code):
            clear_resumable_live_draft_slot(session)
            return {
                "ok": False,
                "error": "tombstoned",
                "message": "That saved draft was permanently deleted and cannot be resumed.",
            }
    except ImportError:
        pass

    room: dict[str, Any] | None = None
    document: dict[str, Any] | None = None
    if code:
        try:
            from draft_room_shared_state import load_shared_room, shared_document_room_blob

            doc = load_shared_room(code)
            if isinstance(doc, dict):
                document = doc
                status = str(doc.get("status") or "").strip().lower()
                if status in ("ended", "closed", "deleted"):
                    clear_resumable_live_draft_slot(session)
                    return {
                        "ok": False,
                        "error": "room_ended",
                        "message": "This draft has ended and cannot be resumed.",
                    }
                blob = shared_document_room_blob(doc)
                if isinstance(blob, dict):
                    room = dict(blob)
                # Rebind membership pointers for shared resume.
                session["active_shared_draft_room_code"] = code
                try:
                    from draft_room_context import publish_shared_room_runtime
                    from draft_room_participant_state import clear_participant_left_room

                    clear_participant_left_room(session, code)
                    publish_shared_room_runtime(session, doc, reason="continue_saved_draft")
                    room = (
                        session.get("live_draft_room")
                        if isinstance(session.get("live_draft_room"), dict)
                        else room
                    )
                except Exception:
                    pass
        except Exception as exc:
            session["_live_draft_continue_saved_diag"] = {
                "ok": False,
                "error": "load_failed",
                "detail": str(exc)[:200],
                "room_code": code,
            }

    if room is None:
        raw = slot.get("room")
        if isinstance(raw, dict):
            room = dict(raw)

    if not isinstance(room, dict):
        return {
            "ok": False,
            "error": "missing_room",
            "message": (
                "Saved draft data is incomplete or the shared room could not be loaded. "
                "Try Replace and Start New Draft, or recreate the room."
            ),
        }

    # Always enter paused — shared drafts open Resume Lobby until everyone rejoins.
    # Keep timer frozen; do not invent a deadline.
    room["status"] = "paused"
    room["paused"] = True
    room["timer_paused"] = True
    room.pop("pick_deadline_ts", None)
    room.pop("timer_deadline", None)
    session["live_draft_room"] = room
    if code:
        session["active_shared_draft_room_code"] = code
    team = str(slot.get("participant_team") or "").strip()
    if team:
        session["draft_room_participant_team"] = team
        session["room_your_team"] = team
    pid = str(slot.get("participant_id") or "").strip()
    if not pid:
        try:
            from draft_room_participant_state import resolve_participant_id

            pid = str(resolve_participant_id(session) or "").strip()
        except ImportError:
            pid = str(session.get("auth_user_id") or "").strip()
    if pid:
        session["draft_room_participant_id"] = pid

    queues = slot.get("queues") if isinstance(slot.get("queues"), dict) else {}
    if queues:
        session["draft_queue"] = list(queues.get("draft_queue") or [])
        session["watchlist_focus"] = list(queues.get("watchlist_focus") or [])
        session["watchlist_favorites"] = list(queues.get("watchlist_favorites") or [])
        ps = queues.get("participant_state")
        if isinstance(ps, dict):
            try:
                from draft_room_participant_state import PARTICIPANT_STATE_KEY

                session[PARTICIPANT_STATE_KEY] = ps
            except ImportError:
                pass

    try:
        from live_draft_state import commit_live_draft_room, write_canonical_live_draft_state

        write_canonical_live_draft_state(session, room)
        if st is not None:
            commit_live_draft_room(st, session, room, reason="continue_saved_draft")
    except Exception:
        pass

    is_shared = bool(code) or bool(slot.get("is_shared"))
    if is_shared:
        try:
            from live_draft_resume_lobby import enter_resume_lobby, mark_resume_rejoined

            enter_resume_lobby(session, document=document)
            # Install lobby flag before any gate / lifecycle pass.
            session["_live_draft_resume_lobby"] = True
            if isinstance(document, dict) and pid:
                from draft_room_shared_state import bump_revision, get_shared_room_store

                # Ensure commissioner/guest remains registered on the parked document.
                parts = dict(document.get("participants") or {})
                if pid not in parts and team:
                    parts[pid] = {
                        "assigned_team": team,
                        "display_name": str(session.get("auth_user_id") or pid),
                    }
                    document["participants"] = parts
                document = mark_resume_rejoined(document, participant_id=pid)
                # Keep backend parked — Resume Lobby until Continue Draft.
                document["status"] = "saved_for_later"
                blob = document.get("room")
                if isinstance(blob, dict):
                    blob["status"] = "paused"
                    blob["paused"] = True
                    blob["timer_paused"] = True
                    blob.pop("timer_deadline", None)
                updated = bump_revision(document)
                get_shared_room_store().save(updated)
                document = updated
        except ImportError:
            session["_live_draft_resume_lobby"] = True
        except Exception as exc:
            session["_live_draft_resume_lobby"] = True
            session["_live_draft_continue_saved_diag"] = {
                "ok": True,
                "warning": "resume_doc_save_failed",
                "detail": str(exc)[:200],
            }

    # Sticky success so a membership soft-miss cannot look like a silent no-op.
    session["_live_draft_continue_saved_flash"] = {
        "ok": True,
        "resume_lobby": bool(is_shared),
        "room_code": code,
        "draft_id": draft_id,
        "message": (
            "Resume Lobby opened — waiting for reserved teams before Continue Draft."
            if is_shared
            else "Saved draft restored."
        ),
    }

    try:
        from baseball_persistent_state import force_save_baseball_state

        if st is not None:
            force_save_baseball_state(st, reason="continue_saved_draft")
    except Exception:
        pass

    return {
        "ok": True,
        "room": room,
        "slot": slot,
        "resume_lobby": bool(is_shared),
        "document": document,
    }


def replace_resumable_and_arm_start(
    session: dict[str, Any],
    *,
    st: Any | None = None,
) -> dict[str, Any]:
    """Permanently discard the resumable slot and arm a fresh Pick-1 create.

    Preserves setup preferences (mode, team/pick counts, timer, scoring, roster).
    Shared mode arms ``prepare_shared`` so a new room code is created.
    """
    slot = get_resumable_live_draft_slot(session)
    draft_id = str((slot or {}).get("draft_id") or "").strip()
    room_id = str((slot or {}).get("room_id") or draft_id or "").strip()
    code = str((slot or {}).get("room_code") or "").strip().upper()
    is_shared = bool((slot or {}).get("is_shared")) or bool(code)

    # Authoritative discard of the old resumable room (backend + tombstones).
    # Parked drafts have no active live_draft_room — tombstone by identity + close backend.
    try:
        from live_draft_termination import persist_durable_tombstones

        persist_durable_tombstones(session, draft_id=draft_id, room_id=room_id, room_code=code)
    except ImportError:
        pass
    if code:
        try:
            from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

            doc = load_shared_room(code)
            if isinstance(doc, dict):
                doc["status"] = "deleted"
                blob = doc.get("room")
                if isinstance(blob, dict):
                    blob["status"] = "deleted"
                get_shared_room_store().save(bump_revision(doc))
        except Exception:
            pass

    clear_resumable_live_draft_slot(session)
    for key in PARK_CLEAR_ACTIVE_KEYS:
        session.pop(key, None)
    session.pop("_live_draft_resume_lobby", None)
    session.pop("_live_draft_resume_reserved_teams", None)
    session.pop("_live_draft_start_replace_resumable_pending", None)
    session.pop("_live_draft_start_replace_resumable_message", None)
    session.pop("_live_draft_replace_confirm_pending", None)

    # Arm create — Shared uses prepare_shared (new code); Solo uses new.
    try:
        from live_draft_setup_mode import SETUP_MODE_SHARED, get_preferred_next_draft_mode, is_shared_multiplayer_intent

        prefer_shared = is_shared or is_shared_multiplayer_intent(session)
        if not prefer_shared:
            prefer_shared = get_preferred_next_draft_mode(session) == SETUP_MODE_SHARED
    except ImportError:
        prefer_shared = is_shared

    session["_live_draft_start_replace_resumable_ok"] = True
    session["_live_draft_replace_create_fresh"] = True
    session["_start_live_draft_mode"] = "prepare_shared" if prefer_shared else "new"
    session["_start_live_draft_pending"] = True
    session["_live_draft_replace_flash"] = {
        "ok": True,
        "message": "Saved draft discarded. Starting a new draft at Pick 1…",
        "prior_room_code": code,
        "mode": session["_start_live_draft_mode"],
    }
    try:
        from baseball_persistent_state import force_save_baseball_state

        if st is not None:
            force_save_baseball_state(st, reason="replace_resumable_and_arm_start")
    except Exception:
        pass
    return {
        "ok": True,
        "mode": session["_start_live_draft_mode"],
        "prior_room_code": code,
        "prior_draft_id": draft_id,
    }


def warn_if_starting_replaces_resumable(session: dict[str, Any]) -> dict[str, Any] | None:
    """Return warning payload when a new draft would replace the resumable slot."""
    slot = get_resumable_live_draft_slot(session)
    if not slot:
        return None
    summary = resumable_slot_summary(slot)
    return {
        "message": (
            "A resumable draft is already saved "
            f"({summary.get('mode_label')}, Pick {summary.get('current_pick')} of {summary.get('total_picks')}). "
            "Starting a new draft will replace it. Save it to Draft Library first if you want to keep a historical copy."
        ),
        "slot": slot,
        "summary": summary,
    }
