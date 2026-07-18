"""Authoritative Shared Live Draft Room snapshot.

All shared-room UI (timer, queue caption, board, chat identity, End Draft) must
read from this snapshot — not from independent local countdown / lobby preview state.
"""

from __future__ import annotations

import copy
from typing import Any

SHARED_ROOM_SNAPSHOT_KEY = "_shared_live_draft_authoritative_snapshot"
SHARED_ROOM_IDENTITY_KEY = "_shared_live_draft_normalized_identity"


def normalize_shared_room_identity(session: dict[str, Any]) -> dict[str, Any]:
    """Resolve auth / workspace / team / room once for all room reads and writes."""
    auth_user_id = str(
        session.get("auth_user_id")
        or session.get("_suite_auth_user_id")
        or session.get("suite_auth_user_id")
        or ""
    ).strip()
    workspace_id = str(
        session.get("_suite_active_workspace_id")
        or session.get("_suite_owned_workspace_id")
        or session.get("workspace_id")
        or ""
    ).strip()
    room_code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not room_code:
        try:
            from draft_room_context import resolve_shared_room_code

            room_code = str(resolve_shared_room_code(session) or "").strip().upper()
        except ImportError:
            pass
    participant_id = ""
    claimed_team = ""
    try:
        from draft_room_participant_state import active_participant_team, resolve_participant_id

        participant_id = str(resolve_participant_id(session) or "").strip() or auth_user_id
        claimed_team = str(active_participant_team(session) or "").strip()
    except ImportError:
        participant_id = auth_user_id
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    room_id = str(
        (room or {}).get("draft_room_id")
        or (room or {}).get("room_id")
        or (room or {}).get("draft_id")
        or room_code
        or ""
    ).strip()
    identity = {
        "auth_user_id": auth_user_id,
        "canonical_workspace_id": workspace_id,
        "participant_id": participant_id,
        "claimed_team": claimed_team,
        "shared_room_code": room_code,
        "shared_room_id": room_id,
    }
    session[SHARED_ROOM_IDENTITY_KEY] = identity
    return identity


