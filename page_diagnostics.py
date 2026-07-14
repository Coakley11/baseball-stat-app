"""Consolidated per-page developer diagnostics — one expander, bottom placement."""

from __future__ import annotations

from typing import Any, Callable

from developer_diagnostics_ui import render_page_developer_diagnostics

# When True, inline diagnostic expanders are suppressed; footer panel collects traces.
CONSOLIDATED_PAGE_DIAGNOSTICS = True


def inline_diagnostics_enabled(developer_mode: bool) -> bool:
    """True only when scattered inline diagnostic expanders should render."""
    return bool(developer_mode) and not CONSOLIDATED_PAGE_DIAGNOSTICS


def suppress_inline_diagnostics(developer_mode: bool) -> bool:
    """True when inline panels should be hidden in favor of consolidated footer."""
    return bool(developer_mode) and CONSOLIDATED_PAGE_DIAGNOSTICS


def _safe(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception as exc:
        return {"error": str(exc)} if default is None else default


def _section_identity(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "_suite_auth_user_id",
        "_suite_auth_external_id",
        "_suite_auth_email",
        "room_your_team",
        "draft_room_participant_team",
        "active_shared_draft_room_code",
    ):
        val = session.get(key)
        if val:
            out[key] = val
    try:
        from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY, ACTIVE_PARTICIPANT_TEAM_KEY

        if session.get(ACTIVE_PARTICIPANT_ID_KEY):
            out["participant_id"] = session.get(ACTIVE_PARTICIPANT_ID_KEY)
        if session.get(ACTIVE_PARTICIPANT_TEAM_KEY):
            out["participant_team"] = session.get(ACTIVE_PARTICIPANT_TEAM_KEY)
    except ImportError:
        pass
    try:
        from suite_identity_guard import summarize_identity_guard

        out["identity_guard"] = _safe(lambda: summarize_identity_guard(session), {})
    except ImportError:
        pass
    return out


def _section_active_source(session: dict[str, Any], page: str) -> dict[str, Any]:
    out: dict[str, Any] = {"page": page}
    try:
        from fantasy_context_source import resolve_fantasy_workflow_source_descriptor

        desc = resolve_fantasy_workflow_source_descriptor(session)
        if isinstance(desc, dict):
            out.update(
                {
                    "display_name": desc.get("display_name"),
                    "draft_type_label": desc.get("draft_type_label"),
                    "my_team_name": desc.get("my_team_name"),
                    "source_kind": desc.get("source_kind"),
                }
            )
            if desc.get("draft_id"):
                out["draft_id"] = desc.get("draft_id")
            if desc.get("league_context_id"):
                out["league_context_id"] = desc.get("league_context_id")
            if desc.get("canonical_league_id"):
                out["canonical_league_id"] = desc.get("canonical_league_id")
    except ImportError:
        pass
    try:
        from fantasy_context_source import collect_saved_vs_effective_source_diagnostics

        layers = collect_saved_vs_effective_source_diagnostics(session)
        out["saved_selection"] = {
            "saved_active_draft_id": layers.get("saved_active_draft_id"),
            "saved_active_context_id": layers.get("saved_active_context_id"),
            "saved_active_name": layers.get("saved_active_name"),
            "saved_active_team": layers.get("saved_active_team"),
        }
        out["effective_workflow_source"] = {
            "effective_source_kind": layers.get("effective_source_kind"),
            "effective_context_id": layers.get("effective_context_id"),
            "effective_team": layers.get("effective_team"),
            "effective_roster_team_names": layers.get("effective_roster_team_names"),
            "effective_board_pick_count": layers.get("effective_board_pick_count"),
            "effective_context_fingerprint": layers.get("effective_context_fingerprint"),
            "descriptor_cache_fingerprint": layers.get("descriptor_cache_fingerprint"),
            "context_coherent": layers.get("context_coherent"),
        }
    except ImportError:
        pass
    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session, respect_source_priority=False)
        if isinstance(ctx, dict):
            out["active_context_type"] = ctx.get("context_type")
            out["active_context_name"] = ctx.get("display_name") or ctx.get("league_name")
    except ImportError:
        pass
    try:
        from resolved_fantasy_context import collect_resolved_fantasy_context_diagnostics

        resolved = collect_resolved_fantasy_context_diagnostics(session)
        if resolved:
            out["Resolved fantasy context"] = resolved
    except ImportError:
        pass
    return out


def _section_persistence(session: dict[str, Any]) -> dict[str, Any]:
    try:
        from workflow_persist_guard import build_saved_draft_library_diagnostics

        return dict(build_saved_draft_library_diagnostics(session))
    except ImportError:
        return {}


