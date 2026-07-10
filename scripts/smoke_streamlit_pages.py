#!/usr/bin/env python3
"""AppTest smoke: run major pages and fail on Streamlit API/runtime exceptions.

Requires streamlit>=1.59 for width="stretch" APIs used across streamlit_app.py.

Usage:
  PYTHONFAULTHANDLER=1 python scripts/smoke_streamlit_pages.py
"""

from __future__ import annotations

import faulthandler
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAJOR_PAGES: tuple[str, ...] = (
    "Historical Explorer",
    "Comparison Tool",
    "Trend Value",
    "Valuation",
    "ML Predictions",
    "Draft Assistant Simulator",
    "Draft Room Simulator",
    "Saved Draft Library",
    "Fantasy Standings Tracker",
    "Fantasy Lineup Assistant",
    "Waiver Wire / Add-Drop Center",
)

MODERN_WIDTH_PATTERNS: tuple[str, ...] = (
    'width="stretch"',
    'width="content"',
    'height="content"',
    'height="stretch"',
)


def _streamlit_version_tuple() -> tuple[int, int, int]:
    try:
        raw = version("streamlit")
    except PackageNotFoundError:
        return (0, 0, 0)
    parts = [int(x) for x in raw.split(".")[:3] if x.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


def _scan_modern_streamlit_api_usage() -> dict[str, int]:
    counts: dict[str, int] = {pattern: 0 for pattern in MODERN_WIDTH_PATTERNS}
    for path in ROOT.rglob("*.py"):
        if path.name.startswith("Old"):
            continue
        if "site-packages" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in MODERN_WIDTH_PATTERNS:
            counts[pattern] += text.count(pattern)
    return counts


def _seed_session(session_state) -> None:
    session_state["portfolio_demo_mode"] = True
    session_state["app_developer_mode"] = False
    for key in ("_suite_auth_session", "_suite_auth_user_id"):
        if key in session_state:
            del session_state[key]


def main() -> int:
    faulthandler.enable()
    st_version = _streamlit_version_tuple()
    print(f"Python: {sys.version}")
    print(f"Streamlit: {'.'.join(str(x) for x in st_version)}")
    if st_version < (1, 59, 0):
        print('FAIL: streamlit>=1.59 required for width="stretch" APIs')
        return 1

    scan = _scan_modern_streamlit_api_usage()
    print("Modern Streamlit width/height API usage scan:")
    for pattern, count in scan.items():
        if count:
            print(f"  {pattern}: {count}")

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=300)
    _seed_session(at.session_state)

    failures: list[str] = []
    for page in MAJOR_PAGES:
        at.session_state["active_page"] = page
        at.session_state["main_sidebar_page"] = page
        try:
            at.run()
            if at.exception:
                messages = [str(exc.value) for exc in at.exception]
                failures.append(f"{page}: {messages}")
                print(f"FAIL page render: {page}: {messages}")
            else:
                print(f"OK  page render: {page}")
        except Exception as exc:
            failures.append(f"{page}: {exc}")
            print(f"FAIL page render: {page}: {exc}")

    if failures:
        print(f"FAILED: {len(failures)} page(s)")
        for row in failures:
            print(f"  - {row}")
        return 1

    print(f"ALL PASS — {len(MAJOR_PAGES)} major pages rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
