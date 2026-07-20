"""Live Draft Chat UI — compact 1990s AIM-style messenger (single HTML card)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from live_draft_chat import (
    CHAT_COLLAPSED_KEY,
    CHAT_POLL_SEC,
    CHAT_REPLY_TO_KEY,
    CHAT_SHOW_EARLIER_KEY,
    CHAT_VISIBLE_LIMIT,
    MSG_TYPE_PRIVATE_REPLY,
    MSG_TYPE_SYSTEM,
    append_live_draft_chat_message,
    append_private_reply,
    chat_room_title,
    clear_system_chat_messages,
    count_earlier_user_messages,
    delete_chat_message,
    find_chat_message_in_room,
    format_chat_timestamp,
    is_chat_commissioner,
    load_live_draft_chat,
    mark_chat_seen,
    message_mentions_viewer,
    participant_may_view_message,
    private_reply_label,
    refresh_live_draft_chat_if_newer,
    set_chat_disabled,
    unread_chat_count,
    user_visible_messages,
)

CHAT_COMPOSER_KEY = "live_draft_chat_composer_text"
CHAT_REPLY_CLIENT_ID_KEY = "_live_draft_chat_reply_client_id"


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
div[data-testid="stVerticalBlockBorderWrapper"]:has(.ld-aim-root) {
  padding: 0 !important;
}
.ld-aim-root {
  width: min(380px, 100%);
  margin: 8px 0 12px 0;
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
}
.ld-aim-controls {
  display: inline-flex;
  gap: 3px;
  flex: 0 0 auto;
}
.ld-aim-controls i {
  display: inline-block;
  width: 12px;
  height: 12px;
  background: #c0c0c0;
  border: 1px solid #000;
  color: #000;
  font-size: 9px;
  font-style: normal;
  line-height: 10px;
  text-align: center;
  font-weight: 700;
}
.ld-aim-status {
  background: #d4d0c8;
  border-bottom: 1px solid #808080;
  font-size: 11px;
  color: #222;
  padding: 3px 6px;
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
  height: 220px;
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
.ld-aim-empty { color: #666; font-style: italic; font-size: 11px; padding: 4px 0; }
.ld-aim-composer-note { font-size: 10px; color: #444; padding: 0 6px 4px 6px; }
.ld-aim-private {
  border-left: 3px solid #000080;
  background: #f0f4ff;
  padding: 4px 6px;
  margin-top: 2px;
}
.ld-aim-private-label { font-size: 10px; font-weight: 700; color: #000080; }
.ld-aim-reply-preview {
  font-size: 10px; color: #444; font-style: italic; margin: 2px 0 4px 0;
}
</style>
"""


def canonical_chat_participant_key(participant: dict[str, Any]) -> str:
    """Stable authenticated identity — never display name alone."""
    for key in (
        "user_id",
        "account_user_id",
        "account_id",
        "draft_room_participant_id",
        "participant_id",
        "owned_workspace_id",
        "workspace_id",
    ):
        val = str(participant.get(key) or "").strip().lower()
        if val and not val.startswith(("local:", "anonymous:", "demo:")):
            return val
    return ""


