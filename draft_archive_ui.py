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
    archive_my_team_player_count,
    archive_card_player_count,
    archive_card_team_count,
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
    upsert_league_context,
)

SAVED_DRAFT_LIBRARY_PAGE = "Saved Draft Library"
FANTASY_STANDINGS_PAGE = "Fantasy Standings Tracker"
FANTASY_LINEUP_PAGE = "Fantasy Lineup Assistant"
FANTASY_WAIVER_PAGE = "Waiver Wire / Add-Drop Center"
LIVE_DRAFT_PAGE = "Live Draft Room"
DRAFT_LAB_PAGE = "Draft Lab / Simulation"
DRAFT_SIMULATOR_PAGE = "Draft Room Simulator"
SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY = "_saved_draft_library_return_page"
_DELETE_CONFIRM_PREFIX = "_draft_archive_delete_confirm_"
_RENAME_CONFIRM_PREFIX = "_draft_archive_rename_confirm_"
MANAGE_SAVED_DRAFTS_LABEL = "Manage Saved Drafts"
_DRAFT_SAVE_UI_FLASH_KEY = "_draft_save_ui_flash"
_DRAFT_ANALYZE_UI_FLASH_KEY = "_draft_analyze_ui_flash"
_PAGE_ICONS: dict[str, str] = {
    SAVED_DRAFT_LIBRARY_PAGE: "📁",
    FANTASY_STANDINGS_PAGE: "📊",
    FANTASY_LINEUP_PAGE: "🧠",
    FANTASY_WAIVER_PAGE: "🔄",
    LIVE_DRAFT_PAGE: "📡",
    DRAFT_LAB_PAGE: "🧪",
    DRAFT_SIMULATOR_PAGE: "🧾",
}

FANTASY_NAV_TARGETS: dict[str, tuple[str, ...]] = {
    FANTASY_STANDINGS_PAGE: (SAVED_DRAFT_LIBRARY_PAGE, FANTASY_LINEUP_PAGE),
    FANTASY_LINEUP_PAGE: (SAVED_DRAFT_LIBRARY_PAGE, FANTASY_STANDINGS_PAGE, FANTASY_WAIVER_PAGE),
    FANTASY_WAIVER_PAGE: (SAVED_DRAFT_LIBRARY_PAGE, FANTASY_STANDINGS_PAGE, FANTASY_LINEUP_PAGE),
}

_KEY_PREFIX_TO_FANTASY_PAGE: dict[str, str] = {
    "standings_archive": FANTASY_STANDINGS_PAGE,
    "lineup_archive": FANTASY_LINEUP_PAGE,
    "waiver_archive": FANTASY_WAIVER_PAGE,
}

_FANTASY_NAV_KEY_PREFIXES: tuple[str, ...] = (
    "standings_archive",
    "lineup_archive",
    "waiver_archive",
    "fantasy_nav",
)


def _fantasy_nav_button_widget_key(key_prefix: str, safe_key: str) -> str:
    """Streamlit button widget key — never write this key into session_state directly."""
    return f"{key_prefix}_nav_btn_{safe_key}"


def purge_fantasy_nav_widget_keys(session: dict[str, Any], *, key_prefix: str = "") -> None:
    """Drop persisted fantasy nav widget keys so st.button can bind on this rerun."""
    prefix = str(key_prefix or "").strip()
    for key in list(session.keys()):
        if not isinstance(key, str):
            continue
        if prefix and not key.startswith(prefix):
            continue
        if not any(key.startswith(f"{p}_nav_") for p in _FANTASY_NAV_KEY_PREFIXES):
            continue
        session.pop(key, None)


def _set_draft_save_ui_flash(session: dict[str, Any], *, level: str, message: str) -> None:
    session[_DRAFT_SAVE_UI_FLASH_KEY] = {"level": str(level or "info"), "message": str(message or "")}


def _pop_draft_save_ui_flash(session: dict[str, Any]) -> dict[str, str] | None:
    flash = session.pop(_DRAFT_SAVE_UI_FLASH_KEY, None)
    return flash if isinstance(flash, dict) else None


def _execute_simulator_league_context_save(
    st: Any,
    session: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str,
    save_only: bool = True,
) -> None:
    """Run simulator league-context save (Streamlit on_click callback body)."""
    draft_name = str(session.get(f"{key_prefix}_name_input") or f"Simulator — {team_name}")
    session["_draft_save_trace_expand"] = True
    try:
        from draft_library_save_trace import (
            finalize_save_trace,
            record_save_button_click,
            record_save_failure_trace,
            resolve_simulator_board_df,
        )

        record_save_button_click(
            session,
            source="draft_room_simulator",
            team_name=team_name,
            key_prefix=key_prefix,
            reason="simulator_league_context_saved",
        )
    except ImportError:
        resolve_simulator_board_df = lambda _s: None  # type: ignore[assignment,misc]
        record_save_failure_trace = None  # type: ignore[assignment,misc]
        finalize_save_trace = None  # type: ignore[assignment,misc]

    counts_before = _workflow_counts(session)
    board_df = resolve_simulator_board_df(session)

    def _fail(error: str, *, user_message: str) -> None:
        try:
            if record_save_failure_trace is not None:
                record_save_failure_trace(
                    session,
                    reason="simulator_league_context_saved",
                    error=error,
                    before=counts_before,
                )
        except Exception:
            pass
        _set_draft_save_ui_flash(session, level="error", message=user_message)

    if board_df is None or getattr(board_df, "empty", True):
        _fail("No draft picks on the board yet", user_message="No draft picks on the board yet — enter picks before saving.")
        return

    filled = board_df.copy()
    player_col = "Player" if "Player" in filled.columns else "fullName"
    if player_col in filled.columns:
        filled = filled[filled[player_col].astype(str).str.strip() != ""]
    if filled.empty:
        _fail(
            "No drafted players found on board",
            user_message="No drafted players found — add picks to the board before saving.",
        )
        return

    try:
        entry, context = save_simulator_league_context(
            session,
            board_df,
            my_team_name=team_name,
            draft_name=draft_name,
            config=dict(session.get("draft_shared_settings") or {}),
            defer_activation=True,
            reuse_session_draft_id=False,
            save_only=save_only,
        )
        counts_after_save = _workflow_counts(session)
        if not list_draft_archives(session):
            try:
                if record_save_failure_trace is not None:
                    record_save_failure_trace(
                        session,
                        reason="simulator_league_context_saved",
                        error="Session library empty after save_simulator_league_context",
                        before=counts_before,
                    )
                if finalize_save_trace is not None:
                    finalize_save_trace(
                        session,
                        reason="simulator_league_context_saved",
                        before=counts_before,
                        after=counts_after_save,
                        persist_ok=False,
                        entry=entry if isinstance(entry, dict) else None,
                        probe_cloud=True,
                    )
            except Exception:
                pass
            _set_draft_save_ui_flash(
                session,
                level="error",
                message="Save did not update Saved Draft Library — see save diagnostics below.",
            )
            return

        _clear_fantasy_caches_on_archive_change(session)
        persist_ok = _persist_archive(session, st, reason="simulator_league_context_saved", entry=entry)
        if isinstance(session.get("_draft_library_save_diag"), dict):
            session["_draft_library_save_diag"]["counts_before_explicit"] = counts_before
        if not persist_ok:
            _set_draft_save_ui_flash(
                session,
                level="error",
                message=(
                    "Saved to this session, but cloud/disk persist failed. "
                    "Review **Save Diagnostics** below before refreshing."
                ),
            )
        else:
            try:
                from baseball_archive_activity import log_saved_draft_archived

                log_saved_draft_archived(entry, session=session)
            except ImportError:
                pass
            stash_league_context_save_flash(session, entry, context=context, league_save=True)
    except Exception as exc:
        try:
            if record_save_failure_trace is not None:
                record_save_failure_trace(
                    session,
                    reason="simulator_league_context_saved",
                    error=f"{type(exc).__name__}: {exc}",
                )
        except Exception:
            pass
        _set_draft_save_ui_flash(session, level="error", message=f"Could not save draft: {exc}")


def _on_simulator_save_click(team_name: str = "", key_prefix: str = "", save_only: bool = True) -> None:
    import streamlit as st

    _execute_simulator_league_context_save(
        st,
        st.session_state,
        team_name=str(team_name or ""),
        key_prefix=str(key_prefix or ""),
        save_only=bool(save_only),
    )


