"""Saved Draft Library UI for shared league invites."""

from __future__ import annotations

from typing import Any

from fantasy_league_invites import (
    build_commissioner_invite_panel_trace,
    build_invite_flow_diagnostics,
    build_invite_submit_trace_snapshot,
    commissioner_invite_context,
    commissioner_invite_diagnostics,
    create_league_invite,
    decline_league_invite,
    is_league_commissioner,
    join_shared_league_from_invite,
    list_pending_invites_for_session,
    record_invite_submit_trace,
    resolve_invitee_target,
    unclaimed_teams_for_invite,
)
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_shared_league_store import load_shared_league


def _format_ownership_summary(ownership: dict[str, Any] | None) -> str:
    if not isinstance(ownership, dict) or not ownership:
        return "—"
    parts: list[str] = []
    for team, record in sorted(ownership.items()):
        if not isinstance(record, dict):
            continue
        owner = str(record.get("display_name") or record.get("user_id") or "—").strip()
        parts.append(f"{team} → {owner}")
    return "; ".join(parts) if parts else "—"


def _render_team_ownership_sync_section(st: Any, sync_diag: dict[str, Any] | None) -> None:
    """Show local session ownership vs canonical shared store."""
    diag = dict(sync_diag) if isinstance(sync_diag, dict) else {}
    comparison = dict(diag.get("comparison") or {})
    st.markdown("##### Team ownership (local vs shared)")
    st.markdown(
        f"- **league_id:** `{diag.get('league_id') or '—'}`  \n"
        f"- **shared doc found:** {diag.get('shared_doc_found')}  \n"
        f"- **local revision:** {int(diag.get('local_shared_revision') or 0)} · "
        f"**shared revision:** {int(diag.get('shared_doc_revision') or 0)}  \n"
        f"- **local claimed:** {int(comparison.get('local_claimed_count') or 0)} · "
        f"**shared claimed:** {int(comparison.get('shared_claimed_count') or 0)}  \n"
        f"- **local stale vs shared:** {comparison.get('local_stale_vs_shared')}"
    )
    only_shared = comparison.get("teams_only_in_shared") or []
    only_local = comparison.get("teams_only_in_local") or []
    diff_owner = comparison.get("teams_with_different_owner") or []
    if only_shared:
        st.warning(
            "Canonical shared store has team claims missing from local context: "
            + ", ".join(str(t) for t in only_shared)
            + ". Library auto-sync or **Set Active** should merge these."
        )
    elif comparison.get("local_stale_vs_shared"):
        st.warning("Shared document has newer ownership than local context.")
    elif diag.get("shared_doc_found"):
        st.caption("Local context matches canonical shared ownership.")
    if only_local:
        st.caption(
            "Local-only claims (not on shared doc): "
            + ", ".join(str(t) for t in only_local)
        )
    if diff_owner:
        st.error(
            "Owner mismatch on: "
            + ", ".join(str(t) for t in diff_owner)
        )
    st.caption(
        f"Local: {_format_ownership_summary(diag.get('local_team_ownership'))}  \n"
        f"Shared: {_format_ownership_summary(diag.get('shared_team_ownership'))}"
    )
    col_local, col_shared = st.columns(2)
    with col_local:
        st.caption("local team_ownership (session context)")
        st.json({"team_ownership": diag.get("local_team_ownership") or {}})
    with col_shared:
        st.caption("shared team_ownership (baseball_shared_leagues)")
        st.json({"team_ownership": diag.get("shared_team_ownership") or {}})


