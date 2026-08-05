"""Shared Streamlit draft button — single UI path via draft_actions."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from draft_actions import can_draft_player, draft_action_context, draft_button_diagnostics, draft_player

PENDING_MANUAL_PICK_KEY = "_pending_manual_draft_pick"
DISABLE_AUTOPICK_FOR_TESTING_KEY = "_live_draft_disable_autopick_for_testing"
MANUAL_CANDIDATE_SNAPSHOT_KEY = "_live_draft_manual_candidate_snapshot"
# Legacy key — do not use for new widgets (pick-index keys are authoritative).
MANUAL_PICK_SELECTBOX_KEY = "live_draft_player_select"
MANUAL_DRAFT_BUTTON_KEY = "draft_btn_live_draft_room_live_manual"
QUEUE_PLAYER_META_KEY = "_queue_player_meta"
DRAFT_PLAYER_META_LOOKUP_KEY = "_draft_player_meta_lookup"


def format_queue_player_label(player_name: str, meta: dict[str, str] | None = None) -> str:
    """Display label: Player Name — Position — Team."""
    name = str(player_name or "").strip()
    if not name:
        return ""
    meta = meta or {}
    pos = str(meta.get("position") or "—").strip() or "—"
    team = str(meta.get("team") or "—").strip() or "—"
    return f"{name} — {pos} — {team}"


def score_queue_player_for_on_clock_team(
    session: dict[str, Any],
    pool_row: Any,
    *,
    room: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Score one queue row with the on-clock team's roster context (same engine as recs)."""
    if pool_row is None:
        return None
    try:
        import pandas as pd

        from live_draft_canonical_snapshot import get_live_draft_paint_snapshot
        from live_draft_pick_scoring import live_draft_target_counts, score_available_for_rule

        live = room if isinstance(room, dict) else session.get("live_draft_room")
        if not isinstance(live, dict):
            return None
        paint = get_live_draft_paint_snapshot(session)
        team = str(paint.get("team_on_clock") or "").strip()
        if not team:
            return None
        if isinstance(pool_row, pd.Series):
            row_df = pd.DataFrame([pool_row.to_dict()])
        elif isinstance(pool_row, dict):
            row_df = pd.DataFrame([dict(pool_row)])
        else:
            return None
        roster_df = pd.DataFrame((live.get("rosters") or {}).get(team, []))
        cfg = dict(live.get("config") or {})
        cfg["current_pick"] = paint.get("current_pick") or cfg.get("current_pick")
        cfg["room"] = live
        target_counts = live_draft_target_counts(cfg)
        rule_key = str(cfg.get("auto_pick_rule") or "balanced recommendation")
        scored, _ = score_available_for_rule(row_df, roster_df, rule_key, target_counts, config=cfg)
        if scored.empty:
            return None
        return scored.iloc[0].to_dict()
    except Exception:
        return None


def format_queue_player_metrics_line(pool_row: Any, session: dict[str, Any] | None = None, room: dict[str, Any] | None = None) -> str:
    """Proj: line plus Decision Score / Roster Fit for queue rows."""
    if pool_row is None:
        return ""
    try:
        from player_photos import compact_fantasy_stat_line, decision_score_display, roster_fit_display

        scored_row = pool_row
        if session is not None:
            try:
                from draft_ui import score_queue_player_for_on_clock_team

                scored_row = score_queue_player_for_on_clock_team(session, pool_row, room=room) or pool_row
            except ImportError:
                scored_row = pool_row

        bits: list[str] = []
        stat_line = compact_fantasy_stat_line(scored_row)
        if stat_line:
            bits.append(stat_line)
        ds = decision_score_display(scored_row)
        rf = roster_fit_display(scored_row)
        score_bits: list[str] = []
        if ds and ds != "Not available":
            score_bits.append(f"Decision Score {ds}")
        if rf and rf not in ("Not available", "Roster Fit calculating…", "0.00"):
            score_bits.append(f"Roster Fit {rf}")
        elif rf == "Roster Fit calculating…":
            score_bits.append(rf)
        if score_bits:
            bits.append(" · ".join(score_bits))
        return " · ".join(bits)
    except ImportError:
        return ""


def cache_queue_player_meta(session: dict[str, Any], player_name: str, meta: dict[str, str]) -> None:
    name = str(player_name or "").strip()
    if not name:
        return
    store = session.get(QUEUE_PLAYER_META_KEY)
    if not isinstance(store, dict):
        store = {}
    store[name.lower()] = {
        "position": str(meta.get("position") or "—").strip() or "—",
        "team": str(meta.get("team") or "—").strip() or "—",
    }
    session[QUEUE_PLAYER_META_KEY] = store
    session.pop(DRAFT_PLAYER_META_LOOKUP_KEY, None)


def _draft_pool_for_meta_lookup(session: dict[str, Any]) -> Any:
    """Best-effort player pool for queue meta without heavy reconcile."""
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict):
            pool = room.get("pool")
            if pool is not None and not getattr(pool, "empty", True):
                return pool
    except ImportError:
        pass
    lab = session.get("draft_lab_results")
    if isinstance(lab, dict):
        pool = lab.get("pool")
        if pool is not None and not getattr(pool, "empty", True):
            return pool
    pool_df = session.get("draft_room_player_pool")
    if pool_df is not None and not getattr(pool_df, "empty", True):
        return pool_df
    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session)
        if board is not None and not getattr(board, "empty", True) and "Player" in board.columns:
            return board
    except Exception:
        pass
    return None


def _ensure_draft_player_meta_lookup(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cached = session.get(DRAFT_PLAYER_META_LOOKUP_KEY)
    if isinstance(cached, dict) and cached:
        return cached
    merged: dict[str, dict[str, Any]] = {}
    ami = session.get("_ami_undrafted_pool_lookup")
    if isinstance(ami, dict):
        merged.update(ami)
    qmeta = session.get(QUEUE_PLAYER_META_KEY)
    if isinstance(qmeta, dict):
        for key, val in qmeta.items():
            if isinstance(val, dict):
                merged[str(key).lower()] = val
    pool = _draft_pool_for_meta_lookup(session)
    if pool is not None:
        try:
            from draft_ami_helpers import build_undrafted_player_lookup

            pool_lookup = build_undrafted_player_lookup(pool)
            for key, val in pool_lookup.items():
                merged.setdefault(str(key).lower(), val)
        except ImportError:
            pass
    session[DRAFT_PLAYER_META_LOOKUP_KEY] = merged
    return merged


def manual_draft_candidate_widget_key(room: dict[str, Any]) -> str:
    """Stable per-pick selectbox key so candidate state cannot bleed across picks."""
    idx = int(room.get("current_pick_index") or 0)
    return f"live_draft_manual_candidate_i{idx}"


def _record_visible_draft_candidate(
    session: dict[str, Any],
    available: Any,
    widget_key: str,
    *,
    fallback_name: str = "",
    source: str = "render",
) -> dict[str, str]:
    """Sync visible dropdown selection into session snapshot + diagnostics."""
    name = str(session.get(widget_key) or fallback_name or "").strip()
    player_id = _player_id_from_available(available, name) if name else ""
    snap = {
        "name": name,
        "id": player_id,
        "widget_key": widget_key,
        "source": source,
    }
    session[MANUAL_CANDIDATE_SNAPSHOT_KEY] = snap
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            draft_candidate_widget_key=widget_key,
            draft_candidate_widget_value=name or None,
            visible_draft_candidate_name=name or None,
            visible_draft_candidate_id=player_id or None,
        )
    except ImportError:
        pass
    return snap


def queue_manual_draft_pick(
    session: dict[str, Any],
    *,
    player_name: str = "",
    player_id: str | None = None,
    pool_source: str = "",
    candidate_source: str = "manual_panel",
    widget_key: str = "",
) -> bool:
    """Store a manual pick from st.button on_click before any rerun/restore can drop the click."""
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(session, queue_manual_draft_pick_entered=True)
    except ImportError:
        pass

    source = str(candidate_source or "")
    from_rec_card = source.startswith("rec_card")

    snap = session.get(MANUAL_CANDIDATE_SNAPSHOT_KEY)
    if not isinstance(snap, dict):
        snap = {}

    if from_rec_card:
        wkey = ""
        selected_id = str(player_id or "").strip()
        name = str(player_name or "").strip()
        if selected_id and not name:
            try:
                from draft_actions import _find_live_player_by_id

                row = _find_live_player_by_id(session, selected_id)
                if row:
                    name = str(row.get("fullName") or row.get("Player") or "").strip()
            except ImportError:
                pass
        if name and not selected_id:
            try:
                from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_get_available

                room = session.get(LIVE_DRAFT_ROOM_KEY)
                if isinstance(room, dict):
                    available = live_draft_get_available(room)
                    selected_id = _player_id_from_available(available, name)
            except Exception:
                pass
    else:
        wkey = str(widget_key or snap.get("widget_key") or "").strip()
        name = ""
        if wkey:
            name = str(session.get(wkey) or "").strip()
        if not name:
            name = str(player_name or snap.get("name") or "").strip()

        selected_id = str(player_id or "").strip()
        if name and not selected_id:
            try:
                from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_get_available

                room = session.get(LIVE_DRAFT_ROOM_KEY)
                if isinstance(room, dict):
                    available = live_draft_get_available(room)
                    selected_id = _player_id_from_available(available, name)
            except Exception:
                pass
        if name and not selected_id and str(snap.get("name") or "").strip() == name:
            selected_id = str(snap.get("id") or "").strip()

    still_available = False
    if name:
        try:
            from draft_actions import _live_player_available

            still_available, _ = _live_player_available(session, name)
        except Exception:
            still_available = bool(name)

    if not name:
        try:
            from draft_commit_diagnostics import record_draft_commit_diagnostics

            record_draft_commit_diagnostics(
                session,
                draft_button_clicked=True,
                manual_pick_error="no_player_selected",
                pending_manual_pick_exists=False,
            )
        except ImportError:
            pass
        session["_live_draft_pick_flash_error"] = "Select a player first."
        session.pop(PENDING_MANUAL_PICK_KEY, None)
        return False

    pending = {
        "player_name": name,
        "selected_player_id": selected_id,
        "pool_source": pool_source,
        "candidate_source": candidate_source,
        "player_still_available_at_click": still_available,
        "widget_key": wkey,
        "queued_at": time.time(),
        "rec_card_player_id": selected_id if from_rec_card else "",
        "rec_card_player_name": name if from_rec_card else "",
    }
    session[PENDING_MANUAL_PICK_KEY] = pending
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY
        from live_draft_pick_timer import freeze_timer_for_pick_submit

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict):
            freeze_timer_for_pick_submit(session, room)
    except ImportError:
        pass
    if str(candidate_source or "").startswith("rec_card"):
        try:
            from live_draft_room_ui import record_rec_card_diagnostics

            record_rec_card_diagnostics(
                session,
                rec_card_draft_click_received=True,
                rec_card_player=name,
            )
        except ImportError:
            pass
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            draft_button_clicked=True,
            selected_player_at_click=name,
            selected_player_name=name,
            selected_player_id=selected_id or None,
            candidate_source=candidate_source,
            pool_source=pool_source,
            player_still_available_at_click=still_available,
            draft_candidate_widget_key=wkey or None,
            draft_candidate_widget_value=name,
            visible_draft_candidate_name=name,
            visible_draft_candidate_id=selected_id or None,
            queued_manual_pick_player_name=name,
            queued_manual_pick_player_id=selected_id or None,
            pending_manual_pick_exists=True,
            pending_manual_pick_player_name=name,
            pending_manual_pick_player_id=selected_id or None,
        )
    except ImportError:
        pass
    return True


