"""One-time corrective repairs for misclassified creation provenance."""

from __future__ import annotations

from typing import Any

# Known production imports misclassified as Live Draft by 727e07d backfill.
KNOWN_MISCLASSIFIED_IMPORT_DRAFTS: dict[str, dict[str, str]] = {
    "3ce50b4f2e8b": {
        "verified_origin": "validated_import",
        "repair_reason": "known_legacy_import_misclassified_as_live",
        "draft_name": "Upload Test Demo",
    },
}

KNOWN_LIVE_DRAFT_DRAFTS: dict[str, dict[str, str]] = {
    "c6810611c73e": {
        "verified_origin": "live_draft_room",
        "repair_reason": "known_canonical_live_draft_room",
        "draft_name": "Robins Fantasy",
    },
}


def repair_incorrect_creation_origin(
    session: dict[str, Any],
    *,
    draft_id: str,
    verified_origin: str,
    repair_reason: str,
) -> dict[str, Any]:
    """Guarded correction — only for verified migration evidence."""
    from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE, get_draft_archive
    from fantasy_league_context import (
        CREATION_ORIGIN_LIVE_DRAFT_ROOM,
        CREATION_ORIGIN_VALIDATED_IMPORT,
        SOURCE_IMPORTED_DRAFT,
        SOURCE_LIVE_DRAFT_ROOM,
        context_id_for_archive,
        get_league_context,
        upsert_league_context,
    )

    draft_id = str(draft_id or "").strip()
    origin = str(verified_origin or "").strip()
    trace: dict[str, Any] = {
        "draft_id": draft_id,
        "verified_origin": origin,
        "repair_reason": str(repair_reason or ""),
        "archive_updated": False,
        "context_updated": False,
        "shared_updated": False,
        "repair_persisted_to_disk": False,
        "repair_persisted_to_cloud": False,
        "repair_persisted_to_shared": False,
    }
    if not draft_id or not origin:
        trace["skipped"] = "missing_draft_id_or_origin"
        return trace

    is_import = origin == CREATION_ORIGIN_VALIDATED_IMPORT
    target_draft_type = DRAFT_TYPE_IMPORTED if is_import else DRAFT_TYPE_LIVE
    target_source = SOURCE_IMPORTED_DRAFT if is_import else SOURCE_LIVE_DRAFT_ROOM
    target_created_from = "validated_import" if is_import else "live_draft"

    entries = session.get(DRAFT_ARCHIVE_KEY)
    if isinstance(entries, list):
        for i, row in enumerate(entries):
            if not isinstance(row, dict) or str(row.get("draft_id") or "") != draft_id:
                continue
            patched = dict(row)
            patched["draft_type"] = target_draft_type
            patched["creation_origin"] = origin
            if is_import:
                patched.pop("shared_league_created", None)
            elif not is_import:
                patched["shared_league_created"] = True
            entries[i] = patched
            trace["archive_updated"] = True
            break
    session[DRAFT_ARCHIVE_KEY] = entries if isinstance(entries, list) else []

    ctx_id = context_id_for_archive(draft_id)
    ctx = get_league_context(session, ctx_id)
    if isinstance(ctx, dict):
        meta = dict(ctx.get("metadata") or {})
        meta["creation_origin"] = origin
        meta["source_draft_type"] = target_draft_type
        meta["created_from"] = target_created_from
        if is_import:
            meta.pop("joined_via_live_draft", None)
            meta.pop("preassigned_live_draft_owner", None)
        ctx = dict(ctx)
        ctx["source"] = target_source
        ctx["creation_origin"] = origin
        ctx["metadata"] = meta
        upsert_league_context(session, ctx, mark_persist_authoritative=True)
        trace["context_updated"] = True
        try:
            from fantasy_league_identity import resolve_canonical_league_id
            from fantasy_shared_league_store import load_shared_league, save_shared_league

            league_id = str(meta.get("league_id") or resolve_canonical_league_id(ctx) or "").strip()
            if league_id:
                shared = load_shared_league(league_id)
                if isinstance(shared, dict):
                    shared = dict(shared)
                    shared["creation_origin"] = origin
                    shared["source"] = target_source
                    shared["source_draft_type"] = target_draft_type
                    shared["created_from"] = target_created_from
                    shared_meta = dict(shared.get("metadata") or {})
                    shared_meta["creation_origin"] = origin
                    shared_meta["source_draft_type"] = target_draft_type
                    shared_meta["created_from"] = target_created_from
                    shared_meta["source"] = target_source
                    shared["metadata"] = shared_meta
                    if is_import:
                        shared.pop("joined_via_live_draft", None)
                        shared.pop("preassigned_live_draft_owner", None)
                        shared_meta.pop("joined_via_live_draft", None)
                        shared_meta.pop("preassigned_live_draft_owner", None)
                    save_shared_league(shared)
                    trace["shared_updated"] = True
                    trace["repair_persisted_to_shared"] = True
        except ImportError:
            pass

    trace["archive_draft_type"] = target_draft_type
    trace["context_creation_origin"] = origin
    trace["context_source"] = target_source
    trace["context_source_draft_type"] = target_draft_type
    session.setdefault("_creation_origin_repair_trace", []).append(trace)
    return trace


