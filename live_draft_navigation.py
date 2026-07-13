"""Leave / return draft navigation for Live Draft Room and Draft Simulator."""

from __future__ import annotations

from typing import Any

BROWSING_AWAY_KEY = "_live_draft_browsing_away"
FORCE_SYNC_ON_RETURN_KEY = "_live_draft_force_sync_on_return"
MAIN_SIDEBAR_PAGE_KEY = "main_sidebar_page"
DEFAULT_BROWSE_PAGE = "Fantasy Trends"

LIVE_DRAFT_QUICK_NAV_PAGES: tuple[tuple[str, str, str, str], ...] = (
    ("Draft Assistant Simulator", "Draft Assistant", "Next-pick ranks", "assistant"),
    ("Fantasy Sleepers & Busts", "Sleepers", "Market edge", "sleepers"),
    ("Trend Value", "Trends", "Breakouts", "trends"),
    ("Valuation", "Valuation", "Perf + trend", "valuation"),
    ("ML Predictions", "ML Projections", "Model view", "ml"),
    ("Comparison Tool", "Comparison", "Side-by-side", "comparison"),
)


def _page_label(page_key: str, page_label_fn=None) -> str:
    if callable(page_label_fn):
        return str(page_label_fn(page_key))
    return page_key


def _page_icon(page_key: str, page_label_fn=None) -> str:
    label = _page_label(page_key, page_label_fn)
    first = label.split(" ", 1)[0].strip()
    return first if first and first != page_key else ""


def _with_page_icon(page_key: str, text: str, page_label_fn=None) -> str:
    icon = _page_icon(page_key, page_label_fn)
    return f"{icon} {text}".strip()


