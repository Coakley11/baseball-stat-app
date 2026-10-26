"""Fantasy position eligibility from games actually played — one rule for every page.

Sources (no reputation guesses):

* Current season: MLB Stats API fielding splits (games by position, DH included).
* Prior season: Lahman ``Fielding.csv`` (games by position; no DH), matched to MLB players
  only by exact birth date + last name + first initial. Anything that does not match
  exactly gets no prior-season positions.
* The player's primary position from the hitting feed.

Rule: a hitter is eligible at a position with at least ``MIN_GAMES`` games there in the
current or the prior season, plus his primary position. LF/CF/RF count as OF. UTIL takes
any hitter (see ``fantasy_lineup_fill``). Players with no fielding data keep only their
primary position — conservative, never widened by guesswork.

Rows carry the result as ``Eligible Positions`` (e.g. ``"OF, DH"``).
"""

from __future__ import annotations

import functools
import re
import unicodedata
from typing import Any

MIN_GAMES = 10
ELIGIBLE_COL = "Eligible Positions"
HITTER_POSITIONS = ("C", "1B", "2B", "3B", "SS", "OF", "DH")
_ALIASES = {"LF": "OF", "CF": "OF", "RF": "OF", "UT": "DH", "UTIL": "DH", "TWP": "DH", "SP": "P", "RP": "P"}


def normalize_position(token: Any) -> str:
    text = str(token or "").strip().upper()
    text = re.sub(r"\d+$", "", text)  # FantasyPros-style OF1/SS2
    return _ALIASES.get(text, text)


