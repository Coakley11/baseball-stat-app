"""Shared uploaded league invites — commissioner invite, inbox, accept + team claim."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    SOURCE_IMPORTED_DRAFT,
    get_league_context,
    upsert_league_context,
)
from fantasy_league_identity import (
    compute_draft_fingerprint,
    ensure_league_identity,
    resolve_canonical_league_id,
)
from fantasy_league_team_ownership import (
    account_user_ids_match,
    assign_team_owner_to_context,
    get_team_ownership,
    owned_team_for_user,
)
from fantasy_shared_league_store import (
    load_shared_league,
    push_league_context_to_shared,
    sync_context_with_shared_store,
)

WORKFLOW_KEY_LEAGUE_INVITES = "league_invites"
INVITE_INBOX_FILENAME = "league_invite_inbox.json"

INVITE_STATUS_PENDING = "pending"
INVITE_STATUS_ACCEPTED = "accepted"
INVITE_STATUS_DECLINED = "declined"
INVITE_STATUS_REVOKED = "revoked"
INVITE_STATUS_EXPIRED = "expired"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_user_id(session: dict[str, Any] | None = None) -> str:
    uid = ""
    try:
        from suite_user import get_account_user_id

        uid = str(get_account_user_id() or "").strip()
    except ImportError:
        pass
    if uid:
        return uid
    if isinstance(session, dict):
        for key in ("_suite_cloud_user_id", "_suite_auth_user_id"):
            val = str(session.get(key) or "").strip()
            if val:
                return val
    try:
        import streamlit as st  # noqa: WPS433

        ss = st.session_state
        for key in ("_suite_cloud_user_id", "_suite_auth_user_id"):
            val = str(ss.get(key) or "").strip()
            if val:
                return val
    except Exception:
        pass
    return ""


def _resolve_external_id() -> str:
    try:
        from suite_user import get_external_user_id

        return str(get_external_user_id() or "").strip().lower()
    except ImportError:
        return ""


def _resolve_display_name() -> str:
    try:
        from suite_user import get_display_name

        return str(get_display_name() or "").strip()
    except ImportError:
        return ""


def _resolve_workspace_id(session: dict[str, Any] | None = None) -> str:
    if isinstance(session, dict):
        for key in ("_suite_owned_workspace_id", "_suite_active_workspace_id"):
            ws = str(session.get(key) or "").strip()
            if ws:
                return ws
    try:
        from suite_workspace import get_active_workspace_id

        return str(get_active_workspace_id() or "").strip()
    except ImportError:
        return ""


def _inbox_path(workspace_id: str) -> Path:
    from suite_workspace import workspace_dir

    return workspace_dir(workspace_id) / INVITE_INBOX_FILENAME


def _read_inbox(workspace_id: str) -> list[dict[str, Any]]:
    ws = str(workspace_id or "").strip()
    if not ws:
        return []
    path = _inbox_path(ws)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    invites = raw.get("invites") if isinstance(raw, dict) else raw
    if not isinstance(invites, list):
        return []
    return [dict(x) for x in invites if isinstance(x, dict)]


def _write_inbox(workspace_id: str, invites: list[dict[str, Any]]) -> None:
    ws = str(workspace_id or "").strip()
    if not ws:
        return
    path = _inbox_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"invites": invites, "updated_at": _utc_now_iso()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_invite_to_inbox(
    workspace_id: str,
    *,
    invite_id: str,
    league_id: str,
    league_name: str = "",
) -> None:
    ws = str(workspace_id or "").strip()
    invite_id = str(invite_id or "").strip()
    league_id = str(league_id or "").strip()
    if not ws or not invite_id or not league_id:
        return
    invites = _read_inbox(ws)
    for row in invites:
        if str(row.get("invite_id") or "") == invite_id and str(row.get("league_id") or "") == league_id:
            return
    invites.append(
        {
            "invite_id": invite_id,
            "league_id": league_id,
            "league_name": str(league_name or "").strip(),
            "added_at": _utc_now_iso(),
        }
    )
    _write_inbox(ws, invites)


def remove_invite_from_inbox(workspace_id: str, *, invite_id: str, league_id: str) -> None:
    ws = str(workspace_id or "").strip()
    if not ws:
        return
    invites = [
        row
        for row in _read_inbox(ws)
        if not (
            str(row.get("invite_id") or "") == str(invite_id or "").strip()
            and str(row.get("league_id") or "") == str(league_id or "").strip()
        )
    ]
    _write_inbox(ws, invites)


def resolve_invitee_target(target: str) -> dict[str, str]:
    """Resolve workspace/account slug to invitee identity fields."""
    from suite_workspace import normalize_workspace_id
    from suite_workspace_registry import _read_registry

    slug = normalize_workspace_id(str(target or "").strip())
    reg = _read_registry()
    by_owner = reg.get("by_owner") if isinstance(reg.get("by_owner"), dict) else {}
    for row in by_owner.values():
        if not isinstance(row, dict):
            continue
        ws = str(row.get("workspace_id") or "").strip()
        ext = str(row.get("owner_external_id") or "").strip().lower()
        if slug and (slug == ws or slug == ext):
            return {
                "invitee_workspace_id": ws or slug,
                "invitee_user_id": str(row.get("owner_user_id") or "").strip(),
                "invitee_external_id": ext or slug,
            }
    return {
        "invitee_workspace_id": slug,
        "invitee_user_id": "",
        "invitee_external_id": slug,
    }


def get_league_invites(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    workflow = context.get("workflow") or {}
    raw = workflow.get(WORKFLOW_KEY_LEAGUE_INVITES) or []
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def _set_league_invites(context: dict[str, Any], invites: list[dict[str, Any]]) -> None:
    workflow = dict(context.get("workflow") or {})
    workflow[WORKFLOW_KEY_LEAGUE_INVITES] = copy.deepcopy(invites)
    context["workflow"] = workflow


def get_commissioner_user_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    meta = context.get("metadata") or {}
    return str(meta.get("commissioner_user_id") or "").strip()


def _joined_via_invite(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    meta = context.get("metadata") or {}
    return bool(meta.get("joined_via_invite"))


def is_upload_commissioner_candidate(context: dict[str, Any] | None, user_id: str = "") -> bool:
    """True when the account uploaded the league and owns ``my_team_name`` (not invite join)."""
    if not isinstance(context, dict):
        return False
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return False
    if _joined_via_invite(context):
        return False
    uid = str(user_id or _resolve_user_id()).strip()
    if not uid:
        return False
    my_team = str(context.get("my_team_name") or "").strip()
    if not my_team:
        return False
    record = get_team_ownership(context).get(my_team) or {}
    stored_uid = str(record.get("user_id") or "").strip()
    if stored_uid and account_user_ids_match(stored_uid, uid):
        return True
    meta = context.get("metadata") or {}
    if str(meta.get("source") or "") == SOURCE_IMPORTED_DRAFT and not stored_uid:
        rosters = context.get("league_rosters") or {}
        if isinstance(rosters, dict) and my_team in rosters:
            return True
    return False


def repair_commissioner_identity(
    context: dict[str, Any],
    session: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Backfill commissioner_user_id when upload owner id drifted after account fixes."""
    if not isinstance(context, dict):
        return context, False
    uid = _resolve_user_id(session)
    if not uid:
        return context, False
    changed = False
    my_team = str(context.get("my_team_name") or "").strip()
    meta = dict(context.get("metadata") or {})
    if (
        str(context.get("context_type") or "") == CONTEXT_TYPE_REAL_LEAGUE
        and not _joined_via_invite(context)
        and str(meta.get("source") or "") == SOURCE_IMPORTED_DRAFT
        and my_team
    ):
        ownership = get_team_ownership(context)
        record = ownership.get(my_team) or {}
        if not str(record.get("user_id") or "").strip():
            context = assign_team_owner_to_context(context, my_team)
            changed = True
            if isinstance(session, dict):
                from fantasy_league_context import upsert_league_context

                context = upsert_league_context(session, context)
    if not is_upload_commissioner_candidate(context, uid):
        return context, changed
    try:
        from fantasy_league_team_ownership import repair_upload_team_ownership_identity

        context, ownership_changed = repair_upload_team_ownership_identity(context, session)
        changed = changed or ownership_changed
    except ImportError:
        pass
    commissioner = get_commissioner_user_id(context)
    if commissioner and account_user_ids_match(commissioner, uid):
        return context, changed
    meta = dict(context.get("metadata") or {})
    meta["commissioner_user_id"] = uid
    context["metadata"] = meta
    changed = True
    if isinstance(session, dict):
        from fantasy_league_context import upsert_league_context

        context = upsert_league_context(session, context)
        try:
            from workflow_persist_guard import mark_workflow_persist_authoritative

            mark_workflow_persist_authoritative(session)
        except ImportError:
            pass
    return context, changed


