"""Sidebar "Build" stamp: git HEAD (+ when the tree is dirty), cached per process.

Computing it ran two git subprocesses (one a full `git status`) on every rerun. The cache
lasts a minute, so an in-place deploy still shows its new commit shortly after it lands.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, str]] = {}


def build_stamp(repo: str | Path | None = None) -> str:
    root = str(Path(repo) if repo is not None else Path(__file__).resolve().parent)
    now = time.monotonic()
    hit = _cache.get(root)
    if hit is not None and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    head = "?"
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        # Mark dirty tree so humans know uncommitted UI fixes are live on this process.
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        if dirty:
            head = f"{head}+"
    except Exception:
        pass
    _cache[root] = (now, head)
    return head
