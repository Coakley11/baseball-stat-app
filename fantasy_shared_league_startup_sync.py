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


def rebuild_workflow_from_canonical_shared_leagues(
    st: Any,
    app_id: str = "baseball",
) -> dict[str, Any]:
    """Rebuild league contexts and draft archives from canonical shared-league docs."""
    from fantasy_admin_draft_archive_repair import repair_workspace_session_for_league
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
            repair_trace = repair_workspace_session_for_league(
                session,
                league_id=league_id,
                shared_doc=shared_doc,
                cloud_blob=cloud_blob,
                disk_blob=disk_blob,
            )
            changed = bool(repair_trace.get("changed"))
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
        active_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
        if active_id:
            session["_suite_startup_canonical_active_draft_id"] = active_id
    session[_STARTUP_SYNC_TRACE_KEY] = trace
    return trace


def get_startup_sync_trace(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(_STARTUP_SYNC_TRACE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}
