"""Dev/acceptance health probes for Supabase shared draft room backend."""

from __future__ import annotations

import random
import string
from typing import Any

_HEALTH_PROBE_PREFIX = "_HEALTH_"


def _dev_visible(session: dict[str, Any]) -> bool:
    try:
        from suite_workspace import developer_ui_visible_from_session

        return developer_ui_visible_from_session(session)
    except ImportError:
        return False


def probe_shared_room_supabase_health(*, run_write_probe: bool = True) -> dict[str, Any]:
    """Check table reachability and optional insert/load round-trip."""
    out: dict[str, Any] = {
        "backend": "supabase",
        "configured": False,
        "table_reachable": False,
        "insert_ok": False,
        "load_ok": False,
        "sql_setup_required": False,
        "status_code": None,
        "detail": "",
        "user_message": "",
        "probe_room_code": None,
    }
    try:
        from draft_room_supabase_store import supabase_shared_room_backend_available

        if not supabase_shared_room_backend_available():
            out["backend"] = "unavailable"
            out["user_message"] = "Supabase shared-room backend is not configured."
            return out
        out["configured"] = True
    except ImportError:
        out["user_message"] = "Supabase modules unavailable."
        return out

    from draft_room_supabase_errors import SharedRoomSupabaseError, shared_room_supabase_error_from_runtime
    from draft_room_supabase_store import SupabaseSharedRoomStore, _request

    store = SupabaseSharedRoomStore()
    try:
        rows = _request(
            "GET",
            "baseball_shared_draft_rooms",
            params={"select": "room_code", "limit": "1"},
            prefer="return=representation",
        )
        out["table_reachable"] = isinstance(rows, list)
    except SharedRoomSupabaseError as exc:
        out["status_code"] = exc.status_code
        out["detail"] = exc.detail
        out["user_message"] = exc.user_message
        out["sql_setup_required"] = exc.status_code == 404 or "pgrst205" in exc.detail.lower()
        return out
    except RuntimeError as exc:
        parsed = shared_room_supabase_error_from_runtime(exc)
        out["status_code"] = parsed.status_code
        out["detail"] = parsed.detail
        out["user_message"] = parsed.user_message
        out["sql_setup_required"] = parsed.status_code == 404
        return out

    if not run_write_probe:
        out["user_message"] = "Table reachable (read probe only)."
        return out

    probe_code = _HEALTH_PROBE_PREFIX + "".join(
        random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(6)
    )
    out["probe_room_code"] = probe_code
    probe_doc = {
        "room_code": probe_code,
        "host_user_id": "healthcheck",
        "revision": 1,
        "status": "not_started",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "schema_version": 1,
        "draft_room_id": probe_code,
        "host_participant_id": "healthcheck",
        "room": {
            "draft_room_id": probe_code,
            "status": "not_started",
            "config": {"num_teams": 2},
            "teams": ["Team 1", "Team 2"],
            "rosters": {"Team 1": [], "Team 2": []},
            "draft_board": [],
            "pool_records": [],
            "pool_columns": [],
        },
        "participants": {},
    }
    try:
        store.save(probe_doc)
        out["insert_ok"] = True
        loaded = store.load(probe_code)
        out["load_ok"] = isinstance(loaded, dict) and str(loaded.get("room_code") or "").upper() == probe_code
        try:
            _request("DELETE", "baseball_shared_draft_rooms", params={"room_code": f"eq.{probe_code}"})
        except Exception:
            pass
        if out["load_ok"]:
            out["user_message"] = "Supabase shared draft room backend healthy (insert + load OK)."
        else:
            out["user_message"] = "Insert succeeded but load-by-code failed."
    except SharedRoomSupabaseError as exc:
        out["status_code"] = exc.status_code
        out["detail"] = exc.detail
        out["user_message"] = exc.user_message
        out["sql_setup_required"] = exc.status_code == 404
    except (RuntimeError, ValueError) as exc:
        parsed = shared_room_supabase_error_from_runtime(exc) if isinstance(exc, RuntimeError) else None
        if parsed is not None:
            out["status_code"] = parsed.status_code
            out["detail"] = parsed.detail
            out["user_message"] = parsed.user_message
        else:
            out["user_message"] = str(exc)
    return out


def maybe_cache_shared_room_health(session: dict[str, Any], *, force: bool = False) -> dict[str, Any] | None:
    if not _dev_visible(session):
        return None
    if not force and session.get("_shared_room_supabase_health"):
        return dict(session["_shared_room_supabase_health"])
    try:
        from draft_room_supabase_store import supabase_shared_room_backend_available

        if not supabase_shared_room_backend_available():
            return None
    except ImportError:
        return None
    health = probe_shared_room_supabase_health()
    session["_shared_room_supabase_health"] = health
    return health


def render_shared_room_supabase_health(st: Any, session: dict[str, Any]) -> None:
    if not _dev_visible(session):
        return
    health = maybe_cache_shared_room_health(session)
    if not isinstance(health, dict):
        return
    with st.expander("Supabase shared room backend (dev)", expanded=bool(health.get("sql_setup_required"))):
        st.caption("Run scripts/sql/baseball_shared_draft_rooms.sql in Supabase if table_reachable is false.")
        rows = [
            ("configured", str(health.get("configured"))),
            ("table_reachable", str(health.get("table_reachable"))),
            ("insert_ok", str(health.get("insert_ok"))),
            ("load_ok", str(health.get("load_ok"))),
            ("sql_setup_required", str(health.get("sql_setup_required"))),
            ("status_code", str(health.get("status_code") if health.get("status_code") is not None else "—")),
            ("user_message", health.get("user_message") or "—"),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if health.get("detail"):
            st.code(str(health.get("detail"))[:2000])
        if st.button("Re-run Supabase health check", key="shared_room_supabase_health_rerun"):
            fresh = maybe_cache_shared_room_health(session, force=True)
            if isinstance(fresh, dict) and fresh.get("user_message"):
                st.info(str(fresh["user_message"]))
