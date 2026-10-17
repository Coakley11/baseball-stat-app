"""Plain-language answers for the answer-first pages (U1). Pure functions, no Streamlit.

Every sentence is built from rows the page already filtered and sorted; nothing here ranks,
filters or computes a statistic. Claims are scoped to what was ranked ("among the 7,842 seasons
shown"), so they stay true whatever filters are active.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

RATE_STATS = ("BA", "OBP", "SLG", "OPS")
STAT_NAMES = {
    "R": "runs", "AB": "at-bats", "H": "hits", "2B": "doubles", "3B": "triples", "HR": "home runs",
    "RBI": "RBIs", "SB": "stolen bases", "BB": "walks", "BA": "batting average", "OBP": "on-base percentage",
    "SLG": "slugging percentage", "OPS": "OPS", "score": "score",
}
TILE_LABELS = {"BA": "AVG", "score": "Score"}


def stat_name(stat: str) -> str:
    return STAT_NAMES.get(str(stat), str(stat))


def fmt_stat(stat: str, value: Any) -> str:
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return "—"
    if stat in RATE_STATS:
        text = f"{float(v):.3f}"
        return text[1:] if text.startswith("0.") else text
    if stat == "score":
        return f"{float(v):,.1f}".rstrip("0").rstrip(".")
    return f"{int(round(float(v))):,}"


def _range_text(year_range: Any) -> str:
    a, b = int(year_range[0]), int(year_range[1])
    return str(a) if a == b else f"{a}–{b}"


def _superlative(stat: str, ascending: bool) -> str:
    rate_like = stat in RATE_STATS or stat == "score"
    if ascending:
        return "lowest" if rate_like else "fewest"
    return "highest" if rate_like else "most"


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def last_name(name: str) -> str:
    parts = [p for p in str(name or "").replace(",", " ").split() if p.lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv")]
    return parts[-1] if parts else str(name or "")


def short_name(name: str) -> str:
    """'Aaron Judge' -> 'A. Judge' (keeps a season label short enough for phones)."""
    parts = str(name or "").split()
    if len(parts) < 2:
        return str(name or "")
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def qualification_text(session: Mapping[str, Any], prefix: str, sort_stat: str, year_range: Any, *,
                       per_season: bool = False) -> str:
    """The at-bat rule a rate-stat ranking is using right now (the same state the
    "Stat minimum filters" control shows). Empty for counting stats. ``per_season``: the rows
    are single seasons, so the minimum applies to each season."""
    if sort_stat not in RATE_STATS:
        return ""
    try:
        import rate_stat_qualification as rsq

        value = int(float(session.get(rsq.ab_min_key(prefix)) or 0))
        manual = session.get(rsq.mode_key(prefix)) == rsq.MODE_MANUAL
    except Exception:
        return ""
    if value <= 0:
        return "No at-bat minimum · part-time players can lead this list"
    if per_season:
        who = "Minimum you set" if manual else "Qualified seasons"
        return f"{who} · at least {value:,} AB in the season"
    who = "Minimum you set" if manual else "Qualified hitters"
    return f"{who} · at least {value:,} AB over {_range_text(year_range)}"


def season_answer(rows: pd.DataFrame, sort_stat: str, year_range: Any, *, ascending: bool = False,
                  team_col: str = "", qualification: str = "") -> dict[str, Any] | None:
    """Answer for a ranked list of single seasons (Historical Explorer)."""
    if rows is None or rows.empty or sort_stat not in rows.columns:
        return None
    ranked = rows[pd.to_numeric(rows[sort_stat], errors="coerce").notna()]
    if ranked.empty:
        return None
    top = ranked.iloc[0]
    name = str(top.get("fullName") or top.get("Player") or "").strip()
    year = top.get("yearID")
    year_text = str(int(year)) if pd.notna(year) else ""
    value = fmt_stat(sort_stat, top.get(sort_stat))
    count = len(rows)
    sup = _superlative(sort_stat, ascending)
    body = (f"{_possessive(name)} {value} {stat_name(sort_stat)} in {year_text} {'are' if sort_stat not in RATE_STATS and sort_stat != 'score' else 'is'} "
            f"the {sup} among the {count:,} season{'s' if count != 1 else ''} shown ({_range_text(year_range)}).")
    if len(ranked) > 1:
        nxt = ranked.iloc[1]
        n_year = nxt.get("yearID")
        same = fmt_stat(sort_stat, nxt.get(sort_stat)) == value
        body += (f" {'Tied with' if same else 'Next:'} {str(nxt.get('fullName') or '').strip()}"
                 f" ({int(n_year) if pd.notna(n_year) else ''}), {fmt_stat(sort_stat, nxt.get(sort_stat))}.")
    team = str(top.get(team_col) or "").strip() if team_col else ""
    pos = str(top.get("displayPosition") or "").strip()
    context = " · ".join(x for x in (year_text, team, pos) if x)
    tile_stats = [sort_stat] + [s for s in ("HR", "RBI", "BA", "OPS") if s != sort_stat][:3]
    tiles = [(TILE_LABELS.get(s, s), fmt_stat(s, top.get(s)), "") for s in tile_stats if s in rows.columns]
    return {
        "headline": f"{name}, {year_text}: {value} {stat_name(sort_stat)}",
        "body": body,
        "context": context,
        "tiles": tiles,
        "player": name,
        "qualification": qualification,
    }


def leaderboard_answer(rows: pd.DataFrame, sort_stat: str, year_range: Any, *,
                       weights: Mapping[str, float] | None = None, qualification: str = "") -> dict[str, Any] | None:
    """Answer for a ranked multi-season leaderboard (totals over the range)."""
    if rows is None or rows.empty or sort_stat not in rows.columns:
        return None
    ranked = rows[pd.to_numeric(rows[sort_stat], errors="coerce").notna()]
    if ranked.empty:
        return None
    top = ranked.iloc[0]
    name = str(top.get("fullName") or top.get("Player") or "").strip()
    span = _range_text(year_range)
    if sort_stat == "score":
        used = [(s, float(w)) for s, w in (weights or {}).items() if float(w or 0) > 0]
        parts = [f"{'' if w == 1 else f'{w:g}× '}{s}" for s, w in used]
        what = ("Score adds up " + " + ".join(parts) + f" over {span}" if parts else f"Score over {span}")
        if any(s in RATE_STATS for s, _w in used):
            what += " (rate stats count ×100)"
        what += ". Change the weights under Explore more."
    elif sort_stat in RATE_STATS:
        name_ = stat_name(sort_stat)
        what = f"{name_[0].upper() + name_[1:]} from each player's combined totals over {span}."
    else:
        what = f"Total {stat_name(sort_stat)} over {span}."
    podium = [
        {"rank": i + 1, "name": str(r.get("fullName") or r.get("Player") or "").strip(),
         "value": fmt_stat(sort_stat, r.get(sort_stat))}
        for i, (_, r) in enumerate(ranked.head(3).iterrows())
    ]
    if len(podium) > 1:
        rest = [f"{p['name']} ({p['value']})" for p in podium[1:]]
        what = f"Ahead of {' and '.join(rest)}. " + what
    return {
        "headline": f"{name} leads {span} in {stat_name(sort_stat)}: {fmt_stat(sort_stat, top.get(sort_stat))}",
        "body": what,
        "podium": podium,
        "player": name,
        "qualification": qualification,
        "ranked_count": int(len(ranked)),
    }


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def category_strengths_and_gaps(table: pd.DataFrame, team: str, categories: tuple[str, ...] | list[str],
                                *, max_gaps: int = 2) -> dict[str, list[str]]:
    """From the official standings table: where ``team`` leads, and the closest gaps to the
    team just above it (higher is better in every hitting category scored here).

    Strength = a category where the team has the most category points (ties say "tied").
    Opportunity = a category where passing the next team up would gain roto points, ordered by
    the smallest gap relative to that team's total. Nothing is projected or estimated.
    """
    out: dict[str, list[str]] = {"strengths": [], "opportunities": []}
    if table is None or table.empty or "Team" not in table.columns or team not in set(table["Team"].astype(str)):
        return out
    me = table[table["Team"].astype(str) == team].iloc[0]
    gaps: list[tuple[float, str]] = []
    for cat in categories:
        pts_col = f"{cat} Points"
        if cat not in table.columns or pts_col not in table.columns:
            continue
        values = pd.to_numeric(table[cat], errors="coerce")
        mine = pd.to_numeric(pd.Series([me[cat]]), errors="coerce").iloc[0]
        if pd.isna(mine):
            continue
        best_pts = pd.to_numeric(table[pts_col], errors="coerce").max()
        if float(me[pts_col]) == float(best_pts):
            tied = int((pd.to_numeric(table[pts_col], errors="coerce") == best_pts).sum()) > 1
            out["strengths"].append(f"{cat} ({'tied for ' if tied else ''}1st)")
            continue
        above = values[values > mine]
        if above.empty:
            continue
        nearest = float(above.min())
        leader_team = str(table.loc[above.idxmin(), "Team"])
        gap = nearest - float(mine)
        gap_text = fmt_stat(cat if cat != "AVG" else "BA", gap) if cat in RATE_STATS or cat == "AVG" else f"{gap:g}"
        gaps.append((gap / max(abs(nearest), 1e-9), f"{cat}: {gap_text} behind {leader_team}"))
    out["opportunities"] = [text for _rel, text in sorted(gaps)[:max_gaps]]
    return out


def starter_comparison(add_row: Mapping[str, Any], my_roster: pd.DataFrame) -> str:
    """'Compared with Willy Adames (SS): OPS .812 vs .690' — the add against the rostered player
    with the lowest OPS among those sharing an eligible position (Phase D3 eligibility).
    Empty when there is no shared position or no OPS to compare."""
    if my_roster is None or my_roster.empty or "OPS" not in my_roster.columns:
        return ""
    try:
        from fantasy_position_eligibility import eligible_positions_from_row
    except ImportError:
        return ""
    add_pos = [p for p in eligible_positions_from_row(dict(add_row)) if p not in ("DH", "UTIL", "P", "SP", "RP")]
    add_ops = pd.to_numeric(pd.Series([add_row.get("OPS")]), errors="coerce").iloc[0]
    if not add_pos or pd.isna(add_ops):
        return ""
    best = None
    for _, row in my_roster.iterrows():
        shared = [p for p in eligible_positions_from_row(row.to_dict()) if p in add_pos]
        ops = pd.to_numeric(pd.Series([row.get("OPS")]), errors="coerce").iloc[0]
        if not shared or pd.isna(ops):
            continue
        if best is None or ops < best[0]:
            best = (float(ops), str(row.get("Player") or row.get("fullName") or ""), shared[0])
    if best is None:
        return ""
    return f"Compared with {best[1]} ({best[2]}): OPS {fmt_stat('OPS', add_ops)} vs {fmt_stat('OPS', best[0])}"


def needs_headline(needs: Mapping[str, Any]) -> str:
    """'Biggest needs: SB (4th of 4) · AVG (3rd of 4)' from the waiver needs analysis."""
    ranks = needs.get("category_ranks") or {}
    n = int(needs.get("n_teams") or 0)
    weak = [c for c in (needs.get("weaknesses") or []) if c in ranks]
    weak.sort(key=lambda c: -int(ranks[c]))
    if not ranks or n < 2:
        return "Load current stats to see your category needs"
    if not weak:
        return "No weak categories right now"
    return "Biggest needs: " + " · ".join(f"{c} ({_ordinal(int(ranks[c]))} of {n})" for c in weak[:3])
