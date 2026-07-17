"""Live Draft Chat UI — fragment-scoped so timer/autopick stay on the hot path."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from live_draft_chat import (
    CHAT_COLLAPSED_KEY,
    CHAT_POLL_SEC,
    QUICK_MESSAGES,
    append_live_draft_chat_message,
    author_label,
    chat_room_title,
    clear_system_chat_messages,
    delete_chat_message,
    format_chat_timestamp,
    is_chat_commissioner,
    load_live_draft_chat,
    mark_chat_seen,
    message_mentions_viewer,
    refresh_live_draft_chat_if_newer,
    set_chat_disabled,
    unread_chat_count,
)


def _chat_css() -> str:
    return """
<style>
.ld-chat-wrap {
  margin: 8px 0 14px 0;
  padding: 10px 12px;
  background: linear-gradient(180deg, #f7faff 0%, #ffffff 100%);
  border: 1px solid #d5e2f2;
  border-radius: 10px;
}
.ld-chat-title {
  font-size: 13px; font-weight: 700; color: #1f4e79; margin: 0 0 4px 0;
}
.ld-chat-sub {
  font-size: 11px; color: #5a6f82; margin: 0 0 8px 0;
}
.ld-chat-log {
  max-height: 200px; overflow-y: auto;
  border: 1px solid #e3ebf5; border-radius: 8px;
  background: #fff; padding: 8px 10px; margin-bottom: 8px;
}
.ld-chat-row { margin: 0 0 8px 0; line-height: 1.35; }
.ld-chat-row.mine {
  background: #eef6ff; border-radius: 6px; padding: 4px 6px; margin-left: 12px;
}
.ld-chat-row.system { opacity: 0.85; font-style: italic; }
.ld-chat-row.mention {
  border-left: 3px solid #c47b1a; padding-left: 6px; background: #fff8ee;
}
.ld-chat-meta { font-size: 11px; color: #5a6f82; margin-bottom: 1px; }
.ld-chat-text { font-size: 13px; color: #12324a; word-wrap: break-word; }
.ld-chat-empty { font-size: 12px; color: #7a8b9c; font-style: italic; padding: 6px 2px; }
.ld-chat-mention-hl { font-weight: 700; color: #8a4b08; }
</style>
"""


def _escape_html(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _highlight_mentions(escaped_text: str) -> str:
    import re

    return re.sub(
        r"(@[A-Za-z0-9][A-Za-z0-9 _.'-]{0,40})",
        r'<span class="ld-chat-mention-hl">\1</span>',
        escaped_text,
    )


def _current_participant_id(session: dict[str, Any]) -> str:
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return ""


def _render_message_log(st: Any, session: dict[str, Any], messages: list[dict[str, Any]]) -> None:
    if not messages:
        st.markdown(
            '<div class="ld-chat-log"><div class="ld-chat-empty">'
            "No league messages yet. Start the conversation."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return
    me = _current_participant_id(session)
    parts: list[str] = ['<div class="ld-chat-log" id="ld-chat-log">']
    for msg in messages[-80:]:
        classes = ["ld-chat-row"]
        msg_type = str(msg.get("message_type") or "user")
        if msg_type == "system":
            classes.append("system")
        if me and str(msg.get("participant_id") or "") == me and msg_type != "system":
            classes.append("mine")
        if message_mentions_viewer(msg, session):
            classes.append("mention")
        meta = f"{author_label(msg)} · {format_chat_timestamp(str(msg.get('ts') or ''))}"
        text = _highlight_mentions(_escape_html(str(msg.get("text") or "")))
        parts.append(
            f'<div class="{" ".join(classes)}"><div class="ld-chat-meta">{_escape_html(meta)}</div>'
            f'<div class="ld-chat-text">{text}</div></div>'
        )
    parts.append("</div>")
    parts.append(
        "<script>"
        "var el=document.getElementById('ld-chat-log');"
        "if(el){el.scrollTop=el.scrollHeight;}"
        "</script>"
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
    """Compact Live Draft / shared-league chat panel."""
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

    st.markdown(_chat_css(), unsafe_allow_html=True)
    st.markdown('<div class="ld-chat-wrap">', unsafe_allow_html=True)

    head = st.columns([5, 1])
    with head[0]:
        badge = f" · {unread} unread" if collapsed and unread else ""
        st.markdown(
            f'<div class="ld-chat-title">{_escape_html(title)} — Draft Chat{badge}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="ld-chat-sub">League chat for this live draft</div>',
            unsafe_allow_html=True,
        )
    with head[1]:
        toggle_label = "Expand" if collapsed else "Collapse"
        if st.button(toggle_label, key="live_draft_chat_collapse", use_container_width=True):
            session[CHAT_COLLAPSED_KEY] = not collapsed
            if not session[CHAT_COLLAPSED_KEY]:
                mark_chat_seen(session)
            st.rerun()

    if collapsed:
        if unread:
            st.caption(f"{unread} unread message{'s' if unread != 1 else ''}")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    mark_chat_seen(session, chat_preview)

    try:
        poll_interval = timedelta(seconds=float(CHAT_POLL_SEC))

        @st.fragment(run_every=poll_interval)
        def _chat_fragment() -> None:
            t0 = None
            try:
                import time

                from live_draft_perf import PHASE_CHAT_LOAD, live_draft_perf_action

                t0 = time.perf_counter()
                ctx = live_draft_perf_action(session, "chat_load", phase=PHASE_CHAT_LOAD)
            except Exception:
                ctx = None
            if ctx is not None:
                with ctx:
                    _chat_fragment_body(st, session)
            else:
                _chat_fragment_body(st, session)
            if t0 is not None:
                try:
                    session["_live_draft_chat_load_ms"] = int((time.perf_counter() - t0) * 1000)
                except Exception:
                    pass

        _chat_fragment()
    except Exception:
        _chat_fragment_body(st, session, form_key="live_draft_chat_form_fallback")

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
                mid = st.text_input("Delete message id", key="ld_chat_delete_id", label_visibility="collapsed", placeholder="Message id")
                if st.button("Delete", key="ld_chat_delete_btn") and mid:
                    ok, err = delete_chat_message(session, mid)
                    if not ok and err:
                        st.caption(err)
                    else:
                        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def _chat_fragment_body(st: Any, session: dict[str, Any], *, form_key: str = "live_draft_chat_form") -> None:
    if session.get("_live_draft_manual_pick_in_flight") or session.get("_pending_manual_draft_pick"):
        chat = load_live_draft_chat(session, force=False)
    else:
        refresh_live_draft_chat_if_newer(session)
        chat = load_live_draft_chat(session, force=False)

    if chat.get("chat_disabled"):
        st.caption("Chat is disabled for this league.")
        _render_message_log(st, session, list(chat.get("messages") or []))
        return

    _render_message_log(st, session, list(chat.get("messages") or []))

    quick_cols = st.columns(len(QUICK_MESSAGES))
    for i, phrase in enumerate(QUICK_MESSAGES):
        with quick_cols[i]:
            if st.button(phrase, key=f"ld_chat_quick_{i}", use_container_width=True):
                _post_message(st, session, phrase)

    with st.form(form_key, clear_on_submit=True):
        composer = st.columns([5, 1])
        with composer[0]:
            message = st.text_input(
                "Message",
                label_visibility="collapsed",
                placeholder="Message the league… (@Team to mention)",
                max_chars=400,
                key=f"{form_key}_input",
            )
        with composer[1]:
            sent = st.form_submit_button("Send", use_container_width=True)
        if sent:
            _post_message(st, session, message)
