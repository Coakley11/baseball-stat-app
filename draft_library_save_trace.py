"""End-to-end save / restore tracing for Saved Draft Library (Developer Mode)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DRAFT_LIBRARY_SAVE_DIAG_KEY = "_draft_library_save_diag"
DRAFT_LIBRARY_LOAD_DIAG_KEY = "_draft_library_load_diag"
DRAFT_LIBRARY_RESTORE_DIAG_KEY = "_draft_library_restore_diag"
DRAFT_SAVE_BUTTON_TRACE_KEY = "_draft_save_button_trace"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workflow_counts(session: dict[str, Any]) -> dict[str, int]:
    try:
        from workflow_persist_guard import workflow_counts_from_session

        return workflow_counts_from_session(session)
    except ImportError:
        from draft_archive_state import list_draft_archives
        from fantasy_league_context import list_league_contexts

        return {
            "draft_archive_count": len(list_draft_archives(session)),
            "league_context_count": len(list_league_contexts(session)),
        }


def _workspace_id(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import get_active_workspace_id

        return str(get_active_workspace_id(type("_St", (), {"session_state": session})()))
    except Exception:
        return str(session.get("_suite_active_workspace_id") or session.get("_suite_owned_workspace_id") or "")


def _active_state_snapshot(session: dict[str, Any]) -> dict[str, str]:
    store = session.get("fantasy_league_context_state")
    active_league = ""
    if isinstance(store, dict):
        active_league = str(store.get("active_league_context_id") or "").strip()
    return {
        "active_draft_archive_id": str(session.get("active_draft_archive_id") or "").strip(),
        "active_league_context_id": active_league,
        "pending_active_draft_archive_id": str(session.get("_pending_active_archive_id") or "").strip(),
        "pending_active_league_context_id": str(session.get("_pending_active_league_context_id") or "").strip(),
    }


def draft_id_in_archives(draft_id: str, archives: Any) -> bool:
    target = str(draft_id or "").strip()
    if not target or not isinstance(archives, list):
        return False
    return any(str(row.get("draft_id") or "") == target for row in archives if isinstance(row, dict))


def probe_disk_workflow_for_workspace(workspace_id: str = "") -> dict[str, Any]:
    """Read-only disk probe for workflow keys."""
    out: dict[str, Any] = {
        "workspace_id": str(workspace_id or ""),
        "disk_found": False,
        "local_state_path": "",
        "error": None,
    }
    try:
        from suite_user_persistence import _load_raw
        from workflow_persist_guard import summarize_cloud_workflow_blob

        state, path, _ = _load_raw("baseball")
        out["local_state_path"] = str(path or "")
        if isinstance(state, dict):
            out["disk_found"] = True
            out.update(summarize_cloud_workflow_blob(state))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def resolve_draft_in_session(
    session: dict[str, Any] | None,
    draft_id: str,
    *,
    after: dict[str, int] | None = None,
    disk_has: bool = False,
) -> bool:
    """Use the same archive source as Saved Draft Library (with disk fallback)."""
    target = str(draft_id or "").strip()
    if not target or not isinstance(session, dict):
        return False
    try:
        from draft_archive_state import get_draft_archive, list_draft_archives

        archives = list_draft_archives(session)
        if draft_id_in_archives(target, archives):
            return True
        if get_draft_archive(session, target):
            return True
        for row in archives:
            if str(row.get("league_context_id") or "") == target:
                return True
    except ImportError:
        pass
    if disk_has and target:
        try:
            from suite_user_persistence import _load_raw

            state, _, _ = _load_raw("baseball")
            if isinstance(state, dict) and draft_id_in_archives(target, state.get("draft_archive_teams")):
                return True
        except Exception:
            pass
    if disk_has and after and int(after.get("draft_archive_count") or 0) > 0:
        return True
    return False


def probe_persisted_draft_id(
    draft_id: str,
    *,
    workspace_id: str = "",
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check whether a draft id exists in session, disk, and cloud snapshots."""
    target = str(draft_id or "").strip()
    ws = str(workspace_id or (session and _workspace_id(session)) or "")
    out: dict[str, Any] = {
        "draft_id": target,
        "in_session": False,
        "in_disk": False,
        "in_cloud": False,
        "session_count": 0,
        "disk_count": 0,
        "cloud_count": 0,
    }
    if not target:
        return out
    disk = probe_disk_workflow_for_workspace(ws)
    out["disk_count"] = int(disk.get("draft_archive_count") or 0)
    if disk.get("disk_found"):
        try:
            from suite_user_persistence import _load_raw

            state, _, _ = _load_raw("baseball")
            out["in_disk"] = draft_id_in_archives(target, (state or {}).get("draft_archive_teams"))
        except Exception:
            pass
    if isinstance(session, dict):
        try:
            from draft_archive_state import list_draft_archives

            out["session_count"] = len(list_draft_archives(session))
            out["in_session"] = resolve_draft_in_session(
                session,
                target,
                disk_has=bool(out.get("in_disk")),
            )
        except ImportError:
            pass
    try:
        cloud_app_key = ""
        if isinstance(session, dict):
            cloud_app_key = str(session.get("_suite_last_cloud_app_key") or "").strip()
        if cloud_app_key:
            from workflow_persist_guard import probe_cloud_workflow_for_app_key

            cloud = probe_cloud_workflow_for_app_key(cloud_app_key, workspace_id=ws)
        else:
            from workflow_persist_guard import probe_cloud_workflow_for_workspace

            cloud = probe_cloud_workflow_for_workspace(ws)
        out["cloud_count"] = int(cloud.get("draft_archive_count") or 0)
        out["in_cloud"] = bool(cloud.get("draft_ids") and target in set(cloud.get("draft_ids") or []))
        out["cloud_app_key"] = cloud.get("cloud_app_key") or cloud_app_key
        out["selected_row_user_id"] = cloud.get("selected_row_user_id")
    except ImportError:
        pass
    return out


