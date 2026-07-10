"""Rebuild session workflow from canonical baseball_shared_leagues at startup."""

from __future__ import annotations

import copy
from typing import Any

from fantasy_league_invites import INVITE_STATUS_ACCEPTED
from fantasy_league_team_ownership import account_user_ids_match
from fantasy_shared_league_store import list_shared_league_documents, load_shared_league

_STARTUP_SYNC_TRACE_KEY = "_suite_shared_league_startup_sync_trace"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_startup_identity(session: dict[str, Any]) -> tuple[str, str, str]:
    uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
    external = str(session.get("_suite_auth_external_id") or "").strip().lower()
    workspace = str(
        session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
    ).strip()
    return uid, external, workspace


def _record_matches_account(
    record: dict[str, Any],
    *,
    user_id: str,
    external_id: str,
    workspace_id: str,
) -> bool:
    if not isinstance(record, dict):
        return False
    stored = str(record.get("user_id") or "").strip()
    if stored and user_id and account_user_ids_match(stored, user_id):
        return True
    aliases = {
        x.lower()
        for x in (
            user_id,
            external_id,
            workspace_id,
            str(record.get("external_id") or "").strip(),
            str(record.get("display_name") or "").strip(),
            str(record.get("email") or "").strip().split("@", 1)[0],
            str(record.get("invitee_external_id") or "").strip(),
            str(record.get("invitee_workspace_id") or "").strip(),
            str(record.get("accepted_by_external_id") or "").strip(),
            str(record.get("accepted_by_workspace_id") or "").strip(),
        )
        if x
    }
    invite_uid = str(record.get("invitee_user_id") or "").strip()
    if invite_uid and user_id and account_user_ids_match(invite_uid, user_id):
        return True
    for candidate in (
        external_id,
        workspace_id,
        str(record.get("invitee_external_id") or "").strip().lower(),
        str(record.get("invitee_workspace_id") or "").strip(),
        str(record.get("accepted_by_external_id") or "").strip().lower(),
        str(record.get("accepted_by_workspace_id") or "").strip(),
    ):
        if candidate and candidate.lower() in aliases:
            return True
    return False


