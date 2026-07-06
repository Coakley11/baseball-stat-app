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


def format_queue_player_metrics_line(pool_row: Any) -> str:
    """Proj: line plus Decision Score / Roster Fit for queue rows."""
    if pool_row is None:
        return ""
    try:
        from player_photos import compact_fantasy_stat_line, decision_score_display, roster_fit_display

        bits: list[str] = []
        stat_line = compact_fantasy_stat_line(pool_row)
        if stat_line:
            bits.append(stat_line)
        ds = decision_score_display(pool_row)
        rf = roster_fit_display(pool_row)
        score_bits: list[str] = []
        if ds and ds != "Not available":
            score_bits.append(f"Decision Score {ds}")
        if rf and rf != "Not available":
            score_bits.append(f"Roster Fit {rf}")
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

    session.pop("_live_draft_manual_pick_in_flight", None)
    try:
        from live_draft_ui_cache import invalidate_draft_assistant_scoring_cache, invalidate_live_draft_ui_caches

        invalidate_live_draft_ui_caches(session)
        invalidate_draft_assistant_scoring_cache(session)
    except ImportError:
        session.pop("_live_draft_rec_cache", None)
    session.pop("_rec_card_commit_in_flight", None)
    try:
        from live_draft_pick_timer import clear_pick_submit_state

        if ok:
            clear_pick_submit_state(session)
        else:
            clear_pick_submit_state(session)
    except ImportError:
        pass

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
    """Always show round, pick, and on-clock team in the workflow sidebar."""
    from draft_actions import draft_status_summary, resolve_on_clock_team_label

    summary = draft_status_summary(session)
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
        st.sidebar.caption(f"On Clock: **{on_clock or '—'}**")
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


