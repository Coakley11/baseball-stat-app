#!/usr/bin/env python3
"""Write deploy_commit.txt from current git HEAD (for Streamlit Cloud runtime)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy_commit.txt"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    try:
        commit = _git("rev-parse", "--short", "HEAD")
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {exc}", file=sys.stderr)
        return 1
    OUT.write_text(
        f"{commit}  # auto-generated; Streamlit Cloud reads this at runtime\nbranch: {branch}\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT.name}: commit={commit} branch={branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