def _render_library_sync_trace_section(st: Any, trace: dict[str, Any] | None) -> None:
    raw = dict(trace) if isinstance(trace, dict) else {}
    if not raw.get("updated_at"):
        return
    st.markdown("##### Library auto-sync (this page load)")
    st.markdown(
        f"- **leagues checked:** {int(raw.get('leagues_checked') or 0)}  \n"
        f"- **leagues synced:** {int(raw.get('leagues_synced') or 0)}  \n"
        f"- **updated_at:** `{raw.get('updated_at') or '—'}`"
    )
    for row in raw.get("results") or []:
        if not isinstance(row, dict):
            continue
        if not row.get("auto_synced"):
            continue
        teams = ", ".join(str(t) for t in (row.get("teams_merged_from_shared") or []) if str(t).strip())
        st.success(
            f"Merged shared ownership for **{row.get('draft_name') or row.get('league_id') or 'league'}**"
            + (f" — {teams}" if teams else "")
        )


def _render_set_active_sync_trace_section(st: Any, trace: dict[str, Any] | None) -> None:
    raw = dict(trace) if isinstance(trace, dict) else {}
    if not raw.get("updated_at"):
        return
    st.markdown("##### Last Set Active shared sync")
    st.markdown(
        f"- **trigger:** `{raw.get('trigger') or '—'}`  \n"
        f"- **league_context_id:** `{raw.get('league_context_id') or '—'}`  \n"
        f"- **shared revision:** {int(raw.get('shared_revision_before') or 0)} → "
        f"{int(raw.get('shared_revision_after') or 0)}  \n"
        f"- **ownership changed:** {raw.get('synced')}"
    )
    if raw.get("synced"):
        st.success("Set Active pulled newer team ownership from the canonical shared league document.")
    else:
        st.caption("Set Active ran shared sync; ownership was already current.")
    _render_team_ownership_sync_section(st, raw.get("ownership_sync"))


def _render_last_invite_submit_section(st: Any, submit: dict[str, Any] | None) -> None:
    """Always show commissioner invite submit trace (placeholder when never submitted)."""
    snap = dict(submit) if isinstance(submit, dict) else {}
    st.markdown("##### Last invite submit")
    if not snap.get("updated_at"):
        st.caption(
            "No invite submit recorded yet. Use **Send invite** below; "
            "fields update on the same page run after submit."
        )
    st.markdown(
        f"- **button_clicked:** {snap.get('button_clicked') if snap.get('updated_at') else '—'}  \n"
        f"- **create_league_invite_called:** "
        f"{snap.get('create_league_invite_called') if snap.get('updated_at') else '—'}  \n"
        f"- **target:** `{snap.get('target_trimmed') or snap.get('target_raw') or '—'}`  \n"
        f"- **invite_id:** `{snap.get('invite_id') or '—'}`  \n"
        f"- **create_error:** {snap.get('create_error') or '—'}  \n"
        f"- **_last_invite_shared_push_ok:** "
        f"{snap.get('last_invite_shared_push_ok') if snap.get('updated_at') else '—'}  \n"
        f"- **_last_invite_shared_push_error:** "
        f"`{snap.get('last_invite_shared_push_error') or '—'}`  \n"
        f"- **league_invite_sent reason set:** "
        f"{snap.get('league_invite_sent_reason_set') if snap.get('updated_at') else '—'}  \n"
        f"- **persist_last_save_reason:** `{snap.get('persist_last_save_reason') or '—'}`"
    )
    if snap.get("updated_at"):
        with st.expander("Invite submit trace (full)", expanded=False):
            st.json(snap)


