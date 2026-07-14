"""Cross-account shared league document — rosters, ownership, trade proposals."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from fantasy_league_identity import compute_draft_fingerprint, resolve_canonical_league_id

WORKFLOW_KEY_TRADE_PROPOSALS = "trade_proposals"
WORKFLOW_KEY_LEAGUE_INVITES = "league_invites"
WORKFLOW_KEY_LEAGUE_ACTIVITY = "league_activity"

DATA_DIR = Path(__file__).resolve().parent / "data" / "shared_leagues"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def shared_league_document_from_context(
    context: dict[str, Any],
    *,
    revision: int = 1,
    existing: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = copy.deepcopy(context)
    league_id = resolve_canonical_league_id(context)
    fp = compute_draft_fingerprint(context)
    workflow = context.get("workflow") or {}
    proposals = workflow.get(WORKFLOW_KEY_TRADE_PROPOSALS) or []
    if not isinstance(proposals, list):
        proposals = []
    invites = workflow.get(WORKFLOW_KEY_LEAGUE_INVITES) or []
    if not isinstance(invites, list):
        invites = []
    activity = workflow.get(WORKFLOW_KEY_LEAGUE_ACTIVITY) or []
    if not isinstance(activity, list):
        activity = []
    ownership = context.get("team_ownership")
    if not isinstance(ownership, dict):
        meta = context.get("metadata") or {}
        ownership = meta.get("team_ownership") or {}
    meta = context.get("metadata") or {}
    try:
        from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE
        from fantasy_league_context import resolve_archive_draft_type_with_reason

        draft_type, _, _ = resolve_archive_draft_type_with_reason(
            context=context,
            shared_doc=existing if isinstance(existing, dict) else None,
            session=session,
        )
        existing_type = None
        if isinstance(existing, dict):
            existing_type, _, _ = resolve_archive_draft_type_with_reason(
                shared_doc=existing,
                session=session,
            )
        if existing_type == DRAFT_TYPE_LIVE and draft_type == DRAFT_TYPE_IMPORTED:
            draft_type = existing_type
    except ImportError:
        draft_type = str(context.get("source") or meta.get("source_draft_type") or "").strip()
        DRAFT_TYPE_LIVE = "live_draft_room"
        DRAFT_TYPE_IMPORTED = "imported_draft"
    creation_origin = str(meta.get("creation_origin") or "").strip()
    existing_meta = dict((existing or {}).get("metadata") or {}) if isinstance(existing, dict) else {}
    preexisting_created_from = str(
        meta.get("created_from")
        or (existing or {}).get("created_from")
        or existing_meta.get("created_from")
        or ""
    ).strip()
    # Never let a poisoned import resolve wipe Live Draft provenance on push.
    if preexisting_created_from == "live_draft" or str(
        (existing or {}).get("source_room_code") or existing_meta.get("source_room_code") or meta.get("source_room_code") or ""
    ).strip():
        draft_type = DRAFT_TYPE_LIVE
    if draft_type == DRAFT_TYPE_LIVE:
        created_from = "live_draft"
        source = "live_draft_room"
        source_draft_type = "live_draft_room"
        try:
            from fantasy_league_context import CREATION_ORIGIN_LIVE_DRAFT_ROOM, CREATION_ORIGIN_VALIDATED_IMPORT

            if not creation_origin or creation_origin == CREATION_ORIGIN_VALIDATED_IMPORT:
                creation_origin = CREATION_ORIGIN_LIVE_DRAFT_ROOM
        except ImportError:
            if not creation_origin or creation_origin == "validated_import":
                creation_origin = "live_draft_room"
    elif draft_type == DRAFT_TYPE_IMPORTED:
        created_from = str(meta.get("created_from") or "imported_draft").strip() or "imported_draft"
        source = "imported_draft"
        source_draft_type = "imported_draft"
        if not creation_origin:
            try:
                from fantasy_league_context import CREATION_ORIGIN_VALIDATED_IMPORT

                creation_origin = CREATION_ORIGIN_VALIDATED_IMPORT
            except ImportError:
                creation_origin = "validated_import"
    else:
        source = str(context.get("source") or meta.get("source") or "").strip()
        created_from = str(meta.get("created_from") or "").strip()
        source_draft_type = str(meta.get("source_draft_type") or source or "").strip()
    room_code = str(
        meta.get("source_room_code")
        or existing_meta.get("source_room_code")
        or (existing or {}).get("source_room_code")
        or ""
    ).strip()
    draft_results = (
        meta.get("draft_results")
        or context.get("draft_results")
        or existing_meta.get("draft_results")
        or (existing or {}).get("draft_results")
    )
    metadata_out = {
        "created_from": created_from,
        "source_draft_type": source_draft_type,
        "source": source,
    }
    if creation_origin:
        metadata_out["creation_origin"] = creation_origin
    if room_code:
        metadata_out["source_room_code"] = room_code
    if isinstance(draft_results, list) and draft_results:
        metadata_out["draft_results"] = copy.deepcopy(draft_results)
    document = {
        "schema_version": 1,
        "league_id": league_id,
        "draft_fingerprint": fp,
        "draft_id": str((context.get("metadata") or {}).get("source_draft_id") or "").strip(),
        "league_name": str(context.get("league_name") or context.get("display_name") or "").strip(),
        "commissioner_user_id": str(meta.get("commissioner_user_id") or "").strip(),
        "revision": int(revision or 1),
        "updated_at": _utc_now_iso(),
        "created_from": created_from,
        "source_draft_type": source_draft_type,
        "source": source,
        "creation_origin": creation_origin,
        "metadata": metadata_out,
        "league_rosters": copy.deepcopy(context.get("league_rosters") or {}),
        "roster_settings": copy.deepcopy(context.get("roster_settings") or {}),
        "team_ownership": copy.deepcopy(ownership if isinstance(ownership, dict) else {}),
        "trade_proposals": copy.deepcopy(proposals),
        "league_invites": copy.deepcopy(invites),
        "league_activity": copy.deepcopy(activity),
    }
    if room_code:
        document["source_room_code"] = room_code
    if isinstance(draft_results, list) and draft_results:
        document["draft_results"] = copy.deepcopy(draft_results)
    return document


@runtime_checkable
class SharedLeagueStore(Protocol):
    def exists(self, league_id: str) -> bool: ...

    def load(self, league_id: str) -> dict[str, Any] | None: ...

    def save(self, document: dict[str, Any]) -> dict[str, Any]: ...

    def save_if_revision(
        self,
        document: dict[str, Any],
        *,
        expected_revision: int | None,
    ) -> tuple[bool, dict[str, Any] | None]: ...

    def list_documents(self) -> list[dict[str, Any]]: ...


class LocalFileSharedLeagueStore:
    """Dev/test backend — one JSON file per canonical league_id."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DATA_DIR

    def _path(self, league_id: str) -> Path:
        safe = str(league_id or "").strip().replace(":", "_").replace("/", "_")
        return self.root / f"{safe}.json"

    def exists(self, league_id: str) -> bool:
        return self._path(league_id).is_file()

    def load(self, league_id: str) -> dict[str, Any] | None:
        path = self._path(league_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return raw if isinstance(raw, dict) else None

    def save(self, document: dict[str, Any]) -> dict[str, Any]:
        league_id = str(document.get("league_id") or "").strip()
        if not league_id:
            raise ValueError("shared league document missing league_id")
        self.root.mkdir(parents=True, exist_ok=True)
        out = copy.deepcopy(document)
        out["updated_at"] = _utc_now_iso()
        self._path(league_id).write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    def save_if_revision(
        self,
        document: dict[str, Any],
        *,
        expected_revision: int | None,
    ) -> tuple[bool, dict[str, Any] | None]:
        league_id = str(document.get("league_id") or "").strip()
        existing = self.load(league_id)
        if expected_revision is not None and isinstance(existing, dict):
            current = int(existing.get("revision") or 0)
            if current != int(expected_revision):
                return False, existing
        saved = self.save(document)
        return True, saved

    def list_documents(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        docs: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(raw, dict):
                docs.append(raw)
        return docs


_SHARED_STORE: SharedLeagueStore | None = None


def get_shared_league_store() -> SharedLeagueStore:
    global _SHARED_STORE
    if _SHARED_STORE is not None:
        return _SHARED_STORE
    try:
        from fantasy_shared_league_supabase_store import get_supabase_shared_league_store

        store = get_supabase_shared_league_store()
        _SHARED_STORE = store
        return store
    except Exception:
        _SHARED_STORE = LocalFileSharedLeagueStore()
        return _SHARED_STORE


def set_shared_league_store(store: SharedLeagueStore | None) -> None:
    global _SHARED_STORE
    _SHARED_STORE = store


def load_shared_league(league_id: str, *, store: SharedLeagueStore | None = None) -> dict[str, Any] | None:
    backend = store or get_shared_league_store()
    return backend.load(str(league_id or "").strip())


def list_shared_league_documents(*, store: SharedLeagueStore | None = None) -> list[dict[str, Any]]:
    backend = store or get_shared_league_store()
    try:
        return list(backend.list_documents())
    except Exception:
        return []


def save_shared_league(document: dict[str, Any], *, store: SharedLeagueStore | None = None) -> dict[str, Any]:
    backend = store or get_shared_league_store()
    return backend.save(document)


def _proposal_sort_key(proposal: dict[str, Any]) -> str:
    return str(proposal.get("updated_at") or proposal.get("created_at") or "")


def _proposal_status_rank(status: str) -> int:
    terminal = {
        "accepted": 5,
        "declined": 5,
        "canceled": 5,
        "countered": 5,
        "expired": 5,
        "stale": 5,
        "pending": 1,
    }
    return terminal.get(str(status or "").strip(), 0)


def _merge_single_proposal(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_rank = _proposal_status_rank(str(existing.get("status") or ""))
    incoming_rank = _proposal_status_rank(str(incoming.get("status") or ""))
    if incoming_rank > existing_rank:
        primary, secondary = incoming, existing
    elif existing_rank > incoming_rank:
        primary, secondary = existing, incoming
    elif _proposal_sort_key(incoming) >= _proposal_sort_key(existing):
        primary, secondary = incoming, existing
    else:
        primary, secondary = existing, incoming
    merged = copy.deepcopy(primary)
    for key in (
        "expires_at",
        "accepted_at",
        "declined_at",
        "responded_at",
        "from_user_display",
        "verdict",
        "give_player_ids",
        "receive_player_ids",
    ):
        if not str(merged.get(key) or "").strip() and str(secondary.get(key) or "").strip():
            merged[key] = secondary[key]
    return merged


def _merge_trade_proposals(*sources: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for proposals in sources:
        if not isinstance(proposals, list):
            continue
        for raw in proposals:
            if not isinstance(raw, dict):
                continue
            pid = str(raw.get("trade_id") or raw.get("proposal_id") or "").strip()
            if not pid:
                continue
            existing = merged.get(pid)
            if existing is None:
                merged[pid] = copy.deepcopy(raw)
            else:
                merged[pid] = _merge_single_proposal(existing, raw)
    return sorted(merged.values(), key=_proposal_sort_key, reverse=True)


def _invite_sort_key(invite: dict[str, Any]) -> str:
    return str(invite.get("responded_at") or invite.get("accepted_at") or invite.get("created_at") or "")


def _invite_status_rank(status: str) -> int:
    return {
        "accepted": 5,
        "declined": 5,
        "revoked": 5,
        "expired": 5,
        "pending": 1,
    }.get(str(status or "").strip(), 0)


def _merge_single_invite(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_rank = _invite_status_rank(str(existing.get("status") or ""))
    incoming_rank = _invite_status_rank(str(incoming.get("status") or ""))
    if incoming_rank > existing_rank:
        primary, secondary = incoming, existing
    elif existing_rank > incoming_rank:
        primary, secondary = existing, incoming
    elif _invite_sort_key(incoming) >= _invite_sort_key(existing):
        primary, secondary = incoming, existing
    else:
        primary, secondary = existing, incoming
    merged = copy.deepcopy(primary)
    for key in ("claimed_team", "accepted_at", "responded_at", "invited_by_display"):
        if not str(merged.get(key) or "").strip() and str(secondary.get(key) or "").strip():
            merged[key] = secondary[key]
    return merged


def _merge_league_invites(*sources: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for invites in sources:
        if not isinstance(invites, list):
            continue
        for raw in invites:
            if not isinstance(raw, dict):
                continue
            iid = str(raw.get("invite_id") or "").strip()
            if not iid:
                continue
            existing = merged.get(iid)
            if existing is None:
                merged[iid] = copy.deepcopy(raw)
            else:
                merged[iid] = _merge_single_invite(existing, raw)
    return sorted(merged.values(), key=_invite_sort_key, reverse=True)


def _activity_sort_key(entry: dict[str, Any]) -> str:
    return str(entry.get("recorded_at") or entry.get("created_at") or "")


def _activity_merge_key(entry: dict[str, Any]) -> str:
    proposal_id = str(entry.get("proposal_id") or "").strip()
    action = str(entry.get("action") or "").strip()
    recorded = str(entry.get("recorded_at") or "").strip()
    if proposal_id and action:
        return f"{proposal_id}::{action}::{recorded}"
    summary = str(entry.get("summary") or "").strip()
    team = str(entry.get("team_name") or "").strip()
    return f"{team}::{action}::{recorded}::{summary}"


def _merge_league_activity(*sources: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for activities in sources:
        if not isinstance(activities, list):
            continue
        for raw in activities:
            if not isinstance(raw, dict):
                continue
            key = _activity_merge_key(raw)
            if not key.strip(":"):
                continue
            existing = merged.get(key)
            if existing is None or _activity_sort_key(raw) >= _activity_sort_key(existing):
                merged[key] = copy.deepcopy(raw)
    ordered = sorted(merged.values(), key=_activity_sort_key, reverse=True)
    return ordered[:100]


def _merge_team_ownership(*sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for team, record in source.items():
            team_name = str(team or "").strip()
            if not team_name or not isinstance(record, dict):
                continue
            existing = merged.get(team_name)
            if existing is None:
                merged[team_name] = copy.deepcopy(record)
                continue
            existing_ts = str(existing.get("assigned_at") or "")
            incoming_ts = str(record.get("assigned_at") or "")
            if incoming_ts >= existing_ts:
                merged[team_name] = copy.deepcopy(record)
    return merged


def _roster_content_fingerprint(rosters: Any) -> str:
    if not isinstance(rosters, dict):
        return ""
    payload = {
        team: sorted(
            str(p.get("player_key") or p.get("player_name") or "").strip().lower()
            for p in (entry.get("players") or [])
            if isinstance(p, dict)
            for _ in [0]
            if str(p.get("player_key") or p.get("player_name") or "").strip()
        )
        for team, entry in sorted(rosters.items())
        if isinstance(entry, dict)
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def merge_shared_into_context(context: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    """Apply shared league document onto a local league context."""
    out = copy.deepcopy(context)
    shared_revision = int(shared.get("revision") or 0)
    local_revision = int((out.get("metadata") or {}).get("shared_revision") or 0)
    shared_rosters = shared.get("league_rosters")
    local_rosters = out.get("league_rosters") or {}
    shared_fp = _roster_content_fingerprint(shared_rosters)
    local_fp = _roster_content_fingerprint(local_rosters)
    if isinstance(shared_rosters, dict) and shared_rosters and (
        shared_revision > local_revision or shared_fp != local_fp
    ):
        out["league_rosters"] = copy.deepcopy(shared_rosters)
    shared_roster_settings = shared.get("roster_settings")
    local_roster_settings = out.get("roster_settings") or {}
    shared_format = (
        shared_roster_settings.get("lineup_format")
        if isinstance(shared_roster_settings, dict)
        else None
    )
    local_format = (
        local_roster_settings.get("lineup_format")
        if isinstance(local_roster_settings, dict)
        else None
    )
    if isinstance(shared_roster_settings, dict) and shared_roster_settings and shared_format and (
        not local_format or shared_revision >= local_revision
    ):
        merged_settings = dict(local_roster_settings if isinstance(local_roster_settings, dict) else {})
        merged_settings.update(copy.deepcopy(shared_roster_settings))
        out["roster_settings"] = merged_settings
    ownership = _merge_team_ownership(get_team_ownership_from_context(out), shared.get("team_ownership") or {})
    out["team_ownership"] = ownership
    meta = dict(out.get("metadata") or {})
    meta["team_ownership"] = copy.deepcopy(ownership)
    meta["shared_revision"] = max(local_revision, shared_revision)
    out["metadata"] = meta
    workflow = dict(out.get("workflow") or {})
    local_proposals = workflow.get(WORKFLOW_KEY_TRADE_PROPOSALS) or []
    merged_proposals = _merge_trade_proposals(
        local_proposals if isinstance(local_proposals, list) else [],
        shared.get("trade_proposals") or [],
    )
    workflow[WORKFLOW_KEY_TRADE_PROPOSALS] = merged_proposals
    local_invites = workflow.get(WORKFLOW_KEY_LEAGUE_INVITES) or []
    merged_invites = _merge_league_invites(
        local_invites if isinstance(local_invites, list) else [],
        shared.get("league_invites") or [],
    )
    workflow[WORKFLOW_KEY_LEAGUE_INVITES] = merged_invites
    local_activity = workflow.get(WORKFLOW_KEY_LEAGUE_ACTIVITY) or []
    merged_activity = _merge_league_activity(
        local_activity if isinstance(local_activity, list) else [],
        shared.get("league_activity") or [],
    )
    workflow[WORKFLOW_KEY_LEAGUE_ACTIVITY] = merged_activity
    out["workflow"] = workflow
    try:
        from fantasy_trade_roster_sync import reconcile_accepted_trades_in_context

        out, _changed, _traces = reconcile_accepted_trades_in_context(out)
    except ImportError:
        pass
    return out


def get_team_ownership_from_context(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = context.get("team_ownership")
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    meta = context.get("metadata") or {}
    raw = meta.get("team_ownership")
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def _claimed_teams_from_ownership(ownership: dict[str, Any] | None) -> set[str]:
    claimed: set[str] = set()
    if not isinstance(ownership, dict):
        return claimed
    try:
        from fantasy_league_team_ownership import ownership_is_firm_claim
    except ImportError:
        ownership_is_firm_claim = lambda record: bool(str((record or {}).get("user_id") or "").strip())  # type: ignore[assignment,misc]
    for team, record in ownership.items():
        team_name = str(team or "").strip()
        if not team_name or not isinstance(record, dict):
            continue
        if ownership_is_firm_claim(record):
            claimed.add(team_name)
    return claimed


def compare_local_and_shared_team_ownership(
    local: dict[str, Any] | None,
    shared: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare session league context ownership vs canonical shared document."""
    local_map = local if isinstance(local, dict) else {}
    shared_map = shared if isinstance(shared, dict) else {}
    local_claimed = _claimed_teams_from_ownership(local_map)
    shared_claimed = _claimed_teams_from_ownership(shared_map)
    teams_only_in_shared = sorted(shared_claimed - local_claimed)
    teams_only_in_local = sorted(local_claimed - shared_claimed)
    teams_with_different_owner: list[str] = []
    shared_has_newer_ownership = bool(teams_only_in_shared)
    for team in sorted(local_claimed & shared_claimed):
        local_uid = str((local_map.get(team) or {}).get("user_id") or "").strip()
        shared_uid = str((shared_map.get(team) or {}).get("user_id") or "").strip()
        if local_uid and shared_uid:
            try:
                from fantasy_league_team_ownership import account_user_ids_match

                if not account_user_ids_match(local_uid, shared_uid):
                    teams_with_different_owner.append(team)
            except ImportError:
                if local_uid != shared_uid:
                    teams_with_different_owner.append(team)
        local_ts = str((local_map.get(team) or {}).get("assigned_at") or "")
        shared_ts = str((shared_map.get(team) or {}).get("assigned_at") or "")
        if shared_ts > local_ts:
            shared_has_newer_ownership = True
    return {
        "local_claimed_count": len(local_claimed),
        "shared_claimed_count": len(shared_claimed),
        "teams_only_in_shared": teams_only_in_shared,
        "teams_only_in_local": teams_only_in_local,
        "teams_with_different_owner": teams_with_different_owner,
        "shared_has_newer_ownership": shared_has_newer_ownership,
        "local_stale_vs_shared": bool(
            teams_only_in_shared or teams_with_different_owner or shared_has_newer_ownership
        ),
    }


def build_team_ownership_sync_diagnostics(
    context: dict[str, Any] | None,
    *,
    shared_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Local vs canonical shared ownership snapshot for diagnostics."""
    if not isinstance(context, dict):
        return {
            "league_id": "",
            "shared_doc_found": False,
            "local_team_ownership": {},
            "shared_team_ownership": {},
            "comparison": compare_local_and_shared_team_ownership({}, {}),
        }
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    local_ownership = get_team_ownership_from_context(context)
    local_revision = int((context.get("metadata") or {}).get("shared_revision") or 0)
    shared = shared_doc if isinstance(shared_doc, dict) else None
    if shared is None and league_id:
        loaded = load_shared_league(league_id)
        shared = loaded if isinstance(loaded, dict) else None
    shared_ownership = (
        copy.deepcopy(shared.get("team_ownership") or {}) if isinstance(shared, dict) else {}
    )
    shared_revision = int(shared.get("revision") or 0) if isinstance(shared, dict) else 0
    comparison = compare_local_and_shared_team_ownership(local_ownership, shared_ownership)
    if shared_revision > local_revision and not comparison.get("local_stale_vs_shared"):
        comparison = dict(comparison)
        comparison["shared_has_newer_ownership"] = True
        comparison["local_stale_vs_shared"] = True
    return {
        "league_id": league_id or None,
        "league_context_id": str(context.get("league_context_id") or "").strip() or None,
        "shared_doc_found": isinstance(shared, dict),
        "local_shared_revision": local_revision,
        "shared_doc_revision": shared_revision,
        "shared_doc_updated_at": str(shared.get("updated_at") or "") if isinstance(shared, dict) else None,
        "local_team_ownership": local_ownership,
        "shared_team_ownership": shared_ownership,
        "comparison": comparison,
    }


def sync_context_with_shared_store(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    store: SharedLeagueStore | None = None,
) -> dict[str, Any]:
    from fantasy_league_context import upsert_league_context
    from fantasy_workspace_team_identity import overlay_workspace_team_on_context, record_team_identity_trace

    league_id = resolve_canonical_league_id(context)
    if not league_id:
        return context
    shared = load_shared_league(league_id, store=store)
    if not isinstance(shared, dict):
        return context
    pre_merge_team = str(context.get("my_team_name") or "").strip()
    merged = merge_shared_into_context(context, shared)
    pre_roster_fp = _roster_content_fingerprint(context.get("league_rosters"))
    post_roster_fp = _roster_content_fingerprint(merged.get("league_rosters"))
    roster_changed = pre_roster_fp != post_roster_fp
    merged = overlay_workspace_team_on_context(
        session,
        merged,
        shared_doc=shared,
        trace_phase="sync_context_with_shared_store",
        record_trace=True,
    )
    if not isinstance(merged, dict):
        merged = context
    if roster_changed:
        try:
            from fantasy_trade_roster_sync import finalize_trade_roster_persistence

            finalize_trade_roster_persistence(session, merged)
            merged = upsert_league_context(session, merged, mark_persist_authoritative=False)
            push_league_context_to_shared(session, merged)
        except ImportError:
            pass
        except Exception:
            pass
    record_team_identity_trace(
        session,
        phase="sync_context_with_shared_store",
        pre_merge_team=pre_merge_team or None,
        post_merge_team=str(merged.get("my_team_name") or "").strip() or None,
    )
    return upsert_league_context(session, merged, mark_persist_authoritative=False)


def push_league_context_to_shared(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    store: SharedLeagueStore | None = None,
) -> dict[str, Any] | None:
    league_id = resolve_canonical_league_id(context)
    if not league_id:
        return None
    backend = store or get_shared_league_store()
    existing = backend.load(league_id)
    base_revision = int(existing.get("revision") or 0) if isinstance(existing, dict) else 0
    revision = max(base_revision + 1, int((context.get("metadata") or {}).get("shared_revision") or 0) + 1)
    document = shared_league_document_from_context(
        context,
        revision=revision,
        existing=existing if isinstance(existing, dict) else None,
        session=session,
    )
    document["league_rosters"] = copy.deepcopy(context.get("league_rosters") or {})
    document["roster_settings"] = copy.deepcopy(context.get("roster_settings") or {})
    if isinstance(existing, dict):
        merged_proposals = _merge_trade_proposals(
            existing.get("trade_proposals") or [],
            document.get("trade_proposals") or [],
        )
        document["trade_proposals"] = merged_proposals
        document["team_ownership"] = _merge_team_ownership(
            existing.get("team_ownership") or {},
            document.get("team_ownership") or {},
        )
        document["league_invites"] = _merge_league_invites(
            existing.get("league_invites") or [],
            document.get("league_invites") or [],
        )
        document["league_activity"] = _merge_league_activity(
            existing.get("league_activity") or [],
            document.get("league_activity") or [],
        )
    saved = backend.save(document)
    meta = dict(context.get("metadata") or {})
    meta["shared_revision"] = int((saved or document).get("revision") or document.get("revision") or 1)
    context["metadata"] = meta
    try:
        from fantasy_league_context import upsert_league_context

        upsert_league_context(session, context, mark_persist_authoritative=False)
    except ImportError:
        pass
    return saved