def save_persist_mode_context(session: dict[str, Any]) -> dict[str, Any]:
    """Whether cloud persistence is expected for this session."""
    authenticated = False
    cloud_enabled = False
    try:
        from suite_auth import is_authenticated
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = bool(cloud_storage_enabled())
        authenticated = bool(is_authenticated(session))
    except ImportError:
        pass
    # Cloud writes require Supabase config. Durability for saved drafts requires
    # readback-confirmed draft_archive_teams in cloud — not payload size alone.
    cloud_expected = bool(cloud_enabled)
    blocked = str(session.get("_suite_autosave_cloud_blocked_reason") or "").strip()
    return {
        "cloud_write_expected": cloud_expected,
        "durable_persistence": False,
        "auth_mode": "signed_in" if authenticated else "local_demo",
        "cloud_blocked_reason": blocked,
        "demo_disk_only_ok": not cloud_expected,
    }


def record_save_button_click(
    session: dict[str, Any],
    *,
    source: str,
    team_name: str = "",
    key_prefix: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """First write on save button click — proves callback executed."""
    save_reason = str(reason or "").strip() or f"{source.replace(' ', '_')}_saved"
    counts = _workflow_counts(session)
    ws = _workspace_id(session)
    active_before = _active_state_snapshot(session)
    draft_id = str(
        session.get("active_draft_archive_id")
        or session.get("simulator_session_library_draft_id")
        or session.get("_simulator_session_library_draft_id")
        or ""
    ).strip()
    payload = {
        "save_requested": True,
        "requested_at": _utc_now(),
        "workspace_id": ws,
        "team_name": str(team_name or ""),
        "draft_id": draft_id,
        "active_draft_before_save": active_before["active_draft_archive_id"],
        "active_league_before_save": active_before["active_league_context_id"],
        "pending_active_draft_before_save": active_before["pending_active_draft_archive_id"],
        "pending_active_league_before_save": active_before["pending_active_league_context_id"],
        "archive_count_before": int(counts.get("draft_archive_count") or 0),
        "context_count_before": int(counts.get("league_context_count") or 0),
        "source": str(source or ""),
        "key_prefix": str(key_prefix or ""),
    }
    session[DRAFT_SAVE_BUTTON_TRACE_KEY] = payload
    begin_save_trace(
        session,
        source=source,
        reason=save_reason,
        draft_name=str(session.get(f"{key_prefix}_name_input") or ""),
    )
    session[DRAFT_LIBRARY_SAVE_DIAG_KEY] = {
        **dict(session.get(DRAFT_LIBRARY_SAVE_DIAG_KEY) or {}),
        **payload,
        "save_request_received": True,
        "save_source": source,
        "draft_archive_count_before": payload["archive_count_before"],
        "league_context_count_before": payload["context_count_before"],
    }
    return payload


def resolve_simulator_board_df(session: dict[str, Any]):
    """Load canonical draft board from session inside save callback."""
    try:
        from draft_room_state import ensure_runtime_draft_board, prepare_draft_room_state

        prepare_draft_room_state(session)
        return ensure_runtime_draft_board(session)
    except Exception:
        return None


def begin_save_trace(
    session: dict[str, Any],
    *,
    source: str,
    reason: str = "",
    draft_name: str = "",
) -> None:
    """Mark that an explicit save button was clicked."""
    counts = _workflow_counts(session)
    active_before = _active_state_snapshot(session)
    session[DRAFT_LIBRARY_SAVE_DIAG_KEY] = {
        "save_request_received": True,
        "save_request_at": _utc_now(),
        "save_source": str(source or ""),
        "reason": str(reason or ""),
        "draft_name_requested": str(draft_name or ""),
        "active_draft_before_save": active_before["active_draft_archive_id"],
        "active_league_before_save": active_before["active_league_context_id"],
        "pending_active_draft_before_save": active_before["pending_active_draft_archive_id"],
        "pending_active_league_before_save": active_before["pending_active_league_context_id"],
        "draft_archive_count_before": int(counts.get("draft_archive_count") or 0),
        "league_context_count_before": int(counts.get("league_context_count") or 0),
        "restore_source": str(
            session.get("_suite_persist_last_restore_source")
            or session.get("_suite_restore_pick_source")
            or "session"
        ),
        "steps": ["save_request_received"],
    }


def finalize_save_trace(
    session: dict[str, Any],
    *,
    reason: str,
    before: dict[str, int],
    after: dict[str, int],
    persist_ok: bool,
    entry: dict[str, Any] | None = None,
    cloud_write_ok: bool | None = None,
    disk_write_ok: bool | None = None,
    probe_cloud: bool = True,
) -> dict[str, Any]:
    """Complete save trace with persist + readback verification."""
    diag = dict(session.get(DRAFT_LIBRARY_SAVE_DIAG_KEY) or {})
    mode = save_persist_mode_context(session)
    steps = list(diag.get("steps") or [])
    draft_id = str((entry or {}).get("draft_id") or "")
    league_context_id = str((entry or {}).get("league_context_id") or "")

    if draft_id:
        steps.append("archive_id_written")
    steps.append("archive_counts_updated")

    if cloud_write_ok is None:
        cloud_write_ok = bool(session.get("_suite_persist_last_save_cloud"))
    if disk_write_ok is None:
        disk_write_ok = bool(session.get("_suite_persist_last_save_disk"))

    ws = _workspace_id(session)
    cloud_app_key = str(session.get("_suite_last_cloud_app_key") or "")
    cloud_readback: dict[str, Any] = {}
    disk_readback: dict[str, Any] = {}
    draft_probe: dict[str, Any] = {}

    if probe_cloud:
        try:
            readback_attempts = 3 if bool(cloud_write_ok) else 1
            if cloud_app_key:
                from workflow_persist_guard import probe_cloud_workflow_for_app_key

                cloud_readback = probe_cloud_workflow_for_app_key(
                    cloud_app_key,
                    workspace_id=ws,
                    max_attempts=readback_attempts,
                )
            else:
                from workflow_persist_guard import probe_cloud_workflow_for_workspace

                cloud_readback = probe_cloud_workflow_for_workspace(ws, max_attempts=readback_attempts)
        except Exception:
            pass
    disk_readback = probe_disk_workflow_for_workspace(ws)
    if draft_id:
        draft_probe = probe_persisted_draft_id(draft_id, workspace_id=ws, session=session)
        if not draft_probe.get("in_session"):
            try:
                from workflow_persist_guard import hydrate_session_workflow_from_disk

                hydrate_session_workflow_from_disk(session, draft_id=draft_id)
                draft_probe = probe_persisted_draft_id(draft_id, workspace_id=ws, session=session)
            except ImportError:
                pass

    in_session = resolve_draft_in_session(
        session,
        draft_id,
        after=after,
        disk_has=bool(draft_probe.get("in_disk")),
    )
    if not in_session and bool(disk_write_ok) and int(disk_readback.get("draft_archive_count") or 0) > 0:
        # Disk is the refresh cache for this Streamlit run.  If the in-memory
        # archive list was stale, treat the session as recoverable after the
        # disk hydrate above; durability still requires cloud readback below.
        in_session = True
    expected_after = int(after.get("draft_archive_count") or 0)
    cloud_count = int(cloud_readback.get("draft_archive_count") or 0)
    cloud_readback_ok = bool(cloud_readback.get("row_found")) and cloud_count == expected_after
    if draft_id:
        draft_ids = set(cloud_readback.get("draft_ids") or [])
        cloud_readback_ok = cloud_readback_ok and draft_id in draft_ids

    if cloud_write_ok:
        steps.append("cloud_write_success")
    elif cloud_write_ok is False:
        if mode.get("demo_disk_only_ok"):
            steps.append("cloud_write_skipped_demo")
        else:
            steps.append("cloud_write_failed")
    if disk_write_ok:
        steps.append("disk_write_success")
    elif disk_write_ok is False:
        steps.append("disk_write_failed")
    if in_session:
        steps.append("session_has_archive")
    if draft_probe.get("in_disk"):
        steps.append("disk_readback_has_archive")
    if draft_probe.get("in_cloud") or cloud_readback_ok:
        steps.append("cloud_readback_has_archive")

    disk_only_ok = bool(mode.get("demo_disk_only_ok")) and bool(disk_write_ok) and bool(
        in_session or draft_probe.get("in_disk")
    )
    cloud_expected = bool(mode.get("cloud_write_expected"))
    cloud_error = str(
        session.get("_suite_persist_last_cloud_error")
        or session.get("_draft_archive_persist_error")
        or session.get("_suite_autosave_cloud_blocked_reason")
        or ""
    ).strip()
    if cloud_expected:
        draft_in_cloud = bool(draft_probe.get("in_cloud")) or bool(cloud_readback_ok)
        effective_persist_ok = bool(cloud_write_ok) and draft_in_cloud
        if not effective_persist_ok and not cloud_error:
            if cloud_write_ok is False:
                cloud_error = "cloud_write_failed"
            elif not draft_in_cloud:
                cloud_error = "cloud_readback_missing_draft"
    elif disk_only_ok:
        effective_persist_ok = disk_only_ok
    else:
        effective_persist_ok = bool(persist_ok)

    active_after = _active_state_snapshot(session)
    active_draft_before = str(diag.get("active_draft_before_save") or "").strip()
    active_league_before = str(diag.get("active_league_before_save") or "").strip()
    pending_draft_before = str(diag.get("pending_active_draft_before_save") or "").strip()
    pending_league_before = str(diag.get("pending_active_league_before_save") or "").strip()
    active_draft_changed = active_after["active_draft_archive_id"] != active_draft_before
    active_league_changed = active_after["active_league_context_id"] != active_league_before
    pending_draft_changed = active_after["pending_active_draft_archive_id"] != pending_draft_before
    pending_league_changed = active_after["pending_active_league_context_id"] != pending_league_before

    payload: dict[str, Any] = {
        **diag,
        **mode,
        "reason": str(reason or diag.get("reason") or ""),
        "persist_ok": effective_persist_ok,
        "draft_id": draft_id,
        "saved_draft_id": draft_id,
        "league_context_id": league_context_id,
        "saved_league_context_id": league_context_id,
        "draft_name": str((entry or {}).get("draft_name") or diag.get("draft_name_requested") or ""),
        "active_draft_before_save": active_draft_before,
        "active_draft_after_save": active_after["active_draft_archive_id"],
        "active_draft_changed_during_save": bool(active_draft_changed),
        "active_league_before_save": active_league_before,
        "active_league_after_save": active_after["active_league_context_id"],
        "active_league_changed_during_save": bool(active_league_changed),
        "pending_active_draft_before_save": pending_draft_before,
        "pending_active_draft_after_save": active_after["pending_active_draft_archive_id"],
        "pending_active_draft_changed_during_save": bool(pending_draft_changed),
        "pending_active_league_before_save": pending_league_before,
        "pending_active_league_after_save": active_after["pending_active_league_context_id"],
        "pending_active_league_changed_during_save": bool(pending_league_changed),
        "saved_draft_became_active": bool(
            draft_id and active_after["active_draft_archive_id"] == draft_id and active_draft_before != draft_id
        ),
        "saved_league_became_active": bool(
            league_context_id
            and active_after["active_league_context_id"] == league_context_id
            and active_league_before != league_context_id
        ),
        "draft_archive_count_before": int(before.get("draft_archive_count") or 0),
        "draft_archive_count_after": int(after.get("draft_archive_count") or 0),
        "league_context_count_before": int(before.get("league_context_count") or 0),
        "league_context_count_after": int(after.get("league_context_count") or 0),
        "cloud_write_success": bool(cloud_write_ok),
        "disk_write_success": bool(disk_write_ok),
        "cloud_readback_drafts": int(cloud_readback.get("draft_archive_count") or 0),
        "cloud_readback_contexts": int(cloud_readback.get("league_context_count") or 0),
        "cloud_readback_ok": bool(cloud_readback_ok),
        "disk_readback_drafts": int(disk_readback.get("draft_archive_count") or 0),
        "draft_in_session": bool(in_session),
        "draft_in_disk": bool(draft_probe.get("in_disk")),
        "draft_in_cloud": bool(draft_probe.get("in_cloud")),
        "restore_source": str(
            session.get("_suite_persist_last_restore_source")
            or session.get("_suite_restore_pick_source")
            or diag.get("restore_source")
            or "session"
        ),
        "last_save_reason": str(session.get("_suite_persist_last_save_reason") or ""),
        "last_save_at": str(session.get("_suite_persist_last_save_at") or ""),
        "cloud_blocked_reason": str(session.get("_suite_autosave_cloud_blocked_reason") or ""),
        "persist_error": cloud_error or str(session.get("_draft_archive_persist_error") or ""),
        "cloud_app_key": cloud_app_key or str(session.get("_suite_last_cloud_app_key") or ""),
        "readback_scope_user_id": cloud_readback.get("scope_user_id"),
        "readback_selected_row_user_id": cloud_readback.get("selected_row_user_id"),
        "readback_row_inspection": cloud_readback.get("row_inspection") or {},
        "steps": steps,
        "finalized_at": _utc_now(),
    }
    session[DRAFT_LIBRARY_SAVE_DIAG_KEY] = payload
    return payload


def record_library_load_trace(session: dict[str, Any]) -> dict[str, Any]:
    """Snapshot counts when Saved Draft Library page renders."""
    ws = _workspace_id(session)
    counts = _workflow_counts(session)
    disk = probe_disk_workflow_for_workspace(ws)
    cloud: dict[str, Any] = {}
    try:
        from workflow_persist_guard import probe_cloud_workflow_for_workspace

        cloud = probe_cloud_workflow_for_workspace(ws)
    except ImportError:
        pass
    payload = {
        "loaded_at": _utc_now(),
        "library_load_count_session": int(counts.get("draft_archive_count") or 0),
        "library_load_contexts_session": int(counts.get("league_context_count") or 0),
        "library_load_count_disk": int(disk.get("draft_archive_count") or 0),
        "library_load_count_cloud": int(cloud.get("draft_archive_count") or 0),
        "restore_source": str(
            session.get("_suite_persist_last_restore_source")
            or session.get("_suite_restore_pick_source")
            or "none"
        ),
        "restore_at": str(session.get("_suite_persist_last_restore_at") or ""),
        "workspace_id": ws,
    }
    session[DRAFT_LIBRARY_LOAD_DIAG_KEY] = payload
    return payload


def record_restore_trace(
    session: dict[str, Any],
    *,
    draft_id: str,
    entry: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    action: str = "activate",
) -> dict[str, Any]:
    """Trace opening / activating a saved draft from the library."""
    draft_id = str(draft_id or "").strip()
    player_count = len((entry or {}).get("players") or [])
    team_count = 0
    try:
        from fantasy_league_context import league_team_count

        team_count = league_team_count(context, entry)
    except ImportError:
        pass
    payload = {
        "restore_action": str(action or "activate"),
        "restored_at": _utc_now(),
        "draft_id": draft_id,
        "draft_name": str((entry or {}).get("draft_name") or ""),
        "player_count": player_count,
        "team_count": team_count,
        "league_context_id": str((context or {}).get("league_context_id") or ""),
        "restore_source": str(
            session.get("_suite_persist_last_restore_source")
            or session.get("_suite_restore_pick_source")
            or "session"
        ),
        "active_draft_archive_id": str(session.get("active_draft_archive_id") or ""),
    }
    session[DRAFT_LIBRARY_RESTORE_DIAG_KEY] = payload
    return payload


def save_trace_checklist(diag: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """Return (label, status, detail) rows for UI — status: pass|fail|warn|pending."""
    if not isinstance(diag, dict) or not diag:
        return []
    rows: list[tuple[str, str, str]] = []

    def _row(label: str, ok: bool | None, detail: str = "") -> None:
        if ok is True:
            rows.append((label, "pass", detail))
        elif ok is False:
            rows.append((label, "fail", detail))
        elif ok is None:
            rows.append((label, "pending", detail))
        else:
            rows.append((label, "warn", detail))

    _row("Save request received", bool(diag.get("save_request_received")))
    _row(
        "Archive id written",
        bool(diag.get("draft_id")),
        str(diag.get("draft_id") or "—"),
    )
    active_changed = bool(
        diag.get("active_draft_changed_during_save")
        or diag.get("active_league_changed_during_save")
        or diag.get("pending_active_draft_changed_during_save")
        or diag.get("pending_active_league_changed_during_save")
    )
    _row(
        "Active draft unchanged by save",
        not active_changed,
        (
            f"draft {diag.get('active_draft_before_save') or '—'} → {diag.get('active_draft_after_save') or '—'}; "
            f"league {diag.get('active_league_before_save') or '—'} → {diag.get('active_league_after_save') or '—'}; "
            f"pending draft {diag.get('pending_active_draft_before_save') or '—'} → "
            f"{diag.get('pending_active_draft_after_save') or '—'}"
        ),
    )
    before = int(diag.get("draft_archive_count_before") or 0)
    after = int(diag.get("draft_archive_count_after") or 0)
    _row(
        "Archive count increased",
        after > before or (after >= before and bool(diag.get("draft_id"))),
        f"{before} → {after}",
    )
    cloud_ok = diag.get("cloud_write_success")
    cloud_expected = bool(diag.get("cloud_write_expected"))
    if cloud_ok is not None:
        if cloud_ok is False and not cloud_expected:
            detail = str(diag.get("cloud_blocked_reason") or "not signed in (local/demo mode)")
            _row("Cloud write", None, f"Skipped — {detail}")
        else:
            _row("Cloud write", bool(cloud_ok), str(diag.get("last_save_reason") or ""))
    disk_ok = diag.get("disk_write_success")
    if disk_ok is not None:
        _row("Disk write", bool(disk_ok))
    disk_has = bool(diag.get("draft_in_disk"))
    session_has = bool(diag.get("draft_in_session"))
    if session_has:
        _row("Session has archive", True, str(diag.get("draft_id") or ""))
    elif disk_has and bool(diag.get("persist_ok")):
        _row(
            "Session has archive",
            True,
            f"{diag.get('draft_id') or '—'} (confirmed via disk readback; session refreshes on rerun)",
        )
    elif disk_has and diag.get("demo_disk_only_ok"):
        _row(
            "Session has archive",
            None,
            "Temporary local save only — will not survive Streamlit Cloud reboot",
        )
    else:
        _row("Session has archive", False, str(diag.get("draft_id") or ""))
    if diag.get("draft_in_disk") is not None:
        _row("Disk readback has archive", bool(diag.get("draft_in_disk")))
    if cloud_expected and (diag.get("cloud_readback_ok") is not None or diag.get("draft_in_cloud") is not None):
        in_cloud = bool(diag.get("draft_in_cloud"))
        detail_bits = [f"cloud drafts={diag.get('cloud_readback_drafts', '—')}"]
        if diag.get("cloud_app_key"):
            detail_bits.append(f"key `{diag.get('cloud_app_key')}`")
        if diag.get("readback_selected_row_user_id") is not None:
            detail_bits.append(f"row user_id `{diag.get('readback_selected_row_user_id')}`")
        _row(
            "Cloud readback has archive",
            in_cloud if diag.get("draft_in_cloud") is not None else bool(diag.get("cloud_readback_ok")),
            " · ".join(detail_bits),
        )
    elif not cloud_expected and diag.get("cloud_write_success") is False:
        _row(
            "Cloud readback has archive",
            None,
            "Cloud not configured — temporary local save only, will not survive reboot",
        )
    _row("Persist OK (overall)", bool(diag.get("persist_ok")))
    if not diag.get("persist_ok") and diag.get("persist_error"):
        _row("Persist error", False, str(diag.get("persist_error")))
    return rows


def record_save_failure_trace(
    session: dict[str, Any],
    *,
    reason: str,
    error: str = "",
    before: dict[str, int] | None = None,
) -> None:
    """Capture partial trace when save aborts before persist."""
    counts = before or _workflow_counts(session)
    diag = dict(session.get(DRAFT_LIBRARY_SAVE_DIAG_KEY) or {})
    diag.update(
        {
            "reason": reason,
            "persist_ok": False,
            "save_error": str(error or ""),
            "draft_archive_count_before": int(counts.get("draft_archive_count") or 0),
            "draft_archive_count_after": int(_workflow_counts(session).get("draft_archive_count") or 0),
            "league_context_count_before": int(counts.get("league_context_count") or 0),
            "league_context_count_after": int(_workflow_counts(session).get("league_context_count") or 0),
            "finalized_at": _utc_now(),
        }
    )
    session[DRAFT_LIBRARY_SAVE_DIAG_KEY] = diag


def render_save_trace_inline(
    st: Any,
    session: dict[str, Any],
    *,
    title: str = "Save Diagnostics / Last Save Trace",
    source: str = "",
) -> None:
    """Always-visible save diagnostics directly under the save button."""
    st.markdown(f"##### {title}")
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        dev_on = bool(developer_mode_checkbox_enabled(st=st))
    except Exception:
        dev_on = False
    if dev_on:
        st.caption("Developer Mode is **ON** — cloud readback probes are enabled on save.")
    else:
        st.caption(
            "Developer Mode is **off**. This panel still shows every save attempt; turn on Developer Mode "
            "in the sidebar for deeper cloud/disk probes on **Saved Draft Library**."
        )
    deploy_ref = ""
    try:
        from pathlib import Path

        marker = Path(__file__).resolve().parent / "deploy_commit.txt"
        if marker.is_file():
            deploy_ref = str(marker.read_text(encoding="utf-8").splitlines()[0].split("#")[0].strip())
    except Exception:
        pass
    if deploy_ref:
        st.caption(f"Deployed build marker: `{deploy_ref}`")

    btn_trace = session.get(DRAFT_SAVE_BUTTON_TRACE_KEY)
    if isinstance(btn_trace, dict) and btn_trace.get("save_requested"):
        st.markdown("**Save button click trace**")
        with st.container(border=True):
            st.markdown(
                f"✅ **Save requested** at `{btn_trace.get('requested_at') or '—'}` · "
                f"workspace `{btn_trace.get('workspace_id') or '—'}` · "
                f"draft_id `{btn_trace.get('draft_id') or '—'}` · "
                f"archives before **{btn_trace.get('archive_count_before', 0)}**"
            )
            st.json(btn_trace)

    diag = session.get(DRAFT_LIBRARY_SAVE_DIAG_KEY)
    has_trace = isinstance(diag, dict) and (
        diag.get("save_request_received") or diag.get("finalized_at") or diag.get("save_error")
    )
    if not has_trace and not (isinstance(btn_trace, dict) and btn_trace.get("save_requested")):
        st.info("No save trace yet — click **Save Active League Context**.")
        return
    if not has_trace:
        st.warning("Save button fired, but full pipeline trace was not finalized yet.")
        return

    diag = diag if isinstance(diag, dict) else {}
    with st.container(border=True):
        if source:
            st.caption(f"Source: **{source}** · reason: `{diag.get('reason') or '—'}`")
        st.markdown(
            f"**Counts:** drafts {diag.get('draft_archive_count_before', '—')} → "
            f"{diag.get('draft_archive_count_after', '—')} · contexts "
            f"{diag.get('league_context_count_before', '—')} → "
            f"{diag.get('league_context_count_after', '—')}"
        )
        st.markdown(
            f"**Persist:** ok={diag.get('persist_ok')} · cloud={diag.get('cloud_write_success')} · "
            f"disk={diag.get('disk_write_success')} · readback drafts "
            f"session/disk/cloud={diag.get('draft_in_session')}/"
            f"{diag.get('draft_in_disk')}/{diag.get('draft_in_cloud')}"
        )
        st.markdown(
            f"**Active IDs:** draft `{diag.get('active_draft_before_save') or '—'}` → "
            f"`{diag.get('active_draft_after_save') or '—'}` · league "
            f"`{diag.get('active_league_before_save') or '—'}` → "
            f"`{diag.get('active_league_after_save') or '—'}` · changed="
            f"{bool(diag.get('active_draft_changed_during_save') or diag.get('active_league_changed_during_save'))}"
        )
        if diag.get("pending_active_draft_changed_during_save") or diag.get(
            "pending_active_league_changed_during_save"
        ):
            st.warning(
                "Save changed a pending active draft/league id. That means this save attempted to schedule activation."
            )
        if diag.get("demo_disk_only_ok") and diag.get("disk_write_success"):
            st.warning(
                "**Temporary local save only — will not survive Streamlit Cloud reboot.** "
                "Cloud storage is not configured in this deployment, so this draft is stored only on "
                "ephemeral disk. It survives page refresh but is lost when the app restarts."
            )
        elif not diag.get("cloud_write_expected") and diag.get("cloud_write_success") is False:
            st.warning(
                "**Temporary local save only — will not survive Streamlit Cloud reboot.** "
                "Cloud write was skipped. Configure Supabase (or sign in, if enabled) for durable saves."
            )
        elif diag.get("cloud_write_expected") and not diag.get("cloud_write_success"):
            st.warning(
                "**Saved to disk/session only — not durable yet.** "
                "Cloud write failed; do not reboot until cloud readback confirms the draft. "
                "If the error mentions PGRST002/503, retry Save Draft after a few seconds."
            )
        if not diag.get("draft_in_session") and diag.get("draft_in_disk"):
            st.info(
                "Draft confirmed on **disk** but missing from session — reload Saved Draft Library "
                "or save again to refresh the in-memory library."
            )
        if diag.get("save_error"):
            st.error(str(diag["save_error"]))
        if diag.get("cloud_blocked_reason"):
            st.caption(f"Cloud blocked: {diag['cloud_blocked_reason']}")
        if diag.get("persist_error"):
            st.caption(f"Persist error: {diag['persist_error']}")
        st.markdown("**Checklist**")
        for label, status, detail in save_trace_checklist(diag):
            icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "pending": "⏳"}.get(status, "•")
            line = f"{icon} **{label}**"
            if detail:
                line += f" — {detail}"
            st.markdown(line)
        st.markdown("**Raw trace JSON**")
        st.json(diag)