def _drafted_from_room(room: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Return (names, player_ids) from the live draft board."""
    names: list[str] = []
    ids: list[str] = []
    if not isinstance(room, dict):
        return names, ids
    board = room.get("draft_board") or []
    if isinstance(board, list):
        for entry in board:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("fullName") or entry.get("Player") or "").strip()
            pid = str(entry.get("playerID") or entry.get("player_id") or "").strip()
            if name:
                names.append(name)
            if pid:
                ids.append(pid)
    drafted_ids = room.get("drafted_player_ids") or []
    if isinstance(drafted_ids, list):
        for pid in drafted_ids:
            s = str(pid or "").strip()
            if s and s not in ids:
                ids.append(s)
    return names, ids


def build_shared_live_draft_snapshot(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one authoritative view of the shared (or solo live) room."""
    identity = normalize_shared_room_identity(session)
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    status = str(live.get("status") or "").strip().lower()
    if isinstance(document, dict):
        doc_status = str(document.get("status") or "").strip().lower()
        if doc_status:
            status = doc_status
        room_blob = document.get("room")
        if isinstance(room_blob, dict) and not live:
            live = room_blob

    pick_order = list(live.get("pick_order") or [])
    board = list(live.get("draft_board") or []) if isinstance(live.get("draft_board"), list) else []
    idx = int(live.get("current_pick_index") or 0)
    # Prefer board length when index lags (stale guest session).
    if status in ("in_progress", "paused") and len(board) > idx and len(board) < len(pick_order):
        idx = len(board)
    slot: dict[str, Any] | None = None
    if 0 <= idx < len(pick_order) and isinstance(pick_order[idx], dict):
        slot = pick_order[idx]
    on_clock = str((slot or {}).get("Team") or live.get("on_clock_team") or "").strip()
    try:
        current_pick = int((slot or {}).get("Pick") or (idx + 1))
    except (TypeError, ValueError):
        current_pick = idx + 1 if pick_order else None

    deadline = live.get("timer_deadline")
    started = live.get("timer_started_at")
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining, live_draft_timer_deadline

        deadline = live_draft_timer_deadline(live) if status == "in_progress" else None
        seconds_remaining = (
            live_draft_seconds_remaining(live) if status in ("in_progress", "paused") else None
        )
    except ImportError:
        seconds_remaining = None

    drafted_names, drafted_ids = _drafted_from_room(live)
    claims: dict[str, str] = {}
    try:
        from draft_room_participant_state import participant_state_for_room

        code = identity.get("shared_room_code") or ""
        if code:
            state = participant_state_for_room(session, code)
            by_p = dict((state or {}).get("by_participant") or {})
            for pid, slot_rec in by_p.items():
                if not isinstance(slot_rec, dict):
                    continue
                team = str(
                    slot_rec.get("team")
                    or (slot_rec.get("membership") or {}).get("team")
                    or ""
                ).strip()
                if team:
                    claims[str(pid)] = team
    except ImportError:
        pass

    commissioner = ""
    room_generation = ""
    timer_paused = bool(live.get("timer_paused") or live.get("paused") or status in ("paused", "saved_for_later", "parked"))
    if isinstance(document, dict):
        commissioner = str(
            document.get("commissioner_participant_id")
            or document.get("host_participant_id")
            or ""
        ).strip()
        room_generation = str(document.get("room_generation") or "").strip()
        if document.get("status"):
            # Authoritative pause/deleted from document wins for lifecycle fields.
            timer_paused = timer_paused or str(document.get("status") or "").lower() in (
                "paused",
                "saved_for_later",
                "parked",
            )
    # Prefer document room blob deadline when present (authoritative shared turn).
    if isinstance(document, dict):
        room_blob = document.get("room") if isinstance(document.get("room"), dict) else {}
        if room_blob.get("timer_deadline") is not None and not timer_paused:
            deadline = room_blob.get("timer_deadline")
            try:
                from live_draft_timer_logic import live_draft_seconds_remaining

                # Temporarily mirror deadline onto live for remaining calc.
                tmp = dict(live)
                tmp["timer_deadline"] = deadline
                seconds_remaining = live_draft_seconds_remaining(tmp)
            except ImportError:
                pass
        doc_idx = room_blob.get("current_pick_index") if isinstance(room_blob, dict) else None
        if doc_idx is not None:
            try:
                doc_idx_i = int(doc_idx)
                if doc_idx_i >= idx:
                    idx = doc_idx_i
                    if 0 <= idx < len(pick_order) and isinstance(pick_order[idx], dict):
                        slot = pick_order[idx]
                        on_clock = str((slot or {}).get("Team") or on_clock).strip()
                        try:
                            current_pick = int((slot or {}).get("Pick") or (idx + 1))
                        except (TypeError, ValueError):
                            current_pick = idx + 1
            except (TypeError, ValueError):
                pass

    snap = {
        "room_id": identity.get("shared_room_id") or live.get("draft_room_id") or "",
        "draft_id": str(live.get("draft_room_id") or identity.get("shared_room_id") or ""),
        "room_code": identity.get("shared_room_code") or "",
        "room_generation": room_generation,
        "room_status": status,
        "lifecycle": str(session.get("_live_draft_lifecycle") or status or ""),
        "current_pick": current_pick,
        "current_pick_index": idx,
        "current_round": int((slot or {}).get("Round") or 0) or None,
        "on_clock_team": on_clock,
        "turn_started_at": started,
        "turn_deadline": deadline,
        "timer_deadline_utc": deadline,
        "timer_paused": timer_paused,
        "seconds_remaining": None if timer_paused else seconds_remaining,
        "completed_picks": len(board),
        "total_picks": len(pick_order),
        "draft_board": copy.deepcopy(board),
        "drafted_player_names": drafted_names,
        "drafted_player_ids": drafted_ids,
        "claimed_teams": claims,
        "claimed_team": identity.get("claimed_team") or "",
        "commissioner_participant_id": commissioner,
        "auth_user_id": identity.get("auth_user_id") or "",
        "participant_id": identity.get("participant_id") or "",
        "chat_room_key": str(identity.get("shared_room_code") or "").strip().upper(),
        "draft_complete": status in ("complete", "completed", "ended", "closed", "deleted")
        or (len(pick_order) > 0 and len(board) >= len(pick_order)),
        "identity": identity,
        "revision": int(
            (document or {}).get("revision")
            or live.get("revision")
            or session.get("_shared_room_expected_revision")
            or 0
        ),
        "latest_committed_pick_id": str(
            (board[-1].get("player_id") or board[-1].get("playerID") or board[-1].get("Player") or "")
            if board and isinstance(board[-1], dict)
            else ""
        ),
    }
    session[SHARED_ROOM_SNAPSHOT_KEY] = snap
    session["_live_draft_authoritative_snap_rev"] = snap["revision"]
    return snap


def refresh_shared_live_draft_snapshot(
    session: dict[str, Any],
    *,
    force_network: bool = False,
) -> dict[str, Any]:
    """Load shared document when multiplayer; always refresh session snapshot."""
    identity = normalize_shared_room_identity(session)
    code = str(identity.get("shared_room_code") or "").strip().upper()
    document = None
    if code:
        try:
            from draft_room_shared_state import (
                invalidate_shared_room_document_cache,
                load_shared_room_document,
                publish_shared_room_runtime,
            )

            if force_network:
                invalidate_shared_room_document_cache(session, code)
            document = load_shared_room_document(session, code)
            if isinstance(document, dict):
                publish_shared_room_runtime(session, document, reason="authoritative_snapshot")
        except ImportError:
            pass
        except Exception:
            pass
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    return build_shared_live_draft_snapshot(session, room=room, document=document)


def get_shared_live_draft_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    snap = session.get(SHARED_ROOM_SNAPSHOT_KEY)
    if isinstance(snap, dict) and snap.get("room_status") is not None:
        return snap
    return build_shared_live_draft_snapshot(session)


def drafted_player_tokens(session: dict[str, Any]) -> set[str]:
    """Canonical drafted name + id tokens for queue reconciliation."""
    snap = get_shared_live_draft_snapshot(session)
    tokens: set[str] = set()
    for name in snap.get("drafted_player_names") or []:
        s = str(name or "").strip()
        if s:
            tokens.add(s)
            tokens.add(s.lower())
    for pid in snap.get("drafted_player_ids") or []:
        s = str(pid or "").strip()
        if s:
            tokens.add(s)
            tokens.add(s.lower())
    # Also include live room board directly in case snapshot is stale mid-pick.
    room = session.get("live_draft_room")
    names, ids = _drafted_from_room(room if isinstance(room, dict) else None)
    for name in names:
        tokens.add(name)
        tokens.add(name.lower())
    for pid in ids:
        tokens.add(pid)
        tokens.add(pid.lower())
    return tokens


def is_player_drafted_in_room(session: dict[str, Any], player_id_or_name: str) -> bool:
    token = str(player_id_or_name or "").strip()
    if not token:
        return False
    drafted = drafted_player_tokens(session)
    return token in drafted or token.lower() in drafted
