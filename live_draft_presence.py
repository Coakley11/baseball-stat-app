"""Shared Live Draft participant presence — joined state persisted on the room document."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

JOINED_PARTICIPANTS_KEY = "joined_participants"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_participant_user_id(session: dict[str, Any]) -> str:
    """Stable authenticated identity — must match resolve_participant_id.

    Presence and claim maps must use one key. Preferring ``_suite_cloud_user_id``
    over ``_suite_auth_user_id`` previously double-registered the host and made
    guests see every team claimed ("No teams are available").
    """
    try:
        from draft_room_participant_state import resolve_participant_id

        pid = str(resolve_participant_id(session) or "").strip()
        if pid:
            return pid
    except ImportError:
        pass
    try:
        from suite_auth import AUTH_USER_ID_KEY

        val = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if val and not val.startswith(("local:", "anonymous:", "demo:")):
            return val
    except ImportError:
        pass
    for key in ("_suite_cloud_user_id", "draft_room_participant_id", "auth_user_id"):
        val = str(session.get(key) or "").strip()
        if val and not val.startswith(("local:", "anonymous:", "demo:")):
            return val
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
        # Always re-use resolve_participant_id — never invent a second claim key.
        if team:
            try:
                from draft_room_participant_state import (
                    register_participant_in_shared_document,
                    resolve_participant_id,
                )

                claim_pid = str(resolve_participant_id(session) or uid).strip() or uid
                out = register_participant_in_shared_document(
                    out,
                    participant_id=claim_pid,
                    assigned_team=team,
                    display_name=display,
                    session=session,
                )
                # Collapse host/guest alias duplicates so one identity owns one seat.
                try:
                    from live_draft_team_ownership import repair_shared_document_claims

                    repaired = repair_shared_document_claims(out)
                    if isinstance(repaired, dict):
                        out = repaired
                except ImportError:
                    pass
                # Normalize joined_participants onto the same claim key.
                if claim_pid != uid and claim_pid in (out.get("participants") or {}):
                    joined = normalize_joined_participants(out.get(JOINED_PARTICIPANTS_KEY))
                    if uid in joined and claim_pid not in joined:
                        row = dict(joined.pop(uid))
                        row["user_id"] = claim_pid
                        joined[claim_pid] = row
                        out[JOINED_PARTICIPANTS_KEY] = joined
                    uid = claim_pid
            except ImportError:
                pass

        # Heartbeat-only writes keep the board revision. Claim / join-map identity
        # changes MUST bump revision so the host lightweight poll applies them.
        # Ignore last_seen_at so presence heartbeats do not fight chat/board writers.
        def _membership_fingerprint(parts: Any, joined_raw: Any) -> tuple[tuple[str, str], ...]:
            rows: list[tuple[str, str]] = []
            if isinstance(parts, dict):
                for pid, meta in parts.items():
                    if not isinstance(meta, dict):
                        continue
                    rows.append(
                        (
                            str(pid),
                            str(meta.get("assigned_team") or "").strip(),
                        )
                    )
            for uid, meta in normalize_joined_participants(joined_raw).items():
                rows.append(
                    (
                        f"joined:{uid}",
                        str(meta.get("team_name") or "").strip(),
                    )
                )
            return tuple(sorted(rows))

        membership_changed = _membership_fingerprint(
            doc.get("participants"), doc.get(JOINED_PARTICIPANTS_KEY)
        ) != _membership_fingerprint(out.get("participants"), out.get(JOINED_PARTICIPANTS_KEY))
        if membership_changed:
            out["revision"] = int(board_rev) + 1
            out["updated_at"] = _utc_now_iso()
        else:
            out["revision"] = board_rev

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
    """One row per configured required human seat (not per visible participant).

    Denominator for ``Participants joined X of Y`` is always len(required teams).
    Open seats appear as Waiting even when the host's participant list is stale.
    """
    try:
        from live_draft_team_ownership import (
            canonicalize_shared_room_claims,
            list_required_human_teams,
            repair_shared_document_claims,
        )
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

    if isinstance(doc, dict):
        doc = repair_shared_document_claims(doc)
    else:
        doc = {"room": room if isinstance(room, dict) else {}, "participants": {}}

    required = list_required_human_teams(room, document=doc)
    if not required:
        return []

    canon = canonicalize_shared_room_claims(doc)
    occupancy = dict(canon.get("occupancy") or {})
    joined_map = normalize_joined_participants(doc.get(JOINED_PARTICIPANTS_KEY))
    raw_participants = dict(doc.get("participants") or {})

    rows: list[dict[str, Any]] = []
    for team in required:
        slot = occupancy.get(team) or {}
        owner_pid = str(slot.get("canonical_participant_id") or "").strip()
        if not owner_pid:
            rows.append(
                {
                    "user_id": "",
                    "display_name": "",
                    "team_name": team,
                    "joined": False,
                    "waiting": True,
                    "joined_at": "",
                    "last_seen_at": "",
                    "participant_id": "",
                    "is_host": False,
                }
            )
            continue

        meta = raw_participants.get(owner_pid) if isinstance(raw_participants.get(owner_pid), dict) else {}
        uid = str(
            (meta or {}).get("user_id")
            or (meta or {}).get("account_user_id")
            or slot.get("canonical_identity")
            or owner_pid
        ).strip()
        presence = joined_map.get(uid.lower()) or joined_map.get(uid) or joined_map.get(owner_pid) or {}
        # Prefer presence / external_id display (coakley11) over raw email.
        display = str(
            presence.get("display_name")
            or (meta or {}).get("display_name")
            or (meta or {}).get("external_id")
            or slot.get("canonical_claimant")
            or uid
        ).strip()
        if "@" in display:
            display = display.split("@", 1)[0].strip() or display
        # Canonical claim fills the seat for lobby counts (Join Room = claim + enter).
        rows.append(
            {
                "user_id": uid,
                "display_name": display,
                "team_name": team,
                "joined": True,
                "waiting": False,
                "joined_at": presence.get("joined_at") or (meta or {}).get("joined_at") or "",
                "last_seen_at": presence.get("last_seen_at") or "",
                "participant_id": owner_pid,
                "is_host": bool(slot.get("is_host")),
            }
        )
    return rows


def count_required_joined(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Return (joined_count, required_human_seats, rows).

    ``required_human_seats`` comes from configured teams — never from len(visible participants).
    """
    rows = required_human_participant_rows(session, room, document=document)
    try:
        from live_draft_team_ownership import list_required_human_teams

        required = list_required_human_teams(room, document=document)
        total = len(required) if required else len(rows)
    except ImportError:
        total = len(rows)
    joined = sum(1 for r in rows if r.get("joined") and not r.get("waiting"))
    return joined, total, rows