def _section_draft_board(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        out["live_room_status"] = room.get("status")
        out["current_pick_index"] = room.get("current_pick_index")
        out["board_len"] = len(room.get("draft_board") or [])
        out["draft_room_id"] = room.get("draft_room_id")
    try:
        from draft_room_state import effective_board_pick_count

        out["effective_board_picks"] = int(effective_board_pick_count(session))
    except ImportError:
        pass
    progress = session.get("_draft_assistant_progress_diag")
    if isinstance(progress, dict):
        out["draft_assistant_progress"] = progress
    return out


def _section_shared_league(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "_draft_room_conflict_notice",
        "_draft_room_membership_notice",
        "_shared_league_library_sync_trace",
        "_live_draft_shared_league_diag",
    ):
        if session.get(key):
            out[key] = session.get(key)
    try:
        from draft_room_diagnostics import get_shared_room_diagnostics

        out["shared_room"] = _safe(lambda: get_shared_room_diagnostics(session), {})
    except ImportError:
        pass
    pair = session.get("_saved_draft_library_active_pair_diag")
    if isinstance(pair, dict):
        out["active_library_pair"] = {
            k: pair.get(k)
            for k in (
                "active_draft_archive_id",
                "persisted_active_context_id",
                "active_pair_coherent",
                "active_pair_repair_reason",
                "repair_applied",
            )
        }
    return out


def _section_performance(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    perf = session.get("_page_perf_ns")
    if isinstance(perf, dict):
        timings = perf.get("timings") or {}
        if timings:
            out["page_timings_ms"] = {k: round(float(v) * 1000.0, 2) for k, v in timings.items()}
    try:
        from deployed_page_timing import summarize_deployed_page_timing

        page = str(session.get("_page_render_last_page") or session.get("active_page") or "")
        if page:
            out["deployed_page_timing"] = summarize_deployed_page_timing(session, page)
        seq = session.get("_deployed_page_timing_sequence")
        if isinstance(seq, list) and seq:
            out["deployed_page_timing_sequence"] = seq[-12:]
    except ImportError:
        pass
    out["warm_startup_skipped"] = bool(session.get("_baseball_warm_startup_skipped"))
    if session.get("_suite_page_change_save_skipped"):
        out["page_change_save_skipped"] = session.get("_suite_page_change_save_skipped")
    actions = session.get("_live_draft_perf_actions")
    if isinstance(actions, list) and actions:
        out["recent_live_draft_actions"] = actions[-8:]
    for key in (
        "_live_draft_timer_diag",
        "_live_draft_autopick_diag",
        "_live_draft_poll_diag",
        "_live_draft_safe_mode_diag",
        "_draft_commit_diag",
    ):
        if session.get(key):
            out[key.lstrip("_")] = session.get(key)
    return out


def _section_repair_history(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if session.get("_creation_origin_repair_done"):
        out["creation_origin_repair_done"] = True
    origin = session.get("_draft_origin_repair_diag")
    if isinstance(origin, dict):
        out["draft_origin_repair"] = origin
    try:
        from fantasy_league_context import get_origin_repair_decisions

        decisions = get_origin_repair_decisions(session)
    except ImportError:
        decisions = session.get("library_origin_repair_decisions") or session.get(
            "_draft_origin_repair_decisions"
        )
    if isinstance(decisions, list) and decisions:
        out["draft_origin_repair_decisions"] = decisions
    repair_trace = (
        session.get("library_origin_migration_trace")
        or session.get("_library_repair_last_trace")
    )
    if isinstance(repair_trace, dict) and repair_trace:
        out["library_repair_last_trace"] = repair_trace
    invite = session.get("_league_invite_flow_diag")
    if invite:
        out["invite_flow"] = invite
    return out


def collect_page_diagnostics(session: dict[str, Any], page: str) -> dict[str, dict[str, Any]]:
    """Gather diagnostic sections without rendering UI."""
    sections: dict[str, dict[str, Any]] = {
        "Identity": _section_identity(session),
        "Active source": _section_active_source(session, page),
        "Persistence": _section_persistence(session),
        "Draft board/progress": _section_draft_board(session),
        "Shared league": _section_shared_league(session),
        "Performance": _section_performance(session),
        "Repair history": _section_repair_history(session),
    }
    try:
        from account_fantasy_preferences import collect_account_preference_diagnostics

        pref_diag = collect_account_preference_diagnostics(session)
        if pref_diag:
            sections["Account preferences sync"] = pref_diag
    except ImportError:
        pass
    extra = session.pop("_page_diag_extra_sections", None)
    if isinstance(extra, dict):
        sections.update(extra)
    return {name: data for name, data in sections.items() if data}


def record_page_diagnostic_section(session: dict[str, Any], name: str, data: dict[str, Any]) -> None:
    """Allow page code to append a section when consolidated mode is on."""
    bucket = session.setdefault("_page_diag_extra_sections", {})
    if isinstance(bucket, dict) and data:
        bucket[str(name)] = dict(data)


def render_consolidated_diagnostics(
    st: Any,
    session: dict[str, Any],
    page: str,
    *,
    developer_mode: bool,
    summary: dict[str, Any] | None = None,
) -> None:
    """Render one collapsed Developer diagnostics expander at page bottom."""
    if not developer_mode or not CONSOLIDATED_PAGE_DIAGNOSTICS:
        session.pop("_page_diag_extra_sections", None)
        return
    sections = collect_page_diagnostics(session, page)
    base_summary = {"page": page}
    if summary:
        base_summary.update(summary)
    render_page_developer_diagnostics(
        st,
        developer_mode=True,
        summary=base_summary,
        detail_sections=sections,
    )
