"""Admin-only Live Draft Cloud diagnostics — render stamps and action timing."""

from __future__ import annotations

import threading
import time
from typing import Any

RUN_SEQ_KEY = "_live_draft_cloud_diag_run_seq"
RUN_LOG_KEY = "_live_draft_cloud_diag_run_log"
ACTION_LOG_KEY = "_live_draft_cloud_action_timing_log"
FRAGMENT_OWNERS_KEY = "_live_draft_fragment_owner_counts"
FRAGMENT_OWNER_HISTORY_KEY = "_live_draft_fragment_owner_history"
SOLO_NO_FRAGMENT_KEY = "_live_draft_solo_no_fragment_mode"
CANARY_MODE_KEY = "_live_draft_cloud_canary_mode"
CLOUD_ACCEPT_KEY = "_live_draft_cloud_accept_mode"
START_STAGE_LOG_KEY = "_live_draft_cloud_start_stage_log"
BLOCKING_OPS_KEY = "_live_draft_cloud_blocking_ops"
CONTROL_CENTER_MOUNT_KEY = "_live_draft_control_center_mount_log"
MANUAL_PANEL_MOUNT_KEY = "_live_draft_manual_panel_mount_log"
EXPIRATION_COMMIT_KEY = "_live_draft_expiration_commit_count"
MAX_LOG = 120


def _qp_from_context_url(st: Any, name: str) -> str:
    """Read a query flag from st.context.url when st.query_params omits it.

    Streamlit fragments and suite_sid writes can leave query_params incomplete
    while the browser/iframe URL still carries diagnostic intents.
    """
    try:
        from urllib.parse import parse_qs, urlparse

        ctx = getattr(st, "context", None)
        url = str(getattr(ctx, "url", "") or "")
        if not url or "=" not in url:
            return ""
        parsed = urlparse(url)
        query = parsed.query
        if not query and "?" in url:
            query = url.split("?", 1)[-1].split("#", 1)[0]
        raw = parse_qs(query, keep_blank_values=True).get(name)
        if not raw:
            return ""
        return str(raw[0] or "").strip()
    except Exception:
        return ""


def _qp_get(st: Any, name: str) -> str:
    raw = None
    try:
        raw = getattr(st, "query_params", None)
        if raw is not None:
            val = raw.get(name)
            if val is not None:
                if isinstance(val, list):
                    return str(val[0] or "").strip()
                if isinstance(val, (str, int, float, bool)):
                    return str(val).strip()
                return ""
    except Exception:
        pass
    try:
        legacy = st.experimental_get_query_params()
        raw = legacy.get(name)
    except Exception:
        raw = None
    if raw is not None:
        if isinstance(raw, list):
            return str(raw[0] or "").strip()
        if isinstance(raw, (str, int, float, bool)):
            return str(raw).strip()
        return ""
    return _qp_from_context_url(st, name)


def _qp_flag(st: Any, name: str) -> bool:
    return _qp_get(st, name).lower() in ("1", "true", "yes", "on")


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


def streamlit_cloud_runtime() -> bool:
    return _streamlit_cloud_runtime()


def bootstrap_cloud_accept_mode(st: Any, session: dict[str, Any]) -> bool:
    """Enable admin diagnostics/canary for internal Cloud acceptance (?ld_accept=1)."""
    if session.get(CLOUD_ACCEPT_KEY):
        return True
    if not _qp_flag(st, "ld_accept"):
        return False
    paired_canary = _qp_flag(st, "ld_canary")
    allowed = paired_canary or _streamlit_cloud_runtime()
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
    if paired_canary:
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
    if st is not None:
        if _qp_flag(st, "ld_accept") and (
            _qp_flag(st, "ld_canary") or _streamlit_cloud_runtime()
        ):
            if isinstance(ss, dict):
                bootstrap_cloud_accept_mode(st, ss)
            return True
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
    row: dict[str, Any] = {
        "ts": time.time(),
        "owner": str(owner),
        "delta": int(delta),
        "streamlit_session_id": "",
        "thread_state_fragment_id": "",
        "current_fragment_id_ctx": "",
        "fragment_storage_ids": [],
        "fragment_in_storage": None,
    }
    try:
        from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity

        snap = snapshot_fragment_identity(phase="FRAGMENT_OWNER_NOTE", widget_user_key="")
        row["thread_state_fragment_id"] = str(snap.get("thread_state_fragment_id") or "")
        row["current_fragment_id_ctx"] = str(snap.get("current_fragment_id_ctx") or "")
        fs = snap.get("fragment_storage") if isinstance(snap.get("fragment_storage"), dict) else {}
        stored = list(fs.get("stored_fragment_ids") or [])
        row["fragment_storage_ids"] = stored[:16]
        tid = row["thread_state_fragment_id"]
        if tid and stored:
            row["fragment_in_storage"] = tid in stored
        row["streamlit_session_id"] = str(snap.get("streamlit_session_id") or "")
    except Exception:
        pass
    hist = list(session.get(FRAGMENT_OWNER_HISTORY_KEY) or [])
    hist.append(dict(row))
    session[FRAGMENT_OWNER_HISTORY_KEY] = hist[-48:]


