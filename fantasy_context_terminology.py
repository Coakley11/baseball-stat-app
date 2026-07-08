"""Central Draft vs League labeling for saved/active fantasy contexts."""

from __future__ import annotations

from typing import Any

from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE, DRAFT_TYPE_SIMULATOR
from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    SOURCE_DRAFT_SIMULATOR,
    SOURCE_IMPORTED_DRAFT,
)

TERM_KIND_DRAFT = "draft"
TERM_KIND_LEAGUE = "league"

BADGE_MOCK_DRAFT = "Mock Draft"
BADGE_SIMULATOR_DRAFT = "Simulator Draft"
BADGE_UPLOADED_LEAGUE = "Uploaded League"
BADGE_SHARED_LEAGUE = "Shared League"
BADGE_LIVE_DRAFT = "Live Draft"
BADGE_ACTIVE_DRAFT = "Active Draft"
BADGE_ACTIVE_LEAGUE = "Active League"


def _metadata(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    meta = context.get("metadata")
    return dict(meta) if isinstance(meta, dict) else {}


def _archive_draft_type(archive_entry: dict[str, Any] | None) -> str:
    if not isinstance(archive_entry, dict):
        return ""
    return str(archive_entry.get("draft_type") or "").strip()


def _has_team_claims(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    try:
        from fantasy_league_team_ownership import claimed_team_count, distinct_account_owner_count

        return claimed_team_count(context) >= 1 or distinct_account_owner_count(context) >= 1
    except ImportError:
        ownership = context.get("team_ownership") or {}
        if not isinstance(ownership, dict):
            return False
        return any(
            str(record.get("user_id") or "").strip()
            for record in ownership.values()
            if isinstance(record, dict)
        )


def _is_shared_league(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    try:
        from fantasy_league_team_ownership import claimed_team_count, distinct_account_owner_count

        return claimed_team_count(context) >= 2 or distinct_account_owner_count(context) >= 2
    except ImportError:
        ownership = context.get("team_ownership") or {}
        if not isinstance(ownership, dict):
            return False
        user_ids = {
            str(record.get("user_id") or "").strip()
            for record in ownership.values()
            if isinstance(record, dict) and str(record.get("user_id") or "").strip()
        }
        return len(user_ids) >= 2


def classify_fantasy_context(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return kind (draft|league), noun (Draft|League), and saved-context badge label."""
    archive_type = _archive_draft_type(archive_entry)
    context_type = str((context or {}).get("context_type") or "").strip()
    source = str(_metadata(context).get("source") or "").strip()

    if context_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION or (
        not context_type and archive_type == DRAFT_TYPE_SIMULATOR
    ):
        if archive_type == DRAFT_TYPE_SIMULATOR or source == SOURCE_DRAFT_SIMULATOR:
            badge = BADGE_SIMULATOR_DRAFT
        else:
            badge = BADGE_MOCK_DRAFT
        return {"kind": TERM_KIND_DRAFT, "noun": "Draft", "saved_badge": badge}

    if context_type == CONTEXT_TYPE_REAL_LEAGUE or archive_type == DRAFT_TYPE_IMPORTED:
        if source == SOURCE_IMPORTED_DRAFT or archive_type == DRAFT_TYPE_IMPORTED:
            badge = BADGE_SHARED_LEAGUE if _is_shared_league(context) else BADGE_UPLOADED_LEAGUE
        else:
            badge = BADGE_SHARED_LEAGUE if _is_shared_league(context) else BADGE_UPLOADED_LEAGUE
        return {"kind": TERM_KIND_LEAGUE, "noun": "League", "saved_badge": badge}

    if context_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT or archive_type == DRAFT_TYPE_LIVE:
        if _has_team_claims(context):
            return {
                "kind": TERM_KIND_LEAGUE,
                "noun": "League",
                "saved_badge": BADGE_SHARED_LEAGUE,
            }
        return {"kind": TERM_KIND_DRAFT, "noun": "Draft", "saved_badge": BADGE_LIVE_DRAFT}

    if archive_type == DRAFT_TYPE_IMPORTED:
        return {"kind": TERM_KIND_LEAGUE, "noun": "League", "saved_badge": BADGE_UPLOADED_LEAGUE}

    return {"kind": TERM_KIND_DRAFT, "noun": "Draft", "saved_badge": BADGE_MOCK_DRAFT}


def is_league_context(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> bool:
    return classify_fantasy_context(context, archive_entry)["kind"] == TERM_KIND_LEAGUE


def saved_context_type_badge(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    return classify_fantasy_context(context, archive_entry)["saved_badge"]


def active_context_label(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    noun = classify_fantasy_context(context, archive_entry)["noun"]
    return f"Active {noun}"


def active_context_short_label(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    if is_league_context(context, archive_entry):
        return BADGE_ACTIVE_LEAGUE
    return BADGE_ACTIVE_DRAFT


def saved_context_badges(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
    *,
    is_active: bool = False,
) -> list[str]:
    """Ordered badge labels for Saved Draft Library cards."""
    badges = [saved_context_type_badge(context, archive_entry)]
    if is_active:
        badges.append(active_context_short_label(context, archive_entry))
    return [badge for badge in badges if badge]


def league_context_type_badge(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    """Backward-compatible alias used across fantasy management pages."""
    return saved_context_type_badge(context, archive_entry)


def no_active_context_message() -> str:
    return (
        "**No Active League selected.**\n\n"
        "Go to **Draft Room Simulator** or **Saved Draft Library** to create/import a draft "
        "and activate a league."
    )