def render_pending_league_invites(st: Any, session: dict[str, Any]) -> bool:
    """Surface pending shared-league invites at the top of Saved Draft Library."""
    # Commissioner notices for responses — accepted/declined invites leave the library UI.
    try:
        from fantasy_league_invites import (
            list_commissioner_invite_response_notifications,
            mark_invite_response_notifications_seen,
        )

        notices = list_commissioner_invite_response_notifications(session)
        if notices:
            seen_keys: list[str] = []
            for notice in notices:
                msg = str(notice.get("message") or "").strip()
                if not msg:
                    continue
                kind = str(notice.get("kind") or "")
                if "declined" in kind:
                    st.warning(msg)
                else:
                    st.success(msg)
                seen_keys.append(str(notice.get("alert_key") or ""))
            if seen_keys:
                mark_invite_response_notifications_seen(session, seen_keys)
    except ImportError:
        pass

    # Refresh commissioner's last-sent invite banner from shared status (drop accepted/declined).
    last_sent = session.get("_last_commissioner_invite_sent")
    if isinstance(last_sent, dict):
        lid = str(last_sent.get("league_id") or "").strip()
        iid = str(last_sent.get("invite_id") or "").strip()
        if lid and iid:
            shared_doc = load_shared_league(lid) or {}
            for row in shared_doc.get("league_invites") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("invite_id") or "") != iid:
                    continue
                status = str(row.get("status") or "").strip()
                if status and status != "pending":
                    session.pop("_last_commissioner_invite_sent", None)
                else:
                    session["_last_commissioner_invite_sent"] = dict(row)
                break

    pending = list_pending_invites_for_session(session)
    if not pending:
        stranded = session.get("_suite_stranded_foreign_disk_draft")
        if stranded:
            st.info(
                "A foreign shared-league draft was removed from this account's library. "
                "If you were invited, check **Invite flow diagnostic** for pending invites "
                "from the canonical shared league document."
            )
        return False

    st.markdown("##### Shared league invites")
    for invite in pending:
        league_id = str(invite.get("league_id") or "").strip()
        invite_id = str(invite.get("invite_id") or "").strip()
        league_name = str(invite.get("league_name") or league_id).strip()
        invited_by = str(invite.get("invited_by_display") or "League commissioner").strip()
        key_base = f"invite_{invite_id}"

        st.info(
            f"You've been invited to join **{league_name}**. "
            f"Claim your team to add this shared league to your Saved Draft Library. "
            f"Invited by **{invited_by}**."
        )

        shared = load_shared_league(league_id) or {}
        teams = unclaimed_teams_for_invite(shared, session=session)
        if not teams:
            st.warning("No unclaimed teams remain in this league.")
            if st.button("Decline invite", key=f"{key_base}_decline_no_teams"):
                ok, err = decline_league_invite(session, league_id=league_id, invite_id=invite_id)
                if err:
                    st.error(err)
                else:
                    st.success("Invite declined.")
                    st.rerun()
            continue

        suggested = str(invite.get("suggested_team") or invite.get("claimed_team") or "").strip()
        default_idx = teams.index(suggested) if suggested in teams else 0
        pick = st.selectbox(
            "Choose your team",
            teams,
            index=default_idx,
            key=f"{key_base}_team_pick",
        )
        accept_col, decline_col = st.columns(2)
        with accept_col:
            if st.button("Accept invite", key=f"{key_base}_accept", type="primary"):
                entry, context, err = join_shared_league_from_invite(
                    session,
                    league_id=league_id,
                    invite_id=invite_id,
                    team_name=pick,
                )
                if err:
                    st.error(err)
                else:
                    title = str((entry or {}).get("draft_name") or league_name)
                    team = str((entry or {}).get("team_name") or pick)
                    st.success(
                        f"Joined **{title}** as **{team}**. "
                        "The league is now in your Saved Draft Library."
                    )
                    st.rerun()
        with decline_col:
            if st.button("Decline", key=f"{key_base}_decline"):
                ok, err = decline_league_invite(session, league_id=league_id, invite_id=invite_id)
                if err:
                    st.error(err)
                elif ok:
                    st.success("Invite declined.")
                    st.rerun()
        st.divider()
    return True


