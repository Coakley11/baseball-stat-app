"""Draft roster context discovery for Trade / Acquire player actions."""

from __future__ import annotations

import copy
from typing import Any

import pandas as pd

from player_trade_constants import (
    TRADE_ACTION_ACQUIRE,
    TRADE_ACTION_TRADE_AWAY,
    TRADE_FLOW_SESSION_KEY,
)


def _player_names_match(left: Any, right: Any) -> bool:
    from player_actions import player_names_match

    return player_names_match(left, right)


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
    league_context_id: str = "",
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
        "league_context_id": str(league_context_id or "").strip(),
    }
    if any(str(c.get("context_id") or "") == context_id for c in contexts):
        return
    contexts.append(row)


def _resolve_league_context_id(session: dict[str, Any], roster_ctx: dict[str, Any] | None) -> str:
    if roster_ctx:
        league_context_id = str(roster_ctx.get("league_context_id") or "").strip()
        if league_context_id:
            return league_context_id
        source = str(roster_ctx.get("source") or "").strip()
        if source in ("live_draft_room", "draft_simulator"):
            return ""
        archive_id = str(roster_ctx.get("archive_id") or "").strip()
        if archive_id:
            try:
                from fantasy_league_context import context_id_for_archive

                return context_id_for_archive(archive_id)
            except ImportError:
                return f"archive:{archive_id}"
    try:
        from fantasy_league_context import get_active_league_context

        active = get_active_league_context(session)
        if active:
            return str(active.get("league_context_id") or "").strip()
    except ImportError:
        pass
    return ""


def player_trade_shortcut_eligible(session: dict[str, Any], player_name: str) -> tuple[bool, str]:
    """True when Trade/Acquire shortcuts may use the active eligible shared league."""
    display = _display_base(player_name)
    if not display:
        return False, "Pick a player first."
    try:
        from fantasy_league_context import get_active_league_context, normalize_player_key
        from fantasy_league_team_ownership import owned_team_for_user, trades_enabled
    except ImportError:
        return False, "Trade shortcuts require an active league."

    active = get_active_league_context(session)
    if not active:
        return False, "Set an active league in Saved Draft Library before trading."
    ok, msg = trades_enabled(active, session)
    if not ok:
        return False, msg

    target_key = normalize_player_key(display)
    if not target_key:
        return False, f"Could not resolve roster identity for {display}."

    ownership = active.get("ownership_map") or {}
    if not isinstance(ownership, dict) or target_key not in ownership:
        league_label = str(active.get("display_name") or active.get("league_name") or "active league")
        return False, f"{display} is not rostered in {league_label}."

    my_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
    if not my_team:
        return False, "Claim your team in this league before trading."

    owner = ownership.get(target_key) or {}
    owner_team = str(owner.get("owner_team") or "").strip() if isinstance(owner, dict) else ""
    if not owner_team:
        return False, f"{display} is not rostered in the active league."

    return True, ""


def _collect_fantasy_league_context_rows(
    session: dict[str, Any],
    target: str,
    contexts: list[dict[str, Any]],
) -> None:
    try:
        from fantasy_league_context import list_league_contexts, normalize_player_key

        target_key = normalize_player_key(target)
        if not target_key:
            return
        for ctx in list_league_contexts(session):
            ownership = ctx.get("ownership_map") or {}
            if not isinstance(ownership, dict):
                continue
            owner = ownership.get(target_key)
            if not isinstance(owner, dict):
                continue
            league_context_id = str(ctx.get("league_context_id") or "").strip()
            owner_team = str(owner.get("owner_team") or "").strip()
            if not league_context_id or not owner_team:
                continue
            source_draft_id = str((ctx.get("metadata") or {}).get("source_draft_id") or "").strip()
            _append_context(
                contexts,
                context_id=f"flc:{league_context_id}:{owner_team}",
                source="fantasy_league_context",
                draft_label=str(ctx.get("display_name") or ctx.get("league_name") or "League"),
                team_name=owner_team,
                is_user_team=bool(owner.get("is_user_team")),
                your_team=str(ctx.get("my_team_name") or ""),
                archive_id=source_draft_id or None,
                league_context_id=league_context_id,
            )
    except Exception:
        pass


