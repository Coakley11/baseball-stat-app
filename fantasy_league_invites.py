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
    build_team_ownership_sync_diagnostics,
    load_shared_league,
    list_shared_league_documents,
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
                "resolve_source": "ownership_registry",
            }
    try:
        import suite_storage_supabase as storage

        for row in storage.list_suite_users_by_external_ids(slug):
            if not isinstance(row, dict):
                continue
            ext = str(row.get("external_id") or slug).strip().lower()
            if ext != slug and slug != normalize_workspace_id(ext):
                continue
            return {
                "invitee_workspace_id": slug,
                "invitee_user_id": str(row.get("id") or "").strip(),
                "invitee_external_id": ext or slug,
                "resolve_source": "suite_users",
            }
    except Exception:
        pass
    return {
        "invitee_workspace_id": slug,
        "invitee_user_id": "",
        "invitee_external_id": slug,
        "resolve_source": "slug_fallback",
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
    if invite_uid and user_id and account_user_ids_match(invite_uid, user_id):
        return True
    if invite_ext and external_id and invite_ext == str(external_id or "").strip().lower():
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
        saved_shared = push_league_context_to_shared(session, saved)
        if isinstance(saved_shared, dict):
            session["_last_invite_shared_push_ok"] = True
            session["_last_invite_shared_league_id"] = str(saved_shared.get("league_id") or league_id)
            session.pop("_last_invite_shared_push_error", None)
        else:
            session["_last_invite_shared_push_ok"] = False
            session["_last_invite_shared_push_error"] = "push_league_context_to_shared returned None"
            invite["shared_push_error"] = session["_last_invite_shared_push_error"]
    except (ImportError, RuntimeError, OSError, ValueError) as exc:
        session["_last_invite_shared_push_ok"] = False
        session["_last_invite_shared_push_error"] = str(exc)
        invite["shared_push_error"] = str(exc)
    append_invite_to_inbox(
        invite_ws,
        invite_id=str(invite["invite_id"]),
        league_id=league_id,
        league_name=str(invite.get("league_name") or ""),
    )
    session["_last_commissioner_invite_sent"] = copy.deepcopy(invite)
    try:
        from workflow_persist_guard import mark_workflow_persist_authoritative

        mark_workflow_persist_authoritative(session)
    except ImportError:
        pass
    return invite, ""


def can_claim_team_for_context(session: dict[str, Any], context: dict[str, Any] | None) -> tuple[bool, str]:
    """Invitee may claim only after accepting invite; commissioner may claim upload team."""
    if not isinstance(context, dict):
        return False, "League context is required."
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return False, "Only shared uploaded leagues support team claims."
    uid = _resolve_user_id(session)
    if not uid:
        return False, "Sign in to claim a team."
    if is_league_commissioner(context, uid):
        return True, ""
    if _joined_via_invite(context):
        return True, ""
    league_id = resolve_canonical_league_id(context)
    for pending in list_pending_invites_for_session(session):
        if league_id and str(pending.get("league_id") or "").strip() == league_id:
            return True, ""
    return False, "Accept your shared league invite before claiming a team."


def record_invite_submit_trace(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Persist commissioner invite form submit diagnostics across reruns."""
    trace = dict(session.get("_suite_last_invite_submit_trace") or {})
    trace.update({k: v for k, v in fields.items() if v is not None or k.endswith("_error")})
    trace["updated_at"] = _utc_now_iso()
    session["_suite_last_invite_submit_trace"] = trace
    return trace


def build_invite_submit_trace_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    """Latest commissioner invite button/form trace for diagnostic panels."""
    trace = dict(session.get("_suite_last_invite_submit_trace") or {})
    last_sent = session.get("_last_commissioner_invite_sent")
    return {
        "button_clicked": bool(trace.get("button_clicked")),
        "create_league_invite_called": bool(trace.get("create_league_invite_called")),
        "target_raw": trace.get("target_raw"),
        "target_trimmed": trace.get("target_trimmed"),
        "resolved_target": trace.get("resolved_target"),
        "invite_id": trace.get("invite_id") or (
            str(last_sent.get("invite_id") or "") if isinstance(last_sent, dict) else None
        ),
        "create_error": trace.get("create_error"),
        "last_invite_shared_push_ok": trace.get("last_invite_shared_push_ok", session.get("_last_invite_shared_push_ok")),
        "last_invite_shared_push_error": trace.get(
            "last_invite_shared_push_error", session.get("_last_invite_shared_push_error")
        ),
        "last_invite_shared_league_id": trace.get(
            "last_invite_shared_league_id", session.get("_last_invite_shared_league_id")
        ),
        "league_invite_sent_reason_set": trace.get("league_invite_sent_reason_set"),
        "force_save_attempted": bool(trace.get("force_save_attempted")),
        "force_save_ok": trace.get("force_save_ok"),
        "persist_last_save_reason": trace.get("persist_last_save_reason")
        or session.get("_suite_persist_last_save_reason"),
        "context_league_id": trace.get("context_league_id"),
        "updated_at": trace.get("updated_at"),
        "last_commissioner_invite_sent": (
            last_sent if isinstance(last_sent, dict) else None
        ),
    }


def build_invite_flow_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Saved Draft Library invite/claim diagnostics for commissioner and invitee."""
    uid = _resolve_user_id(session)
    ext = _resolve_external_id()
    ws = _resolve_workspace_id(session)
    cloud_app_key = ""
    try:
        from suite_workspace import get_active_workspace_id, scoped_cloud_app_id

        st_stub = type("_St", (), {"session_state": session})()
        cloud_app_key = scoped_cloud_app_id("baseball", str(get_active_workspace_id(st=st_stub)))
    except Exception:
        pass
    context = commissioner_invite_context(session)
    league_id = ""
    owner_user_id = ""
    team_claims: dict[str, Any] = {}
    team_claims_shared: dict[str, Any] = {}
    ownership_sync: dict[str, Any] = {}
    invite_rows: list[dict[str, Any]] = []
    if isinstance(context, dict):
        league_id = str(resolve_canonical_league_id(context) or "").strip()
        owner_user_id = str(get_commissioner_user_id(context) or "").strip()
        team_claims = dict(get_team_ownership(context) or {})
        ownership_sync = build_team_ownership_sync_diagnostics(context)
        team_claims_shared = dict(ownership_sync.get("shared_team_ownership") or {})
        invite_rows = list(get_league_invites(context) or [])
    pending = list_pending_invites_for_session(session)
    last_sent = session.get("_last_commissioner_invite_sent")
    lookup_trace = build_invite_lookup_trace(session)
    stranded = session.get("_suite_stranded_foreign_disk_draft")
    library_sync_trace = session.get("_suite_shared_league_library_sync_trace")
    set_active_sync_trace = session.get("_suite_last_set_active_sync_trace")
    return {
        "current_user_id": uid or None,
        "external_id": ext or None,
        "workspace_id": ws or None,
        "cloud_app_key": cloud_app_key or None,
        "league_id": league_id or None,
        "owner_user_id": owner_user_id or None,
        "team_claims": team_claims,
        "team_claims_local": team_claims,
        "team_claims_shared": team_claims_shared,
        "ownership_sync": ownership_sync,
        "library_sync_trace": (
            library_sync_trace if isinstance(library_sync_trace, dict) else None
        ),
        "set_active_sync_trace": (
            set_active_sync_trace if isinstance(set_active_sync_trace, dict) else None
        ),
        "league_invites": invite_rows,
        "pending_invites_for_session": pending,
        "pending_invite_count": len(pending),
        "lookup_trace": lookup_trace,
        "stranded_foreign_disk_draft": bool(stranded),
        "last_commissioner_invite_sent": (
            last_sent if isinstance(last_sent, dict) else None
        ),
        "invite_submit_trace": build_invite_submit_trace_snapshot(session),
        "is_commissioner_for_active_context": bool(
            isinstance(context, dict) and uid and is_league_commissioner(context, uid)
        ),
    }


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


def scan_pending_invites_from_disk_workflow_hints(
    session: dict[str, Any],
    *,
    app_id: str = "baseball",
) -> list[dict[str, Any]]:
    """When disk retains a leaked shared-league blob, load invites by its league_id."""
    uid = _resolve_user_id(session)
    ext = _resolve_external_id()
    ws = _resolve_workspace_id(session)
    if not uid and not ext and not ws:
        return []
    try:
        from workflow_persist_guard import DRAFT_ARCHIVE_KEY, _load_disk_workflow_snapshot, count_draft_archives
    except ImportError:
        return []
    disk = _load_disk_workflow_snapshot(app_id, session)
    if count_draft_archives(disk.get(DRAFT_ARCHIVE_KEY)) <= 0:
        return []
    league_ids: set[str] = set()
    store = disk.get("fantasy_league_context_state")
    if isinstance(store, dict):
        contexts = store.get("contexts")
        if isinstance(contexts, dict):
            for ctx in contexts.values():
                if isinstance(ctx, dict):
                    lid = str(resolve_canonical_league_id(ctx) or "").strip()
                    if lid:
                        league_ids.add(lid)
    for entry in disk.get(DRAFT_ARCHIVE_KEY) or []:
        if not isinstance(entry, dict):
            continue
        try:
            from fantasy_league_context import get_league_context_for_archive

            ctx = get_league_context_for_archive(session, entry)
            if isinstance(ctx, dict):
                lid = str(resolve_canonical_league_id(ctx) or "").strip()
                if lid:
                    league_ids.add(lid)
        except ImportError:
            pass
        meta = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        lid = str(meta.get("league_id") or entry.get("league_id") or "").strip()
        if lid:
            league_ids.add(lid)
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for league_id in sorted(league_ids):
        shared = load_shared_league(league_id)
        if not isinstance(shared, dict):
            continue
        invites = shared.get("league_invites") or []
        if not isinstance(invites, list):
            continue
        for raw in invites:
            if not isinstance(raw, dict):
                continue
            invite = dict(raw)
            if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
                continue
            if not _invite_matches_user(invite, user_id=uid, external_id=ext, workspace_id=ws):
                continue
            invite_id = str(invite.get("invite_id") or "").strip()
            key = f"{league_id}::{invite_id}"
            if not invite_id or key in seen:
                continue
            seen.add(key)
            invite["league_id"] = league_id
            invite["league_name"] = str(
                invite.get("league_name") or shared.get("league_name") or league_id
            ).strip()
            invite["lookup_source"] = "disk_workflow_league_id"
            pending.append(invite)
    return pending


def build_invite_lookup_trace(session: dict[str, Any]) -> dict[str, Any]:
    """Explain each invite lookup path for commissioner/invitee diagnostics."""
    uid = _resolve_user_id(session)
    ext = _resolve_external_id()
    ws = _resolve_workspace_id(session)
    inbox = _read_inbox(ws) if ws else []
    shared_docs = list_shared_league_documents()
    shared_scan = scan_pending_invites_from_shared_leagues(session)
    disk_scan = scan_pending_invites_from_disk_workflow_hints(session)
    disk_raw = 0
    disk_visible = 0
    try:
        from workflow_persist_guard import DRAFT_ARCHIVE_KEY, _load_disk_workflow_snapshot, count_draft_archives
        from draft_archive_visibility import count_visible_draft_archives_in_blob

        disk_state = _load_disk_workflow_snapshot("baseball", session)
        disk_raw = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))
        disk_visible = count_visible_draft_archives_in_blob(session, disk_state)
    except ImportError:
        pass
    return {
        "lookup_user_id": uid or None,
        "lookup_external_id": ext or None,
        "lookup_workspace_id": ws or None,
        "inbox_path": str(_inbox_path(ws)) if ws else None,
        "inbox_ref_count": len(inbox),
        "shared_league_document_count": len(shared_docs),
        "pending_from_shared_scan": len(shared_scan),
        "pending_from_disk_league_ids": len(disk_scan),
        "disk_draft_raw_count": disk_raw,
        "disk_draft_visible_count": disk_visible,
        "disk_pollution_not_invite": bool(disk_raw > 0 and disk_visible == 0),
        "last_invite_shared_push_ok": session.get("_last_invite_shared_push_ok"),
        "last_invite_shared_push_error": session.get("_last_invite_shared_push_error"),
        "last_invite_shared_league_id": session.get("_last_invite_shared_league_id"),
        "stranded_disk_reconcile": session.get("_suite_stranded_disk_reconcile"),
        "migration_writeback_trace": session.get("_suite_auth_migration_writeback_trace"),
    }