def live_draft_autopick_disabled(session: dict[str, Any]) -> bool:
    return bool(session.get(DISABLE_AUTOPICK_FOR_TESTING_KEY))


def process_pending_manual_draft_pick(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a queued manual pick at page entry — before autopick, poll, or canonical restore.

    Returns {processed, ok, should_rerun, message, error}.
    """
    pending_raw = session.get(PENDING_MANUAL_PICK_KEY)
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            process_pending_manual_draft_pick_entered=True,
            pending_manual_pick_exists=isinstance(pending_raw, dict),
            pending_manual_pick_player_name=(pending_raw or {}).get("player_name") if isinstance(pending_raw, dict) else None,
            pending_manual_pick_player_id=(pending_raw or {}).get("selected_player_id") if isinstance(pending_raw, dict) else None,
        )
    except ImportError:
        pass

    pending = session.pop(PENDING_MANUAL_PICK_KEY, None)
    if not isinstance(pending, dict):
        return {"processed": False, "ok": False, "should_rerun": False, "message": "", "error": ""}

    player_name = str(pending.get("player_name") or "").strip()
    if not player_name:
        try:
            from live_draft_pick_timer import clear_pick_submit_state

            clear_pick_submit_state(session)
        except ImportError:
            pass
        return {
            "processed": True,
            "ok": False,
            "should_rerun": False,
            "message": "",
            "error": "Select a player first.",
        }

    if str(pending.get("candidate_source") or "").startswith("rec_card"):
        card_name = str(pending.get("rec_card_player_name") or player_name).strip()
        pid = str(pending.get("selected_player_id") or pending.get("rec_card_player_id") or "").strip()
        try:
            from draft_actions import _find_live_player_by_id

            if pid:
                row = _find_live_player_by_id(session, pid)
                if not row:
                    from live_draft_pick_timer import clear_pick_submit_state

                    clear_pick_submit_state(session)
                    return {
                        "processed": True,
                        "ok": False,
                        "should_rerun": False,
                        "message": "",
                        "error": f"Recommended player is no longer available.",
                    }
                resolved = str(row.get("fullName") or row.get("Player") or "").strip()
                if resolved:
                    player_name = resolved
        except ImportError:
            pass
        if card_name and player_name.lower() != card_name.lower():
            try:
                from live_draft_pick_timer import clear_pick_submit_state

                clear_pick_submit_state(session)
            except ImportError:
                pass
            return {
                "processed": True,
                "ok": False,
                "should_rerun": False,
                "message": "",
                "error": "Recommendation card player mismatch — pick not submitted.",
            }

    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, is_live_draft_locally_dirty, mark_live_draft_local_edit

        mark_live_draft_local_edit(session)
        local_dirty_before = is_live_draft_locally_dirty(session)
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        board_before = len(room.get("draft_board") or []) if isinstance(room, dict) else 0
        idx_before = int(room.get("current_pick_index") or 0) if isinstance(room, dict) else 0
    except ImportError:
        local_dirty_before = True
        board_before = 0
        idx_before = 0

    session["_live_draft_manual_pick_in_flight"] = True
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            draft_button_clicked=True,
            selected_player_at_click=player_name,
            selected_player_name=player_name,
            selected_player_id=pending.get("selected_player_id") or None,
            candidate_source=pending.get("candidate_source"),
            pool_source=pending.get("pool_source"),
            player_still_available_at_click=pending.get("player_still_available_at_click"),
            manual_pick_attempted=True,
            draft_player_called=True,
            local_dirty_before_commit=local_dirty_before,
            board_size_before_manual_pick=board_before,
            current_pick_index_before_manual_pick=idx_before,
        )
    except ImportError:
        pass
    if str(pending.get("candidate_source") or "").startswith("rec_card"):
        session["_rec_card_commit_in_flight"] = True
        try:
            from live_draft_room_ui import record_rec_card_diagnostics

            record_rec_card_diagnostics(
                session,
                rec_card_commit_started=True,
                rec_card_player=player_name,
                rec_card_player_id=pending.get("selected_player_id"),
            )
        except ImportError:
            pass

    result = draft_player(session, player_name, source="live_draft_room", st_obj=st)
    ok = bool(result.get("ok"))
    msg = str(result.get("message") or result.get("error") or "Drafted.")
    err = str(result.get("error") or "")

    try:
        from live_draft_state import check_manual_commit_overwrite, is_live_draft_locally_dirty, record_manual_pick_snapshot

        if ok:
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            board_after = len(room.get("draft_board") or []) if isinstance(room, dict) else board_before
            idx_after = int(room.get("current_pick_index") or 0) if isinstance(room, dict) else idx_before
            record_manual_pick_snapshot(session, board_after, idx_after)
            check_manual_commit_overwrite(session, source="after_pending_commit")
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            local_dirty_after_commit=is_live_draft_locally_dirty(session),
        )
    except ImportError:
        pass

    session.pop("_rec_card_commit_in_flight", None)
    try:
        from live_draft_pick_timer import clear_pick_submit_state

        clear_pick_submit_state(session)
    except ImportError:
        pass

    # Keep poll-skip guard after success — cleared by streamlit_app after ~5s.
    # Clearing in_flight here allowed shared poll to overwrite the committed pick.
    if not ok:
        session.pop("_live_draft_manual_pick_in_flight", None)

    # Phase 2: paint board on this same Streamlit run — no second full-page rerun.
    should_rerun = False
    if ok:
        try:
            from live_draft_room_ui import record_rec_card_diagnostics

            if str(pending.get("candidate_source") or "").startswith("rec_card"):
                record_rec_card_diagnostics(session, rec_card_commit_success=True, local_optimistic_update_applied=True)
        except ImportError:
            pass

    return {
        "processed": True,
        "ok": ok,
        "should_rerun": should_rerun,
        "message": msg,
        "error": err,
    }


def draft_disabled_hint(reason: str) -> str:
    """Short user-facing hint when draft is not allowed."""
    text = str(reason or "").strip()
    if text.startswith("Waiting for"):
        return text
    if text.startswith("Already drafted"):
        return text
    if text.startswith("Not your pick"):
        return "Not your pick"
    return text[:80] if text else "Cannot draft"


def _meta_field(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in row:
            continue
        val = row.get(key)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        text = str(val).strip()
        if text and text.lower() != "nan":
            return text
    return None


def lookup_player_draft_meta(session: dict[str, Any], player_name: str) -> dict[str, str]:
    """Best-effort position + MLB team for queue display."""
    name = str(player_name or "").strip()
    meta = {"position": "—", "team": "—"}
    if not name:
        return meta
    target = name.lower()

    def _from_row(row: dict[str, Any]) -> dict[str, str]:
        pos = (
            _meta_field(
                row,
                "eligible_positions",
                "Eligible Positions",
                "Primary Position",
                "primaryPos",
                "displayPosition",
                "position",
                "Position",
            )
            or "—"
        )
        team = (
            _meta_field(
                row,
                "Team",
                "team",
                "teamAbbrev",
                "teamName",
                "displayTeam",
                "primaryTeamName",
                "Franchise",
            )
            or "—"
        )
        return {"position": pos, "team": team}

    def _match_pool(pool: Any) -> dict[str, str] | None:
        if pool is None or getattr(pool, "empty", True):
            return None
        col = "fullName" if "fullName" in pool.columns else "Player"
        if col not in pool.columns:
            return None
        for _, row in pool.iterrows():
            full = str(row.get(col) or "").strip()
            if full.lower() == target or full == name:
                return _from_row(row.to_dict())
        return None

    qmeta = session.get(QUEUE_PLAYER_META_KEY)
    if isinstance(qmeta, dict):
        cached = qmeta.get(target) or qmeta.get(name)
        if isinstance(cached, dict):
            cpos = str(cached.get("position") or "—").strip() or "—"
            cteam = str(cached.get("team") or "—").strip() or "—"
            if cpos.lower() == "nan":
                cpos = "—"
            if cteam.lower() == "nan":
                cteam = "—"
            if cteam != "—":
                if cpos != "—":
                    return {"position": cpos, "team": cteam}
                meta["team"] = cteam
            elif cpos != "—":
                meta["position"] = cpos

    pool = _draft_pool_for_meta_lookup(session)
    if pool is not None:
        hit = _match_pool(pool)
        if hit and hit.get("team") != "—":
            if hit.get("position") != "—":
                cache_queue_player_meta(session, name, hit)
                return hit
            meta["team"] = hit["team"]
        elif hit and hit.get("position") != "—" and meta.get("position") == "—":
            meta["position"] = hit["position"]

    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session)
        if board is not None and not getattr(board, "empty", True):
            hit = _match_pool(board)
            if hit and hit.get("team") != "—":
                if hit.get("position") != "—":
                    cache_queue_player_meta(session, name, hit)
                    return hit
                meta["team"] = hit["team"]
            elif hit and hit.get("position") != "—":
                meta["position"] = hit["position"]
    except Exception:
        pass

    lookup = _ensure_draft_player_meta_lookup(session)
    row = lookup.get(target) or lookup.get(name)
    if isinstance(row, dict):
        resolved = _from_row(row)
        if resolved.get("team") != "—":
            if meta.get("position") != "—":
                resolved["position"] = meta["position"]
            cache_queue_player_meta(session, name, resolved)
            return resolved
        if resolved.get("position") != "—" and meta.get("position") == "—":
            meta["position"] = resolved["position"]

    try:
        from draft_ami_helpers import build_player_position_index_from_session

        pos_index = build_player_position_index_from_session(session)
        pos = pos_index.get(target) or pos_index.get(name.lower())
        if pos and meta.get("position") == "—":
            meta["position"] = pos
    except Exception:
        pass

    if meta["position"] != "—" or meta["team"] != "—":
        cache_queue_player_meta(session, name, meta)
    return meta


def lookup_player_pool_row(session: dict[str, Any], player_name: str) -> Any:
    """Full draft-pool row for queue photos and projected stat lines."""
    name = str(player_name or "").strip()
    if not name:
        return None
    target = name.lower()

    def _match_pool(pool: Any) -> Any:
        if pool is None or getattr(pool, "empty", True):
            return None
        col = "fullName" if "fullName" in pool.columns else "Player"
        if col not in pool.columns:
            return None
        for _, row in pool.iterrows():
            full = str(row.get(col) or "").strip()
            if full.lower() == target or full == name:
                return row
        return None

    pool = _draft_pool_for_meta_lookup(session)
    hit = _match_pool(pool)
    if hit is not None:
        return hit
    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session)
        return _match_pool(board)
    except Exception:
        return None


def render_draft_button(
    st: Any,
    session: dict[str, Any],
    player_name: str,
    *,
    source: str,
    key_suffix: str,
    use_sidebar: bool = False,
    column: Any = None,
    label: str = "Draft",
    button_type: str = "secondary",
    show_disabled_reason: bool = True,
    flash_key: str = "workflow_sidebar_flash",
    extra_disabled: bool = False,
    extra_disabled_reason: str = "",
) -> bool:
    """
    Render a draft button wired to draft_player().

    Returns True when a draft was attempted (caller should st.rerun()).
    """
    name = str(player_name or "").strip()
    container = column if column is not None else (st.sidebar if use_sidebar else st)
    btn_key = f"draft_btn_{source}_{key_suffix}"

    if extra_disabled:
        container.button(
            label,
            key=f"{btn_key}_blocked",
            disabled=True,
            use_container_width=True,
            type=button_type,
        )
        if show_disabled_reason and extra_disabled_reason:
            container.caption(draft_disabled_hint(extra_disabled_reason))
        return False

    allowed, reason = can_draft_player(session, name)
    gate_message = reason
    try:
        from draft_actions import resolve_player_draft_gate

        gate = resolve_player_draft_gate(session, name, source=source)
        allowed = bool(gate.get("allowed"))
        gate_message = str(gate.get("disable_message") or reason or "")
    except ImportError:
        pass
    if allowed:
        if container.button(label, key=btn_key, use_container_width=True, type=button_type):
            try:
                from draft_commit_diagnostics import record_draft_commit_diagnostics

                record_draft_commit_diagnostics(
                    session,
                    draft_button_clicked=True,
                    selected_player_at_click=name,
                )
            except ImportError:
                pass
            result = draft_player(session, name, source=source, st_obj=st)
            msg = str(result.get("message") or result.get("error") or "Drafted.")
            session[flash_key] = msg
            if result.get("ok"):
                session["_live_draft_pick_flash"] = msg
                if source == "live_draft_room" and hasattr(st, "toast"):
                    st.toast(msg, icon="✅")
            elif result.get("error") == "shared_commit_failed":
                session["_draft_room_conflict_notice"] = msg
                if source == "live_draft_room":
                    st.error(msg)
            elif not result.get("ok"):
                session["_live_draft_pick_flash_error"] = msg
                if source == "live_draft_room":
                    st.error(msg)
            return True
        return False

    container.button(
        label,
        key=f"{btn_key}_disabled",
        disabled=True,
        use_container_width=True,
        type=button_type,
    )
    if show_disabled_reason:
        try:
            from draft_actions import resolve_player_draft_gate

            gate = resolve_player_draft_gate(session, name, source=source)
            msg = str(gate.get("disable_message") or gate_message or "").strip()
            if msg:
                container.caption(msg)
            else:
                diag = draft_button_diagnostics(session, name)
                code = str(diag.get("disable_reason") or "").strip()
                if code:
                    container.caption(f"Disabled: {code}")
                elif gate_message:
                    container.caption(draft_disabled_hint(gate_message))
        except ImportError:
            container.caption(draft_disabled_hint(gate_message))
    return False


def render_draft_sidebar_status(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Show round/pick/on-clock only after Start Draft (or for a completed live draft)."""
    from draft_actions import draft_status_summary, live_pick_clock_may_display, resolve_on_clock_team_label

    summary = draft_status_summary(session)
    if not live_pick_clock_may_display(session):
        return summary
    if summary.get("draft_complete"):
        st.sidebar.caption("Draft complete")
        return summary
    if summary.get("has_active_draft"):
        round_n = summary.get("round")
        pick_n = summary.get("pick")
        line_parts: list[str] = []
        if round_n is not None:
            line_parts.append(f"Round {round_n}")
        if pick_n is not None:
            line_parts.append(f"Pick {pick_n}")
        if line_parts:
            st.sidebar.markdown(f"**{' · '.join(line_parts)}**")
        on_clock = resolve_on_clock_team_label(session, summary=summary)
        if on_clock and on_clock != "—":
            st.sidebar.caption(f"On Clock: **{on_clock}**")
        if summary.get("live_draft_active"):
            render_draft_sidebar_timer(st, session, summary=summary)
    return summary


SIDEBAR_TIMER_REMAINING_KEY = "_live_draft_sidebar_timer_remaining"
SIDEBAR_TIMER_PAUSED_KEY = "_live_draft_sidebar_timer_paused"


def refresh_sidebar_timer_session(session: dict[str, Any], *, summary: dict[str, Any] | None = None) -> None:
    """Update timer values in session only — safe from fragment/callback contexts."""
    from draft_actions import draft_status_summary

    summary = summary or draft_status_summary(session)
    session.pop(SIDEBAR_TIMER_REMAINING_KEY, None)
    session.pop(SIDEBAR_TIMER_PAUSED_KEY, None)
    if not summary.get("live_draft_active"):
        return
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        remaining = summary.get("timer_seconds")
        if remaining is not None:
            session[SIDEBAR_TIMER_REMAINING_KEY] = int(remaining)
        return
    try:
        from live_draft_timer_logic import (
            ensure_live_draft_timer_for_pick,
            live_draft_seconds_remaining,
        )
        from live_draft_timer_ui import sync_live_draft_timer_state

        room = sync_live_draft_timer_state(session, room)
        session["live_draft_room"] = room
    except ImportError:
        pass
    status = str(room.get("status") or "")
    if status != "in_progress":
        paused_remaining = room.get("paused_remaining_seconds")
        if paused_remaining is not None:
            session[SIDEBAR_TIMER_PAUSED_KEY] = int(paused_remaining)
        return
    try:
        from live_draft_timer_logic import ensure_live_draft_timer_for_pick, live_draft_seconds_remaining

        ensure_live_draft_timer_for_pick(room)
        session[SIDEBAR_TIMER_REMAINING_KEY] = max(0, int(live_draft_seconds_remaining(room)))
    except ImportError:
        remaining = summary.get("timer_seconds")
        if remaining is not None:
            session[SIDEBAR_TIMER_REMAINING_KEY] = int(remaining)


def _render_sidebar_timer_caption(st: Any, session: dict[str, Any], *, summary: dict[str, Any] | None = None) -> None:
    """Render sidebar timer from session values — main script path only."""
    from draft_actions import draft_status_summary

    summary = summary or draft_status_summary(session)
    if not summary.get("live_draft_active"):
        return
    page = str(session.get("active_page") or session.get("active_page_name") or "").strip()
    if page == "Live Draft Room":
        _render_live_draft_room_sidebar_snapshot(st, session, summary=summary)
        return
    paused = session.get(SIDEBAR_TIMER_PAUSED_KEY)
    if paused is not None:
        st.sidebar.caption(f"Time Left: **{int(paused)}s** (paused)")
        return
    remaining = session.get(SIDEBAR_TIMER_REMAINING_KEY)
    if remaining is None:
        remaining = summary.get("timer_seconds")
    if remaining is not None:
        st.sidebar.caption(f"Time Left: **{int(remaining)}s**")
    room = session.get("live_draft_room")
    if isinstance(room, dict) and str(room.get("status") or "") == "in_progress":
        try:
            from live_draft_timer_logic import live_draft_timer_deadline
            from live_draft_timer_ui import _mount_js_countdown

            deadline = live_draft_timer_deadline(room)
            if deadline:
                pick_idx = int(room.get("current_pick_index") or 0)
                _mount_js_countdown(
                    st,
                    float(deadline),
                    pick_index=pick_idx,
                    element_id=f"sidebar-ld-timer-{pick_idx}",
                    height=0,
                )
        except Exception:
            pass


def _render_live_draft_room_sidebar_snapshot(
    st: Any,
    session: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
) -> None:
    """Live Draft Room sidebar mirrors the canonical snapshot — no fragment, no sync loop."""
    from draft_actions import draft_status_summary

    summary = summary or draft_status_summary(session)
    room = session.get("live_draft_room")
    remaining: int | None = None
    paused: int | None = None
    try:
        from live_draft_solo_timer import get_solo_display_snapshot, is_solo_live_draft

        if is_solo_live_draft(session, room if isinstance(room, dict) else None):
            snap = get_solo_display_snapshot(session, room if isinstance(room, dict) else None)
            status = str(snap.get("status") or "")
            if status == "paused":
                paused = int(snap.get("remaining_seconds") or 0)
            else:
                remaining = int(snap.get("remaining_seconds") or 0)
    except ImportError:
        pass
    if remaining is None and paused is None:
        try:
            from live_draft_canonical_snapshot import get_live_draft_paint_snapshot

            paint = get_live_draft_paint_snapshot(session)
            if paint.get("timer_remaining") is not None:
                remaining = int(paint.get("timer_remaining") or 0)
        except ImportError:
            pass
    if remaining is None and paused is None:
        remaining = summary.get("timer_seconds")
        if isinstance(room, dict) and str(room.get("status") or "") == "paused":
            try:
                paused = int(room.get("paused_remaining_seconds") or 0)
            except (TypeError, ValueError):
                paused = None
    try:
        from live_draft_cloud_diagnostics import render_surface_stamp

        render_surface_stamp(
            st,
            session,
            component="sidebar_timer",
            render_owner="snapshot_copy",
            room=room if isinstance(room, dict) else None,
        )
    except ImportError:
        pass
    if paused is not None:
        st.sidebar.caption(f"Time remaining: **{int(paused)}s** (paused)")
        return
    if remaining is not None:
        st.sidebar.caption(f"Time remaining: **{int(remaining)}s**")


def render_draft_sidebar_timer(
    st: Any,
    session: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
) -> None:
    """Live Draft countdown in sidebar — matches live draft room timer."""
    # Do not keep a Live Draft timer fragment alive on other application pages.
    try:
        from app_page_generation import fragment_allowed

        if not fragment_allowed(session, expected_page="Live Draft Room"):
            return
    except ImportError:
        page = str(session.get("active_page_name") or session.get("active_page") or "").strip()
        if page and page != "Live Draft Room":
            return
    from draft_actions import draft_status_summary

    summary = summary or draft_status_summary(session)
    if not summary.get("live_draft_active"):
        return
    refresh_sidebar_timer_session(session, summary=summary)
    _render_sidebar_timer_caption(st, session, summary=summary)

    page = str(session.get("active_page") or session.get("active_page_name") or "").strip()
    if page == "Live Draft Room":
        # Snapshot copy only — solo heartbeat owns the 1 Hz expire loop on the main page.
        return

    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return
    if session.get("_fp_sidebar_timer_skipped") or session.get("_live_draft_apptest_skip_sidebar_timer"):
        return

    @fragment(run_every=1)
    def _sidebar_timer_tick() -> None:
        try:
            from app_page_generation import fragment_allowed

            if not fragment_allowed(session, expected_page="Live Draft Room"):
                return
        except ImportError:
            pass
        refresh_sidebar_timer_session(session, summary=summary)

    _sidebar_timer_tick()


def _resolve_visible_draft_queue(
    session: dict[str, Any],
    *,
    qkey: str,
) -> tuple[list[str], str]:
    """Resolve the list the visible Draft Queue UI will paint.

    Prefers session widget key, then draft_state / page_filter / last-good snapshot.
    Returns (names, source_label).
    """
    def _norm(raw: Any) -> list[str]:
        if not isinstance(raw, (list, tuple)):
            return []
        return [str(x).strip() for x in raw if str(x).strip()]

    widget = _norm(session.get(qkey))
    ds = session.get("draft_state") if isinstance(session.get("draft_state"), dict) else {}
    canon = _norm(ds.get("queue"))

    # When local edits dirty the queue, trust the canonical mirrors even if empty
    # so intentional X removal cannot be undone by last-good / write-log fallbacks.
    dirty_local = False
    try:
        from draft_state import is_draft_locally_dirty

        dirty_local = bool(
            is_draft_locally_dirty(session)
            or session.get("_draft_queue_persist_dirty")
            or session.get("_draft_workflow_pending_sync")
        )
    except ImportError:
        dirty_local = bool(session.get("_draft_queue_persist_dirty"))

    if widget:
        session["_live_draft_queue_last_good"] = list(widget)
        return widget, qkey

    if dirty_local and isinstance(ds, dict) and "queue" in ds:
        if canon:
            return canon, "draft_state.queue"
        return [], "draft_state.queue_empty"

    if canon:
        return canon, "draft_state.queue"

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Draft Workflow")
        if isinstance(block, dict):
            pf_q = _norm(block.get(qkey) or (block.get("draft_state") or {}).get("queue"))
            if pf_q:
                return pf_q, "page_filter_state.Draft Workflow"

    if not dirty_local:
        last_good = _norm(session.get("_live_draft_queue_last_good"))
        if last_good:
            return last_good, "_live_draft_queue_last_good"

        # Survival write log: last non-empty new_session_queue.
        try:
            writes = list(session.get("_live_draft_queue_write_log") or [])
            for entry in reversed(writes):
                if not isinstance(entry, dict):
                    continue
                names = _norm(entry.get("new_session_queue"))
                if names:
                    return names, f"write_log:{entry.get('function')}"
        except Exception:
            pass
    return [], "empty"


def render_draft_queue_panel(
    st: Any,
    session: dict[str, Any],
    *,
    key_prefix: str = "queue",
    use_sidebar: bool = False,
    max_rows: int = 20,
    show_subheader: bool = True,
    compact: bool = False,
) -> bool:
    """
    Shared draft queue — reorder controls and draft buttons.

    Returns True when caller should st.rerun().
    """
    from draft_actions import _prune_drafted_from_queue, draft_action_context
    from draft_state import remove_player_from_user_draft_queue, reorder_user_draft_queue

    def _queue_remove_token(pool_row: Any, pname: str) -> str:
        pid = ""
        if isinstance(pool_row, dict):
            pid = str(pool_row.get("playerID") or "").strip()
        elif pool_row is not None and hasattr(pool_row, "get"):
            try:
                pid = str(pool_row.get("playerID") or "").strip()
            except Exception:
                pid = ""
        return pid or str(pname or "").strip()

    def _on_live_queue_remove(token: str) -> None:
        """Optimistic remove before the follow-up script paint."""
        remove_player_from_user_draft_queue(st.session_state, token)

    container = st.sidebar if use_sidebar else st
    try:
        from draft_state import DRAFT_QUEUE_KEY

        _qkey = DRAFT_QUEUE_KEY
    except ImportError:
        _qkey = "draft_queue"
    _is_live = str(key_prefix).startswith("live")
    raw_widget = [str(x).strip() for x in (session.get(_qkey) or []) if str(x).strip()]
    before_prune = list(raw_widget)
    if raw_widget:
        _prune_drafted_from_queue(session)
    widget_after_prune = [str(x).strip() for x in (session.get(_qkey) or []) if str(x).strip()]
    queue, queue_source = _resolve_visible_draft_queue(session, qkey=_qkey)
    # Hard filter: never paint drafted players (no "Already drafted by…" in queue).
    try:
        from shared_live_draft_snapshot import drafted_player_tokens

        drafted_tok = drafted_player_tokens(session)
        if drafted_tok and queue:
            filtered = [
                n
                for n in queue
                if str(n).strip() not in drafted_tok and str(n).strip().lower() not in drafted_tok
            ]
            if filtered != list(queue):
                try:
                    from draft_state import sync_draft_queue

                    sync_draft_queue(session, filtered, reason="queue_paint_drop_drafted")
                except ImportError:
                    session[_qkey] = list(filtered)
                queue = filtered
                queue_source = f"{queue_source}+drop_drafted"
    except ImportError:
        pass
    # If widget was empty but another source has names, repair session for this paint.
    if queue and not widget_after_prune:
        try:
            from draft_state import sync_draft_queue

            sync_draft_queue(session, queue, reason=f"paint_recover_from_{queue_source}")
            widget_after_prune = list(queue)
            session["_live_draft_queue_paint_repaired"] = {
                "from": queue_source,
                "names": list(queue)[:12],
            }
        except ImportError:
            session[_qkey] = list(queue)
            widget_after_prune = list(queue)
    rerun = False
    if _is_live:
        try:
            from live_draft_queue_fragment import record_queue_paint_diag

            record_queue_paint_diag(
                session,
                stage="inside_panel",
                queue=queue,
                extra={
                    "session_key": _qkey,
                    "queue_source": queue_source,
                    "raw_widget": list(raw_widget)[:12],
                    "before_prune_len": len(before_prune),
                    "before_prune": list(before_prune)[:12],
                    "widget_after_prune": list(widget_after_prune)[:12],
                    "pruned": before_prune != widget_after_prune,
                    "rendered_len": len(queue),
                    "id_session": id(session),
                },
            )
        except ImportError:
            pass

    _dev_queue_diag = False
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        _dev_queue_diag = bool(developer_mode_checkbox_enabled(st=st))
    except ImportError:
        _dev_queue_diag = bool(
            session.get("app_developer_mode") or session.get("_suite_developer_mode_user")
        )

    if show_subheader and not use_sidebar:
        container.subheader("Draft Queue")
        if session.pop("_live_draft_focus_queue", None):
            container.info("Draft Queue — reorder and draft from here while you’re on the clock.")
        if queue:
            session["_live_draft_queue_last_good"] = list(queue)
        # Paint / survival diagnostics — Developer Mode only (screenshot-clean otherwise).
        if _dev_queue_diag:
            try:
                from draft_state import _queue_scope_ids

                _qr, _qu = _queue_scope_ids(session)
            except Exception:
                _qr, _qu = ("", "")
            _rm = session.get("_draft_queue_last_remove") or {}
            container.markdown(
                f"**VISIBLE RENDER INPUT:** `{queue}`  \n"
                f"source=`{queue_source}` · widget=`{widget_after_prune}` · key=`{_qkey}`  \n"
                f"scope=`{_qr}|{_qu}` · epoch=`{session.get('_draft_queue_widget_epoch')}`  \n"
                f"last_remove=`{_rm}`"
            )
            if queue:
                _lines = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(queue[:max_rows]))
                container.markdown(f"**In queue ({len(queue)}):**\n\n{_lines}")
            else:
                container.markdown("**In queue (0):** empty")
            if _is_live:
                _canon = []
                _ds = session.get("draft_state")
                if isinstance(_ds, dict):
                    _canon = [str(x).strip() for x in (_ds.get("queue") or []) if str(x).strip()]
                container.caption(
                    f"Paint key=`{_qkey}` · panel={len(queue)} · "
                    f"before_prune={len(before_prune)} · canonical={len(_canon)} · "
                    f"source={queue_source}"
                    + (
                        f" · repaired={session.get('_live_draft_queue_paint_repaired')}"
                        if session.get("_live_draft_queue_paint_repaired")
                        else ""
                    )
                )
        if _is_live:
            try:
                from live_draft_queue_fragment import record_queue_paint_diag

                record_queue_paint_diag(
                    session,
                    stage="screen_list",
                    queue=queue,
                    extra={
                        "visible_markdown_names": list(queue)[:12],
                        "queue_source": queue_source,
                        "visible_render_input": list(queue)[:12],
                    },
                )
            except ImportError:
                pass

    if not queue:
        container.caption("Empty — add players with **⭐ Add to Queue** on recommendation cards.")
        return False

    # Red sliding queue (streamlit_sortables) — Live Draft + simulator.
    # Guards below reject wipe/stale/resurrect payloads; ✕ uses skip-once.
    _enable_drag = len(queue) >= 2
    if _enable_drag:
        try:
            from streamlit_sortables import sort_items

            try:
                from live_draft_ux import inject_draft_queue_sortable_styles

                container.markdown(
                    f"<style>{inject_draft_queue_sortable_styles()}</style>",
                    unsafe_allow_html=True,
                )
            except ImportError:
                pass
            container.caption("Drag the red cards to set queue priority (first = highest).")
            _sortable_in = list(queue)
            try:
                from draft_state import _queue_scope_ids

                _scope_room, _scope_user = _queue_scope_ids(session)
            except Exception:
                _scope_room, _scope_user = ("", "")
            _epoch = int(session.get("_draft_queue_widget_epoch") or 0)
            _q_rev = int(session.get("_draft_queue_revision") or 0)
            _sortable_key = (
                f"{key_prefix}_sortable_"
                f"{str(_scope_room or 'solo')[:24]}_"
                f"{str(_scope_user or 'user')[:24]}_"
                f"e{_epoch}_r{_q_rev}"
            )
            # After ✕ remove, skip sort_items once so stale component state cannot resurrect.
            if session.pop("_draft_queue_skip_sortable_once", None):
                sorted_queue = list(queue)
            else:
                sorted_queue = sort_items(list(queue), key=_sortable_key)
            # Ignore stale sortable returns that resurrect removed players.
            if list(sorted_queue) != list(queue):
                # Stale payload from an older queue revision must never win.
                _prev_rev = int(session.get("_draft_queue_sortable_seen_rev") or 0)
                if _q_rev and _prev_rev and _prev_rev < _q_rev and set(sorted_queue) - set(queue):
                    session["_live_draft_queue_sortable_stale_ignored"] = {
                        "sortable": list(sorted_queue)[:12],
                        "canonical": list(queue)[:12],
                        "key": _sortable_key,
                        "reason": "revision_guard",
                        "prev_rev": _prev_rev,
                        "queue_revision": _q_rev,
                    }
                    sorted_queue = list(queue)
                elif len(queue) >= 2 and not list(sorted_queue):
                    session["_live_draft_queue_sortable_wipe_blocked"] = True
                    try:
                        from live_draft_queue_fragment import record_queue_paint_diag

                        record_queue_paint_diag(
                            session,
                            stage="sortable_wipe_blocked",
                            queue=queue,
                            extra={"sortable_in": list(_sortable_in)[:12]},
                        )
                    except ImportError:
                        pass
                elif set(sorted_queue) - set(queue):
                    session["_live_draft_queue_sortable_stale_ignored"] = {
                        "sortable": list(sorted_queue)[:12],
                        "canonical": list(queue)[:12],
                        "key": _sortable_key,
                    }
                    sorted_queue = list(queue)
                elif set(queue) - set(sorted_queue):
                    # Sortable lagging behind canonical — keep canonical order.
                    session["_live_draft_queue_sortable_lag_ignored"] = True
                    sorted_queue = list(queue)
                else:
                    try:
                        from live_draft_ux_latency import ACTION_REORDER_QUEUE, note_ux_action

                        note_ux_action(
                            session,
                            ACTION_REORDER_QUEUE,
                            source="sortable",
                            detail="drag_reorder_queue",
                            st=st,
                        )
                    except ImportError:
                        pass
                    _changed_q, changed = reorder_user_draft_queue(
                        session,
                        list(sorted_queue),
                        reason="drag_reorder_queue",
                    )
                    if changed:
                        try:
                            from live_draft_queue_survival import note_queue_survival

                            note_queue_survival(
                                session,
                                "sortable_reorder",
                                detail=",".join(list(_changed_q)[:8]),
                            )
                        except ImportError:
                            pass
                        queue = list(_changed_q)
                        session["_draft_queue_revision"] = (
                            int(session.get("_draft_queue_revision") or 0) + 1
                        )
                        rerun = True
            session["_draft_queue_sortable_seen_rev"] = _q_rev
        except ImportError:
            if _enable_drag:
                container.caption("Drag reorder unavailable — install streamlit-sortables to reorder.")
    elif len(queue) >= 2:
        container.caption("Add another player to enable red drag reorder.")

    ctx = draft_action_context(session)
    if ctx.get("is_your_pick") and ctx.get("current_pick"):
        container.caption(f"Your pick · Pick {ctx['current_pick']}")
    elif ctx.get("on_clock_team"):
        pick_n = ctx.get("current_pick")
        clock = f"Pick {pick_n}: {ctx['on_clock_team']}" if pick_n else str(ctx["on_clock_team"])
        container.caption(f"On the clock — {clock}")

    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        paused = isinstance(room, dict) and room.get("status") == "paused"
    except ImportError:
        paused = False

    if not compact and not use_sidebar and not _is_live:
        header = container.columns([0.06, 0.34, 0.12, 0.16, 0.12, 0.20])
        header[0].caption("**Photo**")
        header[1].caption("**Player**")
        header[2].caption("**Pos**")
        header[3].caption("**Team**")
        header[4].caption("**Remove**")
        header[5].caption("**Draft**")

    try:
        from player_photos import get_player_photo_info, inject_player_photo_styles, render_queue_headshot_html

        inject_player_photo_styles(container)
        _queue_photos = True
    except ImportError:
        _queue_photos = False

    # Live Draft: force compact control rows so names cannot vanish into column layout.
    _use_compact_rows = bool(compact or use_sidebar or _is_live)

    for idx, pname in enumerate(queue[:max_rows]):
        meta = lookup_player_draft_meta(session, pname)
        pool_row = lookup_player_pool_row(session, pname)
        photo_info: dict[str, Any] = {}
        if _queue_photos:
            try:
                photo_info = get_player_photo_info(
                    row=pool_row,
                    full_name=pname,
                    use_api=False,
                )
            except Exception:
                photo_info = {}
        if _use_compact_rows:
            if _is_live:
                container.markdown(f"**{idx + 1}. {pname}**")
            c_name, c_rm, c_draft = container.columns([0.62, 0.18, 0.20])
            label = format_queue_player_label(pname, meta)
            metrics_line = format_queue_player_metrics_line(pool_row, session=session, room=room)
            if _queue_photos:
                headshot = render_queue_headshot_html(photo_info)
                short = label[:72] + ("…" if len(label) > 72 else "")
                metrics_html = (
                    f'<div style="font-size:0.76rem;color:#64748b;margin-top:2px;">{metrics_line}</div>'
                    if metrics_line
                    else ""
                )
                c_name.markdown(
                    f'<div class="bb-queue-row">{headshot}<span>{short}{metrics_html}</span></div>',
                    unsafe_allow_html=True,
                )
            else:
                extra = f"\n{metrics_line}" if metrics_line else ""
                c_name.caption(label[:72] + ("…" if len(label) > 72 else "") + extra)
            _rm_token = _queue_remove_token(pool_row, pname)
            if str(key_prefix).startswith("live"):
                c_rm.button(
                    "✕",
                    key=f"{key_prefix}_rm_{idx}",
                    help="Remove from queue",
                    on_click=_on_live_queue_remove,
                    args=(_rm_token,),
                )
            elif c_rm.button("✕", key=f"{key_prefix}_rm_{idx}", help="Remove from queue"):
                remove_player_from_user_draft_queue(session, _rm_token)
                queue = [x for x in queue if x != pname]
                rerun = True
            if render_draft_button(
                st,
                session,
                pname,
                source="queue" if not key_prefix.startswith("live") else "live_queue",
                key_suffix=f"{key_prefix}_{idx}",
                column=c_draft,
                show_disabled_reason=idx == 0,
                extra_disabled=paused,
                extra_disabled_reason="Draft is paused — resume to pick.",
            ):
                rerun = True
        else:
            cols = container.columns([0.06, 0.34, 0.12, 0.16, 0.12, 0.20])
            if _queue_photos:
                cols[0].markdown(render_queue_headshot_html(photo_info), unsafe_allow_html=True)
            else:
                cols[0].write(f"{idx + 1}")
            metrics_line = format_queue_player_metrics_line(pool_row, session=session, room=room)
            name_block = pname
            if metrics_line:
                name_block = f"{pname}\n{metrics_line}"
            cols[1].write(name_block)
            cols[2].write(meta["position"])
            cols[3].write(meta["team"][:18] + ("…" if len(meta["team"]) > 18 else ""))
            _rm_token = _queue_remove_token(pool_row, pname)
            if str(key_prefix).startswith("live"):
                cols[4].button(
                    "✕",
                    key=f"{key_prefix}_rm_{idx}",
                    help="Remove from queue",
                    on_click=_on_live_queue_remove,
                    args=(_rm_token,),
                )
            elif cols[4].button("✕", key=f"{key_prefix}_rm_{idx}", help="Remove from queue"):
                remove_player_from_user_draft_queue(session, _rm_token)
                queue = [x for x in queue if x != pname]
                rerun = True
            if render_draft_button(
                st,
                session,
                pname,
                source="live_queue" if key_prefix.startswith("live") else "queue",
                key_suffix=f"{key_prefix}_{idx}",
                column=cols[5],
                show_disabled_reason=idx == 0,
                extra_disabled=paused,
                extra_disabled_reason="Draft is paused — resume to pick.",
            ):
                if str(key_prefix).startswith("live"):
                    try:
                        from live_draft_ux_latency import ACTION_DRAFT_QUEUE, note_ux_action

                        note_ux_action(
                            session, ACTION_DRAFT_QUEUE, source="queue_draft", detail=pname, st=st
                        )
                    except ImportError:
                        pass
                rerun = True
    if len(queue) > max_rows:
        container.caption(f"+{len(queue) - max_rows} more in queue")
    if _is_live:
        try:
            from live_draft_queue_fragment import record_queue_paint_diag

            record_queue_paint_diag(
                session,
                stage="rows_rendered",
                queue=queue,
                extra={"rows_looped": min(len(queue), max_rows)},
            )
        except ImportError:
            pass
    return rerun