def render_invite_flow_diagnostics_panel(st: Any, session: dict[str, Any]) -> bool:
    """Invite status, league_id, team claims, and cloud_app_key (Developer Mode)."""
    try:
        from suite_workspace import can_show_developer_tools
    except ImportError:
        return False
    if not can_show_developer_tools(st=st):
        return False
    with st.expander("Invite flow diagnostic", expanded=False):
        try:
            diag = build_invite_flow_diagnostics(session)
        except Exception as exc:
            st.error(f"Invite flow diagnostic failed: {exc}")
            return True
        st.markdown(
            f"**current_user_id:** `{diag.get('current_user_id') or '—'}`  \n"
            f"**owner_user_id (commissioner):** `{diag.get('owner_user_id') or '—'}`  \n"
            f"**workspace_id:** `{diag.get('workspace_id') or '—'}`  \n"
            f"**cloud_app_key:** `{diag.get('cloud_app_key') or '—'}`  \n"
            f"**league_id:** `{diag.get('league_id') or '—'}`  \n"
            f"**pending_invites:** {int(diag.get('pending_invite_count') or 0)}  \n"
            f"**is_commissioner:** {diag.get('is_commissioner_for_active_context')}"
        )
        trace = diag.get("lookup_trace")
        if isinstance(trace, dict):
            st.caption(
                f"Lookup: inbox refs **{int(trace.get('inbox_ref_count') or 0)}** · "
                f"shared docs **{int(trace.get('shared_league_document_count') or 0)}** · "
                f"pending from shared scan **{int(trace.get('pending_from_shared_scan') or 0)}** · "
                f"pending from disk league_id **{int(trace.get('pending_from_disk_league_ids') or 0)}** · "
                f"disk drafts raw/visible **{int(trace.get('disk_draft_raw_count') or 0)}**/"
                f"**{int(trace.get('disk_draft_visible_count') or 0)}**"
            )
            if trace.get("disk_pollution_not_invite"):
                st.warning(
                    "Disk has a foreign shared-league draft (pollution), not an invite record. "
                    "Pending invites must exist in `baseball_shared_leagues.league_invites`."
                )
            if trace.get("last_invite_shared_push_error"):
                st.caption(
                    f"Last shared-league push error (commissioner session): "
                    f"`{trace['last_invite_shared_push_error']}`"
                )
            with st.expander("Invite lookup trace", expanded=int(diag.get("pending_invite_count") or 0) == 0):
                st.json(trace)
        pending = diag.get("pending_invites_for_session") or []
        st.markdown(f"**pending_invites:** {len(pending)}")
        if pending:
            st.json(pending)
        last_sent = diag.get("last_commissioner_invite_sent")
        if isinstance(last_sent, dict):
            st.markdown(
                f"**last_invite_sent:** `{last_sent.get('invite_id') or '—'}` · "
                f"status **{last_sent.get('status') or '—'}** · "
                f"to **{last_sent.get('invitee_workspace_id') or '—'}**"
            )
        _render_library_sync_trace_section(st, diag.get("library_sync_trace"))
        _render_set_active_sync_trace_section(st, diag.get("set_active_sync_trace"))
        _render_team_ownership_sync_section(st, diag.get("ownership_sync"))
        invites = diag.get("league_invites")
        if invites:
            st.json({"league_invites": invites})
        _render_last_invite_submit_section(st, diag.get("invite_submit_trace"))
    return True