def _on_click_save_probe_test_draft() -> None:
    import streamlit as st

    try:
        from workflow_persist_guard import save_probe_test_draft

        save_probe_test_draft(st, st.session_state)
    except Exception as exc:
        st.session_state["_probe_test_draft_trace"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def render_persistence_probe_panel(st: Any, session: dict[str, Any]) -> None:
    """Always-visible post-reboot probe: account, workspace, counts, restore verdict."""
    try:
        from workflow_persist_guard import build_persistence_probe_panel
    except ImportError:
        return

    probe = build_persistence_probe_panel(session)
    verdict = str(probe.get("persistence_verdict") or "")
    if verdict == "B_restore_failed":
        st.error("**Saved Draft Persistence Probe** — restore failed; storage may still have your drafts.")
    elif verdict == "A_persistence_failed_or_never_saved":
        st.warning("**Saved Draft Persistence Probe** — no durable saved drafts found in cloud or disk.")
    else:
        st.info("**Saved Draft Persistence Probe** — use after reboot to confirm account, workspace, and restore.")

    if probe.get("auth_signed_out_warning"):
        st.warning(str(probe["auth_signed_out_warning"]))

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**Signed in?** {probe.get('signed_in_label') or '—'}")
        if probe.get("auth_scope_label"):
            st.caption(probe["auth_scope_label"])
        st.markdown(f"**Account email:** {probe.get('account_email') or '—'}")
        st.markdown(f"**Cloud user ID:** `{probe.get('user_id') or '—'}`")
        st.markdown(f"**Workspace ID:** `{probe.get('workspace_id') or '—'}`")
        st.markdown(f"**Owned workspace ID:** `{probe.get('owned_workspace_id') or '—'}`")
        st.markdown(f"**Account scope (external id):** `{probe.get('account_external_id') or '—'}`")
        _allowed = probe.get("allowed_workspaces") or ()
        if _allowed:
            st.caption(f"Allowed workspaces: {', '.join(f'`{w}`' for w in _allowed)}")
        st.markdown(f"**Cloud app key:** `{probe.get('cloud_app_key') or '—'}`")
    with col_b:
        st.markdown(f"**Session draft count:** {int(probe.get('session_draft_count') or 0)}")
        st.markdown(f"**Cloud draft count:** {int(probe.get('cloud_draft_count') or 0)}")
        st.markdown(f"**Disk draft count:** {int(probe.get('disk_draft_count') or 0)}")
        st.markdown(f"**Active draft ID:** `{probe.get('active_draft_id') or '—'}`")
        st.markdown(f"**Active draft name:** {probe.get('active_draft_name') or '—'}")
        st.markdown(f"**Restore source:** `{probe.get('restore_source') or '—'}`")
        st.markdown(f"**Persistence verdict:** {probe.get('persistence_verdict_label') or '—'}")

    st.caption(
        f"Canonical key: `{probe.get('persist_canonical_session_key') or 'draft_archive_teams'}` · "
        f"Path: {probe.get('persistence_key_path') or '—'}"
    )
    st.markdown(
        f"**Cloud restore:** {probe.get('cloud_restore_attempted_label') or '—'} · "
        f"**error:** `{probe.get('cloud_restore_error') or '—'}`"
    )
    st.markdown(
        f"**Cloud write attempted:** {probe.get('cloud_write_attempted_label') or '—'} · "
        f"**readback count:** {int(probe.get('cloud_write_readback_count') or 0)} · "
        f"**readback ok:** {probe.get('cloud_write_readback_ok')}"
    )
    if probe.get("cloud_write_error") and probe.get("cloud_write_error") != "—":
        st.caption(f"Cloud write/readback error: `{probe['cloud_write_error']}`")
    if probe.get("last_save_reason") and probe.get("last_save_reason") != "—":
        st.caption(f"Last save reason: `{probe['last_save_reason']}`")
    if probe.get("empty_startup_write_blocked") and probe.get("empty_startup_write_blocked") != "—":
        st.caption(f"Empty startup write blocked/preserved: `{probe['empty_startup_write_blocked']}`")
    if probe.get("workflow_hydrated_from_cloud"):
        st.caption(
            f"Workflow hydrated this run from `{probe.get('workflow_hydrate_source') or 'cloud'}` "
            "before autosave could overwrite drafts."
        )
    if probe.get("local_state_path") and probe.get("local_state_path") != "—":
        st.caption(f"Disk path: `{probe['local_state_path']}`")

    owned_n = int(probe.get("cloud_draft_count_owned") or 0)
    legacy_n = int(probe.get("cloud_draft_count_legacy") or 0)
    if owned_n or legacy_n:
        st.caption(
            f"Other cloud rows (diagnostic): owned workspace **{owned_n}** · legacy daniel **{legacy_n}**"
        )

    st.markdown("**Reboot diagnosis**")
    diagnosis = probe.get("diagnosis") or {}
    for question, answer in diagnosis.items():
        st.markdown(f"- **{question}** {answer}")

    st.button(
        "Save Probe Test Draft",
        key="library_probe_save_test_draft_btn",
        help="Creates one known minimal draft, saves to disk+cloud, and runs immediate readback.",
        on_click=_on_click_save_probe_test_draft,
    )
    probe_trace = session.get("_probe_test_draft_trace")
    if isinstance(probe_trace, dict) and probe_trace:
        if probe_trace.get("ok"):
            st.success(
                f"Probe save OK — session **{int(probe_trace.get('session_draft_count_after') or 0)}** · "
                f"disk **{int(probe_trace.get('disk_draft_count') or 0)}** · "
                f"cloud readback **{int(probe_trace.get('cloud_readback_count') or 0)}** "
                f"(draft `{probe_trace.get('draft_id') or '—'}`)"
            )
        else:
            st.error(
                f"Probe save failed — session **{int(probe_trace.get('session_draft_count_after') or 0)}** · "
                f"disk **{int(probe_trace.get('disk_draft_count') or 0)}** · "
                f"cloud readback **{int(probe_trace.get('cloud_readback_count') or 0)}** · "
                f"error: `{probe_trace.get('cloud_readback_error') or probe_trace.get('cloud_write_error') or probe_trace.get('error') or '—'}`"
            )


def render_persistence_durability_banner(st: Any, session: dict[str, Any]) -> bool:
    """Visible (non-dev) warning when saves are not durable across app reboot.

    Returns True when durable (verified cloud) persistence is active.
    """
    try:
        from workflow_persist_guard import evaluate_cloud_durability_status
    except ImportError:
        return True
    status = evaluate_cloud_durability_status(session)
    if status.get("durable_persistence"):
        st.success(f"**Persistence:** {status.get('durability_label')}")
        return True
    st.error(f"**Persistence:** {status.get('durability_label')}")
    if status.get("durability_warning"):
        st.warning(str(status["durability_warning"]))
    return False


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
        owned_ws = str(diag.get("owned_workspace_id") or "—")
        if owned_ws and owned_ws != "—" and owned_ws != ws_id:
            st.markdown(f"**Owned workspace:** `{owned_ws}`")
        st.markdown(
            f"**Counts (session):** {int(diag.get('draft_archive_count') or 0)} saved drafts · "
            f"{int(diag.get('league_context_count') or 0)} league contexts"
        )
        st.markdown(
            f"**Counts (storage):** cloud active **{int(diag.get('cloud_saved_draft_count_active') or 0)}** · "
            f"cloud owned **{int(diag.get('cloud_saved_draft_count_owned') or 0)}** · "
            f"cloud legacy (daniel) **{int(diag.get('cloud_saved_draft_count_legacy') or 0)}** · "
            f"disk **{int(diag.get('disk_saved_draft_count') or 0)}**"
        )
        st.caption(str(diag.get("ownership_filter_note") or ""))
        if diag.get("durable_persistence"):
            st.success(f"**Persistence:** {diag.get('durability_label')}")
        else:
            st.error(f"**Persistence:** {diag.get('durability_label')}")
            if diag.get("durability_warning"):
                st.warning(str(diag["durability_warning"]))
        startup_snap = session.get("_suite_startup_restore_snapshot")
        if isinstance(startup_snap, dict) and startup_snap:
            st.markdown("**Startup restore snapshot**")
            verdict = str(startup_snap.get("persistence_verdict") or "")
            verdict_note = {
                "B_restore_failed": "Cloud/disk had data but session is empty — **restore failed (B)**.",
                "A_persistence_failed_or_never_saved": "No drafts/tracked players in cloud or disk — **persistence may have failed or was never saved (A)**.",
                "ok": "Session counts match restore sources.",
            }.get(verdict, "")
            st.markdown(
                f"Workspace `{startup_snap.get('restored_workspace_id') or '—'}` · "
                f"Page **{startup_snap.get('restored_active_page') or '—'}** · "
                f"Session drafts **{int(startup_snap.get('session_saved_draft_count') or 0)}** "
                f"(active `{startup_snap.get('session_active_draft_id') or '—'}`) · "
                f"Tracked **{int(startup_snap.get('session_tracked_player_count') or 0)}**"
            )
            st.caption(
                f"Cloud: {int(startup_snap.get('cloud_saved_draft_count') or 0)} drafts · "
                f"Disk: {int(startup_snap.get('disk_saved_draft_count') or 0)} drafts · "
                f"Restore: {startup_snap.get('restore_pick_source') or '—'} "
                f"({startup_snap.get('restore_decision') or '—'})"
            )
            if verdict_note:
                if verdict == "B_restore_failed":
                    st.warning(verdict_note)
                elif verdict == "A_persistence_failed_or_never_saved":
                    st.info(verdict_note)
                else:
                    st.caption(verdict_note)
        st.markdown(f"**Restore source:** {diag.get('restore_source_label') or '—'}")
        if diag.get("restore_cloud_vs_demo_note"):
            st.warning(str(diag["restore_cloud_vs_demo_note"]))
        if diag.get("auth_mode"):
            st.caption(
                f"Auth mode: **{diag.get('auth_mode')}** · durable cloud write: "
                f"{diag.get('cloud_write_expected')} (requires Supabase config, not sign-in)"
            )
        if diag.get("auth_enabled_but_signed_out"):
            st.info(
                "Sign-in is enabled for this deployment. Signing in scopes your workspace and "
                "guarantees cloud restore after reboot."
            )
        if diag.get("restore_at"):
            st.caption(f"Last restore: {diag['restore_at']}")
        if diag.get("cloud_app_key"):
            st.caption(f"Cloud app key: `{diag['cloud_app_key']}`")
        row_inspection = diag.get("cloud_row_inspection")
        if isinstance(row_inspection, dict) and row_inspection.get("rows"):
            st.markdown("**Cloud row inspection (active workspace)**")
            st.caption(
                f"Scope user_id: `{row_inspection.get('scope_user_id') or 'null'}` · "
                f"Selected row user_id: `{row_inspection.get('selected_row_user_id') or '—'}` · "
                f"Selected drafts: **{int(row_inspection.get('selected_draft_count') or 0)}**"
            )
            st.json(row_inspection)
        legacy_inspection = diag.get("cloud_row_inspection_legacy")
        if isinstance(legacy_inspection, dict) and legacy_inspection.get("rows"):
            st.markdown("**Legacy cloud rows (daniel + null user_id — diagnostic only)**")
            st.json(legacy_inspection)
        save_readback = session.get("_suite_last_draft_save_readback")
        if isinstance(save_readback, dict) and save_readback:
            st.markdown("**Last save readback row identity**")
            st.json(save_readback)
        room_readback = session.get("_suite_last_draft_room_readback")
        if isinstance(room_readback, dict) and room_readback:
            st.markdown("**Last draft-room pick readback row identity**")
            st.json(room_readback)
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
            try:
                from draft_library_save_trace import save_trace_checklist

                for label, status, detail in save_trace_checklist(save_diag):
                    icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "pending": "⏳"}.get(status, "•")
                    line = f"{icon} **{label}**"
                    if detail:
                        line += f" — {detail}"
                    st.markdown(line)
            except ImportError:
                pass
            st.json(save_diag)
        load_diag = session.get("_draft_library_load_diag")
        if isinstance(load_diag, dict) and load_diag:
            st.markdown("**Library load diagnostics**")
            st.markdown(
                f"Session: **{int(load_diag.get('library_load_count_session') or 0)}** drafts · "
                f"Disk: **{int(load_diag.get('library_load_count_disk') or 0)}** · "
                f"Cloud: **{int(load_diag.get('library_load_count_cloud') or 0)}** · "
                f"Restore: **{load_diag.get('restore_source') or '—'}**"
            )
            st.json(load_diag)
        restore_diag = session.get("_draft_library_restore_diag")
        if isinstance(restore_diag, dict) and restore_diag:
            st.markdown("**Restore diagnostics**")
            st.json(restore_diag)
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
            health = session.get("_suite_cloud_health_probe")
            if not isinstance(health, dict) or st.button(
                "Run Supabase state-table health check",
                key="suite_app_current_state_health_rerun",
            ):
                try:
                    from suite_app_current_state_health import probe_suite_app_current_state_health

                    health = probe_suite_app_current_state_health(scoped_app_key=str(diag.get("cloud_app_key") or ""))
                    session["_suite_cloud_health_probe"] = health
                except ImportError:
                    health = None
            if isinstance(health, dict) and health.get("configured"):
                st.markdown("**Supabase `suite_app_current_state` health**")
                rows = [
                    ("ping_ok", health.get("ping_ok")),
                    ("table_reachable", health.get("table_reachable")),
                    ("minimal_write_ok", health.get("minimal_write_ok")),
                    ("minimal_write_mode", health.get("minimal_write_mode") or "—"),
                    ("likely_cause", health.get("likely_cause") or "—"),
                ]
                for label, value in rows:
                    st.text(f"{label}: {value}")
                if session.get("_suite_last_cloud_payload_bytes") is not None:
                    st.text(f"last_save_payload_bytes: {session.get('_suite_last_cloud_payload_bytes')}")
                if health.get("user_message"):
                    st.caption(str(health["user_message"]))
                if health.get("detail"):
                    st.code(str(health["detail"])[:2000])
        elif not diag.get("cloud_enabled"):
            st.caption("Cloud storage not configured in this deployment.")


