"""Saved Draft Library UI for shared league invites."""

from __future__ import annotations

from typing import Any

from fantasy_league_invites import (
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


def render_commissioner_invite_panel(st: Any, session: dict[str, Any]) -> bool:
    """Let the league commissioner invite another workspace/account."""
    context = commissioner_invite_context(session)
    if not context:
        diag = commissioner_invite_diagnostics(session)
        visible_imported = 0
        try:
            from draft_archive_state import DRAFT_TYPE_IMPORTED
            from draft_archive_visibility import list_visible_draft_archives

            visible_imported = sum(
                1
                for entry in list_visible_draft_archives(session)
                if str(entry.get("draft_type") or "") == DRAFT_TYPE_IMPORTED
            )
        except ImportError:
            pass
        if int(diag.get("real_league_context_count") or 0) > 0:
            rows = diag.get("contexts") or []
            blocked = [
                row
                for row in rows
                if isinstance(row, dict) and not row.get("is_commissioner")
            ]
            if blocked:
                first = blocked[0]
                st.warning(
                    "Shared league invite controls are hidden because this account is not recognized as "
                    f"league commissioner for **{first.get('league_name') or 'your uploaded league'}**. "
                    f"Stored commissioner id: `{first.get('commissioner_user_id') or '—'}` · "
                    f"your account id: `{diag.get('account_user_id') or '—'}`. "
                    "Claim your upload team in this library, then refresh."
                )
        elif visible_imported > 0:
            st.warning(
                "Shared league invite controls are hidden because league context metadata is missing "
                f"for **{visible_imported}** uploaded league card(s). "
                f"Your account id: `{diag.get('account_user_id') or '—'}`. "
                "Refresh the page — the library should rebuild context from your saved upload."
            )
        return False
    uid = ""
    try:
        from fantasy_league_invites import _resolve_user_id

        uid = str(_resolve_user_id(session) or "").strip()
    except ImportError:
        pass
    if not is_league_commissioner(context, uid):
        return False

    league_name = str(context.get("league_name") or context.get("display_name") or "Shared league").strip()
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
                ws = str(invite.get("invitee_workspace_id") or target).strip()
                st.success(f"Invite sent to **{ws}** for **{league_name}**.")
                st.rerun()
    return True
