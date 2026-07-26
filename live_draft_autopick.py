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
    """Prefer config teams×rounds — never trust a truncated pick_order alone."""
    try:
        from live_draft_safe_mode import total_expected_picks

        return int(total_expected_picks(room) or 0)
    except ImportError:
        pass
    pick_order = room.get("pick_order") or []
    teams = room.get("teams") or []
    cfg = dict(room.get("config") or {})
    rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
    if teams and rounds:
        return len(teams) * rounds
    return len(pick_order) if isinstance(pick_order, list) else 0


def _candidate_names(scored: pd.DataFrame, limit: int = 8) -> list[str]:
    col = "fullName" if "fullName" in scored.columns else "Player"
    if col not in scored.columns:
        return []
    return [str(x) for x in scored.head(limit)[col].astype(str).tolist() if str(x).strip()]


def live_draft_auto_pick(
    room: dict[str, Any],
    session: dict[str, Any] | None = None,
    *,
    persist: bool = True,
    finalize: bool = True,
) -> tuple[bool, str]:
    """Select and apply auto-pick using the Draft Setup Auto-Pick Rule on the legal pool.

    Mutations always go through ``live_draft_make_pick``. When ``finalize`` is True,
    shared post-pick side effects (queue prune, cache patch, canonical snapshot,
    immediate-paint gate) run via ``finalize_live_draft_pick_transition``.

    The draft queue is never consulted for automatic selection (manual aid only).
    """
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

    # Fragment / page double-fire guard: claim this pick before mutating.
    claim_key = ""
    if session is not None:
        try:
            from live_draft_canonical_snapshot import (
                auto_pick_idempotency_key,
                clear_stale_auto_pick_idempotency,
                idempotency_key_committed,
            )

            clear_stale_auto_pick_idempotency(session, room)
            claim_key = auto_pick_idempotency_key(room)
            last = str(session.get("_live_draft_last_auto_pick_idempotency_key") or "")
            inflight = str(session.get("_live_draft_in_flight_auto_pick_key") or "")
            room_last = str(room.get("_last_auto_pick_idempotency_key") or "")
            if claim_key and claim_key == inflight:
                if idempotency_key_committed(room, claim_key):
                    return True, "Auto-pick already in progress for this pick."
            if claim_key and (
                (claim_key == last and idempotency_key_committed(room, claim_key))
                or (claim_key == room_last and idempotency_key_committed(room, claim_key))
            ):
                return True, "Auto-pick already applied for this pick."
            if claim_key and (claim_key == last or claim_key == room_last):
                session.pop("_live_draft_last_auto_pick_idempotency_key", None)
                room.pop("_last_auto_pick_idempotency_key", None)
            if claim_key:
                session["_live_draft_in_flight_auto_pick_key"] = claim_key
        except ImportError:
            claim_key = ""

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

    board_before = _board_size(room)
    idx_before = int(room.get("current_pick_index") or 0)

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

    # Authoritative Draft Setup Auto-Pick Rule — never invent a separate formula.
    rule_key = str(configured_rule or "balanced recommendation").strip() or "balanced recommendation"
    skip_reason = ""
    if used_rec_cache and rule_key.lower() != "balanced recommendation":
        # Cached tables are balanced-scored; rescore with the configured rule.
        used_rec_cache = False
        skip_reason = "Ignored balanced recommendation cache for configured auto-pick rule."

    if used_rec_cache and not rec_scored.empty:
        pid_col = "playerID" if "playerID" in rec_scored.columns else None
        drafted = {str(x).strip() for x in (room.get("drafted_player_ids") or []) if str(x).strip()}
        if pid_col and drafted:
            rec_scored = rec_scored[~rec_scored[pid_col].astype(str).isin(drafted)]
        if rec_scored.empty:
            used_rec_cache = False
            skip_reason = "Cached recommendations were stale — rescoring available pool."

    if not used_rec_cache:
        rec_scored, gaps = score_available_for_rule(
            available, roster_df, rule_key, target_counts, config=cfg
        )
    if rec_scored.empty:
        if session is not None:
            session.pop("_live_draft_in_flight_auto_pick_key", None)
        return False, "No eligible recommendation for auto-pick."

    chosen = rec_scored.iloc[0]
    chosen_dict = chosen.to_dict()
    top_rec_name = str(chosen.get("fullName") or chosen.get("Player") or "").strip()
    player_id = str(chosen_dict.get("playerID") or chosen_dict.get("player_id") or "").strip()

    from live_draft_pick_engine import build_structured_pick_verdict

    verdict = build_structured_pick_verdict(chosen_dict, pick_source="Auto Pick", gaps=gaps)
    ok, msg = live_draft_make_pick(
        room,
        chosen_dict,
        verdict=verdict,
        pick_source="Auto Pick",
        snapshot=chosen_dict,
        session=session,
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
                configured_rule_would_pick=top_rec_name if ok else None,
                auto_pick_from_queue=False,
            )
        except ImportError:
            pass
        if ok and finalize:
            try:
                from live_draft_pick_commit import finalize_live_draft_pick_transition

                fin = finalize_live_draft_pick_transition(
                    session,
                    room,
                    source="Auto Pick",
                    player_id=player_id,
                    player_name=top_rec_name,
                    board_size_before=board_before,
                    idx_before=idx_before,
                    persist=persist,
                    fast_path=True,
                    request_immediate_paint=True,
                )
                if not fin.ok:
                    try:
                        from live_draft_canonical_snapshot import pick_commit_confirmed

                        if not pick_commit_confirmed(
                            room, pick_index_before=idx_before, board_size_before=board_before
                        ):
                            session.pop("_live_draft_in_flight_auto_pick_key", None)
                            return False, fin.message or msg
                    except ImportError:
                        session.pop("_live_draft_in_flight_auto_pick_key", None)
                        return False, fin.message or msg
            except Exception:
                pass
        session.pop("_live_draft_in_flight_auto_pick_key", None)

    if ok:
        board_after = _board_size(room)
        idx_after = int(room.get("current_pick_index") or 0)
        complete = str(room.get("status") or "") == "complete"
        if not complete and (board_after <= board_before or idx_after <= idx_before):
            if session is not None:
                try:
                    from live_draft_canonical_snapshot import clear_stale_auto_pick_idempotency

                    clear_stale_auto_pick_idempotency(session, room)
                except ImportError:
                    pass
                session.pop("_live_draft_in_flight_auto_pick_key", None)
            return False, "Auto-pick did not advance the draft board."

    return ok, msg


