"""Previous Simulator working boards: kept when a Live Draft takes over the board, restorable.

The Draft Room Simulator has one working board. A Live Draft mirrors its picks onto that board
automatically (``draft_room_state.sync_live_draft_room_to_canonical_board``). Before that first
mirror replaces a *different* board, the displaced board is copied here, so an unfinished mock
draft is never lost. "Restore Previous Mock Draft" puts it back after confirmation, and the board
it replaces is kept here in turn.

Records live in session workflow keys that are saved with the account workspace (disk + cloud),
and every record is stamped with the account and workspace that created it: another account's
record is never listed, restored, or kept on the next write.

Nothing here touches the Live Draft itself, the Saved Draft Library, or league records.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

PREVIOUS_BOARDS_KEY = "simulator_previous_boards"
LIVE_HANDOFF_KEY = "simulator_live_handoff"
RESTORE_GUARD_KEY = "simulator_board_restore_guard"
HISTORY_SESSION_KEYS = (PREVIOUS_BOARDS_KEY, LIVE_HANDOFF_KEY, RESTORE_GUARD_KEY)
MAX_PREVIOUS_BOARDS = 3

_RECORD_COLUMNS = ("Round", "Pick", "Team", "Player", "Primary Position", "Position", "playerID")
_SETTINGS_KEYS = ("room_your_team", "room_team_count", "room_rounds", "room_format", "room_team_names")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _identity(session: dict[str, Any]) -> tuple[str, str]:
    user_id = str(session.get("_suite_auth_user_id") or session.get("_suite_account_user_id") or "").strip()
    workspace = str(session.get("_suite_active_workspace_id") or "").strip()
    return user_id, workspace


def _belongs(session: dict[str, Any], record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    user_id, workspace = _identity(session)
    if str(record.get("user_id") or "") != user_id:
        return False
    rec_ws = str(record.get("workspace_id") or "")
    return not (rec_ws and workspace and rec_ws != workspace)


def _board_table(session: dict[str, Any]) -> pd.DataFrame:
    from draft_room_state import DRAFT_ROOM_TABLE_KEY, coerce_board_table

    return coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))


def board_signature(table: Any) -> str:
    """Order-sensitive signature of who is at which pick."""
    try:
        from draft_room_state import coerce_board_table

        df = coerce_board_table(table)
    except Exception:
        df = table if isinstance(table, pd.DataFrame) else pd.DataFrame()
    if df.empty or "Player" not in df.columns:
        return "empty"
    picks = df["Pick"].tolist() if "Pick" in df.columns else list(range(1, len(df) + 1))
    cells = [f"{p}:{str(n or '').strip().lower()}" for p, n in zip(picks, df["Player"].tolist()) if str(n or "").strip()]
    return f"{len(df)}|" + ";".join(cells)


def _pick_count(df: pd.DataFrame) -> int:
    if df.empty or "Player" not in df.columns:
        return 0
    return int(df["Player"].astype(str).str.strip().ne("").sum())


def _team_order(df: pd.DataFrame) -> list[str]:
    if df.empty or "Team" not in df.columns:
        return []
    out: list[str] = []
    for raw in df["Team"].tolist():
        name = str(raw or "").strip()
        if name and name.lower() not in ("nan", "none") and name not in out:
            out.append(name)
    return out


def _describe_origin(session: dict[str, Any]) -> str:
    try:
        from draft_room_state import get_canonical_draft_meta

        source = str(get_canonical_draft_meta(session).get("source") or "")
    except Exception:
        source = ""
    if source in ("live_draft_room", "completed_live_draft_import"):
        return "live_draft_board"
    if "import" in source:
        return "imported_board"
    if source == "forked_live_draft":
        return "hypothetical_from_live_draft"
    return "mock_draft"


def _owned_entries(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw = session.get(PREVIOUS_BOARDS_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(e) for e in raw if _belongs(session, e)]


def list_previous_boards(session: dict[str, Any]) -> list[dict[str, Any]]:
    """This account's kept boards, newest first."""
    return _owned_entries(session)


