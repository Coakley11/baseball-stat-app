"""Canonical per-workspace team identity for shared leagues."""

from __future__ import annotations

import copy
from typing import Any

from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import account_user_ids_match

TEAM_IDENTITY_TRACE_KEY = "_suite_team_identity_resolution_trace"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def session_account_identity(session: dict[str, Any]) -> tuple[str, str, str, str, str]:
    uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
    external = str(session.get("_suite_auth_external_id") or "").strip().lower()
    workspace = str(
        session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
    ).strip()
    email = str(session.get("_suite_auth_user_email") or "").strip().lower()
    email_local = email.split("@", 1)[0] if email else ""
    return uid, external, workspace, email, email_local


def build_account_aliases(
    session: dict[str, Any] | None = None,
    *,
    owner_user_id: str = "",
    owner_external_id: str = "",
    workspace_id: str = "",
) -> set[str]:
    if session:
        uid, external, workspace, email, email_local = session_account_identity(session)
    else:
        uid = str(owner_user_id or "").strip()
        external = str(owner_external_id or "").strip().lower()
        workspace = str(workspace_id or "").strip()
        email = ""
        email_local = ""
    aliases: set[str] = set()
    for value in (
        uid,
        external,
        workspace,
        workspace.lower() if workspace else "",
        email,
        email_local,
        f"user:{external}" if external else "",
        f"local:{external}" if external else "",
    ):
        token = str(value or "").strip()
        if token:
            aliases.add(token)
            aliases.add(token.lower())
    return aliases


def _ownership_record_matches_aliases(record: dict[str, Any], aliases: set[str]) -> bool:
    if not isinstance(record, dict) or not aliases:
        return False
    candidates = {
        str(record.get("user_id") or "").strip(),
        str(record.get("external_id") or "").strip().lower(),
        str(record.get("display_name") or "").strip().lower(),
        str(record.get("email") or "").strip().lower(),
        str(record.get("email") or "").strip().lower().split("@", 1)[0],
        str(record.get("invitee_external_id") or "").strip().lower(),
        str(record.get("invitee_workspace_id") or "").strip(),
        str(record.get("accepted_by_external_id") or "").strip().lower(),
        str(record.get("accepted_by_workspace_id") or "").strip(),
    }
    for candidate in candidates:
        if candidate and candidate in aliases:
            return True
    return False


def owned_team_from_ownership(
    ownership: dict[str, Any] | None,
    *,
    owner_user_id: str = "",
    aliases: set[str] | None = None,
) -> str:
    """Resolve one owned team from canonical team_ownership."""
    if not isinstance(ownership, dict) or not ownership:
        return ""
    uid = str(owner_user_id or "").strip()
    alias_set = set(aliases or set())
    exact_uid_matches: list[str] = []
    alias_claimed_matches: list[str] = []
    alias_unclaimed_matches: list[str] = []

    for team, record in ownership.items():
        team_name = str(team or "").strip()
        if not team_name or not isinstance(record, dict):
            continue
        stored_uid = str(record.get("user_id") or "").strip()
        if stored_uid and uid and account_user_ids_match(stored_uid, uid):
            exact_uid_matches.append(team_name)
            continue
        if not _ownership_record_matches_aliases(record, alias_set):
            continue
        if stored_uid:
            alias_claimed_matches.append(team_name)
        else:
            alias_unclaimed_matches.append(team_name)

    if exact_uid_matches:
        return sorted(exact_uid_matches)[0]
    if len(alias_claimed_matches) == 1:
        return alias_claimed_matches[0]
    if alias_claimed_matches:
        return sorted(alias_claimed_matches)[0]
    if len(alias_unclaimed_matches) == 1:
        return alias_unclaimed_matches[0]
    return ""


def owned_team_from_shared_doc(
    shared_doc: dict[str, Any] | None,
    session: dict[str, Any] | None = None,
    *,
    owner_user_id: str = "",
    owner_external_id: str = "",
    workspace_id: str = "",
) -> str:
    if not isinstance(shared_doc, dict):
        return ""
    ownership = shared_doc.get("team_ownership") or {}
    uid, external, workspace, _, _ = (
        session_account_identity(session) if session else (owner_user_id, owner_external_id, workspace_id, "", "")
    )
    aliases = build_account_aliases(
        session,
        owner_user_id=uid or owner_user_id,
        owner_external_id=external or owner_external_id,
        workspace_id=workspace or workspace_id,
    )
    return owned_team_from_ownership(
        ownership if isinstance(ownership, dict) else {},
        owner_user_id=uid or owner_user_id,
        aliases=aliases,
    )


