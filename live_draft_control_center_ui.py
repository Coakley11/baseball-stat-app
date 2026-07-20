"""Draft Control Center — compact live controls + commissioner draft actions."""

from __future__ import annotations

from typing import Any, Callable


def _resolve_commissioner(session: dict[str, Any]) -> tuple[bool, Any]:
    """Shared: exact commissioner_participant_id. Solo: local owner. Never fail-open for Shared."""
    doc = None
    try:
        from draft_room_shared_state import load_shared_room_document
        from shared_draft_permissions import session_may_use_commissioner_draft_controls

        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        doc = load_shared_room_document(session, code) if code else None
        return bool(session_may_use_commissioner_draft_controls(session, document=doc)), doc
    except ImportError:
        try:
            from draft_room_membership import is_room_host

            code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
            if code:
                return bool(is_room_host(session, doc)), doc
            return True, doc
        except ImportError:
            return False, None


def render_live_draft_control_center(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    cfg: dict[str, Any],
    persist_room: Callable[[dict[str, Any], str], None],
    developer_mode: bool = False,
    show_heading: bool = True,
) -> dict[str, Any]:
    """Compact live controls only (Pause / Resume / Auto Pick / Reset Timer) in a 2×2 grid.

    Park/delete commissioner actions live near Team Rosters — not here.
    Historical library save is unavailable until the draft finishes naturally.
    """
    del developer_mode  # reserved for future live-control diagnostics
    status = str(room.get("status") or "")
    is_commissioner, doc = _resolve_commissioner(session)
    may_auto = False
    try:
        from shared_draft_permissions import participant_may_auto_pick

        may_auto = participant_may_auto_pick(session, room, document=doc)
    except ImportError:
        may_auto = bool(is_commissioner)

    if show_heading:
        st.markdown("### Draft Control Center")
        st.caption("Temporary actions for the currently active room.")

    top1, top2 = st.columns(2)
    with top1:
        if st.button(
            "⏸ Pause Draft",
            disabled=status != "in_progress",
            key="live_draft_pause",
            help="Temporarily stops the timer for everyone in this active room.",
            use_container_width=True,
        ):
            from live_draft_timer_logic import live_draft_pause_timer

            live_draft_pause_timer(room)
            persist_room(room, "pause_draft")
            try:
                from live_draft_chat_system import maybe_post_draft_system_message

                maybe_post_draft_system_message(
                    session, "draft_paused", pick_index=int(room.get("current_pick_index") or 0)
                )
            except ImportError:
                pass
            try:
                from live_draft_safe_mode import request_live_draft_rerun

                request_live_draft_rerun(st, session, "pause_draft", room=room)
            except ImportError:
                st.rerun()
    with top2:
        if st.button(
            "▶ Resume Draft",
            disabled=status != "paused",
            key="live_draft_resume",
            type="primary",
            help="Continues a normally paused active draft (not a saved-for-later park).",
            use_container_width=True,
        ):
            from live_draft_timer_logic import live_draft_resume_timer

            room["status"] = "in_progress"
            pause_left = int(room.get("paused_remaining_seconds") or cfg.get("timer_seconds", 60))
            live_draft_resume_timer(room, pause_left)
            persist_room(room, "resume_draft")
            try:
                from live_draft_chat_system import maybe_post_draft_system_message

                maybe_post_draft_system_message(
                    session, "draft_resumed", pick_index=int(room.get("current_pick_index") or 0)
                )
            except ImportError:
                pass
            try:
                from live_draft_safe_mode import request_live_draft_rerun

                request_live_draft_rerun(st, session, "resume_draft", room=room)
            except ImportError:
                st.rerun()

    bot1, bot2 = st.columns(2)
    with bot1:
        if st.button(
            "⚡ Auto Pick Now",
            disabled=(status not in ("in_progress", "paused")) or (not may_auto),
            key="live_draft_auto_now",
            help=(
                "Commissioner: auto-pick for the team on the clock. "
                "Guest: only when your claimed team is on the clock."
            ),
            use_container_width=True,
        ):
            from live_draft_autopick import live_draft_auto_pick

            if room.get("status") == "paused":
                room["status"] = "in_progress"
            # Capture expected pick so a double-click cannot advance twice.
            expected_pick = int(room.get("current_pick_index") or 0)
            ok, msg = live_draft_auto_pick(room, session)
            if ok:
                # Persist immediately so both clients see the new deadline before rerun.
                try:
                    persist_room(room, "auto_pick")
                except Exception:
                    pass
                try:
                    from live_draft_ui_cache import (
                        invalidate_draft_assistant_scoring_cache,
                        invalidate_live_draft_ui_caches,
                    )

                    invalidate_live_draft_ui_caches(session)
                    invalidate_draft_assistant_scoring_cache(session)
                except ImportError:
                    session.pop("_live_draft_rec_cache", None)
                session["_live_draft_auto_pick_now_diag"] = {
                    "ok": True,
                    "expected_pick": expected_pick,
                    "after_pick": int(room.get("current_pick_index") or 0),
                    "message": msg,
                }
                st.success(msg)
                try:
                    from live_draft_safe_mode import is_draft_truly_complete, request_live_draft_rerun

                    reason = "auto_pick_complete" if is_draft_truly_complete(room) else "auto_pick"
                    request_live_draft_rerun(st, session, reason, room=room)
                except ImportError:
                    st.rerun()
            else:
                st.warning(msg)
    with bot2:
        if is_commissioner:
            if st.button(
                "⏱ Reset Timer",
                disabled=status != "in_progress",
                key="live_draft_reset_timer",
                help="Commissioner only: restart the current pick timer.",
                use_container_width=True,
            ):
                from live_draft_timer_logic import live_draft_reset_timer

                live_draft_reset_timer(room)
                persist_room(room, "reset_timer")
        elif session.get("active_shared_draft_room_code"):
            if st.button(
                "🚪 Leave Room",
                key="live_draft_leave_this_room_btn",
                help="Leave only your seat. The draft continues for everyone else.",
                use_container_width=True,
            ):
                session["_live_draft_leave_confirm"] = True

    if session.get("_live_draft_leave_confirm"):
        st.warning(
            "Leave this draft room? You will give up your claimed team. "
            "The draft will remain available to the other participants."
        )
        lc1, lc2 = st.columns(2)
        with lc1:
            if st.button("Leave This Room", key="live_draft_leave_confirm_btn", type="primary"):
                from draft_room_context import leave_shared_draft_room

                session.pop("_live_draft_leave_confirm", None)
                leave_shared_draft_room(session)
                st.rerun()
        with lc2:
            if st.button("Stay in Room", key="live_draft_leave_cancel_btn"):
                session.pop("_live_draft_leave_confirm", None)
                st.rerun()

    return {"is_commissioner": is_commissioner, "document": doc}


