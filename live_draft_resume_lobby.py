"""Resume Lobby for Save & Continue Later shared drafts.

A parked shared draft must not resume drafting until every reserved
participant-controlled team has rejoined. The commissioner then presses
Continue Draft to resume from the exact saved pick.
"""

from __future__ import annotations

from typing import Any

RESUME_LOBBY_KEY = "_live_draft_resume_lobby"
RESUME_RESERVED_KEY = "_live_draft_resume_reserved_teams"


def _human_teams_from_document(document: dict[str, Any] | None) -> list[str]:
    if not isinstance(document, dict):
        return []
    room = document.get("room") if isinstance(document.get("room"), dict) else {}
    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    if not teams:
        cfg = dict(room.get("config") or {})
        n = int(cfg.get("num_teams") or 0)
        teams = [f"Team {i + 1}" for i in range(n)] if n else []
    # Drop CPU/placeholder seats from the required-rejoin set.
    try:
        from live_draft_team_ownership import _is_cpu_or_placeholder_team

        return [t for t in teams if not _is_cpu_or_placeholder_team(t)]
    except ImportError:
        return teams


def reserved_team_owners(document: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map team → reserved owner metadata from the parked document / slot."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(document, dict):
        return out
    participants = dict(document.get("participants") or {})
    for pid, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        out[team] = {
            "participant_id": str(pid).strip(),
            "display_name": str(meta.get("display_name") or pid).strip(),
            "team": team,
            "is_commissioner": str(pid).strip()
            == str(
                document.get("commissioner_participant_id")
                or document.get("host_participant_id")
                or ""
            ).strip(),
        }
    # Prefer explicit reserved snapshot stamped at park time.
    reserved = document.get("resume_reserved_teams")
    if isinstance(reserved, dict) and reserved:
        for team, meta in reserved.items():
            if isinstance(meta, dict) and str(team).strip():
                out[str(team).strip()] = {
                    "participant_id": str(meta.get("participant_id") or "").strip(),
                    "display_name": str(meta.get("display_name") or meta.get("participant_id") or "").strip(),
                    "team": str(team).strip(),
                    "is_commissioner": bool(meta.get("is_commissioner")),
                }
    return out


def stamp_resume_reserved_on_document(document: dict[str, Any]) -> dict[str, Any]:
    """Freeze team→owner map so resume never reassigns seats."""
    reserved = reserved_team_owners(document)
    document["resume_reserved_teams"] = reserved
    document["status"] = "saved_for_later"
    # Force everyone to explicitly rejoin the Resume Lobby.
    document["joined_participants"] = {}
    document["resume_rejoined"] = {}
    room = document.get("room")
    if isinstance(room, dict):
        room["status"] = "saved_for_later"
        room["paused"] = True
    return document


def mark_resume_rejoined(
    document: dict[str, Any],
    *,
    participant_id: str,
) -> dict[str, Any]:
    pid = str(participant_id or "").strip()
    if not pid:
        return document
    rejoined = dict(document.get("resume_rejoined") or {})
    rejoined[pid] = True
    document["resume_rejoined"] = rejoined
    return document


def resume_lobby_rows(
    session: dict[str, Any],
    document: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Rows for Resume Lobby UI: reserved owner + rejoined / waiting."""
    reserved = reserved_team_owners(document)
    present_pids: set[str] = set()
    if isinstance(document, dict):
        # Authoritative rejoin set — do not treat leftover participants/joined maps as present.
        for pid, flag in dict(document.get("resume_rejoined") or {}).items():
            if flag:
                present_pids.add(str(pid).strip())
    # Current session counts as rejoined for its reserved team only.
    try:
        from draft_room_participant_state import resolve_participant_id

        me = str(resolve_participant_id(session) or "").strip()
        if me and any(str(m.get("participant_id") or "") == me for m in reserved.values()):
            present_pids.add(me)
    except ImportError:
        pass

    rows: list[dict[str, Any]] = []
    for team, meta in reserved.items():
        pid = str(meta.get("participant_id") or "").strip()
        rejoined = bool(pid and pid in present_pids)
        rows.append(
            {
                "team": team,
                "participant_id": pid,
                "display_name": str(meta.get("display_name") or pid or "—"),
                "is_commissioner": bool(meta.get("is_commissioner")),
                "rejoined": rejoined,
                "status_label": "Rejoined" if rejoined else "Waiting",
            }
        )
    rows.sort(key=lambda r: (0 if r.get("is_commissioner") else 1, str(r.get("team") or "")))
    return rows


def all_required_participants_rejoined(
    session: dict[str, Any],
    document: dict[str, Any] | None,
) -> tuple[bool, int, int]:
    rows = resume_lobby_rows(session, document)
    if not rows:
        # Solo / no reserved map — allow continue.
        return True, 0, 0
    ready = sum(1 for r in rows if r.get("rejoined"))
    total = len(rows)
    return ready >= total and total > 0, ready, total


def enter_resume_lobby(session: dict[str, Any], *, document: dict[str, Any] | None = None) -> None:
    session[RESUME_LOBBY_KEY] = True
    if isinstance(document, dict):
        session[RESUME_RESERVED_KEY] = reserved_team_owners(document)
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        room["status"] = "paused"
        room["paused"] = True
        # Keep timer frozen — never arm deadline in resume lobby.
        room.pop("pick_deadline_ts", None)
        room["timer_paused"] = True


def exit_resume_lobby(session: dict[str, Any]) -> None:
    session.pop(RESUME_LOBBY_KEY, None)
    session.pop(RESUME_RESERVED_KEY, None)


def is_resume_lobby(session: dict[str, Any]) -> bool:
    return bool(session.get(RESUME_LOBBY_KEY))


def continue_draft_from_resume_lobby(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Commissioner-only: leave lobby and resume drafting from the saved pick."""
    try:
        from shared_draft_permissions import is_canonical_commissioner

        if not is_canonical_commissioner(session, document):
            return {"ok": False, "error": "commissioner_only", "message": "Only the commissioner may continue the draft."}
    except ImportError:
        from draft_room_membership import is_room_host

        if not is_room_host(session, document):
            return {"ok": False, "error": "commissioner_only", "message": "Only the commissioner may continue the draft."}

    ready, ready_n, total_n = all_required_participants_rejoined(session, document)
    if not ready:
        return {
            "ok": False,
            "error": "waiting_participants",
            "message": f"Waiting for participants ({ready_n} of {total_n} rejoined).",
            "ready": ready_n,
            "total": total_n,
        }

    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return {"ok": False, "error": "no_room", "message": "No draft room to continue."}

    exit_resume_lobby(session)
    room["status"] = "in_progress"
    room["paused"] = False
    room["timer_paused"] = False
    try:
        from live_draft_timer_logic import live_draft_resume_timer

        pause_left = int(
            room.get("paused_remaining_seconds")
            or (room.get("config") or {}).get("timer_seconds")
            or 60
        )
        live_draft_resume_timer(room, pause_left)
    except ImportError:
        pass
    try:
        from live_draft_state import commit_live_draft_room, write_canonical_live_draft_state

        write_canonical_live_draft_state(session, room)
        if st is not None:
            commit_live_draft_room(st, session, room, reason="continue_from_resume_lobby")
    except Exception:
        session["live_draft_room"] = room

    # Mark backend document active again.
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if code:
        try:
            from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

            doc = document if isinstance(document, dict) else load_shared_room(code)
            if isinstance(doc, dict):
                updated = bump_revision(doc)
                updated["status"] = "in_progress"
                blob = updated.get("room")
                if isinstance(blob, dict):
                    blob["status"] = "in_progress"
                    blob.update({k: room.get(k) for k in ("current_pick_index", "draft_board", "pick_order") if k in room})
                get_shared_room_store().save(updated)
        except Exception:
            pass

    try:
        from live_draft_resumable_slot import clear_resumable_live_draft_slot

        clear_resumable_live_draft_slot(session)
    except ImportError:
        pass

    return {"ok": True, "room": room, "ready": ready_n, "total": total_n}