def render_commissioner_invite_diagnostics_panel(st: Any, session: dict[str, Any]) -> bool:
    """Invite-panel trace on Saved Draft Library (Developer Mode)."""
    try:
        from suite_workspace import can_show_developer_tools
    except ImportError:
        return False
    if not can_show_developer_tools(st=st):
        return False
    with st.expander("Invite panel diagnostic (Saved Draft Library)", expanded=False):
        try:
            trace = build_commissioner_invite_panel_trace(session)
        except Exception as exc:
            st.error(f"Invite diagnostic trace failed: {exc}")
            return True

        st.markdown(
            f"**commissioner_invite_context:** "
            f"{'found' if trace.get('commissioner_invite_context_found') else 'None'}  \n"
            f"**Reason:** {trace.get('commissioner_invite_context_reason') or '—'}  \n"
            f"**session draft archives:** {int(trace.get('session_draft_archive_count') or 0)}  \n"
            f"**visible library cards:** {int(trace.get('visible_library_card_count') or 0)}  \n"
            f"**uploaded leagues in session:** {int(trace.get('uploaded_league_session_count') or 0)}  \n"
            f"**uploaded leagues on cards:** {int(trace.get('uploaded_league_card_count') or 0)}  \n"
            f"**current_user_id:** `{trace.get('current_user_id') or '—'}`  \n"
            f"**session_cloud_user_id:** `{trace.get('session_cloud_user_id') or '—'}`  \n"
            f"**session_auth_user_id:** `{trace.get('session_auth_user_id') or '—'}`  \n"
            f"**session_external_id:** `{trace.get('session_external_id') or '—'}`"
        )

        _render_last_invite_submit_section(st, trace.get("invite_submit_trace"))

        _render_library_sync_trace_section(st, trace.get("library_sync_trace"))
        _render_set_active_sync_trace_section(st, trace.get("set_active_sync_trace"))

        rows = trace.get("uploaded_leagues") or []
        if not rows:
            st.warning(
                "No library cards were traced. If you see a card below, report "
                "`session_draft_archive_count` vs `visible_library_card_count` from this panel."
            )
            return True

        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("draft_name") or row.get("draft_id") or "Library card").strip()
            st.markdown(f"##### {title}")
            st.markdown(
                f"- **draft_id:** `{row.get('draft_id') or '—'}`  \n"
                f"- **draft_type:** `{row.get('draft_type') or '—'}`  \n"
                f"- **league_context_id:** `{row.get('league_context_id') or '—'}`  \n"
                f"- **visible_on_library_card:** {row.get('visible_on_library_card')}  \n"
                f"- **looks_like_uploaded_league:** {row.get('looks_like_uploaded_league')}  \n"
                f"- **upload_detection_reason:** {row.get('upload_detection_reason') or '—'}  \n"
                f"- **team_count_hint:** {row.get('team_count_hint') or 0}  \n"
                f"- **context_exists:** {row.get('context_exists')}  \n"
                f"- **context_type:** `{row.get('context_type') or '—'}`  \n"
                f"- **my_team_name:** `{row.get('my_team_name') or '—'}`  \n"
                f"- **archive_team_name:** `{row.get('archive_team_name') or '—'}`  \n"
                f"- **metadata_source:** `{row.get('metadata_source') or '—'}`  \n"
                f"- **commissioner_user_id:** `{row.get('commissioner_user_id') or '—'}`  \n"
                f"- **upload_owner_candidate:** {row.get('upload_owner_candidate')}  \n"
                f"- **is_commissioner:** {row.get('is_commissioner')}  \n"
                f"- **would_select_for_invite:** {row.get('would_select_for_invite')}  \n"
                f"- **block_reason:** {row.get('block_reason') or '—'}"
            )
            _render_team_ownership_sync_section(st, row.get("ownership_sync"))

    return True


