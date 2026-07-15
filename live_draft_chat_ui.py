"""Live Draft Chat UI — fragment-scoped so timer/autopick stay on the hot path."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from live_draft_chat import (
    CHAT_POLL_SEC,
    append_live_draft_chat_message,
    author_label,
    format_chat_timestamp,
    load_live_draft_chat,
    refresh_live_draft_chat_if_newer,
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
  font-size: 13px; font-weight: 700; color: #1f4e79; margin: 0 0 8px 0;
}
.ld-chat-log {
  max-height: 180px; overflow-y: auto;
  border: 1px solid #e3ebf5; border-radius: 8px;
  background: #fff; padding: 8px 10px; margin-bottom: 8px;
}
.ld-chat-row { margin: 0 0 8px 0; line-height: 1.35; }
.ld-chat-meta { font-size: 11px; color: #5a6f82; margin-bottom: 1px; }
.ld-chat-text { font-size: 13px; color: #12324a; word-wrap: break-word; }
.ld-chat-empty { font-size: 12px; color: #7a8b9c; font-style: italic; padding: 6px 2px; }
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


def _render_message_log(st: Any, messages: list[dict[str, Any]]) -> None:
    if not messages:
        st.markdown(
            '<div class="ld-chat-log"><div class="ld-chat-empty">'
            "No messages yet — say hi to the league."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return
    parts: list[str] = ['<div class="ld-chat-log" id="ld-chat-log">']
    for msg in messages[-80:]:
        meta = f"{author_label(msg)} · {format_chat_timestamp(str(msg.get('ts') or ''))}"
        text = _escape_html(str(msg.get("text") or ""))
        parts.append(
            f'<div class="ld-chat-row"><div class="ld-chat-meta">{_escape_html(meta)}</div>'
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


def render_live_draft_chat_panel(st: Any, session: dict[str, Any]) -> None:
    """Full-width chat strip for shared Live Draft rooms only."""
    try:
        from draft_room_context import is_multiplayer_draft_active
    except ImportError:
        return
    if not is_multiplayer_draft_active(session):
        return

    st.markdown(_chat_css(), unsafe_allow_html=True)
    st.markdown('<div class="ld-chat-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="ld-chat-title">Draft Chat</div>', unsafe_allow_html=True)

    try:
        poll_interval = timedelta(seconds=float(CHAT_POLL_SEC))

        @st.fragment(run_every=poll_interval)
        def _chat_fragment() -> None:
            # Never call board sync / poll_shared_draft_room here.
            if session.get("_live_draft_manual_pick_in_flight") or session.get("_pending_manual_draft_pick"):
                chat = load_live_draft_chat(session, force=False)
            else:
                refresh_live_draft_chat_if_newer(session)
                chat = load_live_draft_chat(session, force=False)
            _render_message_log(st, list(chat.get("messages") or []))

            with st.form("live_draft_chat_form", clear_on_submit=True):
                composer = st.columns([5, 1])
                with composer[0]:
                    message = st.text_input(
                        "Message",
                        label_visibility="collapsed",
                        placeholder="Message the league… (Enter to send)",
                        max_chars=400,
                        key="live_draft_chat_form_input",
                    )
                with composer[1]:
                    sent = st.form_submit_button("Send", use_container_width=True)
                if sent:
                    ok, err = append_live_draft_chat_message(session, message)
                    if ok:
                        try:
                            st.rerun(scope="fragment")
                        except TypeError:
                            st.rerun()
                    elif err:
                        st.caption(err)

        _chat_fragment()
    except Exception:
        chat = load_live_draft_chat(session, force=True)
        _render_message_log(st, list(chat.get("messages") or []))
        with st.form("live_draft_chat_form_fallback", clear_on_submit=True):
            composer = st.columns([5, 1])
            with composer[0]:
                message = st.text_input(
                    "Message",
                    label_visibility="collapsed",
                    placeholder="Message the league… (Enter to send)",
                    max_chars=400,
                )
            with composer[1]:
                sent = st.form_submit_button("Send", use_container_width=True)
            if sent:
                ok, err = append_live_draft_chat_message(session, message)
                if ok:
                    st.rerun()
                elif err:
                    st.caption(err)

    st.markdown("</div>", unsafe_allow_html=True)