def _page_label(page_key: str, page_label_fn=None) -> str:
    if callable(page_label_fn):
        return str(page_label_fn(page_key))
    return page_key


def _page_icon(page_key: str, page_label_fn=None) -> str:
    if callable(page_label_fn):
        label = _page_label(page_key, page_label_fn)
        first = label.split(" ", 1)[0].strip()
        if first and first != page_key:
            return first
    return str(_PAGE_ICONS.get(str(page_key or ""), "") or "")


def _nav_label(page_key: str, text: str, page_label_fn=None) -> str:
    icon = _page_icon(page_key, page_label_fn)
    return f"{icon} {text}".strip()


def _fantasy_nav_button_label(page_key: str, page_label_fn=None) -> str:
    if page_key == SAVED_DRAFT_LIBRARY_PAGE:
        return _nav_label(SAVED_DRAFT_LIBRARY_PAGE, MANAGE_SAVED_DRAFTS_LABEL, page_label_fn)
    return _page_label(page_key, page_label_fn)


def _navigate_fantasy_page(session: dict[str, Any], target_page: str, *, return_page: str = "") -> bool:
    target = str(target_page or "").strip()
    if not target:
        return False
    if target == SAVED_DRAFT_LIBRARY_PAGE:
        schedule_active_context_resync(session)
        schedule_saved_draft_library_navigation(session, return_page=return_page)
        return True
    return schedule_fantasy_analysis_navigation(session, target)


def render_saved_draft_library_draft_room_navigation(
    st: Any,
    session: dict[str, Any],
    *,
    page_label_fn=None,
    key_prefix: str = "library",
) -> None:
    """Bottom navigation to Live Draft Room and Draft Room Simulator."""
    st.divider()
    st.markdown("##### Draft rooms")
    nav1, nav2 = st.columns(2)
    with nav1:
        st.button(
            _nav_label(LIVE_DRAFT_PAGE, "Go to Live Draft Room", page_label_fn),
            key=f"{key_prefix}__go_live_draft_room_btn",
            use_container_width=True,
            on_click=_on_click_navigate_to_page,
            args=(LIVE_DRAFT_PAGE, f"{key_prefix}__go_live_draft_room_btn", "go_live_draft_room"),
        )
    with nav2:
        st.button(
            _nav_label(DRAFT_SIMULATOR_PAGE, "Go to Draft Room Simulator", page_label_fn),
            key=f"{key_prefix}__go_draft_simulator_btn",
            use_container_width=True,
            on_click=_on_click_navigate_to_page,
            args=(DRAFT_SIMULATOR_PAGE, f"{key_prefix}__go_draft_simulator_btn", "go_to_draft_room_simulator"),
        )


