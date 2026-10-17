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


def slope_text(stat: str, slope: Any) -> str:
    """'+.045' for rate stats, '+3.5' for counting stats (per season)."""
    v = _num(slope)
    if v is None:
        return "—"
    if stat in RATE_STATS:
        text = f"{abs(v):.3f}"
        text = text[1:] if text.startswith("0.") else text
    else:
        text = f"{abs(v):.1f}"
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}{text}" if sign and text.strip("0.") else text


def _direction(stat: str, slope: float) -> str:
    shown = slope_text(stat, slope).lstrip("+−")
    if not shown.strip("0."):
        return "flat"
    return "up" if slope > 0 else "down"


def _path_text(stat: str, values: Sequence[tuple] | None) -> str:
    """'.218 in 2023, 39 AB → .912 in 2025, 520 AB'. Entries are (year, value) or
    (year, value, at_bats); at-bats are shown for rate stats so a small sample is visible."""
    pts = sorted((int(p[0]), p[1], _num(p[2]) if len(p) > 2 else None) for p in (values or []) if _num(p[1]) is not None)
    if len(pts) < 2:
        return ""

    def one(p) -> str:
        ab = f", {int(p[2]):,} AB" if stat in RATE_STATS and p[2] is not None else ""
        return f"{fmt_stat(stat, p[1])} in {p[0]}{ab}"

    return f"{one(pts[0])} → {one(pts[-1])}"


def trend_answer(rows: pd.DataFrame, stat: str, years: Sequence[int], *, slope_col: str = "",
                 values: Mapping[str, Sequence[tuple[int, Any]]] | None = None,
                 focus: str = "") -> dict[str, Any] | None:
    """Trend Value: who is rising and falling fastest in ``stat`` over the window, from the
    page's own per-season slopes (``{stat}_trend``). ``values``: season values by player name,
    for the "from → to" text. ``focus``: a player the user sent here; leads when present."""
    slope_col = slope_col or f"{stat}_trend"
    if rows is None or rows.empty or slope_col not in rows.columns:
        return None
    ranked = rows.assign(_s=pd.to_numeric(rows[slope_col], errors="coerce")).dropna(subset=["_s"])
    if ranked.empty:
        return None
    ranked = ranked.sort_values("_s", ascending=False, kind="stable").reset_index(drop=True)
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
    name = lambda r: str(r.get("fullName") or "").strip()  # noqa: E731
    riser, faller = ranked.iloc[0], ranked.iloc[-1]
    up = int(sum(_direction(stat, float(v)) == "up" for v in ranked["_s"]))
    total = len(ranked)
    what = stat_name(stat)
    rate = stat in RATE_STATS

    def line(r) -> str:
        path = _path_text(stat, (values or {}).get(name(r)))
        return f"{name(r)} ({slope_text(stat, r['_s'])} per season{': ' + path if path else ''})"

    focus_row = None
    if focus:
        match = ranked[ranked["fullName"].astype(str).str.strip() == focus]
        focus_row = match.iloc[0] if not match.empty else None
    if focus_row is not None:
        rank = int(match.index[0]) + 1
        direction = _direction(stat, float(focus_row["_s"]))
        verb = "flat" if direction == "flat" else f"trending {direction} by about {slope_text(stat, focus_row['_s']).lstrip('+−')} per season"
        headline = f"{focus}: {stat} {verb} ({span})"
        path = _path_text(stat, (values or {}).get(focus))
        body = (f"{path}. " if path else "") + f"Ranks {_ordinal(rank)} of {total:,} hitters shown by {stat} trend. "
        body += f"Fastest riser: {line(riser)}. Biggest drop: {line(faller)}."
        kicker = f"Your player · {stat} trend · {span}"
        chart_names = [focus] + [n for n in (name(riser), name(faller)) if n != focus][:1]
    elif focus:
        headline = f"Biggest {stat} riser, {span}: {name(riser)}"
        body = (f"{focus} isn't in the current list (check Minimum Games and Fantasy Position under Explore more). "
                f"Fastest riser: {line(riser)}. Biggest drop: {line(faller)}.")
        kicker = f"{stat} trend · {span}"
        chart_names = [name(riser), name(faller)]
    else:
        headline = f"Biggest {stat} riser, {span}: {name(riser)}, about {slope_text(stat, riser['_s']).lstrip('+−')} per season"
        if float(riser["_s"]) <= 0:
            headline = f"No hitter shown is trending up in {stat} over {span}"
        path = _path_text(stat, (values or {}).get(name(riser)))
        body = (f"{path}. " if path else "") + f"Biggest drop: {line(faller)}."
        kicker = f"{stat} trend · {span}"
        chart_names = [name(riser), name(faller)]
    body += f" {up:,} of {total:,} hitters shown {'is' if up == 1 else 'are'} trending up."
    if rate:
        body += " Rate-stat trends weight seasons by playing time so small samples have less influence."
    else:
        body += f" The trend is the per-season slope of each player's season {what}."
    return {"headline": headline, "body": body, "kicker": kicker, "chart_names": chart_names,
            "riser": name(riser), "faller": name(faller), "focus_found": focus_row is not None}


