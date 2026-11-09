"""Continue / edit the Simulator working board as a hypothetical mock draft.

Reuses the Simulator's own board engine (``draft_room_state``): the same board table, the same
``assign_player_to_board_row`` duplicate check, the same programmatic update/persist path. No
second draft system.

Rules
- A completed Live Draft handed to the Simulator is shown as *Live Draft picks*. The moment the
  user changes it (Continue / Edit, Undo, replace a pick, add a round) the working board becomes a
  separate hypothetical mock. The Live Draft room, its saved record, and other managers' records
  are never written here.
- Original Live Draft picks and later hypothetical changes are told apart pick by pick.
- A full board can be extended by whole rounds (same teams, same snake/linear order). A partial
  final round (e.g. an import of 10 of 12 picks) is padded with open picks so drafting continues.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

FORK_SOURCE = "forked_live_draft"


def _session_table(session: dict[str, Any]) -> pd.DataFrame:
    from draft_room_state import DRAFT_ROOM_TABLE_KEY, coerce_board_table

    return coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))


def _filled(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in ("nan", "none")


# ── Board geometry ───────────────────────────────────────────────────────────


def board_team_order(table: pd.DataFrame) -> list[str]:
    """Round-1 team order (the order teams pick in odd rounds)."""
    if table is None or table.empty or "Team" not in table.columns:
        return []
    work = table.sort_values("Pick", kind="stable") if "Pick" in table.columns else table
    if "Round" in work.columns:
        first = work[pd.to_numeric(work["Round"], errors="coerce") == pd.to_numeric(work["Round"], errors="coerce").min()]
        if not first.empty:
            work = first
    order: list[str] = []
    for raw in work["Team"].tolist():
        name = str(raw or "").strip()
        if name and name not in order:
            order.append(name)
    return order


def board_is_snake(table: pd.DataFrame, teams: list[str] | None = None) -> bool:
    """True unless round 2 visibly repeats round 1's order (a linear draft)."""
    teams = teams or board_team_order(table)
    if len(teams) < 2 or table.empty or "Round" not in table.columns:
        return True
    rounds = pd.to_numeric(table["Round"], errors="coerce")
    second = table[rounds == 2].sort_values("Pick", kind="stable") if "Pick" in table.columns else table[rounds == 2]
    seq = [str(t or "").strip() for t in second["Team"].tolist()]
    if not seq:
        return True
    return seq == list(reversed(teams))[: len(seq)] or seq != teams[: len(seq)]


def _round_order(teams: list[str], rnd: int, snake: bool) -> list[str]:
    return list(reversed(teams)) if (snake and rnd % 2 == 0) else list(teams)


