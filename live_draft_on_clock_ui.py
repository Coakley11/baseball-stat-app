"""Live-updating On-the-Clock banner — shares countdown with live_draft_timer_ui.

Solo: one server-driven ``st.fragment`` + ordinary Streamlit/HTML markup.
Shared: ``components.html`` iframe countdown (unchanged).
"""

from __future__ import annotations

import json
import math
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_display_seconds, live_draft_timer_deadline
from live_draft_timer_ui import _resolve_live_room, record_timer_diagnostics

# Solo fragment cadence — 0.5s after DOM-stability work; expire paints next pick
# in the same invocation (never an empty fragment between picks).
SOLO_TIMER_FRAGMENT_CADENCE = timedelta(milliseconds=500)
SOLO_SERVER_TIMER_ACTIVE_KEY = "_solo_server_timer_active"
SOLO_TIMER_FRAGMENT_RUNS_KEY = "_solo_timer_fragment_runs"
SOLO_POST_EXPIRE_REFRESH_KEY = "_solo_post_expire_refresh_pending"
SOLO_EXPIRE_GUARD_KEY = "_solo_server_expire_guard_token"
SOLO_FRAGMENT_LIFECYCLE_SEQ_KEY = "_solo_fragment_lifecycle_seq"

# Session-scoped fragment mounts. A process-global single mount survived across
# Playwright page.goto / new websocket sessions and produced dual wrappers plus
# ``fragment does not exist`` storms that killed the Streamlit process around
# pick 8–9. Key by Streamlit session_id; prune stale entries.
_SOLO_TIMER_FRAGMENT_BY_SESSION: dict[str, Any] = {}
_SOLO_TIMER_FRAGMENT_MOUNT: list[Any] = []  # legacy alias — last mount only
_SOLO_TIMER_MOUNT_SESSION: str | None = None


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is not None and getattr(ctx, "session_id", None):
            return str(ctx.session_id)
    except Exception:
        pass
    return "unknown"


def keep_solo_timer_fragment_registered(st: Any, *, active_page: str = "") -> None:
    """Re-declare the Solo clock fragment on non-LDR ScriptRuns only.

    Streamlit clears ``run_every`` fragments that are not invoked during a full
    ScriptRun. Off Live Draft Room we must call the existing mount so it is not
    evicted. On Live Draft Room, only ``mount_solo_on_clock_fragment`` may invoke
    it — calling it earlier (different delta path) creates a second fragment id
    and dual on-clock wrappers.
    """
    page = str(active_page or "").strip()
    if page in ("Live Draft Room", "Live Draft"):
        return
    sid = _streamlit_session_id()
    frag = _SOLO_TIMER_FRAGMENT_BY_SESSION.get(sid)
    if frag is None:
        return
    try:
        frag()
    except Exception:
        pass


