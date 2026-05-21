"""Contextual cross-page filter transfer (used by streamlit_app.py)."""

from __future__ import annotations

_TRANSFER_STAT_COLS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]

# Stable widget keys (with legacy fallbacks for one migration cycle).
_HIST_YEAR_KEYS = ("historical_year_range_filter", "hist_year")
_CAREER_YEAR_KEYS = ("career_year_range_filter", "career_year")
_LEADERS_YEAR_KEYS = ("leaders_year_range_filter", "leaders_year")
_HIST_BATS_KEYS = ("historical_batting_hand_filter", "hist_bats")
_CAREER_BATS_KEYS = ("career_batting_hand_filter", "career_bats")
_HIST_POS_KEYS = ("historical_position_filter", "hist_pos")
_CAREER_POS_KEYS = ("career_position_filter", "career_pos")
_HIST_MODE_KEYS = ("historical_position_filter_mode", "hist_position_filter_mode")
_CAREER_MODE_KEYS = ("career_position_filter_mode", "career_position_filter_mode")
_HIST_TEAM_KEYS = ("historical_team_filter", "hist_team")
_CAREER_TEAM_KEYS = ("career_team_filter", "career_team")
_DRAFT_LAB_FORMAT_KEYS = ("draft_lab_scoring_type", "draft_lab_format")
_LIVE_TEAM_COUNT_KEYS = ("live_draft_team_count", "live_draft_num_teams")


def year_tuple(val):
    if isinstance(val, (tuple, list)) and len(val) == 2:
        try:
            return (int(val[0]), int(val[1]))
        except (TypeError, ValueError):
            pass
    return None


def _session_year(session, *key_candidates):
    for key in key_candidates:
        yr = year_tuple(session.get(key))
        if yr:
            return yr
    return None


def _session_list(session, *key_candidates):
    for key in key_candidates:
        val = session.get(key)
        if val:
            return list(val)
    return None


def copy_prefix_stat_mins(session, from_prefix: str, to_prefix: str, keys_out: dict):
    for col in _TRANSFER_STAT_COLS:
        fk = f"{from_prefix}_{col}_min"
        if fk in session:
            keys_out[f"{to_prefix}_{col}_min"] = session[fk]


def shared_hist_career_keys(session, from_prefix: str, to_prefix: str) -> dict:
    keys = {}
    if from_prefix == "hist":
        yr = _session_year(session, *_HIST_YEAR_KEYS)
        if yr:
            keys[_CAREER_YEAR_KEYS[0] if to_prefix == "career" else _HIST_YEAR_KEYS[0]] = yr
        src_bats, src_pos, src_mode, src_team = _HIST_BATS_KEYS, _HIST_POS_KEYS, _HIST_MODE_KEYS, _HIST_TEAM_KEYS
    else:
        yr = _session_year(session, *_CAREER_YEAR_KEYS)
        if yr:
            keys[_HIST_YEAR_KEYS[0] if to_prefix == "hist" else _CAREER_YEAR_KEYS[0]] = yr
        src_bats, src_pos, src_mode, src_team = _CAREER_BATS_KEYS, _CAREER_POS_KEYS, _CAREER_MODE_KEYS, _CAREER_TEAM_KEYS
    dst_bats = _CAREER_BATS_KEYS[0] if to_prefix == "career" else _HIST_BATS_KEYS[0]
    dst_pos = _CAREER_POS_KEYS[0] if to_prefix == "career" else _HIST_POS_KEYS[0]
    dst_mode = _CAREER_MODE_KEYS[0] if to_prefix == "career" else _HIST_MODE_KEYS[0]
    dst_team = _CAREER_TEAM_KEYS[0] if to_prefix == "career" else _HIST_TEAM_KEYS[0]
    bats = _session_list(session, *src_bats)
    if bats:
        keys[dst_bats] = bats
    pos = _session_list(session, *src_pos)
    if pos:
        keys[dst_pos] = pos
    for mode_key in src_mode:
        if session.get(mode_key):
            keys[dst_mode] = session[mode_key]
            break
    team = _session_list(session, *src_team)
    if team:
        keys[dst_team] = team
    copy_prefix_stat_mins(session, from_prefix, to_prefix, keys)
    return keys


def leaders_year_keys(session, to_prefix: str) -> dict:
    keys = {}
    yr = _session_year(session, *_LEADERS_YEAR_KEYS)
    if not yr:
        return keys
    if to_prefix == "hist":
        keys[_HIST_YEAR_KEYS[0]] = yr
        copy_prefix_stat_mins(session, "leaders", "hist", keys)
    elif to_prefix == "career":
        keys[_CAREER_YEAR_KEYS[0]] = yr
        copy_prefix_stat_mins(session, "leaders", "career", keys)
    return keys