def pad_partial_last_round(table: pd.DataFrame) -> pd.DataFrame:
    """Add open picks to finish a partial final round (import of 10 picks in a 6-team league)."""
    if table is None or table.empty or not {"Pick", "Team", "Player"}.issubset(table.columns):
        return table
    teams = board_team_order(table)
    if len(teams) < 2:
        return table
    work = table.copy()
    if "Round" not in work.columns:
        work["Round"] = ((pd.to_numeric(work["Pick"], errors="coerce") - 1) // len(teams)) + 1
    rounds = pd.to_numeric(work["Round"], errors="coerce")
    last_round = int(rounds.max() or 1)
    in_last = work[rounds == last_round]
    if len(in_last) >= len(teams):
        return table
    snake = board_is_snake(work, teams)
    order = _round_order(teams, last_round, snake)
    present = [str(t or "").strip() for t in in_last.sort_values("Pick")["Team"].tolist()]
    if present != order[: len(present)]:
        return table  # not a clean prefix of the round: do not guess
    next_pick = int(pd.to_numeric(work["Pick"], errors="coerce").max() or 0) + 1
    extra = [
        {"Round": last_round, "Pick": next_pick + i, "Team": team, "Player": ""}
        for i, team in enumerate(order[len(present):])
    ]
    return pd.concat([work, pd.DataFrame(extra)], ignore_index=True)


def board_with_added_rounds(table: pd.DataFrame, rounds: int = 1) -> pd.DataFrame:
    """The same board plus ``rounds`` open rounds, continuing pick numbers and pick order."""
    teams = board_team_order(table)
    if not teams:
        return table
    work = pad_partial_last_round(table)
    snake = board_is_snake(work, teams)
    last_round = int(pd.to_numeric(work.get("Round"), errors="coerce").max() or 0) if "Round" in work.columns else 0
    next_pick = int(pd.to_numeric(work["Pick"], errors="coerce").max() or 0) + 1 if "Pick" in work.columns else 1
    extra: list[dict[str, Any]] = []
    for rnd in range(last_round + 1, last_round + 1 + max(1, int(rounds))):
        for team in _round_order(teams, rnd, snake):
            extra.append({"Round": rnd, "Pick": next_pick, "Team": team, "Player": ""})
            next_pick += 1
    return pd.concat([work, pd.DataFrame(extra)], ignore_index=True)


# ── Provenance: original Live Draft picks vs hypothetical changes ───────────


def _handoff(session: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from simulator_board_history import LIVE_HANDOFF_KEY, _belongs

        rec = session.get(LIVE_HANDOFF_KEY)
        return dict(rec) if _belongs(session, rec) else None
    except ImportError:
        return None


def board_provenance(session: dict[str, Any]) -> dict[str, Any]:
    """How the working board relates to the Live Draft last handed to it.

    kind: ``live_draft`` (exactly the Live Draft's picks), ``hypothetical`` (started from them and
    changed), or ``other`` (no Live Draft handoff behind this board).
    """
    rec = _handoff(session)
    table = _session_table(session)
    out: dict[str, Any] = {"kind": "other", "changed_picks": [], "added_picks": [], "removed_picks": [],
                           "original_pick_count": 0, "draft_room_id": ""}
    if not rec or not isinstance(rec.get("original_picks"), dict):
        return out
    original = {int(k): str(v) for k, v in rec["original_picks"].items()}
    out["original_pick_count"] = len(original)
    out["draft_room_id"] = str(rec.get("draft_room_id") or "")
    current: dict[int, str] = {}
    if not table.empty and "Pick" in table.columns and "Player" in table.columns:
        for pick, player in zip(table["Pick"].tolist(), table["Player"].tolist()):
            try:
                pk = int(pick)
            except (TypeError, ValueError):
                continue
            if _filled(player):
                current[pk] = str(player).strip()
    if not current:
        return out
    shared = set(original) & set(current)
    if not shared and not rec.get("forked"):
        return out  # a different draft altogether
    changed = sorted(p for p in shared if original[p].lower() != current[p].lower())
    added = sorted(p for p in current if p not in original)
    removed = sorted(p for p in original if p not in current)
    out.update({"changed_picks": changed, "added_picks": added, "removed_picks": removed})
    if not changed and not added and not removed and not rec.get("forked"):
        out["kind"] = "live_draft"
    else:
        out["kind"] = "hypothetical"
    return out


def pick_origin_labels(session: dict[str, Any]) -> dict[int, str]:
    """Per pick: "Live Draft" for an original pick, "Hypothetical" for a changed or added one."""
    prov = board_provenance(session)
    if prov["kind"] == "other":
        return {}
    rec = _handoff(session) or {}
    original = {int(k): str(v) for k, v in dict(rec.get("original_picks") or {}).items()}
    labels: dict[int, str] = {}
    table = _session_table(session)
    for pick, player in zip(table.get("Pick", pd.Series(dtype=object)).tolist(),
                            table.get("Player", pd.Series(dtype=object)).tolist()):
        try:
            pk = int(pick)
        except (TypeError, ValueError):
            continue
        if not _filled(player):
            continue
        same = pk in original and original[pk].lower() == str(player).strip().lower()
        labels[pk] = "Live Draft" if same else "Hypothetical"
    return labels


# ── Fork ─────────────────────────────────────────────────────────────────────


def fork_live_board_as_mock(session: dict[str, Any], *, reason: str = "continue_as_mock") -> dict[str, Any]:
    """Make the handed-off Live Draft board a separate hypothetical mock (idempotent).

    Only this account's Simulator state changes: the handoff record is marked forked so the Live
    Draft never re-takes the board, and the board is detached from any saved Library entry so a
    later save becomes a new mock instead of touching the Live Draft record.
    """
    rec = _handoff(session)
    if not rec:
        return {"ok": False, "forked": False, "reason": "no_live_handoff"}
    if rec.get("forked"):
        return {"ok": True, "forked": False, "reason": "already_forked"}
    from draft_room_state import ACTIVE_DRAFT_MODE_MANUAL, set_canonical_draft_meta, table_pick_count

    try:
        from simulator_board_history import LIVE_HANDOFF_KEY

        rec["forked"] = True
        rec["forked_reason"] = str(reason or "")
        rec["board_signature"] = "forked"
        session[LIVE_HANDOFF_KEY] = rec
    except ImportError:
        pass
    for key in ("saved_mock_board_draft_id", "saved_mock_edit_draft_id", "_simulator_session_library_draft_id"):
        session.pop(key, None)
    set_canonical_draft_meta(
        session, mode=ACTIVE_DRAFT_MODE_MANUAL, source=FORK_SOURCE, pick_count=table_pick_count(_session_table(session))
    )
    session["_draft_room_editable_after_live_import"] = True
    return {"ok": True, "forked": True}


def fork_if_live_board(session: dict[str, Any], *, reason: str) -> bool:
    """Before any edit: a board that is still exactly a completed Live Draft becomes hypothetical."""
    try:
        from draft_room_state import is_live_draft_runtime_active

        if is_live_draft_runtime_active(session):
            return False  # while the Live Draft runs, the board is the Live Draft's
    except Exception:
        pass
    if board_provenance(session)["kind"] == "live_draft":
        return bool(fork_live_board_as_mock(session, reason=reason).get("forked"))
    return False


# ── Edits ────────────────────────────────────────────────────────────────────


def _pin_and_apply(session: dict[str, Any], table: pd.DataFrame, *, reason: str) -> pd.DataFrame:
    from draft_room_state import apply_programmatic_board_update, mark_draft_room_board_authority, table_pick_count

    out = apply_programmatic_board_update(session, table, reason=reason)
    mark_draft_room_board_authority(session, pick_count=table_pick_count(out), reason=reason)
    return out


def add_board_rounds(session: dict[str, Any], rounds: int = 1) -> dict[str, Any]:
    """Extend the working board by whole open rounds (a hypothetical continuation)."""
    try:
        from draft_room_state import is_live_draft_runtime_active

        if is_live_draft_runtime_active(session):
            return {"ok": False, "error": "live_active",
                    "message": "Rounds can be added after the Live Draft finishes."}
    except Exception:
        pass
    table = _session_table(session)
    if table.empty or not board_team_order(table):
        return {"ok": False, "error": "empty_board", "message": "There is no board to extend."}
    fork_if_live_board(session, reason="add_round")
    before = len(table)
    extended = board_with_added_rounds(table, rounds)
    try:
        session["room_rounds"] = int(pd.to_numeric(extended["Round"], errors="coerce").max())
    except (TypeError, ValueError):
        pass
    out = _pin_and_apply(session, extended, reason="extend_board_round")
    added = len(out) - before
    return {"ok": True, "added_slots": added,
            "message": f"Added {added} open pick{'s' if added != 1 else ''}. Keep drafting below."}


def board_names_for_duplicate_check(session: dict[str, Any]) -> set[str]:
    """Players already on *this* working board (a hypothetical board is its own draft)."""
    table = _session_table(session)
    if table.empty or "Player" not in table.columns:
        return set()
    return {str(p).strip() for p in table["Player"].tolist() if _filled(p)}


def replace_board_pick(session: dict[str, Any], *, pick_number: int, player_name: str) -> dict[str, Any]:
    """Put a different player on an already-made pick, or clear it (empty name)."""
    from draft_room_state import assign_player_to_board_row, is_live_draft_runtime_active

    if is_live_draft_runtime_active(session):
        return {"ok": False, "error": "live_active",
                "message": "Picks can be changed here after the Live Draft finishes."}
    table = _session_table(session)
    if table.empty or "Pick" not in table.columns:
        return {"ok": False, "error": "empty_board", "message": "Board is empty."}
    rows = table.index[pd.to_numeric(table["Pick"], errors="coerce") == int(pick_number)].tolist()
    if not rows:
        return {"ok": False, "error": "bad_pick", "message": f"Pick {pick_number} is not on the board."}
    row = rows[0]
    name = str(player_name or "").strip()
    current = str(table.at[row, "Player"] or "").strip()
    if name and name.lower() == current.lower():
        return {"ok": False, "error": "unchanged", "message": f"{name} is already on pick {pick_number}."}
    if name and name in board_names_for_duplicate_check(session):
        return {"ok": False, "error": "duplicate", "message": f"{name} is already on this board."}
    fork_if_live_board(session, reason="replace_pick")
    if not name:
        work = table.copy()
        work.at[row, "Player"] = ""
        _pin_and_apply(session, work, reason="clear_board_pick")
        return {"ok": True, "message": f"Cleared pick {pick_number} ({current}). It is open again."}
    res = assign_player_to_board_row(session, row, name)
    if res.get("ok"):
        from draft_room_state import mark_draft_room_board_authority, table_pick_count

        mark_draft_room_board_authority(session, pick_count=table_pick_count(_session_table(session)),
                                        reason="replace_board_pick")
        res["message"] = (f"Pick {pick_number}: {name} replaces {current}." if current
                          else res.get("message") or f"Set {name} on pick {pick_number}.")
    return res
