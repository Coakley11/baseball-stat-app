"""Saved Draft Library UI — browse, manage, and activate saved draft teams."""

from __future__ import annotations

from typing import Any

from draft_archive_state import (
    clear_active_draft_archive,
    delete_draft_archive,
    draft_type_display,
    duplicate_draft_archive,
    format_archive_modified,
    get_active_draft_archive,
    get_draft_archive,
    list_draft_archives,
    rename_draft_archive,
)
from fantasy_league_context import (
    activate_archive_league_context,
    clear_active_league_context,
    get_active_league_context,
    get_league_context_for_archive,
    league_context_coverage_badge,
    league_context_type_badge,
    league_team_count,
    list_league_contexts,
    pop_league_context_save_flash,
    save_live_draft_league_context,
    save_simulator_league_context,
    schedule_active_context_resync,
    stash_league_context_save_flash,
)

SAVED_DRAFT_LIBRARY_PAGE = "Saved Draft Library"
FANTASY_STANDINGS_PAGE = "Fantasy Standings Tracker"
FANTASY_LINEUP_PAGE = "Fantasy Lineup Assistant"
LIVE_DRAFT_PAGE = "Live Draft Room"
DRAFT_LAB_PAGE = "Draft Lab / Simulation"
DRAFT_SIMULATOR_PAGE = "Draft Room Simulator"
SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY = "_saved_draft_library_return_page"
_DELETE_CONFIRM_PREFIX = "_draft_archive_delete_confirm_"


def _render_persistence_diagnostics(st: Any, session: dict[str, Any]) -> None:
    try:
        from workflow_persist_guard import build_saved_draft_library_diagnostics, probe_cloud_workflow_for_workspace
    except ImportError:
        return

    diag = build_saved_draft_library_diagnostics(session)
    with st.expander("Persistence diagnostics", expanded=False):
        account_bits = []
        if diag.get("authenticated"):
            if diag.get("account_email"):
                account_bits.append(str(diag["account_email"]))
            elif diag.get("account_external_id"):
                account_bits.append(str(diag["account_external_id"]))
            if diag.get("account_user_id"):
                account_bits.append(f"id `{diag['account_user_id']}`")
        else:
            account_bits.append("Not signed in (local/demo mode)")
        st.markdown(f"**Account:** {' · '.join(account_bits)}")
        ws_label = str(diag.get("workspace_label") or diag.get("workspace_id") or "—")
        ws_id = str(diag.get("workspace_id") or "—")
        st.markdown(f"**Workspace:** {ws_label} (`{ws_id}`)")
        st.markdown(
            f"**Counts (session):** {int(diag.get('draft_archive_count') or 0)} saved drafts · "
            f"{int(diag.get('league_context_count') or 0)} league contexts"
        )
        st.markdown(f"**Restore source:** {diag.get('restore_source_label') or '—'}")
        if diag.get("restore_at"):
            st.caption(f"Last restore: {diag['restore_at']}")
        if diag.get("cloud_app_key"):
            st.caption(f"Cloud app key: `{diag['cloud_app_key']}`")
        if diag.get("local_state_path"):
            st.caption(f"Disk path: `{diag['local_state_path']}`")
        merged = diag.get("workflow_merge_keys") or []
        if merged:
            sources = diag.get("workflow_merge_sources") or {}
            bits = [f"{k} ({sources.get(k, '?')})" for k in merged]
            st.caption(f"Partial-save protection restored: {', '.join(bits)}")
        restore_merged = diag.get("workflow_restore_merged_keys") or []
        if restore_merged:
            rsources = diag.get("workflow_restore_merge_sources") or {}
            rb = [f"{k} ({rsources.get(k, '?')})" for k in restore_merged]
            st.caption(f"Restore merge recovered: {', '.join(rb)}")
        nav_diag = session.get("_draft_library_nav_diag")
        save_diag = session.get("_draft_library_save_diag")
        if isinstance(nav_diag, dict) and nav_diag:
            st.markdown("**Navigation diagnostics**")
            nav_rows = dict(nav_diag)
            nav_rows.setdefault("active_page_after", str(session.get("active_page") or ""))
            nav_rows.setdefault("main_sidebar_page_after", str(session.get("main_sidebar_page") or ""))
            nav_rows.setdefault("_navigate_to_page_after", str(session.get("_navigate_to_page") or ""))
            nav_rows.setdefault("_suite_page_user_nav", bool(session.get("_suite_page_user_nav")))
            st.json(nav_rows)
        if isinstance(save_diag, dict) and save_diag:
            st.markdown("**Save diagnostics**")
            st.json(save_diag)
        if diag.get("cloud_enabled"):
            cloud_probe = probe_cloud_workflow_for_workspace(ws_id)
            if cloud_probe.get("row_found"):
                st.markdown(
                    f"**Cloud blob:** {int(cloud_probe.get('draft_archive_count') or 0)} drafts · "
                    f"{int(cloud_probe.get('league_context_count') or 0)} league contexts "
                    f"(updated {cloud_probe.get('updated_at') or '—'})"
                )
            else:
                st.caption("Cloud: no baseball row for this workspace key.")
        elif not diag.get("cloud_enabled"):
            st.caption("Cloud storage not configured in this deployment.")