def _rank_of(series: pd.Series, value: float) -> int:
    vals = pd.to_numeric(series, errors="coerce")
    return int((vals > value).sum()) + 1


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n:,}{suffix}"


def valuation_answer(rows: pd.DataFrame, model_rows: pd.DataFrame, *, w_current: float, w_trend: float,
                     years: Sequence[int]) -> dict[str, Any] | None:
    """Valuation: the top player and why, in the model's own terms.

    ``rows``: what the table ranks (after any Research-mode position-need boost).
    ``model_rows``: the valued pool straight from ``add_valuation_scores`` (Perf_Score,
    Trend_Score, Perf_Pct, Trend_Pct). Valuation = weighted average of the production and
    trend percentiles, rescaled 0–100. A trend score of zero (including "no trend") is neutral,
    never called a decline."""
    need = {"fullName", "Valuation_Score"}
    if rows is None or rows.empty or not need <= set(rows.columns) or model_rows is None or model_rows.empty:
        return None
    ranked = rows.assign(_v=pd.to_numeric(rows["Valuation_Score"], errors="coerce")).dropna(subset=["_v"])
    if ranked.empty:
        return None
    ranked = ranked.sort_values("_v", ascending=False, kind="stable")
    top = ranked.iloc[0]
    name = str(top["fullName"]).strip()
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
    match = model_rows[model_rows["fullName"].astype(str).str.strip() == name]
    m = match.iloc[0] if not match.empty else top
    pool = len(model_rows)
    perf = _num(m.get("Perf_Score"))
    trend = _num(m.get("Trend_Score"))
    perf_rank = _rank_of(model_rows["Perf_Score"], perf) if perf is not None else None
    trend_rank = _rank_of(model_rows["Trend_Score"], trend) if trend is not None else None
    if trend is None or round(trend, 1) == 0:
        trend_word = "about flat"
    else:
        trend_word = "trending up" if trend > 0 else "trending down"
    score = f"{float(top['_v']) * 100:.0f}"
    wc, wt = float(w_current), float(w_trend)
    weights = f"{wc:g} : {wt:g}"
    parts = []
    if perf_rank:
        parts.append(f"Production ranks {_ordinal(perf_rank)} of {pool:,}")
    if trend_rank:
        parts.append(f"trend ranks {_ordinal(trend_rank)} ({trend_word})")
    body = (", ".join(parts) + ". ") if parts else ""
    pp, tp = _num(m.get("Perf_Pct")), _num(m.get("Trend_Pct"))
    if pp is not None and tp is not None and wc > 0 and wt > 0:
        if pp - tp >= 0.2:
            body += "The score comes mainly from production. "
        elif tp - pp >= 0.2:
            body += "The score comes mainly from the trend. "
        else:
            body += "Production and trend both rank high. "
    body += (f"Valuation Score is a {weights} blend (production : trend) of each hitter's percentile among the "
             f"{pool:,} hitters valued for {span}, rescaled 0–100 (top = 100).")
    boosted = False
    if "Valuation_Score" in m.index and _num(m.get("Valuation_Score")) is not None:
        boosted = abs(float(m["Valuation_Score"]) - float(top["_v"])) > 1e-9
    if boosted:
        body += " This list also includes your league's position-need boost (Research mode)."
    tiles = [("Valuation", score, f"1st of {len(ranked):,}")]
    if perf_rank:
        tiles.append(("Production", _ordinal(perf_rank), f"Current Score {perf:,.1f}"))
    if trend_rank:
        tiles.append(("Trend", _ordinal(trend_rank), f"Trend Score {trend:+,.1f}" if trend_word != "about flat" else "about flat"))
    tiles.append(("Weights", weights, "production : trend"))
    return {"headline": f"Top valuation, {span}: {name}", "body": body, "tiles": tiles, "player": name,
            "next": [str(n) for n in ranked["fullName"].head(2).tolist()], "trend_word": trend_word}


