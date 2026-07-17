"""Shared Live Draft participant presence — joined state persisted on the room document."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

JOINED_PARTICIPANTS_KEY = "joined_participants"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_participant_user_id(session: dict[str, Any]) -> str:
    """Stable authenticated identity — never display name alone."""
    # Prefer explicit auth / account ids from the session before Streamlit fallbacks.
    for key in (
        "auth_user_id",
        "_suite_cloud_user_id",
        "_suite_auth_user_id",
        "draft_room_participant_id",
    ):
        val = str(session.get(key) or "").strip()
        if val and not val.startswith(("local:", "anonymous:", "demo:")):
            return val
    try:
        from suite_auth import AUTH_USER_ID_KEY

        val = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if val and not val.startswith(("local:", "anonymous:", "demo:")):
            return val
    except ImportError:
        pass
    try:
        from draft_room_participant_state import resolve_participant_id

        pid = str(resolve_participant_id(session) or "").strip()
        if pid and not pid.startswith(("local:", "anonymous:", "demo:")):
            return pid
        # Last resort only when no authenticated id exists.
        if pid:
            return pid
    except ImportError:
        pass
    return ""


def _workspace_id(session: dict[str, Any]) -> str:
    try:
        from suite_user import current_workspace_id

        return str(current_workspace_id(session) or "").strip()
    except ImportError:
        pass
    return str(session.get("active_workspace_id") or session.get("workspace_id") or "").strip()


def _claimed_team_for_user(session: dict[str, Any], document: dict[str, Any] | None) -> str:
    try:
        from draft_room_participant_state import active_participant_team

        team = str(active_participant_team(session) or "").strip()
        if team:
            return team
    except ImportError:
        pass
    team = str(session.get("room_your_team") or "").strip()
    if team:
        return team
    uid = canonical_participant_user_id(session)
    if uid and isinstance(document, dict):
        participants = dict(document.get("participants") or {})
        meta = participants.get(uid)
        if isinstance(meta, dict):
            return str(meta.get("assigned_team") or "").strip()
        # Alias match via email / external id fields that may still be present.
        for meta in participants.values():
            if not isinstance(meta, dict):
                continue
            for key in ("user_id", "account_user_id", "participant_id", "external_id"):
                if str(meta.get(key) or "").strip() == uid:
                    return str(meta.get("assigned_team") or "").strip()
    return ""


def normalize_joined_participants(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        uid = str(val.get("user_id") or key or "").strip()
        if not uid:
            continue
        out[uid] = {
            "user_id": uid,
            "workspace_id": str(val.get("workspace_id") or "").strip(),
            "team_name": str(val.get("team_name") or val.get("assigned_team") or "").strip(),
            "display_name": str(val.get("display_name") or "").strip(),
            "joined_at": str(val.get("joined_at") or "").strip() or _utc_now_iso(),
            "last_seen_at": str(val.get("last_seen_at") or val.get("joined_at") or "").strip()
            or _utc_now_iso(),
        }
    return out


def merge_joined_participants(
    outgoing: dict[str, Any] | None,
    existing: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Union join records — never drop a remote participant on a stale soft-cache write."""
    base = normalize_joined_participants((existing or {}).get(JOINED_PARTICIPANTS_KEY) if isinstance(existing, dict) else {})
    newer = normalize_joined_participants((outgoing or {}).get(JOINED_PARTICIPANTS_KEY) if isinstance(outgoing, dict) else {})
    merged = dict(base)
    for uid, row in newer.items():
        prev = merged.get(uid) or {}
        merged[uid] = {
            "user_id": uid,
            "workspace_id": row.get("workspace_id") or prev.get("workspace_id") or "",
            "team_name": row.get("team_name") or prev.get("team_name") or "",
            "display_name": row.get("display_name") or prev.get("display_name") or "",
            "joined_at": prev.get("joined_at") or row.get("joined_at") or _utc_now_iso(),
            "last_seen_at": max(
                str(row.get("last_seen_at") or ""),
                str(prev.get("last_seen_at") or ""),
            )
            or _utc_now_iso(),
        }
    return merged