def render_saved_active_draft_summary(st: Any, session: dict[str, Any]) -> None:
    """Saved Active Draft block — only for intentionally saved + selected library drafts."""
    try:
        from fantasy_league_context import get_active_league_context
    except ImportError:
        get_active_league_context = None  # type: ignore[assignment,misc]

    active = get_active_draft_archive(session)
    active_context = None
    if get_active_league_context is not None:
        active_context = get_active_league_context(session, respect_source_priority=False)
    st.markdown("##### Saved Active Draft")
    if not active:
        try:
            from workflow_persist_guard import DRAFT_ARCHIVE_KEY, count_draft_archives

            saved_count = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
        except ImportError:
            saved_count = 0
        if saved_count > 0:
            st.info(
                f"You have **{saved_count}** saved draft{'s' if saved_count != 1 else ''} in the library. "
                "Choose one below and click **Set Active** to drive fantasy management tools."
            )
        else:
            st.caption(
                "No saved draft selected as Active Draft. Fantasy pages can still use a "
                "**temporary / unsaved** simulator or live board when you enable a **Fantasy Source** override."
            )
        return
    context = active_context or get_league_context_for_archive(session, active)
    title = str(active.get("draft_name") or (context or {}).get("display_name") or "Saved Draft")
    team_count = league_team_count(context, active)
    st.markdown(f"**{title}**")
    st.caption(
        f"{team_count} Team{'s' if team_count != 1 else ''} · "
        f"{draft_type_display(active)} · "
        f"Updated {format_archive_modified(active)}"
    )


def render_active_draft_summary(st: Any, session: dict[str, Any]) -> None:
    """Backward-compatible alias."""
    render_saved_active_draft_summary(st, session)


def render_fantasy_page_navigation(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str,
    key_prefix: str = "fantasy_nav",
    page_label_fn=None,
) -> None:
    """Consistent fantasy workflow nav — excludes the current page."""
    page = str(active_page or "").strip()
    targets = FANTASY_NAV_TARGETS.get(page, ())
    if not targets:
        return
    purge_fantasy_nav_widget_keys(session, key_prefix=key_prefix)
    nav_error = session.pop("_fantasy_nav_error", None)
    if nav_error:
        st.warning(str(nav_error))
    cols = st.columns(len(targets))
    for col, page_key in zip(cols, targets):
        with col:
            label = _fantasy_nav_button_label(page_key, page_label_fn)
            safe_key = "".join(ch if ch.isalnum() else "_" for ch in page_key)[:48]
            widget_key = _fantasy_nav_button_widget_key(key_prefix, safe_key)
            st.button(
                label,
                key=widget_key,
                use_container_width=True,
                on_click=_on_click_navigate_fantasy_page,
                args=(page_key, page, widget_key, label),
            )


def render_fantasy_page_header(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str,
    key_prefix: str = "fantasy_nav",
    page_label_fn=None,
) -> None:
    """Fantasy workflow header: context badge, saved active draft, navigation."""
    try:
        from fantasy_context_ui import render_fantasy_workflow_page_header

        render_fantasy_workflow_page_header(
            st,
            session,
            active_page=active_page,
            key_prefix=key_prefix,
            page_label_fn=page_label_fn,
        )
    except ImportError:
        render_saved_active_draft_summary(st, session)
        render_fantasy_page_navigation(
            st,
            session,
            active_page=active_page,
            key_prefix=key_prefix,
            page_label_fn=page_label_fn,
        )


def _sync_draft_rename_to_league_context(
    session: dict[str, Any],
    draft_id: str,
    new_name: str,
) -> None:
    """Update linked league context display name when a draft is renamed."""
    entry = get_draft_archive(session, draft_id)
    if not isinstance(entry, dict):
        return
    context = get_league_context_for_archive(session, entry)
    if not isinstance(context, dict):
        return
    context["display_name"] = str(new_name or "").strip()
    upsert_league_context(session, context)


def _rename_archive_entry(
    st: Any,
    session: dict[str, Any],
    draft_id: str,
    new_name: str,
) -> bool:
    label = str(new_name or "").strip()
    if not label:
        return False
    updated = rename_draft_archive(session, draft_id, label)
    if not updated:
        return False
    _sync_draft_rename_to_league_context(session, draft_id, label)
    _clear_fantasy_caches_on_archive_change(session)
    _persist_archive(session, st, reason="draft_archive_renamed")
    return True


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


def _on_click_navigate_fantasy_page(
    target_page: str,
    return_page: str,
    button_key: str,
    button: str,
) -> None:
    """Streamlit on_click — fantasy workflow navigation with context resync."""
    import streamlit as st

    session = st.session_state
    _record_library_nav_diag(
        session,
        button=button or button_key or "fantasy_nav",
        button_key=button_key,
        target_page=target_page,
    )
    ok = _navigate_fantasy_page(session, target_page, return_page=return_page)
    if not ok:
        session["_fantasy_nav_error"] = (
            f"Could not navigate to {target_page}. Set an **Active Draft** in Saved Draft Library first."
        )


def _on_click_request_delete_draft(draft_id: str, widget_key_prefix: str = "") -> None:
    import streamlit as st

    st.session_state[_DELETE_CONFIRM_PREFIX + str(draft_id or "").strip()] = True


def _on_click_cancel_delete_draft(draft_id: str) -> None:
    import streamlit as st

    st.session_state.pop(_DELETE_CONFIRM_PREFIX + str(draft_id or "").strip(), None)


def _on_click_confirm_delete_draft(draft_id: str, widget_key_prefix: str = "") -> None:
    import streamlit as st

    session = st.session_state
    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return
    if delete_draft_archive(session, draft_id):
        session.pop(_DELETE_CONFIRM_PREFIX + draft_id, None)
        _clear_fantasy_caches_on_archive_change(session)
        _persist_archive(session, st, reason="draft_archive_deleted")
        session["_draft_delete_flash"] = "Draft deleted."
    else:
        session["_draft_delete_flash"] = "Could not delete draft."


def _on_click_waiver_wire(button_key: str, button: str) -> None:
    """Streamlit on_click — open Waiver Wire with active league context."""
    import streamlit as st

    session = st.session_state
    _record_library_nav_diag(
        session,
        button=button,
        button_key=button_key,
        target_page=FANTASY_WAIVER_PAGE,
    )
    schedule_fantasy_analysis_navigation(session, FANTASY_WAIVER_PAGE)



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
    try:
        from draft_library_save_trace import finalize_save_trace

        finalize_save_trace(
            session,
            reason=reason,
            before=before,
            after=after,
            persist_ok=persist_ok,
            entry=entry,
            probe_cloud=probe_cloud,
        )
        return
    except ImportError:
        pass
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