def scan_pending_invites_from_shared_leagues(
    session: dict[str, Any],
) -> list[dict[str, Any]]:
    """Find pending invites in canonical shared-league docs (not session/disk inbox only)."""
    uid = _resolve_user_id()
    ext = _resolve_external_id()
    ws = _resolve_workspace_id(session)
    if not uid and not ext and not ws:
        return []
    warm_fp = "|".join(
        [
            str(uid or ""),
            str(ext or ""),
            str(ws or ""),
            str(session.get("_suite_cloud_session_revision") or ""),
        ]
    )
    cached = session.get("_suite_pending_invite_scan_cache")
    if (
        isinstance(cached, dict)
        and cached.get("fp") == warm_fp
        and isinstance(cached.get("invites"), list)
        and not session.get("_suite_pending_invite_scan_force")
    ):
        return [dict(row) for row in cached["invites"] if isinstance(row, dict)]
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in list_shared_league_documents():
        if not isinstance(doc, dict):
            continue
        league_id = str(doc.get("league_id") or "").strip()
        invites = doc.get("league_invites") or []
        if not isinstance(invites, list):
            continue
        for raw in invites:
            if not isinstance(raw, dict):
                continue
            invite = dict(raw)
            if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
                continue
            if not _invite_matches_user(invite, user_id=uid, external_id=ext, workspace_id=ws):
                continue
            invite_id = str(invite.get("invite_id") or "").strip()
            key = f"{league_id}::{invite_id}"
            if not league_id or not invite_id or key in seen:
                continue
            seen.add(key)
            invite["league_id"] = league_id
            invite["league_name"] = str(
                invite.get("league_name") or doc.get("league_name") or league_id
            ).strip()
            invite["invited_by_display"] = str(
                invite.get("invited_by_display") or doc.get("commissioner_user_id") or "League commissioner"
            ).strip()
            invite["lookup_source"] = "shared_league_scan"
            pending.append(invite)
    pending.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    session["_suite_pending_invite_scan_cache"] = {
        "fp": warm_fp,
        "invites": [dict(row) for row in pending],
    }
    session.pop("_suite_pending_invite_scan_force", None)
    return pending