def _page_label(page_key: str, page_label_fn=None) -> str:
    if callable(page_label_fn):
        return str(page_label_fn(page_key))
    return page_key


def _page_icon(page_key: str, page_label_fn=None) -> str:
    label = _page_label(page_key, page_label_fn)
    first = label.split(" ", 1)[0].strip()
    return first if first and first != page_key else ""


def _nav_label(page_key: str, text: str, page_label_fn=None) -> str:
    icon = _page_icon(page_key, page_label_fn)
    return f"{icon} {text}".strip()


def _workflow_counts(session: dict[str, Any]) -> dict[str, int]:
    try:
        from workflow_persist_guard import workflow_counts_from_session

        return workflow_counts_from_session(session)
    except ImportError:
        return {
            "draft_archive_count": len(list_draft_archives(session)),
            "league_context_count": len(list_league_contexts(session)),
        }


def _record_library_nav_diag(
    session: dict[str, Any],
    *,
    button: str,
    button_key: str,
    target_page: str,
    extra: dict[str, Any] | None = None,
) -> None:
    from datetime import datetime, timezone

    payload: dict[str, Any] = {
        "button": button,
        "button_key": button_key,
        "target_page": target_page,
        "active_page_before": str(session.get("active_page") or ""),
        "_navigate_to_page_before": str(session.get("_navigate_to_page") or ""),
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(extra, dict):
        payload.update(extra)
    session["_draft_library_nav_diag"] = payload


def _on_click_navigate_to_page(target_page: str, button_key: str = "", button: str = "") -> None:
    """Streamlit on_click — runs before sidebar widgets on the next rerun."""
    import streamlit as st

    session = st.session_state
    _record_library_nav_diag(
        session,
        button=button or button_key or "navigate",
        button_key=button_key,
        target_page=target_page,
    )
    schedule_page_navigation(session, target_page)


def _on_click_saved_draft_library(return_page: str, button_key: str, button: str) -> None:
    import streamlit as st

    session = st.session_state
    counts = _workflow_counts(session)
    session["_draft_library_nav_active_before"] = str(session.get("active_page") or "")
    _record_library_nav_diag(
        session,
        button=button,
        button_key=button_key,
        target_page=SAVED_DRAFT_LIBRARY_PAGE,
        extra={
            "draft_archive_count": int(counts.get("draft_archive_count") or 0),
            "league_context_count": int(counts.get("league_context_count") or 0),
        },
    )
    schedule_saved_draft_library_navigation(
        session,
        return_page=return_page or str(session.get("active_page") or ""),
    )


def _on_click_return_from_saved_draft_library(button_key: str) -> None:
    import streamlit as st

    session = st.session_state
    target = str(session.get(SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY) or "").strip()
    if not schedule_return_from_saved_draft_library(session):
        return
    _record_library_nav_diag(
        session,
        button="return_from_library",
        button_key=button_key,
        target_page=target,
    )


def schedule_page_navigation(session: dict[str, Any], target_page: str) -> None:
    """Queue programmatic navigation — consumed before sidebar radio on the next rerun."""
    target = str(target_page or "").strip()
    if not target:
        return
    session["_navigate_to_page"] = target
    session["_skip_page_restore_for"] = target
    session["_suite_page_user_nav"] = True
    session.pop("_suite_cloud_target_page", None)
    prior = session.get("_draft_library_nav_diag")
    if not isinstance(prior, dict):
        prior = {}
    session["_draft_library_nav_diag"] = {
        **prior,
        "target_page": target,
        "active_page_before": str(
            session.get("_draft_library_nav_active_before") or session.get("active_page") or ""
        ),
        "_navigate_to_page": target,
        "_suite_page_user_nav": True,
    }


def schedule_saved_draft_library_navigation(
    session: dict[str, Any],
    *,
    return_page: str = "",
) -> None:
    """Navigate to Saved Draft Library; remember source page for return."""
    source = str(return_page or session.get("active_page") or "").strip()
    if source and source != SAVED_DRAFT_LIBRARY_PAGE:
        session[SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY] = source
    schedule_page_navigation(session, SAVED_DRAFT_LIBRARY_PAGE)


def schedule_return_from_saved_draft_library(session: dict[str, Any]) -> bool:
    """Return to the workflow page that opened the library."""
    target = str(session.pop(SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY, None) or "").strip()
    if not target or target == SAVED_DRAFT_LIBRARY_PAGE:
        return False
    schedule_page_navigation(session, target)
    return True


def schedule_fantasy_analysis_navigation(session: dict[str, Any], target_page: str) -> bool:
    """Activate/resync active league context, then navigate before widgets render on next run."""
    if not schedule_active_context_resync(session):
        return False
    schedule_page_navigation(session, target_page)
    return True


def _record_save_diag(
    session: dict[str, Any],
    *,
    reason: str,
    before: dict[str, int],
    after: dict[str, int],
    persist_ok: bool,
    entry: dict[str, Any] | None = None,
    probe_cloud: bool = True,
) -> None:
    cloud_readback: dict[str, Any] = {}
    if probe_cloud:
        try:
            from workflow_persist_guard import probe_cloud_workflow_for_workspace
            from suite_workspace import get_active_workspace_id

            ws_id = str(get_active_workspace_id(type("_St", (), {"session_state": session})()))
            cloud_readback = probe_cloud_workflow_for_workspace(ws_id)
        except Exception:
            pass
    session["_draft_library_save_diag"] = {
        "reason": reason,
        "persist_ok": persist_ok,
        "draft_archive_count_before": int(before.get("draft_archive_count") or 0),
        "draft_archive_count_after": int(after.get("draft_archive_count") or 0),
        "league_context_count_before": int(before.get("league_context_count") or 0),
        "league_context_count_after": int(after.get("league_context_count") or 0),
        "cloud_readback_drafts": int(cloud_readback.get("draft_archive_count") or 0),
        "cloud_readback_contexts": int(cloud_readback.get("league_context_count") or 0),
        "draft_id": str((entry or {}).get("draft_id") or ""),
        "draft_name": str((entry or {}).get("draft_name") or ""),
        "restore_source": str(
            session.get("_suite_persist_last_restore_source")
            or session.get("_suite_restore_pick_source")
            or "session"
        ),
    }


def _persist_archive(session: dict[str, Any], st: Any, *, reason: str, entry: dict[str, Any] | None = None) -> bool:
    before = _workflow_counts(session)
    try:
        from workflow_persist_guard import mark_workflow_persist_authoritative

        mark_workflow_persist_authoritative(session)
    except ImportError:
        pass
    try:
        from suite_user_persistence import clear_workspace_autosave_block

        clear_workspace_autosave_block(st, "baseball")
    except ImportError:
        try:
            from suite_user_persistence import _autosave_block_key

            session.pop(_autosave_block_key("baseball"), None)
            session.pop("_suite_autosave_block_reason", None)
        except ImportError:
            pass
    session.pop("_suite_autosave_fp::baseball", None)
    session.pop("_suite_restored_fp::baseball", None)
    probe_cloud = False
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        probe_cloud = bool(developer_mode_checkbox_enabled(st=st))
    except Exception:
        pass
    try:
        from baseball_persistent_state import force_save_baseball_state

        ok = bool(force_save_baseball_state(st, reason=reason))
    except Exception as exc:
        session["_draft_archive_persist_error"] = f"{type(exc).__name__}: {exc}"
        ok = False
    after = _workflow_counts(session)
    entry_id = str((entry or {}).get("draft_id") or "").strip()
    if entry_id:
        session_has_entry = bool(get_draft_archive(session, entry_id))
    else:
        session_has_entry = int(after.get("draft_archive_count") or 0) >= int(before.get("draft_archive_count") or 0) > 0
    count_increased = int(after.get("draft_archive_count") or 0) > int(before.get("draft_archive_count") or 0)
    persist_ok = bool(ok and session_has_entry) or (session_has_entry and count_increased)
    if session_has_entry and not ok:
        try:
            session.pop("_suite_autosave_fp::baseball", None)
            ok = bool(force_save_baseball_state(st, reason=f"{reason}_retry"))
            persist_ok = persist_ok or bool(ok and get_draft_archive(session, entry_id))
        except Exception:
            pass
    _record_save_diag(
        session,
        reason=reason,
        before=before,
        after=after,
        persist_ok=persist_ok,
        entry=entry,
        probe_cloud=probe_cloud,
    )
    return persist_ok


def _clear_fantasy_caches_on_archive_change(session: dict[str, Any]) -> None:
    try:
        from fantasy_perf_cache import (
            LINEUP_SCORES_CACHE_KEY,
            STANDINGS_ROSTER_CACHE_KEY,
            WAIVER_ANALYSIS_CACHE_KEY,
        )

        session.pop(STANDINGS_ROSTER_CACHE_KEY, None)
        session.pop(LINEUP_SCORES_CACHE_KEY, None)
        session.pop(WAIVER_ANALYSIS_CACHE_KEY, None)
    except ImportError:
        pass


def _draft_type_badge_html(entry: dict[str, Any]) -> str:
    label = draft_type_display(entry)
    css = "ld-archive-badge-live" if label == "Live Draft" else "ld-archive-badge-sim"
    return f'<span class="ld-archive-badge {css}">{label}</span>'


def _context_badge_html(label: str, css_class: str) -> str:
    if not label:
        return ""
    return f'<span class="ld-archive-badge {css_class}">{label}</span>'


def _context_badges_html(session: dict[str, Any], entry: dict[str, Any]) -> str:
    context = get_league_context_for_archive(session, entry)
    parts = [
        _draft_type_badge_html(entry),
        _context_badge_html(league_context_coverage_badge(context), "ld-archive-badge-coverage"),
        _context_badge_html(league_context_type_badge(context), "ld-archive-badge-context-type"),
    ]
    return "".join(p for p in parts if p)


def render_active_saved_draft_chip(
    st: Any,
    session: dict[str, Any],
    *,
    key_prefix: str = "active_draft",
    page_label_fn=None,
) -> None:
    """Compact active-draft indicator with link to the library."""
    active = get_active_draft_archive(session)
    active_context = get_active_league_context(session)
    if active:
        context = active_context or get_league_context_for_archive(session, active)
        team_count = league_team_count(context, active)
        coverage = league_context_coverage_badge(context)
        st.markdown(
            f"**Active Saved Draft:** {active.get('draft_name', 'Saved Draft')} · "
            f"**{draft_type_display(active)}** · {coverage} · "
            f"{active.get('team_name', '')} · "
            f"{team_count} team{'s' if team_count != 1 else ''} · "
            f"{len(active.get('players') or [])} players on your roster · "
            f"Updated {format_archive_modified(active)}",
            unsafe_allow_html=False,
        )
    else:
        st.caption(
            "No active saved draft selected. Standings and Lineup use the **Draft Room** board "
            "unless you set one active in the library."
        )
    st.button(
        _nav_label(SAVED_DRAFT_LIBRARY_PAGE, "Manage saved drafts", page_label_fn),
        key=f"{key_prefix}__manage_saved_drafts_btn",
        use_container_width=True,
        on_click=_on_click_saved_draft_library,
        args=(str(session.get("active_page") or ""), f"{key_prefix}__manage_saved_drafts_btn", "manage_saved_drafts"),
    )


def _render_post_save_actions(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    page_label_fn=None,
    context: dict[str, Any] | None = None,
    league_save: bool = False,
) -> None:
    context = context or get_league_context_for_archive(session, entry)
    team_count = league_team_count(context, entry)
    if league_save and context:
        st.success(
            f"Saved **{entry.get('draft_name')}** as a **{league_context_coverage_badge(context)}** "
            f"({team_count} teams, {len(entry.get('players') or [])} players on your roster). "
            "Set active for Standings and Lineup analysis."
        )
    else:
        st.success(
            f"Saved **{entry.get('draft_name')}** ({len(entry.get('players') or [])} players). "
            "Set active for Standings and Lineup analysis."
        )
    view_col, standings_col = st.columns(2)
    with view_col:
        st.button(
            _nav_label(SAVED_DRAFT_LIBRARY_PAGE, "View in Saved Draft Library", page_label_fn),
            key=f"view_library_{entry.get('draft_id')}_btn",
            type="primary",
            on_click=_on_click_saved_draft_library,
            args=("", f"view_library_{entry.get('draft_id')}_btn", "view_in_saved_draft_library"),
        )
    with standings_col:
        if st.button(
            _nav_label(FANTASY_STANDINGS_PAGE, "Go to Standings Tracker", page_label_fn),
            key=f"view_standings_{entry.get('draft_id')}",
        ):
            if schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE):
                st.rerun()
            else:
                st.warning("Set an active league context first.")