def _cloud_persist_reason(reason: str) -> str:
    """Route explicit Save Draft actions through the compact draft-library cloud writer."""
    base = str(reason or "").strip()
    if base.endswith("_retry"):
        base = base[:-6]
    if base in ("simulator_league_context_saved", "live_draft_league_context_saved"):
        return "draft_archive_saved"
    return reason


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

        persist_reason = _cloud_persist_reason(reason)
        ok = bool(force_save_baseball_state(st, reason=persist_reason))
    except Exception as exc:
        session["_draft_archive_persist_error"] = f"{type(exc).__name__}: {exc}"
        ok = False
    after = _workflow_counts(session)
    entry_id = str((entry or {}).get("draft_id") or "").strip()
    if entry_id and not get_draft_archive(session, entry_id):
        try:
            from workflow_persist_guard import hydrate_session_workflow_from_disk

            hydrate_session_workflow_from_disk(session, draft_id=entry_id)
        except ImportError:
            pass
    if entry_id:
        session_has_entry = bool(get_draft_archive(session, entry_id))
        if not session_has_entry:
            from draft_library_save_trace import draft_id_in_archives

            session_has_entry = draft_id_in_archives(entry_id, list_draft_archives(session))
    elif reason == "draft_archive_deleted":
        session_has_entry = int(after.get("draft_archive_count") or 0) <= int(before.get("draft_archive_count") or 0)
    else:
        session_has_entry = int(after.get("draft_archive_count") or 0) >= int(before.get("draft_archive_count") or 0) > 0
    count_increased = int(after.get("draft_archive_count") or 0) > int(before.get("draft_archive_count") or 0)
    persist_ok = bool(session_has_entry and ok) if reason != "draft_archive_deleted" else bool(ok and session_has_entry)
    try:
        from draft_library_save_trace import save_persist_mode_context

        if save_persist_mode_context(session).get("cloud_write_expected") and not session.get(
            "_suite_persist_last_save_cloud"
        ):
            persist_ok = False
    except ImportError:
        pass
    if session_has_entry and not ok:
        try:
            session.pop("_suite_autosave_fp::baseball", None)
            retry_reason = f"{_cloud_persist_reason(reason)}_retry"
            ok = bool(force_save_baseball_state(st, reason=retry_reason))
            persist_ok = persist_ok or bool(ok and get_draft_archive(session, entry_id))
        except Exception:
            pass
    if persist_ok and entry_id:
        try:
            from workflow_persist_guard import record_draft_library_readback, verify_cloud_draft_library_readback
            from suite_workspace import get_active_workspace_id, scoped_cloud_app_id

            ws = str(get_active_workspace_id(st=st))
            app_key = scoped_cloud_app_id("baseball", ws)
            readback = verify_cloud_draft_library_readback(
                "baseball",
                min_drafts=1,
                expected_draft_id=entry_id,
                workspace_id=ws,
                cloud_app_key=app_key,
                expected_draft_count=int(after.get("draft_archive_count") or 0),
                session=session,
            )
            record_draft_library_readback(session, readback)
            session["_suite_last_draft_save_readback"] = {
                "cloud_app_key": app_key,
                "workspace_id": ws,
                "scope_user_id": readback.get("scope_user_id"),
                "selected_row_user_id": readback.get("selected_row_user_id"),
                "draft_count": readback.get("draft_count"),
                "draft_ids": list(readback.get("draft_ids") or []),
                "expected_draft_count": int(after.get("draft_archive_count") or 0),
                "expected_draft_id": entry_id,
                "save_reason": reason,
            }
            if not readback.get("ok"):
                persist_ok = False
        except ImportError:
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
            LINEUP_DIAGNOSIS_CACHE_KEY,
        )

        session.pop(STANDINGS_ROSTER_CACHE_KEY, None)
        session.pop(LINEUP_SCORES_CACHE_KEY, None)
        session.pop(WAIVER_ANALYSIS_CACHE_KEY, None)
        session.pop(LINEUP_DIAGNOSIS_CACHE_KEY, None)
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


def _format_league_matchup_label(
    context: dict[str, Any] | None,
    active_entry: dict[str, Any] | None = None,
) -> str:
    """Compact league line: Donny vs Barry."""
    teams: list[str] = []
    if isinstance(context, dict):
        rosters = context.get("league_rosters") or {}
        if isinstance(rosters, dict):
            teams = [str(t).strip() for t in rosters.keys() if str(t).strip()]
        if not teams:
            teams = [str(t).strip() for t in (context.get("teams") or []) if str(t).strip()]
    my_team = str(
        (context or {}).get("my_team_name")
        or (active_entry or {}).get("team_name")
        or ""
    ).strip()
    if len(teams) >= 2:
        others = [t for t in teams if t != my_team][:3]
        if my_team and others:
            return f"{my_team} vs {' vs '.join(others)}"
        return " vs ".join(teams[:4])
    title = str((active_entry or {}).get("draft_name") or (context or {}).get("display_name") or "League")
    return title


