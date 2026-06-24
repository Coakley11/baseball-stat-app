"""Shared draft room diagnostics for acceptance testing."""

from __future__ import annotations

import json
from typing import Any


def get_shared_room_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Structured diagnostics snapshot for multiplayer draft rooms."""
    try:
        from draft_room_context import get_global_draft_context, is_multiplayer_draft_active
    except ImportError:
        return {"active": False}

    if not is_multiplayer_draft_active(session):
        return {"active": False}

    ctx = get_global_draft_context(session)
    meta = dict(session.get("draft_room_shared_meta") or {})
    room = session.get("live_draft_room")
    progress: dict[str, Any] = {}
    shared_doc_status = ""
    scoring_trace: dict[str, Any] = {}
    if isinstance(room, dict):
        try:
            from live_draft_state import analyze_live_draft_progress

            progress = analyze_live_draft_progress(room)
        except ImportError:
            progress = {}
        pick_index = room.get("current_pick_index")
        drafted_count = len(room.get("drafted_player_ids") or [])
        pool = room.get("pool")
        if pool is not None and hasattr(pool, "__len__"):
            try:
                pool_count = len(pool)
            except Exception:
                pool_count = None
        try:
            from draft_scoring_pool import trace_player_scoring

            if pool is not None and hasattr(pool, "columns"):
                scoring_trace = trace_player_scoring(pool)
        except ImportError:
            scoring_trace = {}
    else:
        pick_index = None
        drafted_count = None
        pool_count = None

    code = str(ctx.get("room_code") or "").strip().upper()
    if code:
        try:
            from draft_room_shared_state import load_shared_room

            doc = load_shared_room(code)
            if isinstance(doc, dict):
                shared_doc_status = str(doc.get("status") or "")
        except ImportError:
            pass

    button_diag: dict[str, Any] = {}
    try:
        from draft_actions import draft_button_diagnostics

        button_diag = draft_button_diagnostics(session)
    except ImportError:
        pass

    egress_diag = _egress_diag(session)

    return {
        "active": True,
        "room_code": ctx.get("room_code"),
        "draft_room_id": ctx.get("draft_room_id"),
        "assigned_team": ctx.get("participant_team"),
        "participant_id": ctx.get("participant_id"),
        "backend": ctx.get("shared_storage_backend") or "unknown",
        "revision": ctx.get("shared_revision"),
        "last_sync_time": meta.get("last_sync_at") or ctx.get("shared_updated_at"),
        "last_sync_reason": meta.get("last_sync_reason") or meta.get("reason"),
        "is_room_host": bool(ctx.get("is_room_host")),
        "room_status": ctx.get("room_status"),
        "shared_document_status": shared_doc_status or None,
        "draft_status": progress.get("draft_status"),
        "draft_complete_reason": progress.get("draft_complete_reason"),
        "current_pick_index": progress.get("current_pick_index", pick_index),
        "current_pick": progress.get("current_pick"),
        "total_picks": progress.get("total_picks"),
        "drafted_count": progress.get("drafted_player_count", drafted_count),
        "draft_board_count": progress.get("draft_board_count"),
        "pool_count": pool_count,
        "scoring_trace": scoring_trace,
        "on_clock_team": button_diag.get("on_clock_team"),
        "is_my_turn": button_diag.get("is_my_turn"),
        "disable_reason": button_diag.get("disable_reason"),
        "draft_enabled": button_diag.get("draft_enabled"),
        "queue_len": len(session.get("draft_queue") or []),
        "watchlist_len": len(session.get("draft_assistant_focus_players") or []),
        "conflict_notice": session.get("_draft_room_conflict_notice"),
        "room_payload_bytes": session.get("_shared_room_last_payload_bytes"),
        **egress_diag,
        **_participant_membership_diag(session),
    }


def _egress_diag(session: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "egress_reads_render": None,
        "egress_writes_render": None,
        "egress_bytes_downloaded": None,
        "egress_bytes_uploaded": None,
        "workspace_payload_bytes": None,
    }
    try:
        from suite_egress_trace import get_run_egress_summary

        summary = get_run_egress_summary()
        out["egress_reads_render"] = summary.get("reads")
        out["egress_writes_render"] = summary.get("writes")
        out["egress_bytes_downloaded"] = summary.get("bytes_in")
        out["egress_bytes_uploaded"] = summary.get("bytes_out")
    except ImportError:
        pass
    cloud = session.get("_suite_last_cloud_payload")
    if isinstance(cloud, dict):
        try:
            out["workspace_payload_bytes"] = len(json.dumps(cloud, ensure_ascii=False, default=str).encode("utf-8"))
        except Exception:
            pass
    return out


def _participant_membership_diag(session: dict[str, Any]) -> dict[str, Any]:
    try:
        from draft_room_participant_state import get_participant_membership_diagnostics

        extra = get_participant_membership_diagnostics(session)
        return {
            "auth_email": extra.get("auth_email"),
            "auth_user_id": extra.get("auth_user_id"),
            "membership_team": extra.get("membership_team"),
            "membership_blob_team": extra.get("membership_blob_team"),
            "membership_assigned_team": extra.get("membership_assigned_team"),
            "registry_assigned_team": extra.get("registry_assigned_team"),
            "participant_registry_found": extra.get("participant_registry_found"),
            "displayed_team": extra.get("displayed_team"),
            "displayed_team_source": extra.get("displayed_team_source"),
            "assignment_failure_reason": extra.get("assignment_failure_reason"),
            "active_queue_key": extra.get("active_queue_key"),
            "active_watchlist_focus_key": extra.get("active_watchlist_focus_key"),
            "active_watchlist_favorites_key": extra.get("active_watchlist_favorites_key"),
            "room_participant_registry": extra.get("room_participant_registry"),
            "persisted_membership_blob": extra.get("persisted_membership_blob"),
        }
    except ImportError:
        return {}


def render_shared_room_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Compact dev/acceptance diagnostics panel."""
    diag = get_shared_room_diagnostics(session)
    if not diag.get("active"):
        return

    with st.expander("Room diagnostics", expanded=False):
        st.caption("Acceptance / dev snapshot — use to verify multiplayer sync.")
        rows = [
            ("Room code", diag.get("room_code") or "—"),
            ("Session draft id", diag.get("draft_room_id") or "—"),
            ("Assigned team", diag.get("assigned_team") or "—"),
            ("Participant id", diag.get("participant_id") or "—"),
            ("Auth email", diag.get("auth_email") or "—"),
            ("Auth user id", diag.get("auth_user_id") or "—"),
            ("Registry team", diag.get("registry_assigned_team") or "—"),
            ("Membership team (blob)", diag.get("membership_blob_team") or diag.get("membership_team") or "—"),
            ("Registry found", str(diag.get("participant_registry_found"))),
            ("Displayed team", diag.get("displayed_team") or "—"),
            ("Displayed team source", diag.get("displayed_team_source") or "—"),
            ("Assignment failure", diag.get("assignment_failure_reason") or "—"),
            ("Backend", diag.get("backend") or "—"),
            ("Revision", str(diag.get("revision") if diag.get("revision") is not None else "—")),
            ("Last sync", diag.get("last_sync_time") or "—"),
            ("Sync reason", diag.get("last_sync_reason") or "—"),
            ("Host", "yes" if diag.get("is_room_host") else "no"),
            ("Shared doc status", diag.get("shared_document_status") or "—"),
            ("Draft status", diag.get("draft_status") or "—"),
            ("Draft complete reason", diag.get("draft_complete_reason") or "—"),
            ("Current pick", str(diag.get("current_pick") if diag.get("current_pick") is not None else "—")),
            (
                "Pick index",
                str(diag.get("current_pick_index") if diag.get("current_pick_index") is not None else "—"),
            ),
            ("Total picks", str(diag.get("total_picks") if diag.get("total_picks") is not None else "—")),
            ("On clock team", diag.get("on_clock_team") or "—"),
            ("Is my turn", str(diag.get("is_my_turn"))),
            ("Draft enabled", str(diag.get("draft_enabled"))),
            ("Disable reason", diag.get("disable_reason") or "—"),
            ("Queue len", str(diag.get("queue_len"))),
            ("Watchlist len", str(diag.get("watchlist_len"))),
            ("Drafted", str(diag.get("drafted_count") if diag.get("drafted_count") is not None else "—")),
            ("Board picks", str(diag.get("draft_board_count") if diag.get("draft_board_count") is not None else "—")),
            ("Pool count", str(diag.get("pool_count") if diag.get("pool_count") is not None else "—")),
            ("Room payload bytes", str(diag.get("room_payload_bytes") or "—")),
            ("Workspace payload bytes", str(diag.get("workspace_payload_bytes") or "—")),
            ("Reads / render", str(diag.get("egress_reads_render") or "—")),
            ("Writes / render", str(diag.get("egress_writes_render") or "—")),
            ("Bytes downloaded", str(diag.get("egress_bytes_downloaded") or "—")),
            ("Bytes uploaded", str(diag.get("egress_bytes_uploaded") or "—")),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        trace = diag.get("scoring_trace") or {}
        if trace:
            st.markdown("**Scoring trace (top players)**")
            for player, fields in trace.items():
                if not isinstance(fields, dict):
                    continue
                if not fields.get("found"):
                    st.text(f"{player}: not in pool")
                    continue
                bits = [
                    f"EFV={fields.get('Expected Fantasy Value')}",
                    f"Model={fields.get('Model Rank')}",
                    f"Market={fields.get('Market Rank')}",
                    f"Edge={fields.get('Fantasy Edge')}",
                    f"ADP Rank={fields.get('ADP Rank')}",
                    f"Sleeper={fields.get('Sleeper Score')}",
                ]
                st.text(f"{player}: " + ", ".join(str(b) for b in bits))
        if diag.get("conflict_notice"):
            st.warning(str(diag["conflict_notice"]))


def render_compact_pool_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Dev diagnostics for compact shared-room pool column coverage."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except Exception:
        return

    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return
    pool = room.get("pool")
    if pool is None or not hasattr(pool, "columns"):
        return

    try:
        from draft_scoring_pool import analyze_compact_pool

        diag = analyze_compact_pool(pool)
    except ImportError:
        return

    scoring_diag = room.get("_live_draft_pool_scoring_diag")
    with st.expander("Compact pool scoring (dev)", expanded=False):
        source_cols = diag.get("source_columns") or []
        if source_cols:
            st.text(f"Source columns ({len(source_cols)}): {', '.join(source_cols[:30])}{'…' if len(source_cols) > 30 else ''}")
        st.text(f"Pool players: {diag.get('pool_count')}")
        st.text(f"Compact columns ({diag.get('compact_column_count')}): {', '.join(diag.get('compact_columns') or [])}")
        quality = diag.get("scoring_quality") or {}
        for col, counts in quality.items():
            st.text(f"{col}: real={counts.get('real', 0)} default={counts.get('default', 0)}")
        missing = diag.get("missing_required") or []
        if missing:
            st.text(f"Missing from source pool: {', '.join(missing[:20])}{'…' if len(missing) > 20 else ''}")
        defaults = diag.get("default_filled_counts") or {}
        if defaults:
            st.warning("Default-filled scoring columns: " + ", ".join(f"{k} ({v})" for k, v in defaults.items()))
        else:
            st.caption("No default-filled rank/edge columns.")
        derived = diag.get("derived_columns") or []
        if derived:
            st.caption("Derived: " + ", ".join(derived))
        if isinstance(scoring_diag, dict) and scoring_diag.get("default_filled_counts"):
            st.text(f"Last scoring hydrate defaults: {scoring_diag.get('default_filled_counts')}")


def render_join_assignment_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Team assignment trace after join or restore (acceptance)."""
    raw = session.get("_draft_room_join_assignment_diag")
    if not isinstance(raw, dict):
        return
    with st.expander("Team assignment (join/restore)", expanded=not raw.get("displayed_team")):
        rows = [
            ("room_code", raw.get("room_code") or "—"),
            ("auth_user_id", raw.get("auth_user_id") or "—"),
            ("participant_id", raw.get("participant_id") or "—"),
            ("participant_registry_found", str(raw.get("participant_registry_found"))),
            ("registry_assigned_team", raw.get("registry_assigned_team") or "—"),
            ("membership_assigned_team", raw.get("membership_assigned_team") or "—"),
            ("displayed_team", raw.get("displayed_team") or "—"),
            ("displayed_team_source", raw.get("displayed_team_source") or "—"),
            ("assignment_failure_reason", raw.get("assignment_failure_reason") or "—"),
            ("assignment_source", raw.get("assignment_source") or "—"),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if raw.get("assignment_failure_reason") and not raw.get("displayed_team"):
            st.error(
                "Team assignment is missing — recommendations and draft buttons may be disabled. "
                "Try **Refresh board now** or re-join with the share code."
            )


def render_shared_room_create_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Show post-create verification snapshot (always after create attempt)."""
    raw = session.get("_draft_room_create_diag")
    if not isinstance(raw, dict) or not raw.get("create_button_clicked"):
        return
    save = raw.get("save_result") if isinstance(raw.get("save_result"), dict) else {}
    loaded = raw.get("immediate_load") if isinstance(raw.get("immediate_load"), dict) else {}
    load_meta = raw.get("load_result") if isinstance(raw.get("load_result"), dict) else {}
    verified = bool(
        raw.get("supabase_save_success")
        and raw.get("immediate_load_success")
        and raw.get("valid_runtime_room")
        and raw.get("shared_room_code_displayed_to_user")
    )
    title = "Shared room create — verified" if verified else "Shared room create — failed or incomplete"
    with st.expander(title, expanded=not verified):
        st.caption(
            "**Share code** (6 characters) is what other managers enter to join. "
            "**Internal session ID** is local-only and must not be used as a join code."
        )
        rows = [
            ("create_button_clicked", str(raw.get("create_button_clicked"))),
            ("generated_share_code", raw.get("generated_share_code") or "—"),
            ("internal_draft_session_id", raw.get("internal_draft_session_id") or save.get("draft_room_id") or "—"),
            ("supabase_save_attempted", str(raw.get("supabase_save_attempted"))),
            ("supabase_save_success", str(raw.get("supabase_save_success"))),
            ("immediate_load_success", str(raw.get("immediate_load_success"))),
            ("valid_runtime_room", str(raw.get("valid_runtime_room"))),
            ("shared_room_code_displayed_to_user", str(raw.get("shared_room_code_displayed_to_user"))),
            ("Backend", save.get("backend") or loaded.get("backend") or load_meta.get("backend") or "—"),
            ("Save pool count", str(save.get("pool_count") if save.get("pool_count") is not None else "—")),
            ("Immediate load found", str(load_meta.get("found"))),
            ("Immediate load pool count", str(loaded.get("pool_count") if loaded.get("pool_count") is not None else "—")),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if load_meta.get("query_error"):
            st.code(str(load_meta.get("query_error"))[:2000])
        if not verified:
            st.error(
                "Do **not** share the internal session ID. "
                "Fix the error above and tap **Create Shared Draft Room** again."
            )


def render_shared_room_join_load_diagnostics(st: Any, session: dict[str, Any]) -> None:
    raw = session.get("_draft_room_join_load_diag")
    if not isinstance(raw, dict):
        return
    with st.expander("Join lookup (dev)", expanded=True):
        rows = [
            ("Room code queried", raw.get("room_code_queried") or "—"),
            ("Backend", raw.get("backend") or "—"),
            ("Found", str(raw.get("found"))),
            ("Reason", raw.get("reason") or "—"),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if raw.get("query_error"):
            st.code(str(raw.get("query_error"))[:2000])