def collect_player_roster_contexts(session: dict[str, Any], player_name: str) -> list[dict[str, Any]]:
    """Find live, simulator, saved-draft, and fantasy-league contexts where player is rostered."""
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
                if not pname or not _player_names_match(pname, target):
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
        from fantasy_league_context import context_id_for_archive

        for entry in list_draft_archives(session):
            archive_team = str(entry.get("team_name") or "").strip()
            players = entry.get("players") or []
            found = False
            for prow in players:
                pname = _player_name_from_mapping(prow)
                if pname and _player_names_match(pname, target):
                    found = True
                    break
            if not found:
                continue
            archive_id = str(entry.get("draft_id") or "").strip()
            draft_name = str(entry.get("draft_name") or "Saved Draft").strip()
            dtype = draft_type_display(entry)
            league_context_id = str(entry.get("league_context_id") or context_id_for_archive(archive_id))
            _append_context(
                contexts,
                context_id=f"archive:{archive_id}:{archive_team}",
                source="saved_archive",
                draft_label=f"{draft_name} ({dtype})",
                team_name=archive_team,
                is_user_team=True,
                your_team=archive_team,
                archive_id=archive_id or None,
                league_context_id=league_context_id,
            )
    except Exception:
        pass

    _collect_fantasy_league_context_rows(session, target, contexts)
    return _dedupe_collected_contexts(contexts)