def _normalize_player_key(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def _try_queue_auto_pick(
    room: dict[str, Any],
    session: dict[str, Any],
    available: pd.DataFrame,
    team: str,
    *,
    board_before: int = 0,
    idx_before: int = 0,
    persist: bool = True,
    finalize: bool = True,
) -> tuple[bool, str]:
    """Draft the first still-available queued player for the on-clock team.

    Uses only the on-clock participant's private queue scoped by (room, user).
    """
    your_team = ""
    try:
        from draft_room_participant_state import active_participant_team

        your_team = str(active_participant_team(session) or "").strip()
    except ImportError:
        pass
    if not your_team:
        your_team = str(
            room.get("your_team")
            or (room.get("config") or {}).get("your_team")
            or session.get("draft_room_participant_team")
            or session.get("room_your_team")
            or session.get("your_team")
            or ""
        ).strip()
    # Queue is personal — only apply when this manager's team is on the clock
    # (or when no your_team is configured, e.g. solo drafts).
    if your_team and your_team.lower() != str(team or "").strip().lower():
        return False, ""

    queue_raw: list[Any] = []
    try:
        from draft_room_context import resolve_shared_room_code
        from draft_room_participant_state import participant_workflow_slot, resolve_participant_id

        code = str(resolve_shared_room_code(session) or "").strip().upper()
        if code:
            slot = participant_workflow_slot(session, code)
            wf = dict(slot.get("workflow") or {})
            queue_raw = list(wf.get("queue") or [])
            session["_draft_queue_autopick_scope"] = {
                "room_code": code,
                "user_id": resolve_participant_id(session),
                "team": your_team,
                "source": "participant_slot",
            }
    except ImportError:
        pass
    if not queue_raw:
        queue_raw = session.get("draft_queue") or []
        if isinstance(session.get("_draft_queue_autopick_scope"), dict):
            session["_draft_queue_autopick_scope"]["source"] = "session_fallback"
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
    player_id = str(chosen_dict.get("playerID") or chosen_dict.get("player_id") or "").strip()
    ok, msg = live_draft_make_pick(
        room,
        chosen_dict,
        verdict=verdict,
        pick_source="Queue Auto Pick",
        snapshot=chosen_dict,
        session=session,
    )
    if ok:
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
        if finalize:
            try:
                from live_draft_pick_commit import finalize_live_draft_pick_transition

                finalize_live_draft_pick_transition(
                    session,
                    room,
                    source="Queue Auto Pick",
                    player_id=player_id,
                    player_name=chosen_name,
                    board_size_before=board_before,
                    idx_before=idx_before,
                    persist=persist,
                    fast_path=True,
                    request_immediate_paint=True,
                )
            except Exception:
                # Fall back to best-effort queue prune if finalize is unavailable.
                try:
                    from draft_state import remove_drafted_player_from_active_queues

                    remove_drafted_player_from_active_queues(session, chosen_name)
                except Exception:
                    q = [
                        x
                        for x in (session.get("draft_queue") or [])
                        if _normalize_player_key(str(x.get("fullName") if isinstance(x, dict) else x))
                        != _normalize_player_key(chosen_name)
                    ]
                    session["draft_queue"] = q
        return True, msg or f"Queue auto-picked {chosen_name}."
    return False, msg or ""