def render_commissioner_invite_panel(st: Any, session: dict[str, Any]) -> bool:
    """Let the league commissioner invite another workspace/account."""
    context = commissioner_invite_context(session)
    if not context:
        return False
    uid = ""
    try:
        from fantasy_league_invites import _resolve_user_id

        uid = str(_resolve_user_id(session) or "").strip()
    except ImportError:
        pass
    if not is_league_commissioner(context, uid):
        st.warning(
            "Invite controls are hidden because `is_league_commissioner` failed after "
            "`commissioner_invite_context` returned a context. See **Invite panel diagnostic** below."
        )
        return False

    league_name = str(context.get("league_name") or context.get("display_name") or "Shared league").strip()
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    last_sent = session.get("_last_commissioner_invite_sent")
    submit_err = str(session.get("_last_commissioner_invite_submit_error") or "").strip()
    submit_snap = build_invite_submit_trace_snapshot(session)
    if submit_err:
        st.error(submit_err)
    if isinstance(last_sent, dict) and str(last_sent.get("status") or "") == "pending":
        st.success(
            f"Invite sent to **{last_sent.get('invitee_workspace_id') or '—'}** for "
            f"**{last_sent.get('league_name') or league_name}** · "
            f"status **{last_sent.get('status') or 'pending'}** · "
            f"id `{last_sent.get('invite_id') or '—'}`"
        )
        push_ok = session.get("_last_invite_shared_push_ok")
        push_err = str(session.get("_last_invite_shared_push_error") or "").strip()
        if push_ok is False or push_err:
            st.warning(
                f"Shared league push failed or incomplete. "
                f"ok={push_ok} · error `{push_err or '—'}`"
            )
    if submit_snap.get("updated_at"):
        st.caption(
            f"Last submit: button_clicked={submit_snap.get('button_clicked')} · "
            f"create_called={submit_snap.get('create_league_invite_called')} · "
            f"invite_id=`{submit_snap.get('invite_id') or '—'}` · "
            f"push_ok={submit_snap.get('last_invite_shared_push_ok')}"
        )

    submitted = False
    target = ""
    with st.expander("Invite managers to this shared league", expanded=False):
        st.caption(
            f"Invite another account to join **{league_name}**. "
            "They will see the invite in their Saved Draft Library, claim a team, "
            "and link to the same canonical league — not a duplicate import."
        )
        with st.form("commissioner_invite_form", clear_on_submit=False):
            target = st.text_input(
                "Workspace or account id",
                key="commissioner_invite_target",
                placeholder="e.g. ariel, coakley11",
                help="Use the invitee's workspace slug or account external id.",
            )
            submitted = st.form_submit_button("Send invite", type="primary")

    if submitted:
        target_trimmed = str(target or "").strip()
        resolved = resolve_invitee_target(target_trimmed) if target_trimmed else {}
        record_invite_submit_trace(
            session,
            button_clicked=True,
            target_raw=target,
            target_trimmed=target_trimmed,
            resolved_target=resolved,
            context_league_id=league_id or None,
            create_league_invite_called=False,
            create_error=None,
            invite_id=None,
        )
        invite, err = create_league_invite(session, context, invitee_target=target_trimmed)
        record_invite_submit_trace(
            session,
            create_league_invite_called=True,
            create_error=err or None,
            invite_id=str(invite.get("invite_id") or "") if isinstance(invite, dict) else None,
            last_invite_shared_push_ok=session.get("_last_invite_shared_push_ok"),
            last_invite_shared_push_error=session.get("_last_invite_shared_push_error"),
            last_invite_shared_league_id=session.get("_last_invite_shared_league_id"),
        )
        if err:
            session["_last_commissioner_invite_submit_error"] = err
            st.error(err)
        elif invite:
            session.pop("_last_commissioner_invite_submit_error", None)
            session["_last_commissioner_invite_sent"] = dict(invite)
            ws = str(invite.get("invitee_workspace_id") or target_trimmed).strip()
            st.success(
                f"Invite sent to **{ws}** for **{league_name}** · "
                f"status **{invite.get('status') or 'pending'}** · "
                f"id `{invite.get('invite_id') or '—'}`"
            )
            push_ok = session.get("_last_invite_shared_push_ok")
            push_err = str(session.get("_last_invite_shared_push_error") or "").strip()
            if push_ok is False or push_err:
                st.warning(
                    f"Shared league push failed or incomplete. "
                    f"ok={push_ok} · error `{push_err or '—'}`"
                )
            saved = False
            try:
                from baseball_persistent_state import force_save_baseball_state

                saved = bool(force_save_baseball_state(st, reason="league_invite_sent"))
            except Exception as exc:
                record_invite_submit_trace(
                    session,
                    force_save_attempted=True,
                    force_save_ok=False,
                    force_save_error=str(exc),
                )
            persist_reason = str(session.get("_suite_persist_last_save_reason") or "").strip()
            record_invite_submit_trace(
                session,
                force_save_attempted=True,
                force_save_ok=saved,
                persist_last_save_reason=persist_reason or None,
                league_invite_sent_reason_set=bool(persist_reason == "league_invite_sent"),
            )
        else:
            msg = "Send invite returned no invite and no error."
            session["_last_commissioner_invite_submit_error"] = msg
            record_invite_submit_trace(session, create_error=msg)
            st.error(msg)
    return True