def _dedupe_collected_contexts(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer fantasy-league-context rows over live/sim duplicates for the same team slot."""
    by_slot: dict[tuple[bool, str], dict[str, Any]] = {}
    for ctx in contexts:
        slot = (bool(ctx.get("is_user_team")), str(ctx.get("team_name") or ""))
        existing = by_slot.get(slot)
        if existing is None:
            by_slot[slot] = ctx
            continue
        if not existing.get("league_context_id") and ctx.get("league_context_id"):
            by_slot[slot] = ctx
    return list(by_slot.values())


def split_trade_acquire_contexts(contexts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trade_contexts = [c for c in contexts if c.get("is_user_team")]
    acquire_contexts = [c for c in contexts if not c.get("is_user_team")]
    return trade_contexts, acquire_contexts


def player_has_roster_context(session: dict[str, Any], player_name: str) -> bool:
    return bool(collect_player_roster_contexts(session, player_name))


def format_roster_context_label(ctx: dict[str, Any]) -> str:
    return f"{ctx.get('draft_label', 'Draft')} — {ctx.get('team_name', 'Team')}"


def apply_roster_context(session: dict[str, Any], ctx: dict[str, Any], *, defer_activation: bool = True) -> None:
    """Load the selected draft / league context into session state."""
    league_context_id = _resolve_league_context_id(session, ctx)
    archive_id = str(ctx.get("archive_id") or "").strip()
    try:
        if defer_activation:
            from fantasy_league_context import context_id_for_archive, schedule_league_context_activation

            if archive_id:
                ctx_id = league_context_id or context_id_for_archive(archive_id)
                schedule_league_context_activation(session, ctx_id, archive_id=archive_id)
            elif league_context_id:
                schedule_league_context_activation(session, league_context_id)
            return
        if archive_id:
            from fantasy_league_context import activate_archive_league_context

            activate_archive_league_context(session, archive_id, defer_activation=False)
        elif league_context_id:
            from fantasy_league_context import activate_league_context

            activate_league_context(session, league_context_id)
        elif ctx.get("source") == "saved_archive" and archive_id:
            from draft_archive_state import activate_draft_archive

            activate_draft_archive(session, archive_id)
    except Exception:
        if not defer_activation and ctx.get("source") == "saved_archive" and archive_id:
            try:
                from draft_archive_state import activate_draft_archive

                activate_draft_archive(session, archive_id)
            except Exception:
                pass


def add_trade_flow_target(
    session: dict[str, Any],
    player_name: str,
    action_type: str,
    *,
    roster_ctx: dict[str, Any] | None = None,
) -> str:
    """Persist target to Fantasy League Context workflow. Returns league_context_id used."""
    display = _display_base(player_name)
    league_context_id = _resolve_league_context_id(session, roster_ctx)
    if not league_context_id:
        return ""
    owner_team = str((roster_ctx or {}).get("team_name") or "").strip()
    if action_type == TRADE_ACTION_TRADE_AWAY:
        owner_team = str((roster_ctx or {}).get("your_team") or owner_team or _session_user_team(session)).strip()
    try:
        from fantasy_league_context import add_workflow_target

        add_workflow_target(
            session,
            league_context_id,
            action_type,
            display,
            owner_team=owner_team,
        )
    except ImportError:
        return ""
    return league_context_id


def _finalize_trade_acquire(
    session: dict[str, Any],
    *,
    player: str,
    mode: str,
    roster_ctx: dict[str, Any],
) -> str:
    apply_roster_context(session, roster_ctx)
    league_context_id = add_trade_flow_target(session, player, mode, roster_ctx=roster_ctx)
    label = "trade candidate" if mode == TRADE_ACTION_TRADE_AWAY else "acquire target"
    if league_context_id:
        try:
            from fantasy_league_context import set_trade_acquire_handoff

            set_trade_acquire_handoff(
                session,
                league_context_id=league_context_id,
                mode=mode,
                player_name=player,
                owner_team=str(roster_ctx.get("team_name") or ""),
            )
        except ImportError:
            pass
        session.pop(TRADE_FLOW_SESSION_KEY, None)
        return (
            f"Loaded {format_roster_context_label(roster_ctx)} and added {player} as {label}. "
            "Opening Fantasy Lineup Assistant."
        )
    session.pop(TRADE_FLOW_SESSION_KEY, None)
    return f"Loaded {format_roster_context_label(roster_ctx)} but no league context to persist {label}."


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
    """Resolve Trade / Acquire flow for the active eligible shared league only."""
    display = _display_base(player_name)
    eligible, block_msg = player_trade_shortcut_eligible(session, display)
    if not eligible:
        return block_msg or f"No eligible active-league roster found for {display}."

    try:
        from fantasy_league_context import get_active_league_context, normalize_player_key
        from fantasy_league_team_ownership import owned_team_for_user
    except ImportError:
        return "Trade shortcuts require an active league."

    active = get_active_league_context(session)
    assert isinstance(active, dict)
    my_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
    league_label = str(active.get("display_name") or active.get("league_name") or "League")
    target_key = normalize_player_key(display)
    owner = (active.get("ownership_map") or {}).get(target_key) or {}
    owner_team = str(owner.get("owner_team") or "").strip()
    league_context_id = str(active.get("league_context_id") or "").strip()
    roster_ctx = {
        "context_id": f"flc:{league_context_id}:{owner_team}",
        "source": "fantasy_league_context",
        "draft_label": league_label,
        "team_name": owner_team,
        "is_user_team": owner_team == my_team,
        "your_team": my_team,
        "league_context_id": league_context_id,
    }

    if owner_team == my_team:
        return _finalize_trade_acquire(
            session,
            player=display,
            mode=TRADE_ACTION_TRADE_AWAY,
            roster_ctx=roster_ctx,
        )

    return _finalize_trade_acquire(
        session,
        player=display,
        mode=TRADE_ACTION_ACQUIRE,
        roster_ctx=roster_ctx,
    )


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
            return _finalize_trade_acquire(session, player=player, mode=resolved_mode, roster_ctx=candidates[0])
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
    return _finalize_trade_acquire(session, player=player, mode=resolved_mode, roster_ctx=selected)
