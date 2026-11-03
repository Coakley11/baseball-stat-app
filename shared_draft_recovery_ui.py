"""Saved Draft Library panel: Recover a completed Shared Draft (shared_draft_recovery)."""

from __future__ import annotations

from typing import Any

ROOMS_KEY = "_shared_draft_recovery_rooms"
PREVIEW_KEY = "_shared_draft_recovery_preview"
RESULT_KEY = "_shared_draft_recovery_result"
FOCUS_KEY = "_saved_draft_library_focus_draft_id"


def _room_label(room: dict[str, Any]) -> str:
    when = str(room.get("updated_at") or "")[:10]
    team = room.get("team") or "team unknown"
    role = "commissioner" if room.get("role") == "commissioner" else "participant"
    saved = " · already in your Library" if room.get("in_library") else ""
    return f"{room.get('league_name')} — {team} ({role}) · {room.get('room_code')} · {when}{saved}"


def render_shared_draft_recovery_panel(st: Any, session: Any) -> None:
    from shared_draft_recovery import (
        list_recoverable_rooms,
        load_recovery_preview,
        recover_completed_shared_draft,
        signed_in_account_id,
    )

    with st.expander("♻️ Recover a completed Shared Draft", expanded=bool(session.get(PREVIEW_KEY))):
        st.caption(
            "If a Shared Draft finished but never reached your Library, add your copy from the "
            "completed room. The room itself is never changed, and other players' libraries aren't touched."
        )
        if not signed_in_account_id(session):
            st.info("Sign in to recover your Shared Drafts.")
            return
        if st.button("🔎 Find my completed Shared Drafts", key="sdr_find"):
            session[ROOMS_KEY] = list_recoverable_rooms(session)
            session.pop(PREVIEW_KEY, None)
            session.pop(RESULT_KEY, None)
        rooms = session.get(ROOMS_KEY)
        if rooms is None:
            return
        if not rooms:
            st.info("No completed Shared Drafts were found for your account.")
            return
        labels = {_room_label(r): r for r in rooms}
        choice = st.selectbox("Completed Shared Draft", list(labels), key="sdr_choice")
        if st.button("👁️ Preview", key="sdr_preview"):
            session[PREVIEW_KEY] = load_recovery_preview(session, labels[choice]["room_code"])
            session.pop(RESULT_KEY, None)

        result = session.get(RESULT_KEY)
        if isinstance(result, dict):
            if result.get("ok"):
                st.success(f"Added \"{result.get('draft_name')}\" to your Saved Draft Library (team {result.get('team')}).")
            else:
                st.error(str(result.get("error") or "Recovery failed."))

        preview = session.get(PREVIEW_KEY)
        if not isinstance(preview, dict):
            return
        if preview.get("error"):
            st.error(str(preview["error"]))
            return
        st.markdown(
            f"**{preview['league_name']}** · room `{preview['room_code']}` · status **{preview['status']}** · "
            f"your team **{preview['team'] or 'unknown'}** ({preview['role']})"
        )
        settings = preview.get("settings") or {}
        st.caption(
            f"Teams: {', '.join(map(str, settings.get('teams') or [])) or 'none listed'} · "
            f"format: {settings.get('fantasy_format') or 'not recorded'} · rounds: {settings.get('rounds') or 'not recorded'} · "
            f"roster slots: {settings.get('roster_slots') or 'not recorded'}"
        )
        st.dataframe(preview.get("picks") or [], hide_index=True, use_container_width=True)
        for problem in preview.get("problems") or []:
            st.error(f"Can't recover: {problem}.")
        if preview.get("missing"):
            st.info("Not stored in the room (left as recorded, not filled in): " + "; ".join(preview["missing"]) + ".")
        if preview.get("existing_draft_id"):
            st.info(f"This draft is already in your Library as \"{preview.get('existing_draft_name')}\". Nothing will be replaced.")
            if st.button("📂 Open it in the Library", key="sdr_open_existing"):
                session[FOCUS_KEY] = preview["existing_draft_id"]
                st.rerun()
            return
        if not preview.get("ok"):
            return
        keep_both = False
        if preview.get("similar_draft_id"):
            st.warning(
                f"A draft with the same picks is already in your Library as \"{preview.get('similar_draft_name')}\". "
                "It may be this draft saved earlier, or another room with identical picks."
            )
            if st.button("📂 Open that entry", key="sdr_open_similar"):
                session[FOCUS_KEY] = preview["similar_draft_id"]
                st.rerun()
            keep_both = st.checkbox("Keep both: add this room's draft as a separate entry", key="sdr_keep_both")
        name = st.text_input("Name in your Library", value=f"{preview['league_name']} — {preview['team']}", key="sdr_name")
        confirmed = st.checkbox("Add a copy of this completed draft to my Saved Draft Library", key="sdr_confirm")
        if st.button("♻️ Recover draft", key="sdr_recover", type="primary", disabled=not confirmed):
            outcome = recover_completed_shared_draft(
                st,
                session,
                preview["room_code"],
                confirmed=bool(confirmed),  # checked again on the server, not only by the disabled button
                expected_revision=int(preview.get("revision") or 0),
                draft_name=name,
                keep_alongside_similar=bool(keep_both),
            )
            session[RESULT_KEY] = outcome
            if outcome.get("ok"):
                session[FOCUS_KEY] = outcome.get("draft_id")
                session.pop(PREVIEW_KEY, None)
                session[ROOMS_KEY] = list_recoverable_rooms(session)
            st.rerun()
