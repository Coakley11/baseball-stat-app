"""Player-name resolution against the app's season frame.

Deterministic and transparent: a bare surname resolves only when one player clearly
dominates (prefers the page's selected players, then hitters, then recent players, then
playing time at a 3:1 margin); otherwise the result is ``ambiguous`` with the candidates,
and AMI asks instead of guessing.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from ami_assistant.data import RECENT_SEASONS, BaseballDataset
from player_name_normalization import normalize_player_name_for_merge

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
NOT_FOUND = "not_found"
DOMINANCE_RATIO = 3.0
FUZZY_CUTOFF = 0.9

_POSSESSIVE = re.compile(r"(?:'s|’s|')$")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z.'’\-]*")


@dataclass(frozen=True)
class PlayerRef:
    player_id: str
    name: str
    first_season: int
    last_season: int

    @property
    def label(self) -> str:
        span = str(self.first_season) if self.first_season == self.last_season else f"{self.first_season}–{self.last_season}"
        return f"{self.name} ({span})"

    def as_dict(self) -> dict:
        return {"player_id": self.player_id, "name": self.name, "seasons": [self.first_season, self.last_season]}


@dataclass(frozen=True)
class Resolution:
    status: str
    query: str
    player: PlayerRef | None = None
    candidates: tuple[PlayerRef, ...] = field(default_factory=tuple)
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "query": self.query,
            "player": self.player.as_dict() if self.player else None,
            "candidates": [c.as_dict() for c in self.candidates],
            "note": self.note,
        }


def player_ref(ds: BaseballDataset, player_id: str) -> PlayerRef:
    row = ds.players.loc[player_id]
    return PlayerRef(player_id, str(row["fullName"]), int(row["first_season"]), int(row["last_season"]))


def normalize_query(text: str) -> str:
    return normalize_player_name_for_merge(_POSSESSIVE.sub("", str(text or "").strip()))


def _refs(ds: BaseballDataset, frame: pd.DataFrame) -> tuple[PlayerRef, ...]:
    return tuple(player_ref(ds, pid) for pid in frame.index)


def _pick(ds: BaseballDataset, matches: pd.DataFrame, prefer_ids: Iterable[str]) -> tuple[pd.DataFrame, str]:
    """Narrow several same-name matches; returns the remaining frame and the rule used."""
    preferred = matches[matches.index.isin(list(prefer_ids))]
    if len(preferred) == 1:
        return preferred, "on screen"
    pool = matches
    if "position" in pool.columns:
        hitters = pool[pool["position"].astype(str) != "P"]
        if len(hitters):
            pool = hitters
    if len(pool) == 1:
        return pool, "the hitter"
    recent = pool[pool["last_season"] > ds.latest_season - RECENT_SEASONS]
    if len(recent) == 1:
        return recent, "recent"
    ranked, col = (recent, "recent_ab") if len(recent) else (pool, "career_ab")
    ranked = ranked.sort_values([col, "last_season"], ascending=False)
    top, second = float(ranked[col].iloc[0]), float(ranked[col].iloc[1])
    if top > 0 and top >= DOMINANCE_RATIO * second:
        return ranked.head(1), "most at-bats"
    return ranked, ""


def resolve_player(ds: BaseballDataset, query: str, *, prefer_ids: Iterable[str] = ()) -> Resolution:
    q = normalize_query(query)
    if not q:
        return Resolution(NOT_FOUND, str(query or ""))
    table = ds.players
    matches = table[table["norm_full"] == q]
    if matches.empty and " " not in q:
        matches = table[table["norm_last"] == q]
    if matches.empty and " " in q:
        first, last = q.split(" ", 1)[0], q.rsplit(" ", 1)[-1]
        matches = table[(table["norm_last"] == last) & table["norm_full"].str.startswith(first)]
    if matches.empty:
        close = difflib.get_close_matches(q, table["norm_full"].unique().tolist(), n=4, cutoff=0.8)
        near = table[table["norm_full"].isin(close)]
        if len(close) == 1 and difflib.SequenceMatcher(None, q, close[0]).ratio() >= FUZZY_CUTOFF:
            narrowed, _ = _pick(ds, near, prefer_ids) if len(near) > 1 else (near, "")
            if len(narrowed) == 1:
                ref = player_ref(ds, narrowed.index[0])
                return Resolution(RESOLVED, str(query), ref, (ref,), f"Read “{query}” as {ref.label}.")
        return Resolution(NOT_FOUND, str(query), None, _refs(ds, near.head(4)))
    if len(matches) == 1:
        ref = player_ref(ds, matches.index[0])
        return Resolution(RESOLVED, str(query), ref, (ref,))
    narrowed, rule = _pick(ds, matches, prefer_ids)
    everyone = _refs(ds, matches.sort_values("last_season", ascending=False).head(6))
    if len(narrowed) == 1:
        ref = player_ref(ds, narrowed.index[0])
        others = [c.label for c in everyone if c.player_id != ref.player_id][:3]
        note = f"Read “{query}” as {ref.label}" + (f" (also matches {', '.join(others)})." if others else ".")
        return Resolution(RESOLVED, str(query), ref, everyone, note if rule != "on screen" else "")
    return Resolution(AMBIGUOUS, str(query), None, _refs(ds, narrowed.head(6)))


_SPAN_LABEL = re.compile(r"^(?P<name>.+?) \((?P<lo>\d{4})-(?P<hi>\d{4})\)$")


def resolve_label(ds: BaseballDataset, label: str) -> Resolution:
    """A page dropdown label: "Name", or "Name (first-last)" when names repeat."""
    m = _SPAN_LABEL.match(str(label or "").strip())
    if m:
        q = normalize_query(m.group("name"))
        hit = ds.players[
            (ds.players["norm_full"] == q)
            & (ds.players["first_season"] == int(m.group("lo")))
            & (ds.players["last_season"] == int(m.group("hi")))
        ]
        if len(hit) == 1:
            ref = player_ref(ds, hit.index[0])
            return Resolution(RESOLVED, str(label), ref, (ref,))
    return resolve_player(ds, str(label).split(" (")[0])


# Capitalized words that are never read as a surname on their own.
BASE_STOPWORDS = frozenset(
    """
    a about after against all also am an and any are as at average away bad be been before best better
    between big biggest both but by can career chart compare comparison could current currently did do
    does draft during each either explain fantasy for from give good great had has have he help her here
    him his how i if in into is it its just last league leader leaders least like list long look made make
    many me mean means more most much my need next no not now of off on one only or other our over page
    pick player players please power rank ranked ranking rate recent same season seasons should show since
    so some speed stat stats still team than that the their them then there these they this those three
    through to today top trend trends two up us use versus vs was we were what when where which who whose
    why will with would year years you your five four six seven eight nine ten hall fame value valuation
    score decision trade waiver wire lineup roster standings tracker assistant simulator simulation room
    live saved library pricing upgrade sleepers busts predictions explorer historical totals leaderboards
    tool lab mlb al nl ops obp slg ba hr rbi sb hits runs walks doubles triples homers home steals
    shortstop shortstops catcher catchers outfield outfielders first second third base designated hitter
    dh ss of c ml why's what's who's how's tell find get between versus
    """.split()
)


@dataclass(frozen=True)
class Mention:
    text: str
    resolution: Resolution


def find_player_mentions(
    ds: BaseballDataset,
    text: str,
    *,
    prefer_ids: Iterable[str] = (),
    extra_stopwords: Iterable[str] = (),
) -> list[Mention]:
    """Player names in free text, in order. Full names match in any case; a lone surname
    only when capitalized and not an ordinary word."""
    stop = BASE_STOPWORDS | {normalize_player_name_for_merge(w) for w in extra_stopwords}
    full_names = set(ds.players["norm_full"])
    surnames = set(ds.players["norm_last"])
    tokens = [(m.group(0), _POSSESSIVE.sub("", m.group(0))) for m in _TOKEN.finditer(str(text or ""))]
    found: list[Mention] = []
    seen: set[str] = set()
    i = 0
    while i < len(tokens):
        matched = False
        for n in (3, 2):
            chunk = tokens[i:i + n]
            if len(chunk) < n:
                continue
            # A possessive ends the name: "Judge's Soto" is not one name.
            if any(raw != clean for raw, clean in chunk[:-1]):
                continue
            phrase = " ".join(clean for _, clean in chunk)
            norm = normalize_player_name_for_merge(phrase)
            if norm in full_names and not all(normalize_player_name_for_merge(c) in stop for _, c in chunk):
                res = resolve_player(ds, phrase, prefer_ids=prefer_ids)
                key = res.player.player_id if res.player else norm
                if key not in seen:
                    seen.add(key)
                    found.append(Mention(phrase, res))
                i += n
                matched = True
                break
        if matched:
            continue
        raw, clean = tokens[i]
        norm = normalize_player_name_for_merge(clean)
        if clean[:1].isupper() and norm and norm not in stop and norm in surnames:
            res = resolve_player(ds, clean, prefer_ids=prefer_ids)
            key = res.player.player_id if res.player else norm
            if key not in seen:
                seen.add(key)
                found.append(Mention(clean, res))
        i += 1
    return found