def format_participant_status_line(row: dict[str, Any]) -> str:
    team = str(row.get("team_name") or "Unassigned").strip()
    if row.get("waiting") or (not row.get("joined") and not str(row.get("user_id") or "").strip()):
        return f"{team} — Waiting"
    name = str(row.get("display_name") or row.get("user_id") or "Manager").strip()
    status = "Joined" if row.get("joined") else "Not joined"
    return f"{name} — {team} — {status}"


def missing_participant_labels(rows: list[dict[str, Any]]) -> list[str]:
    missing = []
    for row in rows:
        if row.get("joined"):
            continue
        team = str(row.get("team_name") or "").strip()
        if row.get("waiting") or not str(row.get("user_id") or "").strip():
            missing.append(team or "open seat")
            continue
        name = str(row.get("display_name") or row.get("user_id") or "Manager").strip()
        missing.append(f"{name} ({team})" if team else name)
    return missing


def build_lobby_sync_diagnostics(
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
    *,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Developer Mode snapshot for host/guest lobby sync debugging."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    doc = document
    if not isinstance(doc, dict) and code:
        try:
            from draft_room_shared_state import load_shared_room

            doc = load_shared_room(code)
        except ImportError:
            doc = None
    try:
        from live_draft_team_ownership import (
            canonicalize_shared_room_claims,
            list_required_human_teams,
            session_identity_aliases,
        )
        from draft_room_participant_state import resolve_participant_id

        required = list_required_human_teams(live, document=doc if isinstance(doc, dict) else None)
        canon = canonicalize_shared_room_claims(doc if isinstance(doc, dict) else {})
        joined_n, total_n, rows = count_required_joined(
            session, live, document=doc if isinstance(doc, dict) else None
        )
        pid = str(resolve_participant_id(session) or "").strip()
        claimed = ""
        for row in rows:
            if str(row.get("participant_id") or "") == pid or str(row.get("user_id") or "") in session_identity_aliases(session):
                claimed = str(row.get("team_name") or "")
                break
        storage_key = ""
        try:
            from draft_room_shared_state import shared_room_backend_name

            storage_key = f"{shared_room_backend_name()}:{code}"
        except ImportError:
            storage_key = code
        return {
            "entered_room_code": code,
            "canonical_room_id": str((doc or {}).get("draft_room_id") or live.get("draft_room_id") or ""),
            "shared_document_storage_key": storage_key,
            "room_revision": int((doc or {}).get("revision") or 0),
            "configured_teams": list(required),
            "required_human_teams": list(required),
            "raw_participants": dict((doc or {}).get("participants") or {}),
            "joined_participants": dict((doc or {}).get(JOINED_PARTICIPANTS_KEY) or {}),
            "raw_team_claims": {
                pid: str((meta or {}).get("assigned_team") or "")
                for pid, meta in dict((doc or {}).get("participants") or {}).items()
                if isinstance(meta, dict)
            },
            "canonicalized_claims": {
                team: {
                    "canonical_claimant": (slot or {}).get("canonical_claimant"),
                    "canonical_participant_id": (slot or {}).get("canonical_participant_id"),
                    "claimant_raw_ids": list((slot or {}).get("claimant_raw_ids") or []),
                    "available": (slot or {}).get("available"),
                    "reason": (slot or {}).get("reason"),
                }
                for team, slot in dict(canon.get("occupancy") or {}).items()
            },
            "current_account_participant_id": pid,
            "claimed_team": claimed,
            "last_shared_document_update": str((doc or {}).get("updated_at") or ""),
            "participants_joined": joined_n,
            "participants_required": total_n,
            "lobby_rows": rows,
        }
    except Exception as exc:
        return {"error": str(exc), "entered_room_code": code}
