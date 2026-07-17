"""Pure live draft auto-pick selection — no Streamlit app imports."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_pick_engine import live_draft_make_pick
from live_draft_pick_scoring import (
    live_draft_target_counts,
    score_available_for_rule,
)
from live_draft_state import live_draft_get_available
from live_draft_timer_logic import live_draft_current_slot


def _board_size(room: dict[str, Any]) -> int:
    board = room.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def _total_expected_picks(room: dict[str, Any]) -> int:
    pick_order = room.get("pick_order") or []
    if pick_order:
        return len(pick_order)
    teams = room.get("teams") or []
    cfg = dict(room.get("config") or {})
    rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
    if teams and rounds:
        return len(teams) * rounds
    return 0


def _candidate_names(scored: pd.DataFrame, limit: int = 8) -> list[str]:
    col = "fullName" if "fullName" in scored.columns else "Player"
    if col not in scored.columns:
        return []
    return [str(x) for x in scored.head(limit)[col].astype(str).tolist() if str(x).strip()]


def live_draft_auto_pick(room: dict[str, Any], session: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Select and apply auto-pick — queue-first when enabled, else #1 recommendation."""
    try:
        from live_draft_timer_logic import resolve_live_draft_on_clock_slot

        slot = resolve_live_draft_on_clock_slot(room)
    except ImportError:
        slot = live_draft_current_slot(room)
    if slot is None:
        total = _total_expected_picks(room)
        board = _board_size(room)
        if total > 0 and board < total:
            return False, "Draft pick index out of sync — use Manual Draft to recover."
        return False, "Draft is already complete."

    if str(room.get("status") or "") == "paused":
        return False, "Draft is paused — resume before auto-picking."

    available = live_draft_get_available(room)
    if available.empty:
        total = _total_expected_picks(room)
        board = _board_size(room)
        if total > 0 and board >= total:
            room["status"] = "complete"
        return False, "No players remain in the pool."

    team = slot["Team"]
    roster_df = pd.DataFrame(room["rosters"].get(team, []))
    cfg = dict(room.get("config", {}))
    cfg["current_pick"] = int(slot.get("Pick", 1))
    cfg["room"] = room
    target_counts = live_draft_target_counts(cfg)
    configured_rule = str(cfg.get("auto_pick_rule", "balanced recommendation") or "balanced recommendation")

    # Prefer the manager's draft queue when queue auto-pick is enabled (default on).
    queue_enabled = cfg.get("queue_auto_pick", cfg.get("auto_pick_from_queue", True))
    if queue_enabled is None:
        queue_enabled = True
    if bool(queue_enabled) and session is not None:
        queue_ok, queue_msg = _try_queue_auto_pick(room, session, available, team)
        if queue_ok:
            return True, queue_msg

    rec_scored = pd.DataFrame()
    gaps: list[str] = []
    used_rec_cache = False
    if session is not None:
        try:
            from live_draft_ui_cache import REC_CACHE_KEY, live_draft_ui_cache_key

            cache_key = live_draft_ui_cache_key(session, room, top_n=8, team=None)
            entry = session.get(REC_CACHE_KEY)
            if isinstance(entry, dict) and entry.get("key") == cache_key:
                top_rec = entry.get("top_rec")
                if isinstance(top_rec, pd.DataFrame) and not top_rec.empty:
                    rec_scored = top_rec
                    used_rec_cache = True
                    session["_live_draft_autopick_used_rec_cache"] = True
        except ImportError:
            pass
    if session is not None and not used_rec_cache:
        session["_live_draft_autopick_used_rec_cache"] = False

    if not used_rec_cache:
        rec_scored, gaps = score_available_for_rule(
            available, roster_df, "balanced recommendation", target_counts, config=cfg
        )
    if rec_scored.empty:
        return False, "No eligible recommendation for auto-pick."

    chosen = rec_scored.iloc[0]
    chosen_dict = chosen.to_dict()
    top_rec_name = str(chosen.get("fullName") or chosen.get("Player") or "").strip()
    skip_reason = ""
    rule_pick_name = ""

    # Prefer the #1 cached balanced recommendation for timer autopick; only score a
    # secondary configured rule when the operator did not use balanced recommendation.
    if configured_rule.strip().lower() != "balanced recommendation" and not used_rec_cache:
        rule_scored, _ = score_available_for_rule(
            available, roster_df, configured_rule, target_counts, config=cfg
        )
        if not rule_scored.empty:
            rule_pick_name = str(rule_scored.iloc[0].get("fullName") or rule_scored.iloc[0].get("Player") or "").strip()
            if rule_pick_name and rule_pick_name != top_rec_name:
                skip_reason = (
                    f"Configured rule '{configured_rule}' would pick {rule_pick_name}; "
                    f"using top recommendation {top_rec_name}."
                )

    from live_draft_pick_engine import build_structured_pick_verdict

    verdict = build_structured_pick_verdict(chosen_dict, pick_source="Auto Pick", gaps=gaps)
    ok, msg = live_draft_make_pick(
        room,
        chosen_dict,
        verdict=verdict,
        pick_source="Auto Pick",
        snapshot=chosen_dict,
    )

    if session is not None:
        try:
            from live_draft_expired_pick import record_autopick_diagnostics

            record_autopick_diagnostics(
                session,
                auto_pick_candidate_list=_candidate_names(rec_scored),
                top_recommendation_player=top_rec_name,
                selected_auto_pick_player=top_rec_name if ok else None,
                selected_auto_pick_reason=verdict if ok else msg,
                auto_pick_rule_configured=configured_rule,
                top_recommendation_skipped_reason=skip_reason or None,
                configured_rule_would_pick=rule_pick_name or None,
                auto_pick_from_queue=False,
            )
        except ImportError:
            pass

    return ok, msg