def render_active_saved_draft_chip(
    st: Any,
    session: dict[str, Any],
    key_prefix: str = "active_draft",
    page_label_fn=None,
    active_page: str = "",
    **_unused: Any,
) -> None:
    """Fantasy workflow header — active draft summary + page navigation."""
    page = str(
        active_page
        or _KEY_PREFIX_TO_FANTASY_PAGE.get(str(key_prefix or "").strip())
        or ""
    ).strip()
    if page:
        try:
            render_fantasy_page_header(
                st,
                session,
                active_page=page,
                key_prefix=key_prefix,
                page_label_fn=page_label_fn,
            )
            return
        except TypeError:
            render_active_draft_summary(st, session)
            return
    render_active_draft_summary(st, session)


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
    team_count = archive_card_team_count(entry)
    player_count = archive_card_player_count(entry)
    if league_save and context:
        st.success(
            f"Saved **{entry.get('draft_name')}** as a **{league_context_coverage_badge(context)}** "
            f"({team_count} teams, {player_count} players on your roster). "
            "Set active for Standings and Lineup analysis."
        )
    else:
        st.success(
            f"Saved **{entry.get('draft_name')}** ({player_count} players). "
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
    entry = get_draft_archive(session, draft_id) if draft_id else None
    if not isinstance(entry, dict):
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


def schedule_analyze_completed_draft_navigation(session: dict[str, Any]) -> None:
    """Open Draft Lab with the completed live draft preloaded."""
    target = DRAFT_LAB_PAGE
    payload: dict[str, Any] = {"actions": ["push_live_draft_to_lab"]}
    try:
        import page_transfers as pg_xfer

        payload = pg_xfer.normalize_transfer_payload(
            pg_xfer.build_transfer(session, "live_to_draft_lab", {})
        )
    except ImportError:
        pass
    session["_pending_page_transfer"] = {
        "target": target,
        "source": LIVE_DRAFT_PAGE,
        "payload": payload,
        "filters": payload,
    }
    schedule_page_navigation(session, target)
    session["active_page"] = target
    session["main_sidebar_page"] = target
    session["_suite_page_user_nav"] = True
    session["_suite_nav_consumed_this_run"] = True
    session["_skip_page_restore_for"] = target
    session["_suite_nav_consumed_target"] = target
    session["draft_lab_preferred_tab"] = "Draft Board"
    session["_draft_lab_live_handoff_pending"] = True


def enforce_pending_analyze_draft_navigation(session: dict[str, Any]) -> bool:
    """Re-apply Draft Lab navigation after workspace/resume hooks (Analyze Draft)."""
    if not session.pop("_draft_analyze_nav_pending", None):
        return False
    target = DRAFT_LAB_PAGE
    session["main_sidebar_page"] = target
    session["active_page"] = target
    session["_skip_page_restore_for"] = target
    session["_suite_page_user_nav"] = True
    session["_suite_nav_consumed_this_run"] = True
    session["_suite_nav_consumed_target"] = target
    session["_navigate_to_page"] = target
    session["draft_lab_preferred_tab"] = "Draft Board"
    return True


def _on_analyze_draft_click(key_prefix: str = "live_draft_complete") -> None:
    """Streamlit on_click — preload Draft Lab, then navigate."""
    import streamlit as st

    session = st.session_state
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        session[_DRAFT_ANALYZE_UI_FLASH_KEY] = {
            "level": "error",
            "message": "No active live draft room to analyze.",
        }
        return
    try:
        from live_draft_safe_mode import is_draft_truly_complete

        draft_complete = bool(is_draft_truly_complete(room))
    except ImportError:
        draft_complete = str(room.get("status") or "").strip() == "complete"
    if not draft_complete:
        session[_DRAFT_ANALYZE_UI_FLASH_KEY] = {
            "level": "error",
            "message": "Draft must be fully complete before analysis.",
        }
        return
    try:
        from draft_lab_handoff import push_completed_live_draft_to_lab, resolve_lab_yearly_df

        push_ok = bool(
            push_completed_live_draft_to_lab(
                session,
                room,
                yearly_df=resolve_lab_yearly_df(session),
            )
        )
    except Exception as exc:
        push_ok = False
        session[_DRAFT_ANALYZE_UI_FLASH_KEY] = {
            "level": "error",
            "message": f"Could not load completed draft into Draft Lab: {exc}",
        }
        return
    if not push_ok:
        session[_DRAFT_ANALYZE_UI_FLASH_KEY] = {
            "level": "error",
            "message": "Could not load completed draft into Draft Lab — check Developer Mode diagnostics.",
        }
        return
    schedule_analyze_completed_draft_navigation(session)
    session[_DRAFT_ANALYZE_UI_FLASH_KEY] = {
        "level": "info",
        "message": "Opening Draft Lab with your completed draft…",
    }
    session["_draft_analyze_nav_pending"] = True


def _resolve_live_draft_save_team_name(room: dict[str, Any], team_name: str) -> str:
    cfg = dict(room.get("config") or {})
    resolved = str(team_name or "").strip()
    if not resolved or resolved == "—":
        resolved = str(cfg.get("user_team") or cfg.get("your_team") or "").strip()
    if not resolved or resolved == "—":
        teams = [str(t).strip() for t in (room.get("teams") or cfg.get("teams") or []) if str(t).strip()]
        resolved = teams[0] if teams else ""
    return resolved


def _execute_live_draft_save(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    draft_name: str,
    key_prefix: str,
    defer_activation: bool,
    trace_already_started: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    """Save completed live draft to session + disk/cloud. Returns (entry, context, persist_ok)."""
    if not trace_already_started:
        try:
            from draft_library_save_trace import begin_save_trace

            begin_save_trace(
                session,
                source="live_draft_room",
                reason="live_draft_league_context_saved",
                draft_name=draft_name,
            )
        except ImportError:
            pass
    counts_before = _workflow_counts(session)
    entry, context = save_live_draft_league_context(
        session,
        room,
        my_team_name=team_name,
        draft_name=draft_name,
        defer_activation=defer_activation,
        save_only=defer_activation,
    )
    if not list_draft_archives(session):
        try:
            from draft_library_save_trace import finalize_save_trace, record_save_failure_trace

            record_save_failure_trace(
                session,
                reason="live_draft_league_context_saved",
                error="Session library empty after save_live_draft_league_context",
                before=counts_before,
            )
            counts_after = _workflow_counts(session)
            finalize_save_trace(
                session,
                reason="live_draft_league_context_saved",
                before=counts_before,
                after=counts_after,
                persist_ok=False,
                entry=entry if isinstance(entry, dict) else None,
                probe_cloud=False,
            )
        except ImportError:
            pass
        return None, None, False
    _clear_fantasy_caches_on_archive_change(session)
    persist_ok = _persist_archive(session, st, reason="live_draft_league_context_saved", entry=entry)
    if isinstance(session.get("_draft_library_save_diag"), dict):
        session["_draft_library_save_diag"]["counts_before_explicit"] = counts_before
    if persist_ok:
        try:
            from baseball_archive_activity import log_saved_draft_archived

            log_saved_draft_archived(entry, session=session)
        except ImportError:
            pass
        stash_league_context_save_flash(
            session,
            entry,
            context=context,
            league_save=True,
        )
    return entry, context, persist_ok


def _execute_live_draft_save_click(
    st: Any,
    session: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str,
    defer_activation: bool,
) -> None:
    """Streamlit on_click body — record save trace immediately, then persist."""
    session["_draft_save_trace_expand"] = True
    record_save_failure_trace = None
    finalize_save_trace = None
    record_save_button_click = None
    try:
        from draft_library_save_trace import (
            finalize_save_trace as _finalize_save_trace,
            record_save_button_click as _record_save_button_click,
            record_save_failure_trace as _record_save_failure_trace,
        )

        record_save_failure_trace = _record_save_failure_trace
        finalize_save_trace = _finalize_save_trace
        record_save_button_click = _record_save_button_click
    except ImportError:
        pass

    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        try:
            if record_save_button_click is not None:
                record_save_button_click(
                    session,
                    source="live_draft_room",
                    team_name=team_name,
                    key_prefix=key_prefix,
                    reason="live_draft_league_context_saved",
                )
            if record_save_failure_trace is not None:
                record_save_failure_trace(
                    session,
                    reason="live_draft_league_context_saved",
                    error="No live_draft_room in session",
                )
        except Exception:
            pass
        _set_draft_save_ui_flash(session, level="error", message="No active live draft room to save.")
        return

    save_team = _resolve_live_draft_save_team_name(room, team_name)
    draft_name = str(session.get(f"{key_prefix}_name_input") or "").strip()
    try:
        if record_save_button_click is not None:
            record_save_button_click(
                session,
                source="live_draft_room",
                team_name=save_team,
                key_prefix=key_prefix,
                reason="live_draft_league_context_saved",
            )
    except Exception:
        pass

    if not save_team:
        try:
            if record_save_failure_trace is not None:
                record_save_failure_trace(
                    session,
                    reason="live_draft_league_context_saved",
                    error="Could not determine fantasy team for save",
                )
        except Exception:
            pass
        _set_draft_save_ui_flash(
            session,
            level="error",
            message="Could not determine your fantasy team for saving this draft.",
        )
        return

    counts_before = _workflow_counts(session)
    try:
        entry, context, persist_ok = _execute_live_draft_save(
            st,
            session,
            room,
            team_name=save_team,
            draft_name=draft_name,
            key_prefix=key_prefix,
            defer_activation=defer_activation,
            trace_already_started=True,
        )
        if entry is None:
            _set_draft_save_ui_flash(
                session,
                level="error",
                message="Save did not update Saved Draft Library — check Save diagnostics below.",
            )
        elif not persist_ok:
            _set_draft_save_ui_flash(
                session,
                level="error",
                message=(
                    "Saved to this session, but cloud/disk persist failed. "
                    "Review **Save diagnostics** below before refreshing."
                ),
            )
        elif defer_activation:
            st.toast(f"Saved draft: {entry.get('draft_name', 'Saved Draft')}")
        else:
            st.toast(f"Active draft: {entry.get('draft_name', 'Saved Draft')}")
    except Exception as exc:
        try:
            if record_save_failure_trace is not None:
                record_save_failure_trace(
                    session,
                    reason="live_draft_league_context_saved",
                    error=f"{type(exc).__name__}: {exc}",
                    before=counts_before,
                )
            if finalize_save_trace is not None:
                finalize_save_trace(
                    session,
                    reason="live_draft_league_context_saved",
                    before=counts_before,
                    after=_workflow_counts(session),
                    persist_ok=False,
                    probe_cloud=False,
                )
        except Exception:
            pass
        _set_draft_save_ui_flash(session, level="error", message=f"Could not save draft: {exc}")


def _on_live_draft_save_click(
    team_name: str = "",
    key_prefix: str = "live_draft_complete",
    defer_activation: bool = True,
) -> None:
    import streamlit as st

    _execute_live_draft_save_click(
        st,
        st.session_state,
        team_name=str(team_name or ""),
        key_prefix=str(key_prefix or "live_draft_complete"),
        defer_activation=bool(defer_activation),
    )


def render_live_draft_completion_panel(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str = "live_draft_complete",
    page_label_fn=None,
    export_frames_fn=None,
    csv_export_fn=None,
    excel_export_fn=None,
) -> None:
    """Post-final-pick workflow: Draft Name, Save, Analyze, Set Active, Export."""
    cfg = dict(room.get("config") or {})
    save_team = _resolve_live_draft_save_team_name(room, team_name)
    if not save_team:
        st.warning("Could not determine your fantasy team for saving this draft.")
        return

    expand_save = bool(session.pop("_draft_save_trace_expand", False))
    flash = _pop_draft_save_ui_flash(session)
    if flash and flash.get("message"):
        if flash.get("level") == "error":
            st.error(str(flash["message"]))
        else:
            st.info(str(flash["message"]))
    analyze_flash = session.pop(_DRAFT_ANALYZE_UI_FLASH_KEY, None)
    if isinstance(analyze_flash, dict) and analyze_flash.get("message"):
        if analyze_flash.get("level") == "error":
            st.error(str(analyze_flash["message"]))
        else:
            st.info(str(analyze_flash["message"]))
    default_name = f"{cfg.get('league_name', 'Live Draft')} — {' vs '.join(str(t) for t in (room.get('teams') or [])[:4] if str(t).strip()) or save_team}"
    draft_name = st.text_input(
        "Draft Name",
        value=default_name.strip(" —"),
        key=f"{key_prefix}_name_input",
    )
    st.caption(
        "Save the full draft board, all team rosters, settings, and player grades to **Saved Drafts**."
    )

    save_col, analyze_col, active_col, export_col = st.columns(4)
    with save_col:
        st.button(
            "Save Draft",
            key=f"{key_prefix}_save_btn",
            type="primary",
            use_container_width=True,
            on_click=_on_live_draft_save_click,
            kwargs={
                "team_name": save_team,
                "key_prefix": key_prefix,
                "defer_activation": True,
            },
        )
    with analyze_col:
        st.button(
            "Analyze Draft",
            key=f"{key_prefix}_analyze_btn",
            use_container_width=True,
            on_click=_on_analyze_draft_click,
            kwargs={"key_prefix": key_prefix},
        )
    with active_col:
        st.button(
            "Set Active Draft",
            key=f"{key_prefix}_active_btn",
            use_container_width=True,
            on_click=_on_live_draft_save_click,
            kwargs={
                "team_name": save_team,
                "key_prefix": key_prefix,
                "defer_activation": False,
            },
        )
    with export_col:
        export_clicked = st.button("Export Draft", key=f"{key_prefix}_export_btn", use_container_width=True)

    if export_clicked:
        session[f"{key_prefix}_export_open"] = True

    if session.pop(f"{key_prefix}_export_open", False) or export_clicked:
        if callable(export_frames_fn):
            frames = export_frames_fn(room)
            ex1, ex2 = st.columns(2)
            with ex1:
                if callable(csv_export_fn):
                    st.download_button(
                        "Download CSV",
                        data=csv_export_fn(frames),
                        file_name="live_draft_export.csv",
                        mime="text/csv",
                        key=f"{key_prefix}_csv_dl",
                        use_container_width=True,
                    )
            with ex2:
                if callable(excel_export_fn):
                    try:
                        st.download_button(
                            "Download Excel",
                            data=excel_export_fn(frames),
                            file_name="live_draft_export.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"{key_prefix}_xlsx_dl",
                            use_container_width=True,
                        )
                    except Exception as exc:
                        st.caption(f"Excel export unavailable ({exc}).")

    with st.expander("Save diagnostics", expanded=expand_save):
        try:
            from draft_library_save_trace import render_save_trace_inline

            render_save_trace_inline(st, session, source="Live Draft Room")
        except ImportError:
            pass


def render_save_live_draft_team(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    key_prefix: str = "live_draft_archive",
    page_label_fn=None,
) -> None:
    """Legacy save expander — prefer render_live_draft_completion_panel on the completion screen."""
    save_team = _resolve_live_draft_save_team_name(room, team_name)
    if not save_team:
        return
    render_live_draft_completion_panel(
        st,
        session,
        room,
        team_name=save_team,
        key_prefix=key_prefix,
        page_label_fn=page_label_fn,
    )


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
    expand_save = bool(session.pop("_draft_save_trace_expand", False))
    with st.expander("Set Active Draft", expanded=expand_save):
        flash = _pop_draft_save_ui_flash(session)
        if flash and flash.get("message"):
            if flash.get("level") == "error":
                st.error(str(flash["message"]))
            else:
                st.info(str(flash["message"]))
        st.caption(
            "Saves the full mock draft as your **Active Draft** (all teams), "
            "ready for Standings, Lineup, and Waiver workflows."
        )
        st.text_input(
            "Draft name",
            value=f"Simulator — {team_name}",
            key=f"{key_prefix}_name_input",
        )
        st.button(
            "Set Active Draft",
            key=f"{key_prefix}_save_league_btn",
            type="primary",
            on_click=_on_simulator_save_click,
            kwargs={"team_name": team_name, "key_prefix": key_prefix, "save_only": False},
        )
        try:
            from draft_library_save_trace import render_save_trace_inline

            render_save_trace_inline(
                st,
                session,
                source="Draft Room Simulator · Rosters tab",
            )
        except ImportError:
            pass


def _saved_draft_card_html(
    entry: dict[str, Any],
    *,
    is_active: bool,
    player_n: int,
    team_n: int,
) -> str:
    title = str(entry.get("draft_name") or "Saved Draft")
    team = str(entry.get("team_name") or "—")
    modified = format_archive_modified(entry)
    card_class = "ld-archive-card ld-archive-active" if is_active else "ld-archive-card"
    active_badge = (
        '<span class="ld-archive-badge ld-archive-badge-active">ACTIVE</span> '
        if is_active
        else ""
    )
    type_badge = _draft_type_badge_html(entry)
    return (
        f'<div class="{card_class}">{active_badge}{type_badge}'
        f"<strong>{title}</strong><br>"
        f"<span style='opacity:0.9'>{team}</span><br>"
        f"<span style='opacity:0.85'>{team_n} team{'s' if team_n != 1 else ''} · "
        f"{player_n} player{'s' if player_n != 1 else ''} · Updated {modified}</span></div>"
    )


def _activate_archive_entry(st: Any, session: dict[str, Any], draft_id: str) -> None:
    loaded_entry, loaded_context = activate_archive_league_context(
        session,
        draft_id,
        defer_activation=True,
    )
    if not loaded_entry:
        return
    try:
        from draft_library_save_trace import record_restore_trace

        record_restore_trace(
            session,
            draft_id=draft_id,
            entry=loaded_entry,
            context=loaded_context,
            action="activate",
        )
    except ImportError:
        pass
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
            f"Active draft: {loaded_context.get('display_name', loaded_entry.get('draft_name'))}"
        )
    st.rerun()


def _render_active_draft_section(
    st: Any,
    session: dict[str, Any],
    *,
    active: dict[str, Any] | None,
    active_context: dict[str, Any] | None,
    page_label_fn=None,
) -> None:
    st.markdown("##### Active Draft")
    if not active:
        st.info("No active draft yet. Choose a saved draft below and click **Set Active**.")
        return

    context = active_context or get_league_context_for_archive(session, active)
    title = str(active.get("draft_name") or "Saved Draft")
    team_count = league_team_count(context, active)
    player_n = archive_my_team_player_count(active, context=context)
    league_line = _format_league_matchup_label(context, active)
    st.markdown(f"**{title}** — {league_line}")
    st.caption(
        f"{draft_type_display(active)} | {team_count} Teams | {player_n} Players · "
        f"Updated {format_archive_modified(active)}"
    )
    tool1, tool2, tool3, clear_col = st.columns([1, 1, 1, 1])
    with tool1:
        if st.button(
            _nav_label(FANTASY_STANDINGS_PAGE, "Fantasy Standings Tracker", page_label_fn),
            key="library_active_standings",
            use_container_width=True,
        ):
            if schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE):
                st.rerun()
    with tool2:
        if st.button(
            _nav_label(FANTASY_LINEUP_PAGE, "Fantasy Lineup Assistant", page_label_fn),
            key="library_active_lineup",
            use_container_width=True,
        ):
            if schedule_fantasy_analysis_navigation(session, FANTASY_LINEUP_PAGE):
                st.rerun()
    with tool3:
        if st.button(
            _nav_label(FANTASY_WAIVER_PAGE, "Waiver Wire / Add-Drop Center", page_label_fn),
            key="library_active_waiver",
            use_container_width=True,
        ):
            if schedule_fantasy_analysis_navigation(session, FANTASY_WAIVER_PAGE):
                st.rerun()
    with clear_col:
        if st.button("Clear Active", key="library_clear_active", use_container_width=True):
            clear_active_draft_archive(session)
            clear_active_league_context(session)
            _clear_fantasy_caches_on_archive_change(session)
            _persist_archive(session, st, reason="draft_archive_cleared")
            st.rerun()

    draft_id = str(active.get("draft_id") or "").strip()
    if draft_id:
        st.markdown("**Manage this draft**")
        _render_archive_manage_actions(
            st,
            session,
            active,
            draft_id=draft_id,
            is_active=True,
            widget_key_prefix="library_active",
        )


