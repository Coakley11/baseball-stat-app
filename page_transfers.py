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

# Live Draft Room roster slot widgets — must match streamlit_app.py st.number_input key= values.
_LIVE_SLOT_KEYS = [
    "live_slot_c",
    "live_slot_1b",
    "live_slot_2b",
    "live_slot_3b",
    "live_slot_ss",
    "live_slot_of",
    "live_slot_dh",
    "live_slot_p",
    "live_slot_bench",
]

__all__ = [
    "_TRANSFER_STAT_COLS",
    "_LIVE_SLOT_KEYS",
    "_LIVE_TEAM_COUNT_KEYS",
    "CONTEXTUAL_NAV_REGISTRY",
    "sanitize_session_keys",
    "build_transfer",
]

_FANTASY_FORMAT_VALUES = frozenset({"5x5 Roto", "Points League"})
_LIVE_SCORING_VALUES = frozenset({"Roto (5x5)", "Points League"})
_PROJECTION_STYLES = frozenset({"Conservative", "Balanced", "Aggressive"})
_TREND_SORT_COLS = frozenset({
    "R Δ", "H Δ", "2B Δ", "3B Δ", "HR Δ", "RBI Δ", "SB Δ", "BB Δ",
    "BA Δ", "OBP Δ", "SLG Δ", "OPS Δ",
})


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