def is_league_commissioner(context: dict[str, Any] | None, user_id: str = "") -> bool:
    if not isinstance(context, dict):
        return False
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return False
    uid = str(user_id or _resolve_user_id()).strip()
    if not uid:
        return False
    commissioner = get_commissioner_user_id(context)
    if commissioner and account_user_ids_match(commissioner, uid):
        return True
    if is_upload_commissioner_candidate(context, uid):
        return True
    if commissioner or _joined_via_invite(context):
        return False
    ownership = get_team_ownership(context)
    if not ownership:
        return False
    earliest_team = ""
    earliest_ts = ""
    for team, record in ownership.items():
        if not account_user_ids_match(str(record.get("user_id") or "").strip(), uid):
            continue
        ts = str(record.get("assigned_at") or "")
        if not earliest_ts or ts < earliest_ts:
            earliest_ts = ts
            earliest_team = str(team)
    return bool(earliest_team)


def _invite_matches_user(invite: dict[str, Any], *, user_id: str, external_id: str, workspace_id: str) -> bool:
    if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
        return False
    invite_uid = str(invite.get("invitee_user_id") or "").strip()
    invite_ext = str(invite.get("invitee_external_id") or "").strip().lower()
    invite_ws = str(invite.get("invitee_workspace_id") or "").strip()
    if invite_uid and user_id and invite_uid == user_id:
        return True
    if invite_ext and external_id and invite_ext == external_id:
        return True
    if invite_ws and workspace_id and invite_ws == workspace_id:
        return True
    return False


