"""Admin-only Live Draft Cloud diagnostics — render stamps and action timing."""

from __future__ import annotations

import threading
import time
from typing import Any

RUN_SEQ_KEY = "_live_draft_cloud_diag_run_seq"
RUN_LOG_KEY = "_live_draft_cloud_diag_run_log"
ACTION_LOG_KEY = "_live_draft_cloud_action_timing_log"
FRAGMENT_OWNERS_KEY = "_live_draft_fragment_owner_counts"
SOLO_NO_FRAGMENT_KEY = "_live_draft_solo_no_fragment_mode"
CANARY_MODE_KEY = "_live_draft_cloud_canary_mode"
MAX_LOG = 120


def _admin_ok(st: Any | None = None) -> bool:
    try:
        from suite_workspace import can_show_developer_tools

        return bool(can_show_developer_tools(st=st))
    except Exception:
        return False


def note_fragment_owner(session: dict[str, Any], owner: str, *, delta: int = 1) -> None:
    counts = dict(session.get(FRAGMENT_OWNERS_KEY) or {})
    counts[str(owner)] = int(counts.get(str(owner), 0)) + int(delta)
    session[FRAGMENT_OWNERS_KEY] = counts


def fragment_owner_summary(session: dict[str, Any]) -> str:
    counts = session.get(FRAGMENT_OWNERS_KEY) or {}
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def solo_no_fragment_mode(session: dict[str, Any]) -> bool:
    return bool(session.get(SOLO_NO_FRAGMENT_KEY) or session.get(CANARY_MODE_KEY))


def enable_solo_no_fragment_mode(session: dict[str, Any], *, enabled: bool = True) -> None:
    if enabled:
        session[SOLO_NO_FRAGMENT_KEY] = True
    else:
        session.pop(SOLO_NO_FRAGMENT_KEY, None)


def solo_skip_remote_poll(session: dict[str, Any]) -> bool:
    """Solo active drafts must not poll Supabase on a timer tick cadence."""
    try:
        from live_draft_solo_timer import is_solo_live_draft

        room = session.get("live_draft_room")
        if is_solo_live_draft(session, room if isinstance(room, dict) else None) and isinstance(room, dict):
            if str(room.get("status") or "") in ("in_progress", "paused"):
                return True
    except ImportError:
        pass
    return False


def cloud_canary_requested(st: Any, session: dict[str, Any]) -> bool:
    if session.get(CANARY_MODE_KEY):
        return True
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            raw = qp.get("ld_canary")
            if raw is not None and str(raw).strip().lower() in ("1", "true", "yes", "on"):
                session[CANARY_MODE_KEY] = True
                return True
    except Exception:
        pass
    return False


def begin_run(session: dict[str, Any], *, source: str = "page") -> dict[str, Any]:
    seq = int(session.get(RUN_SEQ_KEY) or 0) + 1
    session[RUN_SEQ_KEY] = seq
    ctx = {
        "seq": seq,
        "source": str(source),
        "started_at": time.time(),
        "started_perf": time.perf_counter(),
        "thread": threading.current_thread().name,
        "db_calls": 0,
        "network_calls": 0,
        "rerun_requested": False,
        "rerun_executed": False,
    }
    session["_live_draft_cloud_diag_active_run"] = ctx
    return ctx


def note_db_call(session: dict[str, Any], *, n: int = 1) -> None:
    ctx = session.get("_live_draft_cloud_diag_active_run")
    if isinstance(ctx, dict):
        ctx["db_calls"] = int(ctx.get("db_calls") or 0) + int(n)


def note_network_call(session: dict[str, Any], *, n: int = 1) -> None:
    ctx = session.get("_live_draft_cloud_diag_active_run")
    if isinstance(ctx, dict):
        ctx["network_calls"] = int(ctx.get("network_calls") or 0) + int(n)


def note_rerun_requested(session: dict[str, Any], *, executed: bool = False) -> None:
    ctx = session.get("_live_draft_cloud_diag_active_run")
    if isinstance(ctx, dict):
        ctx["rerun_requested"] = True
        if executed:
            ctx["rerun_executed"] = True


def finish_run(session: dict[str, Any], *, source: str = "page") -> None:
    ctx = session.pop("_live_draft_cloud_diag_active_run", None)
    if not isinstance(ctx, dict):
        return
    elapsed_ms = int((time.perf_counter() - float(ctx.get("started_perf") or 0)) * 1000)
    entry = {
        "ts": time.time(),
        "seq": ctx.get("seq"),
        "source": source or ctx.get("source"),
        "elapsed_ms": elapsed_ms,
        "db_calls": ctx.get("db_calls"),
        "network_calls": ctx.get("network_calls"),
        "rerun_requested": ctx.get("rerun_requested"),
        "rerun_executed": ctx.get("rerun_executed"),
        "thread": ctx.get("thread"),
        "fragments": fragment_owner_summary(session),
    }
    log = list(session.get(RUN_LOG_KEY) or [])
    log.append(entry)
    session[RUN_LOG_KEY] = log[-MAX_LOG:]


