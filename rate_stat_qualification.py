"""Default qualification minimum for rate-stat rankings (BA / OBP / SLG / OPS).

Ranking by a rate stat with no sample-size floor puts 1-for-1 pitchers (1.000 BA,
2.000 OPS) at the top. When a ranking page sorts by a rate stat, its existing
"Min AB" control defaults to a qualification minimum based on MLB's batting-title
rule (3.1 plate appearances per scheduled team game), expressed in at-bats because
these pages filter on AB:

* one season (Historical Explorer rows): 2.7 AB per team game of a full season in
  the selected years (437 AB for 162 games);
* totals over a span (Leaderboards, Career Totals): 2.7 AB per team game summed over
  the seasons in range, capped at a career-length 3,000 AB.

Season length comes from the data (see ``_schedule_games``), so 2020 counts 60 games
and 1871 counts 33. Counting stats get no automatic minimum.
The control stays editable: once the user sets it, that value (including 0) is kept
until they choose "Use qualified minimum" again.
"""

from __future__ import annotations

from typing import Any, Iterable, MutableMapping

RATE_STAT_KEYS = ("BA", "OBP", "SLG", "OPS")
AB_PER_TEAM_GAME = 2.7
MULTI_SEASON_CAP_AB = 3000
DEFAULT_SEASON_GAMES = 162
MODE_AUTO = "auto"
MODE_MANUAL = "manual"


def is_rate_stat(stat: Any) -> bool:
    return str(stat or "") in RATE_STAT_KEYS


def mode_key(prefix: str) -> str:
    return f"{prefix}_ab_qualification_mode"


def ab_min_key(prefix: str) -> str:
    return f"{prefix}_AB_min"


MAX_SCHEDULE_GAMES = 162


def season_lengths(yearly_df: Any) -> dict[int, int]:
    """Approximate each season's schedule from games played.

    The second-highest total skips the one traded player or tiebreak game that pushes the
    maximum past the schedule (seasons with under five players use the maximum); no MLB
    schedule has exceeded 162 games. Off by a game or two in some years, which moves the
    minimum by a few AB.
    """
    try:
        g = yearly_df[["yearID", "G"]].dropna()
        g = g[g["G"] > 0].sort_values(["yearID", "G"], ascending=[True, False])
        top = g.groupby("yearID").head(2).groupby("yearID")["G"].agg(["max", "min"])
        players = g.groupby("yearID").size()
        games = top["min"].where(players.reindex(top.index) >= 5, top["max"]).clip(upper=MAX_SCHEDULE_GAMES)
        return {int(y): int(v) for y, v in games.items() if int(v) > 0}
    except Exception:
        return {}


def _years(year_range: Any) -> list[int]:
    try:
        lo, hi = int(year_range[0]), int(year_range[1])
    except (TypeError, ValueError, IndexError):
        return []
    if lo > hi:
        lo, hi = hi, lo
    return list(range(lo, hi + 1))


def qualified_ab(lengths: dict[int, int], year_range: Any, *, span: bool) -> dict[str, Any]:
    """The qualifying AB for ``year_range``.

    ``span=False``: one season (rows are single seasons) — a full season in range.
    ``span=True``: totals over the range — summed over its seasons, capped.
    Returns the minimum plus what the caption needs to explain it.
    """
    years = _years(year_range)
    games = [lengths.get(y, DEFAULT_SEASON_GAMES) for y in years] or [DEFAULT_SEASON_GAMES]
    full = max(games)
    if span:
        raw = AB_PER_TEAM_GAME * sum(games)
        value = int(round(min(raw, MULTI_SEASON_CAP_AB)))
        capped = raw > MULTI_SEASON_CAP_AB
    else:
        value = int(round(AB_PER_TEAM_GAME * full))
        capped = False
    short = [y for y, g in zip(years, games) if g < 0.9 * full] if not span else []
    return {"value": value, "span": span, "seasons": len(years), "full_season_games": full,
            "capped": capped, "short_seasons": short}


def resolve_ab_minimum(session: MutableMapping[str, Any], prefix: str, sort_stat: Any, qualified: int) -> dict[str, Any]:
    """Keep the Min AB control on the qualified default while it is automatic.

    Call before the Min AB widget renders. Automatic mode: rate-stat sort → the
    qualified minimum, counting-stat sort → 0. Manual mode (the user edited the
    control): leave the value alone.
    """
    mk, ak = mode_key(prefix), ab_min_key(prefix)
    mode = session.get(mk) if session.get(mk) in (MODE_AUTO, MODE_MANUAL) else MODE_AUTO
    rate = is_rate_stat(sort_stat)
    if mode == MODE_AUTO:
        target = int(qualified) if rate else 0
        current = session.get(ak)
        try:
            same = current is not None and int(float(current)) == target
        except (TypeError, ValueError):
            same = False
        if not same:
            session[ak] = target
    try:
        value = int(float(session.get(ak) or 0))
    except (TypeError, ValueError):
        value = 0
    return {"mode": mode, "rate": rate, "value": value, "qualified": int(qualified)}


def mark_manual(session: MutableMapping[str, Any], prefix: str) -> None:
    session[mode_key(prefix)] = MODE_MANUAL


def restore_auto(session: MutableMapping[str, Any], prefix: str) -> None:
    session[mode_key(prefix)] = MODE_AUTO


def qualification_caption(state: dict[str, Any], info: dict[str, Any], sort_stat: Any) -> str:
    """One line telling the user which minimum is active for this rate-stat ranking."""
    if not state.get("rate"):
        return ""
    value = int(state.get("value") or 0)
    if state.get("mode") == MODE_AUTO and value > 0:
        basis = _caption_basis(info)
        line = (
            f"**Qualified hitters only:** ranking by {sort_stat} requires at least **{value:,} AB** "
            f"({basis}, close to MLB's batting-title rule). Change it under *Stat minimum filters*."
        )
        if info.get("short_seasons"):
            yrs = ", ".join(str(y) for y in info["short_seasons"][:4])
            line += f" Shortened seasons in range ({yrs}) need a lower minimum to appear."
        return line
    if value > 0:
        return f"**Minimum {value:,} AB** (set manually) for this {sort_stat} ranking."
    return f"**No AB minimum** — players with very few at-bats can top this {sort_stat} ranking."


def _caption_basis(info: dict[str, Any]) -> str:
    if info.get("span"):
        return (
            "a career-length minimum for spans this long" if info.get("capped")
            else f"about 2.7 AB per team game over {info.get('seasons')} season(s)"
        )
    return "about 2.7 AB per team game of a full season"


def qualification_explanation(state: dict[str, Any], info: dict[str, Any], stat_label: Any) -> str:
    """``qualification_caption`` as plain text for other surfaces: no Markdown, no control
    names. ``stat_label`` is how the stat is named there (e.g. "batting average")."""
    if not state.get("rate"):
        return ""
    value = int(state.get("value") or 0)
    if state.get("mode") == MODE_AUTO and value > 0:
        line = (
            f"Qualified hitters only: ranking by {stat_label} requires at least {value:,} AB "
            f"({_caption_basis(info)}, close to MLB's batting-title rule)."
        )
        if info.get("short_seasons"):
            yrs = ", ".join(str(y) for y in info["short_seasons"][:4])
            line += f" Shortened seasons in range ({yrs}) need a lower minimum to appear."
        return line
    if value > 0:
        return f"Minimum {value:,} AB (set manually) for this {stat_label} ranking."
    return f"No AB minimum: players with very few at-bats can top this {stat_label} ranking."