def render_league_context_save_flash(st: Any, session: dict[str, Any], *, page_label_fn=None) -> None:
    """Show deferred post-save success after league context save + rerun."""
    flash = pop_league_context_save_flash(session)
    if not flash:
        return
    draft_id = str(flash.get("draft_id") or "")
    entry = {"draft_id": draft_id, "draft_name": flash.get("draft_name")}
    context = get_league_context_for_archive(session, entry) if draft_id else None
    _render_post_save_actions(
        st,
        session,
        entry,
        page_label_fn=page_label_fn,
        context=context,
        league_save=bool(flash.get("league_save")),
    )


def render_save_live_draft_team(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str = "live_draft_archive",
    page_label_fn=None,
) -> None:
    cfg = dict(room.get("config") or {})
    if not team_name or team_name == "—":
        return
    with st.expander("Save completed draft", expanded=False):
        draft_name = st.text_input(
            "League context name",
            value=f"{cfg.get('league_name', 'Live Draft')} — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        st.caption(
            "Saves **Active League Context** with all team rosters from this live draft, "
            "then activates it for fantasy workflows."
        )
        if st.button("Save Active League Context", key=f"{key_prefix}_save_league_btn", type="primary"):
            try:
                counts_before = _workflow_counts(session)
                entry, context = save_live_draft_league_context(
                    session,
                    room,
                    my_team_name=team_name,
                    draft_name=draft_name,
                    defer_activation=True,
                )
                _clear_fantasy_caches_on_archive_change(session)
                persist_ok = _persist_archive(session, st, reason="live_draft_league_context_saved", entry=entry)
                if isinstance(session.get("_draft_library_save_diag"), dict):
                    session["_draft_library_save_diag"]["counts_before_explicit"] = counts_before
                if not persist_ok:
                    st.error(
                        "Saved to this session, but cloud/disk persist failed. "
                        "Open **Persistence diagnostics** on Saved Draft Library (Developer Mode) before refreshing."
                    )
                else:
                    try:
                        from baseball_archive_activity import log_saved_draft_archived

                        log_saved_draft_archived(entry, session=session)
                    except ImportError:
                        pass
                    stash_league_context_save_flash(session, entry, context=context, league_save=True)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save active league context: {exc}")