def note_control_center_mount(session: dict[str, Any], *, source: str = "control_center") -> None:
    log = list(session.get(CONTROL_CENTER_MOUNT_KEY) or [])
    log.append(
        {
            "ts": time.time(),
            "source": str(source),
            "run_seq": int(session.get(RUN_SEQ_KEY) or 0),
        }
    )
    session[CONTROL_CENTER_MOUNT_KEY] = log[-MAX_LOG:]
    if cloud_accept_active(session):
        try:
            from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY

            session[HEAVY_PAINT_DONE_KEY] = True
        except ImportError:
            pass


def control_center_mount_count(session: dict[str, Any]) -> int:
    seq = int(session.get(RUN_SEQ_KEY) or 0)
    log = list(session.get(CONTROL_CENTER_MOUNT_KEY) or [])
    per_run = sum(1 for row in log if isinstance(row, dict) and int(row.get("run_seq") or 0) == seq)
    if per_run > 0:
        return per_run
    return 1 if log else 0


def note_manual_panel_mount(session: dict[str, Any], *, source: str = "manual_panel") -> None:
    log = list(session.get(MANUAL_PANEL_MOUNT_KEY) or [])
    log.append(
        {
            "ts": time.time(),
            "source": str(source),
            "run_seq": int(session.get(RUN_SEQ_KEY) or 0),
        }
    )
    session[MANUAL_PANEL_MOUNT_KEY] = log[-MAX_LOG:]


def manual_panel_mount_count(session: dict[str, Any]) -> int:
    seq = int(session.get(RUN_SEQ_KEY) or 0)
    log = list(session.get(MANUAL_PANEL_MOUNT_KEY) or [])
    per_run = sum(1 for row in log if isinstance(row, dict) and int(row.get("run_seq") or 0) == seq)
    if per_run > 0:
        return per_run
    return 1 if log else 0


def manual_panel_mount_summary(session: dict[str, Any]) -> str:
    log = list(session.get(MANUAL_PANEL_MOUNT_KEY) or [])
    if not log:
        return "none"
    return f"mounts={len(log)} last={log[-1].get('source')} seq={log[-1].get('run_seq')}"


def note_expiration_commit(session: dict[str, Any], *, source: str = "solo_heartbeat") -> None:
    session[EXPIRATION_COMMIT_KEY] = int(session.get(EXPIRATION_COMMIT_KEY) or 0) + 1
    log = list(session.get(ACTION_LOG_KEY) or [])
    log.append(
        {
            "action": "expiration_commit",
            "source": str(source),
            "count": int(session.get(EXPIRATION_COMMIT_KEY) or 0),
            "received_at": time.time(),
        }
    )
    session[ACTION_LOG_KEY] = log[-MAX_LOG:]


def expiration_commit_count(session: dict[str, Any]) -> int:
    return int(session.get(EXPIRATION_COMMIT_KEY) or 0)


