"""Draft Control Center — role-based sections with clear semantics."""

from __future__ import annotations

from typing import Any, Callable


def _resolve_commissioner(session: dict[str, Any]) -> tuple[bool, Any]:
    doc = None
    try:
        from draft_room_shared_state import load_shared_room_document
        from shared_draft_permissions import is_canonical_commissioner

        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        doc = load_shared_room_document(session, code) if code else None
        if code:
            return bool(is_canonical_commissioner(session, doc)), doc
        return True, doc
    except ImportError:
        try:
            from draft_room_membership import is_room_host

            code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
            return (bool(is_room_host(session, doc)) if code else True), doc
        except ImportError:
            return (not bool(session.get("active_shared_draft_room_code"))), None


def render_live_draft_control_center(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    cfg: dict[str, Any],
    persist_room: Callable[[dict[str, Any], str], None],
    developer_mode: bool = False,
) -> dict[str, Any]:
    """Render the Control Center. Returns ``{is_commissioner, document}``."""
    status = str(room.get("status") or "")
    is_commissioner, doc = _resolve_commissioner(session)
    may_auto = False
    try:
        from shared_draft_permissions import participant_may_auto_pick

        may_auto = participant_may_auto_pick(session, room, document=doc)
    except ImportError:
        may_auto = bool(is_commissioner)

    st.markdown("### Draft Control Center")

    # ---- LIVE CONTROLS ----
    st.markdown("#### Live controls")
    st.caption("Temporary actions for the currently active room.")
    live1, live2, live3, live4 = st.columns(4)
    with live1:
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
        st.caption("Stops the timer for everyone.")
    with live2:
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
        st.caption("Continues a paused active draft.")
    with live3:
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
            ok, msg = live_draft_auto_pick(room, session)
            if ok:
                try:
                    from live_draft_ui_cache import (
                        invalidate_draft_assistant_scoring_cache,
                        invalidate_live_draft_ui_caches,
                    )

                    invalidate_live_draft_ui_caches(session)
                    invalidate_draft_assistant_scoring_cache(session)
                except ImportError:
                    session.pop("_live_draft_rec_cache", None)
                st.success(msg)
                try:
                    from live_draft_safe_mode import is_draft_truly_complete, request_live_draft_rerun

                    reason = "auto_pick_complete" if is_draft_truly_complete(room) else "auto_pick"
                    request_live_draft_rerun(st, session, reason, room=room)
                except ImportError:
                    st.rerun()
            else:
                st.warning(msg)
            persist_room(room, "auto_pick")
        st.caption("Your team on clock (guest) or any team (commissioner).")
    with live4:
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
            st.caption("Commissioner only.")
        else:
            st.caption("Reset Timer is commissioner-only.")

    # ---- SAVE AND RETURN LATER ----
    if is_commissioner:
        st.markdown("#### Save and return later")
        st.caption(
            "Park this live draft and return to it later. All picks, teams, queues, and progress "
            "are preserved. This is not the same as saving a historical copy to the Draft Library."
        )
        if st.button(
            "💾 Save & Continue Later",
            key="live_draft_save_continue_btn",
            help="Commissioner only: park this shared draft for everyone.",
            use_container_width=True,
        ):
            from live_draft_resumable_slot import save_and_continue_later

            result = save_and_continue_later(session, st=st, replace_existing=False)
            if result.get("needs_replace_confirm"):
                session["_live_draft_replace_resumable_confirm"] = True
                session["_live_draft_replace_resumable_message"] = result.get("message")
            elif result.get("ok"):
                st.rerun()
            else:
                st.error(str(result.get("message") or "Could not save draft for later."))

    # ---- DRAFT LIBRARY ----
    st.markdown("#### Draft Library")
    st.caption(
        "Save a historical copy of the current board for viewing and analysis. "
        "This does not pause, park, or end the live draft."
    )
    if st.button(
        "📁 Save to Draft Library",
        key="live_draft_save_library_btn",
        help="Historical copy only — does not affect the live room.",
        use_container_width=True,
    ):
        try:
            from fantasy_league_context import save_live_draft_league_context

            team = str(
                session.get("draft_room_participant_team")
                or (room.get("config") or {}).get("your_team")
                or (room.get("config") or {}).get("user_team")
                or ((room.get("teams") or [""])[0])
                or "My Team"
            ).strip()
            save_live_draft_league_context(session, room, my_team_name=team, save_only=True)
            st.success("Saved a historical copy to Draft Library.")
        except Exception as exc:
            st.warning(f"Could not save to Draft Library: {exc}")

    # ---- PERSONAL ROOM ACTION (guest) ----
    if not is_commissioner and session.get("active_shared_draft_room_code"):
        st.markdown("#### Personal room action")
        st.caption("Leave only your seat and release your team. The draft continues for others.")
        if st.button(
            "🚪 Leave This Room",
            key="live_draft_leave_this_room_btn",
            help="Removes only you — does not end the draft.",
            use_container_width=True,
        ):
            session["_live_draft_leave_confirm"] = True

    # ---- DANGER ZONE (commissioner) ----
    if is_commissioner:
        st.markdown("#### Danger zone")
        st.caption(
            "Permanently delete this live draft for every participant. All live progress will be "
            "removed and the room code will stop working. This cannot be undone."
        )
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
                help="Commissioner only: permanently destroy this room for every participant.",
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
            ):
                session["_live_draft_discard_confirm"] = True

    # Confirm / error dialogs
    if session.get("_live_draft_delete_error"):
        st.error(
            "End/Delete failed: "
            + str(session.pop("_live_draft_delete_error", "") or "unknown error")
            + " — the room was left active so you can retry."
        )

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

    if session.get("_live_draft_replace_resumable_confirm"):
        st.warning(
            str(
                session.get("_live_draft_replace_resumable_message")
                or "A resumable draft is already saved. Saving this draft will replace it."
            )
        )
        rc1, rc2 = st.columns(2)
        with rc1:
            if st.button(
                "Replace Saved Draft",
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
                    st.error(str(result.get("message") or "Could not replace saved draft."))
        with rc2:
            if st.button("Keep Existing Saved Draft", key="live_draft_replace_resumable_cancel_btn"):
                session.pop("_live_draft_replace_resumable_confirm", None)
                session.pop("_live_draft_replace_resumable_message", None)
                st.rerun()

    if session.get("_live_draft_discard_confirm"):
        st.error(
            "Permanently delete this draft for every participant?\n\n"
            "All picks, teams, queues, chat, and progress will be removed. "
            "This cannot be undone.\n\n"
            "Guests who only need to exit should use **Leave This Room** instead.\n\n"
            "Choose **Save & Continue Later** if you want to finish another time."
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
                    "🗑 Confirm End/Delete for Everyone",
                    key="live_draft_discard_confirm_btn",
                    type="primary",
                    on_click=on_confirm_end_delete_for_everyone,
                    use_container_width=True,
                )
            except ImportError:
                if st.button(
                    "🗑 Confirm End/Delete for Everyone",
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

    return {"is_commissioner": is_commissioner, "document": doc}
