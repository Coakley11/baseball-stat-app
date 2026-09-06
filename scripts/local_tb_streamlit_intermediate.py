"""Spawn Streamlit then exit immediately so the server is reparented off the harness tree."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def main() -> int:
    if len(sys.argv) < 5:
        print("usage: intermediate.py ROOT PORT LOG_PATH PID_PATH [ENV_KV...]", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    port = sys.argv[2]
    log_path = Path(sys.argv[3])
    pid_path = Path(sys.argv[4])
    env = os.environ.copy()
    for kv in sys.argv[5:]:
        if "=" in kv:
            k, v = kv.split("=", 1)
            env[k] = v
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lf = open(log_path, "w", encoding="utf-8", errors="replace")
    flags = (
        CREATE_NEW_PROCESS_GROUP
        | DETACHED_PROCESS
        | CREATE_NO_WINDOW
        | CREATE_BREAKAWAY_FROM_JOB
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "streamlit_app.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(root),
        env=env,
        stdout=lf,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=False,
    )
    lf.close()
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    # Exit immediately — Streamlit is reparented and outlives this intermediate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
