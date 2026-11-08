"""What to do when the account refuses a Simulator board save because the cloud moved on.

The cloud guard (workspace_cloud_guard) refuses a write whose session has not seen the current
cloud revision. That protects newer work, but on its own it is a dead end: the session never
learns the new revision, so every retry fails the same way ("try again in a moment" never
helps). Reconciling decides, from what this session last verified and what the account holds
now, between exactly two outcomes — never by comparing pick counts:

* ``rebased``  — the account's board is unchanged since this session last verified it (or is
  identical to this page's), so only other data or the revision moved. This page's board is
  applied onto the *fresh* account copy (everything else in it is kept) and written with the
  usual compare-and-set on the fresh revision, so a second concurrent writer is still refused.
* ``conflict`` — the account's board changed elsewhere (another device, a reset). Nothing is
  written, this page's picks stay exactly as they are, and the user chooses explicitly: load
  the saved board, or keep this page's board and replace the saved one.
"""

from __future__ import annotations

import action_icons as _icons

import copy
from typing import Any

CONFLICT_KEY = "_draft_room_save_conflict"
STALE_ERRORS = ("stale_or_unhydrated_cloud_revision", "cloud_revision_conflict", "cloud_newer_than_loaded_session")


def is_stale_error(error: Any) -> bool:
    text = str(error or "")
    return any(token in text for token in STALE_ERRORS)


def _board_of(state: dict[str, Any] | None):
    from draft_room_state import _draft_room_from_blob, table_from_persist_dict

    blob = _draft_room_from_blob(state) if isinstance(state, dict) else None
    return table_from_persist_dict(blob) if isinstance(blob, dict) else None