def reconcile_stranded_foreign_disk_drafts(
    st: Any,
    app_id: str = "baseball",
) -> dict[str, Any]:
    """
    Disk may retain a foreign shared-league draft while session/cloud are empty after prune.

    Sanitize disk and surface pending invites from shared-league documents.
    """
    session = st.session_state
    out: dict[str, Any] = {
        "stranded": False,
        "disk_raw_count": 0,
        "disk_visible_count": 0,
        "session_count": 0,
        "disk_sanitized": False,
        "pending_invites": 0,
    }
    try:
        from workflow_persist_guard import DRAFT_ARCHIVE_KEY, _load_disk_workflow_snapshot, count_draft_archives
        from draft_archive_visibility import (
            count_visible_draft_archives_in_blob,
            force_persist_sanitized_workflow_disk,
        )
    except ImportError:
        return out

    disk_state = _load_disk_workflow_snapshot(app_id, session)
    out["disk_raw_count"] = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))
    out["disk_visible_count"] = count_visible_draft_archives_in_blob(session, disk_state)
    out["session_count"] = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    if out["disk_raw_count"] <= 0:
        return out
    if out["session_count"] > 0 or out["disk_visible_count"] > 0:
        return out

    out["stranded"] = True
    session["_suite_stranded_foreign_disk_draft"] = True
    pending = list_pending_invites_for_session(session)
    out["pending_invites"] = len(pending)
    session["_suite_pending_league_invites"] = pending
    try:
        out["disk_sanitized"] = bool(force_persist_sanitized_workflow_disk(session, app_id=app_id))
    except Exception:
        out["disk_sanitized"] = False
    session["_suite_stranded_disk_reconcile"] = out
    return out


