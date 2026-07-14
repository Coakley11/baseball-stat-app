"""Saved Draft Library UI — browse, manage, and activate saved draft teams."""

from __future__ import annotations

import time
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
    resolve_draft_type_display,
)
from draft_import_pipeline import board_should_save_as_imported_league
from draft_archive_visibility import (
    is_saved_draft_visible_to_session,
    list_visible_draft_archives,
    prune_invisible_shared_league_state,
)
from fantasy_league_context import (
    activate_archive_league_context,
    archive_my_team_player_count,
    archive_card_player_count,
    archive_card_team_count,
    clear_active_league_context,
    get_active_league_context,
    get_league_context,
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
TRADE_CENTER_PAGE = "Trade Center"
LIVE_DRAFT_PAGE = "Live Draft Room"
DRAFT_LAB_PAGE = "Draft Lab / Simulation"
DRAFT_SIMULATOR_PAGE = "Draft Room Simulator"
SHARED_CONFIRM_OPEN_KEY = "_live_draft_shared_league_confirm_open"
SHARED_LEAGUE_CONFIRM_REQUEST_KEY = "_live_draft_shared_league_confirm_request"
SHARED_LEAGUE_CREATE_REQUEST_KEY = "_live_draft_shared_league_create_request"
SHARED_LEAGUE_CREATE_COMPLETED_KEY = "_live_draft_shared_league_create_completed"
SHARED_LEAGUE_CREATE_PROCESSING_KEY = "_live_draft_shared_league_create_processing"
SHARED_LEAGUE_DIAG_KEY = "_live_draft_shared_league_diag"
SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY = "_live_draft_shared_league_open_callback_count"
SHARED_LEAGUE_CONFIRM_CALLBACK_COUNT_KEY = "_live_draft_shared_league_confirm_callback_count"
SHARED_LEAGUE_CREATE_LOCK_STALE_SECONDS = 120
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
    TRADE_CENTER_PAGE: "🔁",
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
        if board_should_save_as_imported_league(session, board_df):
            from fantasy_league_context import save_imported_league_context

            entry, context = save_imported_league_context(
                session,
                board_df,
                my_team_name=team_name,
                draft_name=draft_name,
                league_name=draft_name,
                config=dict(session.get("draft_shared_settings") or {}),
                defer_activation=not save_only,
                save_only=save_only,
                assign_team=True,
            )
            save_reason = "imported_league_context_saved"
        else:
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
            save_reason = "simulator_league_context_saved"
        counts_after_save = _workflow_counts(session)
        if not list_draft_archives(session):
            try:
                if record_save_failure_trace is not None:
                    record_save_failure_trace(
                        session,
                        reason=save_reason,
                        error="Session library empty after league context save",
                        before=counts_before,
                    )
                if finalize_save_trace is not None:
                    finalize_save_trace(
                        session,
                        reason=save_reason,
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
        persist_ok = _persist_archive(session, st, reason=save_reason, entry=entry)
        if isinstance(session.get("_draft_library_save_diag"), dict):
            session["_draft_library_save_diag"]["counts_before_explicit"] = counts_before
        if not persist_ok:
            _set_draft_save_ui_flash(
                session,
                level="error",
                message="Couldn't save changes. Try again.",
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
                    reason=locals().get("save_reason", "simulator_league_context_saved"),
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


def render_persistence_probe_panel(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    """Post-reboot probe: account, workspace, counts, restore verdict (Developer Mode)."""
    try:
        from page_diagnostics import inline_diagnostics_enabled
    except ImportError:
        inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
    if not developer_mode or not inline_diagnostics_enabled(developer_mode):
        return
    try:
        from workflow_persist_guard import build_persistence_probe_panel
    except ImportError:
        return

    probe = build_persistence_probe_panel(session, st=st)
    verdict = str(probe.get("persistence_verdict") or "")
    if verdict == "B_restore_failed":
        st.error("**Saved Draft Persistence Probe** — restore failed; storage may still have your drafts.")
    elif verdict == "A_persistence_failed_or_never_saved":
        st.warning("**Saved Draft Persistence Probe** — no durable saved drafts found in cloud or disk.")
    else:
        st.info("**Saved Draft Persistence Probe** — use after reboot to confirm account, workspace, and restore.")

    deploy_commit = str(probe.get("deploy_commit") or "unknown")
    st.caption(f"Deploy commit: `{deploy_commit}` (expect `51b46cc` or newer for migration scan)")

    if probe.get("auth_signed_out_warning"):
        st.warning(str(probe["auth_signed_out_warning"]))

    if probe.get("auth_last_login_error"):
        st.warning(f"**Last login error:** `{probe['auth_last_login_error']}`")
    if probe.get("auth_last_restore_error"):
        st.warning(f"**Last auth restore error:** `{probe['auth_last_restore_error']}`")
    if probe.get("auth_enabled"):
        auth_bits = [
            f"session flag: {'yes' if probe.get('auth_session_flag') else 'no'}",
            f"complete: {'yes' if probe.get('auth_session_complete') else 'no'}",
            f"tokens: {'yes' if probe.get('auth_tokens_present') else 'no'}",
        ]
        browser = probe.get("auth_browser_storage") if isinstance(probe.get("auth_browser_storage"), dict) else {}
        if browser:
            auth_bits.append(
                f"browser sid: {'yes' if browser.get('session_id_present') else 'no'}"
            )
        st.markdown("**Auth session:** " + " · ".join(auth_bits))

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**Signed in?** {probe.get('signed_in_label') or '—'}")
        if probe.get("auth_scope_label"):
            st.caption(probe["auth_scope_label"])
        st.markdown(f"**Account email:** {probe.get('account_email') or '—'}")
        st.markdown(f"**Cloud user ID:** `{probe.get('user_id') or '—'}`")
        if probe.get("cloud_identity_mismatch"):
            st.error(
                "Cloud identity mismatch — the session cloud row id does not match this account's "
                "suite_users row. Sign out, hard refresh, and sign in again before invite/trade testing."
            )
        st.markdown(f"**Workspace ID:** `{probe.get('workspace_id') or '—'}`")
        st.markdown(f"**Owned workspace ID:** `{probe.get('owned_workspace_id') or '—'}`")
        st.markdown(f"**Account scope (external id):** `{probe.get('account_external_id') or '—'}`")
        _allowed = probe.get("allowed_workspaces") or ()
        if _allowed:
            st.caption(f"Allowed workspaces: {', '.join(f'`{w}`' for w in _allowed)}")
        st.markdown(f"**Cloud app key:** `{probe.get('cloud_app_key') or '—'}`")
        try:
            from live_draft_navigation import collect_simulator_resume_diagnostics

            resume = collect_simulator_resume_diagnostics(session)
            st.markdown("**Draft resume**")
            st.caption(
                f"account=`{resume.get('current_account') or '—'}` · "
                f"workspace=`{resume.get('current_workspace') or '—'}` · "
                f"source=`{resume.get('sidebar_source_selected') or resume.get('resume_source_kind') or '—'}` · "
                f"pri=`{resume.get('sidebar_priority_reason') or '—'}` · "
                f"sim_owner=`{resume.get('simulator_board_owner_external_id') or '—'}`/"
                f"`{resume.get('simulator_board_owner_workspace_id') or '—'}` · "
                f"sim_ok=`{resume.get('simulator_board_owner_verified')}` · "
                f"sim_reject=`{resume.get('simulator_board_rejected_reason') or '—'}` · "
                f"shared_code=`{resume.get('active_shared_room_code') or '—'}` · "
                f"shared_room=`{resume.get('shared_membership_room_id') or '—'}` · "
                f"shared_team=`{resume.get('shared_membership_team') or resume.get('active_shared_room_team') or '—'}` · "
                f"hydrated=`{resume.get('shared_room_hydrated')}` · "
                f"discard=`{resume.get('stale_resume_discarded_reason') or '—'}`"
            )
        except ImportError:
            pass
    with col_b:
        st.markdown(f"**Session draft count:** {int(probe.get('session_draft_count') or 0)}")
        st.markdown(f"**Cloud draft count:** {int(probe.get('cloud_draft_count') or 0)}")
        st.markdown(f"**Disk draft count:** {int(probe.get('disk_draft_count') or 0)}")
        st.markdown(f"**Active draft ID:** `{probe.get('active_draft_id') or '—'}`")
        st.markdown(f"**Active draft name:** {probe.get('active_draft_name') or '—'}")
        st.markdown(
            f"**Active restore source:** `{probe.get('active_restore_source') or '—'}` · "
            f"**reason:** `{probe.get('active_restore_reason') or '—'}`"
        )
        st.caption(
            f"Cloud active id: `{probe.get('cloud_active_draft_id') or '—'}` · "
            f"Disk active id: `{probe.get('disk_active_draft_id') or '—'}`"
        )
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
    wb_trace = probe.get("migration_writeback_trace")
    if probe.get("migration_writeback_attempted") or (
        isinstance(wb_trace, dict) and wb_trace.get("skipped")
    ):
        wb_ok = probe.get("migration_writeback_ok")
        wb_readback = int(
            (wb_trace or {}).get("cloud_readback_count")
            or probe.get("cloud_write_readback_count")
            or 0
        )
        wb_skipped = str((wb_trace or {}).get("skipped") or "")
        st.markdown(
            f"**Auth migration writeback:** "
            f"attempted **{'yes' if probe.get('migration_writeback_attempted') else 'no'}** · "
            f"ok **{'yes' if wb_ok else 'no'}** · "
            f"readback **{wb_readback}**"
            + (f" · skipped `{wb_skipped}`" if wb_skipped and not probe.get("migration_writeback_attempted") else "")
        )
        if isinstance(wb_trace, dict) and wb_trace.get("cloud_readback_error"):
            st.caption(f"Migration writeback error: `{wb_trace['cloud_readback_error']}`")
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

    migration_n = int(probe.get("migration_recoverable_draft_count") or 0)
    migration_sources = probe.get("migration_sources") or []
    st.markdown(
        f"**Migration scan:** {migration_n} recoverable draft(s) across {len(migration_sources)} source(s)"
    )
    best = probe.get("migration_best_source")
    if isinstance(best, dict) and int(best.get("draft_count") or 0) > 0:
        st.caption(
            f"Best source: **{best.get('source_type')}** · "
            f"key `{best.get('cloud_app_key') or best.get('path') or '—'}` · "
            f"user_id `{best.get('user_id') or '—'}` · "
            f"drafts **{int(best.get('draft_count') or 0)}**"
        )
    elif migration_n <= 0:
        st.caption("No recoverable drafts found across scanned cloud user_ids and disk paths.")
    rich_sources = [
        s for s in migration_sources
        if isinstance(s, dict) and int(s.get("draft_count") or 0) > 0
    ]
    if rich_sources:
        with st.expander("Migration sources with drafts", expanded=migration_n > 0 and int(probe.get("session_draft_count") or 0) == 0):
            st.json(rich_sources)
    elif migration_sources:
        with st.expander("Migration scan sources (all checked)", expanded=migration_n <= 0):
            st.json(migration_sources)
    historical_users = probe.get("historical_suite_users") or []
    if historical_users:
        with st.expander("Historical suite_users rows (diagnostic)", expanded=False):
            st.json(historical_users)

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


def _render_persistence_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    try:
        from page_diagnostics import inline_diagnostics_enabled
    except ImportError:
        inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
    if not developer_mode or not inline_diagnostics_enabled(developer_mode):
        return
    try:
        from suite_workspace import can_show_developer_tools
    except ImportError:
        return
    if not can_show_developer_tools(st=st):
        return
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
    return f"{icon} {text}".strip() if icon else text


def _saved_archive_is_active(
    session: dict[str, Any],
    *,
    draft_id: str,
    context_id: str = "",
) -> bool:
    draft_id = str(draft_id or "").strip()
    context_id = str(context_id or "").strip()
    active = get_active_draft_archive(session)
    if not active or str(active.get("draft_id") or "").strip() != draft_id:
        return False
    if not context_id:
        return True
    active_context = get_active_league_context(session, respect_source_priority=False) or {}
    active_context_id = str(active_context.get("league_context_id") or "").strip()
    return not active_context_id or active_context_id == context_id


def _archive_card_is_real_league(entry: dict[str, Any], context: dict[str, Any] | None) -> bool:
    try:
        from fantasy_context_terminology import is_league_context

        return bool(is_league_context(context, entry))
    except ImportError:
        return str((context or {}).get("context_type") or "") == "real_league"


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
    if session.get("_suite_active_draft_restore_prompt"):
        st.warning(
            "Saved drafts were restored after sign-in/reboot, but no Active Draft was persisted. "
            "Choose a library card below and click **Set Active**."
        )
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
    focus_draft_id: str = "",
) -> None:
    """Navigate to Saved Draft Library; remember source page for return."""
    source = str(return_page or session.get("active_page") or "").strip()
    if source and source != SAVED_DRAFT_LIBRARY_PAGE:
        session[SAVED_DRAFT_LIBRARY_RETURN_PAGE_KEY] = source
    focus = str(focus_draft_id or "").strip()
    if focus:
        session["_saved_draft_library_focus_draft_id"] = focus
    schedule_page_navigation(session, SAVED_DRAFT_LIBRARY_PAGE)


def _on_click_open_saved_draft_library_focus(
    draft_id: str = "",
    return_page: str = "",
    button_key: str = "",
    button: str = "",
) -> None:
    import streamlit as st

    session = st.session_state
    did = str(draft_id or "").strip()
    _record_library_nav_diag(
        session,
        button=button or "open_saved_draft_library_focus",
        button_key=button_key,
        target_page=SAVED_DRAFT_LIBRARY_PAGE,
        extra={"focus_draft_id": did},
    )
    schedule_saved_draft_library_navigation(
        session,
        return_page=return_page or str(session.get("active_page") or ""),
        focus_draft_id=did,
    )


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
    if base in (
        "simulator_league_context_saved",
        "live_draft_league_context_saved",
        "imported_league_context_saved",
    ):
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


def _draft_type_badge_html(
    entry: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    label = (
        resolve_draft_type_display(session, entry, context=context)
        if isinstance(session, dict)
        else draft_type_display(entry)
    )
    if label == "Live Draft":
        css = "ld-archive-badge-live"
    elif label == "Imported League":
        css = "ld-archive-badge-imported"
    else:
        css = "ld-archive-badge-sim"
    return f'<span class="ld-archive-badge {css}">{label}</span>'


def _context_badge_html(label: str, css_class: str) -> str:
    if not label:
        return ""
    return f'<span class="ld-archive-badge {css_class}">{label}</span>'


def _context_badges_html(session: dict[str, Any], entry: dict[str, Any]) -> str:
    context = get_league_context_for_archive(session, entry)
    parts = [
        _draft_type_badge_html(entry, session=session, context=context if isinstance(context, dict) else None),
        _context_badge_html(league_context_coverage_badge(context), "ld-archive-badge-coverage"),
        _context_badge_html(league_context_type_badge(context), "ld-archive-badge-context-type"),
    ]
    return "".join(p for p in parts if p)


def _format_league_matchup_label(
    context: dict[str, Any] | None,
    active_entry: dict[str, Any] | None = None,
    *,
    session: dict[str, Any] | None = None,
) -> str:
    """Compact league line: Donny vs Barry."""
    teams: list[str] = []
    if isinstance(context, dict):
        rosters = context.get("league_rosters") or {}
        if isinstance(rosters, dict):
            teams = [str(t).strip() for t in rosters.keys() if str(t).strip()]
        if not teams:
            teams = [str(t).strip() for t in (context.get("teams") or []) if str(t).strip()]
    my_team = ""
    if session and isinstance(active_entry, dict):
        try:
            from fantasy_workspace_team_identity import resolve_archive_display_team

            my_team = resolve_archive_display_team(session, active_entry, context)
        except ImportError:
            my_team = ""
    if not my_team:
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
    draft_id = str(entry.get("draft_id") or "").strip()
    if league_save and context:
        st.success(
            f"Saved **{entry.get('draft_name')}** as a **{league_context_coverage_badge(context)}** "
            f"({team_count} teams, {player_count} players on your roster)."
        )
    else:
        st.success(f"Saved **{entry.get('draft_name')}** ({player_count} players).")
    st.caption("Saved to Saved Draft Library. Saving does not change your Active Draft unless you choose Set Active.")
    if draft_id:
        st.info("Would you like to make this your Active Draft?")
        yes_col, no_col = st.columns(2)
        with yes_col:
            if st.button(
                "⭐ Yes — Set Active",
                key=f"post_save_set_active_{draft_id}",
                type="primary",
            ):
                _activate_archive_entry(st, session, draft_id)
                return
        with no_col:
            st.button(
                "No — Keep current Active Draft",
                key=f"post_save_skip_active_{draft_id}",
            )
    view_col, standings_col = st.columns(2)
    with view_col:
        st.button(
            _nav_label(SAVED_DRAFT_LIBRARY_PAGE, "Manage Saved Drafts", page_label_fn),
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


def _resolve_live_draft_save_team_name(
    room: dict[str, Any],
    team_name: str,
    session: dict[str, Any] | None = None,
) -> str:
    if isinstance(session, dict):
        try:
            from fantasy_workspace_team_identity import resolve_current_account_team_for_live_draft_and_league

            resolved = resolve_current_account_team_for_live_draft_and_league(session, room=room)
            if resolved:
                return resolved
        except ImportError:
            pass
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

    save_team = _resolve_live_draft_save_team_name(room, team_name, session)
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
                message="Couldn't save changes. Try again.",
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


def _merge_shared_league_diag(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    raw = session.get(SHARED_LEAGUE_DIAG_KEY)
    diag = dict(raw) if isinstance(raw, dict) else {}
    for key, value in fields.items():
        if value is not None:
            diag[key] = value
    session[SHARED_LEAGUE_DIAG_KEY] = diag
    return diag


def _resolve_live_draft_shared_league_identity(room: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_completion import build_completion_record, get_completion_record

        record = get_completion_record(room)
        if not record:
            record = build_completion_record(room)
    except ImportError:
        record = {}
    draft_id = str(
        record.get("draft_id")
        or room.get("draft_room_id")
        or room.get("draft_id")
        or (room.get("config") or {}).get("draft_id")
        or ""
    ).strip()
    draft_fingerprint = str(record.get("draft_fingerprint") or room.get("draft_fingerprint") or "").strip()
    if not draft_fingerprint:
        try:
            from live_draft_completion import build_completion_record

            draft_fingerprint = str(build_completion_record(room).get("draft_fingerprint") or "").strip()
        except ImportError:
            pass
    return {
        "draft_id": draft_id,
        "draft_fingerprint": draft_fingerprint,
        "room_status": str(room.get("status") or "").strip(),
        "final_board_locked": bool(record.get("final_board_locked")),
    }


def on_open_live_draft_shared_league_confirmation(
    *,
    key_prefix: str = "",
    draft_id: str = "",
    draft_fingerprint: str = "",
) -> None:
    """Open post-draft shared league confirmation — must use on_click before page body."""
    import streamlit as st

    session = st.session_state
    session[SHARED_CONFIRM_OPEN_KEY] = True
    session[SHARED_LEAGUE_CONFIRM_REQUEST_KEY] = {
        "key_prefix": str(key_prefix or ""),
        "draft_id": str(draft_id or ""),
        "draft_fingerprint": str(draft_fingerprint or ""),
    }
    callback_count = int(session.get(SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY) or 0) + 1
    session[SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY] = callback_count
    _merge_shared_league_diag(
        session,
        shared_button_callback_count=callback_count,
        shared_button_clicked_return=True,
        shared_confirm_open_after_button=True,
    )


def _shared_league_create_request_id(
    *,
    draft_id: str = "",
    draft_fingerprint: str = "",
    my_team_name: str = "",
) -> str:
    return "|".join(
        [
            str(draft_id or "").strip(),
            str(draft_fingerprint or "").strip(),
            str(my_team_name or "").strip(),
        ]
    )


def _normalize_create_processing_lock(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        request_id = str(raw.get("request_id") or "").strip()
        if request_id:
            return {
                "request_id": request_id,
                "started_at": float(raw.get("started_at") or 0),
            }
    if raw is True:
        return {"request_id": "", "started_at": 0.0, "legacy_boolean": True}
    return None


def _processing_lock_age_seconds(lock: dict[str, Any]) -> float:
    if lock.get("legacy_boolean"):
        return float(SHARED_LEAGUE_CREATE_LOCK_STALE_SECONDS + 1)
    started = float(lock.get("started_at") or 0)
    if started <= 0:
        return float(SHARED_LEAGUE_CREATE_LOCK_STALE_SECONDS + 1)
    return max(0.0, time.time() - started)


def _clear_create_processing_lock(session: dict[str, Any], *, request_id: str = "") -> None:
    lock = _normalize_create_processing_lock(session.get(SHARED_LEAGUE_CREATE_PROCESSING_KEY))
    if not lock:
        session.pop(SHARED_LEAGUE_CREATE_PROCESSING_KEY, None)
        return
    rid = str(request_id or "").strip()
    lock_rid = str(lock.get("request_id") or "").strip()
    if not rid or not lock_rid or rid == lock_rid or lock.get("legacy_boolean"):
        session.pop(SHARED_LEAGUE_CREATE_PROCESSING_KEY, None)


def _set_create_processing_lock(session: dict[str, Any], request_id: str) -> None:
    session[SHARED_LEAGUE_CREATE_PROCESSING_KEY] = {
        "request_id": str(request_id or "").strip(),
        "started_at": time.time(),
    }


def _sync_shared_league_create_diag_from_session(session: dict[str, Any]) -> dict[str, Any]:
    raw_req = session.get(SHARED_LEAGUE_CREATE_REQUEST_KEY)
    req = dict(raw_req) if isinstance(raw_req, dict) else {}
    lock = _normalize_create_processing_lock(session.get(SHARED_LEAGUE_CREATE_PROCESSING_KEY))
    lock_age = _processing_lock_age_seconds(lock) if lock else None
    try:
        from suite_deploy_marker import format_build_label, resolve_git_commit_short

        deploy_footer = format_build_label()
        deploy_commit = resolve_git_commit_short()
    except ImportError:
        deploy_footer = "unknown"
        deploy_commit = "unknown"
    return _merge_shared_league_diag(
        session,
        create_request_present=bool(req),
        create_request_id=str(req.get("request_id") or ""),
        create_request_status=str(req.get("status") or ""),
        processing_lock_present=bool(lock),
        processing_lock_request_id=str((lock or {}).get("request_id") or ""),
        processing_lock_age_seconds=round(float(lock_age), 2) if lock_age is not None else None,
        deploy_footer=deploy_footer,
        deploy_commit=deploy_commit,
    )


def _render_shared_league_confirm_diagnostics(st: Any, session: dict[str, Any]) -> None:
    diag = _sync_shared_league_create_diag_from_session(session)
    with st.expander("Shared league creation diagnostics", expanded=True):
        lines = [
            ("confirm_button_rendered", diag.get("confirm_button_rendered")),
            ("confirm_button_callback_count", diag.get("confirm_button_callback_count")),
            ("confirm_requested_team", diag.get("confirm_requested_team")),
            ("confirm_requested_draft_id", diag.get("confirm_requested_draft_id")),
            ("confirm_requested_fingerprint", diag.get("confirm_requested_fingerprint")),
            ("create_request_present", diag.get("create_request_present")),
            ("create_request_id", diag.get("create_request_id")),
            ("create_request_status", diag.get("create_request_status")),
            ("create_processor_entered", diag.get("create_processor_entered")),
            ("processing_lock_present", diag.get("processing_lock_present")),
            ("processing_lock_request_id", diag.get("processing_lock_request_id")),
            ("processing_lock_age_seconds", diag.get("processing_lock_age_seconds")),
            ("identity_validation_ok", diag.get("identity_validation_ok")),
            ("preview_validation_ok", diag.get("preview_validation_ok")),
            ("save_call_started", diag.get("save_call_started")),
            ("save_call_completed", diag.get("save_call_completed")),
            ("save_call_count", diag.get("save_call_count")),
            ("created_draft_id", diag.get("created_draft_id")),
            ("created_context_id", diag.get("created_context_id")),
            ("created_canonical_league_id", diag.get("created_canonical_league_id")),
            ("shared_push_attempted", diag.get("shared_push_attempted")),
            ("shared_push_ok", diag.get("shared_push_ok")),
            ("activation_attempted", diag.get("activation_attempted")),
            ("activation_ok", diag.get("activation_ok")),
            ("create_error", diag.get("create_error")),
            ("confirmation_closed_after_success", diag.get("confirmation_closed_after_success")),
            ("deploy_footer", diag.get("deploy_footer")),
            ("deploy_commit", diag.get("deploy_commit")),
        ]
        for key, value in lines:
            st.text(f"{key}: {value if value not in (None, '') else '—'}")


def _clear_shared_league_tombstones(session: dict[str, Any], *, draft_id: str, context_id: str) -> None:
    draft_id = str(draft_id or "").strip()
    context_id = str(context_id or "").strip()
    if draft_id:
        deleted = [
            str(item).strip()
            for item in (session.get("deleted_draft_archive_ids") or session.get("_deleted_draft_archive_ids") or [])
            if str(item).strip() and str(item).strip() != draft_id
        ]
        session["deleted_draft_archive_ids"] = deleted
        session["_deleted_draft_archive_ids"] = deleted
    if context_id:
        try:
            from fantasy_league_context import ensure_fantasy_league_context_state

            store = ensure_fantasy_league_context_state(session)
            ctx_deleted = [
                str(item).strip()
                for item in (store.get("deleted_context_ids") or [])
                if str(item).strip() and str(item).strip() != context_id
            ]
            store["deleted_context_ids"] = ctx_deleted
        except ImportError:
            pass


def _find_shared_league_context_by_identity(
    session: dict[str, Any],
    *,
    draft_id: str = "",
    context_id: str = "",
    canonical_league_id: str = "",
) -> dict[str, Any] | None:
    draft_id = str(draft_id or "").strip()
    context_id = str(context_id or "").strip()
    canonical = str(canonical_league_id or "").strip()
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_league_context, list_league_contexts
    except ImportError:
        return None
    if context_id:
        ctx = get_league_context(session, context_id)
        if isinstance(ctx, dict):
            return ctx
    for ctx in list_league_contexts(session):
        if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        meta = dict(ctx.get("metadata") or {})
        ctx_canonical = str(ctx.get("league_id") or meta.get("league_id") or "").strip()
        source_draft = str(meta.get("source_draft_id") or ctx.get("source_draft_id") or "").strip()
        if canonical and ctx_canonical == canonical:
            return ctx
        if draft_id and source_draft == draft_id:
            return ctx
    return None


def _ensure_shared_league_library_identity(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    my_team: str,
) -> dict[str, Any]:
    from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, upsert_league_context
    from fantasy_league_invites import repair_commissioner_identity
    from fantasy_league_team_ownership import account_user_ids_match, assign_team_owner_to_context, get_team_ownership
    from live_draft_shared_league import CREATED_FROM_LIVE_DRAFT

    context, _ = repair_commissioner_identity(context, session)
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return context
    uid = ""
    try:
        from draft_archive_visibility import _resolve_session_user_id

        uid = str(_resolve_session_user_id(session) or "").strip()
    except ImportError:
        pass
    meta = dict(context.get("metadata") or {})
    team = str(my_team or context.get("my_team_name") or "").strip()
    if str(meta.get("created_from") or "") == CREATED_FROM_LIVE_DRAFT and uid:
        meta["commissioner_user_id"] = uid
        context["metadata"] = meta
        ownership = get_team_ownership(context)
        record = dict(ownership.get(team) or {})
        if team and not account_user_ids_match(str(record.get("user_id") or ""), uid):
            context = assign_team_owner_to_context(context, team, user_id=uid)
        context["my_team_name"] = team or str(context.get("my_team_name") or "")
        context = upsert_league_context(session, context)
    return context


def _shared_league_visibility_diag(
    session: dict[str, Any],
    entry: dict[str, Any] | None,
    context: dict[str, Any] | None,
    *,
    my_team: str,
) -> dict[str, Any]:
    from draft_archive_visibility import _resolve_session_user_id, is_saved_draft_visible_to_session
    from fantasy_league_invites import get_commissioner_user_id, is_league_commissioner
    from fantasy_league_team_ownership import account_user_ids_match, get_team_ownership, owned_team_for_user

    uid = str(_resolve_session_user_id(session) or "").strip()
    commissioner = str(get_commissioner_user_id(context) or "").strip()
    ownership = get_team_ownership(context) if isinstance(context, dict) else {}
    team_record = dict(ownership.get(my_team) or {}) if my_team else {}
    team_owner = str(team_record.get("user_id") or "").strip()
    visible = bool(entry and is_saved_draft_visible_to_session(session, entry, context=context))
    reason = "visible" if visible else "membership_filter"
    if not entry:
        reason = "archive_missing"
    elif not uid:
        reason = "no_auth_user"
    elif isinstance(context, dict) and not is_league_commissioner(context, uid):
        if not owned_team_for_user(context, uid):
            reason = "not_commissioner_or_member"
    return {
        "current_user_id": uid,
        "commissioner_user_id": commissioner,
        "donny_owner_user_id": team_owner,
        "commissioner_recognized": bool(isinstance(context, dict) and uid and is_league_commissioner(context, uid)),
        "donny_ownership_recognized": bool(
            my_team
            and uid
            and account_user_ids_match(team_owner, uid)
            and owned_team_for_user(context, uid) == my_team
        ),
        "visible_archive_found": visible,
        "visibility_decision": reason,
    }


def _persist_shared_league_library_entry(
    st: Any,
    session: dict[str, Any],
    entry: dict[str, Any],
    context: dict[str, Any],
    *,
    my_team: str,
) -> tuple[bool, dict[str, Any]]:
    draft_id = str(entry.get("draft_id") or "").strip()
    context_id = str(context.get("league_context_id") or entry.get("league_context_id") or "").strip()
    context = _ensure_shared_league_library_identity(session, context, my_team=my_team)
    _clear_shared_league_tombstones(session, draft_id=draft_id, context_id=context_id)
    try:
        from fantasy_league_context import repair_missing_draft_archives_from_contexts

        repair_missing_draft_archives_from_contexts(session, require_visibility=False)
    except ImportError:
        pass
    entry = get_draft_archive(session, draft_id) or entry
    try:
        from fantasy_league_context import repair_archive_draft_type_for_entry

        entry = repair_archive_draft_type_for_entry(session, entry, context=context)
    except ImportError:
        pass
    _clear_fantasy_caches_on_archive_change(session)
    persist_ok = _persist_archive(session, st, reason="live_draft_league_context_saved", entry=entry)
    readback = dict(session.get("_suite_last_draft_save_readback") or {})
    return persist_ok, readback


def _repair_shared_league_library_entry(
    st: Any,
    session: dict[str, Any],
    *,
    draft_id: str,
    context_id: str,
    canonical_league_id: str,
    my_team: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], bool, dict[str, Any]]:
    context = _find_shared_league_context_by_identity(
        session,
        draft_id=draft_id,
        context_id=context_id,
        canonical_league_id=canonical_league_id,
    )
    if not isinstance(context, dict):
        return None, {}, False, {"repair_error": "context_not_found"}
    context = _ensure_shared_league_library_identity(session, context, my_team=my_team)
    draft_id = str(draft_id or (context.get("metadata") or {}).get("source_draft_id") or "").strip()
    context_id = str(context_id or context.get("league_context_id") or "").strip()
    _clear_shared_league_tombstones(session, draft_id=draft_id, context_id=context_id)
    try:
        from fantasy_league_context import repair_missing_draft_archives_from_contexts

        repair_missing_draft_archives_from_contexts(session, require_visibility=False)
    except ImportError:
        pass
    entry = get_draft_archive(session, draft_id) if draft_id else None
    if not isinstance(entry, dict):
        return context, {}, False, {"repair_error": "archive_missing_after_repair"}
    persist_ok, disk_readback = _persist_shared_league_library_entry(
        st,
        session,
        entry,
        context,
        my_team=my_team,
    )
    return entry, context, persist_ok, {"disk_readback": disk_readback}


def _verify_shared_league_persistence(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    draft_id: str,
    context_id: str,
    my_team: str,
    expected_counts: dict[str, int],
    entry: dict[str, Any] | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    readback: dict[str, Any] = {}
    draft_id = str(draft_id or "").strip()
    context_id = str(context_id or "").strip()
    try:
        from draft_archive_state import get_draft_archive, list_draft_archives
        from draft_archive_visibility import list_visible_draft_archives
        from fantasy_league_context import (
            CONTEXT_TYPE_REAL_LEAGUE,
            get_active_league_context,
            get_league_context,
        )
    except ImportError as exc:
        return False, [f"Persistence verification unavailable: {exc}"], readback

    raw_count = len(list_draft_archives(session))
    visible_archives = list_visible_draft_archives(session)
    visible_count = len(visible_archives)
    readback["raw_archive_count"] = raw_count
    readback["visible_archive_count"] = visible_count

    archive = get_draft_archive(session, draft_id) if draft_id else None
    if entry is None and isinstance(archive, dict):
        entry = archive
    readback["raw_archive_found"] = bool(archive)
    if not archive:
        errors.append("Shared league creation did not persist to the Draft Library.")

    visible_entry = next(
        (item for item in visible_archives if str(item.get("draft_id") or "").strip() == draft_id),
        None,
    )
    readback["visible_archive_found"] = bool(visible_entry)
    readback["archive_draft_id_matches"] = bool(
        archive and str(archive.get("draft_id") or "").strip() == draft_id
    )

    context = get_league_context(session, context_id) if context_id else None
    readback["league_context_found"] = bool(context)
    if not context:
        errors.append(f"League context {context_id!r} was not found after save.")
    elif str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        errors.append(
            f"League context type is {context.get('context_type')!r}, expected {CONTEXT_TYPE_REAL_LEAGUE!r}."
        )

    vis = _shared_league_visibility_diag(session, archive, context, my_team=my_team)
    readback.update(vis)
    if archive and not vis.get("visible_archive_found"):
        errors.append(
            "Shared league was created, but its Draft Library card is not visible. "
            f"Visibility decision: {vis.get('visibility_decision') or 'unknown'}."
        )
    if context and not vis.get("commissioner_recognized"):
        errors.append("Commissioner is not recognized for this shared league.")
    if my_team and context and not vis.get("donny_ownership_recognized"):
        errors.append(f"Team {my_team!r} ownership is not recognized for the current account.")

    rosters = dict((context or {}).get("league_rosters") or {})
    roster_counts = {
        str(team): len(list((entry_row or {}).get("players") or []))
        for team, entry_row in rosters.items()
    }
    readback["roster_counts"] = roster_counts
    for team, expected in expected_counts.items():
        actual = int(roster_counts.get(team) or 0)
        if actual != int(expected):
            errors.append(f"Team {team!r} roster count is {actual}, expected {expected}.")

    active = get_active_league_context(session, respect_source_priority=False) or {}
    active_id = str(active.get("league_context_id") or "").strip()
    readback["active_context_id"] = active_id
    readback["active_context_matches"] = bool(context_id and active_id == context_id)
    readback["active_context_required"] = False

    canonical_id = str(
        (context or {}).get("league_id")
        or ((context or {}).get("metadata") or {}).get("league_id")
        or ""
    ).strip()
    readback["canonical_league_id"] = canonical_id
    readback["canonical_league_id_found"] = bool(canonical_id)
    if context and not canonical_id:
        errors.append("Canonical league ID is missing from saved league context.")

    disk_readback = dict(session.get("_suite_last_draft_save_readback") or {})
    readback["disk_readback"] = disk_readback
    readback["disk_readback_found"] = bool(disk_readback.get("draft_ids") and draft_id in (disk_readback.get("draft_ids") or []))
    if st is not None and draft_id:
        try:
            from workflow_persist_guard import hydrate_session_workflow_from_disk

            hydrated = hydrate_session_workflow_from_disk(session, draft_id=draft_id)
            readback["disk_hydrate_found"] = bool(hydrated and get_draft_archive(session, draft_id))
        except ImportError:
            readback["disk_hydrate_found"] = None
    try:
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = bool(cloud_storage_enabled())
    except ImportError:
        cloud_enabled = False
    readback["cloud_enabled"] = cloud_enabled
    cloud_readback = session.get("_suite_persist_last_save_cloud")
    if isinstance(cloud_readback, bool):
        cloud_readback = {"ok": cloud_readback}
    elif not isinstance(cloud_readback, dict):
        cloud_readback = {}
    readback["cloud_readback"] = dict(cloud_readback)
    cloud_blocked = str(session.get("_suite_autosave_cloud_blocked_reason") or "").strip()
    cloud_error = str(
        cloud_readback.get("error")
        or cloud_readback.get("cloud_write_error")
        or cloud_readback.get("cloud_readback_error")
        or ""
    ).strip()
    cloud_draft_confirmed = bool(
        draft_id
        and (
            draft_id in (disk_readback.get("draft_ids") or [])
            or draft_id in (cloud_readback.get("draft_ids") or [])
        )
    )
    if not cloud_enabled:
        readback["cloud_readback_found"] = None
        readback["cloud_readback_skipped"] = True
    elif cloud_draft_confirmed:
        readback["cloud_readback_found"] = True
    elif cloud_blocked or cloud_error:
        readback["cloud_readback_found"] = False
        readback["cloud_unavailable"] = True
        readback["cloud_verification_warning"] = cloud_blocked or cloud_error
    else:
        readback["cloud_readback_found"] = False
        errors.append("Cloud persistence readback did not confirm the saved draft.")

    prune_probe = dict(session)
    prune_removed = False
    try:
        from draft_archive_visibility import list_visible_draft_archives as _visible_probe, prune_invisible_shared_league_state

        before_visible = _visible_probe(prune_probe)
        before_has = any(str(item.get("draft_id") or "").strip() == draft_id for item in before_visible)
        removed = prune_invisible_shared_league_state(prune_probe)
        after_visible = _visible_probe(prune_probe)
        after_has = any(str(item.get("draft_id") or "").strip() == draft_id for item in after_visible)
        prune_removed = bool(before_has and not after_has)
        readback["prune_archives_removed"] = int(removed.get("archives_removed") or 0)
        readback["prune_contexts_removed"] = int(removed.get("contexts_removed") or 0)
        readback["prune_removed_entry"] = prune_removed
        readback["library_navigation_readback_found"] = after_has
    except ImportError:
        try:
            from draft_archive_visibility import list_visible_draft_archives as _visible_probe

            nav_visible = _visible_probe(prune_probe)
            readback["library_navigation_readback_found"] = any(
                str(item.get("draft_id") or "").strip() == draft_id for item in nav_visible
            )
        except ImportError:
            readback["library_navigation_readback_found"] = readback.get("visible_archive_found")

    if not readback.get("library_navigation_readback_found"):
        errors.append("Saved Draft Library navigation readback did not find the archive card.")
    if prune_removed:
        errors.append(
            "Visibility prune would remove this shared league; commissioner/ownership identity must be repaired."
        )

    readback["my_team_name"] = str((context or {}).get("my_team_name") or my_team or "")
    return not errors, errors, readback


def on_retry_live_draft_shared_league_creation(
    *,
    my_team_name: str = "",
    league_name: str = "",
    draft_name: str = "",
    draft_id: str = "",
    draft_fingerprint: str = "",
    key_prefix: str = "",
) -> None:
    import streamlit as st

    session = st.session_state
    request_id = _shared_league_create_request_id(
        draft_id=draft_id,
        draft_fingerprint=draft_fingerprint,
        my_team_name=my_team_name,
    )
    _clear_create_processing_lock(session, request_id=request_id)
    session[SHARED_LEAGUE_CREATE_REQUEST_KEY] = {
        "request_id": request_id,
        "my_team_name": str(my_team_name or "").strip(),
        "league_name": str(league_name or "").strip(),
        "draft_name": str(draft_name or "").strip(),
        "draft_id": str(draft_id or "").strip(),
        "draft_fingerprint": str(draft_fingerprint or "").strip(),
        "key_prefix": str(key_prefix or ""),
        "status": "pending",
        "retry": True,
    }
    _merge_shared_league_diag(
        session,
        create_request_id=request_id,
        create_request_status="pending",
        create_error="",
    )


def on_check_live_draft_shared_league_already_created(
    *,
    my_team_name: str = "",
    draft_id: str = "",
    draft_fingerprint: str = "",
) -> None:
    import streamlit as st

    session = st.session_state
    request_id = _shared_league_create_request_id(
        draft_id=draft_id,
        draft_fingerprint=draft_fingerprint,
        my_team_name=my_team_name,
    )
    session[SHARED_LEAGUE_CREATE_REQUEST_KEY] = {
        "request_id": request_id,
        "my_team_name": str(my_team_name or "").strip(),
        "draft_id": str(draft_id or "").strip(),
        "draft_fingerprint": str(draft_fingerprint or "").strip(),
        "status": "check_existing",
    }
    _clear_create_processing_lock(session, request_id=request_id)


def on_confirm_live_draft_shared_league(
    *,
    my_team_name: str = "",
    league_name: str = "",
    draft_name: str = "",
    draft_id: str = "",
    draft_fingerprint: str = "",
    key_prefix: str = "",
) -> None:
    """Stage Create Shared League confirm — must use on_click before page body."""
    import streamlit as st

    session = st.session_state
    callback_count = int(session.get(SHARED_LEAGUE_CONFIRM_CALLBACK_COUNT_KEY) or 0) + 1
    session[SHARED_LEAGUE_CONFIRM_CALLBACK_COUNT_KEY] = callback_count
    request_id = _shared_league_create_request_id(
        draft_id=draft_id,
        draft_fingerprint=draft_fingerprint,
        my_team_name=my_team_name,
    )
    session[SHARED_LEAGUE_CREATE_REQUEST_KEY] = {
        "request_id": request_id,
        "my_team_name": str(my_team_name or "").strip(),
        "league_name": str(league_name or "").strip(),
        "draft_name": str(draft_name or "").strip(),
        "draft_id": str(draft_id or "").strip(),
        "draft_fingerprint": str(draft_fingerprint or "").strip(),
        "key_prefix": str(key_prefix or ""),
        "status": "pending",
    }
    _merge_shared_league_diag(
        session,
        confirm_button_callback_count=callback_count,
        confirm_requested_team=str(my_team_name or "").strip(),
        confirm_selectbox_return_value=str(my_team_name or "").strip(),
        confirm_requested_draft_id=str(draft_id or "").strip(),
        confirm_requested_fingerprint=str(draft_fingerprint or "").strip(),
        create_request_id=request_id,
        create_request_status="pending",
    )


def _on_click_set_active_league(
    draft_id: str = "",
    context_id: str = "",
    league_label: str = "",
    button_key: str = "",
) -> None:
    import streamlit as st

    session = st.session_state
    did = str(draft_id or "").strip()
    if not did:
        return
    loaded_entry, loaded_context = activate_archive_league_context(
        session,
        did,
        defer_activation=False,
    )
    if not loaded_entry:
        return
    _clear_fantasy_caches_on_archive_change(session)
    _persist_archive(session, st, reason="league_context_activated", entry=loaded_entry)
    label = str(
        league_label
        or (loaded_context or {}).get("display_name")
        or loaded_entry.get("draft_name")
        or "League"
    ).strip()
    session["_league_context_activation_toast"] = f"✅ {label} is now your Active League."
    session["_live_draft_shared_league_flash"] = {
        "level": "success",
        "message": f"✅ {label} is now your Active League.",
    }


def _on_click_fantasy_nav(
    target_page: str = "",
    draft_id: str = "",
    context_id: str = "",
    button_key: str = "",
) -> None:
    import streamlit as st

    session = st.session_state
    did = str(draft_id or "").strip()
    if did and not _saved_archive_is_active(session, draft_id=did, context_id=str(context_id or "")):
        label = str(session.get("_shared_league_pending_nav_league_label") or "This league").strip()
        session["_live_draft_shared_league_flash"] = {
            "level": "warning",
            "message": f"Set {label} as your Active League to use this page.",
        }
        return
    schedule_fantasy_analysis_navigation(session, str(target_page or FANTASY_LINEUP_PAGE).strip())


def _render_shared_league_success_navigation(
    st: Any,
    session: dict[str, Any],
    *,
    draft_id: str,
    context_id: str = "",
    league_label: str = "",
    key_prefix: str = "live_draft_complete",
) -> None:
    draft_id = str(draft_id or "").strip()
    context_id = str(context_id or "").strip()
    league_label = str(league_label or "").strip()
    if not draft_id:
        return
    session["_shared_league_pending_nav_league_label"] = league_label or "Robins Fantasy"
    is_active = _saved_archive_is_active(session, draft_id=draft_id, context_id=context_id)
    if is_active:
        st.success(f"✅ {league_label or 'This league'} is your Active League.")
    else:
        st.button(
            "⭐ Set Active League",
            key=f"{key_prefix}_set_active_league_{draft_id[:8]}",
            type="primary",
            use_container_width=True,
            on_click=_on_click_set_active_league,
            kwargs={
                "draft_id": draft_id,
                "context_id": context_id,
                "league_label": league_label,
                "button_key": f"{key_prefix}_set_active_league_{draft_id[:8]}",
            },
        )

    nav1, nav2 = st.columns(2)
    with nav1:
        st.button(
            _nav_label(SAVED_DRAFT_LIBRARY_PAGE, "Open Saved Draft Library"),
            key=f"{key_prefix}_open_library_{draft_id[:8]}",
            use_container_width=True,
            on_click=_on_click_open_saved_draft_library_focus,
            kwargs={
                "draft_id": draft_id,
                "return_page": str(session.get("active_page") or LIVE_DRAFT_PAGE),
                "button_key": f"{key_prefix}_open_library_{draft_id[:8]}",
                "button": "open_saved_draft_library_focus",
            },
        )
    with nav2:
        st.button(
            _nav_label(FANTASY_STANDINGS_PAGE, "Open Fantasy Standings"),
            key=f"{key_prefix}_open_standings_{draft_id[:8]}",
            use_container_width=True,
            disabled=not is_active,
            on_click=_on_click_fantasy_nav,
            kwargs={
                "target_page": FANTASY_STANDINGS_PAGE,
                "draft_id": draft_id,
                "context_id": context_id,
                "button_key": f"{key_prefix}_open_standings_{draft_id[:8]}",
            },
        )
    nav3, nav4, nav5 = st.columns(3)
    with nav3:
        st.button(
            _nav_label(FANTASY_LINEUP_PAGE, "Open Lineup Assistant"),
            key=f"{key_prefix}_open_lineup_{draft_id[:8]}",
            use_container_width=True,
            disabled=not is_active,
            on_click=_on_click_fantasy_nav,
            kwargs={
                "target_page": FANTASY_LINEUP_PAGE,
                "draft_id": draft_id,
                "context_id": context_id,
                "button_key": f"{key_prefix}_open_lineup_{draft_id[:8]}",
            },
        )
    with nav4:
        st.button(
            _nav_label(TRADE_CENTER_PAGE, "Open Trade Center"),
            key=f"{key_prefix}_open_trade_{draft_id[:8]}",
            use_container_width=True,
            disabled=not is_active,
            on_click=_on_click_open_trade_center,
            kwargs={
                "draft_id": draft_id,
                "context_id": context_id,
                "button_key": f"{key_prefix}_open_trade_{draft_id[:8]}",
            },
        )
    with nav5:
        st.button(
            _nav_label(FANTASY_WAIVER_PAGE, "Open Waiver Wire"),
            key=f"{key_prefix}_open_waiver_{draft_id[:8]}",
            use_container_width=True,
            disabled=not is_active,
            on_click=_on_click_fantasy_nav,
            kwargs={
                "target_page": FANTASY_WAIVER_PAGE,
                "draft_id": draft_id,
                "context_id": context_id,
                "button_key": f"{key_prefix}_open_waiver_{draft_id[:8]}",
            },
        )
    if not is_active:
        st.caption(f"Set {league_label or 'this league'} as your Active League to use Lineup, Trade Center, Standings, or Waiver Wire.")


def _on_click_open_trade_center(
    draft_id: str = "",
    context_id: str = "",
    button_key: str = "",
) -> None:
    import streamlit as st

    session = st.session_state
    did = str(draft_id or "").strip()
    if did and not _saved_archive_is_active(session, draft_id=did, context_id=str(context_id or "")):
        label = str(session.get("_shared_league_pending_nav_league_label") or "This league").strip()
        session["_live_draft_shared_league_flash"] = {
            "level": "warning",
            "message": f"Set {label} as your Active League to use this page.",
        }
        return
    session["_lineup_focus_trade_center"] = True
    schedule_fantasy_analysis_navigation(session, FANTASY_LINEUP_PAGE)


def _shared_league_success_message(
    *,
    league_label: str,
    canonical_id: str,
    draft_id: str,
    context_id: str,
    my_team: str,
    count_text: str,
    readback: dict[str, Any],
) -> str:
    return (
        f"Shared League Saved. "
        f"{league_label} was saved successfully. "
        f"Canonical league ID: {canonical_id or '—'}. "
        f"Saved draft ID: {draft_id or '—'}. "
        f"League context ID: {context_id or '—'}. "
        f"Active team: {my_team}. "
        f"Roster counts: {count_text}. "
        f"Raw archive found: {bool(readback.get('raw_archive_found'))}. "
        f"Visible archive found: {bool(readback.get('visible_archive_found'))}. "
        f"Disk readback found: {bool(readback.get('disk_readback_found'))}. "
        f"{_shared_league_cloud_status_line(readback)}"
    )


def _shared_league_cloud_status_line(readback: dict[str, Any]) -> str:
    if readback.get("cloud_readback_skipped"):
        return "Cloud readback: not required (cloud persistence disabled)."
    if readback.get("cloud_readback_found"):
        return "Cloud readback found: true."
    if readback.get("cloud_unavailable"):
        detail = str(readback.get("cloud_verification_warning") or "Cloud temporarily unavailable").strip()
        return f"Cloud readback: not verified ({detail})."
    return "Cloud readback found: false."


def _finalize_shared_league_creation_success(
    st: Any,
    session: dict[str, Any],
    *,
    request_id: str,
    draft_id: str,
    context_id: str,
    canonical_id: str,
    my_team: str,
    preview: dict[str, Any],
    entry: dict[str, Any],
    readback: dict[str, Any],
    save_call_count: int,
    shared_push_ok: bool,
    key_prefix: str = "live_draft_complete",
) -> None:
    completed = dict(session.get(SHARED_LEAGUE_CREATE_COMPLETED_KEY) or {})
    completed[request_id] = {
        "request_id": request_id,
        "draft_id": draft_id,
        "context_id": context_id,
        "canonical_league_id": canonical_id,
        "my_team_name": my_team,
    }
    session[SHARED_LEAGUE_CREATE_COMPLETED_KEY] = completed
    session.pop(SHARED_LEAGUE_CREATE_REQUEST_KEY, None)
    session.pop(SHARED_CONFIRM_OPEN_KEY, None)
    session.pop(SHARED_LEAGUE_CONFIRM_REQUEST_KEY, None)

    counts = preview.get("roster_count_by_team") or {}
    count_text = ", ".join(f"{team} {n}" for team, n in sorted(counts.items()))
    league_label = str(
        preview.get("league_name")
        or entry.get("draft_name")
        or readback.get("league_name")
        or ""
    ).strip()
    success_msg = _shared_league_success_message(
        league_label=league_label,
        canonical_id=canonical_id,
        draft_id=draft_id,
        context_id=context_id,
        my_team=my_team,
        count_text=count_text,
        readback=readback,
    )
    session["_live_draft_shared_league_flash"] = {"level": "success", "message": success_msg}
    session["_live_draft_shared_league_success_actions"] = {
        "draft_id": draft_id,
        "context_id": context_id,
        "league_label": league_label,
        "key_prefix": key_prefix,
    }
    if not shared_push_ok:
        st.warning("Shared backend push did not confirm success; local league context is active.")
    if readback.get("cloud_enabled") and readback.get("cloud_unavailable") and not readback.get("cloud_readback_found"):
        st.warning(
            "Cloud persistence could not be verified right now: "
            f"{readback.get('cloud_verification_warning') or 'Cloud temporarily unavailable'}. "
            "Local disk save succeeded; retry sign-out/sign-in later to confirm cloud durability."
        )
    _merge_shared_league_diag(
        session,
        create_request_status="completed",
        created_draft_id=draft_id,
        created_context_id=context_id,
        created_canonical_league_id=canonical_id,
        confirmation_closed_after_success=True,
        save_call_count=save_call_count,
        persistence_readback=readback,
        create_error="",
    )


def _post_save_shared_league_library(
    st: Any,
    session: dict[str, Any],
    *,
    entry: dict[str, Any],
    context: dict[str, Any],
    my_team: str,
    draft_id: str,
    context_id: str,
    canonical_id: str,
    expected_counts: dict[str, int],
) -> tuple[bool, list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    context = _ensure_shared_league_library_identity(session, context, my_team=my_team)
    persist_ok, _disk = _persist_shared_league_library_entry(
        st,
        session,
        entry,
        context,
        my_team=my_team,
    )
    ok, verify_errors, readback = _verify_shared_league_persistence(
        session,
        st=st,
        draft_id=draft_id,
        context_id=context_id,
        my_team=my_team,
        expected_counts=expected_counts,
        entry=entry,
    )
    if not persist_ok:
        verify_errors = list(verify_errors) + ["Draft Library disk/cloud persistence did not complete."]
        ok = False
    if ok:
        return ok, verify_errors, readback, entry, context

    st.warning(
        "Shared league was created, but its Draft Library card is not visible. "
        "Repairing account ownership and persistence…"
    )
    entry, context, repair_persist_ok, _repair_meta = _repair_shared_league_library_entry(
        st,
        session,
        draft_id=draft_id,
        context_id=context_id,
        canonical_league_id=canonical_id,
        my_team=my_team,
    )
    if not isinstance(entry, dict) or not isinstance(context, dict):
        return False, verify_errors, readback, entry or {}, context or {}
    ok, verify_errors, readback = _verify_shared_league_persistence(
        session,
        st=st,
        draft_id=draft_id,
        context_id=context_id,
        my_team=my_team,
        expected_counts=expected_counts,
        entry=entry,
    )
    if not repair_persist_ok:
        verify_errors = list(verify_errors) + ["Library repair persistence did not complete."]
        ok = False
    return ok, verify_errors, readback, entry, context


def _find_existing_live_draft_shared_league(
    session: dict[str, Any],
    *,
    request_id: str,
    draft_id: str,
    draft_fingerprint: str,
    canonical_league_id: str = "",
) -> dict[str, Any] | None:
    completed = session.get(SHARED_LEAGUE_CREATE_COMPLETED_KEY)
    if isinstance(completed, dict):
        hit = completed.get(request_id)
        if isinstance(hit, dict) and hit.get("context_id"):
            return hit

    draft_id = str(draft_id or "").strip()
    canonical = str(canonical_league_id or "").strip()
    ctx = _find_shared_league_context_by_identity(
        session,
        draft_id=draft_id,
        canonical_league_id=canonical,
    )
    if isinstance(ctx, dict):
        meta = dict(ctx.get("metadata") or {})
        context_id = str(ctx.get("league_context_id") or "").strip()
        source_draft = str(meta.get("source_draft_id") or ctx.get("source_draft_id") or draft_id).strip()
        canonical_id = str(ctx.get("league_id") or meta.get("league_id") or canonical).strip()
        if context_id:
            return {
                "request_id": request_id,
                "draft_id": source_draft or draft_id,
                "context_id": context_id,
                "canonical_league_id": canonical_id,
                "context": ctx,
            }

    if not draft_id:
        return None
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, list_league_contexts
        from live_draft_shared_league import CREATED_FROM_LIVE_DRAFT
    except ImportError:
        return None

    for ctx in list_league_contexts(session):
        if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        meta = dict(ctx.get("metadata") or {})
        if str(meta.get("created_from") or "") != CREATED_FROM_LIVE_DRAFT:
            continue
        if str(meta.get("source_draft_id") or "").strip() != draft_id:
            continue
        fp = str(meta.get("draft_fingerprint") or ctx.get("draft_fingerprint") or "").strip()
        if draft_fingerprint and fp and fp != draft_fingerprint:
            continue
        context_id = str(ctx.get("league_context_id") or "").strip()
        canonical_id = str(ctx.get("league_id") or meta.get("league_id") or "").strip()
        if not context_id:
            continue
        return {
            "request_id": request_id,
            "draft_id": draft_id,
            "context_id": context_id,
            "canonical_league_id": canonical_id,
            "context": ctx,
        }
    return None


def _mark_create_request_status(session: dict[str, Any], raw: dict[str, Any], *, status: str, error: str = "") -> None:
    updated = dict(raw)
    updated["status"] = str(status or "").strip()
    if error:
        updated["last_error"] = str(error)
    session[SHARED_LEAGUE_CREATE_REQUEST_KEY] = updated


def _finalize_existing_shared_league(
    st: Any,
    session: dict[str, Any],
    *,
    existing: dict[str, Any],
    my_team: str,
    preview: dict[str, Any],
    req_draft_id: str,
    cur_id: str,
    save_call_count: int,
    key_prefix: str = "live_draft_complete",
    shared_push_ok: bool = True,
) -> None:
    draft_id = str(existing.get("draft_id") or req_draft_id or cur_id).strip()
    context_id = str(existing.get("context_id") or "").strip()
    canonical_id = str(existing.get("canonical_league_id") or "").strip()
    request_id = str(existing.get("request_id") or "").strip()
    expected_counts = {
        str(team): int(count)
        for team, count in dict(preview.get("roster_count_by_team") or {}).items()
    }
    context = get_league_context(session, context_id) if context_id else None
    if not isinstance(context, dict):
        context = dict(existing.get("context") or {})
    entry = get_draft_archive(session, draft_id) if draft_id else None
    if not isinstance(entry, dict):
        entry = {"draft_id": draft_id, "league_context_id": context_id}

    ok, verify_errors, readback, entry, context = _post_save_shared_league_library(
        st,
        session,
        entry=entry,
        context=context,
        my_team=my_team,
        draft_id=draft_id,
        context_id=context_id,
        canonical_id=canonical_id,
        expected_counts=expected_counts,
    )
    _merge_shared_league_diag(session, persistence_readback=readback)
    if ok:
        _finalize_shared_league_creation_success(
            st,
            session,
            request_id=request_id or _shared_league_create_request_id(draft_id=draft_id),
            draft_id=draft_id,
            context_id=context_id,
            canonical_id=canonical_id or str(readback.get("canonical_league_id") or ""),
            my_team=my_team,
            preview=preview,
            entry=entry,
            readback=readback,
            save_call_count=save_call_count,
            shared_push_ok=shared_push_ok,
            key_prefix=key_prefix,
        )
        st.info(
            f"This completed draft was already converted to shared league "
            f"`{canonical_id or context_id}`; library card restored and verified."
        )
        return

    err = "; ".join(verify_errors)
    session["_live_draft_shared_league_flash"] = {"level": "error", "message": err}
    st.error(err)
    _merge_shared_league_diag(
        session,
        create_request_status="repair_failed",
        created_draft_id=draft_id,
        created_context_id=context_id,
        created_canonical_league_id=canonical_id,
        confirmation_closed_after_success=False,
        save_call_count=save_call_count,
        create_error=err,
    )


def _process_live_draft_shared_league_create_request(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> None:
    """Process staged Create Shared League confirm/check/retry requests."""
    _sync_shared_league_create_diag_from_session(session)
    raw = session.get(SHARED_LEAGUE_CREATE_REQUEST_KEY)
    if not isinstance(raw, dict):
        return

    status = str(raw.get("status") or "")
    if status not in {"pending", "check_existing"}:
        return

    request_id = str(raw.get("request_id") or "").strip()
    my_team = str(raw.get("my_team_name") or "").strip()
    league_name = str(raw.get("league_name") or "").strip()
    draft_name = str(raw.get("draft_name") or "").strip()
    req_draft_id = str(raw.get("draft_id") or "").strip()
    req_fingerprint = str(raw.get("draft_fingerprint") or "").strip()
    if not request_id:
        request_id = _shared_league_create_request_id(
            draft_id=req_draft_id,
            draft_fingerprint=req_fingerprint,
            my_team_name=my_team,
        )

    lock = _normalize_create_processing_lock(session.get(SHARED_LEAGUE_CREATE_PROCESSING_KEY))
    if lock:
        lock_rid = str(lock.get("request_id") or "").strip()
        lock_age = _processing_lock_age_seconds(lock)
        _merge_shared_league_diag(
            session,
            processing_lock_present=True,
            processing_lock_request_id=lock_rid,
            processing_lock_age_seconds=round(lock_age, 2),
        )
        if lock_rid == request_id and lock_age <= SHARED_LEAGUE_CREATE_LOCK_STALE_SECONDS:
            st.info("Shared league creation is already processing.")
            _merge_shared_league_diag(
                session,
                create_processor_entered=False,
                create_error="processing_lock_active",
            )
            return
        if lock.get("legacy_boolean") or lock_age > SHARED_LEAGUE_CREATE_LOCK_STALE_SECONDS:
            st.warning("A previous creation attempt was interrupted. Resuming the request now.")
            _clear_create_processing_lock(session, request_id=lock_rid or request_id)
        elif lock_rid and lock_rid != request_id:
            st.warning(f"Clearing stale processing lock for request {lock_rid!r}.")
            _clear_create_processing_lock(session, request_id=lock_rid)

    _set_create_processing_lock(session, request_id)
    save_call_count = int((session.get(SHARED_LEAGUE_DIAG_KEY) or {}).get("save_call_count") or 0)
    _merge_shared_league_diag(
        session,
        create_processor_entered=True,
        create_request_id=request_id,
        create_request_status="processing",
        save_call_count=save_call_count,
        create_error="",
    )

    identity_snapshot = None
    try:
        from suite_identity_guard import snapshot_protected_browser_identity

        identity_snapshot = snapshot_protected_browser_identity(session)
    except ImportError:
        pass

    try:
        try:
            from live_draft_shared_league import preview_shared_league_creation, save_live_draft_shared_league_context
        except ImportError as exc:
            err = f"ImportError: {exc}"
            _mark_create_request_status(session, raw, status="failed", error=err)
            session["_live_draft_shared_league_flash"] = {
                "level": "error",
                "message": f"Could not create shared league: {err}",
            }
            st.error(f"Could not create shared league: {err}")
            _merge_shared_league_diag(session, create_error=err, create_request_status="failed")
            return

        identity = _resolve_live_draft_shared_league_identity(room)
        cur_id = str(identity.get("draft_id") or "").strip()
        cur_fp = str(identity.get("draft_fingerprint") or "").strip()

        if status == "check_existing":
            preview = preview_shared_league_creation(
                room,
                my_team_name=my_team or str((room.get("teams") or [""])[0]),
                league_name=league_name,
            )
            existing = _find_existing_live_draft_shared_league(
                session,
                request_id=request_id,
                draft_id=req_draft_id or cur_id,
                draft_fingerprint=req_fingerprint or cur_fp,
            )
            if not existing:
                st.warning("No existing shared league was found for this completed draft.")
                _mark_create_request_status(session, raw, status="failed", error="existing_league_not_found")
                return
            _finalize_existing_shared_league(
                st,
                session,
                existing=existing,
                my_team=my_team,
                preview=preview,
                req_draft_id=req_draft_id,
                cur_id=cur_id,
                save_call_count=save_call_count,
            )
            return

        identity_errors: list[str] = []
        if req_draft_id and cur_id and req_draft_id != cur_id:
            identity_errors.append(f"Draft ID mismatch: requested `{req_draft_id}`, current `{cur_id}`.")
        if req_fingerprint and cur_fp and req_fingerprint != cur_fp:
            identity_errors.append(f"Draft fingerprint mismatch: requested `{req_fingerprint}`, current `{cur_fp}`.")
        if str(identity.get("room_status") or "") != "complete":
            identity_errors.append(
                f"Completed room unavailable: status is `{identity.get('room_status') or 'unknown'}`."
            )
        if not identity.get("final_board_locked"):
            identity_errors.append("Final board is not locked for this completed draft.")
        teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
        if my_team not in teams:
            identity_errors.append(f"Team {my_team!r} is not part of this draft.")

        identity_ok = not identity_errors
        _merge_shared_league_diag(session, identity_validation_ok=identity_ok)
        if identity_errors:
            err = "; ".join(identity_errors)
            _mark_create_request_status(session, raw, status="failed", error=err)
            session["_live_draft_shared_league_flash"] = {
                "level": "error",
                "message": f"Could not create shared league: {err}",
            }
            st.error(f"Could not create shared league: {err}")
            _merge_shared_league_diag(
                session,
                preview_validation_ok=False,
                create_error=err,
                create_request_status="failed",
            )
            return

        st.info("Creating shared league…")
        try:
            preview = preview_shared_league_creation(
                room,
                my_team_name=my_team,
                league_name=league_name,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            _mark_create_request_status(session, raw, status="failed", error=err)
            session["_live_draft_shared_league_flash"] = {
                "level": "error",
                "message": f"Could not create shared league: {err}",
            }
            st.error(f"Could not create shared league: {err}")
            _merge_shared_league_diag(
                session,
                preview_validation_ok=False,
                create_error=err,
                create_request_status="failed",
            )
            return

        validation_errors = [str(e) for e in (preview.get("validation_errors") or []) if str(e).strip()]
        preview_ok = not validation_errors and bool(preview.get("ready"))
        _merge_shared_league_diag(session, preview_validation_ok=preview_ok)
        if not preview_ok:
            err = "; ".join(validation_errors) if validation_errors else "Shared league preview is not ready."
            _mark_create_request_status(session, raw, status="failed", error=err)
            session["_live_draft_shared_league_flash"] = {
                "level": "error",
                "message": f"Could not create shared league: {err}",
            }
            st.error(f"Could not create shared league: {err}")
            _merge_shared_league_diag(
                session,
                create_error=err,
                create_request_status="failed",
            )
            return

        existing = _find_existing_live_draft_shared_league(
            session,
            request_id=request_id,
            draft_id=req_draft_id or cur_id,
            draft_fingerprint=req_fingerprint or cur_fp,
        )
        if existing:
            _finalize_existing_shared_league(
                st,
                session,
                existing=existing,
                my_team=my_team,
                preview=preview,
                req_draft_id=req_draft_id,
                cur_id=cur_id,
                save_call_count=save_call_count,
            )
            return

        _merge_shared_league_diag(session, save_call_started=True)
        entry: dict[str, Any] = {}
        context: dict[str, Any] = {}
        shared_push_ok = False
        try:
            entry, context = save_live_draft_shared_league_context(
                session,
                room,
                my_team_name=my_team,
                league_name=str(league_name or preview.get("league_name") or "").strip(),
                draft_name=draft_name,
                defer_activation=True,
                assign_team=True,
            )
            save_call_count += 1
            shared_push_ok = bool(entry.get("shared_league_created"))
            _merge_shared_league_diag(
                session,
                save_call_completed=True,
                save_call_count=save_call_count,
                shared_push_attempted=True,
                shared_push_ok=shared_push_ok,
                activation_attempted=False,
                activation_ok=False,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            _mark_create_request_status(session, raw, status="failed", error=err)
            session["_live_draft_shared_league_flash"] = {
                "level": "error",
                "message": f"Could not create shared league: {err}",
            }
            st.error(f"Could not create shared league: {err}")
            _merge_shared_league_diag(
                session,
                save_call_completed=False,
                save_call_count=save_call_count,
                create_error=err,
                create_request_status="failed",
            )
            return

        draft_id = str(entry.get("draft_id") or context.get("source_draft_id") or req_draft_id or cur_id).strip()
        context_id = str(context.get("league_context_id") or entry.get("league_context_id") or "").strip()
        canonical_id = str(
            entry.get("canonical_league_id")
            or context.get("league_id")
            or (context.get("metadata") or {}).get("league_id")
            or ""
        ).strip()
        expected_counts = {
            str(team): int(count)
            for team, count in dict(preview.get("roster_count_by_team") or {}).items()
        }
        ok, verify_errors, readback, entry, context = _post_save_shared_league_library(
            st,
            session,
            entry=entry,
            context=context,
            my_team=my_team,
            draft_id=draft_id,
            context_id=context_id,
            canonical_id=canonical_id,
            expected_counts=expected_counts,
        )
        _merge_shared_league_diag(session, persistence_readback=readback)
        if not ok:
            err = "; ".join(verify_errors)
            _mark_create_request_status(session, raw, status="failed", error=err)
            session["_live_draft_shared_league_flash"] = {
                "level": "error",
                "message": err,
            }
            st.error(err)
            _merge_shared_league_diag(
                session,
                create_error=err,
                create_request_status="failed",
                confirmation_closed_after_success=False,
            )
            if not shared_push_ok:
                st.warning("Shared backend push did not confirm success; local league context was saved.")
            return

        _finalize_shared_league_creation_success(
            st,
            session,
            request_id=request_id,
            draft_id=draft_id,
            context_id=context_id,
            canonical_id=canonical_id or str(readback.get("canonical_league_id") or ""),
            my_team=my_team,
            preview=preview,
            entry=entry,
            readback=readback,
            save_call_count=save_call_count,
            shared_push_ok=shared_push_ok,
        )
    finally:
        try:
            from suite_identity_guard import enforce_identity_after_state_apply

            enforce_identity_after_state_apply(
                session,
                snapshot=identity_snapshot if isinstance(identity_snapshot, dict) else None,
                reason="live_draft_shared_league_create",
                last_mutator="_process_live_draft_shared_league_create_request",
                st=st,
            )
        except ImportError:
            pass
        _clear_create_processing_lock(session, request_id=request_id)
        _sync_shared_league_create_diag_from_session(session)


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
    board_df_fn=None,
) -> None:
    """Post-final-pick Draft Complete hub."""
    try:
        from suite_identity_guard import enforce_identity_after_state_apply

        enforce_identity_after_state_apply(
            session,
            reason="render_live_draft_completion_panel",
            last_mutator="render_live_draft_completion_panel",
            st=st,
        )
    except ImportError:
        pass
    try:
        from fantasy_workspace_team_identity import apply_account_team_identity_to_session

        apply_account_team_identity_to_session(
            session,
            room=room,
            reason="render_live_draft_completion_panel",
        )
    except ImportError:
        pass
    try:
        from live_draft_completion import apply_live_draft_completion

        room = apply_live_draft_completion(room, session)
    except ImportError:
        pass

    cfg = dict(room.get("config") or {})
    save_team = _resolve_live_draft_save_team_name(room, team_name, session)
    if not save_team:
        st.warning("Could not determine your fantasy team for saving this draft.")
        return

    identity = _resolve_live_draft_shared_league_identity(room)
    confirm_open_before = bool(session.get(SHARED_CONFIRM_OPEN_KEY))
    _merge_shared_league_diag(
        session,
        shared_confirm_open_before_buttons=confirm_open_before,
        completion_panel_rendered=True,
        completed_room_present=isinstance(room, dict) and bool(room),
        room_status=identity.get("room_status") or "",
        final_board_locked=bool(identity.get("final_board_locked")),
        draft_id=str(identity.get("draft_id") or ""),
        draft_fingerprint=str(identity.get("draft_fingerprint") or ""),
        shared_button_callback_count=int(session.get(SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY) or 0),
    )

    try:
        from suite_identity_guard import render_identity_guard_diagnostic_panel

        render_identity_guard_diagnostic_panel(
            st,
            session,
            title="Live Draft completion — account / workspace identity",
            room=room,
        )
    except ImportError:
        pass

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
    league_name = st.text_input(
        "League name (shared league)",
        value=str(cfg.get("league_name") or default_name).strip(" —"),
        key=f"{key_prefix}_league_name_input",
    )

    st.markdown("#### Draft Complete")
    st.caption("Review the final board, save the completed draft, analyze results, or create a shared league.")
    review_col, save_col, analyze_col, league_col, export_col = st.columns(5)
    with review_col:
        review_open = st.button(
            "Review Draft Results",
            key=f"{key_prefix}_review_btn",
            use_container_width=True,
        )
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
    with league_col:
        st.button(
            "Create Shared League",
            key=f"{key_prefix}_shared_league_btn",
            use_container_width=True,
            on_click=on_open_live_draft_shared_league_confirmation,
            kwargs={
                "key_prefix": key_prefix,
                "draft_id": str(identity.get("draft_id") or ""),
                "draft_fingerprint": str(identity.get("draft_fingerprint") or ""),
            },
        )
    with export_col:
        export_clicked = st.button("Export Draft", key=f"{key_prefix}_export_btn", use_container_width=True)

    _merge_shared_league_diag(
        session,
        shared_confirm_open_after_button=bool(session.get(SHARED_CONFIRM_OPEN_KEY)),
        shared_button_callback_count=int(session.get(SHARED_LEAGUE_OPEN_CALLBACK_COUNT_KEY) or 0),
    )

    if review_open:
        session[f"{key_prefix}_review_open"] = True

    if session.pop(f"{key_prefix}_review_open", False) or review_open:
        with st.expander("Review Draft Results", expanded=True):
            if callable(board_df_fn):
                board_df = board_df_fn(room)
                if board_df.empty:
                    st.caption("No picks recorded.")
                else:
                    st.dataframe(board_df, use_container_width=True, hide_index=True)
            else:
                st.caption("Final board preview unavailable.")
            for team in sorted(room.get("teams") or []):
                roster_rows = list((room.get("rosters") or {}).get(team) or [])
                if roster_rows:
                    st.markdown(f"**{team}** — {len(roster_rows)} players")

    _process_live_draft_shared_league_create_request(st, session, room)

    if session.get(SHARED_CONFIRM_OPEN_KEY):
        _render_live_draft_shared_league_confirmation(
            st,
            session,
            room,
            save_team=save_team,
            league_name=league_name,
            draft_name=draft_name,
            key_prefix=key_prefix,
        )
        _process_live_draft_shared_league_create_request(st, session, room)

    shared_flash = session.pop("_live_draft_shared_league_flash", None)
    if isinstance(shared_flash, dict) and shared_flash.get("message"):
        level = str(shared_flash.get("level") or "info")
        message = str(shared_flash["message"])
        if level == "error":
            st.error(message)
        elif level == "warning":
            st.warning(message)
        elif level == "success":
            st.success(message)
        else:
            st.info(message)

    success_actions = session.pop("_live_draft_shared_league_success_actions", None)
    if isinstance(success_actions, dict) and success_actions.get("draft_id"):
        _render_shared_league_success_navigation(
            st,
            session,
            draft_id=str(success_actions.get("draft_id") or ""),
            context_id=str(success_actions.get("context_id") or ""),
            league_label=str(success_actions.get("league_label") or ""),
            key_prefix=str(success_actions.get("key_prefix") or key_prefix),
        )

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


def _render_live_draft_shared_league_confirmation(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    save_team: str,
    league_name: str,
    draft_name: str,
    key_prefix: str,
) -> None:
    _merge_shared_league_diag(session, confirmation_render_entered=True)
    st.info("Shared league confirmation opened.")

    identity = _resolve_live_draft_shared_league_identity(room)
    request = session.get(SHARED_LEAGUE_CONFIRM_REQUEST_KEY)
    if isinstance(request, dict):
        mismatches: list[str] = []
        req_id = str(request.get("draft_id") or "").strip()
        req_fp = str(request.get("draft_fingerprint") or "").strip()
        cur_id = str(identity.get("draft_id") or "").strip()
        cur_fp = str(identity.get("draft_fingerprint") or "").strip()
        if req_id and cur_id and req_id != cur_id:
            mismatches.append(f"Draft ID mismatch: requested `{req_id}`, current `{cur_id}`.")
        if req_fp and cur_fp and req_fp != cur_fp:
            mismatches.append(f"Draft fingerprint mismatch: requested `{req_fp}`, current `{cur_fp}`.")
        if str(identity.get("room_status") or "") != "complete":
            mismatches.append(
                f"Completed room unavailable: status is `{identity.get('room_status') or 'unknown'}`."
            )
        if not identity.get("final_board_locked"):
            mismatches.append("Final board is not locked for this completed draft.")
        if mismatches:
            for msg in mismatches:
                st.error(msg)
            _merge_shared_league_diag(
                session,
                preview_call_started=False,
                preview_call_completed=False,
                claim_attempted=False,
                preview_validation_errors=mismatches,
            )
            return

    try:
        from live_draft_shared_league import preview_shared_league_creation
    except ImportError:
        st.error("Shared league module unavailable.")
        return

    _merge_shared_league_diag(session, preview_call_started=True)
    try:
        preview = preview_shared_league_creation(
            room,
            my_team_name=save_team,
            league_name=str(league_name or "").strip(),
        )
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        session["_live_draft_shared_league_preview_error"] = err
        st.error(f"Could not prepare shared league confirmation: {err}")
        _merge_shared_league_diag(
            session,
            preview_call_completed=False,
            preview_exception=err,
            preview_validation_errors=[],
            claim_attempted=False,
        )
        return

    validation_errors = [str(e) for e in (preview.get("validation_errors") or []) if str(e).strip()]
    roster_diag = preview.get("roster_transfer_diagnostics") or {}
    _merge_shared_league_diag(
        session,
        preview_call_completed=True,
        preview_validation_errors=validation_errors,
        preview_exception="",
        roster_transfer_diagnostics=roster_diag,
    )
    resolution_notes = [str(n) for n in (roster_diag.get("resolution_notes") or []) if str(n).strip()]
    if resolution_notes:
        with st.expander("Board team label resolution", expanded=False):
            for note in resolution_notes:
                st.caption(note)
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        dev_mode = bool(developer_mode_checkbox_enabled(st=st))
    except ImportError:
        dev_mode = False
    if dev_mode and roster_diag:
        with st.expander("Roster transfer diagnostics (Developer Mode)", expanded=False):
            st.json(
                {
                    k: roster_diag.get(k)
                    for k in (
                        "room_teams",
                        "room_roster_keys",
                        "draft_board_row_count",
                        "draft_board_distinct_team_values",
                        "draft_results_count",
                        "draft_results_distinct_team_values",
                        "configured_team_names",
                        "team_rename_map",
                        "resolved_board_team_map",
                        "unmapped_board_teams",
                        "ambiguous_board_teams",
                    )
                }
            )
            board_rows = roster_diag.get("board_row_details") or []
            if board_rows:
                st.markdown("**Board row resolution**")
                for entry in board_rows:
                    st.text(
                        f"Pick {entry.get('pick_number')} | "
                        f"{entry.get('player_name') or entry.get('player_id')} | "
                        f"raw={entry.get('raw_board_team')!r} | "
                        f"team_id={entry.get('team_id') or '—'} | "
                        f"resolved={entry.get('resolved_display_team')!r}"
                    )
    with st.expander("Create Shared League — confirmation", expanded=True):
        if validation_errors:
            for err in validation_errors:
                st.error(str(err))
            return
        st.markdown(f"**League name:** {preview.get('league_name')}")
        st.markdown(f"**Canonical league ID:** `{preview.get('canonical_league_id') or 'pending'}`")
        st.markdown(f"**Draft ID:** `{preview.get('draft_id') or '—'}`")
        st.markdown(f"**Draft fingerprint:** `{preview.get('draft_fingerprint') or '—'}`")
        st.markdown(f"**Teams:** {', '.join(preview.get('teams') or [])}")
        st.markdown(f"**Trade eligibility:** {preview.get('trade_eligibility_status')}")
        counts = preview.get("roster_count_by_team") or {}
        if counts:
            st.markdown("**Roster counts:** " + ", ".join(f"{team}: {n}" for team, n in counts.items()))
        final_rosters = preview.get("final_rosters") or {}
        for team in sorted(final_rosters.keys()):
            players = [
                str(p.get("player_name") or "").strip()
                for p in (final_rosters.get(team) or {}).get("players") or []
                if str(p.get("player_name") or "").strip()
            ]
            st.markdown(f"**Final roster — {team}:** {', '.join(players) if players else '(empty)'}")
        roster_slots = preview.get("roster_slots") or {}
        if roster_slots:
            st.markdown("**Roster slots:** " + ", ".join(f"{pos}×{n}" for pos, n in roster_slots.items() if int(n or 0) > 0))
        scoring = preview.get("scoring_settings") or {}
        if scoring:
            st.markdown(f"**Scoring:** {scoring.get('scoring_type') or scoring.get('fantasy_format') or '—'}")
        my_team = st.selectbox(
            "Which team is yours?",
            list(preview.get("teams") or [save_team]),
            index=max(0, list(preview.get("teams") or [save_team]).index(save_team) if save_team in (preview.get("teams") or []) else 0),
            key=f"{key_prefix}_shared_my_team",
        )
        _merge_shared_league_diag(
            session,
            confirm_button_rendered=True,
            confirm_selectbox_return_value=str(my_team or "").strip(),
        )
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            st.button(
                "Confirm Create Shared League",
                key=f"{key_prefix}_confirm_shared_league",
                type="primary",
                use_container_width=True,
                on_click=on_confirm_live_draft_shared_league,
                kwargs={
                    "my_team_name": my_team,
                    "league_name": str(league_name or preview.get("league_name") or "").strip(),
                    "draft_name": str(draft_name or "").strip(),
                    "draft_id": str(identity.get("draft_id") or preview.get("draft_id") or "").strip(),
                    "draft_fingerprint": str(
                        identity.get("draft_fingerprint") or preview.get("draft_fingerprint") or ""
                    ).strip(),
                    "key_prefix": key_prefix,
                },
            )
        with cancel_col:
            cancel_clicked = st.button(
                "Cancel",
                key=f"{key_prefix}_cancel_shared_league",
                use_container_width=True,
            )
        if cancel_clicked:
            session.pop(SHARED_CONFIRM_OPEN_KEY, None)
            session.pop(SHARED_LEAGUE_CONFIRM_REQUEST_KEY, None)
            session.pop(SHARED_LEAGUE_CREATE_REQUEST_KEY, None)
            _clear_create_processing_lock(session)
            st.rerun()

        create_req = session.get(SHARED_LEAGUE_CREATE_REQUEST_KEY)
        create_status = str((create_req or {}).get("status") or "") if isinstance(create_req, dict) else ""
        recovery_col, check_col = st.columns(2)
        with recovery_col:
            st.button(
                "Retry Shared League Creation",
                key=f"{key_prefix}_retry_shared_league",
                use_container_width=True,
                disabled=create_status not in {"failed", "pending", ""},
                on_click=on_retry_live_draft_shared_league_creation,
                kwargs={
                    "my_team_name": my_team,
                    "league_name": str(league_name or preview.get("league_name") or "").strip(),
                    "draft_name": str(draft_name or "").strip(),
                    "draft_id": str(identity.get("draft_id") or preview.get("draft_id") or "").strip(),
                    "draft_fingerprint": str(
                        identity.get("draft_fingerprint") or preview.get("draft_fingerprint") or ""
                    ).strip(),
                    "key_prefix": key_prefix,
                },
            )
        with check_col:
            st.button(
                "Check Whether League Was Already Created",
                key=f"{key_prefix}_check_shared_league",
                use_container_width=True,
                on_click=on_check_live_draft_shared_league_already_created,
                kwargs={
                    "my_team_name": my_team,
                    "draft_id": str(identity.get("draft_id") or preview.get("draft_id") or "").strip(),
                    "draft_fingerprint": str(
                        identity.get("draft_fingerprint") or preview.get("draft_fingerprint") or ""
                    ).strip(),
                },
            )
        _render_shared_league_confirm_diagnostics(st, session)


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
    save_team = _resolve_live_draft_save_team_name(room, team_name, session)
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
    is_focused: bool = False,
    is_real_league: bool = False,
    player_n: int,
    team_n: int,
    display_team: str = "",
    session: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    title = str(entry.get("draft_name") or "Saved Draft")
    team = str(display_team or entry.get("team_name") or "—")
    modified = format_archive_modified(entry)
    card_class = "ld-archive-card"
    if is_active:
        card_class = "ld-archive-card ld-archive-active"
    elif is_focused:
        card_class = "ld-archive-card ld-archive-focus"
    active_label = "ACTIVE LEAGUE" if is_real_league else "ACTIVE"
    active_badge = (
        f'<span class="ld-archive-badge ld-archive-badge-active">{active_label}</span> '
        if is_active
        else ""
    )
    type_badge = _draft_type_badge_html(entry, session=session, context=context)
    return (
        f'<div class="{card_class}">{active_badge}{type_badge} '
        f"<strong>{title}</strong><br>"
        f"<span style='opacity:0.9'>{team}</span><br>"
        f"<span style='opacity:0.85'>{team_n} team{'s' if team_n != 1 else ''} · "
        f"{player_n} player{'s' if player_n != 1 else ''} · Updated {modified}</span></div>"
    )


def _activate_archive_entry(st: Any, session: dict[str, Any], draft_id: str) -> None:
    try:
        from account_fantasy_preferences import (
            activate_library_selection_and_sync_preferences,
            pop_preference_sync_warning,
        )
        from library_repair_scheduler import mark_library_dirty

        mark_library_dirty(session, reason="activate_archive")
        activation = activate_library_selection_and_sync_preferences(
            session,
            draft_id=draft_id,
            reason="activate_archive",
        )
        loaded_entry = activation.get("entry")
        loaded_context = activation.get("context")
        if not loaded_entry:
            st.warning("Could not activate that saved draft. Try again.")
            return
        prefs_write = activation.get("prefs_write") or {}
        if prefs_write and not prefs_write.get("write_verified") and prefs_write.get("skipped") != "unsigned":
            warn = pop_preference_sync_warning(session) or (
                "Your selection changed on this device, but account sync did not complete. Try again."
            )
            st.warning(warn)
            # Still continue locally so the phone UI is correct even if cloud sync fails.
    except ImportError:
        loaded_entry, loaded_context = activate_archive_league_context(
            session,
            draft_id,
            defer_activation=False,
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
    _persist_archive(session, st, reason="league_context_activated", entry=loaded_entry)
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
        try:
            from fantasy_context_terminology import is_league_context

            noun = "League" if is_league_context(loaded_context, loaded_entry) else "Draft"
        except ImportError:
            noun = "Draft"
        st.session_state["_league_context_activation_toast"] = (
            f"✅ {loaded_context.get('display_name', loaded_entry.get('draft_name'))} is now your Active {noun}."
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
    if not context:
        st.warning(
            "Active draft archive and league context are out of sync. "
            "Use **⭐ Set Active League** on the correct saved draft below."
        )
        return
    title = str(active.get("draft_name") or "Saved Draft")
    team_count = league_team_count(context, active)
    player_n = archive_my_team_player_count(active, context=context)
    league_line = _format_league_matchup_label(context, active, session=session)
    st.markdown(f"**{title}** — {league_line}")
    origin_label = resolve_draft_type_display(session, active, context=context)
    st.caption(
        f"{origin_label} | "
        f"{team_count} Teams | {player_n} Players · "
        f"Updated {format_archive_modified(active)}"
    )
    # Always show the active league's origin decision so Cloud sessions can be diagnosed.
    try:
        from fantasy_league_context import ORIGIN_REPAIR_DECISIONS_KEY

        active_id = str(active.get("draft_id") or "").strip()
        decisions = session.get(ORIGIN_REPAIR_DECISIONS_KEY) or []
        hit = next(
            (row for row in decisions if isinstance(row, dict) and str(row.get("draft_id") or "") == active_id),
            None,
        )
        if not isinstance(hit, dict):
            from fantasy_league_context import evaluate_origin_decisions_for_visible_archives

            evaluate_origin_decisions_for_visible_archives(session)
            decisions = session.get(ORIGIN_REPAIR_DECISIONS_KEY) or []
            hit = next(
                (row for row in decisions if isinstance(row, dict) and str(row.get("draft_id") or "") == active_id),
                None,
            )
        if isinstance(hit, dict):
            keys = (
                "draft_id",
                "draft_name",
                "selected_draft_type",
                "selected_reason",
                "archive_type_before",
                "archive_type_after",
                "creation_origin_before",
                "live_created_from_evidence",
                "shared_doc_loaded",
                "context_loaded",
                "shared_league_created_flag",
                "shared_created_from",
                "context_created_from",
                "migrated",
                "source",
            )
            st.code(
                "Origin decision (active league)\n"
                + "\n".join(f"{key}: {hit.get(key)}" for key in keys),
                language="text",
            )
    except Exception:
        pass
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
    context: dict[str, Any] | None = None,
    widget_key_prefix: str = "archive",
) -> None:
    context = context or get_league_context_for_archive(session, entry)
    is_league = _archive_card_is_real_league(entry, context)
    set_active_label = "⭐ Set Active League" if is_league else "⭐ Set Active Draft"
    rename_label = "Rename League" if is_league else "Rename Draft"
    delete_label = "Delete League" if is_league else "Delete Draft"
    league_title = str(entry.get("draft_name") or "League").strip()
    if is_active:
        st.button(
            "✅ Active League" if is_league else "✅ Active Draft",
            key=f"{widget_key_prefix}_active_{draft_id}",
            disabled=True,
            use_container_width=True,
        )
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button(
                rename_label,
                key=f"{widget_key_prefix}_rename_{draft_id}",
                use_container_width=True,
            ):
                session[_RENAME_CONFIRM_PREFIX + draft_id] = True
                st.rerun()
        with btn2:
            st.button(
                delete_label,
                key=f"{widget_key_prefix}_del_{draft_id}",
                use_container_width=True,
                on_click=_on_click_request_delete_draft,
                args=(draft_id, widget_key_prefix),
            )
    else:
        btn1, btn2, btn3 = st.columns(3)
        with btn1:
            if st.button(
                set_active_label,
                key=f"{widget_key_prefix}_set_active_{draft_id}",
                type="primary",
                use_container_width=True,
            ):
                _activate_archive_entry(st, session, draft_id)
        with btn2:
            if st.button(
                rename_label,
                key=f"{widget_key_prefix}_rename_{draft_id}",
                use_container_width=True,
            ):
                session[_RENAME_CONFIRM_PREFIX + draft_id] = True
                st.rerun()
        with btn3:
            st.button(
                delete_label,
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
        context=context,
        widget_key_prefix=f"archive_list_{draft_id[:12]}",
    )


def render_saved_draft_library_page(
    st: Any,
    session: dict[str, Any],
    *,
    page_label_fn=None,
    developer_mode: bool = False,
) -> None:
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
        _render_saved_draft_library_page_body(
            st,
            session,
            page_label_fn=page_label_fn,
            developer_mode=developer_mode,
        )


def _render_saved_draft_library_page_body(
    st: Any,
    session: dict[str, Any],
    *,
    page_label_fn=None,
    developer_mode: bool = False,
) -> None:
    _persisted_library_context: dict[str, Any] | None = None
    try:
        from saved_draft_library_selection import prepare_saved_draft_library_active_selection

        _library_selection = prepare_saved_draft_library_active_selection(session)
        _persisted_library_context = _library_selection.get("linked_active_context") or _library_selection.get(
            "active_context"
        )
        if not isinstance(_persisted_library_context, dict):
            _persisted_library_context = None
    except ImportError:
        _library_selection = {}
        _persisted_library_context = None

    try:
        from suite_identity_guard import enforce_identity_after_state_apply

        enforce_identity_after_state_apply(
            session,
            reason="render_saved_draft_library_page",
            last_mutator="render_saved_draft_library_page",
            st=st,
            league_context=_persisted_library_context,
        )
    except ImportError:
        pass
    except RecursionError:
        pass
    # Shared-league materialize is owned by sync_uploaded_league_contexts_on_library_render
    # (warm-gated). Do not call materialize again here on every Library render.
    try:
        from fantasy_workspace_team_identity import apply_account_team_identity_to_session

        apply_account_team_identity_to_session(
            session,
            reason="render_saved_draft_library_page",
            context=_persisted_library_context,
        )
    except RecursionError:
        pass
    except ImportError:
        pass
    except Exception:
        pass
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
    try:
        from deployed_page_timing import mark_page_heading_visible

        mark_page_heading_visible(session, "Saved Draft Library")
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
        .ld-archive-badge-imported { background: #5c4d7d; color: #fff; }
        .ld-archive-badge-sim { background: #3d5a3d; color: #fff; }
        .ld-archive-badge-active { background: #2ecc71; color: #1a1a1a; }
        .ld-archive-badge { margin-right: 0.45rem; }
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
        .ld-archive-focus {
            border-color: #5dade2;
            box-shadow: 0 0 0 1px rgba(93,173,226,0.35);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Materialize owned shared leagues BEFORE prune/list so second accounts see
    # Live Draft Shared Leagues on the same Saved Draft Library render.
    try:
        from fantasy_shared_league_library_sync import (
            summarize_library_sync_for_banner,
            sync_uploaded_league_contexts_on_library_render,
        )

        library_sync_trace = sync_uploaded_league_contexts_on_library_render(session)
    except ImportError:
        library_sync_trace = {}
        summarize_library_sync_for_banner = None  # type: ignore[assignment,misc]

    prune_invisible_shared_league_state(session)
    try:
        from library_repair_scheduler import mark_library_dirty, run_gated_library_repairs

        # prepare_saved_draft_library_active_selection may have already marked repairs
        # complete before shared-league materialize. Force a second pass after sync so
        # Live Draft origin migration sees the canonical shared doc.
        if not (isinstance(library_sync_trace, dict) and library_sync_trace.get("skipped") == "warm_render"):
            mark_library_dirty(session, reason="post_shared_league_library_sync")
        repair_trace = run_gated_library_repairs(session, user_mutated=False)
        session["_library_repair_last_trace"] = dict(repair_trace or {})
        # Always evaluate/repair origin for visible cards — gated repair can skip on warm renders.
        try:
            from fantasy_league_context import (
                evaluate_origin_decisions_for_visible_archives,
                repair_archive_draft_types_from_contexts,
            )

            repair_archive_draft_types_from_contexts(session)
            evaluate_origin_decisions_for_visible_archives(session)
        except ImportError:
            pass
        prune_invisible_shared_league_state(session)
        try:
            from workflow_persist_guard import restore_active_draft_archive_selection

            restore_active_draft_archive_selection(session)
        except ImportError:
            pass
    except ImportError:
        pass

    try:
        from draft_library_manifest import (
            build_library_manifest,
            collect_library_content_clock_diagnostics,
            sync_library_manifest_from_cloud,
        )

        sync_library_manifest_from_cloud(session)
        build_library_manifest(session)
        if developer_mode:
            try:
                from page_diagnostics import record_page_diagnostic_section

                record_page_diagnostic_section(
                    session,
                    "Library content clocks",
                    collect_library_content_clock_diagnostics(session),
                )
            except ImportError:
                pass
    except ImportError:
        pass

    raw_archive_count = 0
    try:
        from draft_archive_state import list_draft_archives

        raw_archive_count = len(list_draft_archives(session))
    except ImportError:
        pass

    archives = list_visible_draft_archives(session)

    focus_draft_id = str(session.get("_saved_draft_library_focus_draft_id") or "").strip()
    if focus_draft_id:
        session.pop("_saved_draft_library_focus_draft_id", None)
    active = get_active_draft_archive(session)
    if active and not is_saved_draft_visible_to_session(session, active):
        clear_active_draft_archive(session)
        try:
            from fantasy_league_context import clear_active_league_context

            clear_active_league_context(session)
        except ImportError:
            pass
        active = None
    try:
        from saved_draft_library_selection import (
            prepare_saved_draft_library_active_selection,
            render_active_library_pair_diagnostics,
            saved_draft_card_is_active,
        )

        selection = prepare_saved_draft_library_active_selection(session)
        active = selection.get("active_archive")
        active_context = selection.get("linked_active_context")
        active_id = str(selection.get("active_draft_archive_id") or "")
        active_context_id = str(selection.get("persisted_active_context_id") or "")
        if developer_mode:
            try:
                from page_diagnostics import inline_diagnostics_enabled
            except ImportError:
                inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
            if inline_diagnostics_enabled(developer_mode):
                render_active_library_pair_diagnostics(st, session, developer_mode=developer_mode)
    except ImportError:
        active_context = get_active_league_context(session, respect_source_priority=False)
        active_id = str((active or {}).get("draft_id") or "")
        active_context_id = str((active_context or {}).get("league_context_id") or "")
        selection = None

    st.caption(
        "Only **intentionally saved drafts** appear here. "
        "Set one **Active Draft** (a saved draft you select) for Standings, Lineup, and Waiver Wire. "
        "Unsaved simulator or live boards stay in their workspace pages — use **Fantasy Context Source** toggles to point at them temporarily."
    )

    if developer_mode:
        render_persistence_probe_panel(st, session, developer_mode=developer_mode)
        try:
            from page_diagnostics import inline_diagnostics_enabled
        except ImportError:
            inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
        if inline_diagnostics_enabled(developer_mode):
            try:
                from suite_identity_guard import render_identity_guard_diagnostic_panel

                render_identity_guard_diagnostic_panel(
                    st,
                    session,
                    title="Saved Draft Library — account / workspace identity",
                )
            except ImportError:
                pass

    try:
        if callable(summarize_library_sync_for_banner):
            sync_banner = summarize_library_sync_for_banner(library_sync_trace if isinstance(library_sync_trace, dict) else {})
            if sync_banner:
                st.success(sync_banner)
    except Exception:
        pass

    try:
        from fantasy_league_context import render_draft_origin_repair_diagnostics

        render_draft_origin_repair_diagnostics(
            st,
            session,
            developer_mode=developer_mode,
        )
    except Exception:
        pass

    # Always-available origin migration log (answers: did repair run / why this league).
    try:
        from fantasy_league_context import ORIGIN_REPAIR_DECISIONS_KEY

        decisions = session.get(ORIGIN_REPAIR_DECISIONS_KEY)
        repair_trace = session.get("_library_repair_last_trace")
        if isinstance(decisions, list) or isinstance(repair_trace, dict):
            with st.expander("Origin repair log", expanded=False):
                st.caption(
                    "Per-league decisions from the latest Saved Draft Library origin migration."
                )
                if isinstance(repair_trace, dict):
                    st.write(
                        {
                            "repair_ran": bool(repair_trace.get("ran")),
                            "skipped": repair_trace.get("skipped"),
                            "steps": repair_trace.get("steps") or [],
                            "failures": repair_trace.get("failures") or [],
                        }
                    )
                if isinstance(decisions, list) and decisions:
                    st.json(decisions)
                else:
                    st.caption("No per-league origin decisions recorded on this render.")
    except Exception:
        pass

    try:
        from fantasy_league_invite_ui import (
            render_commissioner_invite_diagnostics_panel,
            render_commissioner_invite_panel,
            render_invite_flow_diagnostics_panel,
            render_pending_league_invites,
        )
    except ImportError as exc:
        if not session.get("_league_invite_ui_import_error"):
            session["_league_invite_ui_import_error"] = str(exc)
            st.warning(f"Shared league invite UI could not load: {exc}")
    else:
        try:
            render_pending_league_invites(st, session)
            render_commissioner_invite_panel(st, session)
            try:
                from page_diagnostics import inline_diagnostics_enabled
            except ImportError:
                inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
            if developer_mode and inline_diagnostics_enabled(developer_mode):
                render_invite_flow_diagnostics_panel(st, session)
                render_commissioner_invite_diagnostics_panel(st, session)
        except Exception as exc:
            st.error(f"Shared league invite UI failed while rendering: {exc}")

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

        def _persist_team_claim(_session: dict, _st: Any, *, reason: str = "") -> None:
            try:
                from baseball_persistent_state import force_save_baseball_state

                force_save_baseball_state(_st, reason=reason or "team_claimed")
            except Exception:
                pass

        render_active_league_team_claim(
            st,
            session,
            key_prefix="library_team_claim",
            persist_fn=_persist_team_claim,
        )
    except ImportError:
        pass
    st.divider()
    _render_fantasy_sync_section(st, session)
    st.divider()
    _render_persistence_diagnostics(st, session, developer_mode=developer_mode)

    st.markdown("##### Saved Drafts")
    st.metric("Saved drafts", len(archives))
    if raw_archive_count > len(archives):
        st.caption(
            f"Session has **{raw_archive_count}** archive(s); **{len(archives)}** visible after shared-league membership filter."
        )

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
        is_active = saved_draft_card_is_active(
            session,
            draft_id=draft_id,
            league_context_id=league_context_id,
            selection=selection,
        ) if selection is not None else (
            draft_id == active_id
            and (not active_context_id or not league_context_id or league_context_id == active_context_id)
        )
        is_focus = bool(focus_draft_id and draft_id == focus_draft_id and not is_active)
        player_n = archive_card_player_count(entry)
        team_n = archive_card_team_count(entry)
        is_real_league = _archive_card_is_real_league(entry, context)
        display_team = ""
        try:
            from fantasy_workspace_team_identity import resolve_archive_display_team

            display_team = resolve_archive_display_team(session, entry, context)
        except ImportError:
            display_team = str((context or {}).get("my_team_name") or entry.get("team_name") or "").strip()
        st.markdown(
            _saved_draft_card_html(
                entry,
                is_active=is_active,
                is_focused=is_focus,
                is_real_league=is_real_league,
                player_n=player_n,
                team_n=team_n,
                display_team=display_team,
                session=session,
                context=context if isinstance(context, dict) else None,
            ),
            unsafe_allow_html=True,
        )
        if not session.get("_library_main_content_marked"):
            session["_library_main_content_marked"] = True
            try:
                from deployed_page_timing import mark_active_league_visible, mark_main_content_interactive

                mark_active_league_visible(session, "Saved Draft Library")
                mark_main_content_interactive(session, "Saved Draft Library")
            except ImportError:
                pass
        if is_focus:
            st.caption(f"Focused league `{draft_id}` — use **⭐ Set Active League** to manage this league.")
        elif is_active:
            st.caption(
                "Active league — use **Manage this draft** in the **Active Draft** section above."
                if is_real_league
                else "Active draft — use **Manage this draft** in the **Active Draft** section above."
            )
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
    try:
        from page_diagnostics import render_consolidated_diagnostics

        render_consolidated_diagnostics(
            st,
            session,
            "Saved Draft Library",
            developer_mode=developer_mode,
        )
    except ImportError:
        pass
