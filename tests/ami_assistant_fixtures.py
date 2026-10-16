"""Shared fixtures for the AMI assistant tests.

* ``synthetic_dataset()`` — a small hand-built season frame (fast routing/context tests) with
  deliberate name collisions: two Judges, four Sotos (one a pitcher), two Frank Thomases,
  two Bobby Witts (Sr. a pitcher), and a one-season rookie.
* ``monolith_functions(names)`` — the page's own helper functions, compiled from
  ``streamlit_app.py`` with their Streamlit cache decorators removed, so parity tests run the
  exact code the pages run.
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "streamlit_app.py"

# playerID, name, first, last, position, AB/season, HR/season, HR change/season, SB/season
PLAYERS = (
    ("judgeaa01", "Aaron Judge", 2016, 2025, "OF", 520, 40, 2, 6),
    ("judgejo01", "Joe Judge", 1915, 1932, "1B", 520, 3, 0, 10),
    ("sotoju01", "Juan Soto", 2018, 2025, "OF", 560, 32, 0, 10),
    ("sotoge01", "Geovany Soto", 2005, 2017, "C", 350, 12, 0, 0),
    ("sotoli01", "Livan Soto", 2022, 2024, "SS", 60, 1, 0, 2),
    ("sotogr01", "Gregory Soto", 2019, 2025, "P", 1, 0, 0, 0),
    ("thomafr04", "Frank Thomas", 1990, 2008, "1B", 520, 30, 0, 1),
    ("thomafr03", "Frank Thomas", 1951, 1966, "OF", 450, 20, 0, 2),
    ("bettsmo01", "Mookie Betts", 2014, 2025, "SS", 560, 30, -5, 15),
    ("wittbo02", "Bobby Witt", 2022, 2025, "SS", 600, 25, 3, 35),
    ("wittbo01", "Bobby Witt", 1986, 2001, "P", 2, 0, 0, 0),
    ("seageco01", "Corey Seager", 2015, 2025, "SS", 500, 28, 1, 2),
    ("rookigu01", "Rookie Guy", 2025, 2025, "2B", 400, 12, 0, 8),
    ("ruthba01", "Babe Ruth", 1914, 1935, "OF", 480, 40, 0, 5),
)
TEAM = {"OF": "New York Yankees", "1B": "Washington Senators", "C": "Chicago Cubs", "SS": "Los Angeles Dodgers",
        "P": "Detroit Tigers", "2B": "Kansas City Royals"}


def synthetic_yearly() -> pd.DataFrame:
    from lahman_data import add_rate_stats

    rows: list[dict[str, Any]] = []
    for pid, name, first, last, pos, ab, hr, hr_step, sb in PLAYERS:
        for i, year in enumerate(range(first, last + 1)):
            season_hr = max(0, hr + hr_step * i)
            h = int(ab * 0.27) + (hr_step * i if hr_step > 0 else 0)
            rows.append(
                {
                    "playerID": pid, "fullName": name, "bats": "R", "throws": "R", "birthYear": first - 23,
                    "birthMonth": 1, "birthDay": 1, "birthCountry": "USA", "careerPrimaryPos": pos, "yearID": year,
                    "G": 150 if ab > 100 else (40 if ab > 10 else 30), "AB": ab, "R": int(ab * 0.15),
                    "H": h, "2B": int(ab * 0.05), "3B": 1 if ab > 100 else 0, "HR": min(season_hr, h // 3),
                    "RBI": int(ab * 0.16), "SB": sb, "CS": 2, "BB": int(ab * 0.1), "SO": int(ab * 0.2), "IBB": 2,
                    "HBP": 3, "SH": 0, "SF": 4, "GIDP": 8, "primaryPos": pos, "primaryTeamName": TEAM[pos],
                }
            )
    # The schedule-length estimate needs at least five players a season; add filler hitters.
    for year in range(1914, 2026):
        for k in range(5):
            rows.append(
                {
                    "playerID": f"fill{year}{k}", "fullName": f"Filler {year}{k}", "bats": "L", "throws": "L",
                    "birthYear": year - 25, "birthMonth": 1, "birthDay": 1, "birthCountry": "USA",
                    "careerPrimaryPos": "DH", "yearID": year, "G": 162 if k < 2 else 120, "AB": 300, "R": 30, "H": 75,
                    "2B": 12, "3B": 1, "HR": 5, "RBI": 30, "SB": 1, "CS": 1, "BB": 20, "SO": 50, "IBB": 0, "HBP": 1,
                    "SH": 0, "SF": 2, "GIDP": 5, "primaryPos": "DH", "primaryTeamName": "Boston Red Sox",
                }
            )
    return add_rate_stats(pd.DataFrame(rows))


@lru_cache(maxsize=1)
def synthetic_dataset():
    from ami_assistant.data import dataset_from_yearly

    return dataset_from_yearly(synthetic_yearly(), source="synthetic")


def realistic_draft_session() -> dict:
    """The acceptance harness's Draft Assistant session (built by the real cache writer).

    Building it goes through applied_math_context, which puts the sibling AMI repo first on
    sys.path; restore it so later ``import streamlit_app`` still finds this app.
    """
    import sys

    saved_path = list(sys.path)
    try:
        from ami_acceptance_harness import build_realistic_draft_assistant_session

        return build_realistic_draft_assistant_session()
    finally:
        sys.path[:] = saved_path
        app = sys.modules.get("streamlit_app")
        if app is not None and Path(getattr(app, "__file__", "") or "").resolve().parent != ROOT:
            sys.modules.pop("streamlit_app", None)


def page_section(page_key: str) -> str:
    """The page's branch of the main page router in streamlit_app.py."""
    src = APP_SRC.read_text(encoding="utf-8")
    marker = "elif active_page == DRAFT_LAB_PAGE:" if page_key == "Draft Lab / Simulation" else f'elif active_page == "{page_key}":'
    start = src.index(marker)
    nxt = re.search(r"\n(?:elif|if) active_page == ", src[start + len(marker):])
    return src[start: start + len(marker) + (nxt.start() if nxt else len(src))]


@lru_cache(maxsize=1)
def _app_tree() -> ast.Module:
    return ast.parse(APP_SRC.read_text(encoding="utf-8"))


def monolith_functions(*names: str) -> dict[str, Any]:
    """Compile named top-level functions from streamlit_app.py (decorators dropped)."""
    from lahman_data import add_rate_stats

    nodes = []
    for node in _app_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    missing = set(names) - {n.name for n in nodes}
    if missing:
        raise AssertionError(f"streamlit_app.py no longer defines {sorted(missing)}")
    ns: dict[str, Any] = {"pd": pd, "np": np, "add_rate_stats": add_rate_stats}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_SRC), "exec"), ns)
    return ns
