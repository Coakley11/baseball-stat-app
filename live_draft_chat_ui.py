"""Live Draft Chat UI — compact 1990s AIM-style messenger window."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from live_draft_chat import (
    CHAT_COLLAPSED_KEY,
    CHAT_POLL_SEC,
    CHAT_SHOW_EARLIER_KEY,
    CHAT_VISIBLE_LIMIT,
    append_live_draft_chat_message,
    author_label,
    chat_room_title,
    clear_system_chat_messages,
    count_earlier_user_messages,
    delete_chat_message,
    format_chat_timestamp,
    is_chat_commissioner,
    load_live_draft_chat,
    mark_chat_seen,
    message_mentions_viewer,
    refresh_live_draft_chat_if_newer,
    set_chat_disabled,
    unread_chat_count,
    user_visible_messages,
)


def _escape_html(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _aim_css() -> str:
    return """
<style>
.ld-aim-wrap {
  width: min(380px, 100%);
  height: 400px;
  max-height: 400px;
  margin: 8px 0 12px 0;
  display: flex;
  flex-direction: column;
  background: #c0c0c0;
  border: 2px solid;
  border-color: #ffffff #808080 #808080 #ffffff;
  font-family: "Tahoma", "MS Sans Serif", "Segoe UI", sans-serif;
  box-sizing: border-box;
}
.ld-aim-titlebar {
  background: #000080;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
}
.ld-aim-controls span {
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-left: 3px;
  background: #c0c0c0;
  border: 1px solid #000;
  color: #000;
  font-size: 9px;
  line-height: 10px;
  text-align: center;
}
.ld-aim-status {
  background: #d4d0c8;
  border-bottom: 1px solid #808080;
  font-size: 11px;
  color: #222;
  padding: 3px 6px;
  flex: 0 0 auto;
}
.ld-aim-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #228b22;
  margin-right: 3px;
  vertical-align: middle;
}
.ld-aim-log {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  background: #ffffff;
  border: 1px inset #808080;
  margin: 4px;
  padding: 6px 8px;
  font-size: 12px;
  color: #000;
}
.ld-aim-row { margin: 0 0 8px 0; line-height: 1.25; }
.ld-aim-row.mine { background: #ffffe0; }
.ld-aim-row.mention { background: #fff4d6; }
.ld-aim-meta { font-size: 11px; color: #333; margin-bottom: 1px; }
.ld-aim-meta strong { font-weight: 700; color: #000080; }
.ld-aim-team { color: #555; font-weight: 400; }
.ld-aim-ts { float: right; color: #666; font-size: 10px; }
.ld-aim-text { clear: both; white-space: pre-wrap; word-wrap: break-word; }
.ld-aim-empty { color: #666; font-style: italic; font-size: 11px; }
.ld-aim-composer {
  flex: 0 0 auto;
  background: #d4d0c8;
  border-top: 1px solid #808080;
  padding: 4px 6px 6px 6px;
}
</style>
"""


def _participant_status_line(session: dict[str, Any]) -> str:
    try:
        from live_draft_presence import required_human_participant_rows

        room = session.get("live_draft_room") or {}
        rows = required_human_participant_rows(session, room if isinstance(room, dict) else {})
        bits = []
        for row in rows[:6]:
            name = _escape_html(str(row.get("display_name") or ""))
            team = _escape_html(str(row.get("team_name") or ""))
            dot = '<span class="ld-aim-dot" title="Joined"></span>' if row.get("joined") else ""
            bits.append(f"{dot}{name} ({team})" if team else f"{dot}{name}")
        return " · ".join(bits) if bits else "Managers in this draft"
    except Exception:
        return "Managers in this draft"


def _current_participant_id(session: dict[str, Any]) -> str:
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return ""


def _render_transcript(st: Any, session: dict[str, Any], messages: list[dict[str, Any]]) -> None:
    if not messages:
        st.markdown(
            '<div class="ld-aim-log"><div class="ld-aim-empty">'
            "No league messages yet. Start the conversation."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return
    me = _current_participant_id(session)
    parts = ['<div class="ld-aim-log" id="ld-aim-log">']
    for msg in messages:
        classes = ["ld-aim-row"]
        if me and str(msg.get("participant_id") or "") == me:
            classes.append("mine")
        if message_mentions_viewer(msg, session):
            classes.append("mention")
        name = _escape_html(str(msg.get("display_name") or "Manager"))
        team = _escape_html(str(msg.get("claimed_team") or msg.get("team") or ""))
        ts = _escape_html(format_chat_timestamp(str(msg.get("ts") or "")))
        text = _escape_html(str(msg.get("text") or ""))
        team_bit = f' <span class="ld-aim-team">— {team}</span>' if team else ""
        parts.append(
            f'<div class="{" ".join(classes)}">'
            f'<div class="ld-aim-meta"><strong>{name}</strong>{team_bit}'
            f'<span class="ld-aim-ts">{ts}</span></div>'
            f'<div class="ld-aim-text">{text}</div></div>'
        )
    parts.append("</div>")
    parts.append(
        "<script>var el=document.getElementById('ld-aim-log');"
        "if(el){el.scrollTop=el.scrollHeight;}</script>"
    )
    st.markdown("\n".join(parts), unsafe_allow_html=True)


def _post_message(st: Any, session: dict[str, Any], text: str) -> None:
    ok, err = append_live_draft_chat_message(session, text)
    if ok:
        mark_chat_seen(session)
        try:
            st.rerun(scope="fragment")
        except TypeError:
            st.rerun()
    elif err:
        st.caption(err)


def render_live_draft_chat_panel(st: Any, session: dict[str, Any]) -> None:
    """Compact AIM-style Live Draft chat — shared scope, five visible messages."""
    try:
        from draft_room_context import is_multiplayer_draft_active
    except ImportError:
        return
    if not is_multiplayer_draft_active(session):
        return

    title = chat_room_title(session)
    chat_preview = load_live_draft_chat(session, force=False)
    unread = unread_chat_count(session, chat_preview)
    collapsed = bool(session.get(CHAT_COLLAPSED_KEY))

    st.markdown(_aim_css(), unsafe_allow_html=True)

    if collapsed:
        label = f"Live Draft Chat — {title}"
        if unread:
            label += f" ({unread} unread)"
        if st.button(label, key="live_draft_chat_expand"):
            session[CHAT_COLLAPSED_KEY] = False
            mark_chat_seen(session)
            st.rerun()
        return

    st.markdown('<div class="ld-aim-wrap">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ld-aim-titlebar"><span>Live Draft Chat — {_escape_html(title)}</span>'
        f'<span class="ld-aim-controls"><span>_</span><span>□</span><span>×</span></span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="ld-aim-status">{_participant_status_line(session)}</div>',
        unsafe_allow_html=True,
    )

    head = st.columns([4, 1])
    with head[1]:
        if st.button("Hide", key="live_draft_chat_collapse", help="Collapse chat"):
            session[CHAT_COLLAPSED_KEY] = True
            st.rerun()

    mark_chat_seen(session, chat_preview)

    try:
        poll_interval = timedelta(seconds=float(CHAT_POLL_SEC))

        @st.fragment(run_every=poll_interval)
        def _chat_fragment() -> None:
            _chat_body(st, session)

        _chat_fragment()
    except Exception:
        _chat_body(st, session, form_key="live_draft_chat_form_fallback")

    if is_chat_commissioner(session):
        with st.expander("Commissioner chat controls", expanded=False):
            disabled = bool(chat_preview.get("chat_disabled"))
            c1, c2, c3 = st.columns(3)
            with c1:
                if disabled:
                    if st.button("Re-enable chat", key="ld_chat_enable"):
                        set_chat_disabled(session, False)
                        st.rerun()
                else:
                    if st.button("Disable chat", key="ld_chat_disable"):
                        set_chat_disabled(session, True)
                        st.rerun()
            with c2:
                if st.button("Clear system messages", key="ld_chat_clear_system"):
                    clear_system_chat_messages(session)
                    st.rerun()
            with c3:
                mid = st.text_input(
                    "Delete message id",
                    key="ld_chat_delete_id",
                    label_visibility="collapsed",
                    placeholder="Message id",
                )
                if st.button("Delete", key="ld_chat_delete_btn") and mid:
                    ok, err = delete_chat_message(session, mid)
                    if not ok and err:
                        st.caption(err)
                    else:
                        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def _chat_body(st: Any, session: dict[str, Any], *, form_key: str = "live_draft_chat_form") -> None:
    refresh_live_draft_chat_if_newer(session)
    chat = load_live_draft_chat(session, force=True)
    all_messages = list(chat.get("messages") or [])
    show_earlier = bool(session.get(CHAT_SHOW_EARLIER_KEY))
    earlier = count_earlier_user_messages(all_messages)
    if show_earlier:
        visible = user_visible_messages(all_messages, limit=20)
    else:
        visible = user_visible_messages(all_messages, limit=CHAT_VISIBLE_LIMIT)

    if chat.get("chat_disabled"):
        st.caption("Chat is disabled for this league.")
        _render_transcript(st, session, visible)
        return

    if earlier > 0 and not show_earlier:
        if st.button(f"View earlier messages ({earlier})", key="ld_chat_earlier"):
            session[CHAT_SHOW_EARLIER_KEY] = True
            try:
                st.rerun(scope="fragment")
            except TypeError:
                st.rerun()
    elif show_earlier:
        if st.button("Show latest five", key="ld_chat_latest_five"):
            session[CHAT_SHOW_EARLIER_KEY] = False
            try:
                st.rerun(scope="fragment")
            except TypeError:
                st.rerun()

    _render_transcript(st, session, visible)

    with st.form(form_key, clear_on_submit=True):
        message = st.text_area(
            "Message",
            label_visibility="collapsed",
            placeholder="Type a message…",
            max_chars=400,
            height=68,
            key=f"{form_key}_input",
        )
        sent = st.form_submit_button("Send", use_container_width=False)
        if sent:
            _post_message(st, session, message)
