"""Draft Room Simulator controls: Live Draft provenance, Continue / Edit as Mock Draft, change an
earlier pick, add a round, and Restore Previous Mock Draft.

UI only. Board changes go through ``simulator_board_edit`` / ``simulator_board_history`` and are
saved with the Simulator's normal persist path (``persist_fn``).
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

PersistFn = Callable[[str], None]


def board_display_frame(session: dict[str, Any], table: pd.DataFrame) -> pd.DataFrame:
    """Board columns for display, with a Source column telling Live Draft picks from hypothetical ones."""
    cols = [c for c in ("Round", "Pick", "Team", "Player") if c in table.columns]
    view = table[cols].copy() if cols else table.copy()
    try:
        from simulator_board_edit import pick_origin_labels

        labels = pick_origin_labels(session)
    except Exception:
        labels = {}
    if labels and "Pick" in view.columns:
        def _label(pick: Any) -> str:
            try:
                return labels.get(int(pick), "")
            except (TypeError, ValueError):
                return ""

        view["Source"] = view["Pick"].map(_label)
    return view


def _on_continue_as_mock() -> None:
    import streamlit as st

    from simulator_board_edit import fork_live_board_as_mock

    res = fork_live_board_as_mock(st.session_state, reason="continue_as_mock_button")
    if res.get("ok"):
        st.session_state["_sim_board_tools_flash"] = (
            "success",
            "You are now editing a separate hypothetical mock draft. The original Live Draft is unchanged.",
        )
        # Saved by the page on this rerun (the callback has no persist handle).
        st.session_state["_sim_board_tools_pending_persist"] = "fork_live_draft_as_mock"


def render_provenance_banner(st: Any, session: dict[str, Any]) -> None:
    try:
        from simulator_board_edit import board_provenance
        from draft_room_state import is_live_draft_runtime_active
    except ImportError:
        return
    prov = board_provenance(session)
    if is_live_draft_runtime_active(session):
        if prov["kind"] != "other":
            st.caption("Your Live Draft is in progress: this board mirrors its picks as they are made.")
        return
    if prov["kind"] == "live_draft":
        st.info(
            f"These are the actual picks from your completed **Live Draft** ({prov['original_pick_count']} picks). "
            "The Live Draft itself is a finished record: nothing here changes it, its room, or other "
            "managers' records."
        )
        st.button(
            "Continue / Edit as Mock Draft",
            key="sim_continue_as_mock_btn",
            icon="🧾",
            type="primary",
            help="Keep drafting, add rounds, undo or replace picks as a separate hypothetical mock draft.",
            on_click=_on_continue_as_mock,
        )
    elif prov["kind"] == "hypothetical":
        kept = prov["original_pick_count"] - len(prov["changed_picks"]) - len(prov["removed_picks"])
        parts = [f"{max(kept, 0)} original Live Draft picks kept"]
        if prov["changed_picks"]:
            parts.append(f"{len(prov['changed_picks'])} changed")
        if prov["removed_picks"]:
            parts.append(f"{len(prov['removed_picks'])} undone")
        if prov["added_picks"]:
            parts.append(f"{len(prov['added_picks'])} added")
        st.warning(
            "🧾 **Hypothetical mock draft** based on your Live Draft — "
            + ", ".join(parts)
            + ". The original Live Draft is unchanged. Use **Save Draft** to keep this version as its own mock."
        )


def _flash(st: Any, session: dict[str, Any]) -> None:
    msg = session.pop("_sim_board_tools_flash", None)
    if isinstance(msg, tuple) and len(msg) == 2:
        kind, text = msg
        (st.success if kind == "success" else st.warning)(text)


def render_full_board_extend(st: Any, session: dict[str, Any], persist_fn: PersistFn) -> None:
    """Shown when no open picks remain: add a round to keep drafting."""
    from draft_room_state import is_live_draft_runtime_active

    if is_live_draft_runtime_active(session):
        st.info("Board is full.")
        return
    st.info("Board is full. Add a round to keep drafting (a hypothetical continuation), or reset for a new mock.")
    if st.button("Add a round", key="sim_add_round_full_btn", icon="➕"):
        from simulator_board_edit import add_board_rounds

        res = add_board_rounds(session, 1)
        session["_sim_board_tools_flash"] = ("success" if res.get("ok") else "warning", res.get("message", ""))
        if res.get("ok"):
            persist_fn("extend_board_round")
        st.rerun()


def render_edit_tools(
    st: Any,
    session: dict[str, Any],
    table: pd.DataFrame,
    *,
    pool_names: list[str],
    search_fn: Callable[[str, list[str]], list[str]] | None,
    persist_fn: PersistFn,
) -> None:
    """Change an earlier pick and add rounds — the hypothetical-draft tools."""
    from draft_room_state import is_live_draft_runtime_active

    _flash(st, session)
    if is_live_draft_runtime_active(session) or table.empty or "Player" not in table.columns:
        return
    filled = table[table["Player"].astype(str).str.strip().ne("")]
    with st.expander("Change an earlier pick or add rounds", expanded=False, icon="✏️"):
        try:
            from simulator_board_edit import board_provenance

            if board_provenance(session)["kind"] == "live_draft":
                st.caption(
                    "Changing a pick turns this board into a separate hypothetical mock draft. "
                    "The original Live Draft is not changed."
                )
        except Exception:
            pass
        if not filled.empty and "Pick" in filled.columns:
            labels = [f"Pick {int(r.Pick)} · {r.Team} · {r.Player}" for r in filled.itertuples() if pd.notna(r.Pick)]
            picks = [int(r.Pick) for r in filled.itertuples() if pd.notna(r.Pick)]
            choice = st.selectbox("Pick to change", labels, key="sim_replace_pick_choice")
            query = st.text_input("Search replacement player", key="sim_replace_pick_search",
                                  placeholder="Type 2+ letters, e.g. Soto")
            q = str(query or "").strip()
            matches: list[str] = []
            if len(q) >= 2:
                matches = search_fn(q, pool_names) if callable(search_fn) else [
                    n for n in pool_names if q.lower() in n.lower()
                ][:30]
            replacement = st.selectbox(
                "Replacement player",
                matches or ["— type 2+ letters in search above —"],
                key="sim_replace_pick_player",
                disabled=not matches,
            )
            col_a, col_b = st.columns(2)
            pick_no = picks[labels.index(choice)] if choice in labels else None
            with col_a:
                do_replace = st.button("Replace pick", key="sim_replace_pick_btn", type="primary",
                                       disabled=not matches or pick_no is None)
            with col_b:
                do_clear = st.button("Clear this pick", key="sim_clear_pick_btn", disabled=pick_no is None,
                                     help="Makes the pick open again (later picks stay).")
            if (do_replace or do_clear) and pick_no is not None:
                from simulator_board_edit import replace_board_pick

                res = replace_board_pick(session, pick_number=pick_no, player_name="" if do_clear else replacement)
                session["_sim_board_tools_flash"] = ("success" if res.get("ok") else "warning", res.get("message", ""))
                if res.get("ok"):
                    persist_fn("replace_board_pick")
                st.rerun()
        if st.button("Add a round", key="sim_add_round_btn", icon="➕",
                     help="Adds one open round for the same teams, continuing the pick order."):
            from simulator_board_edit import add_board_rounds

            res = add_board_rounds(session, 1)
            session["_sim_board_tools_flash"] = ("success" if res.get("ok") else "warning", res.get("message", ""))
            if res.get("ok"):
                persist_fn("extend_board_round")
            st.rerun()


def render_restore_previous(st: Any, session: dict[str, Any], persist_fn: PersistFn) -> None:
    """↩️ Restore Previous Mock Draft — with confirmation; the current board is kept in turn."""
    try:
        from simulator_board_history import (
            describe_entry,
            list_previous_boards,
            restore_blocked_reason,
            restore_previous_board,
        )
    except ImportError:
        return
    entries = list_previous_boards(session)
    flash = session.pop("_sim_restore_flash", None)
    if isinstance(flash, tuple) and len(flash) == 2:
        (st.success if flash[0] == "success" else st.warning)(flash[1])
    if not entries:
        return
    with st.expander("Restore Previous Mock Draft", expanded=False, icon="↩️"):
        st.caption(
            "Boards replaced on this Simulator (for example when a Live Draft took over the working "
            "board) are kept here for your account, across refresh, sign-in and devices."
        )
        labels = [describe_entry(e) for e in entries]
        idx = st.selectbox("Board to restore", list(range(len(entries))), format_func=lambda i: labels[i],
                           key="sim_restore_choice")
        entry = entries[int(idx or 0)]
        teams = ", ".join(entry.get("teams") or [])
        st.markdown(
            f"**{int(entry.get('pick_count') or 0)} picks** of {int(entry.get('slot_count') or 0)} · "
            f"teams: {teams or '—'} · kept {str(entry.get('saved_at') or '')[:16].replace('T', ' ')} UTC"
        )
        st.caption(
            "Restoring makes this board your current Simulator working board. Your current board is "
            "kept here so you can switch back. Completed Live Drafts and saved drafts are not changed."
        )
        blocked = restore_blocked_reason(session)
        if blocked:
            st.info("Available once your Live Draft finishes: while it runs, its picks are the working board.")
            return
        confirm = st.checkbox("Replace my current working board with this one", key="sim_restore_confirm")
        if st.button("Restore this board", key="sim_restore_btn", type="primary", disabled=not confirm, icon="↩️"):
            res = restore_previous_board(session, str(entry.get("entry_id") or ""))
            session["_sim_restore_flash"] = ("success" if res.get("ok") else "warning", res.get("message", ""))
            if res.get("ok"):
                persist_fn("restore_previous_board")
            st.rerun()
