"""Phase heartbeat for focused P8 binding diagnostic (harness only)."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = ROOT / "data" / "production_p8_binding_diagnostic_heartbeat.json"
LOG_PATH = ROOT / "data" / "p8_binding_handoff_run.out"

_RUN_ID = uuid.uuid4().hex[:16]
_LOG_HANDLE: Any = None
_LOG_PATH_ACTIVE = LOG_PATH


def diagnostic_run_id() -> str:
    return _RUN_ID


def configure_diagnostic_log_path(path: Path) -> None:
    global _LOG_PATH_ACTIVE, _LOG_HANDLE
    _LOG_PATH_ACTIVE = path
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.close()
        except Exception:
            pass
        _LOG_HANDLE = None


def active_log_path() -> Path:
    return _LOG_PATH_ACTIVE


def _ensure_log() -> None:
    global _LOG_HANDLE
    if _LOG_HANDLE is not None:
        return
    _LOG_PATH_ACTIVE.parent.mkdir(parents=True, exist_ok=True)
    _LOG_HANDLE = open(_LOG_PATH_ACTIVE, "a", encoding="utf-8", buffering=1)


def log_line(message: str) -> None:
    _ensure_log()
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {_RUN_ID} {message}\n"
    _LOG_HANDLE.write(line)
    _LOG_HANDLE.flush()
    print(message, flush=True)


def write_heartbeat(
    phase: str,
    *,
    required_cloud_sha: str = "",
    observed_cloud_sha: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "diagnostic_run_id": _RUN_ID,
        "pid": os.getpid(),
        "phase": phase,
        "phase_started_at": time.time(),
        "last_progress_at": time.time(),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "required_cloud_sha": str(required_cloud_sha or "")[:7],
        "observed_cloud_sha": str(observed_cloud_sha or "")[:7],
        "log_path": str(_LOG_PATH_ACTIVE),
        "heartbeat_path": str(HEARTBEAT_PATH),
    }
    if extra:
        payload.update(extra)
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log_line(f"heartbeat phase={phase} observed={payload.get('observed_cloud_sha')}")