def build_transfer(session, builder_id: str, extra_context=None) -> dict:
    extra = extra_context or {}
    b = TRANSFER_BUILDERS.get(builder_id)
    if not b:
        return {}
    return b(session, extra)


TRANSFER_BUILDERS = {}


def _register_builder(builder_id):
    def decorator(fn):
        TRANSFER_BUILDERS[builder_id] = fn
        return fn
    return decorator


@_register_builder("hist_to_career")
def _hist_to_career(session, extra):
    return {"session_keys": shared_hist_career_keys(session, "hist", "career")}


@_register_builder("career_to_hist")
def _career_to_hist(session, extra):
    keys = shared_hist_career_keys(session, "career", "hist")
    return {"session_keys": keys}


@_register_builder("hist_to_leaders")
def _hist_to_leaders(session, extra):
    keys = {}
    yr = _session_year(session, *_HIST_YEAR_KEYS)
    if yr:
        keys[_LEADERS_YEAR_KEYS[0]] = yr
    copy_prefix_stat_mins(session, "hist", "leaders", keys)
    return {"session_keys": keys}


@_register_builder("career_to_leaders")
def _career_to_leaders(session, extra):
    keys = {}
    yr = _session_year(session, *_CAREER_YEAR_KEYS)
    if yr:
        keys[_LEADERS_YEAR_KEYS[0]] = yr
    copy_prefix_stat_mins(session, "career", "leaders", keys)
    return {"session_keys": keys}


@_register_builder("hist_to_compare")
def _hist_to_compare(session, extra):
    keys = {}
    yr = _session_year(session, *_HIST_YEAR_KEYS)
    if yr:
        keys["compare_year_range"] = yr
    names = extra.get("player_names") or []
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("career_to_compare")
def _career_to_compare(session, extra):
    keys = {}
    yr = _session_year(session, *_CAREER_YEAR_KEYS)
    if yr:
        keys["compare_year_range"] = yr
    names = extra.get("player_names") or []
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("hist_to_trend")
def _hist_to_trend(session, extra):
    keys = {}
    yr = _session_year(session, *_HIST_YEAR_KEYS)
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["trend_lag"] = yr[1] - yr[0] + 1
    copy_prefix_stat_mins(session, "hist", "trend", keys)
    names = extra.get("player_names") or []
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("hist_to_valuation")
def _hist_to_valuation(session, extra):
    keys = {}
    yr = _session_year(session, *_HIST_YEAR_KEYS)
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["value_lag"] = yr[1] - yr[0] + 1
    copy_prefix_stat_mins(session, "hist", "value", keys)
    return {"session_keys": keys}


@_register_builder("compare_to_trend")
def _compare_to_trend(session, extra):
    keys = {}
    yr = year_tuple(session.get("compare_year_range"))
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["trend_lag"] = yr[1] - yr[0] + 1
    stat = session.get("compare_stat")
    trend_sort_map = {
        "HR": "HR Δ", "RBI": "RBI Δ", "R": "R Δ", "SB": "SB Δ",
        "OPS": "OPS Δ", "BA": "BA Δ", "OBP": "OBP Δ", "SLG": "SLG Δ",
    }
    if stat in trend_sort_map:
        keys["trend_sort_col"] = trend_sort_map[stat]
    names = []
    for k in ("compare_players", "compare_players_saved"):
        raw = session.get(k)
        if isinstance(raw, list):
            names.extend(raw)
    if names:
        return {"session_keys": keys, "player_labels": names[:3]}
    return {"session_keys": keys}


@_register_builder("compare_to_valuation")
def _compare_to_valuation(session, extra):
    keys = {}
    yr = year_tuple(session.get("compare_year_range"))
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["value_lag"] = yr[1] - yr[0] + 1
    return {"session_keys": keys}


@_register_builder("trend_to_compare")
def _trend_to_compare(session, extra):
    keys = {}
    lag = session.get("trend_lag")
    if lag in (3, 4, 5):
        keys["_transfer_trend_lag"] = int(lag)
    names = extra.get("player_names") or []
    labels = extra.get("player_labels") or []
    if labels:
        return {"session_keys": keys, "player_labels": labels[:3]}
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("valuation_to_compare")
def _valuation_to_compare(session, extra):
    keys = {}
    lag = session.get("value_lag")
    if lag in (3, 4, 5):
        keys["_transfer_value_lag"] = int(lag)
    names = extra.get("player_names") or []
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("leaders_to_hist")
def _leaders_to_hist(session, extra):
    return {"session_keys": leaders_year_keys(session, "hist")}