def _generate_invite_id() -> str:
    return f"inv_{uuid.uuid4().hex[:12]}"


def _find_invite(invites: list[dict[str, Any]], invite_id: str) -> dict[str, Any] | None:
    iid = str(invite_id or "").strip()
    for row in invites:
        if str(row.get("invite_id") or "") == iid:
            return row
    return None


def create_league_invite(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    invitee_target: str,
) -> tuple[dict[str, Any] | None, str]:
    """Commissioner invites another account/workspace to join a shared uploaded league."""
    if not isinstance(context, dict):
        return None, "League context is required."
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return None, "Only uploaded/imported leagues support invites."
    uid = _resolve_user_id(session)
    if not uid:
        return None, "Sign in to invite other managers."
    if not is_league_commissioner(context, uid):
        return None, "Only the league commissioner can send invites."

    target = resolve_invitee_target(invitee_target)
    invite_ws = str(target.get("invitee_workspace_id") or "").strip()
    if not invite_ws:
        return None, "Enter a valid workspace or account id."

    if invite_ws == _resolve_workspace_id(session) and (
        not target.get("invitee_user_id") or target.get("invitee_user_id") == uid
    ):
        return None, "You cannot invite your own account."

    context = ensure_league_identity(context)
    league_id = resolve_canonical_league_id(context)
    if not league_id:
        return None, "League identity is missing."

    invites = get_league_invites(context)
    for row in invites:
        if str(row.get("status") or "") != INVITE_STATUS_PENDING:
            continue
        if not _invite_matches_user(
            row,
            user_id=str(target.get("invitee_user_id") or ""),
            external_id=str(target.get("invitee_external_id") or ""),
            workspace_id=invite_ws,
        ):
            continue
        return None, "A pending invite already exists for that account."

    invite = {
        "invite_id": _generate_invite_id(),
        "league_id": league_id,
        "league_name": str(context.get("league_name") or context.get("display_name") or "").strip(),
        "draft_fingerprint": compute_draft_fingerprint(context),
        "draft_id": str((context.get("metadata") or {}).get("source_draft_id") or "").strip(),
        "status": INVITE_STATUS_PENDING,
        "invited_by_user_id": uid,
        "invited_by_display": _resolve_display_name() or uid,
        "invitee_user_id": str(target.get("invitee_user_id") or "").strip(),
        "invitee_external_id": str(target.get("invitee_external_id") or "").strip(),
        "invitee_workspace_id": invite_ws,
        "claimed_team": "",
        "created_at": _utc_now_iso(),
        "accepted_at": "",
        "responded_at": "",
    }
    invites.append(invite)
    _set_league_invites(context, invites)
    league_context_id = str(context.get("league_context_id") or "").strip()
    saved = upsert_league_context(session, context)
    if league_context_id:
        refreshed = get_league_context(session, league_context_id)
        if refreshed:
            saved = refreshed
    try:
        push_league_context_to_shared(session, saved)
    except (ImportError, RuntimeError, OSError):
        pass
    append_invite_to_inbox(
        invite_ws,
        invite_id=str(invite["invite_id"]),
        league_id=league_id,
        league_name=str(invite.get("league_name") or ""),
    )
    return invite, ""


