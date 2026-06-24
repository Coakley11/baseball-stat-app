"""Live Draft Room runtime diagnostics — acceptance table for deployed Dell/phone testing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from draft_scoring_pool import DEFAULT_SCORING_TRACE_PLAYERS, SCORING_TRACE_COLUMNS, trace_player_scoring

_PIPELINE_KEY = "_draft_scoring_pipeline_trace"
_LEAVE_TRACE_KEY = "_draft_room_leave_trace"
_PREPARE_TRACE_KEY = "_draft_room_prepare_trace"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _workspace_profile(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import resolve_workspace_id

        return str(resolve_workspace_id(st=type("S", (), {"session_state": session})()))
    except Exception:
        pass
    try:
        from suite_auth import resolve_auth_external_id

        return str(resolve_auth_external_id(session) or "")
    except Exception:
        return ""


def _snapshot_identity(session: dict[str, Any]) -> dict[str, Any]:
    auth_email = ""
    auth_user_id = ""
    try:
        from suite_auth import AUTH_USER_ID_KEY, current_auth_email, is_authenticated

        if is_authenticated(session):
            auth_email = str(current_auth_email(session) or "")
            auth_user_id = str(session.get(AUTH_USER_ID_KEY) or "")
    except Exception:
        pass

    participant_id = ""
    assigned_team = ""
    registry_team = ""
    membership_blob_team = ""
    code = ""
    try:
        from draft_room_participant_state import (
            active_participant_team,
            membership_team_for_participant,
            resolve_participant_id,
        )

        participant_id = resolve_participant_id(session)
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        if code:
            assigned_team = active_participant_team(session) or ""
            membership_blob_team = membership_team_for_participant(session, code, participant_id=participant_id)
            try:
                from draft_room_shared_state import load_shared_room

                doc = load_shared_room(code)
                if isinstance(doc, dict):
                    meta = dict((doc.get("participants") or {}).get(participant_id) or {})
                    registry_team = str(meta.get("assigned_team") or "")
            except Exception:
                pass
    except Exception:
        pass

    displayed_team, display_source = resolve_displayed_team_label(session)
    return {
        "auth_email": auth_email,
        "auth_user_id": auth_user_id,
        "workspace_profile": _workspace_profile(session),
        "active_shared_draft_room_code": code or None,
        "multiplayer_joined": bool(code),
        "participant_id": participant_id or None,
        "assigned_team": assigned_team or None,
        "registry_assigned_team": registry_team or None,
        "membership_blob_team": membership_blob_team or None,
        "room_your_team": session.get("room_your_team"),
        "displayed_team_label": displayed_team or None,
        "displayed_team_source": display_source,
    }


def resolve_displayed_team_label(session: dict[str, Any]) -> tuple[str, str]:
    """Return (label, source) for what the Live Draft UI should show."""
    try:
        from draft_room_context import is_multiplayer_draft_active, active_participant_team

        if is_multiplayer_draft_active(session):
            team = active_participant_team(session)
            if team:
                return team, "active_participant_team"
            return "", "active_participant_team(missing)"
    except ImportError:
        pass

    room = session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        for key, src in (("user_team", "live_draft_room.config.user_team"), ("your_team", "live_draft_room.config.your_team")):
            val = str(cfg.get(key) or "").strip()
            if val:
                return val, src
        teams = room.get("teams")
        if isinstance(teams, list) and teams:
            return str(teams[0]).strip(), "live_draft_room.teams[0]"

    ry = str(session.get("room_your_team") or "").strip()
    if ry:
        return ry, "room_your_team"

    try:
        from global_fantasy_settings_state import GLOBAL_TEAM_KEY

        gt = str(session.get(GLOBAL_TEAM_KEY) or "").strip()
        if gt:
            return gt, "global_fantasy_settings.room_your_team"
    except ImportError:
        pass

    return "", "none"


def capture_leave_state_before(session: dict[str, Any]) -> None:
    session[_LEAVE_TRACE_KEY] = {
        "clicked_at": _utc_now_iso(),
        "before": _snapshot_identity(session),
        "after": None,
        "room_code": str(session.get("active_shared_draft_room_code") or "").strip().upper() or None,
        "membership_marked_left": False,
        "rehydrated_after_leave": False,
        "rehydrate_source": None,
    }


def capture_leave_state_after(session: dict[str, Any], *, membership_marked_left: bool) -> None:
    trace = dict(session.get(_LEAVE_TRACE_KEY) or {})
    trace["after"] = _snapshot_identity(session)
    trace["membership_marked_left"] = membership_marked_left
    session[_LEAVE_TRACE_KEY] = trace


def note_prepare_global_rehydrate(session: dict[str, Any], *, room_code: str, source: str) -> None:
    leave = session.get(_LEAVE_TRACE_KEY)
    if isinstance(leave, dict) and leave.get("after") is not None:
        if not str(session.get("active_shared_draft_room_code") or "").strip():
            return
        leave = dict(leave)
        leave["rehydrated_after_leave"] = True
        leave["rehydrate_source"] = source
        leave["rehydrated_room_code"] = room_code
        leave["rehydrated_at"] = _utc_now_iso()
        session[_LEAVE_TRACE_KEY] = leave
    prep = {
        "at": _utc_now_iso(),
        "room_code": room_code,
        "source": source,
        "identity": _snapshot_identity(session),
    }
    session[_PREPARE_TRACE_KEY] = prep


def record_scoring_pipeline_stage(
    session: dict[str, Any],
    stage: str,
    pool: pd.DataFrame | None,
    *,
    document: dict[str, Any] | None = None,
) -> None:
    """Record Aaron Judge / Ohtani / Soto scoring fields at a pipeline stage."""
    trace_root = dict(session.get(_PIPELINE_KEY) or {})
    if pool is not None and hasattr(pool, "columns"):
        for player, fields in trace_player_scoring(pool).items():
            bucket = dict(trace_root.get(player) or {})
            bucket[stage] = fields
            trace_root[player] = bucket
    if document is not None:
        room_blob = document.get("room")
        if isinstance(room_blob, dict):
            records = room_blob.get("pool_records") or []
            columns = room_blob.get("pool_columns") or []
            if records:
                frame = pd.DataFrame(records)
                if columns:
                    ordered = [c for c in columns if c in frame.columns]
                    extras = [c for c in frame.columns if c not in ordered]
                    frame = frame[ordered + extras]
                for player, fields in trace_player_scoring(frame).items():
                    bucket = dict(trace_root.get(player) or {})
                    bucket[stage] = fields
                    trace_root[player] = bucket
    session[_PIPELINE_KEY] = trace_root


def _deploy_marker_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    try:
        from suite_deploy_marker import format_deploy_caption, runtime_feature_verification

        rows.append(("Deploy", "caption", format_deploy_caption()))
        for key, value in runtime_feature_verification().items():
            rows.append(("Deploy", key, str(value)))
    except ImportError:
        rows.append(("Deploy", "marker", "suite_deploy_marker unavailable"))
    return rows


def get_runtime_diagnostic_rows(session: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Flat rows for side-by-side diagnostic table: section, field, value."""
    rows: list[tuple[str, str, str]] = _deploy_marker_rows()
    ident = _snapshot_identity(session)
    for key in (
        "auth_email",
        "auth_user_id",
        "workspace_profile",
        "active_shared_draft_room_code",
        "multiplayer_joined",
        "participant_id",
        "assigned_team",
        "registry_assigned_team",
        "membership_blob_team",
        "room_your_team",
        "displayed_team_label",
        "displayed_team_source",
    ):
        rows.append(("Identity", key, str(ident.get(key) if ident.get(key) is not None else "—")))

    leave = session.get(_LEAVE_TRACE_KEY)
    if isinstance(leave, dict):
        before = leave.get("before") if isinstance(leave.get("before"), dict) else {}
        after = leave.get("after") if isinstance(leave.get("after"), dict) else {}
        for key in (
            "active_shared_draft_room_code",
            "participant_id",
            "assigned_team",
            "room_your_team",
        ):
            rows.append(("Leave (before)", key, str(before.get(key) if before.get(key) is not None else "—")))
            rows.append(("Leave (after)", key, str(after.get(key) if after is not None and after.get(key) is not None else "—")))
        rows.append(("Leave", "membership_marked_left", str(leave.get("membership_marked_left"))))
        rows.append(("Leave", "rehydrated_after_leave", str(leave.get("rehydrated_after_leave"))))
        rows.append(("Leave", "rehydrate_source", str(leave.get("rehydrate_source") or "—")))

    prep = session.get(_PREPARE_TRACE_KEY)
    if isinstance(prep, dict):
        rows.append(("Prepare", "last_rehydrate_at", str(prep.get("at") or "—")))
        rows.append(("Prepare", "last_rehydrate_source", str(prep.get("source") or "—")))
        rows.append(("Prepare", "last_rehydrate_room", str(prep.get("room_code") or "—")))

    pipeline = session.get(_PIPELINE_KEY) or {}
    stages = (
        "original_source",
        "compact_serialized",
        "restored",
        "displayed",
    )
    for player in DEFAULT_SCORING_TRACE_PLAYERS:
        pdata = pipeline.get(player) if isinstance(pipeline, dict) else {}
        if not isinstance(pdata, dict):
            continue
        for stage in stages:
            snap = pdata.get(stage)
            if not isinstance(snap, dict):
                rows.append((f"Scoring {player}", stage, "—"))
                continue
            if not snap.get("found"):
                rows.append((f"Scoring {player}", stage, "not in pool"))
                continue
            for col in SCORING_TRACE_COLUMNS:
                label = f"{stage}.{col}"
                rows.append((f"Scoring {player}", label, str(snap.get(col) if snap.get(col) is not None else "—")))

    return rows


def render_runtime_diagnostic_table(st: Any, session: dict[str, Any]) -> None:
    """Single acceptance table visible in Live Draft Room (dev tools)."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except Exception:
        return

    rows = get_runtime_diagnostic_rows(session)
    try:
        from suite_deploy_marker import format_deploy_caption, runtime_feature_verification

        verify = runtime_feature_verification()
        st.caption(f"**Dev build** · {format_deploy_caption()}")
        st.caption(
            f"Runtime fixes loaded: leave={verify.get('leave_room_fix')} · "
            f"leave_api={verify.get('leave_shared_draft_room')} · "
            f"diagnostics={verify.get('runtime_diagnostics')} · "
            f"mp_gen={verify.get('mp_draft_code_generation')} · "
            f"source={verify.get('deploy_commit_source')}"
        )
    except ImportError:
        pass
    with st.expander("Multiplayer runtime diagnostics (acceptance)", expanded=True):
        st.caption(
            "Deployed runtime values — verify leave, identity, and scoring pipeline before calling fixes done."
        )
        try:
            import pandas as pd

            df = pd.DataFrame(rows, columns=["Section", "Field", "Value"])
            st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception:
            for section, field, value in rows:
                st.text(f"{section} · {field}: {value}")