def render_live_draft_queue_panel(st: Any, session: dict[str, Any]) -> bool:
    """Queue table on Live Draft Room — uses shared queue panel."""
    return render_draft_queue_panel(
        st,
        session,
        key_prefix="live_queue",
        max_rows=20,
        show_subheader=True,
        compact=False,
    )


def render_active_draft_ownership_dev_panel(
    st: Any,
    session: dict[str, Any],
    *,
    player_name: str = "",
    developer_mode: bool = False,
) -> None:
    """Sidebar Dev Mode panel for active draft source and button gating."""
    if not developer_mode:
        return
    diag = draft_button_diagnostics(session, player_name)
    with st.sidebar.expander("Active draft ownership", expanded=True):
        for key, val in diag.items():
            if val is None or val == "":
                continue
            st.text(f"{key}: {val}")
        # Temporary isolation diagnostics: queue owner vs simulator leak.
        try:
            from draft_actions import draft_action_context
            from draft_room_context import resolve_shared_room_code
            from draft_room_participant_state import resolve_participant_id
            from live_draft_queue_survival import QUEUE_SCOPE_KEY
            from live_draft_state import LIVE_DRAFT_ROOM_KEY, analyze_live_draft_progress

            ctx = draft_action_context(session)
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            progress = analyze_live_draft_progress(room if isinstance(room, dict) else None)
            code = str(resolve_shared_room_code(session) or "").strip().upper()
            uid = resolve_participant_id(session)
            q = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]
            sim_table = session.get("draft_room_table")
            sim_picks = 0
            try:
                from draft_room_state import table_pick_count

                sim_picks = int(table_pick_count(sim_table))
            except Exception:
                sim_picks = 0
            rows = (
                ("active_draft_source", ctx.get("active_draft_source")),
                ("active_draft_id", (room or {}).get("draft_room_id") if isinstance(room, dict) else None),
                ("active_room_id", code or None),
                ("current_pick_index", progress.get("current_pick_index")),
                ("current_pick", progress.get("current_pick") or ctx.get("current_pick")),
                ("current_team", progress.get("on_clock_team") or ctx.get("on_clock_team")),
                ("queue_owner_user_id", uid or None),
                ("queue_storage_key", session.get(QUEUE_SCOPE_KEY) or (f"{code}|{uid}" if code else None)),
                ("queue_player_ids", ", ".join(q[:12]) if q else "[]"),
                ("simulator_draft_id", "draft_room_table" if sim_table is not None else None),
                ("simulator_pick_count", sim_picks),
            )
            st.caption("Scope isolation")
            for label, value in rows:
                st.text(f"{label}: {value if value is not None and value != '' else '—'}")
        except Exception:
            pass


