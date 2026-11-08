"""Refresh app modules whose files changed under a running process (Streamlit Cloud in-place pulls).

D4J Dev, 2026-11-08: after the de44bdf push the app crashed at start-up with
``AttributeError: module 'action_icons' has no attribute 'DRAFT_PLAYER'`` although the file on disk
defined it. Streamlit Community Cloud pulls a push into the running container without restarting
the Python process. The main script is re-read from disk on every run, but modules it imports stay
loaded from the previous release (``sys.modules``), so new code met old modules. Streamlit's own
file watcher handles this by dropping changed modules from ``sys.modules``; on Cloud nothing does.

``refresh_stale_app_modules()`` does the same, before the app imports anything: an app module is
stale when the source stamp (mtime + size) that Python wrote into its ``.pyc`` when it loaded the
module no longer matches the file on disk. Stale modules are dropped from ``sys.modules`` so the
next ``import`` loads the current file. Modules without a timestamp ``.pyc`` are left alone.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

APP_DIR = os.path.dirname(os.path.abspath(__file__))
_MIN_INTERVAL_SEC = 2.0
_last_check = 0.0
REFRESHED: list[str] = []  # names dropped in this process (diagnostics)
_refreshed_at: dict[str, tuple[int, int]] = {}  # name -> disk stamp already refreshed for


def _pyc_source_stamp(module: Any) -> tuple[int, int] | None:
    """(source mtime, source size) recorded in the module's timestamp-based .pyc, else None."""
    cached = getattr(module, "__cached__", None)
    if not cached:
        return None
    try:
        with open(cached, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    if len(head) < 16 or int.from_bytes(head[4:8], "little") != 0:  # PEP 552: 0 = timestamp pyc
        return None
    return int.from_bytes(head[8:12], "little"), int.from_bytes(head[12:16], "little")


def stale_app_modules(app_dir: str = APP_DIR) -> list[str]:
    """Names of loaded modules under ``app_dir`` whose source changed since they were loaded."""
    root = os.path.abspath(app_dir) + os.sep
    out: list[str] = []
    for name, module in list(sys.modules.items()):
        if name in ("__main__", __name__) or module is None:
            continue
        path = getattr(module, "__file__", None)
        if not path or not str(path).endswith(".py"):
            continue
        path = os.path.abspath(path)
        if not path.startswith(root):
            continue
        stamp = _pyc_source_stamp(module)
        if stamp is None:
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        disk = (int(st.st_mtime) & 0xFFFFFFFF, st.st_size & 0xFFFFFFFF)
        if stamp != disk and _refreshed_at.get(name) != disk:
            # (once per file version: if the .pyc cannot be rewritten its stamp stays old)
            out.append(name)
    return out


def refresh_stale_app_modules(app_dir: str = APP_DIR, *, force: bool = False) -> list[str]:
    """Drop stale app modules from ``sys.modules``; returns their names. Never raises."""
    global _last_check
    now = time.monotonic()
    if not force and _last_check and now - _last_check < _MIN_INTERVAL_SEC:
        return []
    _last_check = now
    try:
        stale = stale_app_modules(app_dir)
        for name in stale:
            module = sys.modules.pop(name, None)
            try:
                st = os.stat(os.path.abspath(getattr(module, "__file__", "") or ""))
                _refreshed_at[name] = (int(st.st_mtime) & 0xFFFFFFFF, st.st_size & 0xFFFFFFFF)
            except OSError:
                pass
        REFRESHED.extend(stale)
        return stale
    except Exception:
        return []
