"""Compact Saved Draft Library manifest — content clocks authoritative across devices."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

MANIFEST_SESSION_KEY = "_draft_library_manifest"
MANIFEST_FP_KEY = "_draft_library_manifest_fp"
MANIFEST_DOC_KEY = "fantasy_library_manifest"
MANIFEST_REV_DOC_KEY = "fantasy_library_manifest_revision"
LAST_MANIFEST_SYNC_KEY = "_library_manifest_last_sync"

_TEST_CLOUD_STORE: dict[str, dict[str, Any]] | None = None


def install_test_manifest_cloud_store(store: dict[str, dict[str, Any]] | None) -> None:
    global _TEST_CLOUD_STORE
    _TEST_CLOUD_STORE = store


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _content_updated_at(entry: dict[str, Any]) -> str:
    return str(
        entry.get("content_updated_at")
        or entry.get("updated_at")
        or entry.get("created_at")
        or ""
    ).strip()


def _content_revision(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("content_revision") or 0)
    except (TypeError, ValueError):
        return 0


def summarize_archive_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """One card's worth of metadata — no roster payloads."""
    if not isinstance(entry, dict):
        return {}
    teams = entry.get("teams") or entry.get("team_names") or []
    if not teams:
        snap = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
        teams = snap.get("team_names") or []
    team_count = len(teams) if isinstance(teams, (list, tuple)) else int(entry.get("team_count") or 0)
    players = entry.get("players") or entry.get("roster") or []
    player_count = len(players) if isinstance(players, (list, tuple)) else int(entry.get("player_count") or 0)
    if player_count <= 0:
        snap = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
        try:
            player_count = int(snap.get("my_team_player_count") or 0)
        except (TypeError, ValueError):
            player_count = 0
    draft_type = str(entry.get("draft_type") or entry.get("type") or "").strip()
    content_at = _content_updated_at(entry)
    content_rev = _content_revision(entry)
    if content_rev <= 0 and content_at:
        content_rev = 1
    return {
        "draft_id": str(entry.get("draft_id") or "").strip(),
        "display_name": str(entry.get("draft_name") or entry.get("display_name") or "Saved Draft").strip(),
        "type": draft_type,
        "draft_type": draft_type,
        "creation_origin": str(entry.get("creation_origin") or "").strip(),
        "team_count": team_count,
        "player_count": player_count,
        "active_flag": bool(entry.get("is_active")),
        "context_id": str(entry.get("league_context_id") or "").strip(),
        "league_context_id": str(entry.get("league_context_id") or "").strip(),
        "league_id": str(entry.get("league_id") or entry.get("canonical_league_id") or "").strip(),
        "canonical_league_id": str(entry.get("league_id") or entry.get("canonical_league_id") or "").strip(),
        "created_at": str(entry.get("created_at") or "").strip(),
        "content_updated_at": content_at,
        "content_revision": content_rev,
        "updated_revision": f"{content_rev}:{content_at}",
        "is_deleted": bool(entry.get("is_deleted") or entry.get("tombstone")),
    }


