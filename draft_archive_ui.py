"""Saved Draft Library UI — browse, manage, and activate saved draft teams."""

from __future__ import annotations

from typing import Any

from draft_archive_state import (
    activate_draft_archive,
    clear_active_draft_archive,
    delete_draft_archive,
    draft_type_display,
    duplicate_draft_archive,
    format_archive_modified,
    get_active_draft_archive,
    list_draft_archives,
    rename_draft_archive,
    save_live_draft_team_archive,
    save_simulator_team_archive,
    set_active_draft_archive,
)

SAVED_DRAFT_LIBRARY_PAGE = "Saved Draft Library"
_DELETE_CONFIRM_PREFIX = "_draft_archive_delete_confirm_"


def schedule_saved_draft_library_navigation(session: dict[str, Any]) -> None:
    session["_navigate_to_page"] = SAVED_DRAFT_LIBRARY_PAGE


def _persist_archive(session: dict[str, Any], st: Any, *, reason: str) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason=reason)
    except Exception:
        pass


def _clear_fantasy_caches_on_archive_change(session: dict[str, Any]) -> None:
    try:
        from fantasy_perf_cache import LINEUP_SCORES_CACHE_KEY, STANDINGS_ROSTER_CACHE_KEY

        session.pop(STANDINGS_ROSTER_CACHE_KEY, None)
        session.pop(LINEUP_SCORES_CACHE_KEY, None)
    except ImportError:
        pass


def _badge_html(entry: dict[str, Any]) -> str:
    label = draft_type_display(entry)
    css = "ld-archive-badge-live" if label == "Live Draft" else "ld-archive-badge-sim"
    return f'<span class="ld-archive-badge {css}">{label}</span>'


def render_active_saved_draft_chip(st: Any, session: dict[str, Any], *, key_prefix: str = "active_draft") -> None:
    """Compact active-draft indicator with link to the library."""
    active = get_active_draft_archive(session)
    chip_left, chip_right = st.columns([4, 1])
    with chip_left:
        if active:
            st.markdown(
                f"**Active Saved Draft:** {active.get('draft_name', 'Saved Draft')} · "
                f"**{draft_type_display(active)}** · {active.get('team_name', '')} · "
                f"{len(active.get('players') or [])} players · "
                f"Updated {format_archive_modified(active)}",
                unsafe_allow_html=False,
            )
        else:
            st.caption(
                "No active saved draft selected. Standings and Lineup use the **Draft Room** board "
                "unless you set one active in the library."
            )
    with chip_right:
        if st.button("Manage saved drafts", key=f"{key_prefix}_manage_btn", use_container_width=True):
            schedule_saved_draft_library_navigation(session)
            st.rerun()


def _render_post_save_actions(st: Any, session: dict[str, Any], entry: dict[str, Any]) -> None:
    st.success(
        f"Saved **{entry.get('draft_name')}** ({len(entry.get('players') or [])} players). "
        "Set active for Standings and Lineup analysis."
    )
    view_col, standings_col = st.columns(2)
    with view_col:
        if st.button("View in Saved Draft Library", key=f"view_library_{entry.get('draft_id')}", type="primary"):
            schedule_saved_draft_library_navigation(session)
            st.rerun()
    with standings_col:
        if st.button("Go to Standings Tracker", key=f"view_standings_{entry.get('draft_id')}"):
            session["_navigate_to_page"] = "Fantasy Standings Tracker"
            st.rerun()