def render_save_simulator_draft_team(
    st: Any,
    session: dict[str, Any],
    board_df: Any,
    *,
    team_name: str,
    key_prefix: str = "sim_draft_archive",
    page_label_fn=None,
) -> None:
    if not team_name or team_name == "—":
        return
    with st.expander("Save Active League Context", expanded=False):
        st.caption(
            "Saves the full mock draft as **Active League Context** (all teams), "
            "ready for Standings, Lineup, and Waiver workflows."
        )
        draft_name = st.text_input(
            "League name",
            value=f"Simulator — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        if st.button("Save Active League Context", key=f"{key_prefix}_save_league_btn", type="primary"):
            try:
                if board_df is None or getattr(board_df, "empty", True):
                    st.error("No draft picks on the board yet — enter picks before saving.")
                    return
                filled = board_df.copy()
                player_col = "Player" if "Player" in filled.columns else "fullName"
                if player_col in filled.columns:
                    filled = filled[filled[player_col].astype(str).str.strip() != ""]
                if filled.empty:
                    st.error("No drafted players found — add picks to the board before saving.")
                    return
                counts_before = _workflow_counts(session)
                entry, context = save_simulator_league_context(
                    session,
                    board_df,
                    my_team_name=team_name,
                    draft_name=draft_name,
                    config=dict(session.get("draft_shared_settings") or {}),
                    defer_activation=True,
                )
                _clear_fantasy_caches_on_archive_change(session)
                persist_ok = _persist_archive(session, st, reason="simulator_league_context_saved", entry=entry)
                if isinstance(session.get("_draft_library_save_diag"), dict):
                    session["_draft_library_save_diag"]["counts_before_explicit"] = counts_before
                if not persist_ok:
                    st.error(
                        "Saved to this session, but cloud/disk persist failed. "
                        "Open **Persistence diagnostics** on Saved Draft Library (Developer Mode) before refreshing."
                    )
                else:
                    try:
                        from baseball_archive_activity import log_saved_draft_archived

                        log_saved_draft_archived(entry, session=session)
                    except ImportError:
                        pass
                    stash_league_context_save_flash(session, entry, context=context, league_save=True)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save active league context: {exc}")


def _render_archive_actions(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    active_id: str,
    active_context_id: str,
) -> None:
    draft_id = str(entry.get("draft_id") or "")
    if not draft_id:
        return
    context = get_league_context_for_archive(session, entry)
    league_context_id = str((context or {}).get("league_context_id") or entry.get("league_context_id") or "").strip()
    is_active = draft_id == active_id and (
        not active_context_id or not league_context_id or league_context_id == active_context_id
    )
    rename_val = st.text_input(
        "Rename",
        value=str(entry.get("draft_name") or ""),
        key=f"archive_rename_{draft_id}",
        label_visibility="collapsed",
        placeholder="Draft name",
    )
    draft_type = str(entry.get("draft_type") or "")
    room_col1, room_col2 = st.columns(2)
    with room_col1:
        st.button(
            _nav_label(LIVE_DRAFT_PAGE, "Open Live Draft Room", None),
            key=f"archive_open_live_{draft_id}",
            use_container_width=True,
            on_click=_on_click_navigate_to_page,
            args=(LIVE_DRAFT_PAGE, f"archive_open_live_{draft_id}", "open_live_draft_room"),
        )
    with room_col2:
        sim_target = DRAFT_SIMULATOR_PAGE
        st.button(
            "Go to Draft Room Simulator",
            key=f"archive_open_lab_{draft_id}",
            use_container_width=True,
            on_click=_on_click_navigate_to_page,
            args=(sim_target, f"archive_open_lab_{draft_id}", "go_to_draft_room_simulator"),
        )
    btn1, btn2, btn3, btn4 = st.columns(4)
    with btn1:
        if st.button(
            "Active" if is_active else "Set Active League Context",
            key=f"archive_active_{draft_id}",
            type="primary" if is_active else "secondary",
            disabled=is_active,
            use_container_width=True,
        ):
            loaded_entry, loaded_context = activate_archive_league_context(
                session,
                draft_id,
                defer_activation=True,
            )
            if loaded_entry:
                _clear_fantasy_caches_on_archive_change(session)
                _persist_archive(session, st, reason="league_context_activated")
                try:
                    from baseball_archive_activity import log_saved_draft_activated

                    log_saved_draft_activated(
                        loaded_entry,
                        session=session,
                        target_page=SAVED_DRAFT_LIBRARY_PAGE,
                    )
                except ImportError:
                    pass
                if loaded_context:
                    st.session_state["_league_context_activation_toast"] = (
                        f"Active league context: {loaded_context.get('display_name', loaded_entry.get('draft_name'))}"
                    )
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


def render_saved_draft_library_page(st: Any, session: dict[str, Any], *, page_label_fn=None) -> None:
    """Dedicated management page for all saved draft teams."""
    toast_msg = session.pop("_league_context_activation_toast", None)
    if toast_msg:
        st.toast(str(toast_msg))
    flash = pop_league_context_save_flash(session)
    if flash:
        if flash.get("league_save"):
            st.success(
                f"Saved **{flash.get('draft_name')}** as a **{flash.get('coverage')}** "
                f"({flash.get('team_count')} teams, {flash.get('player_count')} players on your roster). "
                "Set active for Standings and Lineup analysis."
            )
        else:
            st.success(
                f"Saved **{flash.get('draft_name')}** ({flash.get('player_count')} players). "
                "Set active for Standings and Lineup analysis."
            )

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
        .ld-archive-badge-coverage { background: #5b4b8a; color: #fff; }
        .ld-archive-badge-context-type { background: #6b4f2a; color: #fff; }
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
    try:
        from fantasy_league_context import repair_missing_draft_archives_from_contexts

        if repair_missing_draft_archives_from_contexts(session):
            archives = list_draft_archives(session)
    except ImportError:
        pass
    active = get_active_draft_archive(session)
    active_context = get_active_league_context(session)
    active_id = str((active or {}).get("draft_id") or "")
    active_context_id = str((active_context or {}).get("league_context_id") or "")

    st.caption(
        "Keep multiple saved drafts and league contexts — mock drafts, live draft results, and uploaded leagues. "
        "Setting one **Active League Context** powers **Standings**, **Lineup**, **Waiver Wire**, and trade tools. "
        "Use **Fantasy Context Sync** below to make research pages league-aware."
    )

    _render_persistence_diagnostics(st, session)

    try:
        from fantasy_context_ui import render_fantasy_context_library_block

        render_fantasy_context_library_block(st, session, active_context=active_context)
        st.divider()
    except ImportError:
        pass

    return_page = str(session.get(SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY) or "").strip()
    if return_page and return_page != SAVED_DRAFT_LIBRARY_PAGE:
        st.button(
            _nav_label(return_page, f"Return to {return_page}", page_label_fn),
            key="library_return_to_workflow",
            use_container_width=False,
            on_click=_on_click_return_from_saved_draft_library,
            args=("library_return_to_workflow",),
        )

    top_left, top_mid, top_right = st.columns([2, 2, 1])
    with top_left:
        st.metric("Saved drafts", len(archives))
    with top_mid:
        try:
            from fantasy_league_context import list_league_contexts

            st.metric("League contexts", len(list_league_contexts(session)))
        except ImportError:
            st.metric("League contexts", 0)
    with top_right:
        if active and st.button("Clear active draft", key="library_clear_active", use_container_width=True):
            clear_active_draft_archive(session)
            clear_active_league_context(session)
            _clear_fantasy_caches_on_archive_change(session)
            _persist_archive(session, st, reason="draft_archive_cleared")
            st.rerun()

    if not archives:
        st.info(
            "No saved drafts yet. Finish a **Live Draft Room** or **Draft Room Simulator** draft, "
            "then use **Save League Context** or **Save Mock League Context**."
        )
        nav1, nav2 = st.columns(2)
        with nav1:
            st.button(
                _nav_label(LIVE_DRAFT_PAGE, "Open Live Draft Room", page_label_fn),
                key="library__go_live_draft_room_btn",
                use_container_width=True,
                on_click=_on_click_navigate_to_page,
                args=(LIVE_DRAFT_PAGE, "library__go_live_draft_room_btn", "open_live_draft_room"),
            )
        with nav2:
            st.button(
                _nav_label(DRAFT_SIMULATOR_PAGE, "Go to Draft Room Simulator", page_label_fn),
                key="library__go_draft_simulator_btn",
                use_container_width=True,
                on_click=_on_click_navigate_to_page,
                args=(DRAFT_SIMULATOR_PAGE, "library__go_draft_simulator_btn", "go_to_draft_room_simulator"),
            )
        return

    for entry in archives:
        draft_id = str(entry.get("draft_id") or "")
        context = get_league_context_for_archive(session, entry)
        league_context_id = str((context or {}).get("league_context_id") or entry.get("league_context_id") or "")
        is_active = draft_id == active_id and (
            not active_context_id or not league_context_id or league_context_id == active_context_id
        )
        card_class = "ld-archive-card ld-archive-active" if is_active else "ld-archive-card"
        player_n = len(entry.get("players") or [])
        team_n = league_team_count(context, entry)
        title = str(entry.get("draft_name") or "Saved Draft")
        team = str(entry.get("team_name") or "—")
        modified = format_archive_modified(entry)
        active_tag = " · **ACTIVE LEAGUE CONTEXT**" if is_active else ""
        st.markdown(
            f'<div class="{card_class}">{_context_badges_html(session, entry)}'
            f"<strong>{title}</strong>{active_tag}<br>"
            f"<span style='opacity:0.85'>{team} · {team_n} team{'s' if team_n != 1 else ''} · "
            f"{player_n} players on your roster · Updated {modified}</span></div>",
            unsafe_allow_html=True,
        )
        _render_archive_actions(
            st,
            session,
            entry,
            active_id=active_id,
            active_context_id=active_context_id,
        )

    st.divider()
    st.markdown("##### Analyze an active saved draft")
    go1, go2 = st.columns(2)
    with go1:
        if st.button(
            _nav_label(FANTASY_STANDINGS_PAGE, "Open Fantasy Standings Tracker", page_label_fn),
            key="library_open_standings",
            use_container_width=True,
        ):
            if not get_active_league_context(session) and not get_active_draft_archive(session):
                st.warning("Set an **Active League Context** first.")
            elif schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE):
                active = get_active_draft_archive(session)
                if active:
                    try:
                        from baseball_archive_activity import log_saved_draft_activated

                        log_saved_draft_activated(
                            active,
                            session=session,
                            target_page=FANTASY_STANDINGS_PAGE,
                        )
                    except ImportError:
                        pass
                st.rerun()
    with go2:
        if st.button(
            _nav_label(FANTASY_LINEUP_PAGE, "Open Fantasy Lineup Assistant", page_label_fn),
            key="library_open_lineup",
            use_container_width=True,
        ):
            if not get_active_league_context(session) and not get_active_draft_archive(session):
                st.warning("Set an **Active League Context** first.")
            elif schedule_fantasy_analysis_navigation(session, FANTASY_LINEUP_PAGE):
                st.rerun()
