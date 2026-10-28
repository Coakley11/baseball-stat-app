"""Refuse unhydrated or stale full-session writes that would erase saved work.

A cloud read that has not completed, and a session that has not observed the
current cloud revision, must not replace a verified account row. Unrelated page
saves may update their own fields, but they cannot shrink a verified simulator
board or drop other nonempty workspace data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CLOUD_REVISION_SEEN_KEY = "_suite_cloud_revision_seen"
CLOUD_CONFIRMED_EMPTY_KEY = "_suite_cloud_confirmed_empty"
EXPLICIT_RESET_KEY = "_draft_room_explicit_reset_intent"
VERIFIED_BOARD_SNAPSHOT_KEY = "draft_room_verified_snapshot"

BOARD_STATE_KEY = "draft_room_state"
BOARD_TABLE_KEY = "draft_room_table"
PAGE_FILTER_KEY = "page_filter_state"
BOARD_PAGE = "Draft Room Simulator"

PROTECTED_WORKSPACE_KEYS: tuple[str, ...] = (
    "draft_archive_teams",
    "fantasy_league_context_state",
    "active_draft_archive_id",
    "draft_queue",
    "draft_state",
    "watchlist_focus",
    "watchlist_favorites",
    "last_draft_board_snapshot",
    "fantasy_research_mode_selection",
    "_deleted_draft_archive_ids",
)

BOARD_MUTATION_REASONS = frozenset(
    {
        "undo_last_pick",
        "manual_save",
        "manual_save_button_click",
        "draft_room_pick",
        "simulator_add_player",
        "simulator_paste",
        "draft_edit",
    }
)

EXPLICIT_RESET_REASONS = frozenset(
    {
        "reset_simulator_board",
        "reset_canonical_board",
        "simulator_reset_only",
        "suite_reset",
        "reset_user_state",
        "user_reset",
    }
)

WORKFLOW_CLEAR_REASONS = frozenset(
    {
        "draft_archive_cleared",
        "draft_archive_deleted",
        "league_context_deleted",
        "suite_reset",
        "reset_user_state",
        "user_reset",
        "workflow_library_sanitized",
    }
)


@dataclass
class CloudWritePlan:
    allowed: bool
    state: dict[str, Any]
    reason: str = ""
    snapshot: dict[str, Any] | None = None
    expected_updated_at: str | None = None
    include_snapshot: bool = False


def session_state_writable(session: Any) -> bool:
    """True for a dict or a Streamlit SessionStateProxy."""
    return session is not None and hasattr(session, "__setitem__") and hasattr(session, "get")


def note_cloud_revision_seen(
    session: Any,
    updated_at: str | None,
    *,
    confirmed_empty: bool = False,
) -> None:
    if not session_state_writable(session):
        return
    if confirmed_empty:
        session[CLOUD_CONFIRMED_EMPTY_KEY] = True
        session[CLOUD_REVISION_SEEN_KEY] = str(updated_at or "")
        return
    session.pop(CLOUD_CONFIRMED_EMPTY_KEY, None)
    session[CLOUD_REVISION_SEEN_KEY] = str(updated_at or "")


def authorize_explicit_reset(session: Any, *, reason: str) -> None:
    if not session_state_writable(session):
        return
    current = session.get(EXPLICIT_RESET_KEY)
    reasons = []
    if isinstance(current, dict) and isinstance(current.get("reasons"), list):
        reasons = [str(item) for item in current.get("reasons") if str(item)]
    label = str(reason or "")
    if label and label not in reasons:
        reasons.append(label)
    session[EXPLICIT_RESET_KEY] = {
        "reasons": reasons,
        "revision": str(session.get(CLOUD_REVISION_SEEN_KEY) or ""),
        "confirmed_empty": bool(session.get(CLOUD_CONFIRMED_EMPTY_KEY)),
    }


def explicit_reset_ready(session: Any, reason: str) -> bool:
    if _reason_base(reason) not in EXPLICIT_RESET_REASONS or not session_state_writable(session):
        return False
    intent = session.get(EXPLICIT_RESET_KEY)
    if not isinstance(intent, dict):
        return False
    reasons = intent.get("reasons")
    if not isinstance(reasons, list) or _reason_base(reason) not in {str(item) for item in reasons}:
        return False
    return str(intent.get("revision") or "") == str(session.get(CLOUD_REVISION_SEEN_KEY) or "")


def consume_explicit_reset(session: Any, reason: str) -> bool:
    if not session_state_writable(session):
        return False
    intent = session.get(EXPLICIT_RESET_KEY)
    if not isinstance(intent, dict):
        return False
    reasons = intent.get("reasons")
    if not isinstance(reasons, list) or str(reason or "") not in {str(item) for item in reasons}:
        return False
    if str(intent.get("revision") or "") != str(session.get(CLOUD_REVISION_SEEN_KEY) or ""):
        return False
    session.pop(EXPLICIT_RESET_KEY, None)
    return True


def filled_pick_count(state: dict[str, Any] | None) -> int:
    if not isinstance(state, dict):
        return 0
    field = 0
    blob = state.get(BOARD_STATE_KEY)
    if isinstance(blob, dict):
        try:
            field = int(blob.get("pick_count") or 0)
        except (TypeError, ValueError):
            field = 0
    table = state.get(BOARD_TABLE_KEY)
    if isinstance(table, dict):
        try:
            field = max(field, int(table.get("pick_count") or 0))
        except (TypeError, ValueError):
            pass
    counted = 0
    try:
        from draft_room_state import draft_room_restore_stats

        counted = int(draft_room_restore_stats(copy.deepcopy(state)).get("pick_count") or 0)
    except Exception:
        counted = 0
    return max(field, counted)


def _reason_base(reason: str) -> str:
    raw = str(reason or "").strip()
    if raw.endswith("_retry"):
        return raw[:-6]
    return raw


def _nonempty(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, dict):
        return any(value.get(key) not in (None, "", [], {}) for key in value) or len(value) > 0
    if isinstance(value, list):
        return len(value) > 0
    return True


def _copy_board(source: dict[str, Any], dest: dict[str, Any]) -> None:
    for key in (BOARD_STATE_KEY, BOARD_TABLE_KEY):
        if key in source:
            dest[key] = copy.deepcopy(source.get(key))
    src_filters = source.get(PAGE_FILTER_KEY)
    if not isinstance(src_filters, dict) or BOARD_PAGE not in src_filters:
        return
    filters = dest.get(PAGE_FILTER_KEY)
    if not isinstance(filters, dict):
        filters = {}
        dest[PAGE_FILTER_KEY] = filters
    filters[BOARD_PAGE] = copy.deepcopy(src_filters.get(BOARD_PAGE))


def _preserve_workspace(outgoing: dict[str, Any], cloud: dict[str, Any], reason: str) -> None:
    if _reason_base(reason) in WORKFLOW_CLEAR_REASONS:
        return
    for key in PROTECTED_WORKSPACE_KEYS:
        cloud_val = cloud.get(key)
        if not _nonempty(cloud_val):
            continue
        if _nonempty(outgoing.get(key)):
            continue
        outgoing[key] = copy.deepcopy(cloud_val)


def _snapshot_from_state(state: dict[str, Any], revision: str) -> dict[str, Any]:
    blob = state.get(BOARD_STATE_KEY)
    if not isinstance(blob, dict):
        blob = state.get(BOARD_TABLE_KEY) if isinstance(state.get(BOARD_TABLE_KEY), dict) else {}
    return {
        "schema": 1,
        "pick_count": filled_pick_count(state),
        "draft_room_state": copy.deepcopy(blob),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_revision": revision,
        "cleared": False,
    }


def _previous_verified(prior: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(prior, dict):
        return None
    if not prior.get("cleared") and int(prior.get("pick_count") or 0) > 0:
        blob = prior.get("draft_room_state")
        if isinstance(blob, dict) and blob:
            return {
                "pick_count": int(prior.get("pick_count") or 0),
                "draft_room_state": copy.deepcopy(blob),
                "saved_at": prior.get("saved_at") or "",
                "source_revision": prior.get("source_revision") or "",
            }
    previous = prior.get("previous_verified")
    return copy.deepcopy(previous) if isinstance(previous, dict) and previous else None


def _cleared_snapshot(reason: str, revision: str, prior: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": 1,
        "pick_count": 0,
        "draft_room_state": {},
        "cleared": True,
        "cleared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": _reason_base(reason),
        "source_revision": revision,
        "previous_verified": _previous_verified(prior),
    }


def recover_board_from_verified_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy a verified board out of the snapshot. Does not write cloud or disk."""
    if not isinstance(snapshot, dict):
        return None
    source = snapshot.get("previous_verified") if snapshot.get("cleared") else snapshot
    if not isinstance(source, dict):
        return None
    blob = source.get("draft_room_state")
    if not isinstance(blob, dict) or not blob:
        return None
    recovered = {
        BOARD_STATE_KEY: copy.deepcopy(blob),
        BOARD_TABLE_KEY: copy.deepcopy(blob),
    }
    if filled_pick_count(recovered) <= 0:
        return None
    return recovered