def render_draft_sidebar_timer(
    st: Any,
    session: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
) -> None:
    """Live Draft countdown in sidebar — matches live draft room timer."""
    from draft_actions import draft_status_summary

    summary = summary or draft_status_summary(session)
    if not summary.get("live_draft_active"):
        return
    refresh_sidebar_timer_session(session, summary=summary)
    _render_sidebar_timer_caption(st, session, summary=summary)

    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return

    @fragment(run_every=1)
    def _sidebar_timer_tick() -> None:
        refresh_sidebar_timer_session(session, summary=summary)

    _sidebar_timer_tick()


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
    from draft_state import (
        move_queue_item_down,
        move_queue_item_to_top,
        move_queue_item_up,
        remove_player_from_draft_queue,
    )

    container = st.sidebar if use_sidebar else st
    _prune_drafted_from_queue(session)
    queue = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]

    if show_subheader and not use_sidebar:
        container.subheader("Draft Queue")
        container.markdown('<div class="live-draft-queue-panel">', unsafe_allow_html=True)

    if not queue:
        container.caption("Empty — add players with **Queue player** in Player Actions.")
        if show_subheader and not use_sidebar:
            container.markdown("</div>", unsafe_allow_html=True)
        return False

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

    if not compact and not use_sidebar:
        header = container.columns([0.06, 0.30, 0.10, 0.14, 0.22, 0.18])
        header[0].caption("**Photo**")
        header[1].caption("**Player**")
        header[2].caption("**Pos**")
        header[3].caption("**Team**")
        header[4].caption("**Reorder**")
        header[5].caption("**Draft**")

    try:
        from player_photos import get_player_photo_info, inject_player_photo_styles, render_queue_headshot_html

        inject_player_photo_styles(container)
        _queue_photos = True
    except ImportError:
        _queue_photos = False

    rerun = False
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
        if compact or use_sidebar:
            c_ctrl, c_name, c_draft = container.columns([0.38, 0.42, 0.20])
            u, d, t, r = c_ctrl.columns(4)
            if u.button("↑", key=f"{key_prefix}_up_{idx}", disabled=idx == 0):
                move_queue_item_up(session, idx)
                rerun = True
            if d.button("↓", key=f"{key_prefix}_dn_{idx}", disabled=idx >= len(queue) - 1):
                move_queue_item_down(session, idx)
                rerun = True
            if t.button("⤒", key=f"{key_prefix}_top_{idx}", disabled=idx == 0):
                move_queue_item_to_top(session, idx)
                rerun = True
            if r.button("✕", key=f"{key_prefix}_rm_{idx}"):
                remove_player_from_draft_queue(session, pname)
                rerun = True
            label = format_queue_player_label(pname, meta)
            metrics_line = format_queue_player_metrics_line(pool_row)
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
            cols = container.columns([0.06, 0.30, 0.10, 0.14, 0.22, 0.18])
            if _queue_photos:
                cols[0].markdown(render_queue_headshot_html(photo_info), unsafe_allow_html=True)
            else:
                cols[0].write(f"{idx + 1}")
            metrics_line = format_queue_player_metrics_line(pool_row)
            name_block = pname
            if metrics_line:
                name_block = f"{pname}\n{metrics_line}"
            cols[1].write(name_block)
            cols[2].write(meta["position"])
            cols[3].write(meta["team"][:18] + ("…" if len(meta["team"]) > 18 else ""))
            ctrl = container.columns([0.5, 0.5])
            with ctrl[0]:
                b1, b2, b3, b4 = st.columns(4)
                if b1.button("Up", key=f"{key_prefix}_up_{idx}", disabled=idx == 0):
                    move_queue_item_up(session, idx)
                    rerun = True
                if b2.button("Down", key=f"{key_prefix}_dn_{idx}", disabled=idx >= len(queue) - 1):
                    move_queue_item_down(session, idx)
                    rerun = True
                if b3.button("Top", key=f"{key_prefix}_top_{idx}", disabled=idx == 0):
                    move_queue_item_to_top(session, idx)
                    rerun = True
                if b4.button("Remove", key=f"{key_prefix}_rm_{idx}"):
                    remove_player_from_draft_queue(session, pname)
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
                rerun = True

    if len(queue) > max_rows:
        container.caption(f"+{len(queue) - max_rows} more in queue")
    if show_subheader and not use_sidebar:
        container.markdown("</div>", unsafe_allow_html=True)
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

    try:
        from live_draft_setup_persist import flush_live_draft_setup_persist

        flush_live_draft_setup_persist(st, st.session_state, reason="live_draft_start")
    except ImportError:
        pass
    mark_start_live_draft_clicked(st.session_state)
    st.session_state["_start_live_draft_mode"] = "new"
    st.session_state["_start_live_draft_pending"] = True
    st.session_state.pop("_simulator_to_live_show_confirm", None)


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
        st.info(_waiting_status_message())
        st.selectbox(
            "Available players",
            player_options,
            key="live_draft_player_view_only",
            disabled=True,
        )
        diag_base.update(
            {
                "draft_button_rendered": False,
                "draft_button_enabled": False,
                "manual_draft_panel_skipped": not should_render,
                "draft_action_disable_reason": turn_disable_reason or "not_your_turn",
            }
        )
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

    if not button_enabled:
        st.caption(disable_reason or "Cannot draft this player right now.")
        diag_base["draft_button_rendered"] = False
        return _finish(diag_base)

    st.markdown('<div class="live-draft-manual-panel">', unsafe_allow_html=True)
    diag_base["candidate_source"] = pool_source

    def _on_manual_draft_click() -> None:
        queue_manual_draft_pick(
            session,
            pool_source=str(pool_source or ""),
            candidate_source="manual_panel_selectbox_on_click",
            widget_key=widget_key,
        )

    st.button(
        "Draft Player",
        key=MANUAL_DRAFT_BUTTON_KEY,
        type="primary",
        use_container_width=True,
        on_click=_on_manual_draft_click,
    )

    pending = session.get(PENDING_MANUAL_PICK_KEY)
    if isinstance(pending, dict) and pending.get("player_name"):
        st.caption("Processing manual pick…")

    st.markdown("</div>", unsafe_allow_html=True)
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