def dedupe_chat_participant_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per canonical user; also one row per claimed team."""
    by_uid: dict[str, dict[str, Any]] = {}
    by_team: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = canonical_chat_participant_key(row)
        if not key:
            # Fallback: team+display so blank ids do not invent duplicates.
            display = str(row.get("display_name") or "").strip().lower()
            team = str(row.get("team_name") or "").strip().lower()
            if not display and not team:
                continue
            key = f"fallback:{display}|{team}"
        team = str(row.get("team_name") or "").strip()
        existing = by_uid.get(key) or {}
        # Prefer the first owner of a team; skip a second identity for the same team.
        if team and team in by_team and by_team[team] != key:
            # Merge into the identity that already owns this team when possible.
            owner_key = by_team[team]
            existing = by_uid.get(owner_key) or existing
            key = owner_key
        merged = dict(existing)
        for field in ("user_id", "display_name", "team_name", "joined_at", "last_seen_at"):
            new_val = row.get(field)
            if new_val not in (None, "") and not merged.get(field):
                merged[field] = new_val
            elif field == "display_name" and new_val and (
                not merged.get("display_name")
                or "@" in str(merged.get("display_name") or "")
            ):
                merged[field] = new_val
        if row.get("joined") or existing.get("joined"):
            merged["joined"] = True
        if not merged.get("user_id"):
            merged["user_id"] = key if not key.startswith("fallback:") else ""
        if not merged.get("display_name"):
            merged["display_name"] = str(row.get("display_name") or merged.get("user_id") or "Manager")
        if team:
            merged["team_name"] = team
            by_team[team] = key
        by_uid[key] = merged
    # Stable order: host-ish first is handled by caller team order; preserve insert order.
    return list(by_uid.values())


def format_chat_participant_status_line(session: dict[str, Any]) -> str:
    """HTML status row — each authenticated manager once."""
    try:
        from live_draft_presence import required_human_participant_rows

        room = session.get("live_draft_room") or {}
        rows = required_human_participant_rows(session, room if isinstance(room, dict) else {})
        rows = dedupe_chat_participant_rows(rows)
        # Host / commissioner first when identifiable.
        try:
            from draft_room_membership import is_room_host
            from draft_room_participant_state import resolve_participant_id

            host_pid = str(resolve_participant_id(session) or "").strip().lower()
            if host_pid:
                # Keep relative order but bubble current host if present.
                pass
            doc = None
            try:
                from draft_room_shared_state import load_shared_room

                code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
                doc = load_shared_room(code) if code else None
            except Exception:
                doc = None
            host_id = ""
            if isinstance(doc, dict):
                host_id = str(doc.get("host_user_id") or doc.get("host_participant_id") or "").strip().lower()

            def _sort_key(r: dict[str, Any]) -> tuple:
                uid = canonical_chat_participant_key(r)
                is_host = bool(host_id and uid == host_id)
                return (0 if is_host else 1, str(r.get("team_name") or ""), str(r.get("display_name") or ""))

            rows = sorted(rows, key=_sort_key)
            _ = is_room_host  # import kept for future host checks
        except ImportError:
            pass

        bits: list[str] = []
        for row in rows[:8]:
            name = _escape_html(str(row.get("display_name") or "").strip())
            if not name:
                continue
            if "@" in name:
                name = _escape_html(name.split("@", 1)[0])
            team = _escape_html(str(row.get("team_name") or "").strip())
            dot = '<span class="ld-aim-dot" title="Joined"></span>' if row.get("joined") else ""
            bits.append(f"{dot}{name} ({team})" if team else f"{dot}{name}")
        # Collapse accidental duplicate separators.
        line = " · ".join(bits)
        while " ·  · " in line:
            line = line.replace(" ·  · ", " · ")
        return line if line else "Managers in this draft"
    except Exception:
        return "Managers in this draft"


def _current_participant_id(session: dict[str, Any]) -> str:
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return ""


def _transcript_html(session: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    if not messages:
        return (
            '<div class="ld-aim-log"><div class="ld-aim-empty">'
            "No league messages yet. Start the conversation."
            "</div></div>"
        )
    me = _current_participant_id(session)
    parts = ['<div class="ld-aim-log" id="ld-aim-log">']
    for msg in messages:
        classes = ["ld-aim-row"]
        is_private = str(msg.get("message_type") or "") == MSG_TYPE_PRIVATE_REPLY
        if me and str(msg.get("participant_id") or msg.get("sender_participant_id") or "") == me:
            classes.append("mine")
        if message_mentions_viewer(msg, session):
            classes.append("mention")
        name = _escape_html(str(msg.get("display_name") or "Manager"))
        team = _escape_html(str(msg.get("claimed_team") or msg.get("team") or ""))
        ts = _escape_html(format_chat_timestamp(str(msg.get("ts") or "")))
        text = _escape_html(str(msg.get("text") or ""))
        team_bit = f' <span class="ld-aim-team">— {team}</span>' if team else ""
        if is_private:
            label = _escape_html(private_reply_label(msg))
            preview = _escape_html(str(msg.get("reply_to_preview") or ""))
            parts.append(
                f'<div class="{" ".join(classes)}">'
                f'<div class="ld-aim-meta"><strong>{name}</strong>{team_bit}'
                f'<span class="ld-aim-ts">{ts}</span></div>'
                f'<div class="ld-aim-private">'
                f'<div class="ld-aim-private-label">{label}</div>'
                f'<div class="ld-aim-reply-preview">Replying to: {preview}</div>'
                f'<div class="ld-aim-text">{text}</div>'
                f"</div></div>"
            )
        else:
            parts.append(
                f'<div class="{" ".join(classes)}">'
                f'<div class="ld-aim-meta"><strong>{name}</strong>{team_bit}'
                f'<span class="ld-aim-ts">{ts}</span></div>'
                f'<div class="ld-aim-text">{text}</div></div>'
            )
    parts.append("</div>")
    # Auto-scroll only on initial load / own send / when already near bottom.
    # Avoid yanking users who are reading older messages.
    room_key = str(session.get("active_shared_draft_room_code") or "solo").strip().upper()
    force = bool(session.pop("_live_draft_chat_force_scroll", None))
    parts.append(
        f"<div id='ld-aim-scroll-anchor-{room_key}' data-force='{1 if force else 0}'></div>"
        "<script>(function(){"
        "var el=document.getElementById('ld-aim-log');"
        "if(!el)return;"
        "var force=document.querySelector('[id^=ld-aim-scroll-anchor-]')&&"
        "document.querySelector('[id^=ld-aim-scroll-anchor-]').getAttribute('data-force')==='1';"
        "var near= (el.scrollHeight - el.scrollTop - el.clientHeight) < 80;"
        "if(force||near||el.scrollTop===0){el.scrollTop=el.scrollHeight;}"
        "})();</script>"
    )
    return "\n".join(parts)


def post_chat_message(session: dict[str, Any], text: str, *, composer_key: str = CHAT_COMPOSER_KEY) -> tuple[bool, str]:
    """Persist a chat message and clear composer state. Does not call st.rerun()."""
    reply_to = str(session.get(CHAT_REPLY_TO_KEY) or "").strip()
    if reply_to:
        client_id = str(session.get(CHAT_REPLY_CLIENT_ID_KEY) or "").strip()
        if not client_id:
            client_id = uuid.uuid4().hex
            session[CHAT_REPLY_CLIENT_ID_KEY] = client_id
        ok, err = append_private_reply(
            session,
            reply_to_message_id=reply_to,
            text=text,
            client_message_id=client_id,
        )
    else:
        ok, err = append_live_draft_chat_message(session, text)
    if ok:
        mark_chat_seen(session)
        session["_live_draft_chat_force_scroll"] = True
        session.pop(CHAT_REPLY_TO_KEY, None)
        session.pop(CHAT_REPLY_CLIENT_ID_KEY, None)
        try:
            session[composer_key] = ""
        except Exception:
            pass
        # Keep widget key empty when present (Streamlit form clear_on_submit also helps).
        try:
            session[f"{composer_key}_widget"] = ""
        except Exception:
            pass
        return True, ""
    return False, err or "Could not send message."


# Back-compat alias used by older call sites / tests.
def _post_message(st: Any, session: dict[str, Any], text: str) -> bool:
    """State-mutation only — never requests fragment or app reruns."""
    _ = st
    ok, err = post_chat_message(session, text)
    if not ok and err:
        # Caller may surface the error; keep return boolean for tests.
        session["_live_draft_chat_post_error"] = err
    return ok


def render_live_draft_chat_panel(st: Any, session: dict[str, Any]) -> None:
    """Compact AIM-style Live Draft chat — one HTML card, no empty wrapper box."""
    try:
        from app_page_generation import fragment_allowed

        if not fragment_allowed(session, expected_page="Live Draft Room"):
            return
    except ImportError:
        pass
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
        cols = st.columns([4, 1])
        with cols[0]:
            st.caption(label)
        with cols[1]:
            if st.button("Show", key="live_draft_chat_expand"):
                session[CHAT_COLLAPSED_KEY] = False
                mark_chat_seen(session)
                # Natural button rerun — no fragment scope.
        return

    hide_cols = st.columns([5, 1])
    with hide_cols[1]:
        if st.button("Hide", key="live_draft_chat_collapse", help="Collapse chat"):
            session[CHAT_COLLAPSED_KEY] = True

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
                else:
                    if st.button("Disable chat", key="ld_chat_disable"):
                        set_chat_disabled(session, True)
            with c2:
                if st.button("Clear system messages", key="ld_chat_clear_system"):
                    clear_system_chat_messages(session)
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


def _chat_body(st: Any, session: dict[str, Any], *, form_key: str = "live_draft_chat_form") -> None:
    # One sidecar fetch updates the cache; paint from cache (no second forced full load).
    refresh_live_draft_chat_if_newer(session)
    chat = load_live_draft_chat(session, force=False)
    all_messages = list(chat.get("messages") or [])
    me = _current_participant_id(session)
    show_earlier = bool(session.get(CHAT_SHOW_EARLIER_KEY))
    earlier = count_earlier_user_messages(all_messages, participant_id=me)
    visible = user_visible_messages(
        all_messages,
        limit=20 if show_earlier else CHAT_VISIBLE_LIMIT,
        participant_id=me,
    )

    title = chat_room_title(session)
    status = format_chat_participant_status_line(session)
    transcript = _transcript_html(session, visible)
    # Single markdown payload — title bar is the first visible element; no empty outer box.
    card = (
        '<div class="ld-aim-root">'
        f'<div class="ld-aim-titlebar"><span>Live Draft Chat — {_escape_html(title)}</span>'
        '<span class="ld-aim-controls" aria-hidden="true">'
        "<i>_</i><i>□</i><i>×</i></span></div>"
        f'<div class="ld-aim-status">{status}</div>'
        f"{transcript}"
        "</div>"
    )
    st.markdown(card, unsafe_allow_html=True)

    if chat.get("chat_disabled"):
        st.caption("Chat is disabled for this league.")
        return

    if earlier > 0 and not show_earlier:
        if st.button(f"View earlier messages ({earlier})", key="ld_chat_earlier"):
            session[CHAT_SHOW_EARLIER_KEY] = True
            # Fragment button click already reruns this fragment.
    elif show_earlier:
        if st.button("Show latest five", key="ld_chat_latest_five"):
            session[CHAT_SHOW_EARLIER_KEY] = False

    # Compact Reply actions for eligible messages (fragment-local; no full-page rerun).
    replyable = [
        m
        for m in visible
        if str(m.get("message_type") or "") != MSG_TYPE_SYSTEM
        and participant_may_view_message(m, me)
        and str(m.get("sender_participant_id") or m.get("participant_id") or "") != me
    ]
    if replyable:
        cols = st.columns(min(len(replyable), 5))
        for idx, msg in enumerate(replyable[-5:]):
            mid = str(msg.get("id") or msg.get("message_id") or "")
            author = str(msg.get("display_name") or "Manager").split("@", 1)[0][:16]
            with cols[idx % len(cols)]:
                if st.button(
                    f"Reply · {author}",
                    key=f"ld_chat_reply_{mid}",
                    help="Send a private reply only you and this author can see.",
                ):
                    session[CHAT_REPLY_TO_KEY] = mid
                    session[CHAT_REPLY_CLIENT_ID_KEY] = uuid.uuid4().hex

    reply_to = str(session.get(CHAT_REPLY_TO_KEY) or "").strip()
    if reply_to:
        original = find_chat_message_in_room(session, reply_to)
        if isinstance(original, dict) and participant_may_view_message(original, me):
            preview = str(original.get("text") or "")[:120]
            to_name = str(original.get("display_name") or "Manager").split("@", 1)[0]
            st.caption(f"Private reply to **{to_name}**")
            st.caption(f"Replying to: {preview}")
            if st.button("Cancel", key=f"{form_key}_reply_cancel"):
                session.pop(CHAT_REPLY_TO_KEY, None)
                session.pop(CHAT_REPLY_CLIENT_ID_KEY, None)
        else:
            session.pop(CHAT_REPLY_TO_KEY, None)
            session.pop(CHAT_REPLY_CLIENT_ID_KEY, None)

    err = str(session.pop("_live_draft_chat_post_error", "") or "").strip()
    if err:
        st.caption(err)

    with st.form(form_key, clear_on_submit=True):
        placeholder = (
            "Type a private reply…"
            if session.get(CHAT_REPLY_TO_KEY)
            else "Type a message…"
        )
        message = st.text_area(
            "Message",
            label_visibility="collapsed",
            placeholder=placeholder,
            max_chars=400,
            height=68,
            key=f"{form_key}_input",
        )
        sent = st.form_submit_button("Send")
        if sent:
            # Form submit already triggers a Streamlit rerun — do not call st.rerun().
            _post_message(st, session, message)