def _proj_bits(row: Mapping[str, Any]) -> str:
    bits = []
    for label, keys, rate in (("HR", ("Projected HR", "proj_HR"), False), ("RBI", ("Projected RBI", "proj_RBI"), False),
                              ("SB", ("Projected SB", "proj_SB"), False), ("OPS", ("Projected OPS", "proj_OPS"), True)):
        v = next((_num(row.get(k)) for k in keys if _num(row.get(k)) is not None), None)
        if v is not None:
            bits.append(f"{fmt_stat('OPS', v)} OPS" if rate else f"{int(round(v)):,} {label}")
    return ", ".join(bits)


def sleeper_bust_answer(sleepers: pd.DataFrame, busts: pd.DataFrame, *, n: int = 4, matched: int = 0,
                        fantasy_format: str = "") -> dict[str, Any] | None:
    """Sleepers & Busts: the biggest gaps between our model's rank and the market's
    (FantasyPros / ADP). ``Fantasy Edge`` = Market Rank − Model Rank, as the page computes it.
    Sleeper = edge > 0 (model ranks the player better than the market); bust risk = edge < 0.
    These are ranking gaps, not predictions."""
    def cards(df: pd.DataFrame, kind: str) -> list[dict[str, Any]]:
        if df is None or df.empty or "Fantasy Edge" not in df.columns:
            return []
        edge = pd.to_numeric(df["Fantasy Edge"], errors="coerce")
        keep = df[edge > 0] if kind == "sleeper" else df[edge < 0]
        out = []
        for _, r in keep.head(n).iterrows():
            name = str(r.get("fullName") or r.get("Player") or "").strip()
            model, market, e = _num(r.get("Model Rank")), _num(r.get("Market Rank")), _num(r.get("Fantasy Edge"))
            if model is None or market is None or e is None:
                continue
            gap = abs(int(round(e)))
            if kind == "sleeper":
                body = f"Our model ranks {last_name(name)} {gap} spot{'s' if gap != 1 else ''} higher than the market does."
            else:
                body = f"The market ranks {last_name(name)} {gap} spot{'s' if gap != 1 else ''} higher than our model supports."
            proj = _proj_bits(r)
            if proj:
                body += f" Model projection: {proj}."
            sub = " · ".join(x for x in (str(r.get("Primary Position") or "").strip(), str(r.get("Team") or "").strip()) if x and x != "Unknown")
            out.append({"title": name, "sub": sub, "body": body,
                        "facts": [("Model", f"#{int(model)}"), ("Market", f"#{int(market)}"), ("Fantasy Edge", f"{int(round(e)):+d}")],
                        "tone": "good" if kind == "sleeper" else "warn"})
        return out

    s_cards, b_cards = cards(sleepers, "sleeper"), cards(busts, "bust")
    if not s_cards and not b_cards:
        return None
    if s_cards:
        top = s_cards[0]
        headline = f"Biggest sleeper: {top['title']} (model {top['facts'][0][1]}, market {top['facts'][1][1]})"
    else:
        headline = "No sleepers in this pool: the market ranks everyone at or above our model"
    body = ("Sleeper = our model ranks the player better than the market (FantasyPros rankings and ADP). "
            "Bust risk = the market's price is higher than our model supports. These are ranking gaps, not predictions of how a season will go.")
    if matched:
        body += f" {matched:,} players have both a model and a market rank"
        body += f" ({fantasy_format})." if fantasy_format else "."
    return {"headline": headline, "body": body, "sleepers": s_cards, "busts": b_cards,
            "players": [c["title"] for c in s_cards[:2]]}