_START_LIVE_DRAFT_TRACE_KEY = "_start_live_draft_trace"


def record_start_live_draft_diagnostics(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Merge Start Live Draft handler diagnostics for Dev Mode."""
    trace = dict(session.get(_START_LIVE_DRAFT_TRACE_KEY) or {})
    trace.update({k: v for k, v in fields.items() if v is not None})
    session[_START_LIVE_DRAFT_TRACE_KEY] = trace
    return trace


def mark_start_live_draft_clicked(session: dict[str, Any]) -> None:
    import time

    try:
        from live_draft_start_progress import begin_live_draft_start

        begin_live_draft_start(session, mode=str(session.get("_start_live_draft_mode") or "new"))
    except ImportError:
        pass
    record_start_live_draft_diagnostics(
        session,
        start_live_draft_clicked=True,
        start_live_draft_attempted=True,
        start_live_draft_error="",
        start_draft_clicked_ts=time.time(),
    )


_SIM_CONVERT_SETTING_KEYS = (
    ("sim_convert_live_draft_timer", "Timer per pick"),
    ("sim_convert_live_draft_proj_window", "Projection window"),
    ("sim_convert_live_draft_proj_style", "Rebalancing style"),
    ("sim_convert_live_draft_auto_rule", "Auto-pick rule"),
)


def assess_required_live_settings(session: dict[str, Any]) -> tuple[bool, list[str], str]:
    """Return (complete, missing_labels, disabled_reason) for simulator convert panel."""
    missing: list[str] = []
    for key, label in _SIM_CONVERT_SETTING_KEYS:
        val = session.get(key)
        if val is None or str(val).strip() == "":
            missing.append(label)
    if missing:
        return False, missing, f"Missing: {', '.join(missing)}"
    return True, [], ""


def copy_sim_convert_settings_to_live(session: dict[str, Any]) -> None:
    """Copy convert-panel widget values into canonical live_draft_* keys."""
    mapping = {
        "sim_convert_live_draft_timer": "live_draft_timer",
        "sim_convert_live_draft_proj_window": "live_draft_proj_window",
        "sim_convert_live_draft_proj_style": "live_draft_proj_style",
        "sim_convert_live_draft_auto_rule": "live_draft_auto_rule",
    }
    for src, dst in mapping.items():
        if src in session:
            session[dst] = session[src]


def sim_convert_canonical_defaults(session: dict[str, Any]) -> tuple[int, str]:
    """Projection window/style defaults for simulator-to-live convert from canonical draft settings."""
    from shared_draft_context import read_canonical_draft_settings

    canonical = read_canonical_draft_settings(session)
    lookback = int(canonical["lookback_window"])
    if lookback not in (3, 4, 5):
        lookback = max(3, min(5, lookback))
    style = str(canonical["projection_style"])
    return lookback, style


def seed_sim_convert_settings_from_canonical(session: dict[str, Any]) -> None:
    """Seed convert-panel projection widgets from draft_shared_settings when unset."""
    lookback, style = sim_convert_canonical_defaults(session)
    session.setdefault("sim_convert_live_draft_proj_window", lookback)
    session.setdefault("sim_convert_live_draft_proj_style", style)


def on_open_simulator_convert_panel() -> None:
    import streamlit as st

    record_start_live_draft_diagnostics(st.session_state, convert_simulator_clicked=True)
    seed_sim_convert_settings_from_canonical(st.session_state)
    st.session_state["_simulator_to_live_show_confirm"] = True


def on_cancel_simulator_convert_panel() -> None:
    import streamlit as st

    st.session_state.pop("_simulator_to_live_show_confirm", None)


def on_confirm_convert_simulator_to_live() -> None:
    import streamlit as st

    session = st.session_state
    complete, missing, reason = assess_required_live_settings(session)
    if not complete:
        record_start_live_draft_diagnostics(
            session,
            confirm_convert_clicked=False,
            required_live_settings_complete=False,
            confirm_button_disabled_reason=reason,
        )
        return
    copy_sim_convert_settings_to_live(session)
    mark_start_live_draft_clicked(session)
    record_start_live_draft_diagnostics(
        session,
        confirm_convert_clicked=True,
        required_live_settings_complete=True,
        confirm_button_disabled_reason="",
        start_live_draft_mode="simulator",
    )
    session["_start_live_draft_mode"] = "simulator"
    session["_start_live_draft_pending"] = True
    session.pop("_simulator_to_live_show_confirm", None)


def on_start_new_live_draft() -> None:
    import streamlit as st

    session = st.session_state
    _pending_armed = False
    _exit_reason = "callback_completed"
    _gate_error = ""

    def _raw(event: str, **extra: Any) -> None:
        try:
            from live_draft_queueui_instrumentation_build import emit_raw_canary

            emit_raw_canary(event, session=session, extra=extra or None)
        except ImportError:
            pass

    _raw("SOLO_QUEUEUI_RAW_CALLBACK_ENTER")
    try:
        try:
            from live_draft_start_stage1_observability import emit_start_callback_entered

            emit_start_callback_entered(session)
        except ImportError:
            pass
        try:
            from live_draft_start_stage1_observability import emit_start_handler_entered

            emit_start_handler_entered(session)
        except ImportError:
            pass
        _handler_ok = False
        _handler_exc = ""
        try:
            from live_draft_setup_persist import flush_live_draft_setup_persist

            flush_live_draft_setup_persist(st, session, reason="live_draft_start")
        except Exception:
            pass
        # Validate in the button callback so invalid setups always persist the exact
        # error beside Start Draft — even when a resumable-slot gate would otherwise
        # return early without arming ``_start_live_draft_pending``.
        try:
            from live_draft_start_setup import gate_start_new_live_draft_click

            gate = gate_start_new_live_draft_click(session)
            if gate.get("armed"):
                mark_start_live_draft_clicked(session)
                try:
                    from suite_auth import snapshot_auth_for_start_draft_rerun

                    snapshot_auth_for_start_draft_rerun(session)
                except ImportError:
                    pass
                _handler_ok = True
                _pending_armed = True
                _exit_reason = "gate_armed_pending"
            elif gate.get("replace_pending"):
                _exit_reason = "replace_confirmation_required"
                _gate_error = str(gate.get("error") or "")
            else:
                _exit_reason = "gate_not_armed"
                _gate_error = str(gate.get("error") or "gate_not_armed")
            try:
                from live_draft_start_stage1_observability import emit_start_handler_exited

                emit_start_handler_exited(
                    session,
                    success=_handler_ok and bool(gate.get("armed")),
                    exception="" if gate.get("armed") else str(gate.get("error") or "gate_not_armed"),
                    session_state_writes=["_start_live_draft_pending"] if gate.get("armed") else [],
                )
            except ImportError:
                pass
            _raw("SOLO_QUEUEUI_RAW_CALLBACK_EXIT", exit_reason=_exit_reason, pending_armed=_pending_armed)
            return
        except Exception:
            # Fall through to legacy arming only when the gate helper is unavailable.
            # Prefer fail-closed validation over silent start when possible.
            try:
                from live_draft_start_setup import (
                    LIVE_DRAFT_SETUP_ERROR,
                    fail_closed_setup_check,
                    store_setup_validation_error,
                )

                check = fail_closed_setup_check(session, solo_mode=True)
                if not check.get("ok"):
                    store_setup_validation_error(
                        session, str(check.get("error") or LIVE_DRAFT_SETUP_ERROR)
                    )
                    _exit_reason = "legacy_setup_validation_failed"
                    _gate_error = str(check.get("error") or LIVE_DRAFT_SETUP_ERROR)
                    _raw("SOLO_QUEUEUI_RAW_CALLBACK_EXIT", exit_reason=_exit_reason, pending_armed=False)
                    return
            except Exception:
                pass
        try:
            from live_draft_resumable_slot import warn_if_starting_replaces_resumable

            warn = warn_if_starting_replaces_resumable(session)
            if warn and not session.get("_live_draft_start_replace_resumable_ok"):
                session["_live_draft_start_replace_resumable_pending"] = True
                session["_live_draft_start_replace_resumable_message"] = warn.get("message")
                _exit_reason = "replace_resumable_confirmation"
                _raw("SOLO_QUEUEUI_RAW_CALLBACK_EXIT", exit_reason=_exit_reason, pending_armed=False)
                return
            session.pop("_live_draft_start_replace_resumable_ok", None)
            session.pop("_live_draft_start_replace_resumable_pending", None)
            session.pop("_live_draft_start_replace_resumable_message", None)
        except Exception:
            pass
        mark_start_live_draft_clicked(session)
        session["_start_live_draft_mode"] = "new"
        session["_start_live_draft_pending"] = True
        session.pop("_simulator_to_live_show_confirm", None)
        _handler_ok = True
        _pending_armed = True
        _exit_reason = "legacy_path_pending_armed"
        try:
            from live_draft_start_stage1_observability import emit_start_handler_exited

            emit_start_handler_exited(
                session,
                success=True,
                session_state_writes=["_start_live_draft_pending", "_start_live_draft_mode"],
            )
        except ImportError:
            pass
    finally:
        _raw(
            "SOLO_QUEUEUI_RAW_CALLBACK_EXIT",
            exit_reason=_exit_reason,
            pending_armed=_pending_armed,
            gate_error=str(_gate_error or "")[:200],
            finally_block=True,
        )
        try:
            from live_draft_start_stage1_observability import emit_start_callback_exited

            emit_start_callback_exited(
                session,
                pending_armed=_pending_armed,
                exit_reason=_exit_reason,
                gate_error=_gate_error,
            )
        except ImportError:
            pass


def on_prepare_shared_draft_room() -> None:
    """Pre-draft shared room create — must use on_click so pending runs before the handler."""
    import streamlit as st

    try:
        from live_draft_setup_persist import flush_live_draft_setup_persist

        flush_live_draft_setup_persist(st, st.session_state, reason="live_draft_start")
    except ImportError:
        pass
    try:
        from live_draft_setup_mode import SETUP_MODE_SHARED, request_live_draft_setup_mode

        # Create-shared callback can fire after the Draft Mode radio this run.
        request_live_draft_setup_mode(st.session_state, SETUP_MODE_SHARED, persist=True, st=st)
    except ImportError:
        pass
    try:
        from draft_room_create_verify import init_create_flow_diagnostics

        diag = init_create_flow_diagnostics(st.session_state, clicked=True)
        diag["create_button_callback_count"] = int(diag.get("create_button_callback_count") or 0) + 1
        st.session_state["_draft_room_create_diag"] = diag
    except ImportError:
        raw = dict(st.session_state.get("_draft_room_create_diag") or {})
        raw["create_button_clicked"] = True
        raw["create_button_callback_count"] = int(raw.get("create_button_callback_count") or 0) + 1
        st.session_state["_draft_room_create_diag"] = raw
    mark_start_live_draft_clicked(st.session_state)
    record_start_live_draft_diagnostics(
        st.session_state,
        start_live_draft_clicked=True,
        start_live_draft_mode="prepare_shared",
        room_create_attempted=True,
    )
    st.session_state["_start_live_draft_mode"] = "prepare_shared"
    st.session_state["_start_live_draft_pending"] = True
    st.session_state.pop("_simulator_to_live_show_confirm", None)


def on_join_shared_draft_from_setup(
    *,
    requested_code: str = "",
    requested_team: str = "",
    selectbox_return_value: str = "",
) -> None:
    """Pre-draft guest join — must use on_click so pending runs before the join handler."""
    import streamlit as st

    session = st.session_state
    code = str(
        requested_code
        or session.get("live_draft_join_code_input")
        or ""
    ).strip().upper()
    team = str(
        requested_team
        or selectbox_return_value
        or session.get("live_draft_join_team_pick")
        or ""
    ).strip()
    session["_join_shared_draft_from_setup"] = True
    session["_join_requested_code"] = code
    session["_join_requested_team"] = team
    session["_join_selectbox_return_value"] = str(selectbox_return_value or requested_team or "").strip()
    session["_join_session_team_widget_value"] = str(session.get("live_draft_join_team_pick") or "").strip()
    callback_count = int(session.get("_join_button_callback_count") or 0) + 1
    session["_join_button_callback_count"] = callback_count
    try:
        from draft_room_diagnostics import merge_join_flow_diagnostics

        merge_join_flow_diagnostics(
            session,
            join_button_callback_count=callback_count,
            join_attempted=True,
            join_code=code,
            requested_team=team,
            selectbox_return_value=str(selectbox_return_value or requested_team or "").strip(),
            session_team_widget_value=str(session.get("live_draft_join_team_pick") or "").strip(),
            captured_requested_team=team,
        )
    except ImportError:
        pass


_LIVE_DRAFT_UI_DIAG_KEY = "_live_draft_ui_diag"


def _player_id_from_available(available: Any, player_name: str) -> str:
    name = str(player_name or "").strip()
    if not name or available is None:
        return ""
    try:
        if hasattr(available, "columns"):
            id_col = "playerID" if "playerID" in available.columns else ""
            name_col = "fullName" if "fullName" in available.columns else ("Player" if "Player" in available.columns else "")
            if name_col:
                series = available[name_col].astype(str).str.strip()
                mask = series.eq(name)
                if id_col and mask.any():
                    return str(available.loc[mask, id_col].iloc[0])
    except Exception:
        return ""
    return ""


def _manual_draft_options_from_pool(available: Any) -> list[str]:
    """Sort pool rows for Manual Draft selectbox; tolerate compact/missing scoring columns."""
    if available is None or getattr(available, "empty", True):
        return []
    df = available.copy()
    name_col = "fullName" if "fullName" in df.columns else ("Player" if "Player" in df.columns else "")
    if not name_col:
        return []
    sort_cols = [c for c in ("Expected Fantasy Value", "Model Rank") if c in df.columns]
    if sort_cols:
        ascending = [False if c == "Expected Fantasy Value" else True for c in sort_cols]
        df = df.sort_values(sort_cols, ascending=ascending)
    return [str(x).strip() for x in df[name_col].dropna().astype(str).tolist() if str(x).strip()]


def _render_manual_draft_action_button(
    st: Any,
    *,
    should_render: bool,
    enabled: bool,
    disable_reason: str,
    key: str,
) -> None:
    """Always show a Draft Player control when the turn gate passes (acceptance)."""
    if not should_render:
        return
    if enabled:
        return
    st.button(
        "Draft Player",
        key=key,
        disabled=True,
        type="primary",
        help=str(disable_reason or "Cannot draft right now.")[:200],
    )


def render_live_manual_draft_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        try:
            from suite_workspace import developer_mode_checkbox_enabled

            developer_mode = developer_mode_checkbox_enabled(st=st)
        except ImportError:
            pass
    if not developer_mode:
        return
    raw = session.get(_LIVE_DRAFT_UI_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Manual draft diagnostics", expanded=developer_mode and not raw.get("draft_button_enabled")):
        rows = (
            ("render_path", raw.get("render_path")),
            ("pool_source", raw.get("pool_source")),
            ("available_player_count", raw.get("available_player_count")),
            ("filtered_player_count", raw.get("filtered_player_count")),
            ("candidate_count", raw.get("candidate_count")),
            ("selected_player", raw.get("selected_player")),
            ("selected_player_id", raw.get("selected_player_id")),
            ("visible_draft_candidate_name", raw.get("visible_draft_candidate_name")),
            ("visible_draft_candidate_id", raw.get("visible_draft_candidate_id")),
            ("draft_candidate_widget_key", raw.get("draft_candidate_widget_key")),
            ("draft_candidate_widget_value", raw.get("draft_candidate_widget_value")),
            ("draft_enabled", raw.get("draft_enabled")),
            ("is_my_turn", raw.get("is_my_turn")),
            ("is_your_pick", raw.get("is_your_pick")),
            ("draft_status", raw.get("draft_status")),
            ("on_clock_team", raw.get("on_clock_team")),
            ("your_team", raw.get("your_team")),
            ("assigned_team", raw.get("assigned_team")),
            ("participant_team", raw.get("participant_team")),
            ("current_pick", raw.get("current_pick")),
            ("current_pick_index", raw.get("current_pick_index")),
            ("total_picks", raw.get("total_picks")),
            ("multiplayer_mode", raw.get("multiplayer_mode")),
            ("draft_button_should_render", raw.get("draft_button_should_render")),
            ("draft_button_rendered", raw.get("draft_button_rendered")),
            ("draft_button_enabled", raw.get("draft_button_enabled")),
            ("draft_button_disable_reason", raw.get("draft_button_disable_reason") or raw.get("draft_action_disable_reason")),
            ("manual_draft_panel_skipped", raw.get("manual_draft_panel_skipped")),
        )
        for label, value in rows:
            st.text(f"{label}: {value if value is not None and value != '' else '—'}")


def record_live_draft_ui_diagnostics(
    session: dict[str, Any],
    updates: dict[str, Any] | None = None,
    /,
    **fields: Any,
) -> dict[str, Any]:
    """Merge manual-draft UI diagnostic fields into session (accepts dict and/or kwargs)."""
    merged: dict[str, Any] = {}
    if updates:
        merged.update(updates)
    merged.update(fields)
    diag = dict(session.get(_LIVE_DRAFT_UI_DIAG_KEY) or {})
    diag.update(merged)
    session[_LIVE_DRAFT_UI_DIAG_KEY] = diag
    return diag


def _live_draft_room_progress(room: dict[str, Any]) -> tuple[int, int, bool]:
    """Return (board_size, total_picks, draft_is_complete) from board length only."""
    board = len(room.get("draft_board") or [])
    try:
        from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks

        total = total_expected_picks(room)
        complete = bool(total > 0 and is_draft_truly_complete(room))
    except ImportError:
        total = len(room.get("pick_order") or [])
        complete = bool(total > 0 and board >= total)
    return board, total, complete


def render_live_manual_draft_panel(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    user_team: str = "",
    multiplayer: bool = False,
) -> bool:
    """
    Manual Draft selectbox + Draft Player button on Live Draft Room.

    Returns True when caller should rerun.
    """
    try:
        from live_draft_cloud_diagnostics import note_manual_panel_mount

        note_manual_panel_mount(session, source="render_live_manual_draft_panel")
    except ImportError:
        pass
    from draft_actions import draft_action_context, resolve_manual_draft_panel_gate

    ctx = draft_action_context(session)
    gate = resolve_manual_draft_panel_gate(session, ctx, multiplayer=multiplayer, room=room)
    manual_recovery = False
    try:
        from live_draft_safe_mode import is_safe_mode_active

        manual_recovery = bool((session.get("_live_draft_safe_mode_diag") or {}).get("manual_recovery_available"))
        if manual_recovery:
            try:
                from live_draft_safe_mode import total_expected_picks

                live = room if isinstance(room, dict) else session.get("live_draft_room")
                if isinstance(live, dict):
                    board = len(live.get("draft_board") or [])
                    total = total_expected_picks(live)
                    if board < total and gate.get("is_your_pick"):
                        gate = {**gate, "draft_button_should_render": True, "draft_enabled": True}
            except ImportError:
                if gate.get("is_your_pick"):
                    gate = {**gate, "draft_button_should_render": True, "draft_enabled": True}
    except ImportError:
        is_safe_mode_active = lambda _s: False  # noqa: E731
    render_path = "live_draft_room"
    should_render = bool(gate.get("draft_button_should_render"))
    turn_disable_reason = str(gate.get("draft_button_disable_reason") or "").strip()
    diag_base: dict[str, Any] = {
        "render_path": render_path,
        **gate,
        "draft_button_rendered": False,
        "draft_button_enabled": False,
        "player_action_panel_rendered": True,
        "manual_draft_panel_skipped": False,
        "selected_player": "",
        "draft_action_disable_reason": turn_disable_reason,
        "pool_source": "",
        "available_player_count": 0,
        "filtered_player_count": 0,
        "candidate_count": 0,
    }

    pool_load_error = ""
    available = None
    try:
        from live_draft_state import live_draft_get_available

        available = live_draft_get_available(room)
    except Exception as exc:
        pool_load_error = str(exc)
        available = None

    available_count = int(len(available)) if available is not None and hasattr(available, "__len__") else 0
    diag_base["available_player_count"] = available_count

    st.subheader("Manual Draft")

    try:
        from live_draft_safe_mode import draft_state_error_reason, is_safe_mode_active

        if is_safe_mode_active(session):
            err = draft_state_error_reason(session)
            if err:
                st.error(f"Draft state error — manual pick recovery enabled. {err}")
    except ImportError:
        pass

    def _finish(diag: dict[str, Any], *, show_disabled: bool = False) -> bool:
        record_live_draft_ui_diagnostics(session, diag)
        render_live_manual_draft_diagnostics(st, session)
        if show_disabled and should_render and not diag.get("draft_button_rendered"):
            _render_manual_draft_action_button(
                st,
                should_render=True,
                enabled=False,
                disable_reason=str(diag.get("draft_button_disable_reason") or diag.get("draft_action_disable_reason") or ""),
                key=f"live_draft_player_blocked_{diag.get('draft_action_disable_reason') or 'blocked'}",
            )
            record_live_draft_ui_diagnostics(session, draft_button_rendered=True)
        return False

    def _waiting_status_message() -> str:
        _, _, complete = _live_draft_room_progress(room)
        if complete:
            return "Draft is complete."
        if room.get("status") == "paused":
            return "Draft is paused — resume to pick."
        draft_status = str(gate.get("draft_status") or ctx.get("draft_status") or "").strip()
        board_size, total_picks, _ = _live_draft_room_progress(room)
        if draft_status == "not_started" or (draft_status == "" and board_size == 0 and total_picks > 0):
            return "Draft has not started yet."
        clock = str(gate.get("on_clock_team") or ctx.get("on_clock_team") or "").strip()
        if clock:
            return f"Waiting for **{clock}** to pick."
        return "Waiting for the next pick."

    if available is None:
        reason = f"live_draft_pool_unavailable:{pool_load_error or 'pool_load_failed'}"
        return _finish(
            {
                **diag_base,
                "filtered_player_count": 0,
                "candidate_count": 0,
                "draft_action_disable_reason": "pool_unavailable",
                "draft_button_disable_reason": reason,
                "pool_source": "unavailable",
            }
        )

    if available_count == 0:
        st.warning("No players left in the pool.")
        return _finish(
            {
                **diag_base,
                "filtered_player_count": 0,
                "candidate_count": 0,
                "draft_action_disable_reason": "empty_pool",
                "draft_button_disable_reason": "empty_pool",
                "pool_source": "empty",
            },
            show_disabled=True,
        )

    all_player_options = _manual_draft_options_from_pool(available)
    if not all_player_options:
        return _finish(
            {
                **diag_base,
                "filtered_player_count": 0,
                "candidate_count": 0,
                "draft_action_disable_reason": "pool_missing_name_column",
                "draft_button_disable_reason": "pool_missing_name_column",
                "pool_source": "invalid_pool_shape",
            }
        )

    pool_source = "free_pool"
    try:
        from draft_source_validation import allow_free_pool_drafting, allowed_draft_player_names

        if allow_free_pool_drafting(session, live_room=room):
            player_options = all_player_options
            pool_source = "free_pool"
        else:
            player_options = allowed_draft_player_names(
                session,
                live_room=room,
                available_names=all_player_options,
            )
            pool_source = "queue_watchlist_tracked"
            if not player_options and should_render:
                player_options = all_player_options
                pool_source = "full_pool_turn_fallback"
                st.caption(
                    "No players in your Queue, Watchlist, or Tracked list — showing full pool for this pick."
                )
    except ImportError:
        player_options = all_player_options
        pool_source = "free_pool"

    filtered_count = len(player_options)
    diag_base.update(
        {
            "filtered_player_count": filtered_count,
            "candidate_count": filtered_count,
            "pool_source": pool_source,
        }
    )

    # Position filter — narrow Manual Draft candidates by roster need.
    position_options = ["All", "C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "UTIL"]
    pos_filter = st.selectbox(
        "Position filter",
        position_options,
        key="live_draft_manual_position_filter",
        help="Filter the Manual Draft pool by position.",
    )
    if pos_filter and pos_filter != "All" and available is not None and hasattr(available, "columns"):
        pos_col = "Primary Position" if "Primary Position" in available.columns else (
            "Position" if "Position" in available.columns else ""
        )
        name_col = "fullName" if "fullName" in available.columns else (
            "Player" if "Player" in available.columns else ""
        )
        if pos_col and name_col:
            pos_series = available[pos_col].astype(str).str.upper()
            allowed_names = {
                str(n).strip()
                for n in available.loc[
                    pos_series.str.contains(str(pos_filter).upper(), na=False)
                    | ((pos_filter == "UTIL") & pos_series.isin(["UTIL", "DH", "PH"])),
                    name_col,
                ].tolist()
                if str(n).strip()
            }
            if pos_filter == "OF":
                allowed_names |= {
                    str(n).strip()
                    for n in available.loc[
                        pos_series.isin(["OF", "LF", "CF", "RF", "OF/DH"]),
                        name_col,
                    ].tolist()
                    if str(n).strip()
                }
            player_options = [n for n in player_options if n in allowed_names]
            filtered_count = len(player_options)
            diag_base["filtered_player_count"] = filtered_count
            diag_base["candidate_count"] = filtered_count
            diag_base["position_filter"] = pos_filter
            if not player_options:
                st.caption(f"No available players at **{pos_filter}** — try All or another position.")

    paused = room.get("status") == "paused"
    board_size, total_picks, draft_is_complete = _live_draft_room_progress(room)
    draft_in_progress = bool(total_picks > 0 and board_size < total_picks and not draft_is_complete)
    if manual_recovery and not draft_in_progress:
        try:
            from live_draft_safe_mode import total_expected_picks

            total = total_expected_picks(room)
            draft_in_progress = bool(total > 0 and board_size < total)
        except ImportError:
            pass

    if draft_is_complete:
        return _finish(
            {
                **diag_base,
                "draft_action_disable_reason": "draft_complete",
                "draft_button_disable_reason": "draft_complete",
                "manual_draft_panel_skipped": True,
            }
        )

    if not player_options:
        return _finish(
            {
                **diag_base,
                "draft_action_disable_reason": "no_allowed_players",
                "draft_button_disable_reason": "no_allowed_players",
            }
        )

    if not should_render or paused or not draft_in_progress:
        wait_msg = _waiting_status_message()
        st.info(wait_msg)
        st.selectbox(
            "Available players",
            player_options,
            key="live_draft_player_view_only",
            disabled=True,
        )
        disable_reason = turn_disable_reason or (
            "Draft is paused" if paused else "Not your turn"
        )
        if "Waiting for" in wait_msg:
            disable_reason = wait_msg.replace("**", "")
        diag_base.update(
            {
                "draft_button_rendered": True,
                "draft_button_enabled": False,
                "manual_draft_panel_skipped": not should_render,
                "draft_action_disable_reason": disable_reason,
                "draft_button_disable_reason": disable_reason,
            }
        )
        with st.container(border=True):
            st.button(
                "Draft Player",
                key=f"{MANUAL_DRAFT_BUTTON_KEY}_waiting",
                type="primary",
                disabled=True,
                use_container_width=True,
                help=str(disable_reason)[:200],
            )
            st.caption(disable_reason)
        return _finish(diag_base)

    widget_key = manual_draft_candidate_widget_key(room)

    def _on_candidate_change() -> None:
        _record_visible_draft_candidate(session, available, widget_key, source="on_change")

    selected_player = st.selectbox(
        "Draft candidate",
        player_options,
        key=widget_key,
        help="Pick a player from the pool (or your queue/watchlist when commissioner mode is off).",
        on_change=_on_candidate_change,
    )
    visible_name = str(selected_player or session.get(widget_key) or "").strip()
    if visible_name and visible_name not in player_options:
        visible_name = str(session.get(widget_key) or "").strip()
    visible_snap = _record_visible_draft_candidate(
        session,
        available,
        widget_key,
        fallback_name=visible_name,
        source="render",
    )
    visible_id = visible_snap.get("id") or _player_id_from_available(available, visible_name)
    diag_base["selected_player"] = visible_name
    diag_base["selected_player_id"] = visible_id
    diag_base["visible_draft_candidate_name"] = visible_name
    diag_base["visible_draft_candidate_id"] = visible_id
    diag_base["draft_candidate_widget_key"] = widget_key
    diag_base["draft_candidate_widget_value"] = visible_name

    allowed, disable_reason = can_draft_player(session, visible_name)
    button_enabled = bool(allowed and not paused)
    if not allowed:
        diag_base["draft_action_disable_reason"] = disable_reason

    diag_base["draft_button_enabled"] = button_enabled
    diag_base["draft_button_disable_reason"] = "" if button_enabled else (disable_reason or "cannot_draft")

    with st.container(border=True):
        diag_base["candidate_source"] = pool_source

        def _on_manual_draft_click() -> None:
            snap = session.get(MANUAL_CANDIDATE_SNAPSHOT_KEY)
            snap = snap if isinstance(snap, dict) else {}
            queue_manual_draft_pick(
                session,
                player_name=str(snap.get("name") or session.get(widget_key) or visible_name or "").strip(),
                player_id=str(snap.get("id") or visible_id or "").strip() or None,
                pool_source=str(pool_source or ""),
                candidate_source="manual_panel_selectbox_on_click",
                widget_key=widget_key,
            )

        # Always paint Draft Player — never hide it when unavailable.
        if button_enabled:
            st.button(
                "Draft Player",
                key=MANUAL_DRAFT_BUTTON_KEY,
                type="primary",
                use_container_width=True,
                on_click=_on_manual_draft_click,
            )
        else:
            reason_txt = disable_reason or "Cannot draft this player right now."
            st.button(
                "Draft Player",
                key=f"{MANUAL_DRAFT_BUTTON_KEY}_disabled",
                type="primary",
                disabled=True,
                use_container_width=True,
                help=str(reason_txt)[:200],
            )
            st.caption(reason_txt)

        pending = session.get(PENDING_MANUAL_PICK_KEY)
        if isinstance(pending, dict) and pending.get("player_name"):
            st.caption("Processing manual pick…")
    record_live_draft_ui_diagnostics(
        session,
        {
            **diag_base,
            "draft_button_rendered": True,
        },
    )
    render_live_manual_draft_diagnostics(st, session)
    return False


def render_start_live_draft_dev_panel(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        return
    trace = dict(session.get(_START_LIVE_DRAFT_TRACE_KEY) or {})
    keys = (
        "convert_simulator_clicked",
        "convert_confirmation_rendered",
        "confirm_button_rendered",
        "required_live_settings_complete",
        "confirm_button_disabled_reason",
        "confirm_convert_clicked",
        "start_live_draft_clicked",
        "start_live_draft_attempted",
        "start_live_draft_error",
        "simulator_board_pick_count_before_start",
        "simulator_board_source",
        "live_room_created",
        "replayed_pick_count",
        "promote_skipped_count",
        "live_draft_status_after_start",
        "live_user_team_after_start",
        "active_draft_source_after_start",
        "current_pick_after_start",
        "promote_error",
        "pool_live_count",
        "start_live_draft_mode",
        "current_start_step",
        "step_elapsed_sec",
        "start_draft_clicked_ts",
        "room_created_ts",
        "shared_write_ok",
        "shared_write_error",
        "timer_deadline_set",
    )
    with st.expander("Start Live Draft trace (Dev Mode)", expanded=True):
        for key in keys:
            val = trace.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
        if trace.get("start_live_draft_clicked") and not trace.get("live_room_created"):
            st.warning("Start Live Draft was clicked but no live room was created — see start_live_draft_error / promote_error.")
