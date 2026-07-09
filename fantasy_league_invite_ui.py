"""Saved Draft Library UI for shared league invites."""

from __future__ import annotations

from typing import Any

from fantasy_league_invites import (
    build_commissioner_invite_panel_trace,
    build_invite_flow_diagnostics,
    commissioner_invite_context,
    commissioner_invite_diagnostics,
    create_league_invite,
    decline_league_invite,
    is_league_commissioner,
    join_shared_league_from_invite,
    list_pending_invites_for_session,
    unclaimed_teams_for_invite,
)
from fantasy_shared_league_store import load_shared_league


def render_pending_league_invites(st: Any, session: dict[str, Any]) -> bool:
    """Surface pending shared-league invites at the top of Saved Draft Library."""
    pending = list_pending_invites_for_session(session)
    if not pending:
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
        teams = unclaimed_teams_for_invite(shared)
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

        pick = st.selectbox(
            "Choose your team",
            teams,
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
    """Invite status, league_id, team claims, and cloud_app_key for commissioner/invitee."""
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
            f"**is_commissioner:** {diag.get('is_commissioner_for_active_context')}"
        )
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
        team_claims = diag.get("team_claims")
        if team_claims:
            st.json({"team_claims": team_claims})
        invites = diag.get("league_invites")
        if invites:
            st.json({"league_invites": invites})
    return True


def render_commissioner_invite_diagnostics_panel(st: Any, session: dict[str, Any]) -> bool:
    """Always show invite-panel trace on Saved Draft Library (not dev-gated)."""
    with st.expander("Invite panel diagnostic (Saved Draft Library)", expanded=True):
        st.caption(
            "Always shown on **Saved Draft Library** (not Developer Mode). "
            "Explains why **Invite managers to this shared league** is visible or hidden."
        )
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
            ownership = row.get("team_ownership")
            if ownership:
                try:
                    st.json({"team_ownership": ownership})
                except Exception:
                    st.code(str(ownership))
            else:
                st.caption("team_ownership: —")
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
            "`commissioner_invite_context` returned a context. See **Invite panel diagnostic** above."
        )
        return False

    league_name = str(context.get("league_name") or context.get("display_name") or "Shared league").strip()
    last_sent = session.get("_last_commissioner_invite_sent")
    if isinstance(last_sent, dict) and str(last_sent.get("status") or "") == "pending":
        st.success(
            f"Invite sent to **{last_sent.get('invitee_workspace_id') or '—'}** for "
            f"**{last_sent.get('league_name') or league_name}** · "
            f"status **{last_sent.get('status') or 'pending'}** · "
            f"id `{last_sent.get('invite_id') or '—'}`"
        )
    with st.expander("Invite managers to this shared league", expanded=False):
        st.caption(
            f"Invite another account to join **{league_name}**. "
            "They will see the invite in their Saved Draft Library, claim a team, "
            "and link to the same canonical league — not a duplicate import."
        )
        target = st.text_input(
            "Workspace or account id",
            key="commissioner_invite_target",
            placeholder="e.g. ariel, coakley11",
            help="Use the invitee's workspace slug or account external id.",
        )
        if st.button("Send invite", key="commissioner_invite_send_btn", type="primary"):
            invite, err = create_league_invite(session, context, invitee_target=target)
            if err:
                st.error(err)
            elif invite:
                session["_last_commissioner_invite_sent"] = dict(invite)
                ws = str(invite.get("invitee_workspace_id") or target).strip()
                st.success(
                    f"Invite sent to **{ws}** for **{league_name}** · "
                    f"status **{invite.get('status') or 'pending'}** · "
                    f"id `{invite.get('invite_id') or '—'}`"
                )
                try:
                    from baseball_persistent_state import force_save_baseball_state

                    force_save_baseball_state(st, reason="league_invite_sent")
                except Exception:
                    pass
                st.rerun()
    return True