def prepare_cloud_full_session_write(
    state: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None,
    read_status: str,
    cloud_state: dict[str, Any] | None,
    cloud_updated_at: str | None,
    save_reason: str = "",
    prior_snapshot: dict[str, Any] | None = None,
    allow_empty: bool = False,
) -> CloudWritePlan:
    """Decide whether this full-session write may replace the authenticated cloud row."""
    from suite_cloud_state import (
        CLOUD_READ_DISABLED,
        CLOUD_READ_ERROR,
        CLOUD_READ_NOT_FOUND,
        CLOUD_READ_NOT_READY,
        CLOUD_READ_OK,
        cloud_write_blocked_by_newer_data,
    )

    outgoing = copy.deepcopy(state) if isinstance(state, dict) else {}
    if not outgoing and not allow_empty:
        return CloudWritePlan(False, outgoing, "empty_state")
    if read_status == CLOUD_READ_NOT_READY:
        return CloudWritePlan(False, outgoing, "auth_not_ready")
    if read_status == CLOUD_READ_ERROR:
        return CloudWritePlan(False, outgoing, "cloud_read_failed")
    if read_status == CLOUD_READ_DISABLED:
        return CloudWritePlan(False, outgoing, "cloud_storage_disabled")

    cloud = cloud_state if isinstance(cloud_state, dict) else {}
    reason = _reason_base(save_reason)
    revision = str(cloud_updated_at or "")
    writable = session_state_writable(session)
    seen = str(session.get(CLOUD_REVISION_SEEN_KEY) or "") if writable else ""
    confirmed_empty = bool(writable and session.get(CLOUD_CONFIRMED_EMPTY_KEY))
    previously_observed = bool(seen) or confirmed_empty

    explicit_reset = explicit_reset_ready(session, reason)
    cloud_picks = filled_pick_count(cloud)
    incoming_picks = filled_pick_count(outgoing)
    if (
        read_status == CLOUD_READ_OK
        and previously_observed
        and cloud_write_blocked_by_newer_data(seen or None, revision or None)
    ):
        return CloudWritePlan(False, outgoing, "stale_or_unhydrated_cloud_revision", expected_updated_at=revision or None)
    if (
        read_status == CLOUD_READ_OK
        and not previously_observed
        and not explicit_reset
        and (reason not in BOARD_MUTATION_REASONS or incoming_picks < cloud_picks)
    ):
        return CloudWritePlan(False, outgoing, "stale_or_unhydrated_cloud_revision", expected_updated_at=revision or None)
    if explicit_reset:
        consume_explicit_reset(session, reason)

    if read_status == CLOUD_READ_OK and cloud_picks > incoming_picks and not explicit_reset:
        if reason not in BOARD_MUTATION_REASONS or not previously_observed:
            _copy_board(cloud, outgoing)
    if read_status == CLOUD_READ_OK:
        _preserve_workspace(outgoing, cloud, reason)

    if explicit_reset:
        retained = prior_snapshot
        if _previous_verified(retained) is None and cloud_picks > 0:
            retained = _snapshot_from_state(cloud, revision)
        snapshot = _cleared_snapshot(reason, revision, retained)
        include_snapshot = True
    elif filled_pick_count(outgoing) > 0:
        snapshot = _snapshot_from_state(outgoing, revision)
        include_snapshot = True
    elif isinstance(prior_snapshot, dict) and prior_snapshot:
        snapshot = copy.deepcopy(prior_snapshot)
        include_snapshot = True
    else:
        snapshot = None
        include_snapshot = False

    if read_status == CLOUD_READ_NOT_FOUND and not confirmed_empty and writable:
        note_cloud_revision_seen(session, revision or None, confirmed_empty=True)
    elif read_status == CLOUD_READ_OK and writable and not previously_observed:
        note_cloud_revision_seen(session, revision or None)
    return CloudWritePlan(
        True,
        outgoing,
        "",
        snapshot=snapshot,
        expected_updated_at=revision or None,
        include_snapshot=include_snapshot,
    )