def reconcile_joined_from_participants(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Ensure every claimed participant appears in joined_participants."""
    joined = normalize_joined_participants(document.get(JOINED_PARTICIPANTS_KEY))
    participants = dict(document.get("participants") or {})
    for pid, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        uid = str(meta.get("user_id") or meta.get("account_user_id") or pid).strip() or str(pid)
        prev = joined.get(uid) or {}
        joined[uid] = {
            "user_id": uid,
            "workspace_id": str(prev.get("workspace_id") or meta.get("workspace_id") or "").strip(),
            "team_name": team,
            "display_name": str(
                meta.get("display_name") or prev.get("display_name") or ""
            ).strip(),
            "joined_at": str(prev.get("joined_at") or meta.get("joined_at") or _utc_now_iso()),
            "last_seen_at": str(
                prev.get("last_seen_at") or meta.get("last_seen_at") or meta.get("joined_at") or _utc_now_iso()
            ),
        }
    return joined


def mark_participant_present(
    session: dict[str, Any],
    *,
    force_save: bool = True,
    store: Any = None,
) -> dict[str, Any] | None:
    """Record that the current authenticated user has entered the Live Draft Room.

    Persists onto the shared room document so every client sees the same join state.
    """
    try:
        from draft_room_shared_state import (
            ACTIVE_SHARED_ROOM_CODE_KEY,
            get_shared_room_store,
            invalidate_shared_room_document_cache,
        )
    except ImportError:
        return None

    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not code:
        return None
    uid = canonical_participant_user_id(session)
    if not uid or uid.startswith(("local:", "anonymous:", "demo:")):
        # Refuse to persist anonymous/local presence into the shared room.
        if not uid:
            return None
        # Still allow local ids in fully offline tests only when no auth id exists.
        pass

    backend = store or get_shared_room_store()
    last_err = ""
    for _attempt in range(4):
        doc = backend.load(code)
        if not isinstance(doc, dict):
            return None
        board_rev = int(doc.get("revision") or 0)
        team = _claimed_team_for_user(session, doc)
        if not team:
            # Still record presence; team may fill in after claim reconcile.
            team = str(session.get("room_your_team") or "").strip()

        display = ""
        try:
            from draft_room_membership import participant_display_name

            display = str(participant_display_name(session) or "").strip()
        except ImportError:
            pass
        if "@" in display:
            display = display.split("@", 1)[0].strip() or display

        joined = reconcile_joined_from_participants(doc)
        prev = joined.get(uid) or {}
        now = _utc_now_iso()
        joined[uid] = {
            "user_id": uid,
            "workspace_id": _workspace_id(session) or prev.get("workspace_id") or "",
            "team_name": team or prev.get("team_name") or "",
            "display_name": display or prev.get("display_name") or uid,
            "joined_at": prev.get("joined_at") or now,
            "last_seen_at": now,
        }
        out = copy.deepcopy(doc)
        out[JOINED_PARTICIPANTS_KEY] = joined

        # Keep participants map in sync when the user already has a claimed team.
        if team:
            try:
                from draft_room_participant_state import register_participant_in_shared_document

                out = register_participant_in_shared_document(
                    out,
                    participant_id=uid,
                    assigned_team=team,
                    display_name=display,
                    session=session,
                )
                # register bumps revision; restore board revision for chat-friendly save.
                out["revision"] = board_rev
            except ImportError:
                pass

        if not force_save:
            session["_live_draft_joined_participants_cache"] = copy.deepcopy(joined)
            return out

        try:
            ok, current = backend.save_if_revision(out, expected_revision=board_rev)
        except Exception as exc:
            last_err = str(exc)
            continue
        if ok and isinstance(current, dict):
            invalidate_shared_room_document_cache(session, code)
            session["_live_draft_joined_participants_cache"] = normalize_joined_participants(
                current.get(JOINED_PARTICIPANTS_KEY)
            )
            return current
        last_err = "revision conflict"
    if last_err:
        session["_live_draft_presence_error"] = last_err
    return None


def required_human_participant_rows(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Required real managers: claimed team owners (not CPU / unclaimed placeholders)."""
    try:
        from live_draft_team_ownership import list_room_teams, load_shared_participants
    except ImportError:
        return []

    doc = document
    if not isinstance(doc, dict):
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        if code:
            try:
                from draft_room_shared_state import load_shared_room

                doc = load_shared_room(code)
            except ImportError:
                doc = None

    participants = {}
    if isinstance(doc, dict):
        participants = dict(doc.get("participants") or {})
    if not participants:
        participants = load_shared_participants(session)

    joined = normalize_joined_participants(
        (doc or {}).get(JOINED_PARTICIPANTS_KEY) if isinstance(doc, dict) else {}
    )

    rows: list[dict[str, Any]] = []
    seen_uids: set[str] = set()
    seen_teams: set[str] = set()
    for pid, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        # Skip explicit CPU / placeholder markers.
        kind = str(meta.get("seat_kind") or meta.get("team_kind") or "").strip().lower()
        if kind in {"cpu", "ai", "placeholder", "filler"}:
            continue
        if str(meta.get("is_cpu") or "").lower() in {"1", "true", "yes"}:
            continue
        uid = str(meta.get("user_id") or meta.get("account_user_id") or pid).strip() or str(pid)
        uid_key = uid.strip().lower()
        team_key = team.strip().lower()
        # One seat per authenticated identity and per claimed team.
        if uid_key in seen_uids or (team_key and team_key in seen_teams):
            continue
        seen_uids.add(uid_key)
        if team_key:
            seen_teams.add(team_key)
        presence = joined.get(uid_key) or joined.get(uid) or {}
        display = str(
            presence.get("display_name") or meta.get("display_name") or uid
        ).strip()
        if "@" in display:
            display = display.split("@", 1)[0].strip() or display
        # Joined means recorded in shared joined_participants (entered the room).
        # Legacy fallback: if the room never wrote joined_participants, treat a
        # claimed participant with joined_at as present so older rooms still start.
        if joined:
            is_joined = uid_key in joined or uid in joined
        else:
            is_joined = bool(str(meta.get("joined_at") or "").strip())
        rows.append(
            {
                "user_id": uid,
                "display_name": display,
                "team_name": team or presence.get("team_name") or "",
                "joined": is_joined,
                "joined_at": presence.get("joined_at") or meta.get("joined_at") or "",
                "last_seen_at": presence.get("last_seen_at") or "",
            }
        )

    # Include presence-only entries that somehow lack participants (safety).
    for uid, presence in joined.items():
        uid_key = str(uid or "").strip().lower()
        if uid_key in seen_uids:
            continue
        team_key = str(presence.get("team_name") or "").strip().lower()
        if team_key and team_key in seen_teams:
            continue
        if str(uid).startswith(("local:", "anonymous:", "demo:")):
            continue
        team = str(presence.get("team_name") or "").strip()
        if not team:
            continue
        # Skip if this team is already represented by a claimed participant.
        if any(str(r.get("team_name") or "").strip().lower() == team.strip().lower() for r in rows):
            continue
        seen_uids.add(uid_key)
        if team_key:
            seen_teams.add(team_key)
        display = str(presence.get("display_name") or uid).strip()
        rows.append(
            {
                "user_id": uid,
                "display_name": display,
                "team_name": team,
                "joined": True,
                "joined_at": presence.get("joined_at") or "",
                "last_seen_at": presence.get("last_seen_at") or "",
            }
        )

    # Deduplicate by canonical authenticated identity (and one seat per team).
    try:
        from live_draft_chat_ui import dedupe_chat_participant_rows

        rows = dedupe_chat_participant_rows(rows)
    except ImportError:
        # Local fallback: unique by lowercased user_id then team.
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("user_id") or "").strip().lower() or str(row.get("team_name") or "").strip().lower()
            if not key:
                continue
            if key not in deduped:
                deduped[key] = row
        rows = list(deduped.values())

    # Stable order by room team list when possible.
    team_order = {t: i for i, t in enumerate(list_room_teams(room))}
    rows.sort(key=lambda r: (team_order.get(str(r.get("team_name") or ""), 999), str(r.get("display_name") or "")))
    return rows


def count_required_joined(session: dict[str, Any], room: dict[str, Any], *, document: dict[str, Any] | None = None) -> tuple[int, int, list[dict[str, Any]]]:
    rows = required_human_participant_rows(session, room, document=document)
    total = len(rows)
    joined = sum(1 for r in rows if r.get("joined"))
    return joined, total, rows


def format_participant_status_line(row: dict[str, Any]) -> str:
    name = str(row.get("display_name") or row.get("user_id") or "Manager").strip()
    team = str(row.get("team_name") or "Unassigned").strip()
    status = "Joined" if row.get("joined") else "Not joined"
    return f"{name} — {team} — {status}"


def missing_participant_labels(rows: list[dict[str, Any]]) -> list[str]:
    missing = []
    for row in rows:
        if row.get("joined"):
            continue
        name = str(row.get("display_name") or row.get("user_id") or "Manager").strip()
        team = str(row.get("team_name") or "").strip()
        missing.append(f"{name} ({team})" if team else name)
    return missing
