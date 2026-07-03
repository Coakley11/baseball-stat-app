"""Command Center activity for Saved Draft Library — Continue cards with restore payloads."""

from __future__ import annotations

from typing import Any

from activity_time import utc_now_iso

_DEDUP_KEY = "_cc_saved_draft_activity_logged"


def _dedup_store(session: dict[str, Any] | None) -> dict[str, str]:
    if session is None:
        return {}
    raw = session.get(_DEDUP_KEY)
    if not isinstance(raw, dict):
        raw = {}
        session[_DEDUP_KEY] = raw
    return raw


def _already_logged(session: dict[str, Any] | None, key: str) -> bool:
    if not key or session is None:
        return False
    store = _dedup_store(session)
    if store.get(key):
        return True
    store[key] = utc_now_iso()
    return False


def _archive_resume_key(draft_id: str) -> str:
    return f"bb:saved_draft:{str(draft_id or '').strip()}"


def _archive_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(entry.get("draft_id") or "").strip()
    draft_type = str(entry.get("draft_type") or "simulator")
    return {
        "draft_id": draft_id,
        "draft_name": str(entry.get("draft_name") or "Saved Draft"),
        "team_name": str(entry.get("team_name") or ""),
        "draft_type": draft_type,
        "player_count": len(entry.get("players") or []),
        "fantasy_format": str(entry.get("fantasy_format") or ""),
        "cc_card_kind": "continue",
        "workstream": "baseball_draft",
        "saved_item_type": "saved_draft",
        "saved_item_key": _archive_resume_key(draft_id),
        "saved_item_title": str(entry.get("draft_name") or "Saved Draft"),
        "saved_item_payload": {
            "draft_id": draft_id,
            "draft_name": entry.get("draft_name"),
            "team_name": entry.get("team_name"),
            "draft_type": draft_type,
            "fantasy_format": entry.get("fantasy_format"),
            "updated_at": entry.get("updated_at"),
        },
    }


def log_saved_draft_archived(entry: dict[str, Any], *, session: dict[str, Any] | None = None) -> None:
    """Continue card: user saved a draft team to the library."""
    draft_id = str(entry.get("draft_id") or "").strip()
    if not draft_id:
        return
    if _already_logged(session, f"saved:{draft_id}:{entry.get('updated_at')}"):
        return
    name = str(entry.get("draft_name") or "Saved Draft")
    team = str(entry.get("team_name") or "")
    try:
        from baseball_activity import log_saved_draft_team_saved

        log_saved_draft_team_saved(
            draft_id=draft_id,
            draft_name=name,
            team_name=team,
            draft_type=str(entry.get("draft_type") or "simulator"),
            player_count=len(entry.get("players") or []),
            metrics_extra=_archive_metrics(entry),
        )
    except ImportError:
        pass


def log_saved_draft_activated(
    entry: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    target_page: str = "Fantasy Standings Tracker",
) -> None:
    """Continue card: loaded/activated a saved team for analysis."""
    draft_id = str(entry.get("draft_id") or "").strip()
    if not draft_id:
        return
    dedup = f"activated:{draft_id}:{target_page}"
    if _already_logged(session, dedup):
        return
    name = str(entry.get("draft_name") or "Saved Draft")
    try:
        from baseball_activity import log_saved_draft_team_loaded

        log_saved_draft_team_loaded(
            draft_id=draft_id,
            draft_name=name,
            team_name=str(entry.get("team_name") or ""),
            target_page=target_page,
            metrics_extra=_archive_metrics(entry),
        )
    except ImportError:
        pass