def _render_archive_rename_delete_confirm(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    draft_id: str,
    *,
    widget_key_prefix: str = "archive",
) -> None:
    if session.get(_RENAME_CONFIRM_PREFIX + draft_id):
        current_name = str(entry.get("draft_name") or "Saved Draft")
        new_name = st.text_input(
            "New draft name",
            value=current_name,
            key=f"{widget_key_prefix}_rename_input_{draft_id}",
        )
        rename_col, cancel_col = st.columns(2)
        with rename_col:
            if st.button("Save rename", key=f"{widget_key_prefix}_rename_confirm_{draft_id}", type="primary"):
                if _rename_archive_entry(st, session, draft_id, new_name):
                    session.pop(_RENAME_CONFIRM_PREFIX + draft_id, None)
                    st.toast(f"Renamed draft to: {new_name.strip()}")
                    st.rerun()
                else:
                    st.error("Could not rename draft — name cannot be empty.")
        with cancel_col:
            if st.button("Cancel rename", key=f"{widget_key_prefix}_rename_cancel_{draft_id}"):
                session.pop(_RENAME_CONFIRM_PREFIX + draft_id, None)
                st.rerun()

    if session.get(_DELETE_CONFIRM_PREFIX + draft_id):
        st.warning(f"Delete **{entry.get('draft_name')}**? Other saved drafts will be kept.")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            st.button(
                "Confirm delete",
                key=f"{widget_key_prefix}_del_confirm_{draft_id}",
                type="primary",
                on_click=_on_click_confirm_delete_draft,
                args=(draft_id, widget_key_prefix),
            )
        with cancel_col:
            st.button(
                "Cancel",
                key=f"{widget_key_prefix}_del_cancel_{draft_id}",
                on_click=_on_click_cancel_delete_draft,
                args=(draft_id,),
            )