def log_action_callback(
    session: dict[str, Any],
    action: str,
    *,
    received_at: float | None = None,
    painted_at: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    received_at = float(received_at if received_at is not None else time.perf_counter())
    entry: dict[str, Any] = {
        "action": str(action),
        "received_at": time.time(),
        "received_perf": received_at,
    }
    if painted_at is not None:
        entry["click_to_paint_ms"] = int((float(painted_at) - received_at) * 1000)
    if extra:
        entry.update(extra)
    log = list(session.get(ACTION_LOG_KEY) or [])
    log.append(entry)
    session[ACTION_LOG_KEY] = log[-MAX_LOG:]


def _snapshot_fields(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from live_draft_solo_timer import get_solo_display_snapshot, is_solo_live_draft

        if is_solo_live_draft(session, room if isinstance(room, dict) else None):
            snap = get_solo_display_snapshot(session, room if isinstance(room, dict) else None)
            if snap:
                out.update(
                    {
                        "draft_id": snap.get("draft_id"),
                        "revision": snap.get("draft_revision"),
                        "pick_index": snap.get("pick_index"),
                        "team_on_clock": snap.get("team"),
                        "deadline": snap.get("timer_deadline"),
                        "remaining": snap.get("remaining_seconds"),
                    }
                )
                return out
    except ImportError:
        pass
    try:
        from live_draft_canonical_snapshot import get_live_draft_paint_snapshot

        paint = get_live_draft_paint_snapshot(session)
        if paint:
            out.update(
                {
                    "draft_id": paint.get("draft_id"),
                    "revision": paint.get("revision"),
                    "pick_index": paint.get("current_pick_index"),
                    "team_on_clock": paint.get("team_on_clock"),
                    "deadline": paint.get("timer_deadline"),
                    "remaining": paint.get("timer_remaining"),
                    "paint_token": paint.get("paint_token") or paint.get("snapshot_id"),
                }
            )
    except ImportError:
        pass
    if isinstance(room, dict):
        out.setdefault("pick_index", room.get("current_pick_index"))
        out.setdefault("deadline", room.get("timer_deadline"))
    return out


def render_surface_stamp(
    st: Any,
    session: dict[str, Any],
    *,
    component: str,
    render_owner: str,
    room: dict[str, Any] | None = None,
    fragment_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if not _admin_ok(st):
        return
    seq = int(session.get(RUN_SEQ_KEY) or 0)
    fields = _snapshot_fields(session, room)
    bits = [
        f"{component}",
        f"owner={render_owner}",
        f"seq={seq}",
        f"ts={time.time():.1f}",
        f"id={fields.get('draft_id') or '—'}",
        f"rev={fields.get('revision') or '—'}",
        f"idx={fields.get('pick_index') if fields.get('pick_index') is not None else '—'}",
        f"team={fields.get('team_on_clock') or '—'}",
        f"dl={fields.get('deadline') if fields.get('deadline') is not None else '—'}",
        f"rem={fields.get('remaining') if fields.get('remaining') is not None else '—'}",
        f"tok={fields.get('paint_token') or '—'}",
        f"frag={fragment_id or '—'}",
        f"thr={threading.current_thread().name}",
    ]
    if extra:
        for k, v in extra.items():
            bits.append(f"{k}={v}")
    st.caption("LDR · " + " · ".join(bits))


def render_admin_diag_panel(st: Any, session: dict[str, Any]) -> None:
    if not _admin_ok(st):
        return
    with st.expander("Live Draft Cloud diagnostics", expanded=False):
        st.caption(f"Fragment owners: {fragment_owner_summary(session)}")
        st.caption(f"Solo no-fragment: {solo_no_fragment_mode(session)} · canary: {bool(session.get(CANARY_MODE_KEY))}")
        runs = list(session.get(RUN_LOG_KEY) or [])[-8:]
        if runs:
            st.markdown("**Recent runs**")
            for row in reversed(runs):
                st.caption(
                    f"#{row.get('seq')} {row.get('source')} · {row.get('elapsed_ms')}ms · "
                    f"db={row.get('db_calls')} net={row.get('network_calls')} · "
                    f"rerun={row.get('rerun_requested')}/{row.get('rerun_executed')} · "
                    f"frag={row.get('fragments')}"
                )
        actions = list(session.get(ACTION_LOG_KEY) or [])[-8:]
        if actions:
            st.markdown("**Action timing**")
            for row in reversed(actions):
                ms = row.get("click_to_paint_ms")
                st.caption(
                    f"{row.get('action')} · paint={ms if ms is not None else '—'}ms · "
                    f"{row.get('received_at', '')}"
                )
