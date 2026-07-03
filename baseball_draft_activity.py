"""
Command Center activity for Live Draft Room and Draft Simulation Test Mode.

Emits meaningful workflow events (not page visits) with resume deep links.
"""

from __future__ import annotations

from typing import Any

from activity_time import utc_now_iso

_DEDUP_SESSION_KEY = "_cc_live_draft_activity_logged"


def _session_dedup_store(session: dict[str, Any] | None) -> dict[str, str]:
    if session is None:
        return {}
    raw = session.get(_DEDUP_SESSION_KEY)
    if not isinstance(raw, dict):
        raw = {}
        session[_DEDUP_SESSION_KEY] = raw
    return raw


def _already_logged(session: dict[str, Any] | None, key: str) -> bool:
    if not key:
        return False
    store = _session_dedup_store(session)
    if store.get(key):
        return True
    store[key] = utc_now_iso()
    return False


def _team_names(room: dict[str, Any] | None) -> list[str]:
    if not isinstance(room, dict):
        return []
    config = room.get("config") if isinstance(room.get("config"), dict) else {}
    teams = list(room.get("teams") or config.get("teams") or [])
    out: list[str] = []
    for name in teams:
        text = str(name or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _matchup_label(teams: list[str]) -> str:
    if len(teams) >= 2:
        return f"{teams[0]} vs {teams[1]}"
    if teams:
        return teams[0]
    return ""


def _picks_per_team(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    config = room.get("config") if isinstance(room.get("config"), dict) else {}
    try:
        return int(config.get("picks_per_team") or room.get("picks_per_team") or 0)
    except (TypeError, ValueError):
        return 0


def _room_id(room: dict[str, Any] | None, session: dict[str, Any] | None = None) -> str:
    if isinstance(room, dict):
        rid = str(room.get("draft_room_id") or "").strip()
        if rid:
            return rid
    if isinstance(session, dict):
        live = session.get("live_draft_room")
        if isinstance(live, dict):
            rid = str(live.get("draft_room_id") or "").strip()
            if rid:
                return rid
    return ""


def _room_code(room: dict[str, Any] | None, session: dict[str, Any] | None = None) -> str:
    if isinstance(session, dict):
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        if code:
            return code
    if isinstance(room, dict):
        return str(room.get("room_code") or "").strip().upper()
    return ""


def live_draft_activity_metrics(
    room: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None = None,
    activity_type: str = "",
    feature: str = "",
) -> dict[str, Any]:
    teams = _team_names(room)
    metrics: dict[str, Any] = {
        "teams": teams,
        "team_matchup": _matchup_label(teams),
        "draft_room_id": _room_id(room, session),
        "room_code": _room_code(room, session),
        "picks_per_team": _picks_per_team(room),
        "feature": feature,
        "activity_type": activity_type,
        "page": feature,
    }
    if activity_type in {"completed_live_draft", "draft_analysis_created"}:
        metrics["completed_at"] = utc_now_iso()
    try:
        from suite_workspace import get_active_workspace_id

        metrics.setdefault("workspace_id", get_active_workspace_id())
    except ImportError:
        pass
    return metrics


def _record_draft_event(
    event: str,
    *,
    page: str,
    metrics: dict[str, Any],
    summary: str,
    resume_key: str,
    resume_title: str,
    resume_subtitle: str = "",
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diag: dict[str, Any] = {}
    try:
        from suite_activity_client import last_record_trace, record_activity
        from suite_activity_namespace import build_activity_write_diagnostics

        record_activity(
            "baseball",
            event,
            page=page,
            metrics=metrics,
            summary=summary,
            resume_key=resume_key,
            resume_title=resume_title,
            resume_subtitle=resume_subtitle,
        )
        trace = last_record_trace()
        if trace:
            metrics.setdefault("_activity_recorded", bool(trace.get("recorded")))
        diag = build_activity_write_diagnostics(
            event_type=event,
            resume_title=resume_title,
            resume_key=resume_key,
            page=page,
            metrics=metrics,
        )
    except Exception as exc:
        try:
            from suite_activity_namespace import build_activity_write_diagnostics

            diag = build_activity_write_diagnostics(
                event_type=event,
                resume_title=resume_title,
                resume_key=resume_key,
                page=page,
                metrics=metrics,
            )
            diag["write_success"] = False
            diag["write_error"] = str(exc)
        except ImportError:
            diag = {"write_success": False, "write_error": str(exc)}
    if isinstance(session, dict):
        session["_draft_activity_write_debug"] = diag
    return diag


def log_live_draft_room_created(room: dict[str, Any], *, session: dict[str, Any] | None = None) -> None:
    rid = _room_id(room, session)
    if _already_logged(session, f"live_draft_created:{rid}"):
        return
    teams = _team_names(room)
    matchup = _matchup_label(teams)
    metrics = live_draft_activity_metrics(
        room,
        session=session,
        activity_type="live_draft_created",
        feature="Live Draft Room",
    )
    metrics.setdefault("cc_card_kind", "continue")
    metrics.setdefault("workstream", "baseball_draft")
    subtitle = matchup or (f"Room {rid[:8]}" if rid else "Live draft")
    _record_draft_event(
        "live_draft_created",
        page="Live Draft Room",
        metrics=metrics,
        summary=f"Started Live Draft" + (f" — {subtitle}" if subtitle else ""),
        resume_key=f"bb:live_draft:{rid}" if rid else "bb:live_draft",
        resume_title="Open Live Draft Room",
        resume_subtitle=subtitle,
        session=session,
    )


def _last_board_player(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    board = room.get("draft_board") or []
    if not board or not isinstance(board[-1], dict):
        return ""
    last = board[-1]
    return str(last.get("fullName") or last.get("Player") or "").strip()


def log_live_draft_pick(room: dict[str, Any], *, session: dict[str, Any] | None = None) -> None:
    rid = _room_id(room, session)
    pick_no = len(room.get("draft_board") or []) if isinstance(room, dict) else 0
    if pick_no <= 0:
        return
    dedup = f"live_draft_pick:{rid}:{pick_no}"
    if _already_logged(session, dedup):
        return
    teams = _team_names(room)
    matchup = _matchup_label(teams)
    player = _last_board_player(room)
    metrics = live_draft_activity_metrics(
        room,
        session=session,
        activity_type="live_draft_pick",
        feature="Live Draft Room",
    )
    metrics["pick_number"] = pick_no
    metrics.setdefault("cc_card_kind", "continue")
    metrics.setdefault("workstream", "baseball_draft")
    if player:
        metrics["player"] = player
    if player:
        summary = f"Made draft pick: {player}"
        resume_subtitle = player
    else:
        summary = f"Live draft pick {pick_no}" + (f" — {matchup}" if matchup else "")
        resume_subtitle = matchup or f"Pick {pick_no}"
    _record_draft_event(
        "live_draft_pick",
        page="Live Draft Room",
        metrics=metrics,
        summary=summary,
        resume_key=f"bb:live_draft:{rid}" if rid else "bb:live_draft",
        resume_title="Continue Live Draft Room",
        resume_subtitle=resume_subtitle,
        session=session,
    )


def log_completed_live_draft(room: dict[str, Any], *, session: dict[str, Any] | None = None) -> None:
    rid = _room_id(room, session)
    if _already_logged(session, f"completed_live_draft:{rid}"):
        return
    teams = _team_names(room)
    matchup = _matchup_label(teams)
    metrics = live_draft_activity_metrics(
        room,
        session=session,
        activity_type="completed_live_draft",
        feature="Live Draft Room",
    )
    _record_draft_event(
        "completed_live_draft",
        page="Live Draft Room",
        metrics=metrics,
        summary="Live Draft completed" + (f" — {matchup}" if matchup else ""),
        resume_key=f"bb:live_draft:{rid}" if rid else "bb:live_draft",
        resume_title="Review completed draft",
        resume_subtitle=matchup or "Analyze or export results",
        session=session,
    )


def log_draft_analysis_created(
    room: dict[str, Any] | None = None,
    *,
    session: dict[str, Any] | None = None,
    lab_state: dict[str, Any] | None = None,
    draft_section: str = "",
) -> None:
    if room is None and isinstance(session, dict):
        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    rid = _room_id(room, session)
    section = str(draft_section or "").strip().lower()
    dedup_key = f"draft_analysis_created:{rid}:{section or 'lab'}"
    if _already_logged(session, dedup_key):
        return
    teams = _team_names(room)
    if not teams and isinstance(lab_state, dict):
        handoff = lab_state.get("handoff") if isinstance(lab_state.get("handoff"), dict) else {}
        ctx = lab_state.get("analysis_context") if isinstance(lab_state.get("analysis_context"), dict) else {}
        teams = list(handoff.get("team_names") or ctx.get("teams") or [])
    matchup = _matchup_label(teams)
    metrics = live_draft_activity_metrics(
        room,
        session=session,
        activity_type="draft_analysis_created",
        feature="Draft Simulation Test Mode",
    )
    resume_key = f"bb:draft_lab:team:{rid}" if rid else "bb:draft_lab"
    metrics["draft_section"] = "team_analysis"
    resume_title = "Continue Draft Analysis"
    _record_draft_event(
        "draft_analysis_created",
        page="Draft Simulation Test Mode",
        metrics=metrics,
        summary="Draft analysis ready" + (f" — {matchup}" if matchup else ""),
        resume_key=resume_key,
        resume_title=resume_title,
        resume_subtitle=matchup or "Draft Simulation Test Mode",
        session=session,
    )


def log_draft_analysis_attempted(
    room: dict[str, Any] | None = None,
    *,
    session: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    """Emit when analysis handoff fails — Command Center can still surface the completed draft."""
    if room is None and isinstance(session, dict):
        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    rid = _room_id(room, session)
    dedup_key = f"draft_analysis_attempted:{rid}"
    if _already_logged(session, dedup_key):
        return
    teams = _team_names(room)
    matchup = _matchup_label(teams)
    metrics = live_draft_activity_metrics(
        room,
        session=session,
        activity_type="draft_analysis_attempted",
        feature="Draft Simulation Test Mode",
    )
    err = str(error or "").strip()
    if err:
        metrics["analysis_error"] = err[:240]
    _record_draft_event(
        "draft_analysis_attempted",
        page="Draft Simulation Test Mode",
        metrics=metrics,
        summary="Draft analysis incomplete" + (f" — {matchup}" if matchup else ""),
        resume_key=f"bb:live_draft:{rid}" if rid else "bb:live_draft",
        resume_title="Review completed draft",
        resume_subtitle=matchup or "Retry Analyze Completed Draft",
        session=session,
    )
    try:
        log_completed_live_draft(room or {}, session=session)
    except Exception:
        pass


def after_live_draft_pick_committed(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Log pick progress and completion after a successful pick commit."""
    if not isinstance(room, dict):
        return
    try:
        log_live_draft_pick(room, session=session)
    except Exception:
        pass
    try:
        from live_draft_safe_mode import is_draft_truly_complete

        if is_draft_truly_complete(room):
            log_completed_live_draft(room, session=session)
    except ImportError:
        status = str(room.get("status") or "").strip().lower()
        if status == "complete":
            log_completed_live_draft(room, session=session)


def render_draft_activity_write_debug(st: Any) -> None:
    """Temporary dev panel: last draft activity write attempt (after Analyze Completed Draft)."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except ImportError:
        return
    diag = st.session_state.get("_draft_activity_write_debug")
    if not isinstance(diag, dict) or not diag:
        return
    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT, format_build_label
    except ImportError:
        GIT_COMMIT_SHORT = "unknown"
        format_build_label = lambda: "unknown"  # noqa: E731
    with st.expander("Dev: Draft activity write (Command Center)", expanded=True):
        st.caption(f"Build `{format_build_label()}` · commit `{GIT_COMMIT_SHORT}` (need ad97004+)")
        st.json(diag)