def _enrich_pending_invite(invite_ref: dict[str, Any], *, user_id: str, external_id: str, workspace_id: str) -> dict[str, Any] | None:
    league_id = str(invite_ref.get("league_id") or "").strip()
    invite_id = str(invite_ref.get("invite_id") or "").strip()
    if not league_id or not invite_id:
        return None
    shared = load_shared_league(league_id)
    if not isinstance(shared, dict):
        return None
    invites = shared.get("league_invites") or []
    if not isinstance(invites, list):
        return None
    invite = _find_invite([dict(x) for x in invites if isinstance(x, dict)], invite_id)
    if not invite:
        return None
    if not _invite_matches_user(invite, user_id=user_id, external_id=external_id, workspace_id=workspace_id):
        return None
    if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
        return None
    out = copy.deepcopy(invite)
    out["league_name"] = str(
        invite.get("league_name")
        or invite_ref.get("league_name")
        or shared.get("league_name")
        or league_id
    ).strip()
    return out


def list_pending_invites_for_session(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Pending invites for the signed-in account/workspace."""
    uid = _resolve_user_id()
    ext = _resolve_external_id()
    ws = _resolve_workspace_id(session)
    if not ws and not uid:
        return []
    inbox = _read_inbox(ws) if ws else []
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in inbox:
        enriched = _enrich_pending_invite(ref, user_id=uid, external_id=ext, workspace_id=ws)
        if not enriched:
            continue
        key = f"{enriched.get('league_id')}::{enriched.get('invite_id')}"
        if key in seen:
            continue
        seen.add(key)
        pending.append(enriched)
    pending.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return pending


def _board_rows_from_league_rosters(league_rosters: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(league_rosters, dict):
        return rows
    pick = 1
    for team_name in sorted(league_rosters.keys()):
        team = str(team_name or "").strip()
        entry = league_rosters.get(team_name)
        if not team or not isinstance(entry, dict):
            continue
        for player in entry.get("players") or []:
            if not isinstance(player, dict):
                continue
            name = str(player.get("player_name") or player.get("Player") or player.get("fullName") or "").strip()
            if not name:
                continue
            rows.append({"Round": 1, "Pick": pick, "Team": team, "Player": name})
            pick += 1
    return rows


def join_shared_league_from_invite(
    session: dict[str, Any],
    *,
    league_id: str,
    invite_id: str,
    team_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    """Accept invite: link library entry to canonical league_id and claim one team."""
    from draft_archive_state import DRAFT_TYPE_IMPORTED, save_draft_archive
    from fantasy_league_context import (
        create_league_context,
        resolve_canonical_save_ids,
        save_draft_archive_with_league_context,
    )

    league_id = str(league_id or "").strip()
    invite_id = str(invite_id or "").strip()
    team = str(team_name or "").strip()
    uid = _resolve_user_id()
    if not uid:
        return None, None, "Sign in to accept a league invite."
    if not league_id or not invite_id:
        return None, None, "Invite reference is incomplete."
    if not team:
        return None, None, "Choose a team to claim."

    shared = load_shared_league(league_id)
    if not isinstance(shared, dict):
        return None, None, "Shared league could not be loaded."

    invites = [dict(x) for x in (shared.get("league_invites") or []) if isinstance(x, dict)]
    invite = _find_invite(invites, invite_id)
    if not invite:
        return None, None, "Invite not found."
    if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
        return None, None, "This invite is no longer pending."
    if not _invite_matches_user(
        invite,
        user_id=uid,
        external_id=_resolve_external_id(),
        workspace_id=_resolve_workspace_id(session),
    ):
        return None, None, "This invite was sent to a different account."

    league_rosters = shared.get("league_rosters") or {}
    if not isinstance(league_rosters, dict) or team not in league_rosters:
        return None, None, f"Team '{team}' is not in this league."
    ownership = shared.get("team_ownership") or {}
    if not isinstance(ownership, dict):
        ownership = {}
    team_record = ownership.get(team) or {}
    owner_uid = str(team_record.get("user_id") or "").strip()
    if owner_uid and owner_uid != uid:
        return None, None, f"{team} is already claimed by another account."
    for owned_team, record in ownership.items():
        if str(record.get("user_id") or "").strip() == uid and str(owned_team) != team:
            return None, None, f"Your account already owns {owned_team} in this league."

    league_name = str(
        invite.get("league_name") or shared.get("league_name") or f"Shared League {league_id}"
    ).strip()
    cfg = dict(session.get("draft_shared_settings") or {})
    draft_id, league_context_id, fingerprint = resolve_canonical_save_ids(
        session,
        league_rosters=league_rosters,
        config=cfg,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
    )
    if not draft_id:
        draft_id = str(invite.get("draft_id") or "").strip() or None
    if draft_id and not league_context_id:
        from fantasy_league_context import context_id_for_archive

        league_context_id = context_id_for_archive(str(draft_id))

    board_rows = _board_rows_from_league_rosters(league_rosters)
    picks = [row for row in board_rows if str(row.get("Team") or "") == team]
    players = [dict(row) for row in picks]

    entry = save_draft_archive(
        session,
        draft_type=DRAFT_TYPE_IMPORTED,
        draft_name=league_name,
        team_name=team,
        config=cfg,
        roster_rows=players,
        pick_rows=picks,
        draft_board_rows=board_rows,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )
    shared_fp = str(shared.get("draft_fingerprint") or invite.get("draft_fingerprint") or "").strip()
    if shared_fp:
        entry["draft_fingerprint"] = shared_fp
        from draft_archive_state import _set_archive_list, list_draft_archives

        archives = list_draft_archives(session)
        for idx, row in enumerate(archives):
            if str(row.get("draft_id") or "") == str(entry.get("draft_id") or ""):
                archives[idx] = copy.deepcopy(entry)
                break
        _set_archive_list(session, archives)
    draft_id = str(entry.get("draft_id") or "")
    league_context_id = str(entry.get("league_context_id") or league_context_id or "").strip()

    context = create_league_context(
        league_context_id=league_context_id,
        context_type=CONTEXT_TYPE_REAL_LEAGUE,
        league_name=league_name,
        my_team_name=team,
        league_rosters=copy.deepcopy(league_rosters),
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
        scoring_settings={
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        roster_settings={
            "roster_slots": dict(cfg.get("slots") or {}),
            "slot_instances": list(cfg.get("slot_instances") or []),
        },
        display_name=league_name,
        source=SOURCE_IMPORTED_DRAFT,
        source_draft_id=draft_id,
    )
    context["league_id"] = league_id
    meta = dict(context.get("metadata") or {})
    meta["league_id"] = league_id
    shared_fp = str(shared.get("draft_fingerprint") or invite.get("draft_fingerprint") or "").strip()
    if shared_fp:
        meta["draft_fingerprint"] = shared_fp
    context["metadata"] = meta
    context = merge_shared_into_context_for_invite(context, shared)
    context = assign_team_owner_to_context(context, team)
    context["my_team_name"] = team
    meta = dict(context.get("metadata") or {})
    meta["joined_via_invite"] = True
    meta["invite_id"] = invite_id
    meta["commissioner_user_id"] = str(shared.get("commissioner_user_id") or meta.get("commissioner_user_id") or "").strip()
    context["metadata"] = meta
    saved_context = upsert_league_context(session, context)
    save_draft_archive_with_league_context(
        session,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )

    invite["status"] = INVITE_STATUS_ACCEPTED
    invite["claimed_team"] = team
    invite["accepted_at"] = _utc_now_iso()
    invite["responded_at"] = invite["accepted_at"]
    shared["league_invites"] = [
        invite if str(row.get("invite_id") or "") == invite_id else row for row in invites
    ]
    ownership = dict(shared.get("team_ownership") or {})
    ownership[team] = get_team_ownership(saved_context).get(team) or {}
    shared["team_ownership"] = ownership
    shared["league_rosters"] = copy.deepcopy(league_rosters)

    try:
        from fantasy_shared_league_store import save_shared_league

        save_shared_league(shared)
    except (ImportError, RuntimeError, OSError):
        push_league_context_to_shared(session, saved_context)

    saved_context = sync_context_with_shared_store(session, saved_context)
    remove_invite_from_inbox(
        _resolve_workspace_id(session),
        invite_id=invite_id,
        league_id=league_id,
    )
    return entry, saved_context, ""


def merge_shared_into_context_for_invite(context: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    from fantasy_shared_league_store import merge_shared_into_context

    merged = merge_shared_into_context(context, shared)
    invites = shared.get("league_invites") or []
    if isinstance(invites, list):
        _set_league_invites(merged, [dict(x) for x in invites if isinstance(x, dict)])
    return merged


def decline_league_invite(
    session: dict[str, Any],
    *,
    league_id: str,
    invite_id: str,
) -> tuple[bool, str]:
    league_id = str(league_id or "").strip()
    invite_id = str(invite_id or "").strip()
    uid = _resolve_user_id()
    shared = load_shared_league(league_id)
    if not isinstance(shared, dict):
        return False, "Shared league could not be loaded."
    invites = [dict(x) for x in (shared.get("league_invites") or []) if isinstance(x, dict)]
    invite = _find_invite(invites, invite_id)
    if not invite:
        return False, "Invite not found."
    if not _invite_matches_user(
        invite,
        user_id=uid,
        external_id=_resolve_external_id(),
        workspace_id=_resolve_workspace_id(session),
    ):
        return False, "This invite was sent to a different account."
    if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
        return False, "This invite is no longer pending."
    invite["status"] = INVITE_STATUS_DECLINED
    invite["responded_at"] = _utc_now_iso()
    shared["league_invites"] = [
        invite if str(row.get("invite_id") or "") == invite_id else row for row in invites
    ]
    try:
        from fantasy_shared_league_store import save_shared_league

        save_shared_league(shared)
    except (ImportError, RuntimeError, OSError):
        return False, "Could not update invite status."
    remove_invite_from_inbox(_resolve_workspace_id(session), invite_id=invite_id, league_id=league_id)
    return True, ""


def unclaimed_teams_for_invite(shared: dict[str, Any]) -> list[str]:
    rosters = shared.get("league_rosters") or {}
    ownership = shared.get("team_ownership") or {}
    if not isinstance(rosters, dict):
        return []
    if not isinstance(ownership, dict):
        ownership = {}
    teams: list[str] = []
    for team_name in sorted(rosters.keys()):
        team = str(team_name or "").strip()
        if not team:
            continue
        record = ownership.get(team) or {}
        if str(record.get("user_id") or "").strip():
            continue
        teams.append(team)
    return teams


def commissioner_invite_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Explain why commissioner invite UI may be hidden."""
    from fantasy_league_context import get_league_context_for_archive, list_league_contexts

    uid = _resolve_user_id(session)
    contexts = [
        ctx
        for ctx in list_league_contexts(session)
        if str(ctx.get("context_type") or "") == CONTEXT_TYPE_REAL_LEAGUE
    ]
    rows: list[dict[str, Any]] = []
    for ctx in contexts:
        league_context_id = str(ctx.get("league_context_id") or "").strip()
        rows.append(
            {
                "league_context_id": league_context_id,
                "league_name": str(ctx.get("league_name") or ctx.get("display_name") or ""),
                "my_team_name": str(ctx.get("my_team_name") or ""),
                "commissioner_user_id": get_commissioner_user_id(ctx),
                "joined_via_invite": _joined_via_invite(ctx),
                "upload_owner_candidate": is_upload_commissioner_candidate(ctx, uid),
                "is_commissioner": is_league_commissioner(ctx, uid),
            }
        )
    try:
        from draft_archive_visibility import list_visible_draft_archives

        for entry in list_visible_draft_archives(session):
            ctx = get_league_context_for_archive(session, entry)
            if not isinstance(ctx, dict):
                continue
            if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
                continue
            league_context_id = str(ctx.get("league_context_id") or "").strip()
            if any(str(row.get("league_context_id") or "") == league_context_id for row in rows):
                continue
            rows.append(
                {
                    "league_context_id": league_context_id,
                    "league_name": str(ctx.get("league_name") or ctx.get("display_name") or ""),
                    "my_team_name": str(ctx.get("my_team_name") or ""),
                    "commissioner_user_id": get_commissioner_user_id(ctx),
                    "joined_via_invite": _joined_via_invite(ctx),
                    "upload_owner_candidate": is_upload_commissioner_candidate(ctx, uid),
                    "is_commissioner": is_league_commissioner(ctx, uid),
                }
            )
    except ImportError:
        pass
    return {
        "account_user_id": uid,
        "real_league_context_count": len(contexts),
        "commissioner_context_found": bool(commissioner_invite_context(session)),
        "contexts": rows,
    }


def commissioner_invite_context(session: dict[str, Any]) -> dict[str, Any] | None:
    """Best league context the current user can invite from."""
    from fantasy_league_context import get_active_league_context, get_league_context, list_league_contexts

    candidates: list[dict[str, Any]] = []
    context = get_active_league_context(session, respect_source_priority=False)
    if isinstance(context, dict) and str(context.get("context_type") or "") == CONTEXT_TYPE_REAL_LEAGUE:
        candidates.append(context)
    for ctx in list_league_contexts(session):
        if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        if ctx not in candidates:
            candidates.append(ctx)
    try:
        from draft_archive_visibility import list_visible_draft_archives
        from fantasy_league_context import get_league_context_for_archive

        for entry in list_visible_draft_archives(session):
            ctx = get_league_context_for_archive(session, entry)
            if isinstance(ctx, dict) and str(ctx.get("context_type") or "") == CONTEXT_TYPE_REAL_LEAGUE:
                if ctx not in candidates:
                    candidates.append(ctx)
    except ImportError:
        pass
    uid = _resolve_user_id(session)
    for raw in candidates:
        league_context_id = str(raw.get("league_context_id") or "").strip()
        context = get_league_context(session, league_context_id) if league_context_id else raw
        if not isinstance(context, dict):
            continue
        context, _ = repair_commissioner_identity(context, session)
        if is_league_commissioner(context, uid):
            return context
    return None
