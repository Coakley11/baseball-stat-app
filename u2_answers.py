"""Plain-language answers for the U2 analytics pages. Pure functions, no Streamlit.

Same rules as ``u1_answers``: every sentence comes from rows the page already computed, and
claims are scoped to those rows. Nothing here ranks players, fits a model or estimates a value
the page does not already show. No overall "winner" is declared unless the page supplies a
weighting the user chose.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from u1_answers import RATE_STATS, fmt_stat, last_name, stat_name

COMPARE_METRICS = ("HR", "RBI", "SB", "OBP", "OPS")
SMALL_SAMPLE_AB = 300  # below this many at-bats a rate stat can swing a lot


def _num(value: Any) -> float | None:
    v = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(v) else float(v)


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def comparison_answer(career: pd.DataFrame, *, seasons: Mapping[str, int] | None = None, span_text: str = "",
                      metrics: Sequence[str] = COMPARE_METRICS, name_col: str = "fullName") -> dict[str, Any] | None:
    """Head-to-head summary for two or three players, from the page's own totals table
    (one row per player: counting totals plus rates computed from those totals).

    Returns the headline (who leads which metrics), a scoped body, per-metric bar data and the
    leaders by metric. Ties use the displayed precision, so ".301 vs .301" is a tie."""
    if career is None or career.empty or name_col not in career.columns:
        return None
    rows = career.drop_duplicates(name_col)
    players = [str(n).strip() for n in rows[name_col].tolist() if str(n).strip()]
    if len(players) < 2:
        return None
    metrics = [m for m in metrics if m in rows.columns]
    by_name = {str(r[name_col]).strip(): r for _, r in rows.iterrows()}
    leaders: dict[str, list[str]] = {}
    bars = []
    for m in metrics:
        vals = {p: _num(by_name[p].get(m)) for p in players}
        known = {p: v for p, v in vals.items() if v is not None}
        if not known:
            continue
        top_text = fmt_stat(m, max(known.values()))
        lead = [p for p, v in known.items() if fmt_stat(m, v) == top_text]
        leaders[m] = lead
        peak = max(max(known.values()), 0.0)
        bars.append({
            "label": m,
            "rows": [{"name": p, "value": fmt_stat(m, vals[p]),
                      "fraction": (max(vals[p], 0.0) / peak) if (vals[p] is not None and peak > 0) else 0.0,
                      "lead": p in lead and len(lead) < len(known)}
                     for p in players],
        })
    if not leaders:
        return None
    sole: dict[str, list[str]] = {p: [] for p in players}
    tied: list[str] = []
    for m, lead in leaders.items():
        if len(lead) == 1:
            sole[lead[0]].append(m)
        else:
            tied.append(m)
    clauses = [f"{last_name(p)} leads in {_join(ms)}" for p, ms in sole.items() if ms]
    headline = "; ".join(clauses) if clauses else "Even across " + _join(list(leaders))
    if clauses and tied:
        headline += f"; tied in {_join(tied)}"

    abs_ = {p: _num(by_name[p].get("AB")) for p in players}
    sample = []
    for p in players:
        n_seasons = int((seasons or {}).get(p, 0))
        ab = abs_.get(p)
        bits = [_plural(n_seasons, "season")] if n_seasons else []
        if ab is not None:
            bits.append(f"{int(ab):,} AB")
        if bits:
            sample.append(f"{last_name(p)} {', '.join(bits)}")
    body = f"Over {span_text}" if span_text else "Over the seasons shown"
    body += f" ({'; '.join(sample)})." if sample else "."
    counting = [m for m in leaders if m not in RATE_STATS]
    known_ab = [v for v in abs_.values() if v]
    if counting and len(known_ab) >= 2 and max(known_ab) > 1.15 * min(known_ab):
        more = max((p for p in players if abs_.get(p)), key=lambda p: abs_[p])
        extra = round((abs_[more] / min(known_ab) - 1) * 100)
        rates = [m for m in leaders if m in RATE_STATS]
        body += f" {last_name(more)} had {extra}% more at-bats, which counts toward {_join(counting)} (totals)"
        body += f"; {_join(rates)} {'are rates and adjust' if len(rates) > 1 else 'is a rate and adjusts'} for playing time." if rates else "."
    small = [p for p in players if abs_.get(p) is not None and abs_[p] < SMALL_SAMPLE_AB]
    if small:
        body += f" Small sample for {_join([last_name(p) for p in small])} (under {SMALL_SAMPLE_AB} AB), so rates can swing."
    body += " No overall winner: that depends on which categories matter to you."
    return {"headline": headline, "body": body, "bars": bars, "leaders": leaders, "players": players}


def single_player_summary(row: Mapping[str, Any], *, seasons: int = 0, span_text: str = "",
                          metrics: Sequence[str] = COMPARE_METRICS) -> dict[str, Any]:
    """One player picked: their numbers over the range, and the nudge to add a second."""
    name = str(row.get("fullName") or row.get("Player") or "").strip()
    head = name + (f", {span_text}" if span_text else "")
    sub = _plural(int(seasons), "season") if seasons else ""
    ab = _num(row.get("AB"))
    if ab is not None:
        sub = f"{sub} · {int(ab):,} AB" if sub else f"{int(ab):,} AB"
    tiles = [("AVG" if m == "BA" else m, fmt_stat(m, row.get(m)), "") for m in metrics if m in row]
    return {"headline": head, "context": sub, "tiles": tiles, "player": name}


def career_answer(rows: pd.DataFrame, sort_stat: str, year_range: Any, *, seasons: pd.DataFrame | None = None,
                  qualification: str = "") -> dict[str, Any] | None:
    """Career Totals: the leader's career story within the filters.

    ``rows``: the page's career rows, already filtered and qualified. ``seasons``: that
    leader's season rows from the same filtered data (several stints in one year are summed);
    used for the span, the season count and the best season. A best season is named only for
    counting stats; a best rate-stat season would need its own qualification rule."""
    if rows is None or rows.empty or sort_stat not in rows.columns:
        return None
    ranked = rows.assign(_v=pd.to_numeric(rows[sort_stat], errors="coerce")).dropna(subset=["_v"])
    if ranked.empty:
        return None
    ranked = ranked.sort_values("_v", ascending=False, kind="stable")
    top = ranked.iloc[0]
    name = str(top.get("fullName") or "").strip()
    a, b = int(year_range[0]), int(year_range[1])
    span = str(a) if a == b else f"{a}–{b}"
    value = fmt_stat(sort_stat, top.get(sort_stat))
    played, best, n_seasons = "", "", 0
    if seasons is not None and not seasons.empty and "yearID" in seasons.columns:
        years = pd.to_numeric(seasons["yearID"], errors="coerce").dropna().astype(int)
        if not years.empty:
            n_seasons = int(years.nunique())
            first, last = int(years.min()), int(years.max())
            played = f"{_plural(n_seasons, 'season')} ({first}{'' if first == last else f'–{last}'})"
        if sort_stat not in RATE_STATS and sort_stat in seasons.columns and n_seasons > 1:
            per_year = seasons.assign(_v=pd.to_numeric(seasons[sort_stat], errors="coerce")).groupby("yearID")["_v"].sum()
            if not per_year.empty and per_year.max() > 0:
                best = f"Best season for {stat_name(sort_stat)}: {fmt_stat(sort_stat, per_year.max())} in {int(per_year.idxmax())}."
    headline = f"{name}: {value} {stat_name(sort_stat)}" + (f" over {played}" if played else f", {span}")
    facts = []
    games = _num(top.get("G"))
    if games:
        facts.append(f"{int(games):,} games")
    slash = [fmt_stat(s, top.get(s)) for s in ("BA", "OBP", "SLG") if s in top.index]
    if len(slash) == 3 and "—" not in slash:
        facts.append(f"{slash[0]} AVG / {slash[1]} OBP / {slash[2]} SLG")
    body = (" · ".join(facts) + ". ") if facts else ""
    if best:
        body += best + " "
    others = [f"{str(r.get('fullName') or '').strip()} ({fmt_stat(sort_stat, r.get(sort_stat))})" for _, r in ranked.iloc[1:3].iterrows()]
    shown = f"the {_plural(len(ranked), 'hitter')} shown for {span}"
    if others and fmt_stat(sort_stat, ranked.iloc[1].get(sort_stat)) == value:
        body += f"Tied for the lead among {shown}, with {_join(others)}."
    else:
        body += f"Leads {shown}" + (f", ahead of {_join(others)}." if others else ".")
    team = str(top.get("displayTeam") or "").strip()
    pos = str(top.get("displayPosition") or "").strip()
    tile_stats = [sort_stat] + [s for s in ("HR", "RBI", "SB", "BA", "OPS") if s != sort_stat][:4]
    tiles = [("AVG" if s == "BA" else s, fmt_stat(s, top.get(s)), "") for s in tile_stats if s in top.index]
    if games:
        tiles.insert(1, ("G", f"{int(games):,}", ""))
    return {
        "headline": headline,
        "body": body.strip(),
        "context": " · ".join(x for x in (f"Career leader · {stat_name(sort_stat)} · {span}", team, pos) if x),
        "tiles": tiles,
        "player": name,
        "qualification": qualification,
        "seasons": n_seasons,
    }