def _is_commissioner_for_context(
    session: dict[str, Any],
    context: dict[str, Any],
    shared_doc: dict[str, Any] | None = None,
) -> bool:
    from fantasy_league_invites import is_league_commissioner

    uid, _, _, _, _ = session_account_identity(session)
    if not uid:
        return False
    meta = context.get("metadata") or {}
    commissioner = str(
        meta.get("commissioner_user_id")
        or (shared_doc or {}).get("commissioner_user_id")
        or ""
    ).strip()
    return bool(is_league_commissioner(context, uid) or account_user_ids_match(uid, commissioner))


def _claimed_team_from_accepted_invite(
    session: dict[str, Any],
    shared_doc: dict[str, Any] | None,
) -> str:
    from fantasy_league_invites import INVITE_STATUS_ACCEPTED
    from fantasy_shared_league_startup_sync import _record_matches_account

    if not isinstance(shared_doc, dict):
        return ""
    uid, external, workspace, _, _ = session_account_identity(session)
    invites = shared_doc.get("league_invites") or []
    if not isinstance(invites, list):
        return ""
    for invite in invites:
        if not isinstance(invite, dict):
            continue
        if str(invite.get("status") or "").strip() != INVITE_STATUS_ACCEPTED:
            continue
        if not _record_matches_account(
            invite,
            user_id=uid,
            external_id=external,
            workspace_id=workspace,
        ):
            continue
        return str(invite.get("claimed_team") or "").strip()
    return ""


def _shared_league_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    if league_id:
        return True
    return str(context.get("context_type") or "").strip() == "real_league"


def overlay_workspace_team_on_context(
    session: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    shared_doc: dict[str, Any] | None = None,
    trace_phase: str = "",
    record_trace: bool = True,
) -> dict[str, Any] | None:
    """Apply canonical ownership team; never let stale archive/context team bleed across accounts."""
    if not isinstance(context, dict):
        return context

    uid, external, workspace, _, _ = session_account_identity(session)
    pre_merge_team = str(context.get("my_team_name") or "").strip()
    out = copy.deepcopy(context)
    league_id = str(resolve_canonical_league_id(out) or "").strip()

    shared = shared_doc
    if shared is None and league_id:
        try:
            from fantasy_shared_league_store import load_shared_league

            loaded = load_shared_league(league_id)
            shared = loaded if isinstance(loaded, dict) else None
        except ImportError:
            shared = None

    ownership = {}
    if isinstance(shared, dict):
        raw = shared.get("team_ownership") or {}
        ownership = raw if isinstance(raw, dict) else {}
    if not ownership:
        try:
            from fantasy_shared_league_store import get_team_ownership_from_context

            ownership = get_team_ownership_from_context(out)
        except ImportError:
            ownership = {}

    aliases = build_account_aliases(session)
    ownership_team = owned_team_from_ownership(ownership, owner_user_id=uid, aliases=aliases)
    if not ownership_team and isinstance(shared, dict):
        ownership_team = owned_team_from_shared_doc(shared, session)

    invite_team = ""
    if not _is_commissioner_for_context(session, out, shared):
        invite_team = _claimed_team_from_accepted_invite(session, shared)

    resolved_team = ownership_team or invite_team
    if resolved_team:
        out["my_team_name"] = resolved_team
    elif _shared_league_context(out):
        out["my_team_name"] = ""

    post_merge_team = str(out.get("my_team_name") or "").strip()

    if record_trace and trace_phase:
        record_team_identity_trace(
            session,
            phase=trace_phase,
            authenticated_workspace=workspace,
            ownership_resolved_team=ownership_team or None,
            pre_merge_team=pre_merge_team or None,
            post_merge_team=post_merge_team or None,
        )
    return out


