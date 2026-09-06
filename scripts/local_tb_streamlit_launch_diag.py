"""Diagnose why local Streamlit children die under Cursor/agent shells (Windows)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tb_probe"
OUT.mkdir(parents=True, exist_ok=True)
PY = sys.executable
PORT = 8599
LOG = OUT / "diag_launch_8599.log"
REPORT = OUT / "streamlit_launch_diag.json"

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def http_ok(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as r:
            return int(r.status) < 500
    except Exception:
        return False


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def launch(mode: str) -> dict:
    if LOG.exists():
        LOG.unlink()
    env = os.environ.copy()
    env["BASEBALL_SHARED_DRAFT_ROOM_BACKEND"] = "local"
    env["SUITE_WORKSPACE_ID"] = "diag"
    env["BASEBALL_DEVICE_ID"] = f"diag-{mode}"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    cmd = [
        PY,
        "-m",
        "streamlit",
        "run",
        "streamlit_app.py",
        "--server.port",
        str(PORT),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    info: dict = {"mode": mode, "cmd": cmd}
    if mode == "pipe_redirect":
        # Parent-owned pipes — classic Cursor block_until_ms:0 failure mode.
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        info["creationflags"] = 0
        info["stdout"] = "PIPE"
    elif mode == "file_redirect_no_breakaway":
        lf = open(LOG, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        )
        info["creationflags"] = "NEW_GROUP|NO_WINDOW"
        info["stdout"] = str(LOG)
        # Close parent handle intentionally — child should keep duplicate on Windows.
        lf.close()
    elif mode == "breakaway_detached_file":
        lf = open(LOG, "w", encoding="utf-8", errors="replace")
        flags = (
            CREATE_NEW_PROCESS_GROUP
            | DETACHED_PROCESS
            | CREATE_NO_WINDOW
            | CREATE_BREAKAWAY_FROM_JOB
        )
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=False,
        )
        info["creationflags"] = "BREAKAWAY|DETACHED|NEW_GROUP|NO_WINDOW"
        info["stdout"] = str(LOG)
        lf.close()
    else:
        raise ValueError(mode)

    info["pid"] = proc.pid
    info["ppid"] = os.getpid()
    # Wait briefly for boot, then return WITHOUT waiting for process — caller
    # will re-check after this diagnostic script exits (simulating harness end).
    ready = False
    for i in range(40):
        time.sleep(1.0)
        if not alive(proc.pid):
            info["died_during_boot"] = True
            info["exit_code"] = proc.poll()
            info["alive_at_t"] = i
            break
        if http_ok(PORT):
            ready = True
            info["ready_after_s"] = i + 1
            break
    info["http_ready"] = ready
    info["alive_before_parent_exit"] = alive(proc.pid)
    info["poll_before_parent_exit"] = proc.poll()
    return info


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "breakaway_detached_file"
    # Kill anything on PORT
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue | "
             f"ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass
    time.sleep(1)
    report = launch(mode)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    # Intentionally do NOT kill the child — next check script verifies survival.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