def _safe_int(val, default=None):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _sanitize_value(key: str, value):
    """Coerce transfer payload values; return None to skip applying."""
    if value is None:
        return None
    if key.endswith("_year_range_filter") or key in ("hist_year", "career_year", "leaders_year", "compare_year_range"):
        yr = year_tuple(value)
        return yr
    if key.endswith("_filter") and key not in (
        "historical_position_filter_mode", "career_position_filter_mode",
        "historical_combine_split_seasons_filter", "career_by_team_toggle_filter",
    ):
        if isinstance(value, list):
            cleaned = [str(x) for x in value if str(x).strip()]
            return cleaned
        return None
    if key.endswith("_min") or key in (
        "trend_min_g", "value_min_g", "fantasy_market_min_g", "fantasy_market_min_ab",
        "leaders_top_n_filter", "draft_lab_picks_per_team", "live_draft_picks_per_team",
        "standings_api_season",
    ) or key.startswith("live_slot_"):
        if isinstance(value, bool):
            return value
        if key.startswith("live_slot_"):
            iv = _safe_int(value, None)
            return iv if iv is not None and iv >= 0 else None
        if key.endswith("_min") or key in ("fantasy_market_min_g", "fantasy_market_min_ab", "leaders_top_n_filter"):
            if key in ("fantasy_market_min_g", "fantasy_market_min_ab", "trend_min_g", "value_min_g", "leaders_top_n_filter",
                       "draft_lab_picks_per_team", "live_draft_picks_per_team", "standings_api_season"):
                iv = _safe_int(value, None)
                return iv if iv is not None else None
            fv = _safe_float(value, None)
            return fv if fv is not None else None
    if key in ("trend_lag", "value_lag", "draft_lab_window", "draft_window", "fantasy_market_window", "live_draft_proj_window"):
        iv = _safe_int(value, None)
        return iv if iv in (3, 4, 5) else None
    if key in _DRAFT_LAB_FORMAT_KEYS or key in ("draft_format", "fantasy_market_format", "standings_scoring_format"):
        s = str(value)
        return s if s in _FANTASY_FORMAT_VALUES else None
    if key == "live_draft_scoring":
        s = str(value)
        return s if s in _LIVE_SCORING_VALUES else None
    if key in ("live_draft_proj_style", "draft_lab_projection_style", "fantasy_draft_projection_style"):
        s = str(value)
        return s if s in _PROJECTION_STYLES else s
    if key in _LIVE_TEAM_COUNT_KEYS:
        iv = _safe_int(value, None)
        return iv if iv in (4, 8, 10, 12, 14) else None
    if key == "trend_sort_col":
        return value if value in _TREND_SORT_COLS else None
    if key in ("historical_sort_stat_filter", "historical_sort_order_filter", "career_sort_stat_filter",
               "leaders_sort_stat_filter", "compare_stat", "compare_x_axis_mode", "compare_trend_mode",
               "lineup_format", "lineup_diagnosis_rate_col", "lineup_team", "room_your_team",
               "live_draft_type", "live_draft_timer", "live_draft_auto_rule", "live_draft_league_name",
               "comparison_user_team", "trend_sync_team_for_draft", "value_sync_team_for_draft", "sleeper_sync_team"):
        return str(value) if str(value).strip() else None
    if key in ("historical_combine_split_seasons_filter", "career_by_team_toggle_filter",
               "trend_use_draft_room_sync", "value_use_draft_room_sync", "sleeper_use_draft_room_needs",
               "draft_use_ml_blend"):
        return bool(value)
    if key == "lineup_context_category_needs":
        if isinstance(value, (list, tuple)):
            return [str(x) for x in value if str(x).strip()]
        return None
    if key == "fantasy_market_age_range":
        return year_tuple(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def sanitize_session_keys(keys, allowed_keys):
    """
    Return only keys allowed for the target page transfer, with validated/coerced values.
    Prevents unsupported session_state keys from being transferred between pages.
    """
    if not isinstance(keys, dict):
        return {}
    allowed = frozenset(allowed_keys or ())
    if not allowed:
        return dict(keys)
    out = {}
    for key, value in keys.items():
        if key not in allowed or str(key).startswith("_transfer_"):
            continue
        cleaned = _sanitize_value(key, value)
        if cleaned is not None:
            out[key] = cleaned
    return out


def copy_prefix_stat_mins(session, from_prefix: str, to_prefix: str, keys_out: dict, cols=None):
    stat_cols = cols or _TRANSFER_STAT_COLS
    for col in stat_cols:
        fk = f"{from_prefix}_{col}_min"
        if fk not in session:
            continue
        val = session[fk]
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        if num == 0:
            keys_out[f"{to_prefix}_{col}_min"] = num
        elif num > 0:
            keys_out[f"{to_prefix}_{col}_min"] = num


def shared_hist_career_keys(session, from_prefix: str, to_prefix: str) -> dict:
    """Full Historical <-> Career transfer: year, hand, position, team, mode, stat minimums."""
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


def explorer_to_leaders_keys(session, from_prefix: str) -> dict:
    """Historical or Career -> Leaderboards: year range + compatible stat minimums."""
    keys = {}
    if from_prefix == "hist":
        yr = _session_year(session, *_HIST_YEAR_KEYS)
    else:
        yr = _session_year(session, *_CAREER_YEAR_KEYS)
    if yr:
        keys[_LEADERS_YEAR_KEYS[0]] = yr
    copy_prefix_stat_mins(session, from_prefix, "leaders", keys)
    return keys


def leaders_to_explorer_keys(session, to_prefix: str) -> dict:
    """Leaderboards -> Historical or Career: year range + stat minimums."""
    keys = {}
    yr = _session_year(session, *_LEADERS_YEAR_KEYS)
    if yr:
        if to_prefix == "hist":
            keys[_HIST_YEAR_KEYS[0]] = yr
        else:
            keys[_CAREER_YEAR_KEYS[0]] = yr
    copy_prefix_stat_mins(session, "leaders", to_prefix, keys)
    return keys


def leaders_year_keys(session, to_prefix: str) -> dict:
    return leaders_to_explorer_keys(session, to_prefix)


def _live_scoring_from_lab(fmt: str) -> str:
    return "Roto (5x5)" if "Roto" in str(fmt) else "Points League"


def _lab_format_from_live(scoring: str) -> str:
    return "5x5 Roto" if "Roto" in str(scoring) else "Points League"


def lab_to_live_keys(session) -> dict:
    """Draft Simulation Test Mode -> Live Draft Room."""
    keys = {}
    fmt = _draft_lab_format(session)
    keys["live_draft_scoring"] = _live_scoring_from_lab(fmt)
    picks = _safe_int(session.get("draft_lab_picks_per_team"), None)
    if picks is not None:
        keys["live_draft_picks_per_team"] = picks
    style = session.get("draft_lab_projection_style")
    if style:
        keys["live_draft_proj_style"] = style
    window = session.get("draft_lab_window")
    if window in (3, 4, 5):
        keys["live_draft_proj_window"] = int(window)
    for slot_key in _LIVE_SLOT_KEYS:
        if slot_key in session:
            keys[slot_key] = session[slot_key]
    return keys


def live_to_lab_keys(session) -> dict:
    """Live Draft Room -> Draft Simulation Test Mode settings."""
    keys = {}
    scoring = session.get("live_draft_scoring")
    if scoring:
        keys["draft_lab_scoring_type"] = _lab_format_from_live(scoring)
    picks = _safe_int(session.get("live_draft_picks_per_team"), None)
    if picks is not None:
        keys["draft_lab_picks_per_team"] = picks
    style = session.get("live_draft_proj_style")
    if style:
        keys["draft_lab_projection_style"] = style
    window = session.get("live_draft_proj_window")
    if window in (3, 4, 5):
        keys["draft_lab_window"] = int(window)
    return keys


def fantasy_format_window_keys(session, fmt_src, fmt_dst, window_src, window_dst, style_src=None, style_dst=None) -> dict:
    keys = {}
    fmt = session.get(fmt_src)
    if fmt in _FANTASY_FORMAT_VALUES:
        keys[fmt_dst] = fmt
    window = session.get(window_src)
    if window in (3, 4, 5):
        keys[window_dst] = int(window)
    if style_src and style_dst:
        style = session.get(style_src)
        if style:
            keys[style_dst] = style
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
    return {"session_keys": shared_hist_career_keys(session, "career", "hist")}


@_register_builder("hist_to_leaders")
def _hist_to_leaders(session, extra):
    return {"session_keys": explorer_to_leaders_keys(session, "hist")}


@_register_builder("career_to_leaders")
def _career_to_leaders(session, extra):
    return {"session_keys": explorer_to_leaders_keys(session, "career")}


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


@_register_builder("career_to_trend")
def _career_to_trend(session, extra):
    keys = {}
    yr = _session_year(session, *_CAREER_YEAR_KEYS)
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["trend_lag"] = yr[1] - yr[0] + 1
    copy_prefix_stat_mins(session, "career", "trend", keys)
    names = extra.get("player_names") or []
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("career_to_valuation")
def _career_to_valuation(session, extra):
    keys = {}
    yr = _session_year(session, *_CAREER_YEAR_KEYS)
    if yr and yr[1] - yr[0] + 1 in (3, 4, 5):
        keys["value_lag"] = yr[1] - yr[0] + 1
    copy_prefix_stat_mins(session, "career", "value", keys)
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
    labels = extra.get("player_labels") or []
    names = extra.get("player_names") or []
    if labels:
        return {"session_keys": keys, "player_labels": labels[:3]}
    if names:
        return {"session_keys": keys, "player_names": names[:3]}
    return {"session_keys": keys}


@_register_builder("trend_to_valuation")
def _trend_to_valuation(session, extra):
    keys = {}
    lag = session.get("trend_lag")
    if lag in (3, 4, 5):
        keys["value_lag"] = int(lag)
    copy_prefix_stat_mins(session, "trend", "value", keys)
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


@_register_builder("valuation_to_trend")
def _valuation_to_trend(session, extra):
    keys = {}
    lag = session.get("value_lag")
    if lag in (3, 4, 5):
        keys["trend_lag"] = int(lag)
    copy_prefix_stat_mins(session, "value", "trend", keys)
    return {"session_keys": keys}


@_register_builder("leaders_to_hist")
def _leaders_to_hist(session, extra):
    return {"session_keys": leaders_to_explorer_keys(session, "hist")}


@_register_builder("leaders_to_career")
def _leaders_to_career(session, extra):
    return {"session_keys": leaders_to_explorer_keys(session, "career")}


@_register_builder("leaders_to_compare")
def _leaders_to_compare(session, extra):
    keys = {}
    yr = _session_year(session, *_LEADERS_YEAR_KEYS)
    if yr:
        keys["compare_year_range"] = yr
    return {"session_keys": keys}


@_register_builder("leaders_to_trend")
def _leaders_to_trend(session, extra):
    keys = {}
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
    return {"session_keys": lab_to_live_keys(session)}


@_register_builder("live_to_draft_lab")
def _live_to_draft_lab(session, extra):
    return {"session_keys": live_to_lab_keys(session), "actions": ["push_live_draft_to_lab"]}


@_register_builder("live_to_draft_lab_settings")
def _live_to_draft_lab_settings(session, extra):
    return {"session_keys": live_to_lab_keys(session)}


@_register_builder("draft_assistant_to_sleepers")
def _draft_assistant_to_sleepers(session, extra):
    keys = fantasy_format_window_keys(
        session,
        "draft_format", "fantasy_market_format",
        "draft_window", "fantasy_market_window",
        "fantasy_draft_projection_style", "fantasy_draft_projection_style",
    )
    team = session.get("room_your_team")
    if team:
        keys["sleeper_sync_team"] = team
    return {"session_keys": keys}


@_register_builder("sleepers_to_draft_assistant")
def _sleepers_to_draft_assistant(session, extra):
    keys = fantasy_format_window_keys(
        session,
        "fantasy_market_format", "draft_format",
        "fantasy_market_window", "draft_window",
    )
    return {"session_keys": keys}


@_register_builder("draft_assistant_to_live")
def _draft_assistant_to_live(session, extra):
    keys = {}
    fmt = session.get("draft_format")
    if fmt in _FANTASY_FORMAT_VALUES:
        keys["live_draft_scoring"] = _live_scoring_from_lab(fmt)
    window = session.get("draft_window")
    if window in (3, 4, 5):
        keys["live_draft_proj_window"] = int(window)
    style = session.get("fantasy_draft_projection_style")
    if style:
        keys["live_draft_proj_style"] = style
    return {"session_keys": keys}


@_register_builder("standings_to_lineup")
def _standings_to_lineup(session, extra):
    keys = {}
    fmt = session.get("standings_scoring_format")
    if fmt in _FANTASY_FORMAT_VALUES:
        keys["lineup_format"] = fmt
    elif fmt == "Head-to-Head Categories":
        keys["lineup_format"] = "Head-to-Head Categories"
    team = extra.get("team") or session.get("room_your_team")
    if team:
        keys["lineup_team"] = str(team)
        keys["room_your_team"] = str(team)
    needs = extra.get("category_needs")
    if isinstance(needs, dict) and needs:
        keys["lineup_context_category_needs"] = [k for k, v in needs.items() if v]
    return {"session_keys": keys}


@_register_builder("lineup_to_standings")
def _lineup_to_standings(session, extra):
    keys = {}
    fmt = session.get("lineup_format")
    if fmt in ("5x5 Roto", "Points League"):
        keys["standings_scoring_format"] = fmt
    elif fmt == "Head-to-Head Categories":
        keys["standings_scoring_format"] = "5x5 Roto"
    team = session.get("lineup_team")
    if team:
        keys["room_your_team"] = str(team)
    return {"session_keys": keys}


# Registry: (source_page, placement_key) -> list of {target, builder, label}
CONTEXTUAL_NAV_REGISTRY = {
    ("Historical Explorer", "after_table"): [
        {"target": "Career Totals", "builder": "hist_to_career", "label": "Career Totals — team, years, hand, position, stat minimums"},
        {"target": "Leaderboards", "builder": "hist_to_leaders", "label": "Leaderboards — year window & stat minimums"},
        {"target": "Comparison Tool", "builder": "hist_to_compare", "label": "Comparison Tool — same year range"},
        {"target": "Trend Value", "builder": "hist_to_trend", "label": "Trend Value — window, hand, position, team, stat minimums"},
        {"target": "Valuation", "builder": "hist_to_valuation", "label": "Valuation — window & stat minimums"},
    ],
    ("Career Totals", "after_table"): [
        {"target": "Historical Explorer", "builder": "career_to_hist", "label": "Historical Explorer — same filters"},
        {"target": "Leaderboards", "builder": "career_to_leaders", "label": "Leaderboards — year window & stat minimums"},
        {"target": "Comparison Tool", "builder": "career_to_compare", "label": "Comparison Tool — same year range"},
        {"target": "Trend Value", "builder": "career_to_trend", "label": "Trend Value — connected filters"},
        {"target": "Valuation", "builder": "career_to_valuation", "label": "Valuation — connected filters"},
    ],
    ("Leaderboards", "after_table"): [
        {"target": "Historical Explorer", "builder": "leaders_to_hist", "label": "Historical Explorer — year & stat minimums"},
        {"target": "Career Totals", "builder": "leaders_to_career", "label": "Career Totals — year & stat minimums"},
        {"target": "Comparison Tool", "builder": "leaders_to_compare", "label": "Comparison Tool — same year range"},
        {"target": "Trend Value", "builder": "leaders_to_trend", "label": "Trend Value"},
        {"target": "Valuation", "builder": "leaders_to_valuation", "label": "Valuation"},
    ],
    ("Comparison Tool", "after_analysis"): [
        {"target": "Trend Value", "builder": "compare_to_trend", "label": "Trend Value — players & year window"},
        {"target": "Valuation", "builder": "compare_to_valuation", "label": "Valuation — year window"},
        {"target": "Historical Explorer", "builder": "compare_to_hist", "label": "Historical Explorer — year range"},
        {"target": "Career Totals", "builder": "compare_to_career", "label": "Career Totals — year range & players"},
    ],
    ("Trend Value", "after_table"): [
        {"target": "Comparison Tool", "builder": "trend_to_compare", "label": "Comparison Tool — players & window"},
        {"target": "Valuation", "builder": "trend_to_valuation", "label": "Valuation — window & stat minimums"},
    ],
    ("Valuation", "after_table"): [
        {"target": "Comparison Tool", "builder": "valuation_to_compare", "label": "Comparison Tool"},
        {"target": "Trend Value", "builder": "valuation_to_trend", "label": "Trend Value — window & stat minimums"},
    ],
    ("Fantasy Sleepers & Busts", "after_tables"): [
        {"target": "Draft Assistant Simulator", "builder": "sleepers_to_draft_assistant", "label": "Draft Assistant — scoring & window"},
        {"target": "Draft Assistant Simulator", "builder": "draft_assistant_to_sleepers", "label": "Sleepers — sync format from Draft Assistant"},
    ],
    ("Draft Assistant Simulator", "after_recommendations"): [
        {"target": "Fantasy Sleepers & Busts", "builder": "draft_assistant_to_sleepers", "label": "Sleepers & Busts — format & window"},
        {"target": "Live Draft Room", "builder": "draft_assistant_to_live", "label": "Live Draft Room — scoring & projection from assistant"},
    ],
    ("Draft Simulation Test Mode", "after_results"): [
        {"target": "Live Draft Room", "builder": "lab_to_live_draft", "label": "Live Draft Room — league size, scoring, roster slots, picks"},
    ],
    ("Live Draft Room", "after_draft"): [
        {"target": "Draft Simulation Test Mode", "builder": "live_to_draft_lab", "label": "Analyze completed draft in Draft Lab"},
        {"target": "Draft Simulation Test Mode", "builder": "live_to_draft_lab_settings", "label": "Draft Lab — copy live draft settings"},
    ],
    ("Fantasy Standings Tracker", "after_standings"): [
        {"target": "Fantasy Lineup Assistant", "builder": "standings_to_lineup", "label": "Lineup Assistant — team, scoring, category needs"},
    ],
    ("Fantasy Lineup Assistant", "after_lineup"): [
        {"target": "Fantasy Standings Tracker", "builder": "lineup_to_standings", "label": "Standings Tracker — scoring & team"},
    ],
}