def record_team_identity_trace(session: dict[str, Any], *, phase: str, **fields: Any) -> None:
    trace = session.get(TEAM_IDENTITY_TRACE_KEY)
    if not isinstance(trace, dict):
        trace = {"updated_at": _utc_now_iso(), "steps": []}
    steps = trace.setdefault("steps", [])
    if not isinstance(steps, list):
        steps = []
        trace["steps"] = steps
    entry = {"phase": str(phase or "").strip(), "at": _utc_now_iso()}
    entry.update({k: v for k, v in fields.items() if v is not None and v != ""})
    steps.append(entry)
    trace["updated_at"] = _utc_now_iso()
    for key in (
        "authenticated_workspace",
        "ownership_resolved_team",
        "pre_merge_team",
        "post_merge_team",
        "active_archive_team",
        "final_library_team",
        "final_fantasy_lineup_team",
    ):
        if key in entry:
            trace[key] = entry[key]
    session[TEAM_IDENTITY_TRACE_KEY] = trace


def get_team_identity_trace(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(TEAM_IDENTITY_TRACE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _load_shared_doc_for_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    if not league_id:
        return None
    try:
        from fantasy_shared_league_store import load_shared_league

        loaded = load_shared_league(league_id)
        return loaded if isinstance(loaded, dict) else None
    except ImportError:
        return None


def _raw_live_draft_participant_team(
    session: dict[str, Any],
    room: dict[str, Any] | None,
) -> str:
    """Read authoritative live-draft participant evidence only — no preference validation."""
    try:
        from draft_room_participant_state import active_participant_team

        team = str(active_participant_team(session) or "").strip()
        if team:
            return team
    except ImportError:
        pass

    if not isinstance(room, dict):
        room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return ""

    try:
        from live_draft_team_ownership import load_shared_participants

        participants = load_shared_participants(session)
        pid = str(session.get("draft_room_participant_id") or "").strip()
        if pid and pid in participants:
            meta = participants.get(pid) or {}
            if isinstance(meta, dict):
                team = str(meta.get("assigned_team") or "").strip()
                if team:
                    return team
    except ImportError:
        pass

    membership = session.get("draft_room_participant_membership")
    if isinstance(membership, dict):
        pid = str(session.get("draft_room_participant_id") or "").strip()
        if pid:
            slot = membership.get(pid)
            if isinstance(slot, dict):
                team = str(slot.get("assigned_team") or "").strip()
                if team:
                    return team
    return ""


def _team_from_live_draft_participants(
    session: dict[str, Any],
    room: dict[str, Any] | None,
) -> str:
    """Resolve team from live-draft participant membership only."""
    return _raw_live_draft_participant_team(session, room)


def _local_team_preference_allowed(
    session: dict[str, Any],
    team: str,
    *,
    shared_doc: dict[str, Any] | None,
    context: dict[str, Any] | None,
    participant_team: str = "",
) -> bool:
    candidate = str(team or "").strip()
    if not candidate:
        return False
    uid, _, _, _, _ = session_account_identity(session)
    if isinstance(shared_doc, dict):
        owned = owned_team_from_shared_doc(shared_doc, session)
        if owned and owned == candidate:
            return True
    if isinstance(context, dict) and uid:
        try:
            from fantasy_league_team_ownership import owned_team_for_user

            owned_ctx = str(owned_team_for_user(context, uid) or "").strip()
            if owned_ctx and owned_ctx == candidate:
                return True
        except ImportError:
            pass
    participant = str(participant_team or "").strip()
    return bool(participant and participant == candidate)


def resolve_current_account_team_for_live_draft_and_league(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
) -> str:
    """
    Canonical team for the signed-in browser — never commissioner/host/first-team fallback.

    Priority: auth identity → live-draft participant → canonical team_ownership →
    same-account local preference.
    """
    uid, external, workspace, _, _ = session_account_identity(session)
    if room is None:
        live = session.get("live_draft_room")
        room = live if isinstance(live, dict) else None

    if shared_doc is None and isinstance(context, dict):
        shared_doc = _load_shared_doc_for_context(context)
    if shared_doc is None:
        try:
            from fantasy_league_context import get_active_league_context

            # Never resolve via effective/temporary context here — that recurses through
            # get_effective_fantasy_context → my-team → this function.
            active_ctx = get_active_league_context(session, respect_source_priority=False)
            if isinstance(active_ctx, dict):
                shared_doc = _load_shared_doc_for_context(active_ctx)
                if context is None:
                    context = active_ctx
        except ImportError:
            pass

    # Temporary Live Draft room teams — Active Draft ownership must not win unless
    # that team is actually seated at this board (Team 1 vs Team X/Team Y leak).
    room_teams: list[str] = []
    if isinstance(room, dict):
        raw_teams = room.get("teams")
        if isinstance(raw_teams, list):
            room_teams = [str(t).strip() for t in raw_teams if str(t).strip()]

    def _on_this_board(team: str) -> bool:
        t = str(team or "").strip()
        if not t:
            return False
        return (not room_teams) or (t in room_teams)

    ownership_team = ""
    if isinstance(shared_doc, dict):
        ownership_team = owned_team_from_shared_doc(shared_doc, session)
    if not ownership_team and isinstance(context, dict):
        overlaid = overlay_workspace_team_on_context(
            session,
            context,
            shared_doc=shared_doc,
            trace_phase="resolve_current_account_team",
            record_trace=False,
        )
        if isinstance(overlaid, dict):
            ownership_team = str(overlaid.get("my_team_name") or "").strip()
    if ownership_team and not _on_this_board(ownership_team):
        ownership_team = ""

    participant_team = _raw_live_draft_participant_team(session, room)
    if participant_team and not _on_this_board(participant_team):
        participant_team = ""

    if ownership_team:
        resolved = ownership_team
        source = "canonical_team_ownership"
    elif participant_team:
        resolved = participant_team
        source = "live_draft_participant"
    else:
        resolved = ""
        source = ""

    for candidate in (
        str(session.get("live_draft_my_team") or "").strip(),
        str(session.get("draft_room_participant_team") or "").strip(),
        str(session.get("room_your_team") or "").strip(),
    ):
        if resolved:
            break
        if candidate and _on_this_board(candidate) and _local_team_preference_allowed(
            session,
            candidate,
            shared_doc=shared_doc if isinstance(shared_doc, dict) else None,
            context=context if isinstance(context, dict) else None,
            participant_team=participant_team,
        ):
            resolved = candidate
            source = "local_preference"
            break

    if not resolved and isinstance(context, dict) and uid:
        try:
            from fantasy_league_invites import is_league_commissioner

            if is_league_commissioner(context, uid):
                commissioner_team = str(context.get("my_team_name") or "").strip()
                if _on_this_board(commissioner_team):
                    resolved = commissioner_team
                    source = "commissioner_context"
        except ImportError:
            pass

    if not resolved and room_teams:
        # Solo temporary boards: keep identity on the live room, never Active Draft Team 1.
        cfg = room.get("config") if isinstance(room, dict) and isinstance(room.get("config"), dict) else {}
        for key in ("user_team", "your_team"):
            cfg_team = str(cfg.get(key) or "").strip()
            if cfg_team and _on_this_board(cfg_team):
                resolved = cfg_team
                source = "live_room_config"
                break
        if not resolved:
            resolved = room_teams[0]
            source = "live_room_first_team"

    if resolved:
        record_team_identity_trace(
            session,
            phase="resolve_current_account_team_for_live_draft_and_league",
            authenticated_workspace=workspace,
            ownership_resolved_team=ownership_team or None,
            post_merge_team=resolved,
            auth_user_id=uid or None,
            auth_external_id=external or None,
            resolution_source=source or None,
        )
    return resolved


# Bound to a Streamlit selectbox on Live Draft Room — cannot be written after widget render.
_LIVE_DRAFT_MY_TEAM_WIDGET_KEY = "live_draft_my_team"


def _set_session_key_unless_widget_locked(
    session: dict[str, Any],
    key: str,
    value: Any,
) -> str:
    """Set session[key]=value, skipping when Streamlit already owns the key as a widget."""
    if session.get(key) == value:
        return "unchanged"
    try:
        session[key] = value
        return "set"
    except Exception as exc:
        # StreamlitAPIException: "cannot be modified after the widget with key ... is instantiated"
        name = type(exc).__name__
        msg = str(exc).lower()
        if name == "StreamlitAPIException" or "widget with key" in msg or "already been created" in msg:
            return "skipped_widget_locked"
        raise


def apply_account_team_identity_to_session(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Sync account-local team fields after restore/hydration — never mutate canonical rosters."""
    if room is None:
        live = session.get("live_draft_room")
        room = live if isinstance(live, dict) else None
    if context is None:
        try:
            from fantasy_league_context import get_active_league_context

            # Saved Active Draft only — not ephemeral Live/Simulator effective context.
            context = get_active_league_context(session, respect_source_priority=False)
        except ImportError:
            context = None

    team = resolve_current_account_team_for_live_draft_and_league(
        session,
        room=room,
        context=context,
    )
    out: dict[str, Any] = {"team": team, "applied": bool(team), "reason": str(reason or "").strip()}
    if not team:
        return out

    session["draft_room_participant_team"] = team
    session["room_your_team"] = team
    # Widget key: set only when Streamlit has not already instantiated the selectbox.
    out["live_draft_my_team_set"] = _set_session_key_unless_widget_locked(
        session,
        _LIVE_DRAFT_MY_TEAM_WIDGET_KEY,
        team,
    )

    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        cfg["user_team"] = team
        cfg["your_team"] = team
        room["config"] = cfg
        session["live_draft_room"] = room

    membership = session.get("draft_room_participant_membership")
    pid = str(session.get("draft_room_participant_id") or "").strip()
    if isinstance(membership, dict) and pid:
        slot = dict(membership.get(pid) or {})
        slot["participant_id"] = pid
        slot["assigned_team"] = team
        membership[pid] = slot
        session["draft_room_participant_membership"] = membership

    # While a temporary Live Draft owns fantasy context, do not mutate Active Draft
    # / shared-league contexts with the practice-board team (or vice versa).
    temporary_live = False
    if isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused"):
        temporary_live = True
    try:
        from fantasy_context_source import SOURCE_LIVE_DRAFT, resolve_fantasy_context_source

        temporary_live = temporary_live or (
            resolve_fantasy_context_source(session).kind == SOURCE_LIVE_DRAFT
        )
    except ImportError:
        pass

    if isinstance(context, dict) and not temporary_live:
        shared_doc = _load_shared_doc_for_context(context)
        updated = overlay_workspace_team_on_context(
            session,
            context,
            shared_doc=shared_doc,
            trace_phase="apply_account_team_identity_to_session",
            record_trace=True,
        )
        if isinstance(updated, dict) and str(updated.get("my_team_name") or "").strip():
            try:
                from fantasy_league_context import upsert_league_context

                upsert_league_context(session, updated, mark_persist_authoritative=False)
            except ImportError:
                pass

    if not temporary_live:
        try:
            from draft_archive_state import get_active_draft_archive
            from fantasy_league_context import get_league_context_for_archive

            entry = get_active_draft_archive(session)
            if isinstance(entry, dict):
                ctx_for_archive = get_league_context_for_archive(session, entry)
                if isinstance(ctx_for_archive, dict):
                    ctx_for_archive = overlay_workspace_team_on_context(
                        session,
                        ctx_for_archive,
                        trace_phase="apply_account_team_identity_active_archive",
                        record_trace=False,
                    )
                    if isinstance(ctx_for_archive, dict):
                        from fantasy_league_context import upsert_league_context

                        upsert_league_context(session, ctx_for_archive, mark_persist_authoritative=False)
        except ImportError:
            pass

    out["applied"] = True
    return out


def detect_account_team_mismatch(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """True when displayed/local team disagrees with canonical account team."""
    expected = resolve_current_account_team_for_live_draft_and_league(
        session,
        room=room,
        context=context,
    )
    if not expected:
        return False, []

    reasons: list[str] = []
    observed = {
        "draft_room_participant_team": str(session.get("draft_room_participant_team") or "").strip(),
        "room_your_team": str(session.get("room_your_team") or "").strip(),
    }
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        cfg = dict(live.get("config") or {})
        observed["room_config_team"] = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()

    if isinstance(context, dict):
        observed["context_my_team"] = str(context.get("my_team_name") or "").strip()
    else:
        try:
            from fantasy_league_context import get_active_league_context

            active = get_active_league_context(session)
            if isinstance(active, dict):
                observed["context_my_team"] = str(active.get("my_team_name") or "").strip()
        except ImportError:
            pass

    for field, value in observed.items():
        if value and value != expected:
            reasons.append(f"{field}={value} expected={expected}")
    return bool(reasons), reasons


def resolve_archive_display_team(
    session: dict[str, Any],
    archive_entry: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> str:
    """Team label for Saved Draft Library cards.

    Uses only archive / shared-league ownership for THIS draft.
    Never falls back to temporary Live Draft session widgets
    (`live_draft_my_team`, `room_your_team`, `resolve_current_account_team_for_live_draft_and_league`).
    """
    if not isinstance(archive_entry, dict):
        return ""
    if context is None:
        try:
            from fantasy_league_context import get_league_context_for_archive

            context = get_league_context_for_archive(session, archive_entry)
        except ImportError:
            context = None

    # 1) Shared-league ownership for THIS archive's league (account → team mapping).
    shared = _load_shared_doc_for_context(context) if isinstance(context, dict) else None
    owned = owned_team_from_shared_doc(shared, session) if isinstance(shared, dict) else ""
    if owned:
        return owned
    if isinstance(context, dict):
        try:
            from fantasy_shared_league_store import get_team_ownership_from_context

            ownership = get_team_ownership_from_context(context)
        except ImportError:
            ownership = {}
        if isinstance(ownership, dict) and ownership:
            uid, _, _, _, _ = session_account_identity(session)
            owned = owned_team_from_ownership(
                ownership,
                owner_user_id=uid,
                aliases=build_account_aliases(session),
            )
            if owned:
                return owned

    archive_team = ""
    for key in ("my_team", "claimed_team", "team_name", "owner_team"):
        archive_team = str(archive_entry.get(key) or "").strip()
        if archive_team:
            break

    ctx_team = ""
    if isinstance(context, dict):
        ctx_team = str(context.get("my_team_name") or "").strip()

    # Reject temporary Live Draft teams leaking into archive cards.
    live_room = session.get("live_draft_room") if isinstance(session, dict) else None
    live_teams: set[str] = set()
    if isinstance(live_room, dict):
        for t in list(live_room.get("teams") or []) + list((live_room.get("config") or {}).get("teams") or []):
            name = str(t or "").strip()
            if name:
                live_teams.add(name)
    if (
        archive_team
        and ctx_team
        and live_teams
        and ctx_team in live_teams
        and ctx_team != archive_team
    ):
        return archive_team

    # 2) League-context team for this archive only (may already be ownership-overlaid by caller).
    if ctx_team:
        return ctx_team

    # 3) Permanent fields stored on the archive row itself.
    return archive_team


def resolve_final_fantasy_lineup_team(session: dict[str, Any]) -> str:
    try:
        from fantasy_league_context import get_active_league_context

        context = get_active_league_context(session, respect_source_priority=True)
    except ImportError:
        context = None
    team = resolve_current_account_team_for_live_draft_and_league(session, context=context)
    if team:
        return team
    if isinstance(context, dict):
        return str(context.get("my_team_name") or "").strip()
    return ""


def resolve_final_rendered_context_teams(
    session: dict[str, Any],
    *,
    draft_id: str = "",
) -> dict[str, Any]:
    """Final teams as library + lineup pages would render after full resolution."""
    from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, get_draft_archive, list_draft_archives

    uid, external, workspace, _, _ = session_account_identity(session)
    active_id = str(draft_id or session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    entry = get_draft_archive(session, active_id) if active_id else None
    if not isinstance(entry, dict):
        archives = list_draft_archives(session)
        entry = archives[0] if archives else None

    context = None
    if isinstance(entry, dict):
        try:
            from fantasy_league_context import get_league_context_for_archive

            context = get_league_context_for_archive(session, entry)
        except ImportError:
            context = None

    ownership_team = ""
    if isinstance(context, dict):
        league_id = str(resolve_canonical_league_id(context) or "").strip()
        if league_id:
            try:
                from fantasy_shared_league_store import load_shared_league

                shared = load_shared_league(league_id)
            except ImportError:
                shared = None
            if isinstance(shared, dict):
                ownership_team = owned_team_from_shared_doc(shared, session)

    library_team = resolve_archive_display_team(session, entry if isinstance(entry, dict) else None, context)
    lineup_team = resolve_final_fantasy_lineup_team(session)
    active_archive_team = str((entry or {}).get("team_name") or "").strip() if isinstance(entry, dict) else ""

    result = {
        "authenticated_workspace": workspace,
        "ownership_resolved_team": ownership_team or None,
        "pre_merge_team": None,
        "post_merge_team": str((context or {}).get("my_team_name") or "").strip() or None,
        "active_archive_team": active_archive_team or None,
        "final_library_team": library_team or None,
        "final_fantasy_lineup_team": lineup_team or None,
        "auth_user_id": uid or None,
        "auth_external_id": external or None,
        "draft_id": active_id or None,
    }
    record_team_identity_trace(session, phase="final_rendered_context", **result)
    return result
