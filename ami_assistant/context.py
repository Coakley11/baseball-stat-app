"""The small, safe slice of page state AMI may see.

Only the session keys listed in ``PAGE_KEYS`` are read — AMI never iterates session state,
so auth tokens, billing ids, workspace blobs and other users' data can't leak in. Values are
coerced to short plain strings/numbers and screened by ``safety.looks_secret``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ami_assistant.safety import clean_text
from nav_groups import NAV_LABELS

MAX_PLAYERS = 4
_EMOJI = re.compile(r"^[^\w(]+\s*")


def display_label(page_key: str) -> str:
    """The page name the user sees (U1 labels), emoji stripped."""
    return _EMOJI.sub("", NAV_LABELS.get(page_key, page_key)).strip() or page_key


PAGE_REF = re.compile(r"\[\[([^\]]+)\]\]")


def render_page_names(text: str) -> str:
    """Help prose names pages as ``[[<page key>]]``; the user reads the current label, so a page
    rename never needs a prose edit (``display_label`` is the only place labels come from)."""
    return PAGE_REF.sub(lambda m: display_label(m.group(1)), str(text or ""))


# page → {field: session key(s), first present wins}
PAGE_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "Historical Explorer": {
        "year_range": ("historical_year_range_filter",),
        "metric": ("historical_sort_stat_filter",),
        "positions": ("historical_position_filter",),
    },
    "Career Totals": {
        "year_range": ("career_year_range_filter",),
        "metric": ("career_sort_stat_filter",),
        "positions": ("career_position_filter",),
        "position_mode": ("career_position_filter_mode",),
    },
    "Leaderboards": {
        "year_range": ("leaders_year_range_filter",),
        "metric": ("leaders_sort_stat_filter",),
        "top_n": ("leaders_top_n_filter",),
    },
    "Comparison Tool": {
        "players": ("compare_players",),
        "year_range": ("compare_year_range",),
        "metric": ("compare_stat",),
    },
    "Trend Value": {
        "players": ("single_trend_dashboard_player", "trend_players_multi"),
        "window": ("trend_lag",),
        "min_games": ("trend_min_g",),
        "metric": ("trend_sort_col",),
        "positions": ("trend_position_filter",),
    },
    "Valuation": {
        "players": ("valuation_selected_player",),
        "window": ("value_lag",),
        "min_games": ("value_min_g",),
        "positions": ("value_position_filter",),
        "weight_current": ("value_w_current",),
        "weight_trend": ("value_w_trend",),
    },
}
DRAFT_PAGES = ("Draft Assistant Simulator", "Live Draft Room", "Draft Room Simulator", "Draft Lab / Simulation")
# Pages whose context line names the active league (read through fantasy_league_peek; never writes).
LEAGUE_PAGES = ("Home", "Fantasy Standings Tracker", "Fantasy Lineup Assistant", "Waiver Wire / Add-Drop Center",
                "Saved Draft Library")
DRAFT_SNAPSHOT_KEY = "_ami_draft_snapshot"


@dataclass(frozen=True)
class AmiPageContext:
    page: str = ""
    players: tuple[str, ...] = ()
    year_range: tuple[int, int] | None = None
    metric: str = ""
    positions: tuple[str, ...] = ()
    position_mode: str = ""
    window: int | None = None
    min_games: int | None = None
    top_n: int | None = None
    weight_current: float | None = None
    weight_trend: float | None = None
    draft: dict[str, Any] = field(default_factory=dict)
    # League pages only: {league_name, my_team, access_mode, week_label, week_status}. Small by design.
    league: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v not in (None, "", (), [], {})}

    def summary(self) -> str:
        """One line for the panel's context indicator."""
        bits = [display_label(self.page) if self.page else "No page"]
        if self.players:
            bits.append(", ".join(self.players[:3]))
        elif self.page == "Comparison Tool":
            return bits[0] + " · no players selected"  # its range/stat are just chart defaults
        if self.year_range:
            lo, hi = self.year_range
            bits.append(str(lo) if lo == hi else f"{lo}–{hi}")
        elif self.window:
            bits.append(f"last {self.window} seasons")
        if self.metric:
            bits.append(self.metric)
        if self.positions and len(self.positions) < 6:  # page defaults select every position
            bits.append("/".join(self.positions[:3]))
        if self.league:
            lg = self.league
            team = lg.get("my_team") or "no team claimed"
            if lg.get("access_mode") == "commissioner_proxy":
                team += " (commissioner view, unclaimed)"
            bits.append(f"{lg.get('league_name') or 'League'} · {team}")
            if lg.get("week_label"):
                bits.append(f"{lg['week_label']} {lg.get('week_status', '')}".strip())
        if self.draft:
            pick = self.draft.get("current_pick")
            bits.append(f"draft pick {pick}" if pick else "draft in progress")
        return " · ".join(bits)


