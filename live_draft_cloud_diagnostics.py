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
CLOUD_ACCEPT_KEY = "_live_draft_cloud_accept_mode"
START_STAGE_LOG_KEY = "_live_draft_cloud_start_stage_log"
BLOCKING_OPS_KEY = "_live_draft_cloud_blocking_ops"
MAX_LOG = 120


def _streamlit_cloud_runtime() -> bool:
    import os

    cloud_keys = (
        "STREAMLIT_RUNTIME_ENVIRONMENT",
        "STREAMLIT_SERVER_HEADLESS",
        "STREAMLIT_CLOUD",
        "STREAMLIT_CLOUD_COMMIT",
        "STREAMLIT_CLOUD_BRANCH",
        "STREAMLIT_SHARING_BASE_URL",
    )
    if any(os.environ.get(k) for k in cloud_keys):
        return True
    host = str(os.environ.get("HOSTNAME") or "").lower()
    return host.endswith(".streamlit.app") or "streamlit" in host


def bootstrap_cloud_accept_mode(st: Any, session: dict[str, Any]) -> bool:
    """Enable admin diagnostics/canary for internal Cloud acceptance (?ld_accept=1)."""
    if session.get(CLOUD_ACCEPT_KEY):
        return True
    raw = None
    ld_canary_raw = None
    try:
        qp = getattr(st, "query_params", None)
        if qp is not None:
            raw = qp.get("ld_accept")
            ld_canary_raw = qp.get("ld_canary")
    except Exception:
        return False
    if raw is None or str(raw).strip().lower() not in ("1", "true", "yes", "on"):
        return False
    paired_canary = str(ld_canary_raw or "").strip().lower() in ("1", "true", "yes", "on")
    allowed = paired_canary
    if not allowed:
        allowed = _streamlit_cloud_runtime()
    if not allowed:
        try:
            from suite_workspace import is_admin_session

            allowed = bool(is_admin_session(st=st))
        except ImportError:
            allowed = False
    if not allowed:
        return False
    try:
        from suite_workspace import set_developer_mode_user

        set_developer_mode_user(session, True, source="ld_accept_query")
    except ImportError:
        pass
    session[CLOUD_ACCEPT_KEY] = True
    if str(ld_canary_raw or "").strip().lower() in ("1", "true", "yes", "on"):
        session[CANARY_MODE_KEY] = True
    return True


def cloud_accept_active(session: dict[str, Any]) -> bool:
    return bool(session.get(CLOUD_ACCEPT_KEY))


def _admin_ok(st: Any | None = None, session: dict[str, Any] | None = None) -> bool:
    ss = session
    if ss is None and st is not None:
        try:
            ss = getattr(st, "session_state", None)
        except Exception:
            ss = None
    if isinstance(ss, dict) and cloud_accept_active(ss):
        return True
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
    bootstrap_cloud_accept_mode(st, session)
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


def log_start_stage(session: dict[str, Any], stage: str, *, elapsed_ms: int = 0, **fields: Any) -> None:
    log = list(session.get(START_STAGE_LOG_KEY) or [])
    log.append({"stage": str(stage), "elapsed_ms": int(elapsed_ms), "ts": time.time(), **fields})
    session[START_STAGE_LOG_KEY] = log[-MAX_LOG:]


def note_blocking_op(session: dict[str, Any], name: str, *, duration_ms: int, **fields: Any) -> None:
    ops = list(session.get(BLOCKING_OPS_KEY) or [])
    ops.append({"name": str(name), "duration_ms": int(duration_ms), "ts": time.time(), **fields})
    session[BLOCKING_OPS_KEY] = ops[-MAX_LOG:]
    if int(duration_ms) >= 500:
        try:
            from live_draft_perf import record_slow_path

            record_slow_path(session, str(name), duration_ms=int(duration_ms), **fields)
        except ImportError:
            pass


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
    if not _admin_ok(st, session):
        return
    with st.expander("Live Draft Cloud diagnostics", expanded=False):
        st.caption(f"Fragment owners: {fragment_owner_summary(session)}")
        st.caption(
            f"Solo no-fragment: {solo_no_fragment_mode(session)} · canary: {bool(session.get(CANARY_MODE_KEY))} · "
            f"cloud_accept: {cloud_accept_active(session)}"
        )
        stages = list(session.get(START_STAGE_LOG_KEY) or [])[-12:]
        if stages:
            st.markdown("**Start Draft stages**")
            for row in stages:
                st.caption(
                    f"{row.get('stage')} · {row.get('elapsed_ms')}ms · "
                    f"{', '.join(f'{k}={v}' for k, v in row.items() if k not in ('stage', 'elapsed_ms', 'ts'))}"
                )
        blockers = list(session.get(BLOCKING_OPS_KEY) or [])
        if blockers:
            worst = max(blockers, key=lambda x: int(x.get("duration_ms") or 0))
            st.caption(
                f"Longest blocking op: {worst.get('name')} · {worst.get('duration_ms')}ms"
            )
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