@_register_builder("leaders_to_career")
def _leaders_to_career(session, extra):
    return {"session_keys": leaders_year_keys(session, "career")}


@_register_builder("leaders_to_compare")
def _leaders_to_compare(session, extra):
    keys = {}
    yr = _session_year(session, *_LEADERS_YEAR_KEYS)
    if yr:
        keys["compare_year_range"] = yr
    return {"session_keys": keys}


@_register_builder("leaders_to_trend")
def _leaders_to_trend(session, extra):
    keys = leaders_year_keys(session, "hist")
    yr = _session_year(session, *_LEADERS_YEAR_KEYS)
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["trend_lag"] = yr[1] - yr[0] + 1
    copy_prefix_stat_mins(session, "leaders", "trend", keys)
    return {"session_keys": keys}


@_register_builder("leaders_to_valuation")
def _leaders_to_valuation(session, extra):
    keys = {}
    yr = _session_year(session, *_LEADERS_YEAR_KEYS)
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["value_lag"] = yr[1] - yr[0] + 1
    copy_prefix_stat_mins(session, "leaders", "value", keys)
    return {"session_keys": keys}


@_register_builder("compare_to_hist")
def _compare_to_hist(session, extra):
    keys = {}
    yr = year_tuple(session.get("compare_year_range"))
    if yr:
        keys[_HIST_YEAR_KEYS[0]] = yr
    return {"session_keys": keys}


@_register_builder("compare_to_career")
def _compare_to_career(session, extra):
    keys = {}
    yr = year_tuple(session.get("compare_year_range"))
    if yr:
        keys[_CAREER_YEAR_KEYS[0]] = yr
    labels = []
    for k in ("compare_players", "compare_players_saved"):
        raw = session.get(k)
        if isinstance(raw, list):
            labels.extend(raw)
    payload = {"session_keys": keys}
    if labels:
        payload["player_labels"] = labels[:3]
    return payload


def _draft_lab_format(session):
    for key in _DRAFT_LAB_FORMAT_KEYS:
        val = session.get(key)
        if val:
            return str(val)
    return "5x5 Roto"


@_register_builder("lab_to_live_draft")
def _lab_to_live_draft(session, extra):
    fmt = _draft_lab_format(session)
    scoring = "Roto (5x5)" if "Roto" in fmt else "Points League"
    style = session.get("draft_lab_projection_style")
    window = session.get("draft_lab_window")
    keys = {
        _LIVE_TEAM_COUNT_KEYS[0]: 4,
        "live_draft_picks_per_team": int(session.get("draft_lab_picks_per_team", 15) or 15),
        "live_draft_scoring": scoring,
    }
    if style in ("Conservative", "Balanced", "Aggressive") or style is not None:
        keys["live_draft_proj_style"] = style
    if window in (3, 4, 5):
        keys["live_draft_proj_window"] = int(window)
    return {"session_keys": keys}


@_register_builder("live_to_draft_lab")
def _live_to_draft_lab(session, extra):
    return {"actions": ["push_live_draft_to_lab"]}


@_register_builder("draft_assistant_to_sleepers")
def _draft_assistant_to_sleepers(session, extra):
    keys = {}
    fmt = session.get("draft_format")
    if fmt in ("5x5 Roto", "Points League"):
        keys["fantasy_market_format"] = fmt
    window = session.get("draft_window")
    if window in (3, 4, 5):
        keys["fantasy_market_window"] = int(window)
    style = session.get("fantasy_draft_projection_style")
    if style is not None:
        keys["fantasy_draft_projection_style"] = style
    return {"session_keys": keys}


@_register_builder("sleepers_to_draft_assistant")
def _sleepers_to_draft_assistant(session, extra):
    keys = {}
    fmt = session.get("fantasy_market_format")
    if fmt in ("5x5 Roto", "Points League"):
        keys["draft_format"] = fmt
    window = session.get("fantasy_market_window")
    if window in (3, 4, 5):
        keys["draft_window"] = int(window)
    return {"session_keys": keys}


@_register_builder("standings_to_lineup")
def _standings_to_lineup(session, extra):
    keys = {}
    fmt = session.get("standings_scoring_format")
    if fmt:
        keys["lineup_format"] = fmt
    team = session.get("room_your_team")
    if team:
        keys["lineup_team"] = team
    return {"session_keys": keys}