def snapshot_current_board(session: dict[str, Any], *, reason: str, label: str = "") -> dict[str, Any] | None:
    """A restorable copy of the current working board, or None when it has no picks."""
    df = _board_table(session)
    picks = _pick_count(df)
    if picks <= 0:
        return None
    cols = [c for c in _RECORD_COLUMNS if c in df.columns]
    records = df[cols].copy()
    records = records.where(pd.notna(records), "")
    user_id, workspace = _identity(session)
    teams = _team_order(df)
    try:
        rounds = int(session.get("room_rounds") or 0)
    except (TypeError, ValueError):
        rounds = 0
    if not rounds and "Round" in df.columns:
        rounds = int(pd.to_numeric(df["Round"], errors="coerce").max() or 0)
    origin = _describe_origin(session)
    return {
        "entry_id": uuid.uuid4().hex[:12],
        "user_id": user_id,
        "workspace_id": workspace,
        "saved_at": _utc_now_iso(),
        "reason": str(reason or ""),
        "origin": origin,
        "label": str(label or "").strip(),
        "pick_count": picks,
        "slot_count": int(len(df)),
        "teams": teams,
        "rounds": rounds,
        "settings": {k: session.get(k) for k in _SETTINGS_KEYS if session.get(k) not in (None, "")},
        "saved_mock_draft_id": str(session.get("saved_mock_board_draft_id") or "").strip(),
        "signature": board_signature(df),
        "records": records.to_dict(orient="records"),
    }