def get_acceptance_snapshot(session: dict[str, Any], room: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = _snapshot_fields(session, room)
    try:
        from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, heavy_fragment_mount_count

        heavy_done = bool(session.get(HEAVY_PAINT_DONE_KEY))
        heavy_mounts = heavy_fragment_mount_count(session)
    except ImportError:
        heavy_done = False
        heavy_mounts = 0
    try:
        from live_draft_solo_heartbeat import SOLO_HEARTBEAT_TICK_KEY, solo_heartbeat_active

        hb_ticks = int(session.get(SOLO_HEARTBEAT_TICK_KEY) or 0)
        hb_active = solo_heartbeat_active(session)
    except ImportError:
        hb_ticks = 0
        hb_active = False
    hb_diag: dict[str, Any] = {}
    try:
        from live_draft_solo_heartbeat_diagnostics import last_heartbeat_tick_summary

        hb_diag = last_heartbeat_tick_summary(session)
    except ImportError:
        pass
    egress_idle: dict[str, Any] = {}
    try:
        from live_draft_solo_heartbeat import get_solo_timer_idle_egress_report

        egress_idle = get_solo_timer_idle_egress_report(session)
    except ImportError:
        pass
    try:
        from suite_egress_trace import get_run_egress_summary

        egress_summary = get_run_egress_summary()
    except ImportError:
        egress_summary = {}
    runs = list(session.get(RUN_LOG_KEY) or [])
    render_seq = [int(r.get("seq") or 0) for r in runs[-6:] if isinstance(r, dict)]
    return {
        "control_center_mounts": control_center_mount_count(session),
        "manual_panel_mounts": manual_panel_mount_count(session),
        "heavy_fragment_mounts": heavy_mounts,
        "heavy_paint_done": heavy_done,
        "paint_token": fields.get("paint_token"),
        "render_sequence": render_seq,
        "fragment_owners": dict(session.get(FRAGMENT_OWNERS_KEY) or {}),
        "draft_id": fields.get("draft_id"),
        "pick_index": fields.get("pick_index"),
        "revision": fields.get("revision"),
        "heartbeat_ticks": hb_ticks,
        "heartbeat_active": hb_active,
        "heartbeat_recent": hb_diag.get("recent"),
        "heartbeat_last_row": hb_diag.get("last_row"),
        "expiration_commits": expiration_commit_count(session),
        "run_seq": int(session.get(RUN_SEQ_KEY) or 0),
        "solo_poll_owner": egress_idle.get("poll_owner") or "local_page",
        "solo_idle_ticks": egress_idle.get("idle_ticks"),
        "solo_idle_reads_per_min": egress_idle.get("idle_reads_per_min"),
        "solo_idle_writes_per_min": egress_idle.get("idle_writes_per_min"),
        "solo_idle_full_room_per_min": egress_idle.get("idle_full_room_per_min"),
        "egress_reads_total": egress_summary.get("reads"),
        "egress_writes_total": egress_summary.get("writes"),
        "egress_full_room_total": egress_summary.get("full_room_loads"),
        "egress_full_room_by_caller": egress_summary.get("full_room_by_caller"),
    }


def render_acceptance_stamp(st: Any, session: dict[str, Any], room: dict[str, Any] | None = None) -> None:
    if not cloud_accept_active(session):
        return
    snap = get_acceptance_snapshot(session, room)
    st.caption(
        "LDR accept · "
        f"cc_mounts={snap.get('control_center_mounts')} · "
        f"manual_mounts={snap.get('manual_panel_mounts')} · "
        f"paint_tok={snap.get('paint_token') or '—'} · "
        f"run_seq={snap.get('render_sequence') or '—'} · "
        f"frag={snap.get('fragment_owners') or '—'} · "
        f"id={snap.get('draft_id') or '—'} · "
        f"pick={snap.get('pick_index') if snap.get('pick_index') is not None else '—'} · "
        f"rev={snap.get('revision') or '—'} · "
        f"hb_ticks={snap.get('heartbeat_ticks')} · "
        f"exp_commits={snap.get('expiration_commits')} · "
        f"solo_poll={snap.get('solo_poll_owner') or 'local_page'} · "
        f"idle_rpm={snap.get('solo_idle_reads_per_min') if snap.get('solo_idle_reads_per_min') is not None else '—'} · "
        f"idle_wpm={snap.get('solo_idle_writes_per_min') if snap.get('solo_idle_writes_per_min') is not None else '—'} · "
        f"idle_full/min={snap.get('solo_idle_full_room_per_min') if snap.get('solo_idle_full_room_per_min') is not None else '—'}"
    )


def render_acceptance_stamp_live(
    st: Any, session: dict[str, Any], room: dict[str, Any] | None = None
) -> None:
    """Refresh acceptance counters during fragment/heartbeat activity without full-page reruns."""
    if not cloud_accept_active(session):
        return
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        render_acceptance_stamp(st, session, room)
        return

    @fragment(run_every=2)
    def _acceptance_stamp_fragment() -> None:
        render_acceptance_stamp(st, session, room)

    _acceptance_stamp_fragment()


def control_center_mount_summary(session: dict[str, Any]) -> str:
    log = list(session.get(CONTROL_CENTER_MOUNT_KEY) or [])
    if not log:
        return "none"
    return f"mounts={len(log)} last={log[-1].get('source')} seq={log[-1].get('run_seq')}"


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
    if _qp_flag(st, "ld_canary"):
        session[CANARY_MODE_KEY] = True
        return True
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
        snap = get_acceptance_snapshot(session)
        st.caption(f"Acceptance snapshot: {snap}")
        st.caption(f"Fragment owners: {fragment_owner_summary(session)}")
        st.caption(f"Control center mounts: {control_center_mount_summary(session)}")
        st.caption(f"Manual panel mounts: {manual_panel_mount_summary(session)}")
        st.caption(
            f"Heartbeat ticks: {snap.get('heartbeat_ticks')} · active={snap.get('heartbeat_active')} · "
            f"expiration commits: {snap.get('expiration_commits')}"
        )
        st.caption(
            f"Solo no-fragment: {solo_no_fragment_mode(session)} · canary: {bool(session.get(CANARY_MODE_KEY))} · "
            f"cloud_accept: {cloud_accept_active(session)}"
        )
        try:
            from live_draft_fast_solo_start import get_start_stage_report, should_defer_heavy_first_paint

            stage_report = get_start_stage_report(session)
            if stage_report:
                st.markdown("**Start Draft stages (measured)**")
                for name, row in stage_report.items():
                    if not isinstance(row, dict):
                        continue
                    st.caption(
                        f"{name} · {row.get('elapsed_ms', '—')}ms · "
                        f"{', '.join(f'{k}={v}' for k, v in row.items() if k not in ('elapsed_ms', 'at'))}"
                    )
            if should_defer_heavy_first_paint(session):
                st.caption("Heavy paint deferred for first active-page pass.")
        except ImportError:
            pass
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