def split_positions(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        parts = [str(x) for x in raw]
    else:
        text = str(raw)
        if text.strip().lower() in ("", "nan", "none"):
            return []
        parts = re.split(r"[,/|;]+", text)
    out: list[str] = []
    for part in parts:
        token = normalize_position(part)
        if token and token not in out:
            out.append(token)
    return out


def eligible_positions_from_row(row: Any) -> set[str]:
    """Eligible positions for a player row: the canonical column plus the primary position."""
    getter = row.get if hasattr(row, "get") else (lambda _k, _d=None: None)
    positions: set[str] = set()
    for col in (ELIGIBLE_COL, "eligible_positions", "positions", "Primary Position", "Position", "Pos"):
        try:
            val = getter(col)
        except Exception:
            val = None
        positions.update(split_positions(val))
    return {p for p in positions if p}


def positions_from_games(games_by_position: dict[str, float], *, min_games: int = MIN_GAMES) -> set[str]:
    out: set[str] = set()
    totals: dict[str, float] = {}
    for pos, games in (games_by_position or {}).items():
        token = normalize_position(pos)
        if token:
            totals[token] = totals.get(token, 0.0) + float(games or 0)
    for token, games in totals.items():
        if games >= min_games and token in HITTER_POSITIONS + ("P",):
            out.add(token)
    return out


def format_positions(positions: set[str] | list[str]) -> str:
    order = {p: i for i, p in enumerate(HITTER_POSITIONS + ("P",))}
    return ", ".join(sorted(set(positions), key=lambda p: (order.get(p, 99), p)))


# --- data sources ----------------------------------------------------------------------


def _fold(text: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", raw.lower())


def fetch_current_season_fielding(season: int, *, timeout: float = 12.0) -> dict[int, dict[str, Any]]:
    """MLBAM id -> {"games": {pos: G}, "birth_date": "YYYY-MM-DD", "name": str} from the MLB Stats API."""
    import requests

    params = {"stats": "season", "group": "fielding", "playerPool": "ALL", "season": int(season),
              "sportIds": 1, "limit": 8000, "hydrate": "person"}
    resp = requests.get("https://statsapi.mlb.com/api/v1/stats", params=params, timeout=timeout)
    resp.raise_for_status()
    out: dict[int, dict[str, Any]] = {}
    for split in (resp.json().get("stats") or [{}])[0].get("splits", []):
        person = split.get("player") or {}
        pid = person.get("id")
        pos = (split.get("position") or {}).get("abbreviation")
        if pid is None or not pos:
            continue
        entry = out.setdefault(int(pid), {"games": {}, "birth_date": str(person.get("birthDate") or ""),
                                          "name": str(person.get("fullName") or "")})
        entry["games"][pos] = entry["games"].get(pos, 0) + int((split.get("stat") or {}).get("gamesPlayed") or 0)
    return out


@functools.lru_cache(maxsize=4)
def prior_season_lahman_positions(season: int, base_dir: str = ".") -> dict[tuple[str, str, str], dict[str, float]]:
    """(birth_date, folded last name, first initial) -> {pos: games} for ``season`` from Lahman."""
    import os

    import pandas as pd

    fielding_path = os.path.join(base_dir, "Fielding.csv")
    people_path = os.path.join(base_dir, "People.csv")
    if not (os.path.exists(fielding_path) and os.path.exists(people_path)):
        return {}
    fielding = pd.read_csv(fielding_path, usecols=["playerID", "yearID", "POS", "G"], low_memory=False)
    fielding = fielding[fielding["yearID"] == int(season)]
    if fielding.empty:
        return {}
    people = pd.read_csv(people_path, usecols=["playerID", "nameFirst", "nameLast", "birthYear", "birthMonth", "birthDay"],
                         low_memory=False)
    people = people[people["playerID"].isin(set(fielding["playerID"]))].dropna(subset=["birthYear", "birthMonth", "birthDay"])
    keys: dict[str, tuple[str, str, str]] = {}
    for _, p in people.iterrows():
        birth = f"{int(p['birthYear']):04d}-{int(p['birthMonth']):02d}-{int(p['birthDay']):02d}"
        keys[str(p["playerID"])] = (birth, _fold(p["nameLast"]), _fold(p["nameFirst"])[:1])
    out: dict[tuple[str, str, str], dict[str, float]] = {}
    for pid, grp in fielding.groupby("playerID"):
        key = keys.get(str(pid))
        if key is None:
            continue
        games = out.setdefault(key, {})
        for pos, g in grp.groupby("POS")["G"].sum().items():
            games[str(pos)] = games.get(str(pos), 0) + float(g)
    return out


def _person_key(name: str, birth_date: str) -> tuple[str, str, str] | None:
    parts = str(name or "").split()
    if not parts or not birth_date:
        return None
    suffixes = {"jr", "sr", "ii", "iii", "iv"}
    last_parts = [p for p in parts[1:] if _fold(p) not in suffixes] or parts[-1:]
    return (str(birth_date)[:10], _fold(" ".join(last_parts)), _fold(parts[0])[:1])


def build_eligibility_map(
    season: int,
    *,
    current: dict[int, dict[str, Any]] | None = None,
    prior: dict[tuple[str, str, str], dict[str, float]] | None = None,
    min_games: int = MIN_GAMES,
) -> dict[int, set[str]]:
    """MLBAM id -> eligible positions (current-season or prior-season games)."""
    out: dict[int, set[str]] = {}
    for pid, info in (current or {}).items():
        positions = positions_from_games(info.get("games") or {}, min_games=min_games)
        key = _person_key(info.get("name", ""), info.get("birth_date", ""))
        if key and prior and key in prior:
            positions |= positions_from_games(prior[key], min_games=min_games)
        if positions:
            out[int(pid)] = positions
    return out


_CACHE: dict[int, tuple[float, dict[int, set[str]]]] = {}
_CACHE_TTL_S = 6 * 3600


def eligibility_for_season(season: int, *, base_dir: str = "") -> dict[int, set[str]]:
    """Cached eligibility map for season (MLB current-season games + Lahman prior season).

    Network or file problems return what is available (possibly {}); callers then fall back
    to primary positions only.
    """
    import os
    import time

    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    hit = _CACHE.get(int(season))
    if hit and time.time() - hit[0] < _CACHE_TTL_S:
        return hit[1]
    try:
        current = fetch_current_season_fielding(int(season))
    except Exception:
        current = {}
    try:
        prior = prior_season_lahman_positions(int(season) - 1, base_dir=base_dir)
    except Exception:
        prior = {}
    result = build_eligibility_map(int(season), current=current, prior=prior)
    if result:
        _CACHE[int(season)] = (time.time(), result)
    return result


def attach_eligible_positions(df: Any, eligibility: dict[int, set[str]], *, id_col: str = "MLBAM ID") -> Any:
    """Add ``Eligible Positions`` to a stats frame (primary position always included)."""
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    values: list[str] = []
    for _, row in out.iterrows():
        positions = set(split_positions(row.get("Primary Position")))
        try:
            pid = int(float(row.get(id_col)))
        except (TypeError, ValueError):
            pid = None
        if pid is not None:
            positions |= eligibility.get(pid, set())
        values.append(format_positions(positions))
    out[ELIGIBLE_COL] = values
    return out