def reconcile_board_save(session: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Return ``{"status": "rebased", "state": ...}`` or ``{"status": "conflict"|"unreadable", ...}``."""
    from draft_room_state import (
        BOARD_CLOUD_VERIFIED_FP_KEY,
        DRAFT_ROOM_TABLE_KEY,
        coerce_board_table,
        table_pick_count,
        table_picks_fingerprint,
    )
    from suite_cloud_state import CLOUD_READ_NOT_FOUND, CLOUD_READ_OK, load_cloud_full_session_status
    from workspace_cloud_guard import _copy_board, note_cloud_revision_seen

    fresh = load_cloud_full_session_status("baseball", force=True)
    if fresh.status not in (CLOUD_READ_OK, CLOUD_READ_NOT_FOUND):
        return {"status": "unreadable", "error": fresh.error or fresh.status}
    cloud_table = _board_of(fresh.state)
    cloud_picks = table_pick_count(cloud_table) if cloud_table is not None else 0
    cloud_fp = table_picks_fingerprint(cloud_table) if cloud_table is not None else ""
    local = coerce_board_table(session.get(DRAFT_ROOM_TABLE_KEY))
    local_fp = table_picks_fingerprint(local)
    verified = str(session.get(BOARD_CLOUD_VERIFIED_FP_KEY) or "")

    unchanged_since_verified = bool(verified) and cloud_fp == verified
    never_verified_and_empty = not verified and cloud_picks == 0
    if cloud_fp == local_fp or unchanged_since_verified or never_verified_and_empty:
        rebased = copy.deepcopy(fresh.state) if fresh.state else {}
        _copy_board(state, rebased)
        note_cloud_revision_seen(
            session, fresh.updated_at, confirmed_empty=fresh.status == CLOUD_READ_NOT_FOUND
        )
        session.pop(CONFLICT_KEY, None)
        return {"status": "rebased", "state": rebased, "revision": fresh.updated_at}

    conflict = {
        "status": "conflict",
        "cloud_picks": cloud_picks,
        "local_picks": table_pick_count(local),
        "cloud_revision": fresh.updated_at,
    }
    session[CONFLICT_KEY] = dict(conflict)
    return conflict


def adopt_cloud_board(session: dict[str, Any]) -> bool:
    """Replace this page's board with the account's (the user chose to). Returns True when applied."""
    from draft_room_state import (
        apply_restored_board_to_session,
        clear_draft_room_local_edit,
        mark_board_cloud_verified,
    )
    from suite_cloud_state import CLOUD_READ_NOT_FOUND, CLOUD_READ_OK, load_cloud_full_session_status
    from workspace_cloud_guard import note_cloud_revision_seen

    fresh = load_cloud_full_session_status("baseball", force=True)
    if fresh.status != CLOUD_READ_OK:
        return False
    table = _board_of(fresh.state)
    if table is None:
        return False
    from draft_room_state import _draft_room_from_blob

    apply_restored_board_to_session(session, table, blob=copy.deepcopy(_draft_room_from_blob(fresh.state)), bump_widget=True)
    note_cloud_revision_seen(session, fresh.updated_at, confirmed_empty=fresh.status == CLOUD_READ_NOT_FOUND)
    clear_draft_room_local_edit(session)
    mark_board_cloud_verified(session)
    session.pop(CONFLICT_KEY, None)
    return True


def accept_replacing_cloud_board(session: dict[str, Any]) -> bool:
    """The user chose to keep this page's board over the saved one: acknowledge the account's
    current revision so the next manual save is allowed, then let the normal guards run."""
    from suite_cloud_state import CLOUD_READ_NOT_FOUND, CLOUD_READ_OK, load_cloud_full_session_status
    from workspace_cloud_guard import note_cloud_revision_seen

    fresh = load_cloud_full_session_status("baseball", force=True)
    if fresh.status not in (CLOUD_READ_OK, CLOUD_READ_NOT_FOUND):
        return False
    note_cloud_revision_seen(session, fresh.updated_at, confirmed_empty=fresh.status == CLOUD_READ_NOT_FOUND)
    session.pop(CONFLICT_KEY, None)
    return True


def render_board_conflict_controls(st: Any, session: dict[str, Any]) -> None:
    """Shown while a genuine board conflict is open: two explicit, acknowledged choices.

    Neither choice is taken for the user, and neither runs without its acknowledgement box.
    Widget keys end in ``_btn`` so page-state snapshots never restore an acknowledgement.
    """
    conflict = session.get(CONFLICT_KEY)
    if not isinstance(conflict, dict):
        return
    st.warning(
        f"The board saved in your account has **{conflict.get('cloud_picks', 0)}** pick(s) and this page has "
        f"**{conflict.get('local_picks', 0)}**, and they are different boards. Choose which one to keep. "
        "Nothing is changed until you do.",
        icon=_icons.WARNING,
    )
    load_col, keep_col = st.columns(2)
    with load_col:
        load_ok = st.checkbox("I understand this page's picks will be replaced", key="dr_conflict_load_ack_btn")
        if st.button("Load the saved board", key="dr_conflict_load_btn", disabled=not load_ok,
                     use_container_width=True, icon=_icons.OPEN):
            if adopt_cloud_board(session):
                st.rerun()
            st.error("The saved board could not be loaded right now. Your picks on this page are unchanged.")
    with keep_col:
        keep_ok = st.checkbox("I understand the saved board will be replaced", key="dr_conflict_keep_ack_btn")
        if st.button("Save this page's board instead", key="dr_conflict_keep_btn", disabled=not keep_ok,
                     use_container_width=True, icon=_icons.SAVE):
            if accept_replacing_cloud_board(session):
                session["_draft_room_manual_save_requested"] = True
                st.rerun()
            st.error("The saved board could not be reached right now. Nothing was changed.")


SAVE_FAILED_STALE = (
    "Your saved board was changed from another device or tab, so this save was held back to protect "
    "that newer version. Nothing was overwritten and your picks are still on this page."
)
SAVE_FAILED_SIGN_IN = "You are signed out, so the board could not be saved to your account. Sign in again; your picks are kept on this page."
SAVE_FAILED_UNREACHABLE = "Your account storage could not be reached, so the board was not saved. Your picks are kept on this page; try again in a moment."


def save_failure_message(error: Any, default: str) -> str:
    """The honest reason a manual board save did not reach the account (``default`` otherwise)."""
    text = str(error or "")
    if is_stale_error(text):
        return SAVE_FAILED_STALE
    if "auth_not_ready" in text or "sign in" in text.lower():
        return SAVE_FAILED_SIGN_IN
    if "could not be read" in text or "cloud_read_failed" in text:
        return SAVE_FAILED_UNREACHABLE
    return default
