"""Solo Live Clock — browser-owned visual countdown + one expire event.

Stable Streamlit component key is room-scoped (not pick/deadline). Absolute
deadline is a prop so Streamlit reruns (Queue, Manual filter, etc.) resume
remaining time instead of resetting the clock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_FRONTEND_DIR = (Path(__file__).resolve().parent / "frontend").resolve()
_COMPONENT = components.declare_component(
    "solo_live_clock",
    path=str(_FRONTEND_DIR),
)

SOLO_LIVE_CLOCK_ACTIVE_KEY = "_solo_live_clock_active"
SOLO_LIVE_CLOCK_LAST_TOKEN_KEY = "_solo_live_clock_last_expire_token"


def get_component_frontend_dir() -> Path:
    return _FRONTEND_DIR


def component_frontend_ready() -> bool:
    return (_FRONTEND_DIR / "index.html").is_file()


def solo_live_clock_widget_key(room_id: str) -> str:
    rid = str(room_id or "solo").strip().upper() or "SOLO"
    # Stable identity — must NOT include pick index or deadline.
    return f"solo_live_clock_{rid[:24]}"


def solo_live_clock_prewarm_key(room_id: str) -> str:
    rid = str(room_id or "solo").strip().upper() or "SOLO"
    return f"solo_live_clock_prewarm_{rid[:24]}"


def prewarm_solo_live_clock(st: Any, room_id: str = "solo") -> bool:
    """Warm this component's registration while the timer is still off.

    Streamlit serves a declared component's frontend only on its first use in a
    server process. Measured on a fresh process: the first on-clock paint
    rendered the keyed container with NO iframe child at +4.2s, recovering to
    197px later — and because ``component_frontend_ready()`` is just a
    file-exists check, the documented legacy fallback was unreachable during
    that window, so the user saw the "TIME REMAINING" label with no clock.

    Mounting the SAME declared component once during Preparing/Ready pays the
    registration round-trip up front. The mount is inert by construction:
    ``prewarm=True`` makes the frontend render nothing and report height 0,
    and ``running=False`` / empty ``expire_token`` / ``deadline=0`` mean it
    never ticks and never emits an expire event. No second clock, no second
    deadline authority, no legacy markup.
    """
    if not component_frontend_ready():
        return False
    try:
        # Collapse only the prewarm container. The frontend asks for height 0, but
        # its init calls the 160px-floored setFrameHeight() before props arrive and
        # Streamlit's element container keeps its own box -- measured 26px, which
        # would otherwise be a visible empty gap in the Ready card. Scoped to the
        # prewarm key prefix so the real clock container is untouched. Height 0
        # rather than display:none so the iframe still loads and completes the
        # registration handshake this mount exists to perform.
        # Emitted EVERY run, deliberately not guarded by a session flag: a
        # st.markdown style only exists in the run that wrote it, so a once-only
        # guard left the rule present on the first run and gone afterwards
        # (measured container height 0 -> 40 -> 26 as the style disappeared).
        st.markdown(
            "<style>"
            '[class*="st-key-solo_live_clock_prewarm_"]{'
            "height:0!important;min-height:0!important;max-height:0!important;"
            "margin:0!important;padding:0!important;overflow:hidden!important;"
            "}"
            '[class*="st-key-solo_live_clock_prewarm_"] iframe{'
            "height:0!important;min-height:0!important;display:block!important;"
            "}</style>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass
    try:
        _COMPONENT(
            prewarm=True,
            expire_token="",
            deadline=0.0,
            pick_index=0,
            pick_number=0,
            team="",
            round_label="",
            next_pick=0,
            has_next_pick=False,
            room_id=str(room_id or "solo"),
            clock_seconds=0,
            flash=False,
            widget_key=solo_live_clock_prewarm_key(room_id),
            key=solo_live_clock_prewarm_key(room_id),
            default=None,
        )
        return True
    except Exception:
        return False


def _coerce_token(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("token", "expire_token", "value"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value).strip()


def render_solo_live_clock(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    slot: dict[str, Any] | None,
    *,
    next_pick: int | None = None,
    flash: bool = False,
) -> str | None:
    """Mount the visible Solo On-the-Clock component; return expire token if any."""
    if not component_frontend_ready():
        return None
    if str(room.get("status") or "") != "in_progress":
        session.pop(SOLO_LIVE_CLOCK_ACTIVE_KEY, None)
        return None
    try:
        from live_draft_timer_logic import live_draft_timer_deadline
        from solo_countdown_component import build_solo_expire_token
    except ImportError:
        return None

    deadline = live_draft_timer_deadline(room)
    if deadline is None:
        raw = room.get("timer_deadline")
        if raw is not None:
            deadline = float(raw)
    if deadline is None:
        return None

    # If the page took longer than the clock to paint, the deadline may already be
    # past before the browser component mounts.
    #
    # Pick 1 (empty board, never live-ready): re-arm once so the user actually sees
    # a full clock after a slow first product paint. Later picks: expire+advance.
    try:
        import time as _time
        from live_draft_timer_logic import (
            TIMER_LIVE_READY_AT_KEY,
            live_draft_reset_timer,
        )

        if float(deadline) <= _time.time():
            board = room.get("draft_board") or []
            pick0 = int(room.get("current_pick_index") or 0) == 0
            never_live_ready = not bool(room.get(TIMER_LIVE_READY_AT_KEY))
            empty_board = not (isinstance(board, list) and board)
            if pick0 and never_live_ready and empty_board:
                live_draft_reset_timer(room)
                room[TIMER_LIVE_READY_AT_KEY] = _time.time()
                session["live_draft_room"] = room
                deadline = live_draft_timer_deadline(room)
                if deadline is None and room.get("timer_deadline") is not None:
                    deadline = float(room.get("timer_deadline"))
            else:
                from live_draft_solo_timer import expire_current_pick_and_advance

                result = expire_current_pick_and_advance(
                    room, session=session, request_full_rerun=False
                )
                live = session.get("live_draft_room")
                if isinstance(live, dict):
                    room = live
                if result is not None and result.ok and (result.advanced or result.complete):
                    deadline = live_draft_timer_deadline(room)
                    if deadline is None and room.get("timer_deadline") is not None:
                        deadline = float(room.get("timer_deadline"))
                    if str(room.get("status") or "") != "in_progress" or deadline is None:
                        session.pop(SOLO_LIVE_CLOCK_ACTIVE_KEY, None)
                        return None
                    try:
                        from live_draft_timer_logic import live_draft_current_slot

                        fresh = live_draft_current_slot(room)
                        if isinstance(fresh, dict):
                            slot = fresh
                    except ImportError:
                        pass
        elif not room.get(TIMER_LIVE_READY_AT_KEY) and int(room.get("current_pick_index") or 0) == 0:
            # First successful live-clock mount stamps live-ready even when remaining > 0.
            room[TIMER_LIVE_READY_AT_KEY] = _time.time()
            session["live_draft_room"] = room
    except Exception:
        pass

    if deadline is None:
        return None

    room_id = str(
        room.get("draft_room_id") or room.get("draft_id") or room.get("id") or "solo"
    ).strip() or "solo"
    pick_index = int(room.get("current_pick_index") or 0)
    slot_d = dict(slot or {})
    team = str(slot_d.get("Team") or room.get("on_clock_team") or "—")
    rnd = slot_d.get("Round", "—")
    pick_no = slot_d.get("Pick", pick_index + 1)
    expire_token = build_solo_expire_token(room)
    widget_key = solo_live_clock_widget_key(room_id)
    cfg = dict(room.get("config") or {})
    clock_seconds = int(
        cfg.get("timer_seconds")
        or room.get("timer_seconds")
        or room.get("pick_timer_seconds")
        or 60
    )

    session[SOLO_LIVE_CLOCK_ACTIVE_KEY] = True
    session["_solo_live_clock_ready_once"] = True
    # Do NOT set `_solo_server_timer_active` — that flag suppresses post-expire
    # full ScriptRun (fragment-owned path). Live clock needs a full page rerun.
    try:
        from live_draft_on_clock_ui import SOLO_SERVER_TIMER_ACTIVE_KEY

        session.pop(SOLO_SERVER_TIMER_ACTIVE_KEY, None)
    except ImportError:
        session.pop("_solo_server_timer_active", None)
    try:
        from live_draft_solo_expire_chain import SOLO_EXPIRE_OWNER_KEY

        session[SOLO_EXPIRE_OWNER_KEY] = "wake"
    except ImportError:
        session["_solo_expire_owner"] = "wake"
    session["_solo_live_clock_expire_owner"] = "wake"

    def _on_change() -> None:
        raw = st.session_state.get(widget_key)
        token = _coerce_token(raw)
        if not token:
            return
        if token == str(session.get(SOLO_LIVE_CLOCK_LAST_TOKEN_KEY) or ""):
            return
        try:
            from live_draft_solo_heartbeat import process_solo_component_wake

            if process_solo_component_wake(
                st, session, room, token, delivery_via="live_clock_on_change"
            ):
                session[SOLO_LIVE_CLOCK_LAST_TOKEN_KEY] = token
        except ImportError:
            pass

    value = _COMPONENT(
        expire_token=expire_token,
        deadline=float(deadline),
        pick_index=int(pick_index),
        pick_number=int(pick_no) if str(pick_no).isdigit() else int(pick_index) + 1,
        team=team,
        round_label=str(rnd),
        next_pick=int(next_pick) if next_pick is not None else 0,
        has_next_pick=bool(next_pick is not None),
        room_id=room_id,
        clock_seconds=int(clock_seconds),
        flash=bool(flash),
        widget_key=widget_key,
        key=widget_key,
        default=None,
        on_change=_on_change,
    )
    token = _coerce_token(value)
    if token and token != str(session.get(SOLO_LIVE_CLOCK_LAST_TOKEN_KEY) or ""):
        try:
            from live_draft_solo_heartbeat import process_solo_component_wake

            if process_solo_component_wake(
                st, session, room, token, delivery_via="live_clock_return"
            ):
                session[SOLO_LIVE_CLOCK_LAST_TOKEN_KEY] = token
        except ImportError:
            pass
        return token
    return None