def _render_archive_manage_actions(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    draft_id: str,
    is_active: bool,
    widget_key_prefix: str = "archive",
) -> None:
    if is_active:
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button(
                "Rename Draft",
                key=f"{widget_key_prefix}_rename_{draft_id}",
                use_container_width=True,
            ):
                session[_RENAME_CONFIRM_PREFIX + draft_id] = True
                st.rerun()
        with btn2:
            st.button(
                "Delete",
                key=f"{widget_key_prefix}_del_{draft_id}",
                use_container_width=True,
                on_click=_on_click_request_delete_draft,
                args=(draft_id, widget_key_prefix),
            )
    else:
        btn1, btn2, btn3 = st.columns(3)
        with btn1:
            if st.button(
                "Set Active",
                key=f"{widget_key_prefix}_set_active_{draft_id}",
                type="primary",
                use_container_width=True,
            ):
                _activate_archive_entry(st, session, draft_id)
        with btn2:
            if st.button(
                "Rename Draft",
                key=f"{widget_key_prefix}_rename_{draft_id}",
                use_container_width=True,
            ):
                session[_RENAME_CONFIRM_PREFIX + draft_id] = True
                st.rerun()
        with btn3:
            st.button(
                "Delete",
                key=f"{widget_key_prefix}_del_{draft_id}",
                use_container_width=True,
                on_click=_on_click_request_delete_draft,
                args=(draft_id, widget_key_prefix),
            )

    _render_archive_rename_delete_confirm(
        st,
        session,
        entry,
        draft_id,
        widget_key_prefix=widget_key_prefix,
    )


def _render_fantasy_sync_section(st: Any, session: dict[str, Any]) -> None:
    try:
        from fantasy_context_ui import render_fantasy_context_sync_control

        with st.container(border=True):
            render_fantasy_context_sync_control(st, session)
    except ImportError:
        pass


def _render_archive_actions(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    active_id: str,
    active_context_id: str,
    page_label_fn=None,
) -> None:
    draft_id = str(entry.get("draft_id") or "")
    if not draft_id:
        return
    context = get_league_context_for_archive(session, entry)
    league_context_id = str((context or {}).get("league_context_id") or entry.get("league_context_id") or "").strip()
    is_active = draft_id == active_id and (
        not active_context_id or not league_context_id or league_context_id == active_context_id
    )
    _render_archive_manage_actions(
        st,
        session,
        entry,
        draft_id=draft_id,
        is_active=is_active,
        widget_key_prefix=f"archive_list_{draft_id[:12]}",
    )


def render_saved_draft_library_page(st: Any, session: dict[str, Any], *, page_label_fn=None) -> None:
    """Dedicated management page for all saved draft teams."""
    try:
        from page_perf_phases import session_perf_phase

        perf_ctx = session_perf_phase(session, "saved_draft_library_load")
    except ImportError:
        from contextlib import nullcontext

        perf_ctx = nullcontext()
    with perf_ctx:
        try:
            from draft_library_save_trace import record_library_load_trace

            record_library_load_trace(session)
        except ImportError:
            pass
        _render_saved_draft_library_page_body(st, session, page_label_fn=page_label_fn)


def _render_saved_draft_library_page_body(st: Any, session: dict[str, Any], *, page_label_fn=None) -> None:
    delete_flash = session.pop("_draft_delete_flash", None)
    if delete_flash:
        st.success(str(delete_flash))
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

    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT, format_deploy_caption

        build_line = format_deploy_caption() or f"Build `{GIT_COMMIT_SHORT}`"
        st.caption(f"Library UI · {build_line}")
    except ImportError:
        pass

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
        .ld-archive-badge-active { background: #2ecc71; color: #1a1a1a; }
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
        "Only **intentionally saved drafts** appear here. "
        "Set one **Active Draft** (a saved draft you select) for Standings, Lineup, and Waiver Wire. "
        "Unsaved simulator or live boards stay in their workspace pages — use **Fantasy Context Source** toggles to point at them temporarily."
    )

    render_persistence_probe_panel(st, session)

    try:
        from fantasy_league_invite_ui import render_commissioner_invite_panel, render_pending_league_invites

        render_pending_league_invites(st, session)
        render_commissioner_invite_panel(st, session)
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

    _render_active_draft_section(
        st,
        session,
        active=active,
        active_context=active_context,
        page_label_fn=page_label_fn,
    )
    try:
        from fantasy_league_team_claim_ui import render_active_league_team_claim

        render_active_league_team_claim(st, session, key_prefix="library_team_claim")
    except ImportError:
        pass
    st.divider()
    _render_fantasy_sync_section(st, session)
    st.divider()
    _render_persistence_diagnostics(st, session)

    st.markdown("##### Saved Drafts")
    st.metric("Saved drafts", len(archives))

    if not archives:
        try:
            from workflow_persist_guard import build_saved_draft_library_diagnostics

            _empty_diag = build_saved_draft_library_diagnostics(session)
            _session_n = int(_empty_diag.get("draft_archive_count") or 0)
            _cloud_active = int(_empty_diag.get("cloud_saved_draft_count_active") or 0)
            _cloud_owned = int(_empty_diag.get("cloud_saved_draft_count_owned") or 0)
            _cloud_legacy = int(_empty_diag.get("cloud_saved_draft_count_legacy") or 0)
            _disk_n = int(_empty_diag.get("disk_saved_draft_count") or 0)
            _cloud_any = max(_cloud_active, _cloud_owned, _cloud_legacy)
            if _cloud_any > 0 and _session_n == 0:
                st.error(
                    "Saved drafts exist in cloud storage but were **not restored into this session**. "
                    "Open **Persistence diagnostics** below for workspace / account details. "
                    "This is usually a restore-path issue (wrong workspace key or user_id scope), "
                    "not lost data."
                )
            elif _disk_n > 0 and _session_n == 0:
                st.warning(
                    f"Disk has **{_disk_n}** saved draft(s) but the session loaded **0**. "
                    "Cloud-first restore may have picked an empty cloud row — check Persistence diagnostics."
                )
        except ImportError:
            pass
        st.info(
            "No saved drafts yet. Finish a **Live Draft Room** or **Draft Room Simulator** draft, "
            "then save your draft from the draft room."
        )
        render_saved_draft_library_draft_room_navigation(
            st,
            session,
            page_label_fn=page_label_fn,
            key_prefix="library_empty",
        )
        return

    for entry in archives:
        draft_id = str(entry.get("draft_id") or "")
        context = get_league_context_for_archive(session, entry)
        league_context_id = str((context or {}).get("league_context_id") or entry.get("league_context_id") or "")
        is_active = draft_id == active_id and (
            not active_context_id or not league_context_id or league_context_id == active_context_id
        )
        player_n = archive_card_player_count(entry)
        team_n = archive_card_team_count(entry)
        st.markdown(
            _saved_draft_card_html(entry, is_active=is_active, player_n=player_n, team_n=team_n),
            unsafe_allow_html=True,
        )
        if is_active:
            st.caption("Active draft — use **Manage this draft** in the **Active Draft** section above.")
        else:
            _render_archive_actions(
                st,
                session,
                entry,
                active_id=active_id,
                active_context_id=active_context_id,
                page_label_fn=page_label_fn,
            )

    render_saved_draft_library_draft_room_navigation(
        st,
        session,
        page_label_fn=page_label_fn,
        key_prefix="library_bottom",
    )
