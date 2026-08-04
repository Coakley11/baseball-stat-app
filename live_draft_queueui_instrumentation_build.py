"""Unconditional QUEUEUI instrumentation identity and raw stdout canaries (logging only)."""

from __future__ import annotations

import json
import time
from typing import Any

# Bump on each instrumentation-only deploy intended for QUEUEUI audit proof.
QUEUEUI_INSTRUMENTATION_BUILD = "7a75a1a"

EVENT_BUILD_LOADED = "SOLO_QUEUEUI_INSTRUMENTATION_BUILD_LOADED"

_BUILD_LOADED_MODULES: set[str] = set()


def _git_head() -> str:
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:40]
    except Exception:
        pass
    try:
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parent
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True)
        return out.strip()[:40]
    except Exception:
        return ""


def _deploy_pin() -> str:
    try:
        from solo_cloud_deploy_identity import read_deploy_commit_pin

        pin, _ = read_deploy_commit_pin()
        return str(pin or "")[:16]
    except Exception:
        return ""


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _diagnostic_run_id(session: dict[str, Any] | None) -> str:
    if not isinstance(session, dict):
        return ""
    return str(session.get("_solo_stage1_run_id") or "")[:32]


def _script_run_seq(session: dict[str, Any] | None) -> int:
    if not isinstance(session, dict):
        return 0
    return int(session.get("_solo_stage1_script_run_seq") or 0)


def _room_id(session: dict[str, Any] | None) -> str:
    if not isinstance(session, dict):
        return ""
    live = session.get("live_draft_room")
    if not isinstance(live, dict):
        return ""
    return str(live.get("draft_room_id") or live.get("draft_id") or "").upper()[:32]


def _active_page(session: dict[str, Any] | None) -> str:
    if not isinstance(session, dict):
        return ""
    return str(session.get("active_page") or "")[:120]


def _lifecycle(session: dict[str, Any] | None) -> str:
    if not isinstance(session, dict):
        return ""
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        return str(resolve_live_draft_lifecycle(session, room=room) or "")[:64]
    except Exception:
        return ""


def _print_canary(event: str, payload: dict[str, Any]) -> None:
    row = {"event": event, "ts": time.time(), **payload}
    try:
        print(f"{event}|{json.dumps(row, default=str)}", flush=True)
    except Exception:
        pass


def emit_instrumentation_build_loaded(
    module_name: str,
    module_file: str,
    *,
    session: dict[str, Any] | None = None,
) -> None:
    """Once per process per module — no ledger, no session mutation."""
    key = str(module_name or module_file or "")
    if not key or key in _BUILD_LOADED_MODULES:
        return
    _BUILD_LOADED_MODULES.add(key)
    _print_canary(
        EVENT_BUILD_LOADED,
        {
            "instrumentation_build": QUEUEUI_INSTRUMENTATION_BUILD,
            "git_head": _git_head(),
            "deploy_pin": _deploy_pin(),
            "module_name": str(module_name)[:200],
            "module_file": str(module_file)[:400],
            "diagnostic_run_id": _diagnostic_run_id(session),
            "streamlit_session_id": _streamlit_session_id(),
            "script_run_seq": _script_run_seq(session),
        },
    )


def emit_raw_canary(
    event: str,
    *,
    session: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Structured stdout only — must not touch ledger or session state."""
    if not event:
        return
    base: dict[str, Any] = {
        "instrumentation_build": QUEUEUI_INSTRUMENTATION_BUILD,
        "git_head": _git_head(),
        "deploy_pin": _deploy_pin(),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "streamlit_session_id": _streamlit_session_id(),
        "script_run_seq": _script_run_seq(session),
        "room_id": _room_id(session),
        "active_page": _active_page(session),
        "lifecycle": _lifecycle(session),
    }
    if isinstance(session, dict):
        if "_start_live_draft_pending" in session:
            base["pending_key_present"] = True
            base["pending_value"] = bool(session.get("_start_live_draft_pending"))
        else:
            base["pending_key_present"] = False
    if extra:
        base.update(extra)
    _print_canary(str(event), base)