def _pending_trade_involves_account(
    proposal: dict[str, Any],
    *,
    owned_teams: set[str],
) -> bool:
    if str(proposal.get("status") or "").strip() != "pending":
        return False
    proposer = str(proposal.get("proposer_team") or proposal.get("from_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or proposal.get("to_team") or "").strip()
    return bool(owned_teams and (proposer in owned_teams or recipient in owned_teams))


def discover_shared_league_memberships_for_session(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Find canonical shared leagues this workspace participates in."""
    uid, external, workspace = _resolve_startup_identity(session)
    if not uid and not external and not workspace:
        return []

    memberships: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in list_shared_league_documents():
        if not isinstance(doc, dict):
            continue
        league_id = str(doc.get("league_id") or "").strip()
        if not league_id or league_id in seen:
            continue

        reasons: list[str] = []
        owned_teams: set[str] = set()
        ownership = doc.get("team_ownership") or {}
        if isinstance(ownership, dict):
            for team, record in ownership.items():
                if _record_matches_account(
                    record if isinstance(record, dict) else {},
                    user_id=uid,
                    external_id=external,
                    workspace_id=workspace,
                ):
                    owned_teams.add(str(team or "").strip())
                    reasons.append("team_ownership")

        invites = doc.get("league_invites") or []
        if isinstance(invites, list):
            for invite in invites:
                if not isinstance(invite, dict):
                    continue
                status = str(invite.get("status") or "").strip()
                if status == INVITE_STATUS_ACCEPTED and _record_matches_account(
                    invite,
                    user_id=uid,
                    external_id=external,
                    workspace_id=workspace,
                ):
                    reasons.append("accepted_invite")
                    claimed = str(invite.get("claimed_team") or "").strip()
                    if claimed:
                        owned_teams.add(claimed)

        proposals = doc.get("trade_proposals") or []
        if isinstance(proposals, list):
            for proposal in proposals:
                if isinstance(proposal, dict) and _pending_trade_involves_account(
                    proposal, owned_teams=owned_teams
                ):
                    reasons.append("pending_trade")
                    break

        if reasons:
            seen.add(league_id)
            memberships.append(
                {
                    "league_id": league_id,
                    "reasons": sorted(set(reasons)),
                    "owned_teams": sorted(owned_teams),
                    "draft_id": str(doc.get("draft_id") or "").strip(),
                    "revision": doc.get("revision"),
                }
            )
    return memberships


def apply_accepted_member_identity_from_shared(
    session: dict[str, Any],
    context: dict[str, Any],
    shared_doc: dict[str, Any],
) -> dict[str, Any]:
    """Apply Team N identity and joined_via_invite before visibility pruning."""
    from fantasy_league_team_ownership import assign_team_owner_to_context

    uid, external, workspace = _resolve_startup_identity(session)
    merged = copy.deepcopy(context)
    my_team = str(merged.get("my_team_name") or "").strip()
    meta = dict(merged.get("metadata") or {})
    commissioner = str(meta.get("commissioner_user_id") or shared_doc.get("commissioner_user_id") or "").strip()

    invites = shared_doc.get("league_invites") or []
    if isinstance(invites, list):
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
            meta["joined_via_invite"] = True
            invite_id = str(invite.get("invite_id") or "").strip()
            if invite_id:
                meta["invite_id"] = invite_id
            claimed = str(invite.get("claimed_team") or "").strip()
            if claimed:
                merged["my_team_name"] = claimed
                my_team = claimed
            break

    ownership = shared_doc.get("team_ownership") or {}
    if my_team and isinstance(ownership, dict):
        record = ownership.get(my_team) or {}
        if isinstance(record, dict) and str(record.get("user_id") or "").strip():
            merged = assign_team_owner_to_context(
                merged,
                my_team,
                user_id=str(record.get("user_id") or uid),
                email=str(record.get("email") or ""),
                display_name=str(record.get("display_name") or ""),
            )
        elif uid and uid != commissioner:
            merged = assign_team_owner_to_context(
                merged,
                my_team,
                user_id=uid,
                email=str(session.get("_suite_auth_user_email") or ""),
                display_name=str(session.get("_suite_auth_external_id") or external),
            )

    if my_team and uid and uid != commissioner:
        meta["joined_via_invite"] = True
    merged["metadata"] = meta
    return merged


def canonical_membership_draft_ids_for_session(session: dict[str, Any]) -> set[str]:
    return {
        str(row.get("draft_id") or "").strip()
        for row in discover_shared_league_memberships_for_session(session)
        if str(row.get("draft_id") or "").strip()
    }


def finalize_repaired_archives_for_membership(
    session: dict[str, Any],
    *,
    shared_doc: dict[str, Any],
    cloud_blob: dict[str, Any] | None = None,
    disk_blob: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair archives, apply identity, then reconcile active selection in order."""
    from fantasy_admin_draft_archive_repair import (
        _normalize_repaired_archive_types,
        _sync_archives_to_workspace_team,
        find_league_context_by_league_id,
    )
    from fantasy_league_context import repair_missing_draft_archives_from_contexts, upsert_league_context
    from workflow_persist_guard import ACTIVE_DRAFT_ARCHIVE_KEY, restore_active_draft_archive_selection

    league_id = str(shared_doc.get("league_id") or "").strip()
    trace: dict[str, Any] = {
        "archives_repaired": 0,
        "archive_types_normalized": 0,
        "archive_team_rows_rewritten": 0,
        "active_restore_trace": {},
    }
    context = find_league_context_by_league_id(session, league_id)
    if not isinstance(context, dict):
        return trace

    context = apply_accepted_member_identity_from_shared(session, context, shared_doc)
    upsert_league_context(session, context, mark_persist_authoritative=False)
    context = find_league_context_by_league_id(session, league_id) or context

    trace["archives_repaired"] = int(
        repair_missing_draft_archives_from_contexts(session, require_visibility=False) or 0
    )
    trace["archive_types_normalized"] = _normalize_repaired_archive_types(session)
    refreshed = find_league_context_by_league_id(session, league_id) or context
    trace["archive_team_rows_rewritten"] = _sync_archives_to_workspace_team(session, refreshed)

    draft_id = str(shared_doc.get("draft_id") or (refreshed.get("metadata") or {}).get("source_draft_id") or "").strip()
    if draft_id:
        from draft_archive_state import set_active_draft_archive

        set_active_draft_archive(session, draft_id)
        session["_suite_startup_canonical_active_draft_id"] = draft_id

    restore_trace = restore_active_draft_archive_selection(
        session,
        cloud_state=cloud_blob if isinstance(cloud_blob, dict) else {},
        disk_state=disk_blob if isinstance(disk_blob, dict) else {},
        phase="startup_canonical_sync",
        respect_canonical_membership=True,
    )
    trace["active_restore_trace"] = restore_trace if isinstance(restore_trace, dict) else {}
    if draft_id:
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = draft_id
    return trace

    """Find canonical shared leagues this workspace participates in."""
    uid, external, workspace = _resolve_startup_identity(session)
    if not uid and not external and not workspace:
        return []

    memberships: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in list_shared_league_documents():
        if not isinstance(doc, dict):
            continue
        league_id = str(doc.get("league_id") or "").strip()
        if not league_id or league_id in seen:
            continue

        reasons: list[str] = []
        owned_teams: set[str] = set()
        ownership = doc.get("team_ownership") or {}
        if isinstance(ownership, dict):
            for team, record in ownership.items():
                if _record_matches_account(
                    record if isinstance(record, dict) else {},
                    user_id=uid,
                    external_id=external,
                    workspace_id=workspace,
                ):
                    owned_teams.add(str(team or "").strip())
                    reasons.append("team_ownership")

        invites = doc.get("league_invites") or []
        if isinstance(invites, list):
            for invite in invites:
                if not isinstance(invite, dict):
                    continue
                status = str(invite.get("status") or "").strip()
                if status == INVITE_STATUS_ACCEPTED and _record_matches_account(
                    invite,
                    user_id=uid,
                    external_id=external,
                    workspace_id=workspace,
                ):
                    reasons.append("accepted_invite")
                    claimed = str(invite.get("claimed_team") or "").strip()
                    if claimed:
                        owned_teams.add(claimed)

        proposals = doc.get("trade_proposals") or []
        if isinstance(proposals, list):
            for proposal in proposals:
                if isinstance(proposal, dict) and _pending_trade_involves_account(
                    proposal, owned_teams=owned_teams
                ):
                    reasons.append("pending_trade")
                    break

        if reasons:
            seen.add(league_id)
            memberships.append(
                {
                    "league_id": league_id,
                    "reasons": sorted(set(reasons)),
                    "owned_teams": sorted(owned_teams),
                    "draft_id": str(doc.get("draft_id") or "").strip(),
                    "revision": doc.get("revision"),
                }
            )
    return memberships


def rebuild_workflow_from_canonical_shared_leagues(
    st: Any,
    app_id: str = "baseball",
) -> dict[str, Any]:
    """Rebuild league contexts and draft archives from canonical shared-league docs."""
    from fantasy_admin_draft_archive_repair import (
        build_context_from_shared_for_workspace,
        find_league_context_by_league_id,
    )
    from workflow_persist_guard import (
        ACTIVE_DRAFT_ARCHIVE_KEY,
        DRAFT_ARCHIVE_KEY,
        LEAGUE_CONTEXT_STATE_KEY,
        _load_cloud_workflow_snapshot,
        _load_disk_workflow_snapshot,
        count_draft_archives,
        count_league_contexts,
    )

    session = st.session_state
    before_drafts = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    before_contexts = count_league_contexts(session.get(LEAGUE_CONTEXT_STATE_KEY))
    trace: dict[str, Any] = {
        "updated_at": _utc_now_iso(),
        "memberships": [],
        "leagues_rebuilt": 0,
        "rebuilt": False,
        "session_before": {"drafts": before_drafts, "contexts": before_contexts},
        "session_after": {"drafts": before_drafts, "contexts": before_contexts},
        "errors": [],
    }

    memberships = discover_shared_league_memberships_for_session(session)
    trace["memberships"] = memberships
    if not memberships:
        trace["reason"] = "no_shared_league_memberships"
        session[_STARTUP_SYNC_TRACE_KEY] = trace
        return trace

    cloud_blob = _load_cloud_workflow_snapshot(app_id, st)
    disk_blob = _load_disk_workflow_snapshot(app_id)
    results: list[dict[str, Any]] = []
    for row in memberships:
        league_id = str(row.get("league_id") or "").strip()
        shared_doc = load_shared_league(league_id)
        if not isinstance(shared_doc, dict):
            results.append({"league_id": league_id, "error": "shared_doc_not_found"})
            trace["errors"].append(f"{league_id}:shared_doc_not_found")
            continue
        try:
            from fantasy_admin_draft_archive_repair import (
                build_context_from_shared_for_workspace,
                find_league_context_by_league_id,
            )
            from fantasy_league_context import upsert_league_context

            owner_uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
            owner_external = str(session.get("_suite_auth_external_id") or "").strip().lower()
            workspace_id = str(
                session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
            ).strip()
            existing = find_league_context_by_league_id(session, league_id)
            context = build_context_from_shared_for_workspace(
                shared_doc,
                owner_user_id=owner_uid,
                owner_external_id=owner_external,
                workspace_id=workspace_id,
                existing=existing,
            )
            context = apply_accepted_member_identity_from_shared(session, context, shared_doc)
            upsert_league_context(session, context, mark_persist_authoritative=False)
            finalize_trace = finalize_repaired_archives_for_membership(
                session,
                shared_doc=shared_doc,
                cloud_blob=cloud_blob,
                disk_blob=disk_blob,
            )
            changed = bool(
                (finalize_trace.get("archives_repaired") or 0) > 0
                or (finalize_trace.get("archive_team_rows_rewritten") or 0) > 0
                or not existing
            )
            repair_trace = {
                "league_id": league_id,
                "context_created": not bool(existing),
                "finalize_trace": finalize_trace,
                "changed": changed,
            }
            if changed:
                trace["leagues_rebuilt"] += 1
            results.append(
                {
                    "league_id": league_id,
                    "reasons": row.get("reasons") or [],
                    "changed": changed,
                    "repair_trace": repair_trace,
                }
            )
        except Exception as exc:
            err = f"{league_id}:{type(exc).__name__}:{exc}"
            trace["errors"].append(err)
            results.append({"league_id": league_id, "error": err})

    after_drafts = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    after_contexts = count_league_contexts(session.get(LEAGUE_CONTEXT_STATE_KEY))
    trace["session_after"] = {"drafts": after_drafts, "contexts": after_contexts}
    trace["results"] = results
    trace["rebuilt"] = (
        after_drafts > before_drafts
        or after_contexts > before_contexts
        or trace["leagues_rebuilt"] > 0
    )
    if trace["rebuilt"]:
        try:
            from workflow_persist_guard import mark_workflow_persist_authoritative

            mark_workflow_persist_authoritative(session)
        except ImportError:
            pass
    session[_STARTUP_SYNC_TRACE_KEY] = trace
    return trace


def get_startup_sync_trace(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(_STARTUP_SYNC_TRACE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}