def repair_known_misclassified_import_origins(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Idempotent production correction for known poisoned import drafts."""
    traces: list[dict[str, Any]] = []
    for draft_id, spec in KNOWN_MISCLASSIFIED_IMPORT_DRAFTS.items():
        trace = repair_incorrect_creation_origin(
            session,
            draft_id=draft_id,
            verified_origin=spec["verified_origin"],
            repair_reason=spec["repair_reason"],
        )
        traces.append(trace)
    return traces


def repair_known_canonical_live_draft_origins(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Idempotent correction for canonical live drafts mislabeled as imports."""
    traces: list[dict[str, Any]] = []
    for draft_id, spec in KNOWN_LIVE_DRAFT_DRAFTS.items():
        trace = repair_incorrect_creation_origin(
            session,
            draft_id=draft_id,
            verified_origin=spec["verified_origin"],
            repair_reason=spec["repair_reason"],
        )
        traces.append(trace)
    return traces


def repair_poisoned_live_draft_creation_origins(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Correct Live Draft leagues whose creation_origin/draft_type were poisoned as import.

    Detects `created_from=live_draft` (or source_room_code) while archive/context still
    carries validated_import / imported_draft labels. Generic — not draft-id hardcoding.
    """
    from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, get_draft_archive
    from fantasy_league_context import (
        CREATION_ORIGIN_LIVE_DRAFT_ROOM,
        CREATION_ORIGIN_VALIDATED_IMPORT,
        _canonical_live_created_from,
        context_id_for_archive,
        get_league_context,
        list_league_contexts,
        read_immutable_creation_origin,
    )

    traces: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _maybe_repair(draft_id: str, *, context: dict | None, archive: dict | None, shared: dict | None) -> None:
        draft_id = str(draft_id or "").strip()
        if not draft_id or draft_id in seen:
            return
        if not _canonical_live_created_from(context=context, shared_doc=shared, archive_entry=archive):
            return
        origin = read_immutable_creation_origin(
            context=context, shared_doc=shared, archive_entry=archive
        )
        archive_type = str((archive or {}).get("draft_type") or "").strip()
        poisoned = origin == CREATION_ORIGIN_VALIDATED_IMPORT or archive_type == DRAFT_TYPE_IMPORTED
        if not poisoned:
            return
        seen.add(draft_id)
        traces.append(
            repair_incorrect_creation_origin(
                session,
                draft_id=draft_id,
                verified_origin=CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                repair_reason="poisoned_import_origin_live_created_from",
            )
        )

    for ctx in list_league_contexts(session):
        if not isinstance(ctx, dict):
            continue
        meta = dict(ctx.get("metadata") or {})
        draft_id = str(meta.get("source_draft_id") or "").strip()
        if not draft_id:
            cid = str(ctx.get("league_context_id") or "")
            if cid.startswith("archive:"):
                draft_id = cid.split(":", 1)[-1].strip()
        archive = get_draft_archive(session, draft_id) if draft_id else None
        shared = None
        try:
            from fantasy_league_identity import resolve_canonical_league_id
            from fantasy_shared_league_store import load_shared_league

            league_id = str(resolve_canonical_league_id(ctx) or "").strip()
            if league_id:
                shared = load_shared_league(league_id)
        except ImportError:
            shared = None
        _maybe_repair(
            draft_id,
            context=ctx,
            archive=archive if isinstance(archive, dict) else None,
            shared=shared if isinstance(shared, dict) else None,
        )

    entries = session.get(DRAFT_ARCHIVE_KEY)
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            draft_id = str(entry.get("draft_id") or "").strip()
            linked = str(entry.get("league_context_id") or "").strip() or context_id_for_archive(draft_id)
            ctx = get_league_context(session, linked)
            shared = None
            if isinstance(ctx, dict):
                try:
                    from fantasy_league_identity import resolve_canonical_league_id
                    from fantasy_shared_league_store import load_shared_league

                    league_id = str(resolve_canonical_league_id(ctx) or "").strip()
                    if league_id:
                        shared = load_shared_league(league_id)
                except ImportError:
                    shared = None
            _maybe_repair(
                draft_id,
                context=ctx if isinstance(ctx, dict) else None,
                archive=entry,
                shared=shared if isinstance(shared, dict) else None,
            )
    return traces


def repair_known_canonical_creation_origins(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Run all guarded canonical provenance repairs."""
    traces = repair_known_misclassified_import_origins(session)
    traces.extend(repair_known_canonical_live_draft_origins(session))
    traces.extend(repair_poisoned_live_draft_creation_origins(session))
    return traces