def render_control_center_with_live_chat(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    cfg: dict[str, Any],
    persist_room: Callable[[dict[str, Any], str], None],
    developer_mode: bool = False,
) -> dict[str, Any]:
    """Control Center (left) + Live Chat (right), above the On-the-Clock timer card."""
    try:
        from live_draft_chat_ui import render_live_draft_chat_panel
    except ImportError:
        render_live_draft_chat_panel = None  # type: ignore[assignment]

    ctrl_col, chat_col = st.columns([1.0, 1.15])
    with ctrl_col:
        st.markdown('<div class="live-draft-action-row">', unsafe_allow_html=True)
        result = render_live_draft_control_center(
            st,
            session,
            room,
            cfg=cfg,
            persist_room=persist_room,
            developer_mode=developer_mode,
            show_heading=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
    with chat_col:
        if render_live_draft_chat_panel is not None:
            try:
                render_live_draft_chat_panel(st, session)
            except Exception as exc:
                st.caption(f"Draft chat unavailable: {type(exc).__name__}")
        else:
            st.caption("Draft chat unavailable.")
    return result


def render_commissioner_draft_actions(
    st: Any,
    session: dict[str, Any],
    *,
    developer_mode: bool = False,
) -> None:
    """Compact commissioner-only Save / End buttons (near Team Rosters)."""
    is_commissioner, _doc = _resolve_commissioner(session)
    if not is_commissioner:
        return

    st.markdown("**Draft Actions**")
    a1, a2 = st.columns(2)
    with a1:
        try:
            from live_draft_resumable_slot import (
                SAVING_FOR_LATER_UI_KEY,
                on_save_continue_later_click,
            )
        except ImportError:
            on_save_continue_later_click = None  # type: ignore[assignment]
            SAVING_FOR_LATER_UI_KEY = "_live_draft_saving_for_later_ui"
        saving = bool(session.get(SAVING_FOR_LATER_UI_KEY))
        if saving:
            st.info("Saving draft for later…")
        st.button(
            "💾 Save & Continue Later",
            key="live_draft_save_continue_btn",
            help="Pause and preserve this unfinished draft so the commissioner can continue it later.",
            use_container_width=True,
            disabled=saving,
            on_click=on_save_continue_later_click if on_save_continue_later_click else None,
        )
        st.caption("Pause unfinished draft for later.")
        if session.get("_live_draft_save_continue_error"):
            st.error(str(session.pop("_live_draft_save_continue_error", "") or "Save failed."))
    with a2:
        try:
            from live_draft_delete_authority import (
                note_delete_trace,
                on_show_end_delete_confirm,
                render_delete_trace_panel,
            )

            note_delete_trace(
                session,
                "button_rendered",
                widget_key="live_draft_discard_btn",
                is_commissioner=True,
            )
            st.button(
                "🗑 End/Delete Draft for Everyone",
                key="live_draft_discard_btn",
                type="primary",
                help="Permanently delete this draft and room for every participant. This cannot be undone.",
                use_container_width=True,
                on_click=on_show_end_delete_confirm,
            )
            if developer_mode:
                render_delete_trace_panel(st, session)
        except ImportError:
            if st.button(
                "🗑 End/Delete Draft for Everyone",
                key="live_draft_discard_btn",
                type="primary",
                use_container_width=True,
                help="Permanently delete this draft and room for every participant. This cannot be undone.",
            ):
                session["_live_draft_discard_confirm"] = True
        st.caption("Permanent — cannot be undone.")

    if session.get("_live_draft_delete_error"):
        st.error(
            "End/Delete failed: "
            + str(session.pop("_live_draft_delete_error", "") or "unknown error")
            + " — the room was left active so you can retry."
        )

    if session.get("_live_draft_replace_resumable_confirm"):
        st.warning(
            str(
                session.get("_live_draft_replace_resumable_message")
                or (
                    "An unfinished draft is already saved for later. "
                    "Saving this draft will discard that unfinished saved draft."
                )
            )
        )
        rc1, rc2 = st.columns(2)
        with rc1:
            if st.button(
                "Discard Previous Saved Draft",
                key="live_draft_replace_resumable_confirm_btn",
                type="primary",
            ):
                from live_draft_resumable_slot import save_and_continue_later

                session.pop("_live_draft_replace_resumable_confirm", None)
                session.pop("_live_draft_replace_resumable_message", None)
                result = save_and_continue_later(session, st=st, replace_existing=True)
                if result.get("ok"):
                    st.rerun()
                else:
                    st.error(str(result.get("message") or "Could not save draft for later."))
        with rc2:
            if st.button("Cancel", key="live_draft_replace_resumable_cancel_btn"):
                session.pop("_live_draft_replace_resumable_confirm", None)
                session.pop("_live_draft_replace_resumable_message", None)
                st.rerun()

    if session.get("_live_draft_discard_confirm"):
        st.error(
            "Permanently delete this draft for every participant?\n\n"
            "All picks, teams, queues, chat, and progress will be removed. "
            "This cannot be undone."
        )
        dc1, dc2 = st.columns(2)
        with dc1:
            try:
                from live_draft_delete_authority import (
                    note_delete_trace,
                    on_confirm_end_delete_for_everyone,
                )

                note_delete_trace(
                    session,
                    "confirmation_shown",
                    widget_key="live_draft_discard_confirm_btn",
                )
                st.button(
                    "🗑 Confirm End/Delete",
                    key="live_draft_discard_confirm_btn",
                    type="primary",
                    on_click=on_confirm_end_delete_for_everyone,
                    use_container_width=True,
                )
            except ImportError:
                if st.button(
                    "🗑 Confirm End/Delete",
                    key="live_draft_discard_confirm_btn",
                    type="primary",
                ):
                    from live_draft_termination import discard_live_draft_and_start_over

                    session.pop("_live_draft_discard_confirm", None)
                    discard_live_draft_and_start_over(session, st=st)
                    st.rerun()
        with dc2:
            if st.button("Keep Draft", key="live_draft_discard_cancel_btn"):
                session.pop("_live_draft_discard_confirm", None)
                st.rerun()


# Backward-compatible aliases for older imports / tests.
render_commissioner_actions_beside_chat = render_commissioner_draft_actions


def render_live_chat_with_commissioner_actions(
    st: Any,
    session: dict[str, Any],
    *,
    developer_mode: bool = False,
) -> None:
    """Deprecated layout helper — chat only (commissioner actions render near rosters)."""
    try:
        from live_draft_chat_ui import render_live_draft_chat_panel

        render_live_draft_chat_panel(st, session)
    except Exception as exc:
        st.caption(f"Draft chat unavailable: {type(exc).__name__}")
    del developer_mode
