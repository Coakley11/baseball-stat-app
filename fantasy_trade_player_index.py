"""Player positions and current-season stats for Trade Center UI."""

from __future__ import annotations

from typing import Any

import pandas as pd

HITTER_STAT_CATEGORIES: tuple[str, ...] = ("R", "HR", "RBI", "SB", "BA")


def player_row(roster_stats: pd.DataFrame | None, player_name: str) -> pd.Series | None:
    if roster_stats is None or roster_stats.empty or "Player" not in roster_stats.columns:
        return None
    name = str(player_name or "").strip()
    if not name:
        return None
    matches = roster_stats[roster_stats["Player"].astype(str).str.strip() == name]
    if matches.empty:
        return None
    return matches.iloc[0]


def format_position_label(roster_stats: pd.DataFrame | None, player_name: str) -> str:
    row = player_row(roster_stats, player_name)
    if row is None:
        return "Position unavailable"
    try:
        from fantasy_weekly_lineup import hitter_position_tokens

        tokens = hitter_position_tokens(row)
    except ImportError:
        tokens = []
        for col in ("Primary Position", "Position", "Eligibility", "Positions"):
            raw = str(row.get(col) or "").strip()
            if raw:
                tokens = [part.strip().upper() for part in raw.replace("/", ",").split(",") if part.strip()]
                break
    if not tokens:
        return "Position unavailable"
    if len(tokens) == 1:
        return tokens[0]
    return "/".join(tokens[:3])


def format_player_option_label(
    roster_stats: pd.DataFrame | None,
    player_name: str,
    *,
    owner: str = "",
    include_owner: bool = False,
) -> str:
    pos = format_position_label(roster_stats, player_name)
    if include_owner and owner:
        return f"{player_name} · {pos} · {owner}"
    return f"{player_name} · {pos}"


def _format_rate(value: Any) -> str:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return "Unavailable"
    if float(num) < 1:
        return f"{float(num):.3f}".lstrip("0")
    return str(int(round(float(num))))


def format_player_stat_line(roster_stats: pd.DataFrame | None, player_name: str) -> str:
    row = player_row(roster_stats, player_name)
    if row is None:
        return "Stats unavailable"
    parts: list[str] = []
    any_stat = False
    for cat in HITTER_STAT_CATEGORIES:
        val = row.get(cat)
        num = pd.to_numeric(val, errors="coerce")
        if pd.isna(num):
            parts.append(f"{cat} Unavailable")
        elif cat == "BA":
            any_stat = True
            parts.append(f"AVG {_format_rate(num)}")
        else:
            any_stat = True
            parts.append(f"{cat} {_format_rate(num)}")
    pa = pd.to_numeric(row.get("PA"), errors="coerce")
    if pd.notna(pa):
        any_stat = True
        parts.append(f"PA {int(pa)}")
    elif pd.notna(pd.to_numeric(row.get("G"), errors="coerce")):
        any_stat = True
        parts.append(f"G {int(pd.to_numeric(row.get('G'), errors='coerce'))}")
    if not any_stat:
        return "Stats unavailable"
    return " · ".join(parts)


def stats_updated_caption(session: dict[str, Any]) -> str:
    ts = str(session.get("_fantasy_standings_stats_loaded_at") or "").strip()
    if ts:
        return f"Stats updated: {ts[:19].replace('T', ' ')} UTC"
    return "Stats updated: Unavailable"


def build_player_index(roster_stats: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if roster_stats is None or roster_stats.empty or "Player" not in roster_stats.columns:
        return index
    for _, row in roster_stats.iterrows():
        name = str(row.get("Player") or "").strip()
        if not name:
            continue
        index[name] = {
            "player_name": name,
            "team_owner": str(row.get("Team") or "").strip(),
            "mlb_team": str(row.get("MLB Team") or row.get("Team") or "").strip(),
            "position": format_position_label(roster_stats, name),
            "stats_line": format_player_stat_line(roster_stats, name),
        }
    return index