@_register_builder("lineup_to_standings")
def _lineup_to_standings(session, extra):
    keys = {}
    fmt = session.get("lineup_format")
    if fmt in ("5x5 Roto", "Points League", "Head-to-Head Categories"):
        keys["standings_scoring_format"] = fmt if fmt != "Head-to-Head Categories" else "5x5 Roto"
    return {"session_keys": keys}


# Registry: (source_page, placement_key) -> list of {target, builder, label}
CONTEXTUAL_NAV_REGISTRY = {
    ("Historical Explorer", "after_table"): [
        {"target": "Career Totals", "builder": "hist_to_career", "label": "Career Totals — same team, years, hand, position"},
        {"target": "Leaderboards", "builder": "hist_to_leaders", "label": "Leaderboards — same year window"},
        {"target": "Comparison Tool", "builder": "hist_to_compare", "label": "Comparison Tool — same year range"},
        {"target": "Trend Value", "builder": "hist_to_trend", "label": "Trend Value — similar window & filters"},
        {"target": "Valuation", "builder": "hist_to_valuation", "label": "Valuation — similar window & filters"},
    ],
    ("Career Totals", "after_table"): [
        {"target": "Historical Explorer", "builder": "career_to_hist", "label": "Historical Explorer — same filters"},
        {"target": "Leaderboards", "builder": "career_to_leaders", "label": "Leaderboards — same year window"},
        {"target": "Comparison Tool", "builder": "career_to_compare", "label": "Comparison Tool — same year range"},
    ],
    ("Leaderboards", "after_table"): [
        {"target": "Historical Explorer", "builder": "leaders_to_hist", "label": "Historical Explorer"},
        {"target": "Career Totals", "builder": "leaders_to_career", "label": "Career Totals"},
        {"target": "Comparison Tool", "builder": "leaders_to_compare", "label": "Comparison Tool"},
        {"target": "Trend Value", "builder": "leaders_to_trend", "label": "Trend Value"},
        {"target": "Valuation", "builder": "leaders_to_valuation", "label": "Valuation"},
    ],
    ("Comparison Tool", "after_analysis"): [
        {"target": "Trend Value", "builder": "compare_to_trend", "label": "Trend Value"},
        {"target": "Valuation", "builder": "compare_to_valuation", "label": "Valuation"},
        {"target": "Historical Explorer", "builder": "compare_to_hist", "label": "Historical Explorer"},
        {"target": "Career Totals", "builder": "compare_to_career", "label": "Career Totals"},
    ],
    ("Trend Value", "after_table"): [
        {"target": "Comparison Tool", "builder": "trend_to_compare", "label": "Comparison Tool"},
        {"target": "Valuation", "builder": "hist_to_valuation", "label": "Valuation"},
    ],
    ("Valuation", "after_table"): [
        {"target": "Comparison Tool", "builder": "valuation_to_compare", "label": "Comparison Tool"},
        {"target": "Trend Value", "builder": "hist_to_trend", "label": "Trend Value"},
    ],
    ("Fantasy Sleepers & Busts", "after_tables"): [
        {"target": "Draft Assistant Simulator", "builder": "sleepers_to_draft_assistant", "label": "Draft Assistant"},
        {"target": "Draft Assistant Simulator", "builder": "draft_assistant_to_sleepers", "label": "Sync format from Draft Assistant"},
    ],
    ("Draft Assistant Simulator", "after_recommendations"): [
        {"target": "Fantasy Sleepers & Busts", "builder": "draft_assistant_to_sleepers", "label": "Sleepers & Busts"},
        {"target": "Draft Simulation Test Mode", "builder": "lab_to_live_draft", "label": "Draft Lab settings"},
    ],
    ("Draft Simulation Test Mode", "after_results"): [
        {"target": "Live Draft Room", "builder": "lab_to_live_draft", "label": "Live Draft Room — apply lab scoring"},
    ],
    ("Live Draft Room", "after_draft"): [
        {"target": "Draft Simulation Test Mode", "builder": "live_to_draft_lab", "label": "Analyze in Draft Lab"},
    ],
    ("Fantasy Standings Tracker", "after_standings"): [
        {"target": "Fantasy Lineup Assistant", "builder": "standings_to_lineup", "label": "Lineup Assistant"},
    ],
    ("Fantasy Lineup Assistant", "after_lineup"): [
        {"target": "Fantasy Standings Tracker", "builder": "lineup_to_standings", "label": "Standings Tracker"},
    ],
}
