"""Smoke: Fantasy Lineup Assistant stats-loader path without streamlit_app re-entry."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import pandas as pd
from fantasy_lineup_stats_loader import ensure_lineup_page_hitter_stats
from player_name_normalization import normalize_player_name_for_merge

assert normalize_player_name_for_merge("Juan Soto") == "juan soto"
session = {{
    "_fantasy_current_hitter_stats": pd.DataFrame([{{"Player": "Juan Soto", "HR": 25}}]),
}}
ctx = {{
    "league_rosters": {{
        "Daniel": {{"players": [{{"player_name": "Juan Soto"}}]}},
        "Team 2": {{"players": []}},
    }},
    "my_team_name": "Daniel",
}}
result = ensure_lineup_page_hitter_stats(session, ctx, normalize_name_fn=normalize_player_name_for_merge)
assert result.get("hitter_stats") is not None
assert "streamlit_app" not in sys.modules
print("lineup_stats_loader_smoke_ok")
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=45,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return 1
    print(proc.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
