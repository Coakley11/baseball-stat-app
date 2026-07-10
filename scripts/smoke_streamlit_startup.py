#!/usr/bin/env python3
"""Headless Streamlit startup smoke — verify process startup and major page renders.

Usage:
  PYTHONFAULTHANDLER=1 python scripts/smoke_streamlit_startup.py
  PYTHONFAULTHANDLER=1 python scripts/smoke_streamlit_startup.py --pages-only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTUP_MARKERS = (
    "You can now view your Streamlit app",
    "Local URL:",
    "Network URL:",
    "URL: http://",
)


def _run_startup_smoke(env: dict[str, str]) -> int:
    port = str(env.get("SMOKE_STREAMLIT_PORT", "8502"))
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "streamlit_app.py",
        "--server.headless",
        "true",
        f"--server.port={port}",
        "--browser.gatherUsageStats",
        "false",
    ]
    print(f"Python: {sys.version}")
    print(f"Command: {' '.join(cmd)}")
    print(f"PYTHONFAULTHANDLER={env.get('PYTHONFAULTHANDLER')}")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output: list[str] = []
    deadline = time.time() + float(env.get("SMOKE_STREAMLIT_TIMEOUT", "90"))
    try:
        while time.time() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if line:
                print(line, end="", flush=True)
                output.append(line)
                if any(marker in line for marker in STARTUP_MARKERS):
                    print("SMOKE OK: Streamlit startup banner detected")
                    return 0
            code = proc.poll()
            if code is not None:
                print(f"SMOKE FAIL: process exited early with code {code}")
                if "Segmentation fault" in "".join(output):
                    print("Detected segmentation fault in child output")
                return code or 1
            if not line:
                time.sleep(0.1)
        print("SMOKE FAIL: timed out waiting for Streamlit startup banner")
        return 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _run_page_smoke(env: dict[str, str]) -> int:
    cmd = [sys.executable, str(ROOT / "scripts" / "smoke_streamlit_pages.py")]
    print(f"Running page smoke: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Streamlit startup + page smoke")
    parser.add_argument("--pages-only", action="store_true", help="Skip subprocess startup; only AppTest pages")
    parser.add_argument("--startup-only", action="store_true", help="Only verify startup banner")
    args = parser.parse_args()

    env = os.environ.copy()
    env.setdefault("PYTHONFAULTHANDLER", "1")

    if args.pages_only:
        return _run_page_smoke(env)

    code = _run_startup_smoke(env)
    if code != 0 or args.startup_only:
        return code
    return _run_page_smoke(env)


if __name__ == "__main__":
    raise SystemExit(main())