def _solo_fragment_is_auto_rerun() -> bool:
    """True when Streamlit is executing a fragment-only auto-rerun."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx(suppress_warning=True)
        return bool(ctx is not None and getattr(ctx, "fragment_ids_this_run", None))
    except Exception:
        return False


def _solo_fragment_should_skip_duplicate_fullrun_paint(session: dict[str, Any]) -> bool:
    """If mount is somehow invoked twice in one full ScriptRun, paint once."""
    if _solo_fragment_is_auto_rerun():
        return False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx(suppress_warning=True)
        token = id(ctx) if ctx is not None else None
    except Exception:
        token = None
    if token is None:
        return False
    if session.get("_solo_frag_fullrun_paint_token") == token:
        return True
    session["_solo_frag_fullrun_paint_token"] = token
    return False


def mount_solo_on_clock_fragment(
    st: Any,
    session: dict[str, Any],
    *,
    room_id: str,
    next_pick: int | None = None,
    slot_view: dict[str, Any] | None = None,
) -> None:
    """Register the Solo timer fragment scoped to this Streamlit session."""
    global _SOLO_TIMER_MOUNT_SESSION
    session["_solo_frag_room_id"] = str(room_id or "solo")
    session["_solo_frag_next_pick"] = next_pick
    session["_solo_frag_slot_view"] = dict(slot_view or {})
    session[SOLO_SERVER_TIMER_ACTIVE_KEY] = True
    sid = _streamlit_session_id()
    if sid not in _SOLO_TIMER_FRAGMENT_BY_SESSION:
        try:
            deco = st.fragment(run_every=SOLO_TIMER_FRAGMENT_CADENCE)
        except Exception:
            _solo_on_clock_fragment_tick()
            return
        _SOLO_TIMER_FRAGMENT_BY_SESSION[sid] = deco(_solo_on_clock_fragment_tick)
        # Drop other sessions' mounts — their run_every callbacks are orphaned
        # after Playwright reconnect / page.goto and can crash the process.
        for other in list(_SOLO_TIMER_FRAGMENT_BY_SESSION.keys()):
            if other != sid:
                _SOLO_TIMER_FRAGMENT_BY_SESSION.pop(other, None)
        _SOLO_TIMER_FRAGMENT_MOUNT[:] = [_SOLO_TIMER_FRAGMENT_BY_SESSION[sid]]
        _SOLO_TIMER_MOUNT_SESSION = sid
    try:
        _SOLO_TIMER_FRAGMENT_BY_SESSION[sid]()
    except Exception:
        _solo_on_clock_fragment_tick()


_ON_CLOCK_BANNER_CSS = """
.live-draft-on-clock {
  font-family: system-ui, -apple-system, Segoe UI, sans-serif;
  background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #1d4ed8 100%);
  color: #f8fafc;
  border-radius: 12px;
  padding: 16px 18px;
  margin: 0 0 8px 0;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.35);
}
.live-draft-on-clock .ld-title {
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  opacity: 0.85;
  margin-bottom: 4px;
}
.live-draft-on-clock .ld-team-name {
  font-size: 28px;
  font-weight: 800;
  line-height: 1.1;
  margin-bottom: 10px;
}
.live-draft-on-clock .ld-pick-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.live-draft-on-clock .ld-pill {
  background: rgba(248, 250, 252, 0.14);
  border: 1px solid rgba(248, 250, 252, 0.22);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 13px;
  font-weight: 600;
}
.live-draft-on-clock .ld-next-pick {
  margin-top: 10px;
  font-size: 13px;
  opacity: 0.92;
}
.live-draft-on-clock .ld-meta {
  margin-top: 14px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.live-draft-on-clock .ld-clock-label {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  opacity: 0.8;
}
.live-draft-on-clock .live-draft-timer {
  font-size: 36px;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.live-draft-on-clock.ld-on-clock-flash {
  animation: ldFlash 0.9s ease-in-out 2;
}
@keyframes ldFlash {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.18); }
}
"""


def _team_accent(team: str) -> str:
    import hashlib

    digest = hashlib.md5(str(team or "team").encode("utf-8")).hexdigest()
    return f"#{digest[:6]}"


def _build_on_clock_banner_markup(
    slot: dict[str, Any],
    remaining: int,
    *,
    next_pick: int | None = None,
    pick_index: int = 0,
    deadline: float | None = None,
    flash: bool = False,
    room_id: str = "",
) -> str:
    team = slot.get("Team", "—")
    rnd = slot.get("Round", "—")
    pick_no = slot.get("Pick", "—")
    next_txt = f'<div class="ld-next-pick">Your next pick: #{next_pick}</div>' if next_pick else ""
    accent = _team_accent(str(team))
    seed = max(0, int(remaining))
    dl_token = f"{float(deadline):.3f}" if deadline is not None else "none"
    rid = str(room_id or "solo").strip() or "solo"
    timer_key = f"{rid}|{int(pick_index)}|{dl_token}"
    flash_class = " ld-on-clock-flash" if flash else ""
    dl_attr = f"{float(deadline):.3f}" if deadline is not None else ""
    return f"""
        <div class="live-draft-on-clock{flash_class}" style="border-left: 8px solid {accent};"
             data-live-draft-timer-root="1" data-timer-key="{timer_key}"
             data-testid="live-draft-on-clock">
            <div class="ld-title">On the clock</div>
            <div class="ld-team-name">{team}</div>
            <div class="ld-pick-pills">
                <span class="ld-pill" data-testid="live-draft-pick"
                      data-pick-index="{int(pick_index)}" data-pick-number="{pick_no}">
                    Round {rnd}</span>
                <span class="ld-pill">Pick {pick_no}</span>
            </div>
            {next_txt}
            <div class="ld-meta">
                <span class="ld-clock-label">Time remaining</span>
                <span class="live-draft-timer"
                      data-testid="live-draft-timer"
                      data-timer-key="{timer_key}"
                      data-authoritative="1"
                      data-room-id="{rid}"
                      data-pick-index="{int(pick_index)}"
                      data-deadline-version="{dl_token}"
                      data-deadline="{dl_attr}">{seed}</span>
            </div>
        </div>
        """


def _emit_solo_server_timer_markup(st: Any, html: str) -> None:
    """Solo clock HTML via ``st.html`` (not iframed, not ``components.html``)."""
    try:
        st.markdown(f"<style>{_ON_CLOCK_BANNER_CSS}</style>", unsafe_allow_html=True)
    except Exception:
        pass
    try:
        # Body only — CSS injected separately. st.html is not iframed (Streamlit 1.59).
        st.html(html)
        return
    except Exception as exc:
        try:
            st.session_state["_solo_st_html_err"] = f"{type(exc).__name__}: {exc}"[:160]
        except Exception:
            pass


def _render_solo_on_clock_card(
    st: Any,
    slot: dict[str, Any],
    remaining: int,
    *,
    next_pick: int | None = None,
    pick_index: int = 0,
    deadline: float | None = None,
    flash: bool = False,
    room_id: str = "",
    state_version: str | int | None = None,
    board_len: int | None = None,
) -> bool:
    """Paint Solo On-the-Clock with native Streamlit + one ``st.html`` timer node.

    Single persistent owner of team / round / pick / countdown. Always emits the
    ``data-testid="live-draft-on-clock"`` wrapper — never leave a blank fragment.
    Returns True when timer markup was emitted.
    """
    del flash  # reserved for shared flash CSS; native path uses metric emphasis
    rem = max(0, int(remaining))
    team = str(slot.get("Team", "—") or "—")
    rnd = slot.get("Round", "—")
    pick_no = slot.get("Pick", "—")
    rid = str(room_id or "solo").strip() or "solo"
    dl_token = f"{float(deadline):.3f}" if deadline is not None else "none"
    timer_key = f"{rid}|{int(pick_index)}|{dl_token}"
    dl_attr = f"{float(deadline):.3f}" if deadline is not None else ""
    accent = _team_accent(team)
    sv = str(state_version if state_version is not None else dl_token)
    bl_attr = "" if board_len is None else f' data-board-len="{int(board_len)}"'

    # Inject card CSS once (style-only markdown is reliable).
    try:
        if not st.session_state.get("_solo_on_clock_css"):
            st.markdown(f"<style>{_ON_CLOCK_BANNER_CSS}</style>", unsafe_allow_html=True)
            st.session_state["_solo_on_clock_css"] = True
    except Exception:
        pass

    next_txt = (
        f'<div class="ld-next-pick">Your next pick: #{next_pick}</div>' if next_pick else ""
    )

    # Native Streamlit FIRST — fragment must never abort before these paint.
    st.caption(f"TIME REMAINING {rem}")

    # Single st.html mount: blue card + authoritative timer (no components.html).
    card = f"""
    <div class="live-draft-on-clock" style="border-left: 8px solid {accent};"
         data-live-draft-timer-root="1" data-timer-key="{timer_key}"
         data-testid="live-draft-on-clock"
         data-pick-index="{int(pick_index)}"
         data-room-id="{rid}"
         data-state-version="{sv}"{bl_attr}>
      <div class="ld-title">On the clock</div>
      <div class="ld-team-name" data-testid="live-draft-team">{team}</div>
      <div class="ld-pick-pills">
        <span class="ld-pill">Round {rnd}</span>
        <span class="ld-pill" data-testid="live-draft-pick"
              data-pick-index="{int(pick_index)}" data-pick-number="{pick_no}">Pick {pick_no}</span>
      </div>
      {next_txt}
      <div class="ld-meta">
        <span class="ld-clock-label">Time remaining</span>
        <span class="live-draft-timer" data-testid="live-draft-timer"
              data-timer-key="{timer_key}" data-authoritative="1"
              data-room-id="{rid}" data-pick-index="{int(pick_index)}"
              data-deadline-version="{dl_token}" data-deadline="{dl_attr}">{rem}</span>
      </div>
    </div>
    """
    html_ok = False
    try:
        st.html(card)
        html_ok = True
    except Exception as exc:
        try:
            st.session_state["_solo_st_html_err"] = f"{type(exc).__name__}: {exc}"[:160]
        except Exception:
            pass
    if not html_ok:
        try:
            st.html(
                f'<div data-testid="live-draft-on-clock" data-pick-index="{int(pick_index)}" '
                f'data-room-id="{rid}" data-state-version="{sv}"{bl_attr}>'
                f'<span data-testid="live-draft-team">{team}</span>'
                f'<span class="live-draft-timer" data-testid="live-draft-timer" '
                f'data-authoritative="1" data-timer-key="{timer_key}" '
                f'data-room-id="{rid}" data-pick-index="{int(pick_index)}" '
                f'data-deadline-version="{dl_token}" data-deadline="{dl_attr}">'
                f"{rem}</span></div>"
            )
            html_ok = True
        except Exception:
            pass
        st.markdown(f"**On the clock** — {team} · Round {rnd} · Pick {pick_no}")
    return html_ok


def _note_solo_expire_txn(payload: dict[str, Any]) -> None:
    try:
        from pathlib import Path
        import json as _json

        out = Path(__file__).resolve().parent / "data" / "tb_probe" / "solo_expire_txn.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _note_solo_fragment_lifecycle(payload: dict[str, Any]) -> None:
    """Append one lifecycle row per Solo timer fragment invocation."""
    try:
        from pathlib import Path
        import json as _json

        out = (
            Path(__file__).resolve().parent
            / "data"
            / "tb_probe"
            / "solo_fragment_lifecycle.jsonl"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _board_len_safe(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    board = room.get("draft_board")
    if isinstance(board, list):
        return len(board)
    try:
        return int(room.get("picks_made") or 0)
    except (TypeError, ValueError):
        return 0


def _solo_on_clock_fragment_tick() -> None:
    """Module-stable Solo timer body — reads only ``st.session_state``."""
    import streamlit as st

    session = st.session_state
    # Hard gate: never run expire/paint work when this ScriptRun/page is not
    # Live Draft Room. Stale ``run_every`` callbacks after leave/nav otherwise
    # spam Streamlit ("fragment does not exist") and can wedge the process.
    active_page = str(session.get("active_page") or session.get("nav_page") or "").strip()
    if active_page and active_page not in ("Live Draft Room", "Live Draft"):
        return
    if not bool(session.get(SOLO_SERVER_TIMER_ACTIVE_KEY)):
        # Fragment may still be scheduled from a prior mount; stay silent.
        if not isinstance(session.get("live_draft_room"), dict):
            return
        status = str((session.get("live_draft_room") or {}).get("status") or "")
        if status != "in_progress":
            return
    # keep_solo + mount both invoke this on full ScriptRuns; only paint once.
    if _solo_fragment_should_skip_duplicate_fullrun_paint(session):
        return

    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    _room_id = str(
        session.get("_solo_frag_room_id")
        or room.get("draft_room_id")
        or room.get("draft_id")
        or "solo"
    ).strip() or "solo"
    next_pick_view = session.get("_solo_frag_next_pick")
    slot_view = dict(session.get("_solo_frag_slot_view") or {})
    t_enter = time.time()
    seq = int(session.get(SOLO_FRAGMENT_LIFECYCLE_SEQ_KEY) or 0) + 1
    session[SOLO_FRAGMENT_LIFECYCLE_SEQ_KEY] = seq
    session[SOLO_TIMER_FRAGMENT_RUNS_KEY] = int(session.get(SOLO_TIMER_FRAGMENT_RUNS_KEY) or 0) + 1
    life: dict[str, Any] = {
        "seq": seq,
        "ts": t_enter,
        "fragment_run": int(session.get(SOLO_TIMER_FRAGMENT_RUNS_KEY) or 0),
        "room_id": _room_id,
        "session_has_room": isinstance(session.get("live_draft_room"), dict),
        "expired": False,
        "expire_ran": False,
        "full_rerun_called": False,
        "fragment_rerun_called": False,
        "markup_emitted": False,
        "returned_normally": False,
        "exception": None,
        "blank_return": False,
        "active_page": active_page,
    }
    tick_room = _resolve_live_room(session, room)
    life["disk_status"] = str((tick_room or {}).get("status") or "")
    life["active_room_id"] = str(
        (tick_room or {}).get("draft_room_id") or (tick_room or {}).get("draft_id") or ""
    )
    try:
        from live_draft_solo_timer import get_solo_display_snapshot, install_solo_display_snapshot
        from live_draft_timer_logic import live_draft_seconds_remaining
    except ImportError as exc:
        life["exception"] = f"import:{type(exc).__name__}"
        life["markup_emitted"] = bool(
            _render_solo_on_clock_card(
                st,
                slot_view or {"Team": "—", "Round": "—", "Pick": "—"},
                1,
                next_pick=next_pick_view if isinstance(next_pick_view, int) else None,
                pick_index=int((tick_room or {}).get("current_pick_index") or 0),
                deadline=None,
                room_id=_room_id,
                board_len=_board_len_safe(tick_room),
            )
        )
        life["returned_normally"] = True
        _note_solo_fragment_lifecycle(life)
        return

    pending = session.pop(SOLO_POST_EXPIRE_REFRESH_KEY, None)
    if pending is not None:
        session["_solo_needs_post_expire_board_sync"] = pending

    status = str(tick_room.get("status") or "")
    life["room_status"] = status
    life["pick_index"] = int(tick_room.get("current_pick_index") or 0)
    life["board_len"] = _board_len_safe(tick_room)
    life["team_on_clock"] = str(tick_room.get("on_clock_team") or "")
    life["deadline"] = tick_room.get("timer_deadline")
    life["state_version"] = str(
        tick_room.get("state_version") or tick_room.get("revision") or life["board_len"]
    )

    if status != "in_progress":
        paint_slot = _solo_slot_from_room(tick_room, fallback=slot_view)
        rem_done = int(live_draft_display_seconds(tick_room) or 0) if status == "paused" else 0
        life["remaining_seconds"] = rem_done
        life["markup_emitted"] = bool(
            _render_solo_on_clock_card(
                st,
                paint_slot,
                rem_done,
                next_pick=next_pick_view if isinstance(next_pick_view, int) else None,
                pick_index=int(tick_room.get("current_pick_index") or 0),
                deadline=None,
                room_id=_room_id,
                state_version=life["state_version"],
                board_len=life["board_len"],
            )
        )
        if status == "paused":
            st.caption("Draft paused — timer stopped")
        elif status in ("complete", "completed", "finished"):
            st.caption("Draft complete")
        else:
            st.caption(f"Draft status: {status or '—'}")
        life["returned_normally"] = True
        _note_solo_fragment_lifecycle(life)
        return

    now = time.time()
    dl = live_draft_timer_deadline(tick_room)
    pidx = int(tick_room.get("current_pick_index") or 0)
    life["pick_index"] = pidx
    life["deadline"] = dl
    npick = next_pick_view if isinstance(next_pick_view, int) else None

    # Optional durability poke: force deadline into the past once per token.
    try:
        poke_path = (
            Path(__file__).resolve().parent / "data" / "tb_probe" / "force_expire_poke.json"
        )
        if poke_path.is_file():
            poke = json.loads(poke_path.read_text(encoding="utf-8"))
            token = str(poke.get("token") or "").strip()
            if token and token != str(session.get("_solo_force_expire_token") or ""):
                session["_solo_force_expire_token"] = token
                tick_room["timer_deadline"] = time.time() - 0.5
                session["live_draft_room"] = tick_room
                dl = live_draft_timer_deadline(tick_room)
                life["deadline"] = dl
                life["force_expire_poke"] = token
    except Exception:
        pass

    if dl is None:
        try:
            from live_draft_timer_logic import ensure_live_draft_timer_for_pick

            ensure_live_draft_timer_for_pick(tick_room, live_board_ready=True)
            session["live_draft_room"] = tick_room
            dl = live_draft_timer_deadline(tick_room)
            life["deadline"] = dl
        except Exception as exc:
            life["exception"] = f"arm:{type(exc).__name__}:{exc}"[:160]
        seed = int(
            tick_room.get("timer_seconds") or tick_room.get("pick_timer_seconds") or 60
        )
        paint_slot = _solo_slot_from_room(tick_room, fallback=slot_view)
        life["remaining_seconds"] = (
            seed if dl is None else int(max(0, math.ceil(float(dl) - time.time())))
        )
        life["team_on_clock"] = str(paint_slot.get("Team") or "")
        life["markup_emitted"] = bool(
            _render_solo_on_clock_card(
                st,
                paint_slot,
                life["remaining_seconds"] or seed,
                next_pick=npick,
                pick_index=pidx,
                deadline=float(dl) if dl is not None else None,
                room_id=_room_id,
                state_version=life["state_version"],
                board_len=life["board_len"],
            )
        )
        if dl is None:
            st.caption("Starting pick clock…")
        life["returned_normally"] = True
        _note_solo_fragment_lifecycle(life)
        return

    rem = int(max(0, math.ceil(float(dl) - now)))
    life["remaining_seconds"] = rem
    expired = now >= (float(dl) - 0.15)
    life["expired"] = bool(expired)

    if expired:
        t_detect = time.time()
        guard = f"{_room_id}|{pidx}|{float(dl):.3f}"
        txn: dict[str, Any] = {
            "deadline_detected": t_detect,
            "pick_index_before": pidx,
            "deadline_before": float(dl),
            "guard": guard,
            "fragment_run": int(session.get(SOLO_TIMER_FRAGMENT_RUNS_KEY) or 0),
            "lifecycle_seq": seq,
        }
        already = session.get(SOLO_EXPIRE_GUARD_KEY) == guard
        if already:
            txn["expire_skipped"] = "guard_hit"
        else:
            try:
                from live_draft_solo_heartbeat import run_solo_expire_tick

                txn["expire_handler_entry"] = time.time()
                result = run_solo_expire_tick(st, session, source="solo_banner_fragment")
                txn["expire_handler_return"] = time.time()
                life["expire_ran"] = True
                txn["expire_ok"] = bool(getattr(result, "ok", False))
                txn["expire_advanced"] = bool(getattr(result, "advanced", False))
                txn["expire_ms"] = round(
                    (float(txn["expire_handler_return"]) - float(txn["expire_handler_entry"]))
                    * 1000.0,
                    2,
                )
                if txn["expire_advanced"] or bool(getattr(result, "complete", False)):
                    session[SOLO_EXPIRE_GUARD_KEY] = guard
                    session["_solo_warm_next_plan_pending"] = True
                    session.pop("_solo_warm_paint_done_for", None)
                    session.pop("_solo_warm_plan_for_pick", None)
            except Exception as exc:
                txn["expire_error"] = f"{type(exc).__name__}: {exc}"[:160]
                life["exception"] = txn["expire_error"]

        tick_room = _resolve_live_room(session, room)
        if txn.get("expire_advanced"):
            session["_solo_schedule_warm"] = True
            try:
                from live_draft_autopick import invalidate_autopick_warm_for_room

                invalidate_autopick_warm_for_room(tick_room)
            except Exception:
                pass
        install_solo_display_snapshot(session, tick_room)
        snap = get_solo_display_snapshot(session, tick_room)
        rem_next = int(live_draft_seconds_remaining(tick_room))
        if snap.get("remaining_seconds") is not None:
            try:
                rem_next = int(snap.get("remaining_seconds"))
            except (TypeError, ValueError):
                pass
        dl_next = snap.get("timer_deadline")
        if dl_next is None:
            dl_next = live_draft_timer_deadline(tick_room)
        if dl_next is not None:
            dl_next = float(dl_next)
        pidx_next = int(
            snap.get("pick_index")
            if snap.get("pick_index") is not None
            else (tick_room.get("current_pick_index") or 0)
        )
        slot_next = _solo_slot_from_room(tick_room, fallback=slot_view, snap=snap)
        board_next = _board_len_safe(tick_room)
        state_ver = str(tick_room.get("state_version") or tick_room.get("revision") or board_next)
        txn["pick_index_after"] = pidx_next
        txn["deadline_after"] = dl_next
        txn["remaining_after"] = rem_next
        txn["next_deadline_created"] = time.time()
        prof = session.get("_live_draft_last_autopick_profile") or {}
        if not prof and isinstance(tick_room, dict):
            prof = dict(tick_room.get("_last_autopick_profile") or {})
        warm = dict(prof.get("warm") or {})
        txn["warm_plan_hit"] = bool(
            warm.get("warm_hit") or session.get("_live_draft_autopick_used_warm_cache")
        )
        txn["warm_meta"] = warm
        txn["autopick_stages_ms"] = dict(prof.get("stages_ms") or {})
        txn["autopick_total_ms"] = prof.get("total_ms")
        txn["warm_miss_full_score"] = bool(prof.get("warm_miss_full_score"))
        txn["autopick_player"] = prof.get("player")
        _note_solo_expire_txn(txn)

        if rem_next <= 1 and pidx_next == pidx:
            paint_rem = max(
                1,
                int(tick_room.get("timer_seconds") or tick_room.get("pick_timer_seconds") or 1),
            )
            st.caption("Advancing pick…")
        else:
            paint_rem = rem_next if rem_next > 1 else int(
                tick_room.get("timer_seconds") or tick_room.get("pick_timer_seconds") or 60
            )
        life["pick_index"] = pidx_next
        life["deadline"] = dl_next
        life["remaining_seconds"] = paint_rem
        life["board_len"] = board_next
        life["team_on_clock"] = str(slot_next.get("Team") or "")
        life["state_version"] = state_ver
        life["markup_emitted"] = bool(
            _render_solo_on_clock_card(
                st,
                slot_next,
                paint_rem,
                next_pick=npick,
                pick_index=pidx_next,
                deadline=dl_next,
                room_id=_room_id,
                state_version=state_ver,
                board_len=board_next,
            )
        )
        session[SOLO_POST_EXPIRE_REFRESH_KEY] = f"{pidx_next}|{dl_next}|{time.time():.3f}"
        # Do NOT launch warm on the expire tick itself — even a short GIL burst
        # plus schedule bookkeeping races the next paint flush. Mark pending and
        # let a later non-expire tick schedule after the new pick has painted.
        if rem_next >= 5:
            session["_solo_schedule_warm"] = True
            session["_solo_warm_schedule_after_paints"] = 3
            session["_solo_warm_schedule_pick"] = pidx_next
        life["returned_normally"] = True
        _note_solo_fragment_lifecycle(life)
        return

    install_solo_display_snapshot(session, tick_room)
    snap = get_solo_display_snapshot(session, tick_room)
    rem = int(max(0, math.ceil(float(dl) - time.time())))
    if snap.get("remaining_seconds") is not None:
        try:
            rem = max(rem, int(snap.get("remaining_seconds")))
        except (TypeError, ValueError):
            pass
    rem = max(1, rem)
    if snap.get("timer_deadline") is not None:
        try:
            dl = float(snap["timer_deadline"])
        except (TypeError, ValueError):
            pass
    pidx = int(snap.get("pick_index") if snap.get("pick_index") is not None else pidx)
    tick_slot = _solo_slot_from_room(tick_room, fallback=slot_view, snap=snap)
    board_len = _board_len_safe(tick_room)
    state_ver = str(tick_room.get("state_version") or tick_room.get("revision") or board_len)
    life["pick_index"] = pidx
    life["deadline"] = dl
    life["remaining_seconds"] = rem
    life["board_len"] = board_len
    life["team_on_clock"] = str(tick_slot.get("Team") or "")
    life["state_version"] = state_ver
    life["markup_emitted"] = bool(
        _render_solo_on_clock_card(
            st,
            tick_slot,
            rem,
            next_pick=npick,
            pick_index=pidx,
            deadline=float(dl) if dl is not None else None,
            room_id=_room_id,
            state_version=state_ver,
            board_len=board_len,
        )
    )
    # After the new pick has painted a few times, schedule exactly one warm worker.
    if session.get("_solo_schedule_warm") and int(session.get("_solo_warm_schedule_pick") or -1) == pidx:
        left = int(session.get("_solo_warm_schedule_after_paints") or 0) - 1
        session["_solo_warm_schedule_after_paints"] = left
        if left <= 0:
            session.pop("_solo_schedule_warm", None)
            session.pop("_solo_warm_schedule_after_paints", None)
            if int(session.get("_solo_warm_scheduled_for") or -999) != pidx:
                session["_solo_warm_scheduled_for"] = pidx
                try:
                    from live_draft_autopick import schedule_autopick_warm_plan

                    schedule_autopick_warm_plan(tick_room)
                except Exception:
                    pass
    elif (
        int(session.get("_solo_warm_scheduled_for") or -999) != pidx
        and rem >= 5
        and not session.get("_solo_schedule_warm")
    ):
        # First pick after Start: arm warm after a few paints (expire path not yet run).
        session["_solo_schedule_warm"] = True
        session["_solo_warm_schedule_after_paints"] = 2
        session["_solo_warm_schedule_pick"] = pidx
    life["returned_normally"] = True
    _note_solo_fragment_lifecycle(life)


def _solo_slot_from_room(
    tick_room: dict[str, Any],
    *,
    fallback: dict[str, Any] | None = None,
    snap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slot = dict(fallback or {})
    snap = snap or {}
    if snap.get("team"):
        slot["Team"] = snap.get("team")
    if snap.get("pick_number") is not None:
        slot["Pick"] = snap.get("pick_number")
    try:
        cur = live_draft_current_slot(tick_room) or {}
        if cur.get("Pick") is not None:
            slot["Pick"] = cur.get("Pick")
        if cur.get("Team"):
            slot["Team"] = cur.get("Team")
        if cur.get("Round") is not None:
            slot["Round"] = cur.get("Round")
    except Exception:
        pass
    return slot


def _emit_banner_html(
    st: Any,
    html: str,
    *,
    height: int = 210,
    deadline: float | None = None,
    timer_id: str = "",
    timer_key: str = "",
    server_driven: bool = False,
) -> None:
    """Shared Draft: banner + client JS countdown in one iframe.

    Solo must not use this path — see ``_emit_solo_server_timer_markup``.
    ``server_driven`` is ignored (legacy); callers should use Solo markup helpers.
    """
    del server_driven, timer_key  # Solo no longer remounts iframes / ghost-cleans.
    banner_css = _ON_CLOCK_BANNER_CSS
    try:
        import streamlit.components.v1 as components

        countdown_script = ""
        if deadline is not None and timer_id:
            countdown_script = f"""
            <script>
            (function() {{
              const deadline = {float(deadline)};
              const el = document.getElementById("{timer_id}");
              function tick() {{
                const rem = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
                if (el) el.textContent = String(rem);
                if (rem <= 0) return;
                window.setTimeout(tick, 250);
              }}
              tick();
            }})();
            </script>
            """
        components.html(
            f"""
            <style>{banner_css}</style>
            {html}
            {countdown_script}
            """,
            height=height,
        )
        return
    except Exception:
        pass
    try:
        st.html(html)
        return
    except Exception:
        pass
    st.markdown(html, unsafe_allow_html=True)


def _render_on_clock_banner_html(
    st: Any,
    slot: dict[str, Any],
    remaining: int,
    *,
    next_pick: int | None = None,
    pick_index: int = 0,
    deadline: float | None = None,
    flash: bool = False,
    server_driven: bool = False,
    room_id: str = "",
) -> None:
    """Shared Draft iframe banner. Solo callers should use ``_render_solo_on_clock_card``."""
    del server_driven  # Solo no longer uses components.html via this helper.
    team = slot.get("Team", "—")
    rnd = slot.get("Round", "—")
    pick_no = slot.get("Pick", "—")
    next_txt = f'<div class="ld-next-pick">Your next pick: #{next_pick}</div>' if next_pick else ""
    accent = _team_accent(str(team))
    timer_id = f"ld-banner-timer-{pick_index}"
    seed = max(0, int(remaining))
    dl_token = f"{float(deadline):.3f}" if deadline is not None else "none"
    rid = str(room_id or "solo").strip() or "solo"
    timer_key = f"{rid}|{int(pick_index)}|{dl_token}"
    timer_html = (
        f'<span id="{timer_id}" class="live-draft-timer" '
        f'data-testid="live-draft-timer" data-timer-key="{timer_key}" '
        f'data-authoritative="1" data-pick-index="{int(pick_index)}">{seed}</span>'
        if deadline is not None
        else (
            f'<span class="live-draft-timer" data-testid="live-draft-timer" '
            f'data-timer-key="{timer_key}" data-authoritative="1">{seed}</span>'
        )
    )
    flash_class = " ld-on-clock-flash" if flash else ""
    html = f"""
        <div class="live-draft-on-clock{flash_class}" style="border-left: 8px solid {accent};"
             data-live-draft-timer-root="1" data-timer-key="{timer_key}">
            <div class="ld-title">On the clock</div>
            <div class="ld-team-name">{team}</div>
            <div class="ld-pick-pills">
                <span class="ld-pill">Round {rnd}</span>
                <span class="ld-pill">Pick {pick_no}</span>
            </div>
            {next_txt}
            <div class="ld-meta">
                <span class="ld-clock-label">Time remaining</span>
                {timer_html}
            </div>
        </div>
        """
    _emit_banner_html(
        st,
        html,
        height=220 if next_pick else 190,
        deadline=float(deadline) if deadline is not None else None,
        timer_id=timer_id if deadline is not None else "",
        timer_key=timer_key,
    )


def _emit_primary_auto_picking_status(st: Any, session: dict[str, Any]) -> None:
    """Single authoritative Auto-picking label for the On-the-Clock area."""
    count = int(session.get("visible_auto_picking_status_count") or 0) + 1
    session["visible_auto_picking_status_count"] = count
    session["_live_draft_timer_autopick_ui"] = True
    st.caption("Auto-picking…")
    if bool(session.get("developer_mode") or session.get("_developer_mode")) and count != 1:
        st.caption(f"Dev assert: visible_auto_picking_status_count == {count} (expected 1)")


def render_live_on_clock_banner(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    slot: dict[str, Any],
    *,
    next_pick: int | None = None,
) -> None:
    """Render blue On-the-Clock banner with client-side 1 Hz countdown."""
    try:
        from pathlib import Path
        import json as _json

        _probe = (
            Path(__file__).resolve().parent
            / "data"
            / "tb_probe"
            / "on_clock_banner_enter.json"
        )
        _probe.parent.mkdir(parents=True, exist_ok=True)
        live = room if isinstance(room, dict) else {}
        _probe.write_text(
            _json.dumps(
                {
                    "ts": time.time(),
                    "status": live.get("status"),
                    "pick_index": live.get("current_pick_index"),
                    "deadline": live.get("timer_deadline"),
                    "slot_pick": (slot or {}).get("Pick") if isinstance(slot, dict) else None,
                    "solo_early": bool(session.get("_live_draft_solo_early_timer_painted")),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    # Reset per full-page paint; fragment ticks may increment once more.
    session["visible_auto_picking_status_count"] = 0
    # Never skip the on-clock banner for an active pick — fragment_allowed=False used
    # to silent-return and leave Solo Draft with zero visible timers during heavy paint.
    _fragments_ok = True
    try:
        from app_page_generation import fragment_allowed

        _fragments_ok = bool(fragment_allowed(session, expected_page="Live Draft Room"))
    except ImportError:
        _fragments_ok = True
    if not isinstance(slot, dict):
        return
    try:
        from live_draft_ux_latency import mark_ux_milestone
    except ImportError:
        mark_ux_milestone = None  # type: ignore[assignment]
    if mark_ux_milestone:
        mark_ux_milestone(session, "on_clock_paint_start", rebuild="on_clock", st=st)

    live_room = _resolve_live_room(session, room)
    try:
        from live_draft_canonical_snapshot import get_live_draft_paint_snapshot, render_canonical_diag_line

        canon = get_live_draft_paint_snapshot(session)
        if isinstance(slot, dict) and canon.get("team_on_clock"):
            slot = dict(slot)
            slot["Team"] = canon["team_on_clock"]
            if canon.get("current_pick") is not None:
                slot["Pick"] = canon["current_pick"]
            if canon.get("round") is not None:
                slot["Round"] = canon["round"]
        pick_idx = int(
            canon.get("current_pick_index")
            if canon.get("current_pick_index") is not None
            else live_room.get("current_pick_index") or 0
        )
        render_canonical_diag_line(st, session, label="On the Clock")
    except ImportError:
        pick_idx = int(live_room.get("current_pick_index") or 0)
    slot_view = dict(slot) if isinstance(slot, dict) else {}
    next_pick_view = next_pick
    try:
        from live_draft_ux import on_clock_should_flash

        clock_flash = on_clock_should_flash(session, pick_idx)
    except ImportError:
        clock_flash = False

    def _mark_on_clock_done() -> None:
        if mark_ux_milestone:
            mark_ux_milestone(session, "on_clock_paint_done", rebuild="on_clock", st=st)

    _solo_early = False
    try:
        from live_draft_solo_timer import is_solo_live_draft, record_visible_timer_count

        _solo_early = bool(is_solo_live_draft(session, live_room))
        record_visible_timer_count(session, 1)
    except ImportError:
        pass

    if str(live_room.get("status") or "") == "paused":
        remaining = live_draft_display_seconds(live_room)
        if _solo_early:
            _render_solo_on_clock_card(
                st,
                slot_view,
                remaining,
                next_pick=next_pick_view,
                pick_index=pick_idx,
                deadline=None,
                flash=clock_flash,
                room_id=str(live_room.get("draft_room_id") or live_room.get("draft_id") or "solo"),
            )
        else:
            _render_on_clock_banner_html(
                st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=None, flash=clock_flash
            )
        st.caption("Draft paused — timer stopped")
        _mark_on_clock_done()
        return

    try:
        from live_draft_pick_timer import display_seconds_with_freeze, frozen_deadline, is_pick_submitting

        if is_pick_submitting(session):
            remaining = display_seconds_with_freeze(session, live_room)
            deadline = frozen_deadline(session, live_room)
            if _solo_early:
                _render_solo_on_clock_card(
                    st,
                    slot_view,
                    remaining,
                    next_pick=next_pick_view,
                    pick_index=pick_idx,
                    deadline=deadline,
                    flash=clock_flash,
                    room_id=str(live_room.get("draft_room_id") or live_room.get("draft_id") or "solo"),
                )
            else:
                _render_on_clock_banner_html(
                    st, slot_view, remaining, next_pick=next_pick_view, pick_index=pick_idx, deadline=deadline, flash=clock_flash
                )
            st.caption("Submitting pick…")
            _mark_on_clock_done()
            return
    except ImportError:
        pass

    deadline = live_draft_timer_deadline(live_room)
    record_timer_diagnostics(
        session,
        live_room,
        source="on_clock_banner_render",
    )
    if session.get("_live_draft_timer_diag"):
        diag = dict(session["_live_draft_timer_diag"])
        diag["timer_component_mounted"] = deadline is not None
        diag["timer_component_last_render"] = time.time()
        session["_live_draft_timer_diag"] = diag

    use_fragment = False
    try:
        from live_draft_safe_mode import is_draft_truly_complete, timer_should_run

        use_fragment = (
            _fragments_ok
            and timer_should_run(session, live_room)
            and not is_draft_truly_complete(live_room)
        )
    except ImportError:
        use_fragment = _fragments_ok and live_room.get("status") == "in_progress"

    remaining_now = live_draft_display_seconds(live_room)

    _solo_draft = False
    try:
        from live_draft_solo_timer import (
            get_solo_display_snapshot,
            install_solo_display_snapshot,
            is_solo_live_draft,
        )

        _solo_draft = bool(is_solo_live_draft(session, live_room))
    except ImportError:
        _solo_draft = False

    # Solo: one server-driven fragment + ordinary HTML markup (no components.html).
    # Deadline is the only clock authority. Zero is an event: expire before paint,
    # then render the NEW pick at full clock — never sit on TIME REMAINING 0.
    if _solo_draft and use_fragment and deadline is not None:
        session[SOLO_SERVER_TIMER_ACTIVE_KEY] = True
        try:
            fragment = st.fragment
        except AttributeError:
            fragment = None
        if fragment is not None:
            _room_id = str(
                live_room.get("draft_room_id")
                or live_room.get("draft_id")
                or live_room.get("id")
                or "solo"
            ).strip() or "solo"
            mount_solo_on_clock_fragment(
                st,
                session,
                room_id=_room_id,
                next_pick=next_pick_view,
                slot_view=slot_view,
            )
            _mark_on_clock_done()
            return

    # Solo fallback: one-shot markdown paint (no fragment support).
    if _solo_draft and deadline is not None:
        try:
            from live_draft_solo_timer import get_solo_display_snapshot, install_solo_display_snapshot

            install_solo_display_snapshot(session, live_room)
            snap = get_solo_display_snapshot(session, live_room)
            remaining_now = int(snap.get("remaining_seconds") or remaining_now)
            if snap.get("timer_deadline") is not None:
                deadline = float(snap["timer_deadline"])
            # Never paint a sticky 0 for Solo static path — still emit the wrapper.
            paint_rem = max(1, int(remaining_now)) if remaining_now > 0 else max(
                1,
                int(
                    live_room.get("timer_seconds")
                    or live_room.get("pick_timer_seconds")
                    or 1
                ),
            )
            if remaining_now <= 0:
                st.caption("Advancing pick…")
            _render_solo_on_clock_card(
                st,
                slot_view,
                paint_rem,
                next_pick=next_pick_view,
                pick_index=pick_idx,
                deadline=deadline,
                flash=clock_flash,
                room_id=str(
                    live_room.get("draft_room_id")
                    or live_room.get("draft_id")
                    or "solo"
                ),
                board_len=_board_len_safe(live_room),
            )
            _mark_on_clock_done()
            return
        except ImportError:
            pass

    if not use_fragment or deadline is None:
        # in_progress with no deadline: try one arm before painting so Solo does not
        # show a fake full-clock seed without JS. If still unarmed, show a preparing
        # caption rather than a stuck numeric clock.
        if deadline is None and str(live_room.get("status") or "") == "in_progress":
            try:
                from live_draft_timer_logic import ensure_live_draft_timer_for_pick

                ensure_live_draft_timer_for_pick(live_room, live_board_ready=True)
                deadline = live_draft_timer_deadline(live_room)
                remaining_now = live_draft_display_seconds(live_room)
                session["live_draft_room"] = live_room
            except ImportError:
                pass
        if deadline is None and str(live_room.get("status") or "") == "in_progress":
            # Still unarmed (rare) — visible preparing state, not a frozen 60/30.
            st.info("Starting pick clock…")
            _mark_on_clock_done()
            return
        _render_on_clock_banner_html(
            st,
            slot_view,
            remaining_now,
            next_pick=next_pick_view,
            pick_index=pick_idx,
            deadline=deadline,
            flash=clock_flash,
        )
        if (
            int(remaining_now or 0) <= 0
            and str(live_room.get("status") or "") == "in_progress"
        ):
            _emit_primary_auto_picking_status(st, session)
        _mark_on_clock_done()
        return

    try:
        fragment = st.fragment
    except AttributeError:
        _render_on_clock_banner_html(
            st,
            slot_view,
            remaining_now,
            next_pick=next_pick_view,
            pick_index=pick_idx,
            deadline=deadline,
            flash=clock_flash,
        )
        if (
            int(remaining_now or 0) <= 0
            and str(live_room.get("status") or "") == "in_progress"
        ):
            _emit_primary_auto_picking_status(st, session)
        _mark_on_clock_done()
        return

    @fragment(run_every=1)
    def _banner_tick() -> None:
        try:
            from live_draft_rerun_scope import mark_live_draft_timer_tick

            mark_live_draft_timer_tick(session)
        except ImportError:
            pass
        # Keep banner on the same authoritative deadline as Draft Control Center.
        try:
            from live_draft_timer_ui import _sync_room_on_timer_tick

            tick_room, _changed = _sync_room_on_timer_tick(session, room)
        except Exception:
            tick_room = _resolve_live_room(session, room)
        try:
            from live_draft_canonical_snapshot import get_live_draft_paint_snapshot

            paint = get_live_draft_paint_snapshot(session)
            tick_idx = int(paint.get("current_pick_index") or pick_idx)
            tick_deadline = paint.get("timer_deadline")
            if paint.get("timer_remaining") is not None:
                remaining = int(paint.get("timer_remaining") or 0)
            else:
                remaining = live_draft_display_seconds(tick_room)
            on_clock = str(paint.get("team_on_clock") or "").strip()
            tick_slot = dict(slot_view)
            if on_clock:
                tick_slot["Team"] = on_clock
            if paint.get("current_pick") is not None:
                tick_slot["Pick"] = paint.get("current_pick")
            if paint.get("round") is not None:
                tick_slot["Round"] = paint.get("round")
        except ImportError:
            try:
                from shared_live_draft_snapshot import build_shared_live_draft_snapshot
                from live_draft_canonical_snapshot import (
                    align_room_pick_index,
                    install_canonical_live_draft_snapshot,
                )

                snap = build_shared_live_draft_snapshot(session, room=tick_room)
                align_room_pick_index(tick_room)
                install_canonical_live_draft_snapshot(session, tick_room, state_source="shared_fallback_sync")
                session["_live_draft_shared_fallback_paint"] = dict(snap)
                tick_idx = int(snap.get("current_pick_index") or pick_idx)
                tick_deadline = snap.get("turn_deadline")
                remaining = snap.get("seconds_remaining")
                if remaining is None:
                    remaining = live_draft_display_seconds(tick_room)
                on_clock = str(snap.get("on_clock_team") or "").strip()
                tick_slot = dict(slot_view)
                if on_clock:
                    tick_slot["Team"] = on_clock
                if snap.get("current_pick") is not None:
                    tick_slot["Pick"] = snap.get("current_pick")
            except ImportError:
                tick_slot = live_draft_current_slot(tick_room) or slot_view
                tick_deadline = live_draft_timer_deadline(tick_room)
                tick_idx = int(tick_room.get("current_pick_index") or pick_idx)
                remaining = live_draft_display_seconds(tick_room)
        # When at zero: Solo fragment/banner installs next pick+full timer in-place.
        # Shared rooms still poll; page/timer-authority owns multiparty CAS.
        try:
            from live_draft_timer_logic import live_draft_timer_expired_for_pick

            if live_draft_timer_expired_for_pick(tick_room):
                try:
                    from live_draft_solo_timer import (
                        expire_current_pick_and_advance,
                        is_solo_live_draft,
                        note_solo_fragment_owned_expire,
                    )

                    if is_solo_live_draft(session, tick_room):
                        note_solo_fragment_owned_expire(session)
                        result = expire_current_pick_and_advance(
                            tick_room, session=session, request_full_rerun=False
                        )
                        tick_room = _resolve_live_room(session, tick_room)
                        if result.display is not None:
                            tick_idx = int(result.display.pick_index)
                            tick_deadline = result.display.timer_deadline
                            remaining = int(result.display.remaining_seconds)
                            tick_slot = dict(tick_slot)
                            tick_slot["Team"] = result.display.team or tick_slot.get("Team")
                            tick_slot["Pick"] = result.display.pick_number
                        else:
                            tick_slot = live_draft_current_slot(tick_room) or tick_slot
                            tick_deadline = live_draft_timer_deadline(tick_room)
                            tick_idx = int(tick_room.get("current_pick_index") or tick_idx)
                            remaining = live_draft_display_seconds(tick_room)
                        session["_live_draft_solo_board_stale"] = True
                        if result.ok and (result.advanced or result.complete):
                            try:
                                from live_draft_canonical_snapshot import (
                                    align_room_pick_index,
                                    begin_live_draft_paint,
                                    invalidate_live_draft_paint,
                                    note_action_timing,
                                )

                                invalidate_live_draft_paint(session)
                                tick_room = _resolve_live_room(session, tick_room)
                                align_room_pick_index(tick_room)
                                begin_live_draft_paint(session, tick_room, state_source="solo_expire_fragment")
                                note_action_timing(
                                    session,
                                    "solo_expire_fragment",
                                    zero_to_commit_ms=result.zero_to_commit_ms,
                                    team_after=result.team_on_clock,
                                )
                            except ImportError:
                                pass
                            try:
                                from live_draft_safe_mode import request_live_draft_rerun

                                request_live_draft_rerun(st, session, "solo_expire", room=tick_room)
                            except Exception:
                                st.rerun()
                    else:
                        # Shared: poll fragment owns room sync. Banner never force-loads
                        # the full shared_room_json on a schedule.
                        if not session.get("_live_draft_poll_fragment_active"):
                            try:
                                from draft_room_context import (
                                    poll_shared_draft_room,
                                    reset_shared_draft_sync_gate,
                                )

                                reset_shared_draft_sync_gate(session)
                                changed = bool(poll_shared_draft_room(session, force=False))
                                session["_live_draft_on_clock_zero_diag"] = {
                                    "force_poll": False,
                                    "poll_changed": changed,
                                    "ts": time.time(),
                                }
                            except Exception as exc:
                                session["_live_draft_on_clock_zero_diag"] = {
                                    "poll_error": f"{type(exc).__name__}: {exc}"[:160],
                                }
                        tick_room = _resolve_live_room(session, tick_room)
                        try:
                            from shared_live_draft_snapshot import build_shared_live_draft_snapshot
                            from live_draft_canonical_snapshot import (
                                align_room_pick_index,
                                install_canonical_live_draft_snapshot,
                            )

                            snap = build_shared_live_draft_snapshot(session, room=tick_room)
                            align_room_pick_index(tick_room)
                            install_canonical_live_draft_snapshot(
                                session, tick_room, state_source="shared_fallback_poll"
                            )
                            session["_live_draft_shared_fallback_paint"] = dict(snap)
                            tick_idx = int(snap.get("current_pick_index") or tick_idx)
                            tick_deadline = snap.get("turn_deadline")
                            remaining = snap.get("seconds_remaining")
                            if remaining is None:
                                remaining = live_draft_display_seconds(tick_room)
                            on_clock = str(snap.get("on_clock_team") or "").strip()
                            if on_clock:
                                tick_slot = dict(tick_slot)
                                tick_slot["Team"] = on_clock
                            if snap.get("current_pick") is not None:
                                tick_slot = dict(tick_slot)
                                tick_slot["Pick"] = snap.get("current_pick")
                        except ImportError:
                            remaining = live_draft_display_seconds(tick_room)
                            tick_deadline = live_draft_timer_deadline(tick_room)
                except ImportError:
                    remaining = live_draft_display_seconds(tick_room)
                    tick_deadline = live_draft_timer_deadline(tick_room)
        except Exception as exc:
            session["_live_draft_on_clock_zero_diag"] = {
                **dict(session.get("_live_draft_on_clock_zero_diag") or {}),
                "banner_zero_error": f"{type(exc).__name__}: {exc}"[:160],
            }
        record_timer_diagnostics(session, tick_room, source="on_clock_banner_tick")
        if session.get("_live_draft_timer_diag"):
            diag = dict(session["_live_draft_timer_diag"])
            diag["timer_component_mounted"] = tick_deadline is not None
            diag["timer_component_last_render"] = time.time()
            session["_live_draft_timer_diag"] = diag
        try:
            from live_draft_solo_timer import record_visible_timer_count

            record_visible_timer_count(session, 1)
        except ImportError:
            pass
        try:
            from live_draft_solo_heartbeat import shared_banner_should_repaint

            force_repaint = int(remaining or 0) <= 0 and str(tick_room.get("status") or "") == "in_progress"
            if shared_banner_should_repaint(
                session,
                pick_index=tick_idx,
                deadline=float(tick_deadline) if tick_deadline is not None else None,
                force=force_repaint,
            ):
                try:
                    from live_draft_cloud_diagnostics import note_fragment_owner, render_surface_stamp

                    note_fragment_owner(session, "shared_on_clock_banner", delta=1)
                    render_surface_stamp(
                        st,
                        session,
                        component="on_clock_banner",
                        render_owner="shared_banner_fragment",
                        room=tick_room,
                        fragment_id="shared-banner",
                        extra={"remaining": int(remaining or 0)},
                    )
                except ImportError:
                    pass
                _render_on_clock_banner_html(
                    st,
                    tick_slot,
                    int(remaining or 0),
                    next_pick=next_pick_view,
                    pick_index=tick_idx,
                    deadline=tick_deadline,
                    flash=False,
                )
        except ImportError:
            _render_on_clock_banner_html(
                st,
                tick_slot,
                int(remaining or 0),
                next_pick=next_pick_view,
                pick_index=tick_idx,
                deadline=tick_deadline,
                flash=False,
            )
        if (
            int(remaining or 0) <= 0
            and str(tick_room.get("status") or "") == "in_progress"
        ):
            # Fragment re-paint: keep a single Auto-picking caption under On-the-Clock.
            session["visible_auto_picking_status_count"] = 0
            _emit_primary_auto_picking_status(st, session)

    _banner_tick()
    _mark_on_clock_done()
