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


def resolve_workspace_team_from_shared(
    session: dict[str, Any],
    shared_doc: dict[str, Any],
) -> str:
    """Resolve the signed-in member's team from canonical shared team_ownership."""
    from fantasy_workspace_team_identity import owned_team_from_shared_doc, record_team_identity_trace

    uid, external, workspace = _resolve_startup_identity(session)
    team = owned_team_from_shared_doc(shared_doc, session)
    record_team_identity_trace(
        session,
        phase="resolve_workspace_team_from_shared",
        authenticated_workspace=workspace,
        ownership_resolved_team=team or None,
        auth_user_id=uid or None,
        auth_external_id=external or None,
    )
    return team


def apply_workspace_member_identity_from_shared(
    session: dict[str, Any],
    context: dict[str, Any],
    shared_doc: dict[str, Any],
) -> dict[str, Any]:
    """Apply workspace-local team identity from canonical membership; never bleed invitee fields globally."""
    from fantasy_league_invites import is_league_commissioner
    from fantasy_league_team_ownership import assign_team_owner_to_context
    from fantasy_workspace_team_identity import overlay_workspace_team_on_context, record_team_identity_trace

    uid, external, workspace = _resolve_startup_identity(session)
    pre_merge_team = str(context.get("my_team_name") or "").strip()
    merged = overlay_workspace_team_on_context(
        session,
        context,
        shared_doc=shared_doc,
        trace_phase="apply_workspace_member_identity_pre_overlay",
        record_trace=True,
    )
    if not isinstance(merged, dict):
        merged = copy.deepcopy(context)

    meta = dict(merged.get("metadata") or {})
    commissioner = str(
        meta.get("commissioner_user_id") or shared_doc.get("commissioner_user_id") or ""
    ).strip()
    my_team = str(merged.get("my_team_name") or "").strip()
    if not my_team:
        my_team = resolve_workspace_team_from_shared(session, shared_doc)
        if my_team:
            merged["my_team_name"] = my_team

    is_commissioner = bool(uid and (is_league_commissioner(merged, uid) or account_user_ids_match(uid, commissioner)))
    if is_commissioner:
        meta.pop("joined_via_invite", None)
        meta.pop("invite_id", None)
    else:
        matched_invite = False
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
                if claimed and not my_team:
                    merged["my_team_name"] = claimed
                    my_team = claimed
                matched_invite = True
                break

        if not matched_invite and my_team and uid and not is_commissioner:
            meta_doc = dict(shared_doc.get("metadata") or {})
            created_from = str(
                meta.get("created_from")
                or meta_doc.get("created_from")
                or shared_doc.get("created_from")
                or ""
            ).strip()
            source_token = str(
                shared_doc.get("source") or meta_doc.get("source") or meta.get("source") or ""
            ).strip()
            try:
                from draft_archive_state import DRAFT_TYPE_LIVE
                from fantasy_league_context import (
                    _accepted_invite_claims_team,
                    _account_owns_team_in_shared,
                    classify_origin_token,
                    collect_origin_evidence,
                )
            except ImportError:
                DRAFT_TYPE_LIVE = "live_draft_room"
                classify_origin_token = lambda _token: None  # type: ignore[assignment,misc]
                _accepted_invite_claims_team = lambda *_args, **_kwargs: False  # type: ignore[assignment,misc]
                _account_owns_team_in_shared = lambda *_args, **_kwargs: False  # type: ignore[assignment,misc]
            identity_session = {
                "_suite_auth_user_id": uid,
                "_suite_auth_external_id": external,
                "_suite_active_workspace_id": workspace,
            }
            live_origin = (
                created_from == "live_draft"
                or classify_origin_token(created_from) == DRAFT_TYPE_LIVE
                or classify_origin_token(source_token) == DRAFT_TYPE_LIVE
            )
            if live_origin:
                meta["joined_via_live_draft"] = True
                meta["preassigned_live_draft_owner"] = True
                meta.pop("joined_via_invite", None)
            elif _account_owns_team_in_shared(shared_doc, merged, session=identity_session) and not _accepted_invite_claims_team(
                shared_doc,
                my_team,
                session=identity_session,
            ):
                evidence = collect_origin_evidence(
                    shared_doc=shared_doc,
                    context=merged,
                    session=identity_session,
                )
                if (
                    evidence.get("explicit_import_origin")
                    and not meta.get("joined_via_live_draft")
                    and not meta.get("preassigned_live_draft_owner")
                ):
                    meta.setdefault("joined_via_invite", True)
                else:
                    meta["joined_via_live_draft"] = True
                    meta["preassigned_live_draft_owner"] = True
                    meta.pop("joined_via_invite", None)

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
        elif uid:
            merged = assign_team_owner_to_context(
                merged,
                my_team,
                user_id=uid,
                email=str(session.get("_suite_auth_user_email") or ""),
                display_name=str(session.get("_suite_auth_external_id") or external),
            )

    merged["metadata"] = meta
    record_team_identity_trace(
        session,
        phase="apply_workspace_member_identity_from_shared",
        authenticated_workspace=workspace,
        ownership_resolved_team=my_team or None,
        pre_merge_team=pre_merge_team or None,
        post_merge_team=str(merged.get("my_team_name") or "").strip() or None,
    )
    return merged


# Backward-compatible alias for earlier startup-sync callers.
apply_accepted_member_identity_from_shared = apply_workspace_member_identity_from_shared


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

    context = apply_workspace_member_identity_from_shared(session, context, shared_doc)
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
        from draft_archive_state import get_draft_archive, set_active_draft_archive
        from fantasy_workspace_team_identity import record_team_identity_trace, resolve_archive_display_team

        set_active_draft_archive(session, draft_id)
        session["_suite_startup_canonical_active_draft_id"] = draft_id
        active_entry = get_draft_archive(session, draft_id)
        active_context = find_league_context_by_league_id(session, league_id) or refreshed
        record_team_identity_trace(
            session,
            phase="finalize_repaired_archives_active_archive",
            active_archive_team=str((active_entry or {}).get("team_name") or "").strip() or None,
            final_library_team=resolve_archive_display_team(session, active_entry, active_context) or None,
            final_fantasy_lineup_team=str((active_context or {}).get("my_team_name") or "").strip() or None,
        )

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
    identity_snapshot = None
    try:
        from suite_identity_guard import snapshot_protected_browser_identity

        identity_snapshot = snapshot_protected_browser_identity(session)
    except ImportError:
        pass
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
            context = apply_workspace_member_identity_from_shared(session, context, shared_doc)
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
    try:
        from suite_identity_guard import enforce_identity_after_state_apply

        enforce_identity_after_state_apply(
            session,
            snapshot=identity_snapshot if isinstance(identity_snapshot, dict) else None,
            reason="rebuild_workflow_from_canonical_shared_leagues",
            last_mutator="fantasy_shared_league_startup_sync.rebuild",
            st=st,
        )
    except ImportError:
        pass
    return trace


def get_startup_sync_trace(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(_STARTUP_SYNC_TRACE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}