def list_pending_invites_for_session(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Pending invites for the signed-in account/workspace."""
    uid = _resolve_user_id()
    ext = _resolve_external_id()
    ws = _resolve_workspace_id(session)
    if not ws and not uid:
        return []
    inbox = _read_inbox(ws) if ws else []
    refs: list[dict[str, Any]] = [dict(x) for x in inbox if isinstance(x, dict)]
    try:
        from fantasy_league_context import list_league_contexts

        for ctx in list_league_contexts(session):
            league_id = str(resolve_canonical_league_id(ctx) or "").strip()
            for invite in get_league_invites(ctx):
                if not isinstance(invite, dict):
                    continue
                if not _invite_matches_user(invite, user_id=uid, external_id=ext, workspace_id=ws):
                    continue
                if str(invite.get("status") or "") != INVITE_STATUS_PENDING:
                    continue
                refs.append(
                    {
                        "invite_id": str(invite.get("invite_id") or "").strip(),
                        "league_id": league_id or str(invite.get("league_id") or "").strip(),
                        "league_name": str(invite.get("league_name") or "").strip(),
                    }
                )
    except ImportError:
        pass
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        enriched = _enrich_pending_invite(ref, user_id=uid, external_id=ext, workspace_id=ws)
        if not enriched:
            continue
        key = f"{enriched.get('league_id')}::{enriched.get('invite_id')}"
        if key in seen:
            continue
        seen.add(key)
        pending.append(enriched)
    for invite in scan_pending_invites_from_shared_leagues(session):
        if not isinstance(invite, dict):
            continue
        key = f"{invite.get('league_id')}::{invite.get('invite_id')}"
        if key in seen:
            continue
        seen.add(key)
        pending.append(invite)
    for invite in scan_pending_invites_from_disk_workflow_hints(session):
        if not isinstance(invite, dict):
            continue
        key = f"{invite.get('league_id')}::{invite.get('invite_id')}"
        if key in seen:
            continue
        seen.add(key)
        pending.append(invite)
    pending.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    session["_suite_pending_league_invites"] = pending
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
    team_record = ownership.get(team) if isinstance(ownership.get(team), dict) else {}
    try:
        from fantasy_league_team_ownership import account_user_ids_match, ownership_is_firm_claim
    except ImportError:
        account_user_ids_match = lambda a, b: str(a or "") == str(b or "")  # type: ignore[assignment,misc]
        ownership_is_firm_claim = lambda record: bool(str((record or {}).get("user_id") or "").strip())  # type: ignore[assignment,misc]
    owner_uid = str(team_record.get("user_id") or "").strip()
    if ownership_is_firm_claim(team_record) and owner_uid and not account_user_ids_match(owner_uid, uid):
        return None, None, f"{team} is already claimed by another account."
    for owned_team, record in ownership.items():
        if not isinstance(record, dict):
            continue
        other_uid = str(record.get("user_id") or "").strip()
        if (
            ownership_is_firm_claim(record)
            and other_uid
            and account_user_ids_match(other_uid, uid)
            and str(owned_team) != team
        ):
            return None, None, f"Your account already owns {owned_team} in this league."

    league_name = str(
        invite.get("league_name") or shared.get("league_name") or f"Shared League {league_id}"
    ).strip()
    cfg = dict(session.get("draft_shared_settings") or {})

    # Origin travels with the shared league — Live Draft leagues stay Live for invitees.
    from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE, save_draft_archive

    shared_created_from = str(shared.get("created_from") or (shared.get("metadata") or {}).get("created_from") or "").strip()
    shared_source = str(shared.get("source") or (shared.get("metadata") or {}).get("source") or "").strip()
    shared_source_type = str(
        shared.get("source_draft_type") or (shared.get("metadata") or {}).get("source_draft_type") or ""
    ).strip()
    is_live_origin = (
        shared_created_from == "live_draft"
        or shared_source in {"live_draft_room", "live_draft"}
        or shared_source_type in {"live_draft_room", "live_draft"}
        or bool(str(shared.get("source_room_code") or (shared.get("metadata") or {}).get("source_room_code") or "").strip())
    )
    archive_draft_type = DRAFT_TYPE_LIVE if is_live_origin else DRAFT_TYPE_IMPORTED
    try:
        from fantasy_league_context import SOURCE_LIVE_DRAFT_ROOM

        context_source = SOURCE_LIVE_DRAFT_ROOM if is_live_origin else SOURCE_IMPORTED_DRAFT
    except ImportError:
        context_source = "live_draft_room" if is_live_origin else SOURCE_IMPORTED_DRAFT

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
        draft_type=archive_draft_type,
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
        source=context_source,
        source_draft_id=draft_id,
    )
    context["league_id"] = league_id
    meta = dict(context.get("metadata") or {})
    meta["league_id"] = league_id
    if is_live_origin:
        meta["created_from"] = "live_draft"
        meta["source_draft_type"] = "live_draft_room"
        meta["creation_origin"] = str(
            shared.get("creation_origin")
            or (shared.get("metadata") or {}).get("creation_origin")
            or "live_draft_room"
        ).strip()
        room_code = str(
            shared.get("source_room_code") or (shared.get("metadata") or {}).get("source_room_code") or ""
        ).strip()
        if room_code:
            meta["source_room_code"] = room_code
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
    _append_invite_response_activity(
        shared,
        invite=invite,
        status=INVITE_STATUS_ACCEPTED,
        team_name=team,
        responder_user_id=uid,
    )

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
    try:
        from draft_room_participant_state import align_live_draft_session_with_active_league

        align_live_draft_session_with_active_league(session)
    except ImportError:
        pass
    _notify_invite_response_activity(
        session,
        invite=invite,
        status=INVITE_STATUS_ACCEPTED,
        team_name=team,
        league_name=league_name,
    )
    return entry, saved_context, ""


def merge_shared_into_context_for_invite(context: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    from fantasy_shared_league_store import merge_shared_into_context

    merged = merge_shared_into_context(context, shared)
    invites = shared.get("league_invites") or []
    if isinstance(invites, list):
        _set_league_invites(merged, [dict(x) for x in invites if isinstance(x, dict)])
    return merged


def _append_invite_response_activity(
    shared: dict[str, Any],
    *,
    invite: dict[str, Any],
    status: str,
    team_name: str = "",
    responder_user_id: str = "",
) -> None:
    """Record accept/decline on the shared league so the commissioner can see it."""
    activities = [dict(x) for x in (shared.get("league_activity") or []) if isinstance(x, dict)]
    invitee = str(
        invite.get("invitee_display_name")
        or invite.get("invitee_username")
        or invite.get("invitee_email")
        or invite.get("invitee_user_id")
        or "Invitee"
    ).strip()
    league_name = str(invite.get("league_name") or shared.get("league_name") or "your league").strip()
    if status == INVITE_STATUS_ACCEPTED and team_name:
        message = f"{invitee} accepted your invitation and claimed {team_name}"
    elif status == INVITE_STATUS_ACCEPTED:
        message = f"{invitee} accepted your invitation"
    else:
        message = f"{invitee} declined your invitation to {league_name}"
    activities.insert(
        0,
        {
            "activity_id": f"invite_{status}_{invite.get('invite_id') or uuid.uuid4().hex[:8]}",
            "kind": f"invite_{status}",
            "message": message,
            "invite_id": str(invite.get("invite_id") or "").strip(),
            "league_id": str(shared.get("league_id") or invite.get("league_id") or "").strip(),
            "team_name": str(team_name or "").strip(),
            "responder_user_id": str(responder_user_id or "").strip(),
            "created_at": _utc_now_iso(),
            "audience": "commissioner",
        },
    )
    shared["league_activity"] = activities[:100]


def _notify_invite_response_activity(
    session: dict[str, Any],
    *,
    invite: dict[str, Any],
    status: str,
    team_name: str = "",
    league_name: str = "",
) -> None:
    """Queue a session flash for invite responses (invitee-side write; commissioner reads shared)."""
    invitee = str(
        invite.get("invitee_display_name")
        or invite.get("invitee_username")
        or invite.get("invitee_email")
        or "Invitee"
    ).strip()
    name = str(league_name or invite.get("league_name") or "your league").strip()
    if status == INVITE_STATUS_ACCEPTED:
        message = f"{invitee} accepted your invitation"
        if team_name:
            message = f"{invitee} accepted your invitation and claimed {team_name}"
    else:
        message = f"{invitee} declined your invitation to {name}"
    pending = list(session.get("_league_invite_response_notifications") or [])
    pending.append(
        {
            "kind": f"invite_{status}",
            "message": message,
            "invite_id": str(invite.get("invite_id") or "").strip(),
            "league_id": str(invite.get("league_id") or "").strip(),
            "created_at": _utc_now_iso(),
        }
    )
    session["_league_invite_response_notifications"] = pending[-20:]


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
    _append_invite_response_activity(
        shared,
        invite=invite,
        status=INVITE_STATUS_DECLINED,
        responder_user_id=uid,
    )
    try:
        from fantasy_shared_league_store import save_shared_league

        save_shared_league(shared)
    except (ImportError, RuntimeError, OSError):
        return False, "Could not update invite status."
    remove_invite_from_inbox(_resolve_workspace_id(session), invite_id=invite_id, league_id=league_id)
    _notify_invite_response_activity(
        session,
        invite=invite,
        status=INVITE_STATUS_DECLINED,
        league_name=str(invite.get("league_name") or shared.get("league_name") or ""),
    )
    return True, ""


def list_commissioner_invite_response_notifications(
    session: dict[str, Any],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Pull unread accept/decline notices for leagues this account commissioned."""
    uid = _resolve_user_id()
    if not uid:
        return []
    seen = set(str(x) for x in (session.get("_league_invite_response_seen_ids") or []) if str(x).strip())
    alerts: list[dict[str, Any]] = []
    try:
        for doc in list_shared_league_documents() or []:
            if not isinstance(doc, dict):
                continue
            commissioner = str(doc.get("commissioner_user_id") or "").strip()
            if commissioner and not account_user_ids_match(commissioner, uid):
                continue
            for raw in doc.get("league_activity") or []:
                if not isinstance(raw, dict):
                    continue
                kind = str(raw.get("kind") or "").strip()
                if kind not in {f"invite_{INVITE_STATUS_ACCEPTED}", f"invite_{INVITE_STATUS_DECLINED}"}:
                    continue
                if str(raw.get("audience") or "") not in {"", "commissioner"}:
                    continue
                aid = str(raw.get("activity_id") or "").strip()
                if not aid or aid in seen:
                    continue
                alerts.append(
                    {
                        "alert_key": aid,
                        "kind": kind,
                        "message": str(raw.get("message") or "").strip(),
                        "league_id": str(raw.get("league_id") or doc.get("league_id") or "").strip(),
                        "created_at": str(raw.get("created_at") or "").strip(),
                    }
                )
    except Exception:
        pass
    alerts.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return alerts[: max(1, int(limit or 10))]


def mark_invite_response_notifications_seen(session: dict[str, Any], alert_keys: list[str]) -> None:
    seen = set(str(x) for x in (session.get("_league_invite_response_seen_ids") or []) if str(x).strip())
    for key in alert_keys:
        k = str(key or "").strip()
        if k:
            seen.add(k)
    session["_league_invite_response_seen_ids"] = sorted(seen)[-200:]


def unclaimed_teams_for_invite(
    shared: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    invitee_user_id: str = "",
    invitee_external_id: str = "",
    invitee_workspace_id: str = "",
) -> list[str]:
    """Teams available for an invitee to claim.

    A team is unavailable only when another account holds a *firm* claim.
    Provisional Live Draft reservations and the invitee's own preassignment remain claimable.
    """
    from fantasy_league_team_ownership import (
        account_user_ids_match,
        ownership_is_firm_claim,
        ownership_is_provisional,
    )

    rosters = shared.get("league_rosters") or {}
    ownership = shared.get("team_ownership") or {}
    if not isinstance(rosters, dict):
        return []
    if not isinstance(ownership, dict):
        ownership = {}

    uid = str(invitee_user_id or "").strip()
    external = str(invitee_external_id or "").strip().lower()
    workspace = str(invitee_workspace_id or "").strip().lower()
    if isinstance(session, dict):
        if not uid:
            uid = str(
                session.get("_suite_cloud_user_id")
                or session.get("_suite_auth_user_id")
                or _resolve_user_id()
                or ""
            ).strip()
        if not external:
            external = str(session.get("_suite_auth_external_id") or _resolve_external_id() or "").strip().lower()
        if not workspace:
            workspace = str(session.get("_suite_active_workspace_id") or _resolve_workspace_id(session) or "").strip().lower()
    if not uid:
        uid = str(_resolve_user_id() or "").strip()
    if not external:
        external = str(_resolve_external_id() or "").strip().lower()

    def _matches_invitee(record: dict[str, Any]) -> bool:
        owner_uid = str(record.get("user_id") or "").strip()
        if owner_uid and uid and account_user_ids_match(owner_uid, uid):
            return True
        reserved_uid = str(record.get("reserved_for_user_id") or "").strip()
        if reserved_uid and uid and account_user_ids_match(reserved_uid, uid):
            return True
        reserved_ext = str(record.get("reserved_for_external_id") or record.get("external_id") or "").strip().lower()
        if reserved_ext and external and reserved_ext == external:
            return True
        if reserved_ext and workspace and reserved_ext == workspace:
            return True
        reserved_email = str(record.get("reserved_for_email") or record.get("email") or "").strip().lower()
        if reserved_email and "@" in reserved_email:
            local = reserved_email.split("@", 1)[0]
            if external and local == external:
                return True
            if workspace and local == workspace:
                return True
        return False

    teams: list[str] = []
    for team_name in sorted(rosters.keys()):
        team = str(team_name or "").strip()
        if not team:
            continue
        record = ownership.get(team) if isinstance(ownership.get(team), dict) else {}
        if not ownership_is_firm_claim(record):
            # Unclaimed or provisional reservation — always selectable.
            teams.append(team)
            continue
        # Firm claim by this invitee (legacy Live Draft preassign) — still allow Accept.
        if _matches_invitee(record):
            teams.append(team)
            continue
    return teams


def _archive_team_count_hint(
    entry: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> int:
    """Team count from immutable snapshot, archive rosters, or linked context."""
    snap = entry.get("snapshot")
    if isinstance(snap, dict) and snap.get("team_count") is not None:
        return int(snap.get("team_count") or 0)
    rosters = entry.get("league_rosters") or {}
    if isinstance(rosters, dict) and rosters:
        return len([name for name in rosters.keys() if str(name).strip()])
    if isinstance(context, dict):
        ctx_rosters = context.get("league_rosters") or {}
        if isinstance(ctx_rosters, dict) and ctx_rosters:
            return len([name for name in ctx_rosters.keys() if str(name).strip()])
    return 0


def explain_upload_league_detection(
    entry: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Whether this archive counts as uploaded/shared for invite diagnostics."""
    try:
        from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_SIMULATOR
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, SOURCE_IMPORTED_DRAFT
    except ImportError as exc:
        return False, f"import failed: {exc}"

    draft_type = str(entry.get("draft_type") or "").strip()
    team_count = _archive_team_count_hint(entry, context)
    if draft_type == DRAFT_TYPE_IMPORTED:
        return True, "draft_type=imported_draft"
    if isinstance(context, dict):
        context_type = str(context.get("context_type") or "").strip()
        if context_type == CONTEXT_TYPE_REAL_LEAGUE:
            return True, "linked context_type=real_league"
        meta = context.get("metadata") or {}
        if str(meta.get("source") or context.get("source") or "") == SOURCE_IMPORTED_DRAFT:
            return True, "metadata.source=imported_draft"
    if draft_type == DRAFT_TYPE_SIMULATOR:
        return False, f"draft_type=simulator (team_count={team_count})"
    if team_count >= 2:
        return True, f"multi-team archive (team_count={team_count})"
    return False, f"not uploaded (draft_type={draft_type or '—'}, team_count={team_count})"


def _archive_looks_like_uploaded_league(
    entry: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> bool:
    """True when a Saved Draft Library entry is an uploaded/shared multi-team league."""
    looks, _reason = explain_upload_league_detection(entry, context)
    return looks


def _uploaded_league_archive_candidates(session: dict[str, Any]) -> list[dict[str, Any]]:
    """All session archives that look like uploaded/shared leagues (visible or not)."""
    try:
        from draft_archive_state import list_draft_archives
        from draft_archive_visibility import is_saved_draft_visible_to_session
        from fantasy_league_context import get_league_context_for_archive
    except ImportError:
        return []

    candidates: list[dict[str, Any]] = []
    for entry in list_draft_archives(session):
        if not isinstance(entry, dict):
            continue
        ctx = get_league_context_for_archive(session, entry)
        if not _archive_looks_like_uploaded_league(entry, ctx):
            continue
        row = copy.deepcopy(entry)
        row["_invite_diag_visible_on_library_card"] = is_saved_draft_visible_to_session(
            session,
            entry,
            context=ctx,
        )
        row["_invite_diag_team_count_hint"] = _archive_team_count_hint(entry, ctx)
        candidates.append(row)
    return candidates


def _visible_uploaded_league_archives(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Visible library cards that look like uploaded/shared multi-team leagues."""
    return [
        entry
        for entry in _uploaded_league_archive_candidates(session)
        if entry.get("_invite_diag_visible_on_library_card")
    ]


def _current_user_id_snapshot(session: dict[str, Any]) -> dict[str, str]:
    uid = _resolve_user_id(session)
    return {
        "current_user_id": uid,
        "session_cloud_user_id": str(session.get("_suite_cloud_user_id") or "").strip(),
        "session_auth_user_id": str(session.get("_suite_auth_user_id") or "").strip(),
        "session_external_id": _resolve_external_id(),
    }


def explain_commissioner_invite_block(
    context: dict[str, Any] | None,
    *,
    uid: str,
    entry: dict[str, Any] | None = None,
) -> str:
    """Human-readable reason this uploaded league cannot open the invite panel."""
    if not isinstance(context, dict):
        draft_id = str((entry or {}).get("draft_id") or "").strip()
        linked = str((entry or {}).get("league_context_id") or "").strip()
        if draft_id or linked:
            return (
                "linked league context missing "
                f"(draft_id={draft_id or '—'}, league_context_id={linked or '—'})"
            )
        return "no linked league context for this archive"
    context_type = str(context.get("context_type") or "").strip()
    if context_type != CONTEXT_TYPE_REAL_LEAGUE:
        return f"context_type={context_type or '—'} (need real_league)"
    if not uid:
        return "current_user_id empty — sign in required"
    if _joined_via_invite(context):
        return "joined_via_invite — only the upload commissioner may invite"
    if is_league_commissioner(context, uid):
        return "eligible commissioner"
    commissioner = get_commissioner_user_id(context)
    my_team = str(context.get("my_team_name") or "").strip()
    ownership = get_team_ownership(context)
    owner_rec = ownership.get(my_team) or {}
    owner_uid = str(owner_rec.get("user_id") or "").strip()
    if commissioner and not account_user_ids_match(commissioner, uid):
        if is_upload_commissioner_candidate(context, uid):
            return (
                f"commissioner_user_id mismatch ({commissioner}) but upload-owner candidate "
                f"(my_team={my_team or '—'}, owner={owner_uid or '—'})"
            )
        return (
            f"commissioner_user_id={commissioner or '—'} does not match current_user_id={uid or '—'} "
            f"and not upload-owner candidate (my_team={my_team or '—'}, owner={owner_uid or '—'})"
        )
    if not is_upload_commissioner_candidate(context, uid):
        return (
            f"not upload-owner candidate (my_team={my_team or '—'}, owner={owner_uid or '—'})"
        )
    return "unknown block — check team_ownership and commissioner_user_id"


def _invite_trace_row_for_archive(
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    uid: str,
    visible_on_library_card: bool,
) -> dict[str, Any]:
    from fantasy_league_context import get_league_context_for_archive

    ctx = get_league_context_for_archive(session, entry)
    looks_uploaded, upload_detection_reason = explain_upload_league_detection(entry, ctx)
    repaired = ctx
    if isinstance(ctx, dict):
        repaired, _ = repair_commissioner_identity(copy.deepcopy(ctx), session=None)
    block_reason = explain_commissioner_invite_block(ctx, uid=uid, entry=entry)
    ownership = get_team_ownership(ctx) if isinstance(ctx, dict) else {}
    meta = (ctx or {}).get("metadata") or {}
    ownership_sync = (
        build_team_ownership_sync_diagnostics(ctx)
        if isinstance(ctx, dict)
        else build_team_ownership_sync_diagnostics(None)
    )
    return {
        "draft_id": str(entry.get("draft_id") or "").strip(),
        "draft_name": str(entry.get("draft_name") or "").strip(),
        "draft_type": str(entry.get("draft_type") or "").strip(),
        "archive_team_name": str(entry.get("team_name") or "").strip(),
        "league_context_id": str(entry.get("league_context_id") or "").strip(),
        "visible_on_library_card": visible_on_library_card,
        "looks_like_uploaded_league": looks_uploaded,
        "upload_detection_reason": upload_detection_reason,
        "team_count_hint": _archive_team_count_hint(entry, ctx),
        "context_exists": isinstance(ctx, dict),
        "context_type": str((ctx or {}).get("context_type") or "").strip(),
        "my_team_name": str((ctx or {}).get("my_team_name") or entry.get("team_name") or "").strip(),
        "metadata_source": str(meta.get("source") or "").strip(),
        "commissioner_user_id": get_commissioner_user_id(ctx) if isinstance(ctx, dict) else "",
        "team_ownership": ownership,
        "team_ownership_local": ownership,
        "team_ownership_shared": ownership_sync.get("shared_team_ownership") or {},
        "ownership_sync": ownership_sync,
        "upload_owner_candidate": (
            is_upload_commissioner_candidate(ctx, uid) if isinstance(ctx, dict) else False
        ),
        "is_commissioner": is_league_commissioner(ctx, uid) if isinstance(ctx, dict) else False,
        "block_reason": block_reason,
        "would_select_for_invite": isinstance(repaired, dict) and is_league_commissioner(repaired, uid),
    }


def build_commissioner_invite_panel_trace(session: dict[str, Any]) -> dict[str, Any]:
    """Full invite-panel diagnostic for Saved Draft Library cards."""
    from draft_archive_state import list_draft_archives
    from draft_archive_visibility import is_saved_draft_visible_to_session, list_visible_draft_archives

    ids = _current_user_id_snapshot(session)
    uid = str(ids.get("current_user_id") or "").strip()
    visible_entries = list_visible_draft_archives(session)
    session_archive_count = len(list_draft_archives(session))
    uploaded_candidates = _uploaded_league_archive_candidates(session)
    uploaded_entries = _visible_uploaded_league_archives(session)
    invite_context = commissioner_invite_context(session)

    seen_draft_ids: set[str] = set()
    league_rows: list[dict[str, Any]] = []

    for entry in visible_entries:
        if not isinstance(entry, dict):
            continue
        draft_id = str(entry.get("draft_id") or "").strip()
        if not draft_id or draft_id in seen_draft_ids:
            continue
        seen_draft_ids.add(draft_id)
        league_rows.append(
            _invite_trace_row_for_archive(
                session,
                entry,
                uid=uid,
                visible_on_library_card=True,
            )
        )

    for entry in uploaded_candidates:
        draft_id = str(entry.get("draft_id") or "").strip()
        if not draft_id or draft_id in seen_draft_ids:
            continue
        seen_draft_ids.add(draft_id)
        league_rows.append(
            _invite_trace_row_for_archive(
                session,
                entry,
                uid=uid,
                visible_on_library_card=bool(entry.get("_invite_diag_visible_on_library_card")),
            )
        )

    if invite_context:
        invite_reason = "commissioner_invite_context matched a real_league context"
    elif not league_rows:
        invite_reason = (
            "commissioner_invite_context returned None — no Saved Draft Library cards in session "
            f"(session_draft_archive_count={session_archive_count})"
        )
    elif not uploaded_candidates:
        visible_types = ", ".join(
            f"{row.get('draft_type') or '—'}({row.get('team_count_hint') or 0} teams)"
            for row in league_rows
        )
        invite_reason = (
            "commissioner_invite_context returned None — visible library cards did not match "
            f"uploaded/shared detection ({visible_types or 'no cards'})"
        )
    elif not uploaded_entries:
        invite_reason = (
            "commissioner_invite_context returned None — uploaded league exists in session "
            "but no card is visible on Saved Draft Library (check membership / commissioner)"
        )
    else:
        blocked = [str(row.get("block_reason") or "") for row in league_rows if row.get("block_reason")]
        invite_reason = (
            "commissioner_invite_context returned None — "
            + ("; ".join(blocked) if blocked else "no eligible real_league commissioner context")
        )

    return {
        **ids,
        "session_draft_archive_count": session_archive_count,
        "visible_library_card_count": len(visible_entries),
        "uploaded_league_session_count": len(uploaded_candidates),
        "uploaded_league_card_count": len(uploaded_entries),
        "commissioner_invite_context_found": bool(invite_context),
        "commissioner_invite_context_reason": invite_reason,
        "selected_league_context_id": str((invite_context or {}).get("league_context_id") or "").strip(),
        "uploaded_leagues": league_rows,
        "invite_submit_trace": build_invite_submit_trace_snapshot(session),
        "library_sync_trace": session.get("_suite_shared_league_library_sync_trace"),
        "set_active_sync_trace": session.get("_suite_last_set_active_sync_trace"),
    }


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
        "invite_panel_trace": build_commissioner_invite_panel_trace(session),
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