def inject_live_draft_quick_nav_styles(st: Any) -> None:
    st.markdown(
        """
        <style>
        .ld-quick-nav-wrap { margin: 0 0 10px 0; }
        .ld-quick-nav-title {
            font-size: 13px; font-weight: 800; color: #334155;
            letter-spacing: 0.04em; margin-bottom: 10px;
        }
        .ld-quick-nav-row { margin-bottom: 6px; }
        .ld-quick-tile {
            border-radius: 12px; padding: 10px 12px 8px 12px;
            min-height: 56px; border: 1px solid transparent;
            margin-bottom: 4px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        .ld-quick-tile-assistant { background: linear-gradient(135deg,#eff6ff,#dbeafe); border-color:#93c5fd; }
        .ld-quick-tile-sleepers { background: linear-gradient(135deg,#fff7ed,#ffedd5); border-color:#fdba74; }
        .ld-quick-tile-trends { background: linear-gradient(135deg,#ecfdf5,#d1fae5); border-color:#6ee7b7; }
        .ld-quick-tile-valuation { background: linear-gradient(135deg,#f5f3ff,#ede9fe); border-color:#c4b5fd; }
        .ld-quick-tile-ml { background: linear-gradient(135deg,#fdf2f8,#fce7f3); border-color:#f9a8d4; }
        .ld-quick-tile-comparison { background: linear-gradient(135deg,#f8fafc,#e2e8f0); border-color:#cbd5e1; }
        .ld-quick-tile-label { font-size: 13px; font-weight: 800; color: #0f172a; line-height: 1.25; }
        .ld-quick-tile-sub { font-size: 10px; color: #64748b; margin-top: 3px; line-height: 1.25; }
        div[data-testid="column"] .ld-quick-tile + div[data-testid="stButton"] button {
            min-height: 30px; padding: 4px 10px; font-size: 11px; font-weight: 700;
            border-radius: 8px; margin-top: 2px;
        }
        @media (max-width: 768px) {
            .ld-quick-nav-wrap { margin-bottom: 8px; }
            .ld-quick-tile { min-height: 48px; padding: 8px 10px 6px 10px; }
            .ld-quick-tile-label { font-size: 12px; }
            .ld-quick-tile-sub { display: none; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _go_body(session: dict[str, Any], target_page: str, prepare_canonical_scoring_context) -> None:
    if prepare_canonical_scoring_context is not None:
        try:
            prepare_canonical_scoring_context(session, active_page=target_page)
        except Exception:
            pass
    session[BROWSING_AWAY_KEY] = True
    _apply_scheduled_page(session, target_page)


def render_live_draft_quick_nav(st: Any, session: dict[str, Any], *, page_label_fn=None) -> None:
    """Color-coded navigation tiles to related fantasy pages."""
    try:
        from shared_draft_context import prepare_canonical_scoring_context
    except ImportError:
        prepare_canonical_scoring_context = None  # type: ignore[misc,assignment]

    def _go(target_page: str) -> None:
        try:
            from live_draft_perf import PHASE_SECTION_NAV, live_draft_perf_action

            with live_draft_perf_action(session, f"nav:{target_page}", phase=PHASE_SECTION_NAV):
                _go_body(session, target_page, prepare_canonical_scoring_context)
        except ImportError:
            _go_body(session, target_page, prepare_canonical_scoring_context)

    inject_live_draft_quick_nav_styles(st)
    st.markdown('<div class="ld-quick-nav-wrap"><div class="ld-quick-nav-title">Quick navigation</div></div>', unsafe_allow_html=True)
    row_size = 3
    for row_start in range(0, len(LIVE_DRAFT_QUICK_NAV_PAGES), row_size):
        row_pages = LIVE_DRAFT_QUICK_NAV_PAGES[row_start : row_start + row_size]
        cols = st.columns(len(row_pages))
        for col, (page, label, subtitle, theme) in zip(cols, row_pages):
            with col:
                col.markdown(
                    f'<div class="ld-quick-tile ld-quick-tile-{theme}">'
                    f'<div class="ld-quick-tile-label">{_with_page_icon(page, label, page_label_fn)}</div>'
                    f'<div class="ld-quick-tile-sub">{subtitle}</div></div>',
                    unsafe_allow_html=True,
                )
                col.button(
                    "Open →",
                    key=f"live_draft_quick_nav_{page.replace(' ', '_')}",
                    use_container_width=True,
                    on_click=_go,
                    args=(page,),
                )


def _apply_scheduled_page(session: dict[str, Any], target_page: str) -> None:
    """Navigate immediately — sidebar radio reads these keys on the same rerun."""
    page = str(target_page or "").strip()
    if not page:
        return
    session["_navigate_to_page"] = page
    session[MAIN_SIDEBAR_PAGE_KEY] = page
    session["active_page"] = page
    session["_suite_page_user_nav"] = True
    session.pop("_suite_cloud_target_page", None)


def on_browse_other_pages(session: dict[str, Any], *, target_page: str | None = None) -> None:
    """Leave Live Draft Room without ending or pausing the draft."""
    page = str(target_page or session.get("_live_draft_browse_return_page") or DEFAULT_BROWSE_PAGE).strip()
    session[BROWSING_AWAY_KEY] = True
    _apply_scheduled_page(session, page)


def on_return_to_live_draft(session: dict[str, Any]) -> None:
    session.pop(BROWSING_AWAY_KEY, None)
    session[FORCE_SYNC_ON_RETURN_KEY] = True
    _apply_scheduled_page(session, "Live Draft Room")


def on_return_to_draft_simulator(session: dict[str, Any]) -> None:
    session.pop(BROWSING_AWAY_KEY, None)
    _apply_scheduled_page(session, "Draft Room Simulator")


def _seconds_remaining(room: dict[str, Any]) -> int | None:
    try:
        from live_draft_timer_logic import live_draft_seconds_remaining

        if str(room.get("status") or "") == "in_progress":
            return int(live_draft_seconds_remaining(room))
        paused = room.get("paused_remaining_seconds")
        if paused is not None:
            return int(paused)
    except ImportError:
        pass
    return None


def _is_live_draft_room(room: Any) -> bool:
    return isinstance(room, dict) and bool(room.get("draft_room_id") or room.get("pick_order"))


def _live_draft_room_for_return(session: dict[str, Any]) -> dict[str, Any] | None:
    """Hydrate a return-card room without running the full Live Draft page pipeline."""
    room = session.get("live_draft_room")
    if _is_live_draft_room(room):
        return room
    try:
        from live_draft_state import canonical_live_draft, room_from_persist_dict

        blob = canonical_live_draft(session)
        if isinstance(blob, dict) and (blob.get("draft_room_id") or blob.get("pick_order")):
            restored = room_from_persist_dict(blob)
            if restored:
                session["live_draft_room"] = restored
                return restored
    except ImportError:
        pass
    return None


def get_draft_return_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Sidebar card context for active live draft, lobby, completed draft, or simulator."""
    room = _live_draft_room_for_return(session)

    if isinstance(room, dict):
        try:
            from live_draft_state import analyze_live_draft_progress, has_active_live_draft
            from live_draft_setup_mode import is_shared_multiplayer_intent, shared_room_code

            progress = analyze_live_draft_progress(room)
            cfg = dict(room.get("config") or {})
            teams = [str(t) for t in (room.get("teams") or []) if str(t).strip()]
            team_label = " vs ".join(teams[:4]) if teams else str(cfg.get("league_name") or "Draft")
            mode_label = "Shared Multiplayer" if is_shared_multiplayer_intent(session, room=room) else "Solo Draft"
            code = shared_room_code(session) or ""
            user_team = str(session.get("draft_room_participant_team") or cfg.get("your_team") or cfg.get("user_team") or "")
            try:
                from fantasy_workspace_team_identity import resolve_current_account_team_for_live_draft_and_league

                resolved = resolve_current_account_team_for_live_draft_and_league(session, room=room)
                if resolved:
                    user_team = resolved
            except ImportError:
                pass
            slot = progress.get("slot") or {}
            round_no = slot.get("Round") if isinstance(slot, dict) else None
            pick_no = progress.get("current_pick")
            on_clock = progress.get("on_clock_team") or "—"
            done = int(progress.get("draft_board_count") or 0)
            total = int(progress.get("total_picks") or 0)
            status = str(room.get("status") or "").strip()

            if progress.get("draft_complete") or status == "complete":
                return {
                    "kind": "live_complete",
                    "title": "Draft Completed",
                    "team_label": team_label,
                    "picks_label": f"{done} of {total} picks completed" if total else f"{done} picks",
                    "room_code": code,
                    "mode_label": mode_label,
                    "user_team": user_team,
                }

            if has_active_live_draft(session) or status in ("not_started", "in_progress", "paused"):
                return {
                    "kind": "live_active" if status in ("in_progress", "paused") else "live_lobby",
                    "title": "Return to Live Draft",
                    "team_label": team_label,
                    "room_code": code,
                    "mode_label": mode_label,
                    "user_team": user_team,
                    "round_no": round_no,
                    "pick_no": pick_no,
                    "on_clock": on_clock,
                    "picks_label": f"{done} / {total} picks made" if total else f"{done} picks",
                    "seconds_remaining": _seconds_remaining(room),
                }
        except Exception:
            status = str(room.get("status") or "").strip()
            if status == "complete":
                return {
                    "kind": "live_complete",
                    "title": "Draft Completed",
                    "team_label": str((room.get("config") or {}).get("league_name") or "Live Draft"),
                    "user_team": str(session.get("draft_room_participant_team") or ""),
                }
            return {
                "kind": "live_active" if status in ("in_progress", "paused") else "live_lobby",
                "title": "Return to Live Draft",
                "team_label": str((room.get("config") or {}).get("league_name") or "Live Draft"),
                "user_team": str(session.get("draft_room_participant_team") or ""),
            }

    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE, get_active_draft_status

        status = get_active_draft_status(session)
        if status.get("active"):
            mode = status.get("mode")
            if mode == ACTIVE_DRAFT_MODE_LIVE:
                return None
            return {
                "kind": "simulator",
                "title": "Return to Draft Simulator",
                "picks_label": f"{status.get('pick_count', 0)} pick(s) logged",
                "round_no": status.get("current_round"),
                "pick_no": status.get("current_pick"),
                "on_clock": str(status.get("on_clock_team") or "").strip(),
                "user_team": status.get("your_team") or "",
            }
    except ImportError:
        pass
    return None


def apply_force_sync_on_return(session: dict[str, Any]) -> bool:
    """Fetch latest shared draft state when user returns to Live Draft Room."""
    if not session.pop(FORCE_SYNC_ON_RETURN_KEY, None):
        return False
    synced = False
    try:
        from draft_room_context import is_multiplayer_draft_active, poll_shared_draft_room, sync_shared_draft_room

        if is_multiplayer_draft_active(session):
            sync_shared_draft_room(session, force=True)
            poll_shared_draft_room(session)
            synced = True
    except ImportError:
        pass
    try:
        from draft_room_state import ensure_live_draft_synced_to_canonical_board

        ensure_live_draft_synced_to_canonical_board(session, reason="force_sync_on_return")
        synced = True
    except ImportError:
        pass
    return synced


def render_return_to_draft_sidebar(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str = "",
    page_label_fn=None,
) -> None:
    """Prominent sidebar card to return to active live draft, completed draft, or simulator."""
    ctx = get_draft_return_context(session)
    if not ctx:
        return

    kind = str(ctx.get("kind") or "")
    if active_page == "Live Draft Room" and kind == "live_complete":
        return
    with st.sidebar.container(border=True):
        st.markdown(f"**{ctx.get('title')}**")
        if ctx.get("team_label"):
            st.caption(str(ctx["team_label"]))
        if ctx.get("room_code"):
            st.caption(f"Room **{ctx['room_code']}** · {ctx.get('mode_label', '')}")
        if ctx.get("user_team"):
            st.caption(f"Your team: **{ctx['user_team']}**")
        if ctx.get("round_no") and ctx.get("pick_no"):
            st.caption(f"Round **{ctx['round_no']}** · Pick **{ctx['pick_no']}**")
        on_clock = str(ctx.get("on_clock") or "").strip()
        if on_clock and on_clock != "—":
            st.caption(f"On clock: **{on_clock}**")
        if ctx.get("picks_label"):
            st.caption(str(ctx["picks_label"]))
        sec = ctx.get("seconds_remaining")
        if sec is not None and kind == "live_active":
            st.caption(f"Time remaining: **{sec}s**")

        if kind in ("live_active", "live_lobby"):
            st.button(
                _with_page_icon("Live Draft Room", "Return to Live Draft", page_label_fn),
                type="primary",
                key="sidebar_return_live_draft_btn",
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "live_complete":
            st.button(
                _with_page_icon("Live Draft Room", "Open Live Draft Room", page_label_fn),
                key="sidebar_open_completed_draft_btn",
                use_container_width=True,
                on_click=on_return_to_live_draft,
                args=(session,),
            )
        elif kind == "simulator":
            st.button(
                _with_page_icon("Draft Room Simulator", "Return to Draft Simulator", page_label_fn),
                type="primary",
                key="sidebar_return_simulator_btn",
                use_container_width=True,
                on_click=on_return_to_draft_simulator,
                args=(session,),
            )


def render_leave_draft_button(st: Any, session: dict[str, Any]) -> None:
    """In-room control to browse other pages without ending the draft."""
    st.button(
        "Leave Draft / Browse Other Pages",
        key="live_draft_browse_other_btn",
        help="Draft continues running. Use the sidebar Return to Draft button to come back.",
        on_click=on_browse_other_pages,
        args=(session,),
    )
