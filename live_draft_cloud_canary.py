"""Administrator-only minimal Solo Live Draft canary for Streamlit Cloud."""

from __future__ import annotations

import time
from typing import Any

CANARY_TEAMS = ("Team A", "Team B")
CANARY_PICKS_PER_TEAM = 2


def _admin_ok(st: Any, session: dict[str, Any]) -> bool:
    try:
        from live_draft_cloud_diagnostics import bootstrap_cloud_accept_mode

        bootstrap_cloud_accept_mode(st, session)
        from live_draft_cloud_diagnostics import _admin_ok as diag_admin_ok

        return bool(diag_admin_ok(st, session))
    except ImportError:
        return False


def ensure_canary_room(session: dict[str, Any]) -> dict[str, Any]:
    room = session.get("live_draft_room")
    if isinstance(room, dict) and str(room.get("_cloud_canary") or "") == "1":
        return room
    try:
        from live_draft_timer_logic import ensure_full_pick_order, live_draft_reset_timer
    except ImportError:
        ensure_full_pick_order = None  # type: ignore[assignment]
        live_draft_reset_timer = None  # type: ignore[assignment]

    cfg = {
        "league_name": "Cloud Canary",
        "num_teams": len(CANARY_TEAMS),
        "picks_per_team": CANARY_PICKS_PER_TEAM,
        "timer_seconds": 23,
        "draft_setup_mode": "solo",
    }
    pick_order: list[dict[str, Any]] = []
    n = len(CANARY_TEAMS) * CANARY_PICKS_PER_TEAM
    for i in range(n):
        team = CANARY_TEAMS[i % len(CANARY_TEAMS)]
        rnd = (i // len(CANARY_TEAMS)) + 1
        pick_order.append({"Team": team, "Round": rnd, "Pick": i + 1})
    room = {
        "status": "in_progress",
        "teams": list(CANARY_TEAMS),
        "config": cfg,
        "pick_order": pick_order,
        "draft_board": [],
        "current_pick_index": 0,
        "draft_room_id": "LD-CANARY",
        "_cloud_canary": "1",
    }
    if ensure_full_pick_order is not None:
        ensure_full_pick_order(room)
    if live_draft_reset_timer is not None:
        live_draft_reset_timer(room)
    try:
        import pandas as pd

        room["pool"] = pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "Player One", "Primary Position": "1B", "Expected Fantasy Value": 90, "Model Rank": 1, "Market Rank": 1, "Fantasy Edge": 0},
                {"playerID": "p2", "fullName": "Player Two", "Primary Position": "C", "Expected Fantasy Value": 85, "Model Rank": 2, "Market Rank": 2, "Fantasy Edge": 0},
                {"playerID": "p3", "fullName": "Player Three", "Primary Position": "OF", "Expected Fantasy Value": 80, "Model Rank": 3, "Market Rank": 3, "Fantasy Edge": 0},
                {"playerID": "p4", "fullName": "Player Four", "Primary Position": "P", "Expected Fantasy Value": 75, "Model Rank": 4, "Market Rank": 4, "Fantasy Edge": 0},
            ]
        )
    except Exception:
        pass
    session["live_draft_room"] = room
    session.pop("active_shared_draft_room_code", None)
    session["live_draft_setup_mode"] = "solo"
    try:
        from live_draft_canonical_snapshot import begin_live_draft_paint

        begin_live_draft_paint(session, room, state_source="cloud_canary")
    except ImportError:
        pass
    try:
        from live_draft_solo_timer import install_solo_display_snapshot

        install_solo_display_snapshot(session, room)
    except ImportError:
        pass
    return room


def render_live_draft_cloud_canary(st: Any, session: dict[str, Any]) -> bool:
    """Render minimal canary page. Returns True when canary handled the page."""
    try:
        from live_draft_cloud_diagnostics import CANARY_MODE_KEY, cloud_canary_requested

        if not cloud_canary_requested(st, session):
            return False
    except ImportError:
        return False
    if not _admin_ok(st, session):
        st.warning("Cloud canary requires Developer Mode or ?ld_accept=1 (admin).")
        return True

    session[CANARY_MODE_KEY] = True
    try:
        from live_draft_cloud_diagnostics import enable_solo_no_fragment_mode

        enable_solo_no_fragment_mode(session, enabled=False)
    except ImportError:
        pass

    room = ensure_canary_room(session)
    try:
        from live_draft_solo_heartbeat import render_solo_live_draft_heartbeat

        render_solo_live_draft_heartbeat(st, session, room)
    except ImportError:
        pass

    try:
        from live_draft_timer_logic import live_draft_current_slot, live_draft_seconds_remaining
        from live_draft_on_clock_ui import render_live_on_clock_banner
        from live_draft_solo_timer import get_solo_display_snapshot

        slot = live_draft_current_slot(room) or {"Team": "—", "Round": 1, "Pick": 1}
        render_live_on_clock_banner(st, session, room, slot, next_pick=None)
        snap = get_solo_display_snapshot(session, room)
        rem = int(snap.get("remaining_seconds") or live_draft_seconds_remaining(room))
        st.sidebar.caption(f"Canary sidebar · Time remaining: **{rem}s**")
    except ImportError:
        st.error("Canary modules unavailable.")
        return True

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Pause", key="canary_pause"):
            try:
                from live_draft_timer_logic import live_draft_pause_timer

                live_draft_pause_timer(room)
                session["live_draft_room"] = room
            except ImportError:
                pass
            st.rerun()
    with c2:
        if st.button("Resume", key="canary_resume"):
            try:
                from live_draft_timer_logic import live_draft_resume_timer

                pause_left = int(room.get("paused_remaining_seconds") or 23)
                live_draft_resume_timer(room, pause_left)
                session["live_draft_room"] = room
            except ImportError:
                pass
            st.rerun()
    with c3:
        if st.button("Auto Pick", key="canary_auto_pick"):
            try:
                from live_draft_solo_timer import expire_current_pick_and_advance

                expire_current_pick_and_advance(room, session=session, request_full_rerun=False)
            except ImportError:
                pass
            st.rerun()

    if st.button("Reset Timer", key="canary_reset_timer"):
        try:
            from live_draft_timer_logic import live_draft_reset_timer

            live_draft_reset_timer(room)
            session["live_draft_room"] = room
        except ImportError:
            pass
        st.rerun()

    try:
        from live_draft_cloud_diagnostics import render_admin_diag_panel

        render_admin_diag_panel(st, session)
    except ImportError:
        pass

    board = room.get("draft_board") or []
    st.markdown("**Draft Board**")
    if not board:
        st.caption("No picks yet.")
    else:
        for row in board:
            if isinstance(row, dict):
                st.write(f"Pick {row.get('Pick')}: {row.get('fullName') or row.get('Player') or '—'}")

    players = ["Player One", "Player Two", "Player Three", "Player Four"]
    st.markdown("**Manual pick**")
    pick_name = st.selectbox("Player", players, key="canary_player_pick")
    if st.button("Draft Player", key="canary_manual_draft"):
        t0 = time.perf_counter()
        try:
            from draft_actions import draft_player

            result = draft_player(session, pick_name, source="cloud_canary", st_obj=st)
            if not result.get("ok"):
                st.error(str(result.get("error") or result.get("message") or "Manual pick failed."))
        except ImportError:
            st.error("Manual pick unavailable.")
        else:
            try:
                from live_draft_cloud_diagnostics import log_action_callback

                log_action_callback(session, "canary_manual_draft", received_at=t0, painted_at=time.perf_counter())
            except ImportError:
                pass
        st.rerun()

    return True