def _player_label(raw: Any) -> str:
    # Page widgets store "Name", or "Name (1990-2008)" when two players share a name
    # (build_clean_player_label_map); players.resolve_label uses the span.
    return clean_text(raw, 60)


def _first(session: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        val = session.get(key)
        if val not in (None, "", [], ()):
            return val
    return None


def _int(val: Any) -> int | None:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _range(val: Any) -> tuple[int, int] | None:
    if isinstance(val, (list, tuple)) and len(val) == 2:
        lo, hi = _int(val[0]), _int(val[1])
        if lo is not None and hi is not None and 1800 < lo <= hi < 2200:
            return (lo, hi)
    return None


def _strings(val: Any, limit: int) -> tuple[str, ...]:
    items = val if isinstance(val, (list, tuple)) else [val]
    out = [clean_text(x, 40) for x in items if isinstance(x, (str, int, float))]
    return tuple(x for x in out if x)[:limit]


def _draft_summary(session: Mapping[str, Any]) -> dict[str, Any]:
    snap = session.get(DRAFT_SNAPSHOT_KEY)
    if not isinstance(snap, dict):
        return {}
    out: dict[str, Any] = {"available": True}
    for key in ("current_pick", "draft_round", "my_next_pick"):
        n = _int(snap.get(key))
        if n is not None:
            out[key] = n
    page = clean_text(snap.get("page"), 40)
    if page:
        out["source_page"] = page
    return out


def _league_summary(session: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from ami_assistant.tools.fantasy import league_brief

        brief = league_brief(session)
    except Exception:
        return {}
    if not brief:
        return {}
    week = brief.get("current_week") or {}
    out = {
        "league_name": clean_text(brief.get("league_name"), 60),
        "my_team": clean_text(brief.get("my_team"), 60),
        "access_mode": clean_text((brief.get("access") or {}).get("mode"), 30),
        "week_label": clean_text(week.get("label"), 30),
        "week_status": clean_text(week.get("status"), 20),
    }
    return {k: v for k, v in out.items() if v}


def build_ami_context(session: Mapping[str, Any] | None, active_page: str) -> AmiPageContext:
    session = session if session is not None else {}
    page = clean_text(active_page, 60)
    if page.startswith("__"):
        page = ""  # entitlement / paywall placeholders
    keys = PAGE_KEYS.get(page, {})
    fields: dict[str, Any] = {"page": page}
    raw_players = _first(session, keys.get("players", ()))
    if raw_players is not None:
        items = raw_players if isinstance(raw_players, (list, tuple)) else [raw_players]
        names = [_player_label(x) for x in items if isinstance(x, str)]
        fields["players"] = tuple(dict.fromkeys(n for n in names if n))[:MAX_PLAYERS]
    if "year_range" in keys:
        fields["year_range"] = _range(_first(session, keys["year_range"]))
    if "metric" in keys:
        metric = _first(session, keys["metric"])
        fields["metric"] = clean_text(metric, 20).replace(" Δ", "") if isinstance(metric, str) else ""
    if "positions" in keys:
        fields["positions"] = _strings(_first(session, keys["positions"]) or (), 8)
    if "position_mode" in keys:
        mode = _first(session, keys["position_mode"])
        fields["position_mode"] = clean_text(mode, 40) if isinstance(mode, str) else ""
    for name, conv in (("window", _int), ("min_games", _int), ("top_n", _int),
                       ("weight_current", _float), ("weight_trend", _float)):
        if name in keys:
            fields[name] = conv(_first(session, keys[name]))
    if page in LEAGUE_PAGES:
        fields["league"] = _league_summary(session)
    if page in DRAFT_PAGES:
        fields["draft"] = _draft_summary(session)
    return AmiPageContext(**fields)