def _ml_value(col: str, value: Any) -> str:
    stat = col.replace("Predicted ", "")
    if col.startswith("Predicted "):
        return fmt_stat(stat, value)
    v = _num(value)
    if v is None:
        return "—"
    return f"{v:.2f}" if "Score" in col else f"{v:,.1f}"


def ml_answer(view: pd.DataFrame, sort_col: str, *, models: Mapping[str, Any] | None = None,
              player_count: int = 0, n: int = 5) -> dict[str, Any] | None:
    """ML Predictions: the top projected hitters for the chosen stat, with the model's own
    holdout accuracy for that stat (MAE, R²) and its confidence label. No interval is shown
    because the model does not produce one. Position/Team sorts fall back to Predicted OPS."""
    if view is None or view.empty:
        return None
    col = sort_col if sort_col in view.columns and sort_col not in ("Position", "Team") else "Predicted OPS"
    if col not in view.columns:
        return None
    ranked = view.assign(_v=pd.to_numeric(view[col], errors="coerce")).dropna(subset=["_v"])
    if ranked.empty:
        return None
    ranked = ranked.sort_values("_v", ascending=False, kind="stable").head(n)
    top = ranked.iloc[0]
    year = top.get("prediction_year")
    year_text = f" for {int(year)}" if _num(year) is not None else ""
    label = col.replace("Predicted ", "projected ") if col.startswith("Predicted ") else col
    name = str(top.get("fullName") or top.get("Player") or "").strip()
    headline = f"Top {label}{year_text}: {name}, {_ml_value(col, top['_v'])}"
    total = int(player_count or len(view))
    body = f"Top {len(ranked)} of {total:,} hitters projected{year_text}."
    stat = col.replace("Predicted ", "")
    info = (models or {}).get(stat) if col.startswith("Predicted ") else None
    if isinstance(info, Mapping) and _num(info.get("mae")) is not None:
        mae = float(info["mae"])
        mae_text = fmt_stat(stat, mae) if stat in RATE_STATS else f"{mae:.1f}"
        body += f" Model check: on held-out seasons the {stat} model misses by about {mae_text} on average"
        r2 = _num(info.get("r2"))
        body += f" (R² {r2:.2f})." if r2 is not None else "."
    if "Projection Confidence" in ranked.columns:
        body += " Confidence (High / Medium / Risky) is the model's label from sample size and volatility, not a statistical range."
    rows = []
    for i, (_, r) in enumerate(ranked.iterrows(), start=1):
        sub = " · ".join(x for x in (str(r.get("Position") or "").strip(), str(r.get("primaryTeamID") or "").strip(),
                                     str(r.get("Projection Confidence") or "").strip()) if x and x.lower() != "nan")
        rows.append({"rank": i, "name": str(r.get("fullName") or r.get("Player") or "").strip(), "sub": sub,
                     "value": _ml_value(col, r["_v"])})
    return {"headline": headline, "body": body, "rows": rows, "sorted_by": col,
            "players": [r["name"] for r in rows[:2]]}
