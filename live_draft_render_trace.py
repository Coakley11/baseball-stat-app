"""Live Draft Room render-pipeline tracer (Daniel / ?ldr_trace=1)."""

from __future__ import annotations

import json
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

LDR_TRACE_LOG_KEY = "_live_draft_render_trace_log"
LDR_TRACE_ENABLED_KEY = "_live_draft_render_trace_enabled"
LDR_TRACE_LAST_SECTION_KEY = "_live_draft_render_last_section"
LDR_TRACE_MAX = 400

# Temporary debug for Daniel-only LDR incomplete paint — show for everyone on Live Draft Room.
# Flip to False once the stall section is identified.
LDR_TRACE_UNCONDITIONAL = True

# Canonical LDR page pipeline order (sparse markers may skip some).
LDR_SECTION_ORDER = (
    "page_entry",
    "account_pref_sync",
    "prepare_global_fantasy_settings",
    "header_and_guide",
    "shared_settings",
    "prepare_live_draft_state",
    "poll_fragment",
    "shared_draft_panel",
    "room_body",
    "room_reconcile",
    "room_lobby",
    "room_team_identity",
    "room_headers",
    "room_controls_timer",
    "timer_enter",
    "timer_load_timer_state",
    "timer_load_room_state",
    "timer_load_poll_state",
    "timer_compute_remaining",
    "timer_render_countdown",
    "timer_attach_fragment",
    "timer_fragment_tick",
    "timer_handle_expired_pick",
    "timer_render_controls",
    "timer_attach_callbacks",
    "timer_exit",
    "post_rerun_after_header",
    "shared_settings",
    "prepare_live_draft_state",
    "poll_fragment",
    "shared_draft_panel",
    "room_body",
    "room_board_column",
    "room_recommendations",
    "room_decision_panels",
    "page_complete",
)

LDR_TRACE_LAST_STEP_KEY = "_live_draft_render_last_step"


def is_ldr_trace_enabled(session: dict[str, Any] | None, st: Any | None = None) -> bool:
    if LDR_TRACE_UNCONDITIONAL:
        if isinstance(session, dict):
            session[LDR_TRACE_ENABLED_KEY] = True
        return True
    if not isinstance(session, dict):
        return False
    if session.get(LDR_TRACE_ENABLED_KEY) or session.get("_live_draft_render_trace_force"):
        return True
    try:
        from fantasy_workflow_trace import is_wf_trace_enabled

        if is_wf_trace_enabled(session, st):
            return True
    except ImportError:
        pass
    if st is not None:
        try:
            raw = st.query_params.get("ldr_trace")
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else ""
            if str(raw or "").strip() in {"1", "true", "yes"}:
                session[LDR_TRACE_ENABLED_KEY] = True
                return True
        except Exception:
            pass
    return False


