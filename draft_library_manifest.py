"""Compact Saved Draft Library manifest — summary index without full archive copies."""

from __future__ import annotations

import copy
from typing import Any

MANIFEST_SESSION_KEY = "_draft_library_manifest"
MANIFEST_FP_KEY = "_draft_library_manifest_fp"


def _archive_revision(entry: dict[str, Any]) -> str:
    return str(
        entry.get("updated_at")
        or entry.get("modified_at")
        or entry.get("saved_at")
        or entry.get("draft_id")
        or ""
    ).strip()


def summarize_archive_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """One card's worth of metadata — no roster payloads."""
    if not isinstance(entry, dict):
        return {}
    teams = entry.get("teams") or entry.get("team_names") or []
    team_count = len(teams) if isinstance(teams, (list, tuple)) else int(entry.get("team_count") or 0)
    players = entry.get("players") or entry.get("roster") or []
    player_count = len(players) if isinstance(players, (list, tuple)) else int(entry.get("player_count") or 0)
    draft_type = str(entry.get("draft_type") or entry.get("type") or "").strip()
    return {
        "draft_id": str(entry.get("draft_id") or "").strip(),
        "display_name": str(entry.get("draft_name") or entry.get("display_name") or "Saved Draft").strip(),
        "type": draft_type,
        "team_count": team_count,
        "player_count": player_count,
        "active_flag": bool(entry.get("is_active")),
        "context_id": str(entry.get("league_context_id") or "").strip(),
        "league_id": str(entry.get("league_id") or entry.get("canonical_league_id") or "").strip(),
        "updated_revision": _archive_revision(entry),
        "creation_origin": str(entry.get("creation_origin") or "").strip(),
    }


def _manifest_fingerprint(session: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    parts = [str(len(entries))]
    try:
        from account_fantasy_preferences import preference_revision_fingerprint

        parts.append(preference_revision_fingerprint(session))
    except ImportError:
        pass
    for row in entries[:64]:
        if not isinstance(row, dict):
            continue
        parts.append(str(row.get("draft_id") or ""))
        parts.append(_archive_revision(row))
    return "|".join(parts)


def build_library_manifest(session: dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    """Build or return cached compact library index."""
    from draft_archive_state import DRAFT_ARCHIVE_KEY

    raw = session.get(DRAFT_ARCHIVE_KEY)
    entries = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    fp = _manifest_fingerprint(session, entries)
    if not force and session.get(MANIFEST_FP_KEY) == fp:
        cached = session.get(MANIFEST_SESSION_KEY)
        if isinstance(cached, list):
            return copy.deepcopy(cached)

    manifest = [summarize_archive_entry(e) for e in entries]
    manifest.sort(key=lambda r: (r.get("display_name") or "", r.get("draft_id") or ""))
    session[MANIFEST_SESSION_KEY] = manifest
    session[MANIFEST_FP_KEY] = fp
    return copy.deepcopy(manifest)


def get_archive_detail(session: dict[str, Any], draft_id: str) -> dict[str, Any] | None:
    """Load one full archive record on demand."""
    from draft_archive_state import get_draft_archive

    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return None
    entry = get_draft_archive(session, draft_id)
    return copy.deepcopy(entry) if isinstance(entry, dict) else None
