"""Explicit saved-Mock editing identity; never infer a target from latest content."""
from __future__ import annotations

import copy
from typing import Any

OWNER_KEY = "saved_mock_edit_draft_id"
BOARD_OWNER_KEY = "saved_mock_board_draft_id"
WORKFLOWS_KEY = "saved_mock_workflows"
PENDING_KEY = "_suite_resume_saved_draft_id"


def remember_mock_workflow(session: dict[str, Any]) -> None:
    owner = str(session.get(OWNER_KEY) or "")
    if not owner:
        return
    from draft_state import gather_draft_workflow

    workflows = copy.deepcopy(session.get(WORKFLOWS_KEY) or {})
    workflows[owner] = copy.deepcopy(gather_draft_workflow(session))
    session[WORKFLOWS_KEY] = workflows


def release_mock_edit(session: dict[str, Any]) -> None:
    remember_mock_workflow(session)
    session.pop(OWNER_KEY, None)
    session.pop(BOARD_OWNER_KEY, None)
    session.pop("_simulator_session_library_draft_id", None)


def resumed_mock_save_owner(session: dict[str, Any]) -> str | None:
    owner = str(session.get(OWNER_KEY) or "").strip()
    if not owner:
        return None
    from draft_archive_state import get_draft_archive
    from fantasy_league_context import get_active_league_context

    entry = get_draft_archive(session, owner)
    context = get_active_league_context(session, respect_source_priority=False) or {}
    context_owner = str((context.get("metadata") or {}).get("source_draft_id") or "")
    board = session.get("draft_room_table")
    board_owner = (board.get("saved_mock_draft_id") if isinstance(board, dict)
                   else getattr(board, "attrs", {}).get("saved_mock_draft_id"))
    identities = [session.get("active_draft_archive_id"), session.get(BOARD_OWNER_KEY),
                  session.get("_simulator_session_library_draft_id"),
                  (session.get("draft_room_state") or {}).get("saved_mock_draft_id"), board_owner, context_owner]
    if not entry or entry.get("draft_type") != "simulator" or any(str(x or "") != owner for x in identities):
        raise ValueError("Saved Mock ownership changed. Reopen the intended saved draft before editing or saving.")
    return owner


def apply_pending_saved_mock_resume(session: dict[str, Any]) -> dict[str, Any]:
    requested = str(session.get(PENDING_KEY) or "").strip()
    if not requested:
        return {}
    from draft_archive_state import get_draft_archive
    from fantasy_league_context import (
        activate_archive_league_context, get_league_context_for_archive,
        PENDING_ARCHIVE_ACTIVATION_KEY, PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    )
    from draft_room_state import coerce_board_table, sync_board_to_session_keys

    entry = get_draft_archive(session, requested)
    if not entry:
        return {"error": "The requested saved draft is unavailable; no other draft was opened."}
    if entry.get("draft_type") != "simulator":
        session.pop(PENDING_KEY, None)
        return {}  # Existing imported/shared/Live resume paths are unchanged.
    context = get_league_context_for_archive(session, entry)
    if context and context.get("context_type") != "mock_draft_simulation":
        session.pop(PENDING_KEY, None)
        return {}
    board = coerce_board_table(entry.get("draft_board"))
    if board is None or board.empty or "Team" not in board.columns:
        return {"error": "This saved Mock has no editable board; no other board was substituted."}
    teams = list(dict.fromkeys(str(x).strip() for x in board["Team"] if str(x).strip()))
    if not teams or str(entry.get("team_name") or "") not in teams:
        return {"error": "The saved Mock's team is unavailable; its owner was not changed."}

    room = session.get("live_draft_room")
    if isinstance(room, dict):
        slot = session.get("resumable_live_draft_slot") or {}
        if session.get("active_shared_draft_room_code") or room.get("room_code"):
            return {"error": "Leave the shared Live room before editing a saved Mock."}
        if slot.get("draft_id") and slot.get("draft_id") != room.get("draft_room_id"):
            return {"error": "Save the active Live draft before opening another saved Mock."}
        from live_draft_resumable_slot import save_and_continue_later

        result = save_and_continue_later(session)
        if not result.get("ok"):
            return {"error": result.get("message") or "The Live draft could not be parked safely."}
    else:
        remember_mock_workflow(session)

    # Clear pending older selection before coherently activating the explicit ID.
    session.pop(PENDING_ARCHIVE_ACTIVATION_KEY, None)
    session.pop(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, None)
    activate_archive_league_context(session, requested, defer_activation=False)
    session[OWNER_KEY] = session[BOARD_OWNER_KEY] = requested
    session["_simulator_session_library_draft_id"] = requested
    session["_simulator_library_draft_name"] = entry["draft_name"]
    rounds = int(board["Round"].max()) if "Round" in board else max(1, len(board) // len(teams))
    session.update(room_team_names="\n".join(teams), room_team_count=len(teams), room_rounds=rounds,
                   room_your_team=entry["team_name"], room_format=entry.get("fantasy_format") or "5x5 Roto")
    config = dict(entry.get("projection_settings") or {})
    config.update(teams=teams, team_count=len(teams), num_teams=len(teams), rounds=rounds,
                  picks_per_team=rounds, fantasy_format=session["room_format"],
                  slots=entry.get("roster_slots") or {}, slot_instances=entry.get("slot_instances") or [])
    session["draft_shared_settings"] = config
    session.pop("live_draft_state", None)
    board.attrs["saved_mock_draft_id"] = requested
    sync_board_to_session_keys(session, board, local_edit=True, reason="saved_mock_resume")
    session["draft_room_state"]["saved_mock_draft_id"] = requested

    # A previous room/Mock's empty-write protection must not repopulate this scope.
    for key in ("draft_queue", "draft_state", "_live_draft_queue_last_good", "_live_draft_queue_sidebar_mirror"):
        session.pop(key, None)
    from draft_state import write_canonical_draft_state

    workflow = copy.deepcopy((session.get(WORKFLOWS_KEY) or {}).get(requested) or {})
    write_canonical_draft_state(session, queue=workflow.get("queue") or [],
        watchlist_focus=workflow.get("watchlist_focus") or [], watchlist_favorites=workflow.get("watchlist_favorites") or [],
        reason="clear_queue_saved_mock_resume", local_edit=True, sync_participant=False)
    session["use_live_draft_as_fantasy_context"] = False
    session["use_simulator_board_as_fantasy_context"] = False
    session.pop("fantasy_source_override_selection", None)
    session.pop(PENDING_KEY, None)
    resumed_mock_save_owner(session)
    session["_navigate_to_page"] = "Draft Room Simulator"
    session["_skip_page_restore_for"] = "Draft Room Simulator"
    return {"applied": True, "draft_id": requested}


def save_resumed_mock_board(session: dict[str, Any], board: Any) -> str | None:
    owner = resumed_mock_save_owner(session)
    if not owner:
        return None
    if getattr(board, "attrs", {}).get("saved_mock_draft_id") != owner:
        raise ValueError("The board does not belong to the resumed Mock Draft; save was refused.")
    from draft_archive_state import get_draft_archive
    from fantasy_league_context import save_simulator_league_context

    entry = get_draft_archive(session, owner)
    saved, _ = save_simulator_league_context(session, board, my_team_name=entry["team_name"],
        draft_name=entry["draft_name"], config=session.get("draft_shared_settings"), draft_id=owner,
        reuse_session_draft_id=False, save_only=True)
    if saved["draft_id"] != owner:
        raise ValueError("Saved Mock write changed identity; save was not accepted.")
    remember_mock_workflow(session)
    resumed_mock_save_owner(session)
    return owner