def _append(session: dict[str, Any], entry: dict[str, Any]) -> None:
    log = session.setdefault(LDR_TRACE_LOG_KEY, [])
    if not isinstance(log, list):
        log = []
        session[LDR_TRACE_LOG_KEY] = log
    log.append(entry)
    if len(log) > LDR_TRACE_MAX:
        session[LDR_TRACE_LOG_KEY] = log[-LDR_TRACE_MAX:]
    # Only persist real Live Draft Room runs (avoid unit-test pollution).
    if str(session.get("active_page") or "") != "Live Draft Room":
        return
    try:
        from suite_user_persistence import DATA_DIR

        ws = str(session.get("_suite_active_workspace_id") or "unknown").strip() or "unknown"
        path = Path(DATA_DIR) / "workspaces" / ws / "live_draft_render_trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def build_ldr_workspace_compare_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    """Comparable identity/source fields for Daniel vs coakley11."""
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
    source_kind = ""
    source_origin = ""
    effective_my_team = ""
    try:
        from fantasy_context_source import get_effective_fantasy_context, resolve_fantasy_context_source

        src = resolve_fantasy_context_source(session)
        source_kind = str(getattr(src, "kind", "") or "")
        source_origin = str(getattr(src, "origin", "") or "")
        ctx = get_effective_fantasy_context(session)
        if isinstance(ctx, dict):
            effective_my_team = str(ctx.get("my_team_name") or "").strip()
    except Exception as exc:
        source_kind = f"error:{type(exc).__name__}"
    active_draft_id = str(session.get("active_draft_archive_id") or "").strip()
    try:
        from draft_archive_state import get_active_draft_archive

        arch = get_active_draft_archive(session)
        if isinstance(arch, dict):
            active_draft_id = str(arch.get("draft_id") or active_draft_id).strip()
            active_draft_name = str(arch.get("draft_name") or "").strip()
            active_draft_team = str(arch.get("team_name") or "").strip()
        else:
            active_draft_name = ""
            active_draft_team = ""
    except Exception:
        active_draft_name = ""
        active_draft_team = ""
    shared_code = str(session.get("active_shared_draft_room_code") or "").strip()
    poll_diag = session.get("_live_draft_poll_diag") if isinstance(session.get("_live_draft_poll_diag"), dict) else {}
    return {
        "workspace_id": str(session.get("_suite_active_workspace_id") or session.get("suite_workspace_id") or ""),
        "auth_user_id": str(session.get("_suite_auth_user_id") or ""),
        "auth_external_id": str(session.get("_suite_auth_external_id") or ""),
        "effective_source_kind": source_kind,
        "effective_source_origin": source_origin,
        "effective_my_team": effective_my_team,
        "active_draft_id": active_draft_id,
        "active_draft_name": active_draft_name,
        "active_draft_team": active_draft_team,
        "temporary_draft_id": str(room.get("draft_room_id") or room.get("room_id") or ""),
        "temporary_league_name": str(cfg.get("league_name") or room.get("league_name") or ""),
        "temporary_status": str(room.get("status") or ""),
        "temporary_teams": list(room.get("teams") or cfg.get("teams") or []),
        "room_code": shared_code,
        "live_draft_my_team": str(session.get("live_draft_my_team") or ""),
        "room_your_team": str(session.get("room_your_team") or ""),
        "config_user_team": str(cfg.get("user_team") or cfg.get("your_team") or ""),
        "participant_team": str(session.get("draft_room_participant_team") or ""),
        "shared_league_context_id": str(session.get("active_league_context_id") or ""),
        "multiplayer_active": bool(shared_code),
        "poll_ts": session.get("_shared_draft_poll_ts"),
        "poll_active_page": session.get("_shared_draft_poll_active_page"),
        "poll_apply_pending": bool(session.get("_live_draft_poll_apply_pending")),
        "poll_diag": {
            "live_poll_enabled": poll_diag.get("live_poll_enabled"),
            "live_poll_interval_ms": poll_diag.get("live_poll_interval_ms"),
            "local_revision": poll_diag.get("local_revision"),
            "remote_revision": poll_diag.get("remote_revision"),
            "remote_update_detected": poll_diag.get("remote_update_detected"),
            "remote_update_applied": poll_diag.get("remote_update_applied"),
            "poll_suppressed_reason": poll_diag.get("poll_suppressed_reason"),
        },
        "last_rerun_source": str(session.get("_live_draft_last_rerun_source") or ""),
        "last_successful_section": str(session.get(LDR_TRACE_LAST_SECTION_KEY) or ""),
        "page_overwrite_source": str(session.get("_suite_page_overwrite_source") or ""),
    }


def analyze_ldr_stall(session: dict[str, Any]) -> dict[str, Any]:
    """Derive last successful section + next section begun from the session log."""
    log = session.get(LDR_TRACE_LOG_KEY) or []
    if not isinstance(log, list) or not log:
        return {
            "last_successful_section": "",
            "next_section_begun": "",
            "next_behavior": "no_trace_entries",
            "analysis": "No Live Draft render trace entries in session.",
        }
    last_success = ""
    next_begun = ""
    next_behavior = "unknown"
    terminal: dict[str, Any] | None = None
    for entry in log:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "")
        section = str(entry.get("section") or "")
        reason = str(entry.get("reason") or "")
        if kind in {"section_end", "step_end"} and reason == "complete":
            last_success = section
            next_begun = ""
            next_behavior = "unknown"
            terminal = None
        elif kind in {"section", "step"} and reason == "enter":
            if last_success and not next_begun:
                next_begun = section
            elif not last_success:
                next_begun = section
            terminal = entry
        elif kind in {"rerun", "stop", "early_return", "exception"}:
            next_begun = section or next_begun
            next_behavior = kind
            terminal = entry
    if not last_success:
        last_success = str(session.get(LDR_TRACE_LAST_SECTION_KEY) or "")
    if not next_begun and last_success:
        try:
            idx = LDR_SECTION_ORDER.index(last_success)
            if idx + 1 < len(LDR_SECTION_ORDER):
                next_begun = LDR_SECTION_ORDER[idx + 1]
                if next_behavior == "unknown":
                    next_behavior = "expected_next_not_entered"
        except ValueError:
            pass
    if terminal and next_behavior == "unknown":
        kind = str(terminal.get("kind") or "")
        reason = str(terminal.get("reason") or "")
        if kind in {"section", "step"} and reason == "enter":
            next_behavior = "entered_not_completed"
    analysis_bits = [
        f"LAST SUCCESSFUL SECTION: {last_success or '(none)'}",
        f"NEXT SECTION: {next_begun or '(unknown)'}",
        f"NEXT BEHAVIOR: {next_behavior}",
    ]
    if terminal and terminal.get("reason"):
        analysis_bits.append(f"TERMINAL REASON: {terminal.get('reason')}")
    return {
        "last_successful_section": last_success,
        "next_section_begun": next_begun,
        "next_behavior": next_behavior,
        "analysis": "\n".join(analysis_bits),
        "terminal": terminal,
    }


def ldr_trace(
    session: dict[str, Any],
    *,
    section: str,
    reason: str = "",
    kind: str = "section",
    st: Any | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if not is_ldr_trace_enabled(session, st):
        return
    entry = {
        "t": time.time(),
        "kind": kind,
        "section": str(section or ""),
        "reason": str(reason or ""),
        "active_page": str(session.get("active_page") or ""),
    }
    if extra:
        entry["extra"] = extra
    if kind in {"section", "section_end", "fragment", "empty", "container", "step", "step_end"}:
        session[LDR_TRACE_LAST_SECTION_KEY] = str(section or "")
    if kind in {"step", "step_end"}:
        session[LDR_TRACE_LAST_STEP_KEY] = str(section or "")
    _append(session, entry)


def ldr_section(session: dict[str, Any], name: str, *, st: Any | None = None, **extra: Any) -> None:
    ldr_trace(session, section=name, reason="enter", kind="section", st=st, extra=extra or None)


def ldr_section_done(session: dict[str, Any], name: str, *, st: Any | None = None, **extra: Any) -> None:
    ldr_trace(session, section=name, reason="complete", kind="section_end", st=st, extra=extra or None)


def ldr_early_return(session: dict[str, Any], name: str, *, reason: str, st: Any | None = None) -> None:
    ldr_trace(session, section=name, reason=f"early_return:{reason}", kind="early_return", st=st)


def ldr_rerun(session: dict[str, Any], name: str, *, reason: str, st: Any | None = None) -> None:
    ldr_trace(session, section=name, reason=f"rerun:{reason}", kind="rerun", st=st)


def ldr_stop(session: dict[str, Any], name: str, *, reason: str, st: Any | None = None) -> None:
    ldr_trace(session, section=name, reason=f"st.stop:{reason}", kind="stop", st=st)


def ldr_exception(session: dict[str, Any], name: str, exc: BaseException, *, st: Any | None = None) -> None:
    ldr_trace(
        session,
        section=name,
        reason=f"exception:{type(exc).__name__}:{exc}",
        kind="exception",
        st=st,
        extra={"traceback": traceback.format_exc()[-1500:]},
    )


@contextmanager
def ldr_step(
    session: dict[str, Any],
    name: str,
    *,
    st: Any | None = None,
    ui_marker: bool = True,
    **extra: Any,
) -> Iterator[None]:
    """Fine-grained timed subsection tracer for stall isolation."""
    if not is_ldr_trace_enabled(session, st):
        yield
        return
    t0 = time.perf_counter()
    ldr_trace(
        session,
        section=name,
        reason="enter",
        kind="step",
        st=st,
        extra=extra or None,
    )
    if ui_marker and st is not None:
        try:
            st.caption(f"⏱ LDR step enter: `{name}`")
        except Exception:
            pass
    try:
        yield
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        ldr_trace(
            session,
            section=name,
            reason=f"exception:{type(exc).__name__}:{exc}",
            kind="exception",
            st=st,
            extra={"elapsed_ms": elapsed_ms, "traceback": traceback.format_exc()[-1500:]},
        )
        if ui_marker and st is not None:
            try:
                st.error(f"⏱ LDR step exception: `{name}` ({elapsed_ms}ms) {type(exc).__name__}: {exc}")
            except Exception:
                pass
        raise
    else:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        ldr_trace(
            session,
            section=name,
            reason="complete",
            kind="step_end",
            st=st,
            extra={"elapsed_ms": elapsed_ms, **(extra or {})},
        )
        if ui_marker and st is not None:
            try:
                st.caption(f"⏱ LDR step done: `{name}` ({elapsed_ms}ms)")
            except Exception:
                pass


def format_ldr_trace_text(session: dict[str, Any], *, limit: int = 120) -> str:
    log = session.get(LDR_TRACE_LOG_KEY) or []
    if not isinstance(log, list) or not log:
        return "(no Live Draft render trace entries)"
    lines = []
    for i, entry in enumerate(log[-limit:], 1):
        if not isinstance(entry, dict):
            continue
        extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
        elapsed = extra.get("elapsed_ms")
        suffix = f" | {elapsed}ms" if elapsed is not None else ""
        lines.append(
            f"{i:02d}. [{entry.get('kind')}] {entry.get('section')} | {entry.get('reason')}{suffix}"
        )
    stall = analyze_ldr_stall(session)
    lines.append("")
    lines.append(stall["analysis"])
    last_step = session.get(LDR_TRACE_LAST_STEP_KEY) or ""
    if last_step:
        lines.append(f"LAST TIMER/STEP: {last_step}")
    return "\n".join(lines)


def format_next_behavior_label(behavior: str, *, terminal: dict[str, Any] | None = None) -> str:
    """Map internal stall codes to the sidebar labels used for diagnosis."""
    b = str(behavior or "").strip()
    reason = str((terminal or {}).get("reason") or "")
    if b == "rerun" or reason.startswith("rerun:"):
        if "poll" in reason.lower():
            return "rerun (poll / shared-state apply)"
        return "rerun"
    if b == "stop" or reason.startswith("st.stop:"):
        return "stop"
    if b == "early_return" or reason.startswith("early_return:"):
        return "early return"
    if b == "exception" or reason.startswith("exception:"):
        return f"exception ({reason.split(':', 1)[-1] if ':' in reason else reason})"
    if b == "entered_not_completed":
        return "entered but not completed (possible block / hang)"
    if b == "expected_next_not_entered":
        return "expected next not entered (script stopped before enter)"
    if b == "no_trace_entries":
        return "no_trace_entries"
    return b or "unknown"


def _format_poll_state(snap: dict[str, Any]) -> str:
    diag = snap.get("poll_diag") if isinstance(snap.get("poll_diag"), dict) else {}
    parts = [
        f"enabled={diag.get('live_poll_enabled')}",
        f"interval_ms={diag.get('live_poll_interval_ms')}",
        f"local_rev={diag.get('local_revision')}",
        f"remote_rev={diag.get('remote_revision')}",
        f"update_detected={diag.get('remote_update_detected')}",
        f"update_applied={diag.get('remote_update_applied')}",
        f"suppressed={diag.get('poll_suppressed_reason') or '—'}",
        f"poll_ts={snap.get('poll_ts')}",
        f"poll_page={snap.get('poll_active_page') or '—'}",
        f"apply_pending={snap.get('poll_apply_pending')}",
        f"last_rerun={snap.get('last_rerun_source') or '—'}",
    ]
    return " | ".join(str(p) for p in parts)


def _write_ldr_trace_panel_body(st: Any, ss: dict[str, Any]) -> None:
    snap = build_ldr_workspace_compare_snapshot(ss)
    stall = analyze_ldr_stall(ss)
    effective_source = (
        f"{snap.get('effective_source_kind') or '—'} "
        f"(origin={snap.get('effective_source_origin') or '—'}; "
        f"team={snap.get('effective_my_team') or '—'})"
    )
    behavior_label = format_next_behavior_label(
        str(stall.get("next_behavior") or ""),
        terminal=stall.get("terminal") if isinstance(stall.get("terminal"), dict) else None,
    )
    st.caption("Temporary unconditional debug panel — paste this when LDR lower half stalls.")
    st.markdown(f"**Last successful section:** `{stall.get('last_successful_section') or '—'}`")
    st.markdown(f"**Next section entered:** `{stall.get('next_section_begun') or '—'}`")
    st.markdown(f"**Next behavior:** `{behavior_label}`")
    st.markdown(f"**Last timer/step:** `{ss.get(LDR_TRACE_LAST_STEP_KEY) or '—'}`")
    try:
        from live_draft_expired_pick import format_expired_pick_perf

        perf_line = format_expired_pick_perf(ss)
    except ImportError:
        perf_line = ""
    if perf_line:
        st.markdown(f"**Expired-pick perf (ms):** `{perf_line}`")
    else:
        st.markdown("**Expired-pick perf (ms):** `—`")
    st.markdown("---")
    st.markdown(f"**Effective Draft Source:** `{effective_source}`")
    st.markdown(f"**Workspace ID:** `{snap.get('workspace_id') or '—'}`")
    st.markdown(f"**Active Draft ID:** `{snap.get('active_draft_id') or '—'}`")
    st.markdown(f"**Temporary Draft ID:** `{snap.get('temporary_draft_id') or '—'}`")
    st.markdown(f"**Room Code:** `{snap.get('room_code') or '—'}`")
    st.markdown(
        f"**My Team:** `{snap.get('live_draft_my_team') or snap.get('effective_my_team') or '—'}`"
    )
    st.markdown(f"**Shared League ID:** `{snap.get('shared_league_context_id') or '—'}`")
    st.markdown(f"**Poll state:** `{_format_poll_state(snap)}`")
    st.caption("Raw section log:")
    st.code(format_ldr_trace_text(ss), language="text")
    st.caption("Full workspace / draft compare JSON (Daniel vs coakley11):")
    st.code(json.dumps(snap, indent=2, default=str), language="json")


def ldr_post_rerun_checkpoint(
    st: Any,
    session: dict[str, Any],
    label: str,
) -> None:
    """Lightweight in-page marker for the post-timer-zero rerun path (no heavy JSON dump)."""
    if not is_ldr_trace_enabled(session, st):
        return
    last_rerun = str(session.get("_live_draft_last_rerun_source") or "")
    last_step = str(session.get(LDR_TRACE_LAST_STEP_KEY) or "")
    last_section = str(session.get(LDR_TRACE_LAST_SECTION_KEY) or "")
    try:
        st.info(
            f"LDR post-rerun checkpoint `{label}` · "
            f"last_rerun=`{last_rerun or '—'}` · "
            f"last_section=`{last_section or '—'}` · "
            f"last_step=`{last_step or '—'}`"
        )
    except Exception:
        pass
    ldr_trace(
        session,
        section=label,
        reason="checkpoint",
        kind="checkpoint",
        st=st,
        extra={"last_rerun_source": last_rerun},
    )


def force_render_live_draft_trace_banner(
    st: Any,
    session: dict[str, Any] | None = None,
    *,
    label: str = "top",
) -> None:
    """Direct widgets only — never st.empty(). Always paint something visible."""
    ss = session if isinstance(session, dict) else st.session_state
    # Force-enable for this debug window regardless of prior gates.
    if isinstance(ss, dict):
        ss[LDR_TRACE_ENABLED_KEY] = True
        ss["_live_draft_render_trace_force"] = True
    title = f"Live Draft render trace (debug — always on) [{label}]"
    try:
        st.warning(
            f"🔎 {title} — temporary stall-debug instrumentation. "
            "Copy the fields below if the lower half of Live Draft Room does not finish rendering."
        )
        with st.expander(title, expanded=True):
            _write_ldr_trace_panel_body(st, ss)
        try:
            with st.sidebar.expander(title, expanded=True):
                _write_ldr_trace_panel_body(st, ss)
        except Exception as sidebar_exc:
            st.caption(f"(Sidebar trace unavailable: {type(sidebar_exc).__name__})")
    except Exception as exc:
        st.error(f"LDR TRACE RENDER ERROR [{label}]: {type(exc).__name__}: {exc}")


def begin_live_draft_render_trace(st: Any, session: dict[str, Any] | None = None) -> None:
    force_render_live_draft_trace_banner(st, session, label="page_entry")


def refresh_live_draft_render_trace(st: Any | None, session: dict[str, Any] | None = None) -> None:
    if st is None:
        return
    force_render_live_draft_trace_banner(st, session, label="refresh")


def render_live_draft_render_trace(st: Any, session: dict[str, Any] | None = None) -> None:
    force_render_live_draft_trace_banner(st, session, label="render")