def _normalize_player_key(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def _try_queue_auto_pick(
    room: dict[str, Any],
    session: dict[str, Any],
    available: pd.DataFrame,
    team: str,
) -> tuple[bool, str]:
    """Draft the first still-available queued player for the on-clock team."""
    your_team = str(
        room.get("your_team")
        or (room.get("config") or {}).get("your_team")
        or session.get("your_team")
        or ""
    ).strip()
    # Queue is personal — only apply when this manager's team is on the clock
    # (or when no your_team is configured, e.g. solo drafts).
    if your_team and your_team.lower() != str(team or "").strip().lower():
        return False, ""

    queue_raw = session.get("draft_queue") or []
    if not isinstance(queue_raw, list) or not queue_raw:
        return False, ""

    name_col = "fullName" if "fullName" in available.columns else ("Player" if "Player" in available.columns else None)
    if not name_col:
        return False, ""

    available_by_name: dict[str, dict[str, Any]] = {}
    for _, row in available.iterrows():
        key = _normalize_player_key(str(row.get(name_col) or ""))
        if key and key not in available_by_name:
            available_by_name[key] = row.to_dict()

    chosen_dict: dict[str, Any] | None = None
    chosen_name = ""
    for entry in queue_raw:
        if isinstance(entry, dict):
            name = str(entry.get("fullName") or entry.get("Player") or entry.get("name") or "").strip()
        else:
            name = str(entry or "").strip()
        if not name:
            continue
        hit = available_by_name.get(_normalize_player_key(name))
        if hit:
            chosen_dict = hit
            chosen_name = name
            break
    if not chosen_dict:
        return False, ""

    from live_draft_pick_engine import build_structured_pick_verdict

    verdict = build_structured_pick_verdict(chosen_dict, pick_source="Queue Auto Pick", gaps=[])
    ok, msg = live_draft_make_pick(
        room,
        chosen_dict,
        verdict=verdict,
        pick_source="Queue Auto Pick",
        snapshot=chosen_dict,
    )
    if ok:
        try:
            from draft_state import remove_player_from_draft_queue

            remove_player_from_draft_queue(session, chosen_name, reason="queue_autopick")
        except Exception:
            # Best-effort queue cleanup — pick already applied.
            q = [x for x in (session.get("draft_queue") or []) if _normalize_player_key(
                str(x.get("fullName") if isinstance(x, dict) else x)
            ) != _normalize_player_key(chosen_name)]
            session["draft_queue"] = q
        try:
            from live_draft_expired_pick import record_autopick_diagnostics

            record_autopick_diagnostics(
                session,
                selected_auto_pick_player=chosen_name,
                selected_auto_pick_reason=verdict,
                auto_pick_from_queue=True,
                top_recommendation_player=chosen_name,
            )
        except ImportError:
            pass
        return True, msg or f"Queue auto-picked {chosen_name}."
    return False, msg or ""
