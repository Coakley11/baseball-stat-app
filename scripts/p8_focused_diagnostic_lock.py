"""Single-instance guard for focused P8 binding diagnostic (harness-only)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "data" / "p8_focused_binding_diagnostic.lock"
LATEST_RUN_PATH = ROOT / "data" / "p8_focused_binding_latest_run.json"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_lock() -> dict[str, Any]:
    if not LOCK_PATH.is_file():
        return {}
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def acquire_focused_diagnostic_lock(*, harness_run_id: str, log_path: Path) -> tuple[bool, str]:
    existing = read_lock()
    ep = int(existing.get("pid") or 0)
    if ep and _pid_alive(ep) and ep != os.getpid():
        return (
            False,
            f"CONCURRENT_FOCUSED_P8_DIAGNOSTIC — pid={ep} run_id={existing.get('harness_run_id')} "
            f"log={existing.get('log_path')}",
        )
    payload = {
        "pid": os.getpid(),
        "harness_run_id": harness_run_id,
        "started_at": time.time(),
        "log_path": str(log_path),
        "heartbeat_path": str(ROOT / "data" / "production_p8_binding_diagnostic_heartbeat.json"),
    }
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LATEST_RUN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True, ""


def release_focused_diagnostic_lock() -> None:
    existing = read_lock()
    if int(existing.get("pid") or 0) == os.getpid() and LOCK_PATH.is_file():
        LOCK_PATH.unlink(missing_ok=True)