def _write_entries(session: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    # Only this account's records survive a write.
    session[PREVIOUS_BOARDS_KEY] = [e for e in entries if _belongs(session, e)][:MAX_PREVIOUS_BOARDS]


def preserve_current_board(session: dict[str, Any], *, reason: str, label: str = "") -> dict[str, Any] | None:
    """Keep the current board (if it has picks and is not already the newest kept copy)."""
    entry = snapshot_current_board(session, reason=reason, label=label)
    if entry is None:
        return None
    entries = _owned_entries(session)
    entries = [e for e in entries if e.get("signature") != entry["signature"]]
    _write_entries(session, [entry] + entries)
    return entry


# ── Live Draft handoff ───────────────────────────────────────────────────────


def _room_id(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    return str(room.get("draft_room_id") or room.get("room_id") or "").strip()


def _live_handoff(session: dict[str, Any]) -> dict[str, Any] | None:
    rec = session.get(LIVE_HANDOFF_KEY)
    return dict(rec) if _belongs(session, rec) else None


def _board_is_this_rooms_mirror(table: pd.DataFrame, room: dict[str, Any]) -> bool:
    """True when every filled board pick matches the room's pick at the same number."""
    try:
        from draft_room_state import _board_holds_another_draft

        return not _board_holds_another_draft(table, room)
    except Exception:
        return False


def before_live_board_mirror(session: dict[str, Any], room: dict[str, Any]) -> bool:
    """Called just before a Live Draft is mirrored onto the working board.

    Returns False when the mirror must be skipped: a completed Live Draft that was already handed
    off, after which the user moved the board on (restored a previous board, started or edited a
    mock). Otherwise keeps the board it is about to replace, when that board is a different draft.
    """
    room_id = _room_id(room)
    status = str(room.get("status") or "").strip().lower()
    handoff = _live_handoff(session)
    table = _board_table(session)
    current_sig = board_signature(table)
    handed_off = bool(handoff) and handoff.get("draft_room_id") == room_id and bool(room_id)

    if handed_off and status in ("complete", "completed"):
        if handoff.get("forked") or current_sig != handoff.get("board_signature"):
            # The user moved the board on after the handoff (restore, Undo, edits, a new mock):
            # that later board wins, and the finished Live Draft never re-takes it on a rerun.
            return False

    if not handed_off and _pick_count(table) > 0 and not _board_is_this_rooms_mirror(table, room):
        preserve_current_board(session, reason="replaced_by_live_draft")
    return True


def _original_picks(table: pd.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    if table.empty or "Pick" not in table.columns or "Player" not in table.columns:
        return out
    for pick, player in zip(table["Pick"].tolist(), table["Player"].tolist()):
        name = str(player or "").strip()
        if not name or name.lower() in ("nan", "none"):
            continue
        try:
            out[str(int(pick))] = name
        except (TypeError, ValueError):
            continue
    return out


def after_live_board_mirror(session: dict[str, Any], room: dict[str, Any]) -> None:
    user_id, workspace = _identity(session)
    table = _board_table(session)
    session[LIVE_HANDOFF_KEY] = {
        "user_id": user_id,
        "workspace_id": workspace,
        "draft_room_id": _room_id(room),
        "status": str(room.get("status") or ""),
        "board_signature": board_signature(table),
        # The actual Live Draft picks, so hypothetical changes can be told apart pick by pick.
        "original_picks": _original_picks(table),
        "at": _utc_now_iso(),
    }
    session.pop(RESTORE_GUARD_KEY, None)


# ── Restore ──────────────────────────────────────────────────────────────────


def restore_blocked_reason(session: dict[str, Any]) -> str:
    try:
        from draft_room_state import is_live_draft_runtime_active

        if is_live_draft_runtime_active(session):
            return "live_draft_in_progress"
    except Exception:
        pass
    return ""


def restore_previous_board(session: dict[str, Any], entry_id: str) -> dict[str, Any]:
    """Make a kept board the working board again. The board it replaces is kept in turn."""
    result: dict[str, Any] = {"ok": False, "message": "", "kept_current": False}
    blocked = restore_blocked_reason(session)
    if blocked:
        result["error"] = blocked
        result["message"] = (
            "Restore is available once the Live Draft is finished: while it runs, its picks are the "
            "working board."
        )
        return result
    entries = _owned_entries(session)
    entry = next((e for e in entries if e.get("entry_id") == entry_id), None)
    if entry is None:
        result["error"] = "not_found"
        result["message"] = "That previous board is no longer available."
        return result

    from draft_room_state import (
        ACTIVE_DRAFT_MODE_MANUAL,
        apply_programmatic_board_update,
        mark_draft_room_board_authority,
        set_canonical_draft_meta,
    )

    kept = preserve_current_board(session, reason="replaced_by_restore")
    result["kept_current"] = kept is not None
    entries = [e for e in _owned_entries(session) if e.get("entry_id") != entry_id]

    table = pd.DataFrame(entry.get("records") or [])
    for col in ("Round", "Pick", "Team", "Player"):
        if col not in table.columns:
            table[col] = ""
    table["Player"] = table["Player"].fillna("").astype(str)
    for key, value in dict(entry.get("settings") or {}).items():
        if key in _SETTINGS_KEYS:
            session[key] = value
    out = apply_programmatic_board_update(session, table, reason="restore_previous_board")
    picks = _pick_count(out)
    mark_draft_room_board_authority(session, pick_count=picks, reason="restore_previous_board")
    set_canonical_draft_meta(session, mode=ACTIVE_DRAFT_MODE_MANUAL, source="restored_previous_board", pick_count=picks)
    if entry.get("saved_mock_draft_id"):
        session["saved_mock_board_draft_id"] = entry["saved_mock_draft_id"]
    _write_entries(session, entries if kept is None else [kept] + [e for e in entries if e.get("entry_id") != kept["entry_id"]])
    user_id, workspace = _identity(session)
    session[RESTORE_GUARD_KEY] = {
        "user_id": user_id,
        "workspace_id": workspace,
        "entry_id": entry_id,
        "board_signature": board_signature(out),
        "at": _utc_now_iso(),
    }
    # The handoff stays recorded, so a completed Live Draft does not re-take the board.
    handoff = _live_handoff(session)
    if handoff:
        handoff["board_signature"] = "restored:" + handoff.get("board_signature", "")
        session[LIVE_HANDOFF_KEY] = handoff
    result.update({"ok": True, "pick_count": picks, "teams": entry.get("teams") or []})
    result["message"] = f"Restored the previous board ({picks} picks). It is now your Simulator working board."
    return result


def describe_entry(entry: dict[str, Any]) -> str:
    teams = [str(t) for t in entry.get("teams") or []]
    team_text = ", ".join(teams[:6]) + (f" +{len(teams) - 6} more" if len(teams) > 6 else "")
    origin = {
        "mock_draft": "Mock draft",
        "imported_board": "Imported board",
        "live_draft_board": "Live Draft picks",
        "hypothetical_from_live_draft": "Hypothetical continuation",
    }.get(str(entry.get("origin") or ""), "Board")
    label = str(entry.get("label") or "").strip()
    head = f"{label} · {origin}" if label else origin
    return (
        f"{head} — {int(entry.get('pick_count') or 0)} of {int(entry.get('slot_count') or 0)} picks"
        f" · {len(teams)} teams ({team_text})"
    )


def forget_foreign_history(session: dict[str, Any]) -> None:
    """Account or workspace changed: drop records this account does not own."""
    raw = session.get(PREVIOUS_BOARDS_KEY)
    if isinstance(raw, list):
        session[PREVIOUS_BOARDS_KEY] = [e for e in raw if _belongs(session, e)]
    for key in (LIVE_HANDOFF_KEY, RESTORE_GUARD_KEY):
        if key in session and not _belongs(session, session.get(key)):
            session.pop(key, None)