def render_save_live_draft_team(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str = "live_draft_archive",
) -> None:
    cfg = dict(room.get("config") or {})
    if not team_name or team_name == "—":
        return
    with st.expander("Save completed draft team", expanded=False):
        draft_name = st.text_input(
            "Draft name",
            value=f"{cfg.get('league_name', 'Live Draft')} — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        if st.button("Save Draft Team", key=f"{key_prefix}_save_btn", type="secondary"):
            try:
                entry = save_live_draft_team_archive(
                    session,
                    room,
                    team_name=team_name,
                    draft_name=draft_name,
                )
                set_active_draft_archive(session, str(entry.get("draft_id") or ""))
                _clear_fantasy_caches_on_archive_change(session)
                _persist_archive(session, st, reason="live_draft_archive_saved")
                try:
                    from baseball_archive_activity import log_saved_draft_archived

                    log_saved_draft_archived(entry, session=session)
                except ImportError:
                    pass
                _render_post_save_actions(st, session, entry)
            except Exception as exc:
                st.error(f"Could not save draft team: {exc}")


def render_save_simulator_draft_team(
    st: Any,
    session: dict[str, Any],
    board_df: Any,
    *,
    team_name: str,
    key_prefix: str = "sim_draft_archive",
) -> None:
    if not team_name or team_name == "—":
        return
    with st.expander("Save draft team for Standings / Lineup", expanded=False):
        st.caption("Save your team's roster from this mock draft without replacing the live board.")
        draft_name = st.text_input(
            "Draft name",
            value=f"Simulator — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        if st.button("Save Draft Team", key=f"{key_prefix}_save_btn", type="secondary"):
            try:
                entry = save_simulator_team_archive(
                    session,
                    board_df,
                    team_name=team_name,
                    draft_name=draft_name,
                    config=dict(session.get("draft_shared_settings") or {}),
                )
                set_active_draft_archive(session, str(entry.get("draft_id") or ""))
                _clear_fantasy_caches_on_archive_change(session)
                _persist_archive(session, st, reason="simulator_draft_archive_saved")
                try:
                    from baseball_archive_activity import log_saved_draft_archived

                    log_saved_draft_archived(entry, session=session)
                except ImportError:
                    pass
                _render_post_save_actions(st, session, entry)
            except Exception as exc:
                st.error(f"Could not save draft team: {exc}")


def _render_archive_actions(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    active_id: str,
) -> None:
    draft_id = str(entry.get("draft_id") or "")
    if not draft_id:
        return
    is_active = draft_id == active_id
    rename_val = st.text_input(
        "Rename",
        value=str(entry.get("draft_name") or ""),
        key=f"archive_rename_{draft_id}",
        label_visibility="collapsed",
        placeholder="Draft name",
    )
    btn1, btn2, btn3, btn4 = st.columns(4)
    with btn1:
        if st.button(
            "Active" if is_active else "Set Active",
            key=f"archive_active_{draft_id}",
            type="primary" if is_active else "secondary",
            disabled=is_active,
            use_container_width=True,
        ):
            loaded = activate_draft_archive(session, draft_id)
            if loaded:
                _clear_fantasy_caches_on_archive_change(session)
                _persist_archive(session, st, reason="draft_archive_activated")
                try:
                    from baseball_archive_activity import log_saved_draft_activated

                    log_saved_draft_activated(entry, session=session, target_page="Saved Draft Library")
                except ImportError:
                    pass
                st.rerun()
    with btn2:
        if st.button("Rename", key=f"archive_rename_btn_{draft_id}", use_container_width=True):
            renamed = rename_draft_archive(session, draft_id, rename_val)
            if renamed:
                _persist_archive(session, st, reason="draft_archive_renamed")
                st.rerun()
            else:
                st.warning("Enter a valid name.")
    with btn3:
        if st.button("Duplicate", key=f"archive_dup_{draft_id}", use_container_width=True):
            dup = duplicate_draft_archive(session, draft_id)
            if dup:
                _persist_archive(session, st, reason="draft_archive_duplicated")
                st.rerun()
    with btn4:
        if st.button("Delete", key=f"archive_del_{draft_id}", use_container_width=True):
            session[_DELETE_CONFIRM_PREFIX + draft_id] = True
            st.rerun()

    if session.get(_DELETE_CONFIRM_PREFIX + draft_id):
        st.warning(f"Delete **{entry.get('draft_name')}**? Other saved drafts will be kept.")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Confirm delete", key=f"archive_del_confirm_{draft_id}", type="primary"):
                if delete_draft_archive(session, draft_id):
                    session.pop(_DELETE_CONFIRM_PREFIX + draft_id, None)
                    _clear_fantasy_caches_on_archive_change(session)
                    _persist_archive(session, st, reason="draft_archive_deleted")
                    st.rerun()
        with cancel_col:
            if st.button("Cancel", key=f"archive_del_cancel_{draft_id}"):
                session.pop(_DELETE_CONFIRM_PREFIX + draft_id, None)
                st.rerun()


def render_saved_draft_library_page(st: Any, session: dict[str, Any]) -> None:
    """Dedicated management page for all saved draft teams."""
    st.markdown(
        """
        <style>
        .ld-archive-badge {
            display: inline-block;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            margin-right: 0.35rem;
        }
        .ld-archive-badge-live { background: #1f4e79; color: #fff; }
        .ld-archive-badge-sim { background: #3d5a3d; color: #fff; }
        .ld-archive-card {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 0.65rem;
            padding: 0.85rem 1rem;
            margin-bottom: 0.75rem;
        }
        .ld-archive-active {
            border-color: #2ecc71;
            box-shadow: 0 0 0 1px rgba(46,204,113,0.35);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    archives = list_draft_archives(session)
    active = get_active_draft_archive(session)
    active_id = str((active or {}).get("draft_id") or "")

    st.caption(
        "Keep multiple saved teams — current season roster, mock drafts, live draft results, and practice drafts. "
        "Setting one **Active** tells **Standings Tracker** and **Lineup Assistant** which roster to analyze."
    )

    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.metric("Saved drafts", len(archives))
    with top_right:
        if active and st.button("Clear active draft", key="library_clear_active", use_container_width=True):
            clear_active_draft_archive(session)
            _clear_fantasy_caches_on_archive_change(session)
            _persist_archive(session, st, reason="draft_archive_cleared")
            st.rerun()

    if not archives:
        st.info(
            "No saved drafts yet. Finish a **Live Draft Room** or **Draft Room Simulator** draft, "
            "then use **Save Draft Team**."
        )
        nav1, nav2 = st.columns(2)
        with nav1:
            if st.button("Open Live Draft Room", key="library_go_live", use_container_width=True):
                session["_navigate_to_page"] = "Live Draft Room"
                st.rerun()
        with nav2:
            if st.button("Open Draft Room Simulator", key="library_go_sim", use_container_width=True):
                session["_navigate_to_page"] = "Draft Room Simulator"
                st.rerun()
        return

    for entry in archives:
        draft_id = str(entry.get("draft_id") or "")
        is_active = draft_id == active_id
        card_class = "ld-archive-card ld-archive-active" if is_active else "ld-archive-card"
        player_n = len(entry.get("players") or [])
        title = str(entry.get("draft_name") or "Saved Draft")
        team = str(entry.get("team_name") or "—")
        modified = format_archive_modified(entry)
        active_tag = " · **ACTIVE**" if is_active else ""
        st.markdown(
            f'<div class="{card_class}">{_badge_html(entry)}'
            f"<strong>{title}</strong>{active_tag}<br>"
            f"<span style='opacity:0.85'>{team} · {player_n} players · Updated {modified}</span></div>",
            unsafe_allow_html=True,
        )
        _render_archive_actions(st, session, entry, active_id=active_id)

    st.divider()
    st.markdown("##### Analyze an active saved draft")
    go1, go2 = st.columns(2)
    with go1:
        if st.button("Open Standings Tracker", key="library_open_standings", use_container_width=True):
            active = get_active_draft_archive(session)
            if active:
                try:
                    from baseball_archive_activity import log_saved_draft_activated

                    log_saved_draft_activated(
                        active,
                        session=session,
                        target_page="Fantasy Standings Tracker",
                    )
                except ImportError:
                    pass
            session["_navigate_to_page"] = "Fantasy Standings Tracker"
            st.rerun()
    with go2:
        if st.button("Open Lineup Assistant", key="library_open_lineup", use_container_width=True):
            session["_navigate_to_page"] = "Fantasy Lineup Assistant"
            st.rerun()
