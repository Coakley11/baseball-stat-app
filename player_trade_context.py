"""Draft roster context discovery for Trade / Acquire player actions."""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

import pandas as pd

from player_actions import dedupe_append_name, normalize_player_display_name, player_names_match

TRADE_FLOW_SESSION_KEY = "_player_trade_acquire_flow"
TRADE_ACTION_ACQUIRE = "acquire"
TRADE_ACTION_TRADE_AWAY = "trade_away"


def _display_base(name: str) -> str:
    return str(name or "").split(" (")[0].strip()


def _player_name_from_mapping(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("Player", "fullName", "name", "player"):
            raw = str(value.get(key) or "").strip()
            if raw:
                return _display_base(raw)
    return _display_base(str(value or "").strip())


def _session_user_team(session: dict[str, Any]) -> str:
    return str(session.get("room_your_team") or "").strip()


def _live_room_user_team(room: dict[str, Any], session: dict[str, Any]) -> str:
    cfg = room.get("config") or {}
    return str(
        cfg.get("your_team")
        or cfg.get("user_team")
        or _session_user_team(session)
        or ""
    ).strip()


def _append_context(
    contexts: list[dict[str, Any]],
    *,
    context_id: str,
    source: str,
    draft_label: str,
    team_name: str,
    is_user_team: bool,
    your_team: str,
    archive_id: str | None = None,
) -> None:
    if not team_name:
        return
    row = {
        "context_id": context_id,
        "source": source,
        "draft_label": draft_label,
        "team_name": team_name,
        "is_user_team": bool(is_user_team),
        "your_team": your_team or team_name,
        "archive_id": archive_id,
    }
    if any(str(c.get("context_id") or "") == context_id for c in contexts):
        return
    contexts.append(row)


def collect_player_roster_contexts(session: dict[str, Any], player_name: str) -> list[dict[str, Any]]:
    """Find live, simulator, and saved-draft contexts where ``player_name`` is rostered."""
    target = _display_base(player_name)
    if not target:
        return []

    contexts: list[dict[str, Any]] = []
    user_team_global = _session_user_team(session)

    room = session.get("live_draft_room")
    if isinstance(room, dict) and room:
        your_team = _live_room_user_team(room, session)
        league = str((room.get("config") or {}).get("league_name") or "Live Draft").strip()
        board = room.get("draft_board") or []
        if isinstance(board, list):
            for entry in board:
                if not isinstance(entry, dict):
                    continue
                pname = _player_name_from_mapping(entry)
                if not pname or not player_names_match(pname, target):
                    continue
                team = str(entry.get("Fantasy Team") or entry.get("Team") or "").strip()
                _append_context(
                    contexts,
                    context_id=f"live:{league}:{team}:{pname}",
                    source="live_draft_room",
                    draft_label=league,
                    team_name=team,
                    is_user_team=bool(your_team and team == your_team),
                    your_team=your_team,
                )

    try:
        from draft_room_state import get_canonical_draft_board, table_pick_count

        board_df = get_canonical_draft_board(session)
        has_board = table_pick_count(session.get("draft_room_table")) > 0
    except Exception:
        board_df = pd.DataFrame()
        has_board = False

    if has_board and isinstance(board_df, pd.DataFrame) and not board_df.empty and "Player" in board_df.columns:
        your_team = user_team_global
        for _, row in board_df.iterrows():
            pname = _player_name_from_mapping(row.to_dict())
            if not pname or not player_names_match(pname, target):
                continue
            team = str(row.get("Team") or "").strip()
            _append_context(
                contexts,
                context_id=f"simulator:{team}:{pname}",
                source="draft_simulator",
                draft_label="Draft Room Simulator",
                team_name=team,
                is_user_team=bool(your_team and team == your_team),
                your_team=your_team,
            )

    try:
        from draft_archive_state import draft_type_display, list_draft_archives

        for entry in list_draft_archives(session):
            archive_team = str(entry.get("team_name") or "").strip()
            players = entry.get("players") or []
            found = False
            matched_name = ""
            for prow in players:
                pname = _player_name_from_mapping(prow)
                if pname and player_names_match(pname, target):
                    found = True
                    matched_name = pname
                    break
            if not found:
                continue
            archive_id = str(entry.get("draft_id") or "").strip()
            draft_name = str(entry.get("draft_name") or "Saved Draft").strip()
            dtype = draft_type_display(entry)
            _append_context(
                contexts,
                context_id=f"archive:{archive_id}:{archive_team}",
                source="saved_archive",
                draft_label=f"{draft_name} ({dtype})",
                team_name=archive_team,
                is_user_team=True,
                your_team=archive_team,
                archive_id=archive_id or None,
            )
    except Exception:
        pass

    return contexts


def split_trade_acquire_contexts(contexts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trade_contexts = [c for c in contexts if c.get("is_user_team")]
    acquire_contexts = [c for c in contexts if not c.get("is_user_team")]
    return trade_contexts, acquire_contexts


def player_has_roster_context(session: dict[str, Any], player_name: str) -> bool:
    return bool(collect_player_roster_contexts(session, player_name))


def format_roster_context_label(ctx: dict[str, Any]) -> str:
    return f"{ctx.get('draft_label', 'Draft')} — {ctx.get('team_name', 'Team')}"


def apply_roster_context(session: dict[str, Any], ctx: dict[str, Any]) -> None:
    """Load the selected draft context into session state."""
    if ctx.get("source") == "saved_archive" and ctx.get("archive_id"):
        try:
            from draft_archive_state import activate_draft_archive

            activate_draft_archive(session, str(ctx["archive_id"]))
        except Exception:
            pass
    your_team = str(ctx.get("your_team") or ctx.get("team_name") or "").strip()
    if your_team:
        session["room_your_team"] = your_team


def add_trade_flow_target(session: dict[str, Any], player_name: str, action_type: str) -> None:
    display = _display_base(player_name)
    if action_type == TRADE_ACTION_TRADE_AWAY:
        give = session.get("pending_trade_away_players", [])
        session["pending_trade_away_players"] = dedupe_append_name(give, display)
        return
    acquire = session.get("pending_trade_acquire_players", [])
    session["pending_trade_acquire_players"] = dedupe_append_name(acquire, display)


def _flow_candidates(trade_contexts: list[dict[str, Any]], acquire_contexts: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == TRADE_ACTION_TRADE_AWAY:
        return list(trade_contexts)
    return list(acquire_contexts)


def start_trade_acquire_flow(
    session: dict[str, Any],
    *,
    player_name: str,
    key_prefix: str,
) -> str | None:
    """Resolve Trade / Acquire flow. Returns flash message when complete, else None (UI picker needed)."""
    display = _display_base(player_name)
    contexts = collect_player_roster_contexts(session, display)
    trade_contexts, acquire_contexts = split_trade_acquire_contexts(contexts)
    if not trade_contexts and not acquire_contexts:
        return f"No active or saved team context for {display}."

    if trade_contexts and acquire_contexts:
        session[TRADE_FLOW_SESSION_KEY] = {
            "player": display,
            "key_prefix": key_prefix,
            "step": "choose_mode",
            "trade_contexts": copy.deepcopy(trade_contexts),
            "acquire_contexts": copy.deepcopy(acquire_contexts),
        }
        return None

    mode = TRADE_ACTION_TRADE_AWAY if trade_contexts else TRADE_ACTION_ACQUIRE
    candidates = _flow_candidates(trade_contexts, acquire_contexts, mode)
    if len(candidates) == 1:
        ctx = candidates[0]
        apply_roster_context(session, ctx)
        add_trade_flow_target(session, display, mode)
        label = "trade candidate" if mode == TRADE_ACTION_TRADE_AWAY else "acquire target"
        return f"Loaded {format_roster_context_label(ctx)} and added {display} as {label}."

    session[TRADE_FLOW_SESSION_KEY] = {
        "player": display,
        "key_prefix": key_prefix,
        "step": "choose_context",
        "mode": mode,
        "candidates": copy.deepcopy(candidates),
    }
    return None


def complete_trade_acquire_flow(session: dict[str, Any], *, mode: str | None = None, context_id: str | None = None) -> str:
    flow = session.get(TRADE_FLOW_SESSION_KEY) or {}
    player = str(flow.get("player") or "").strip()
    if not player:
        session.pop(TRADE_FLOW_SESSION_KEY, None)
        return "Trade / Acquire flow expired. Try again."

    resolved_mode = mode or str(flow.get("mode") or "").strip()
    if flow.get("step") == "choose_mode":
        trade_contexts = list(flow.get("trade_contexts") or [])
        acquire_contexts = list(flow.get("acquire_contexts") or [])
        if resolved_mode not in (TRADE_ACTION_TRADE_AWAY, TRADE_ACTION_ACQUIRE):
            return "Choose whether to trade this player away or acquire this player."
        candidates = _flow_candidates(trade_contexts, acquire_contexts, resolved_mode)
        if not candidates:
            session.pop(TRADE_FLOW_SESSION_KEY, None)
            return f"No draft context available for {player}."
        if len(candidates) == 1:
            ctx = candidates[0]
            apply_roster_context(session, ctx)
            add_trade_flow_target(session, player, resolved_mode)
            session.pop(TRADE_FLOW_SESSION_KEY, None)
            label = "trade candidate" if resolved_mode == TRADE_ACTION_TRADE_AWAY else "acquire target"
            return f"Loaded {format_roster_context_label(ctx)} and added {player} as {label}."
        flow["step"] = "choose_context"
        flow["mode"] = resolved_mode
        flow["candidates"] = copy.deepcopy(candidates)
        session[TRADE_FLOW_SESSION_KEY] = flow
        return ""

    candidates = list(flow.get("candidates") or [])
    if not candidates:
        session.pop(TRADE_FLOW_SESSION_KEY, None)
        return f"No draft context available for {player}."

    selected = None
    if context_id:
        for ctx in candidates:
            if str(ctx.get("context_id") or "") == str(context_id):
                selected = ctx
                break
    if selected is None and len(candidates) == 1:
        selected = candidates[0]
    if selected is None:
        return "Choose which draft context to use."

    resolved_mode = resolved_mode or TRADE_ACTION_ACQUIRE
    apply_roster_context(session, selected)
    add_trade_flow_target(session, player, resolved_mode)
    session.pop(TRADE_FLOW_SESSION_KEY, None)
    label = "trade candidate" if resolved_mode == TRADE_ACTION_TRADE_AWAY else "acquire target"
    return f"Loaded {format_roster_context_label(selected)} and added {player} as {label}."