def _manifest_settings_app(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import scoped_cloud_app_id

        ws = str(session.get("_suite_active_workspace_id") or "daniel")
        base = scoped_cloud_app_id("baseball", ws)
    except ImportError:
        base = "baseball"
    return f"{base}_library_manifest"


def _manifest_revision(session: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    return max((_content_revision(r) for r in rows), default=0) + len(rows)


def build_library_manifest(session: dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    """Build or return cached compact library index from local archives."""
    from draft_archive_state import DRAFT_ARCHIVE_KEY

    raw = session.get(DRAFT_ARCHIVE_KEY)
    entries = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    # Backfill content_updated_at without rewriting clocks to "now".
    for e in entries:
        if not str(e.get("content_updated_at") or "").strip():
            e["content_updated_at"] = str(e.get("updated_at") or e.get("created_at") or "").strip()
        if not e.get("content_revision"):
            e["content_revision"] = 1 if e.get("content_updated_at") else 0

    manifest = [summarize_archive_entry(e) for e in entries if not e.get("is_deleted")]
    manifest.sort(key=lambda r: (r.get("display_name") or "", r.get("draft_id") or ""))
    fp = "|".join(f"{r.get('draft_id')}:{r.get('updated_revision')}" for r in manifest)
    if not force and session.get(MANIFEST_FP_KEY) == fp:
        cached = session.get(MANIFEST_SESSION_KEY)
        if isinstance(cached, list):
            return copy.deepcopy(cached)
    session[MANIFEST_SESSION_KEY] = manifest
    session[MANIFEST_FP_KEY] = fp
    session["_library_manifest_revision"] = _manifest_revision(session, manifest)
    return copy.deepcopy(manifest)


def load_manifest_revision_meta(session: dict[str, Any]) -> dict[str, Any]:
    """Compact library-manifest revision header — no full row payload."""
    empty = {"revision": 0, "updated_at": ""}
    app = _manifest_settings_app(session)
    try:
        if _TEST_CLOUD_STORE is not None:
            envelope = _TEST_CLOUD_STORE.get(app) or {}
        else:
            from suite_account import load_settings

            envelope = load_settings(app) or {}
        header = envelope.get(MANIFEST_REV_DOC_KEY) if isinstance(envelope, dict) else None
        if isinstance(header, dict) and header:
            return {
                "revision": int(header.get("revision") or 0),
                "updated_at": str(header.get("updated_at") or ""),
                "source": "revision_header",
            }
        doc = envelope.get(MANIFEST_DOC_KEY) if isinstance(envelope, dict) else None
        if isinstance(doc, dict):
            return {
                "revision": int(doc.get("revision") or 0),
                "updated_at": str(doc.get("updated_at") or ""),
                "source": "manifest_fallback",
            }
        return empty
    except Exception:
        return empty


def sync_library_manifest_from_cloud(session: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Merge compact remote manifest content clocks into local archive summaries."""
    trace: dict[str, Any] = {"applied": False, "rows": 0}
    app = _manifest_settings_app(session)
    try:
        meta = load_manifest_revision_meta(session)
        remote_rev = int(meta.get("revision") or 0)
        local_rev = int(session.get("_library_manifest_applied_rev") or 0)
        if not force and remote_rev and remote_rev == local_rev and session.get(MANIFEST_FP_KEY):
            trace["skipped"] = "header_unchanged"
            session[LAST_MANIFEST_SYNC_KEY] = trace
            return trace

        if _TEST_CLOUD_STORE is not None:
            envelope = _TEST_CLOUD_STORE.get(app) or {}
        else:
            from suite_account import load_settings

            envelope = load_settings(app) or {}
        doc = envelope.get(MANIFEST_DOC_KEY) if isinstance(envelope, dict) else None
        if not isinstance(doc, dict):
            repair_polluted_identical_content_clocks(session)
            build_library_manifest(session, force=True)
            trace["skipped"] = "empty"
            session[LAST_MANIFEST_SYNC_KEY] = trace
            return trace
        remote_rows = doc.get("rows") if isinstance(doc.get("rows"), list) else []
        remote_by_id = {
            str(r.get("draft_id") or "").strip(): r
            for r in remote_rows
            if isinstance(r, dict) and str(r.get("draft_id") or "").strip()
        }
        from draft_archive_state import DRAFT_ARCHIVE_KEY

        local = session.get(DRAFT_ARCHIVE_KEY)
        if not isinstance(local, list):
            return trace
        changed = 0
        for i, entry in enumerate(local):
            if not isinstance(entry, dict):
                continue
            did = str(entry.get("draft_id") or "").strip()
            remote = remote_by_id.get(did)
            if not remote:
                continue
            remote_rev_row = _content_revision(remote)
            local_rev_row = _content_revision(entry)
            remote_at = _content_updated_at(remote)
            local_at = _content_updated_at(entry)
            # Prefer higher content_revision; ties break on content_updated_at string.
            take_remote = remote_rev_row > local_rev_row or (
                remote_rev_row == local_rev_row and remote_at and remote_at != local_at and remote_at > local_at
            )
            if take_remote and remote_at:
                patched = dict(entry)
                patched["content_updated_at"] = remote_at
                patched["content_revision"] = remote_rev_row or local_rev_row or 1
                remote_name = str(remote.get("display_name") or remote.get("draft_name") or "").strip()
                if remote_name:
                    patched["draft_name"] = remote_name
                # Never invent updated_at from hydration clock.
                if not patched.get("updated_at"):
                    patched["updated_at"] = remote_at
                local[i] = patched
                changed += 1
            elif remote_rev_row == local_rev_row:
                # Same content revision — still converge display_name after rename sync.
                remote_name = str(remote.get("display_name") or remote.get("draft_name") or "").strip()
                local_name = str(entry.get("draft_name") or "").strip()
                if remote_name and remote_name != local_name:
                    patched = dict(entry)
                    patched["draft_name"] = remote_name
                    local[i] = patched
                    changed += 1
        if changed:
            session[DRAFT_ARCHIVE_KEY] = local
            session.pop(MANIFEST_FP_KEY, None)
            build_library_manifest(session, force=True)
            trace["applied"] = True
            trace["rows"] = changed
        else:
            repair_polluted_identical_content_clocks(session)
            build_library_manifest(session, force=True)
        session["_library_manifest_applied_rev"] = int(doc.get("revision") or remote_rev or 0)
        session[LAST_MANIFEST_SYNC_KEY] = trace
        return trace
    except Exception as exc:
        trace["error"] = type(exc).__name__
        session[LAST_MANIFEST_SYNC_KEY] = trace
        return trace


def repair_polluted_identical_content_clocks(session: dict[str, Any]) -> int:
    """
    When hydration stamped the same Updated time onto every card, fall back to created_at.

    Does not invent wall-clock 'now'. Only runs when content clocks are identical across
    multiple drafts while created_at values differ.
    """
    from draft_archive_state import DRAFT_ARCHIVE_KEY

    local = session.get(DRAFT_ARCHIVE_KEY)
    if not isinstance(local, list) or len(local) < 2:
        return 0
    stamps = [
        _content_updated_at(e)
        for e in local
        if isinstance(e, dict) and not e.get("is_deleted")
    ]
    created = [
        str(e.get("created_at") or "").strip()
        for e in local
        if isinstance(e, dict) and not e.get("is_deleted")
    ]
    if len(stamps) < 2:
        return 0
    if len(set(stamps)) != 1 or not stamps[0]:
        return 0
    if len(set(c for c in created if c)) <= 1:
        return 0
    # Identical display stamps with distinct created_at → treat clocks as polluted.
    repaired = 0
    for i, entry in enumerate(local):
        if not isinstance(entry, dict) or entry.get("is_deleted"):
            continue
        created_at = str(entry.get("created_at") or "").strip()
        if not created_at or created_at == stamps[0]:
            continue
        # Skip if an explicit content_revision > 1 suggests a real later content edit.
        try:
            rev = int(entry.get("content_revision") or 0)
        except (TypeError, ValueError):
            rev = 0
        if rev > 1:
            continue
        patched = dict(entry)
        patched["content_updated_at"] = created_at
        patched["content_revision"] = 1
        patched["last_content_clock_repair"] = "identical_hydration_stamp"
        local[i] = patched
        repaired += 1
    if repaired:
        session[DRAFT_ARCHIVE_KEY] = local
        session.pop(MANIFEST_FP_KEY, None)
    return repaired


def collect_library_content_clock_diagnostics(
    session: dict[str, Any],
    *,
    draft_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Per-draft content-clock report for Developer Mode."""
    from draft_archive_state import get_draft_archive

    ids = draft_ids or ["3ce50b4f2e8b", "c6810611c73e"]
    rows: dict[str, Any] = {}
    for did in ids:
        entry = get_draft_archive(session, did)
        if not isinstance(entry, dict):
            rows[did] = {"missing": True}
            continue
        rows[did] = {
            "draft_id": did,
            "league_context_id": str(entry.get("league_context_id") or ""),
            "canonical_league_id": str(entry.get("league_id") or entry.get("canonical_league_id") or ""),
            "created_at": str(entry.get("created_at") or ""),
            "saved_at": str(entry.get("saved_at") or ""),
            "modified_at": str(entry.get("modified_at") or ""),
            "updated_at": str(entry.get("updated_at") or ""),
            "content_updated_at": _content_updated_at(entry),
            "content_revision": _content_revision(entry),
            "last_local_hydration_at": str(entry.get("last_local_hydration_at") or ""),
            "last_cloud_sync_at": str(entry.get("last_cloud_sync_at") or ""),
            "display_updated": _content_updated_at(entry),
            "last_content_clock_repair": str(entry.get("last_content_clock_repair") or ""),
        }
    manifest = session.get(MANIFEST_SESSION_KEY)
    return {
        "manifest_revision": int(session.get("_library_manifest_revision") or 0),
        "manifest_applied_rev": int(session.get("_library_manifest_applied_rev") or 0),
        "last_manifest_sync": session.get(LAST_MANIFEST_SYNC_KEY) or {},
        "rows": rows,
        "manifest_row_count": len(manifest) if isinstance(manifest, list) else 0,
    }


def publish_library_manifest_to_cloud(session: dict[str, Any]) -> dict[str, Any]:
    """Write compact manifest for cross-device content clock convergence."""
    rows = build_library_manifest(session, force=True)
    rev = int(session.get("_library_manifest_revision") or len(rows))
    now = _utc_now_iso()
    doc = {
        "schema_version": 1,
        "updated_at": now,
        "revision": rev,
        "rows": rows,
    }
    app = _manifest_settings_app(session)
    header = {"revision": rev, "updated_at": now}
    try:
        if _TEST_CLOUD_STORE is not None:
            _TEST_CLOUD_STORE[app] = {MANIFEST_DOC_KEY: doc, MANIFEST_REV_DOC_KEY: header}
            session["_library_manifest_applied_rev"] = rev
            return {"written": True, "revision": rev, "rows": len(rows)}
        from suite_account import save_settings

        save_settings(app, {MANIFEST_DOC_KEY: doc, MANIFEST_REV_DOC_KEY: header})
        session["_library_manifest_applied_rev"] = rev
        return {"written": True, "revision": rev, "rows": len(rows)}
    except Exception as exc:
        return {"written": False, "error": type(exc).__name__}


def get_archive_detail(session: dict[str, Any], draft_id: str) -> dict[str, Any] | None:
    """Load one full archive record on demand."""
    from draft_archive_state import get_draft_archive

    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return None
    entry = get_draft_archive(session, draft_id)
    return copy.deepcopy(entry) if isinstance(entry, dict) else None
