
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import altair as alt
from matplotlib.ticker import MaxNLocator
from pathlib import Path
import re
import unicodedata
import hashlib

import workflow_sidebar as wf_sb
from draft_strategy_intel import draft_strategy_line
from draft_team_fit import team_fit_summary_line
from projection_style import PROJECTION_STYLE_OPTIONS, get_draft_projection_factors

BASE_DIR = Path(__file__).resolve().parent

def read_required_csv(filename):
    path = BASE_DIR / filename
    if not path.exists():
        st.error(
            f"Missing required data file: {filename}. Upload {filename} to the same GitHub repository folder as this app file. "
            "Streamlit Cloud is case-sensitive, so the filename must match exactly."
        )
        st.stop()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as e:
        st.error(f"Could not read {filename}: {e}")
        st.stop()

try:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False


# ============================================================
# Daniel Cohen Baseball Explorer - Full Updated Version
# ============================================================

team_id_mapping = {
    "SFN": "SFG", "SLN": "STL", "CHN": "CHC", "NYA": "NYY", "NYN": "NYM",
    "FLO": "MIA", "LAN": "LAD", "BRO": "LAD", "SLA": "BAL",
    "WS1": "MIN", "WS2": "TEX", "NY1": "SFG", "ML4": "MIL", "ML1": "ATL",
    "TBA": "TBR", "SDN": "SDP", "CHA": "CWS", "KCA": "KCR",
    "SE1": "MIL", "MON": "WAS", "CAL": "LAA", "ANA": "LAA",
    "PHA": "OAK", "KC1": "OAK", "BSN": "ATL"
}

team_id_to_name = {
    "ARI": "Arizona Diamondbacks", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians", "COL": "Colorado Rockies", "CWS": "Chicago White Sox",
    "DET": "Detroit Tigers", "HOU": "Houston Astros", "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets",
    "NYY": "New York Yankees", "OAK": "Athletics", "ATH": "Athletics",
    "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates", "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners", "SFG": "San Francisco Giants", "STL": "St. Louis Cardinals",
    "TBR": "Tampa Bay Rays", "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays",
    "WAS": "Washington Nationals"
}

team_id_to_historical_name = {
    "ARI": "Arizona Diamondbacks", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CHN": "Chicago Cubs",
    "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians", "COL": "Colorado Rockies",
    "CWS": "Chicago White Sox", "CHA": "Chicago White Sox", "DET": "Detroit Tigers",
    "HOU": "Houston Astros", "KCR": "Kansas City Royals", "KCA": "Kansas City Royals",
    "LAA": "Los Angeles Angels", "CAL": "California Angels", "ANA": "Anaheim Angels",
    "LAD": "Los Angeles Dodgers", "LAN": "Los Angeles Dodgers", "BRO": "Brooklyn Dodgers",
    "MIA": "Miami Marlins", "FLO": "Florida Marlins", "MIL": "Milwaukee Brewers",
    "ML4": "Milwaukee Brewers", "SE1": "Seattle Pilots", "MIN": "Minnesota Twins",
    "WS1": "Washington Senators", "NYM": "New York Mets", "NYN": "New York Mets",
    "NYY": "New York Yankees", "NYA": "New York Yankees", "OAK": "Athletics",
    "PHA": "Philadelphia Athletics", "KC1": "Kansas City Athletics",
    "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates", "SDP": "San Diego Padres",
    "SDN": "San Diego Padres", "SEA": "Seattle Mariners", "SFG": "San Francisco Giants",
    "SFN": "San Francisco Giants", "NY1": "New York Giants", "STL": "St. Louis Cardinals",
    "SLN": "St. Louis Cardinals", "SLA": "St. Louis Browns", "TBR": "Tampa Bay Rays",
    "TBA": "Tampa Bay Rays", "TEX": "Texas Rangers", "WS2": "Washington Senators",
    "TOR": "Toronto Blue Jays", "WAS": "Washington Nationals", "MON": "Montreal Expos",
    "ML1": "Milwaukee Braves", "BSN": "Boston Braves"
}


# Lightweight team/league context features for ML and filters. Historical exceptions are handled by year:
# Houston was NL through 2012 and AL starting 2013; Milwaukee/Seattle was AL through 1997 and NL starting 1998.
AL_TEAMS = {"BAL", "BOS", "NYY", "TBR", "TOR", "CWS", "CLE", "DET", "KCR", "MIN", "HOU", "LAA", "OAK", "SEA", "TEX"}
NL_TEAMS = {"ATL", "MIA", "NYM", "PHI", "WAS", "CHC", "CIN", "MIL", "PIT", "STL", "ARI", "COL", "LAD", "SDP", "SFG"}
TEAM_PARK_FACTOR = {
    "COL": 1.15, "BOS": 1.06, "CIN": 1.05, "NYY": 1.04, "PHI": 1.04, "BAL": 1.03,
    "HOU": 1.02, "TEX": 1.02, "ATL": 1.01, "CHC": 1.01, "LAD": 1.00, "NYM": 1.00,
    "TOR": 1.00, "STL": 0.99, "MIL": 0.99, "ARI": 0.99, "SDP": 0.98, "SFG": 0.97,
    "SEA": 0.97, "DET": 0.97, "MIA": 0.96, "OAK": 0.95, "PIT": 0.98, "CLE": 0.99,
    "KCR": 0.99, "MIN": 0.99, "CWS": 1.00, "TBR": 1.00, "WAS": 1.00, "LAA": 1.00
}

def normalize_team_id(team_id):
    return team_id_mapping.get(str(team_id), str(team_id))

def safe_int_year(year):
    try:
        if pd.isna(year):
            return None
        return int(year)
    except Exception:
        return None

def team_league(team_id, year=None):
    """Return AL/NL using historical league membership when a season year is available."""
    tid = normalize_team_id(team_id)
    yr = safe_int_year(year)
    if tid == "HOU" and yr is not None:
        return "NL" if yr <= 2012 else "AL"
    if tid == "MIL" and yr is not None:
        return "AL" if yr <= 1997 else "NL"
    if tid in AL_TEAMS:
        return "AL"
    if tid in NL_TEAMS:
        return "NL"
    return "Unknown"

def historical_team_name(team_id_original, year=None):
    """Display the real historical team name for the season while preserving franchise filtering.

    Cleveland is one franchise for filtering, but it should display as Indians through 2021
    and Guardians starting in 2022. Other historical franchise names use Lahman team IDs
    where available, such as BRO, FLO, MON, SLA, etc.
    """
    original = str(team_id_original)
    tid = normalize_team_id(original)
    yr = safe_int_year(year)
    if tid == "CLE" and yr is not None:
        return "Cleveland Indians" if yr <= 2021 else "Cleveland Guardians"
    return team_id_to_historical_name.get(original, team_id_to_historical_name.get(tid, original))

def current_franchise_name(team_id_or_name):
    """Return the current MLB franchise name for draft/fantasy pages.

    Draft pages are forward-looking, so historical names like Tampa Bay Devil Rays,
    Florida Marlins, Montreal Expos, Cleveland Indians, etc. should display as
    current franchise names.
    """
    if pd.isna(team_id_or_name):
        return "Unknown"
    val = str(team_id_or_name).strip()
    if val == "":
        return "Unknown"

    name_aliases = {
        "Tampa Bay Rays": "Tampa Bay Rays",
        "TBA": "Tampa Bay Rays",
        "TBR": "Tampa Bay Rays",
        "Cleveland Indians": "Cleveland Guardians",
        "CLE": "Cleveland Guardians",
        "Florida Marlins": "Miami Marlins",
        "FLO": "Miami Marlins",
        "MIA": "Miami Marlins",
        "Montreal Expos": "Washington Nationals",
        "MON": "Washington Nationals",
        "WAS": "Washington Nationals",
        "Brooklyn Dodgers": "Los Angeles Dodgers",
        "BRO": "Los Angeles Dodgers",
        "LAN": "Los Angeles Dodgers",
        "LAD": "Los Angeles Dodgers",
        "St. Louis Browns": "Baltimore Orioles",
        "SLA": "Baltimore Orioles",
        "BAL": "Baltimore Orioles",
        "California Angels": "Los Angeles Angels",
        "Anaheim Angels": "Los Angeles Angels",
        "CAL": "Los Angeles Angels",
        "ANA": "Los Angeles Angels",
        "LAA": "Los Angeles Angels",
        "Oakland Athletics": "Athletics",
        "Philadelphia Athletics": "Athletics",
        "Kansas City Athletics": "Athletics",
        "OAK": "Athletics",
        "ATH": "Athletics",
        "PHA": "Athletics",
        "KC1": "Athletics",
        "Washington Senators": "Texas Rangers",
        "WS2": "Texas Rangers",
        "TEX": "Texas Rangers",
        "Seattle Pilots": "Milwaukee Brewers",
        "SE1": "Milwaukee Brewers",
        "ML4": "Milwaukee Brewers",
        "MIL": "Milwaukee Brewers",
        "New York Giants": "San Francisco Giants",
        "NY1": "San Francisco Giants",
        "SFN": "San Francisco Giants",
        "SFG": "San Francisco Giants",
        "Boston Braves": "Atlanta Braves",
        "Milwaukee Braves": "Atlanta Braves",
        "BSN": "Atlanta Braves",
        "ML1": "Atlanta Braves",
        "ATL": "Atlanta Braves",
    }
    if val in name_aliases:
        return name_aliases[val]

    normalized = normalize_team_id(val)
    return team_id_to_name.get(normalized, name_aliases.get(normalized, val))


COUNT_STATS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "G"]
RATE_STATS = ["BA", "OBP", "SLG", "OPS"]
TREND_COUNT_COLS = ["R Δ", "H Δ", "2B Δ", "3B Δ", "HR Δ", "RBI Δ", "SB Δ", "BB Δ"]

POSITION_ORDER = ["C", "1B", "2B", "3B", "SS", "OF", "DH", "P"]

def sort_positions_custom(pos_list):
    """Sort baseball positions in consistent fantasy order."""
    cleaned = [str(p).upper() for p in pos_list if pd.notna(p)]
    unique_positions = list(dict.fromkeys(cleaned))
    return sorted(
        unique_positions,
        key=lambda x: POSITION_ORDER.index(x) if x in POSITION_ORDER else 999
    )


TREND_RATE_COLS = ["BA Δ", "OBP Δ", "SLG Δ", "OPS Δ"]
ML_TARGET_STATS = ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]
ML_BASE_FEATURE_STATS = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "BA", "OBP", "SLG", "OPS"]
ML_DERIVED_FEATURE_STATS = ["PA_est", "BB_rate", "K_rate", "SB_rate", "XBH", "XBH_rate", "HR_rate", "Speed_Index"]

st.set_page_config(page_title="⚾ Daniel Cohen Baseball Explorer ⚾", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; padding-left: 2rem; padding-right: 2rem;}
.title-box {background: linear-gradient(90deg, #0b1f3a, #1f4e79); padding: 22px; border-radius: 16px; margin-bottom: 20px; box-shadow: 0 4px 14px rgba(0,0,0,0.18);}
.title-text {color: white; font-size: 36px; font-weight: 800; margin: 0;}
.subtitle-text {color: #dbe8f5; font-size: 16px; margin-top: 6px;}
.section-card {background-color: #f7f9fc; padding: 16px; border-radius: 12px; border: 1px solid #d9e2ec; margin-bottom: 16px;}
.section-title {font-size: 24px; font-weight: 800; color: #12324a; margin-bottom: 6px;}
.small-note {color: #4f6475; font-size: 14px;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="title-box">
    <div class="title-text">⚾ Daniel Cohen Baseball Explorer</div>
    <div class="subtitle-text">
        A full baseball and fantasy analytics platform: historical explorer, career totals, leaderboards, comparison tools,
        significance testing, scatterplots, trend analysis, ML projections, FantasyPros/ADP market sleepers and bust risks,
        Draft Assistant recommendations, Draft Room Simulator, roster construction views, live Fantasy Standings Tracker,
        current-season MLB API stat scoring, and Trade Analyzer tools for evaluating and proposing fantasy trades.
    </div>
</div>
""", unsafe_allow_html=True)

def fmt_int(x):
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x): return ""
    return f"{x:.0f}"

def fmt_count_1(x):
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x): return ""
    return f"{x:.1f}"

def fmt_rate_3(x):
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x): return ""
    return f"{x:.3f}"

def fmt_rate_4(x):
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x): return ""
    return f"{x:.4f}"



def normalize_series(series):
    """Scale a numeric pandas Series to 0-1 safely.

    Used by the fantasy and draft assistant pages so different stats
    can be combined into one score without crashing on missing values,
    all-equal values, or non-numeric data.
    """
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if s.notna().sum() == 0:
        return pd.Series(0.0, index=series.index)
    s = s.fillna(s.median())
    min_val = s.min()
    max_val = s.max()
    if pd.isna(min_val) or pd.isna(max_val) or max_val == min_val:
        return pd.Series(0.0, index=series.index)
    return (s - min_val) / (max_val - min_val)


def safe_round_rate_stats(df):
    df = df.copy()
    for col in ["BA", "OBP", "SLG", "OPS", "BA_roll", "OBP_roll", "SLG_roll", "OPS_roll"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(3)
    return df



def build_clean_player_label_map(df):
    """Build clean player dropdown labels without Lahman/playerID text.

    If names are duplicated, append a short career span rather than the internal ID.
    """
    base = (
        df[["playerID", "fullName", "yearID"]]
        .dropna(subset=["playerID", "fullName"])
        .copy()
    )
    base["yearID"] = pd.to_numeric(base["yearID"], errors="coerce")
    spans = base.groupby(["playerID", "fullName"], as_index=False)["yearID"].agg(["min", "max"]).reset_index()
    name_counts = spans["fullName"].value_counts().to_dict()

    label_map = {}
    for _, row in spans.sort_values(["fullName", "min", "max"]).iterrows():
        name = str(row["fullName"])
        if name_counts.get(name, 0) > 1:
            label = f"{name} ({int(row['min'])}-{int(row['max'])})"
        else:
            label = name
        label_map[label] = row["playerID"]
    return label_map


def get_player_career_span(df, player_id):
    player_years = pd.to_numeric(df.loc[df["playerID"] == player_id, "yearID"], errors="coerce").dropna()
    if player_years.empty:
        all_years = pd.to_numeric(df["yearID"], errors="coerce").dropna()
        return int(all_years.min()), int(all_years.max())
    return int(player_years.min()), int(player_years.max())




def build_pid_to_clean_label_map(df):
    label_map = build_clean_player_label_map(df)
    return {pid: label for label, pid in label_map.items()}


def resolve_fullname_to_clean_label(full_name, label_map):
    """Map a table/full name string to the app's canonical dropdown label (handles duplicate names with career spans)."""
    fn = " ".join(str(full_name).strip().split())
    if not fn:
        return None
    if fn in label_map:
        return fn
    base = " ".join(fullname_base_from_label(fn).split())
    if base in label_map:
        return base
    candidates = sorted([lbl for lbl in label_map.keys() if lbl.startswith(fn + " (")])
    if candidates:
        return candidates[0]
    candidates = sorted([lbl for lbl in label_map.keys() if lbl.startswith(base + " (")])
    if candidates:
        return candidates[0]
    base_matches = [lbl for lbl in label_map.keys() if fullname_base_from_label(lbl) == base]
    if len(base_matches) == 1:
        return base_matches[0]
    if len(base_matches) > 1:
        return sorted(base_matches)[0]
    fl = fn.lower()
    bl = base.lower()
    ci = [lbl for lbl in label_map.keys() if str(lbl).lower() == fl or fullname_base_from_label(lbl).lower() == bl]
    if len(ci) == 1:
        return ci[0]
    return None


def fullname_base_from_label(label):
    return str(label).split(" (")[0].strip()


def get_next_open_draft_pick_team():
    """Team whose row has the next empty Player slot in Draft Room table pick order."""
    table = st.session_state.get("draft_room_table", pd.DataFrame())
    if table.empty or "Player" not in table.columns or "Team" not in table.columns:
        return None
    t = table.copy()
    open_mask = t["Player"].fillna("").astype(str).str.strip().eq("")
    if not open_mask.any():
        return None
    if "Pick" in t.columns:
        t = t.sort_values("Pick", kind="stable")
    for _, row in t.iterrows():
        if str(row.get("Player", "")).strip() == "":
            return str(row.get("Team", "")).strip()
    return None


def is_users_draft_turn(team_name):
    """True when Draft Room's next open pick belongs to team_name."""
    if team_name is None or str(team_name).strip() == "":
        return False
    nxt = get_next_open_draft_pick_team()
    if nxt is None:
        return False
    return str(nxt).strip() == str(team_name).strip()


def register_players_sent_to_trend_page(full_name, label_map):
    """Route Send to Trend Page.

    First sent player anchors the single-player dashboard.
    Last three sent players populate the multi-player trend visualization.
    """
    lbl = resolve_fullname_to_clean_label(full_name, label_map)
    if not lbl:
        return False

    base_fn = fullname_base_from_label(lbl)

    if not st.session_state.get("trend_anchor_fullname"):
        st.session_state["trend_anchor_fullname"] = base_fn

    mq = st.session_state.get("trend_multi_queue_fullnames", [])
    if not isinstance(mq, list):
        mq = []
    if base_fn in mq:
        mq.remove(base_fn)
    mq.append(base_fn)
    while len(mq) > 3:
        mq.pop(0)

    st.session_state["trend_multi_queue_fullnames"] = mq

    anchor = st.session_state.get("trend_anchor_fullname") or base_fn
    anchor_label = resolve_fullname_to_clean_label(anchor, label_map)
    if anchor_label:
        st.session_state["trend_force_single_label"] = anchor_label

    multi_labels = []
    for name in mq:
        ml = resolve_fullname_to_clean_label(name, label_map)
        if ml and ml not in multi_labels:
            multi_labels.append(ml)

    st.session_state["trend_force_multi_labels"] = multi_labels[:3]
    # Also store readable names for pages that use base-name matching.
    st.session_state["pending_trend_players"] = [fullname_base_from_label(x) for x in multi_labels[:3]]
    st.session_state["pending_trend_player"] = fullname_base_from_label(anchor_label) if anchor_label else base_fn
    return True


def append_compare_player_ordered(full_name, label_map):
    """Queue one player for the Comparison Tool using Player A / Player B slots.

    Rules:
    - If Player A is empty, the sent player becomes Player A.
    - If Player A is already set, the sent player becomes Player B (replacing any prior B).
    - ``pending_compare_players`` is kept in sync so the top multiselect matches A/B.
    """
    lbl = resolve_fullname_to_clean_label(full_name, label_map)
    if not lbl:
        return False

    a = st.session_state.get("sig_player_a_clean")
    b = st.session_state.get("sig_player_b_clean")
    a = a if isinstance(a, str) and a in label_map else None
    b = b if isinstance(b, str) and b in label_map else None

    old_compare = [x for x in (st.session_state.get("compare_players") or []) if isinstance(x, str) and x in label_map]
    # When navigating from other pages, sig A/B session may be unset while compare_players still holds the last UI selection.
    if a is None and old_compare:
        a = old_compare[0]
    if b is None and len(old_compare) > 1:
        b = old_compare[1]

    if not a:
        st.session_state["pending_sig_player_a"] = lbl
        st.session_state["pending_compare_clear_player_b"] = True
        st.session_state.pop("pending_sig_player_b", None)
        tail = [x for x in old_compare if x != lbl]
        st.session_state["pending_compare_players"] = ([lbl] + tail)[:3]
        return True

    if a == lbl:
        tail = [x for x in old_compare if x != lbl]
        st.session_state["pending_compare_players"] = ([lbl] + tail)[:3]
        return True

    if not b or b == lbl:
        st.session_state["pending_sig_player_b"] = lbl
        merged = [a, lbl]
        for x in old_compare:
            if x not in merged and len(merged) < 3:
                merged.append(x)
        st.session_state["pending_compare_players"] = merged[:3]
        return True

    # Both slots occupied by different players: new send replaces Player B.
    st.session_state["pending_sig_player_a"] = a
    st.session_state["pending_sig_player_b"] = lbl
    merged = [a, lbl]
    for x in old_compare:
        if x not in merged and len(merged) < 3:
            merged.append(x)
    st.session_state["pending_compare_players"] = merged[:3]
    return True


def build_player_label_map(df):
    options = df[["playerID", "fullName"]].drop_duplicates().sort_values(["fullName", "playerID"])
    return {f"{row.fullName} ({row.playerID})": row.playerID for row in options.itertuples()}



def plot_player_stat_trends(ax, df, player_ids, stat_col, mode="Actual Values", smooth_window=3):
    """Plot one stat for multiple players using actual values or a moving-average smooth."""
    for pid in player_ids:
        subset = df[df["playerID"] == pid].sort_values("yearID").copy()
        if subset.empty or stat_col not in subset.columns:
            continue

        player_name = subset["fullName"].iloc[0] if "fullName" in subset.columns else str(pid)
        y = pd.to_numeric(subset[stat_col], errors="coerce")

        if mode == "Smoothed Moving Average":
            y_plot = y.rolling(window=int(smooth_window), min_periods=1).mean()
            label = f"{player_name} — smoothed"
        else:
            y_plot = y
            label = player_name

        ax.plot(subset["yearID"], y_plot, marker="o", label=label)




def _trend_numeric_series(df, stat_col):
    if df is None or df.empty or stat_col not in df.columns:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    d = df.sort_values("yearID").copy()
    x = pd.to_numeric(d["yearID"], errors="coerce")
    y = pd.to_numeric(d[stat_col], errors="coerce")
    mask = x.notna() & y.notna()
    return x[mask], y[mask]


def _trend_slope_r2(x, y):
    if len(x) < 2 or len(y) < 2:
        return np.nan, np.nan
    try:
        coef = np.polyfit(x.astype(float), y.astype(float), 1)
        pred = coef[0] * x.astype(float) + coef[1]
        ss_res = float(((y.astype(float) - pred) ** 2).sum())
        ss_tot = float(((y.astype(float) - y.astype(float).mean()) ** 2).sum())
        r2 = np.nan if ss_tot == 0 else 1 - ss_res / ss_tot
        return float(coef[0]), float(r2)
    except Exception:
        return np.nan, np.nan


def classify_player_trend_from_series(x, y, stat_col):
    """Classify a player trend using slope, recent slope, volatility, and direction."""
    if len(y) < 3:
        return {
            "Trend Direction": "Not enough data",
            "Slope": np.nan,
            "Recent Slope": np.nan,
            "Volatility": np.nan,
            "Consistency Rating": "Unknown",
            "R²": np.nan,
            "Fantasy Signal": "Not enough recent seasons to classify."
        }

    slope, r2 = _trend_slope_r2(x, y)
    recent_x = x.tail(min(3, len(x)))
    recent_y = y.tail(min(3, len(y)))
    recent_slope, _ = _trend_slope_r2(recent_x, recent_y)

    volatility = float(y.std()) if len(y) > 1 else np.nan
    mean_abs = float(abs(y.mean())) if pd.notna(y.mean()) else np.nan
    cv = volatility / mean_abs if mean_abs and mean_abs != 0 else np.nan

    if pd.isna(cv):
        consistency = "Unknown"
    elif cv < 0.12:
        consistency = "Very consistent"
    elif cv < 0.25:
        consistency = "Moderately consistent"
    elif cv < 0.45:
        consistency = "Volatile"
    else:
        consistency = "Very volatile"

    # Stat-aware thresholds: rate stats need smaller slope cutoffs than counting stats.
    rate_stats = {"BA", "AVG", "OBP", "SLG", "OPS", "BB%", "K%", "Strikeout Rate", "Walk Rate"}
    if str(stat_col).upper() in {s.upper() for s in rate_stats}:
        strong = 0.015
        mild = 0.005
    else:
        strong = 4.0
        mild = 1.0

    if pd.isna(slope):
        direction = "Not enough data"
    elif slope >= strong:
        direction = "Accelerating upward" if pd.notna(recent_slope) and recent_slope > slope * 1.20 else "Improving"
    elif slope >= mild:
        direction = "Slightly improving"
    elif slope <= -strong:
        direction = "Accelerating downward" if pd.notna(recent_slope) and recent_slope < slope * 1.20 else "Declining"
    elif slope <= -mild:
        direction = "Slightly declining"
    else:
        direction = "Stable"

    fantasy_signal = "Stable profile."
    if direction in ["Improving", "Accelerating upward"] and consistency in ["Very consistent", "Moderately consistent"]:
        fantasy_signal = "Positive fantasy momentum with relatively reliable year-to-year growth."
    elif direction in ["Improving", "Accelerating upward"] and consistency in ["Volatile", "Very volatile"]:
        fantasy_signal = "Upside signal, but volatility means the breakout may carry risk."
    elif direction in ["Declining", "Accelerating downward"]:
        fantasy_signal = "Possible decline or bust-risk signal."
    elif consistency in ["Very consistent", "Moderately consistent"]:
        fantasy_signal = "Consistency may be useful even without a major breakout trend."
    elif consistency in ["Volatile", "Very volatile"]:
        fantasy_signal = "High volatility; treat recent spikes carefully."

    return {
        "Trend Direction": direction,
        "Slope": slope,
        "Recent Slope": recent_slope,
        "Volatility": volatility,
        "Consistency Rating": consistency,
        "R²": r2,
        "Fantasy Signal": fantasy_signal
    }


def build_advanced_trend_intelligence(df, player_ids, stat_col):
    rows = []
    for pid in player_ids:
        sub = df[df["playerID"] == pid].sort_values("yearID").copy()
        if sub.empty:
            continue
        player = sub["fullName"].iloc[0] if "fullName" in sub.columns else str(pid)
        x, y = _trend_numeric_series(sub, stat_col)
        info = classify_player_trend_from_series(x, y, stat_col)
        last_val = y.iloc[-1] if len(y) else np.nan
        first_val = y.iloc[0] if len(y) else np.nan
        info.update({
            "Player": player,
            "Stat": stat_col,
            "First Value": first_val,
            "Latest Value": last_val,
            "Net Change": last_val - first_val if pd.notna(last_val) and pd.notna(first_val) else np.nan,
            "Years Used": (float(x.iloc[-1]) - float(x.iloc[0])) if len(x) >= 2 else 0
        })
        rows.append(info)
    out = pd.DataFrame(rows)
    if not out.empty and "Slope" in out.columns:
        out = out.sort_values("Slope", ascending=False)
    return out


def make_advanced_trend_commentary(intel_df, stat_col):
    if intel_df is None or intel_df.empty:
        return "Not enough data to generate trend intelligence."

    lines = []
    best = intel_df.sort_values("Slope", ascending=False).iloc[0]
    worst = intel_df.sort_values("Slope", ascending=True).iloc[0]

    if pd.notna(best.get("Slope")):
        lines.append(
            f"{best['Player']} shows the strongest {stat_col} growth trend in this comparison "
            f"(slope {best['Slope']:.3f} per season, {best.get('Trend Direction', 'trend unclear').lower()})."
        )

    if len(intel_df) > 1 and pd.notna(worst.get("Slope")) and worst["Player"] != best["Player"]:
        lines.append(
            f"{worst['Player']} has the weakest {stat_col} trend here "
            f"(slope {worst['Slope']:.3f} per season, {worst.get('Trend Direction', 'trend unclear').lower()})."
        )

    volatile = intel_df[intel_df["Consistency Rating"].astype(str).str.contains("volatile", case=False, na=False)]
    if not volatile.empty:
        v = volatile.iloc[0]
        lines.append(
            f"{v['Player']} has a higher volatility profile, so recent spikes should be treated more cautiously."
        )

    consistent = intel_df[intel_df["Consistency Rating"].astype(str).str.contains("consistent", case=False, na=False)]
    if not consistent.empty:
        c = consistent.iloc[0]
        lines.append(
            f"{c['Player']} grades as {str(c['Consistency Rating']).lower()}, which is useful for fantasy managers who prefer stable production."
        )

    if not lines:
        lines.append("The selected players have similar or unclear trend patterns.")

    return " ".join(lines)


def format_advanced_trend_table(df):
    out = df.copy()
    for c in ["Slope", "Recent Slope", "Volatility", "R²", "First Value", "Latest Value", "Net Change"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").round(4)
    if "Years Used" in out.columns:
        out["Years Used"] = pd.to_numeric(out["Years Used"], errors="coerce").round(0).astype("Int64")
    out = out.rename(columns={"Trend Direction": "Trend", "R²": "R-squared"})
    ordered_cols = [
        "Player",
        "Stat",
        "Slope",
        "Trend",
        "Recent Slope",
        "Volatility",
        "Consistency Rating",
        "R-squared",
        "Fantasy Signal",
        "First Value",
        "Latest Value",
        "Net Change",
        "Years Used",
    ]
    return out[[c for c in ordered_cols if c in out.columns]]


def compute_trend_slope(group, stat_col):
    group = group.sort_values("yearID")
    x = pd.to_numeric(group["yearID"], errors="coerce").values
    y = pd.to_numeric(group[stat_col], errors="coerce").values
    mask = ~pd.isna(y)
    x = x[mask]
    y = y[mask]
    if len(x) < 2:
        return np.nan
    return np.polyfit(x, y, 1)[0]

def add_missing_numeric_columns(df, cols):
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df

def add_rate_stats(df):
    df = df.copy()
    needed_cols = ["AB", "H", "2B", "3B", "HR", "BB", "HBP", "SF"]
    df = add_missing_numeric_columns(df, needed_cols)
    df["1B"] = df["H"] - df["2B"] - df["3B"] - df["HR"]
    ab_denom = df["AB"].replace(0, np.nan)
    obp_denom = (df["AB"] + df["BB"] + df["HBP"] + df["SF"]).replace(0, np.nan)
    df["BA"] = pd.to_numeric(df["H"] / ab_denom, errors="coerce")
    df["OBP"] = pd.to_numeric((df["H"] + df["BB"] + df["HBP"]) / obp_denom, errors="coerce")
    df["SLG"] = pd.to_numeric((df["1B"] + 2 * df["2B"] + 3 * df["3B"] + 4 * df["HR"]) / ab_denom, errors="coerce")
    df["OPS"] = pd.to_numeric(df["OBP"] + df["SLG"], errors="coerce")
    return df

def apply_stat_min_filters(df, prefix):
    df = df.copy()
    stat_columns = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]
    for col in stat_columns:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce")

    with st.expander("Stat minimum filters", expanded=False):
        count_tab, rate_tab = st.tabs(["Counting stats", "Rate stats"])
        mins = {}
        with count_tab:
            cols = st.columns(4)
            count_filter_cols = [c for c in stat_columns if c not in RATE_STATS]
            for i, stat in enumerate(count_filter_cols):
                with cols[i % 4]:
                    mins[stat] = st.number_input(
                        f"Min {stat}",
                        min_value=0,
                        value=0,
                        step=1,
                        key=f"{prefix}_{stat}_min",
                    )
        with rate_tab:
            cols = st.columns(4)
            for i, stat in enumerate([c for c in stat_columns if c in RATE_STATS]):
                with cols[i % 4]:
                    mins[stat] = st.number_input(
                        f"Min {stat}",
                        min_value=0.0,
                        value=0.0,
                        step=0.001,
                        format="%.3f",
                        key=f"{prefix}_{stat}_min",
                    )

    mask = pd.Series(True, index=df.index)
    for stat, min_val in mins.items():
        if min_val:
            mask &= df[stat].fillna(-np.inf) >= min_val
    return df.loc[mask].copy()

def color_trend(val):
    try:
        if pd.isna(val):
            return ""
        num = pd.to_numeric(str(val).replace(",", ""), errors="coerce")
        if pd.isna(num):
            return ""

        # Stronger/darker colors for highly significant values.
        if num >= 1.96:
            return "color: darkgreen; font-weight: 900;"
        if num > 0:
            return "color: green; font-weight: bold;"

        if num <= -1.96:
            return "color: darkred; font-weight: 900;"
        if num < 0:
            return "color: red; font-weight: bold;"

        return "color: gray;"
    except Exception:
        return ""




def color_p_value(val):
    """Use darker colors for highly significant p-values."""
    try:
        if pd.isna(val):
            return ""

        num = pd.to_numeric(str(val).replace(",", ""), errors="coerce")
        if pd.isna(num):
            return ""

        # Extremely significant
        if num < 0.01:
            return "color: darkgreen; font-weight: 900;"

        # Statistically significant
        if num < 0.05:
            return "color: green; font-weight: bold;"

        # Weak/non-significant
        if num > 0.10:
            return "color: darkred; font-weight: bold;"

        return "color: #cc5500; font-weight: bold;"
    except Exception:
        return ""


def style_significance_row(row):
    """Synchronize Difference, Test Statistic, and p-value colors using p-value as the master signal."""
    styles = pd.Series("", index=row.index)
    try:
        p = pd.to_numeric(row.get("p-value", np.nan), errors="coerce")
        diff = pd.to_numeric(row.get("Difference", np.nan), errors="coerce")
    except Exception:
        return styles

    target_cols = [c for c in ["Difference", "Test Statistic", "p-value"] if c in row.index]
    if pd.isna(p) or pd.isna(diff):
        return styles

    if p < 0.01:
        color = "darkgreen" if diff > 0 else "darkred"
        weight = "900"
    elif p < 0.05:
        color = "green" if diff > 0 else "red"
        weight = "bold"
    else:
        # Not statistically significant at the selected alpha level.
        # Keep it neutral so it doesn't look like a real win/loss.
        color = "gray"
        weight = "normal"

    for c in target_cols:
        styles[c] = f"color: {color}; font-weight: {weight};"
    return styles

def color_positive_green(val):
    """Display positive/valuable scores in green."""
    try:
        if pd.isna(val):
            return ""
        num = pd.to_numeric(str(val).replace(",", ""), errors="coerce")
        if pd.isna(num):
            return ""
        if num > 0:
            return "color: green; font-weight: bold;"
        return "color: gray;"
    except Exception:
        return ""


def _extract_numeric_from_arrow(value):
    """Convert values like '▲ 4.2' or '▼ -0.0310' back to numeric for styling."""
    try:
        if pd.isna(value):
            return np.nan
        if isinstance(value, str):
            value = value.replace("▲", "").replace("▼", "").strip()
        return float(value)
    except Exception:
        return np.nan


def trend_heatmap_style(val):
    """Heat-map style for Trend Table: green = improving, red = declining."""
    v = _extract_numeric_from_arrow(val)
    if pd.isna(v):
        return ""
    if v >= 5:
        return "background-color:#006400; color:white; font-weight:bold;"
    if v > 0:
        return "background-color:#c6efce; color:#006100;"
    if v <= -5:
        return "background-color:#8b0000; color:white; font-weight:bold;"
    if v < 0:
        return "background-color:#ffc7ce; color:#9c0006;"
    return ""


def trend_heatmap_style_dynamic(val, col_name):
    """Use tighter thresholds for rate stats like BA/OBP/SLG/OPS."""
    v = _extract_numeric_from_arrow(val)
    if pd.isna(v):
        return ""
    rate_cols = {"BA Δ", "OBP Δ", "SLG Δ", "OPS Δ"}
    if col_name in rate_cols:
        strong = 0.030
    else:
        strong = 5.0
    if v >= strong:
        return "background-color:#006400; color:white; font-weight:bold;"
    if v > 0:
        return "background-color:#c6efce; color:#006100;"
    if v <= -strong:
        return "background-color:#8b0000; color:white; font-weight:bold;"
    if v < 0:
        return "background-color:#ffc7ce; color:#9c0006;"
    return ""


def format_trend_arrow_value(x, is_rate=False):
    """Format a trend value with an arrow and correct decimals."""
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x):
        return ""
    arrow = "▲" if x > 0 else ("▼" if x < 0 else "")
    if is_rate:
        return f"{arrow} {x:.4f}".strip()
    return f"{arrow} {x:.1f}".strip()


def format_fantasy_table(df):
    """Fantasy/Draft display formatting. Ranks and Fantasy Edge are integers; score/rate fields are clean."""
    df = df.copy()
    rank_cols = ["Market Rank", "Model Rank", "Current Rank", "FantasyPros Rank", "ADP Rank", "Recommendation Rank", "Draft Fit Rank", "RK", "BEST", "WORST"]
    score_cols = [
        "Expected Fantasy Value", "Expected Fantasy Value",
        "Recommendation Score", "Draft Fit Score", "Sleeper Score", "Bust Risk Score",
        "Player Value Component", "Market Edge Component", "Roster Need Component",
        "Scarcity Component", "Category Fit Component", "Availability Urgency Component",
        "Risk Component", "ML Projection Score", "Blended Projection Score"
    ]
    edge_cols = ["Fantasy Edge"]
    rate_cols = ["BA", "OBP", "SLG", "OPS", "Projected BA", "Projected OBP", "Projected SLG", "Projected OPS"]
    count_cols = ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "Projected R", "Projected H", "Projected 2B", "Projected 3B", "Projected HR", "Projected RBI", "Projected SB", "Projected BB"]
    one_decimal_cols = ["ADP", "Expert Std Dev", "Age", "Availability Probability", "Position Need Bonus", "Category Need Bonus", "Risk Penalty"]
    for col in rank_cols + edge_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(0).astype("Int64")
    for col in score_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    for col in rate_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(4)
    for col in count_cols + one_decimal_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(1)
    return df

def classify_trend(row):
    ops_trend = pd.to_numeric(row.get("OPS_trend", np.nan), errors="coerce")
    hr_trend = pd.to_numeric(row.get("HR_trend", np.nan), errors="coerce")
    if pd.isna(ops_trend): return "insufficient"
    if ops_trend >= 0.03 or (pd.notna(hr_trend) and hr_trend >= 3): return "breakout"
    if ops_trend <= -0.03 or (pd.notna(hr_trend) and hr_trend <= -3): return "decline"
    return "stable"

def describe_valuation_index(index):
    index = pd.to_numeric(index, errors="coerce")
    if pd.isna(index): return "not enough data to classify the valuation score"
    if index >= 0.90: return "an elite valuation score"
    if index >= 0.75: return "a very strong valuation score"
    if index >= 0.50: return "a solid middle-tier valuation score"
    if index >= 0.25: return "a low valuation score"
    return "a very low valuation score"

def make_trend_insight_summary(row):
    player = row.get("fullName", "This player")
    ops_trend = pd.to_numeric(row.get("OPS_trend", np.nan), errors="coerce")
    hr_trend = pd.to_numeric(row.get("HR_trend", np.nan), errors="coerce")
    rbi_trend = pd.to_numeric(row.get("RBI_trend", np.nan), errors="coerce")
    sb_trend = pd.to_numeric(row.get("SB_trend", np.nan), errors="coerce")
    xbh_trend = pd.to_numeric(row.get("XBH_noHR_trend", np.nan), errors="coerce")
    proj_ops = pd.to_numeric(row.get("proj_OPS", np.nan), errors="coerce")
    proj_hr = pd.to_numeric(row.get("proj_HR", np.nan), errors="coerce")
    proj_rbi = pd.to_numeric(row.get("proj_RBI", np.nan), errors="coerce")
    proj_sb = pd.to_numeric(row.get("proj_SB", np.nan), errors="coerce")
    proj_xbh = pd.to_numeric(row.get("proj_XBH", np.nan), errors="coerce")
    trend_type = classify_trend(row)
    label = "a breakout candidate" if trend_type == "breakout" else ("a decline risk" if trend_type == "decline" else "a stable profile")
    return (
        f"{player} looks like {label}. "
        f"OPS trend is {fmt_rate_4(ops_trend)} per year, HR trend is {fmt_count_1(hr_trend)}, "
        f"2B+3B trend is {fmt_count_1(xbh_trend)}, RBI trend is {fmt_count_1(rbi_trend)}, "
        f"and SB trend is {fmt_count_1(sb_trend)}. "
        f"If the recent pattern continues, the next-season trend estimate is roughly "
        f"{fmt_rate_4(proj_ops)} OPS, {fmt_count_1(proj_hr)} HR, {fmt_count_1(proj_xbh)} doubles/triples, "
        f"{fmt_count_1(proj_rbi)} RBI, and {fmt_count_1(proj_sb)} SB."
    )

def make_valuation_summary(row):
    player = row.get("fullName", "This player")
    trend_score = pd.to_numeric(row.get("Trend_Score", np.nan), errors="coerce")
    perf_score = pd.to_numeric(row.get("Perf_Score", np.nan), errors="coerce")
    valuation_score = pd.to_numeric(row.get("Valuation_Score", np.nan), errors="coerce")
    proj_ops = pd.to_numeric(row.get("proj_OPS", np.nan), errors="coerce")
    proj_hr = pd.to_numeric(row.get("proj_HR", np.nan), errors="coerce")
    proj_xbh = pd.to_numeric(row.get("proj_XBH", np.nan), errors="coerce")
    proj_rbi = pd.to_numeric(row.get("proj_RBI", np.nan), errors="coerce")
    proj_sb = pd.to_numeric(row.get("proj_SB", np.nan), errors="coerce")
    valuation_description = describe_valuation_index(valuation_score)
    return (
        f"{player}'s Trend Score is {fmt_count_1(trend_score)}, Current Score is {fmt_count_1(perf_score)}, "
        f"and Valuation Score is {fmt_rate_4(valuation_score)}. "
        f"That is {valuation_description}. "
        f"The Valuation Score combines current score with recent trend direction, "
        f"then scales the result from 0 to 1 compared with the other players in the filtered group. "
        f"If the recent pattern continues, the next-season trend estimate is roughly "
        f"{fmt_rate_4(proj_ops)} OPS, {fmt_count_1(proj_hr)} HR, {fmt_count_1(proj_xbh)} doubles/triples, "
        f"{fmt_count_1(proj_rbi)} RBI, and {fmt_count_1(proj_sb)} SB."
    )

def render_section_header(title, note):
    st.markdown(f"""
        <div class="section-card">
            <div class="section-title">{title}</div>
            <div class="small-note">{note}</div>
        </div>
        """, unsafe_allow_html=True)

def top_bar_chart(df, name_col, value_col, title, top_n=10):
    if df.empty or value_col not in df.columns or name_col not in df.columns:
        return
    chart_df = df[[name_col, value_col]].copy()
    chart_df[value_col] = pd.to_numeric(chart_df[value_col], errors="coerce")
    chart_df = chart_df.dropna(subset=[value_col]).sort_values(value_col, ascending=False).head(top_n)
    if chart_df.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(chart_df[name_col], chart_df[value_col])
    ax.set_title(title)
    ax.set_xlabel(value_col)
    ax.invert_yaxis()
    try:
        st.pyplot(fig, clear_figure=True)
    except TypeError:
        st.pyplot(fig)
    plt.close(fig)

def format_display_table(df, count_cols=None, rate_cols=None, score_cols=None, count_decimals=0, rate_decimals=3):
    """Return a plain DataFrame for maximum Streamlit Cloud stability.
    Formatting is handled by rounding numeric columns instead of pandas Styler.

    count_decimals / rate_decimals let the Trend page keep change values readable:
    counting-stat changes use 1 decimal, while OPS/BA/OBP/SLG changes use 4 decimals.
    """
    df = df.copy()
    count_cols = count_cols or []
    rate_cols = rate_cols or []
    score_cols = score_cols or []
    for col in count_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(count_decimals)
    for col in rate_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(rate_decimals)
    for col in score_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(4 if col == "Valuation Score" else 1)
    return df





MAX_TABLE_DISPLAY_ROWS = 500

@st.cache_data(show_spinner=False)
def _df_to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")

def render_output_table(df, *, key, file_name, display_rows=MAX_TABLE_DISPLAY_ROWS, style_cols=None):
    """Render a table quickly and add a CSV export button that opens cleanly in Excel."""
    table_df = df.copy()
    if len(table_df) > display_rows:
        st.caption(f"Showing first {display_rows:,} rows. Export downloads all {len(table_df):,} rows.")
        display_df = table_df.head(display_rows)
    else:
        display_df = table_df

    style_cols = [c for c in (style_cols or []) if c in display_df.columns]
    # Avoid heavy styling on large tables. Styling was slowing Trend/Valuation pages and re-expanding decimals.
    if style_cols and display_df.size <= 6000:
        fmt = {}
        for col in display_df.columns:
            if col in TREND_RATE_COLS or col in ["OPS Δ", "BA Δ", "OBP Δ", "SLG Δ"]:
                fmt[col] = "{:.4f}"
            elif col in TREND_COUNT_COLS or col in ["HR Δ", "2B+3B Δ", "RBI Δ", "SB Δ", "R Δ", "H Δ", "2B Δ", "3B Δ", "BB Δ"]:
                fmt[col] = "{:.1f}"
            elif col in RATE_STATS or col in ["BA", "OBP", "SLG", "OPS"]:
                fmt[col] = "{:.3f}"
            elif col in ["Trend Score", "Current Score", "Performance Score", "Score"]:
                fmt[col] = "{:.1f}"
            elif col == "Valuation Score":
                fmt[col] = "{:.4f}"
            elif col == "Draft Fit Score":
                fmt[col] = "{:.4f}"
            elif col == "Fantasy Edge":
                fmt[col] = "{:.0f}"

        styled_df = display_df.style.format(fmt)

        red_green_cols = [c for c in style_cols if c in display_df.columns and c != "Draft Fit Score"]
        green_cols = [c for c in style_cols if c in display_df.columns and c == "Draft Fit Score"]

        if red_green_cols:
            styled_df = styled_df.map(color_trend, subset=red_green_cols)
        if green_cols:
            styled_df = styled_df.map(color_positive_green, subset=green_cols)

        # Synchronize Difference, Test Statistic, and p-value colors using p-value as the master signal.
        # This prevents cases where the p-value looks significant but the test statistic/difference use a weaker shade.
        if "p-value" in display_df.columns:
            try:
                styled_df = styled_df.apply(style_significance_row, axis=1)
            except Exception:
                styled_df = styled_df.map(color_p_value, subset=["p-value"])

        # Make long explanation/reason columns readable instead of truncated.
        try:
            st.dataframe(
                styled_df,
                width="stretch",
                hide_index=True,
                row_height=42,
                column_config={
                    "Reason": st.column_config.TextColumn(
                        "Reason",
                        width="large"
                    ),
                    "Interpretation": st.column_config.TextColumn(
                        "Interpretation",
                        width="large"
                    )
                }
            )
        except Exception:
            st.dataframe(styled_df, width="stretch", hide_index=True)
    else:
        st.dataframe(display_df, width="stretch", hide_index=True)

    st.download_button(
        "Export CSV for Excel",
        data=_df_to_csv_bytes(table_df),
        file_name=file_name,
        mime="text/csv",
        width="content",
    )


def _numeric_plot_columns(df):
    """Return useful numeric columns for chart axes.

    The chart can use internal fields such as Age/Games, but it intentionally
    hides backend IDs and raw birth-date fields from the dropdowns.
    """
    blocked = {"birthday", "birthmonth", "birthyear", "birth day", "birth month", "birth year"}
    preferred = [
        "Age", "G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB",
        "BA", "OBP", "SLG", "OPS", "Current Score", "Valuation Score", "Score",
        "Debut Age", "Final Age", "Average Age"
    ]
    cols = []
    for c in preferred:
        if c in df.columns and c not in cols:
            vals = pd.to_numeric(df[c], errors="coerce")
            if vals.notna().sum() > 0:
                cols.append(c)
    for c in df.columns:
        c_key = str(c).replace("_", " ").lower().strip()
        if c not in cols and c_key not in blocked:
            vals = pd.to_numeric(df[c], errors="coerce")
            if vals.notna().sum() > 0 and not str(c).lower().endswith("id"):
                cols.append(c)
    return cols

def _categorical_plot_columns(df):
    """Color-by options should stay consistent across Historical and Career scatterplots."""
    options = []
    for col in ["Primary Position", "Bats", "Team", "League"]:
        if col in df.columns:
            options.append(col)
    return options


# Current-franchise helpers for scatterplot labels and colors
CURRENT_MLB_TEAMS = set(team_id_to_name.values())
AL_TEAM_NAMES = {team_id_to_name[t] for t in AL_TEAMS if t in team_id_to_name}
NL_TEAM_NAMES = {team_id_to_name[t] for t in NL_TEAMS if t in team_id_to_name}
AL_TEAM_NAMES.add("Athletics")
AL_TEAM_NAMES.add("Oakland Athletics")

TEAM_NAME_ALIASES = {
    "OAK": "Athletics",
    "ATH": "Athletics",
    "Oakland Athletics": "Athletics",
    "Philadelphia Athletics": "Athletics",
    "Kansas City Athletics": "Athletics",
    "LAD": "Los Angeles Dodgers",
    "BRO": "Los Angeles Dodgers",
    "LAN": "Los Angeles Dodgers",
    "FLO": "Miami Marlins",
    "MIA": "Miami Marlins",
    "SLA": "Baltimore Orioles",
    "BAL": "Baltimore Orioles",
}

def normalize_current_team_name(value):
    """Return a current MLB franchise name when the value clearly maps to one; otherwise Unknown."""
    if pd.isna(value):
        return "Unknown"
    s = str(value).strip()
    if s == "":
        return "Unknown"
    if s in TEAM_NAME_ALIASES:
        return TEAM_NAME_ALIASES[s]
    if s in CURRENT_MLB_TEAMS:
        return s
    return "Unknown"

def get_scatter_team_color_group(row):
    """Modern 2025/2026 franchise used only for coloring scatterplot points."""
    candidates = [
        row.get("primaryTeamName", None),
        row.get("teamName", None),
        row.get("Team Color Group", None),
        row.get("Franchise", None),
    ]
    for val in candidates:
        team = normalize_current_team_name(val)
        if team != "Unknown":
            return team
    return "Unknown"

def get_scatter_team_display(row):
    """Historical team label shown in tooltips/tables, but only if tied to a current franchise."""
    franchise = get_scatter_team_color_group(row)
    if franchise == "Unknown":
        return "Unknown"
    for key in ["primaryHistoricalTeamName", "teamHistoricalName", "displayTeam", "Team"]:
        val = row.get(key, None)
        if pd.notna(val) and str(val).strip() != "":
            return str(val).strip()
    return franchise

def get_scatter_league_display(row):
    """League used for scatterplots: current franchise league when known; otherwise raw AL/NL if explicit; else Unknown."""
    franchise = get_scatter_team_color_group(row)
    if franchise in AL_TEAM_NAMES:
        return "American League"
    if franchise in NL_TEAM_NAMES:
        return "National League"

    raw = str(row.get("teamLeague", row.get("primaryLeague", row.get("League", "")))).strip()
    if raw in ["AL", "American League"]:
        return "American League"
    if raw in ["NL", "National League"]:
        return "National League"
    return "Unknown"


def _baseball_age_series(df):
    def _num_col(col, default=np.nan):
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
        return pd.Series(default, index=df.index)

    season = _num_col("yearID")
    birth_year = _num_col("birthYear")
    birth_month = _num_col("birthMonth", 7).fillna(7)
    birth_day = _num_col("birthDay", 1).fillna(1)
    age = season - birth_year
    age = age - ((birth_month > 7) | ((birth_month == 7) & (birth_day > 1))).astype(int)
    return age.where(season.notna() & birth_year.notna(), np.nan)


def _add_scatter_context_columns(plot_df):
    """Add team, league, and display labels without row-wise dataframe apply."""
    out = plot_df.copy()
    team_group = pd.Series("Unknown", index=out.index, dtype="object")
    for col in ["primaryTeamName", "teamName", "Team Color Group", "Franchise"]:
        if col in out.columns:
            normalized = out[col].map(normalize_current_team_name)
            team_group = team_group.mask(team_group.eq("Unknown") & normalized.ne("Unknown"), normalized)

    out["Team Color Group"] = team_group
    out["Team"] = team_group
    for col in ["primaryHistoricalTeamName", "teamHistoricalName", "displayTeam", "Team"]:
        if col in out.columns:
            vals = out[col].where(out[col].notna(), "").astype(str).str.strip()
            out["Team"] = out["Team"].mask(team_group.ne("Unknown") & vals.ne(""), vals)
    out.loc[team_group.eq("Unknown"), "Team"] = "Unknown"

    league = pd.Series("Unknown", index=out.index, dtype="object")
    league = league.mask(team_group.isin(AL_TEAM_NAMES), "American League")
    league = league.mask(team_group.isin(NL_TEAM_NAMES), "National League")
    raw_league = pd.Series("", index=out.index, dtype="object")
    for col in ["teamLeague", "primaryLeague", "League"]:
        if col in out.columns:
            vals = out[col].where(out[col].notna(), "").astype(str).str.strip()
            raw_league = raw_league.mask(raw_league.eq("") & vals.ne(""), vals)
    league = league.mask(league.eq("Unknown") & raw_league.isin(["AL", "American League"]), "American League")
    league = league.mask(league.eq("Unknown") & raw_league.isin(["NL", "National League"]), "National League")
    out["League"] = league
    return out


@st.cache_data(show_spinner=False)
def _prepare_historical_scatter_data(hist_df, team_col):
    """Build plot-ready data for Historical Explorer.

    The visible table stays clean, but the scatterplot can use internal fields such as
    season Age and G.
    """
    if hist_df is None or hist_df.empty:
        return pd.DataFrame()
    plot_df = hist_df.copy()
    plot_df["Player"] = plot_df.get("fullName", "")
    plot_df["Year"] = pd.to_numeric(plot_df.get("yearID"), errors="coerce")
    plot_df = _add_scatter_context_columns(plot_df)
    plot_df["Primary Position"] = plot_df.get("displayPosition", plot_df.get("primaryPos", plot_df.get("careerPrimaryPos", "")))
    plot_df["Bats"] = plot_df.get("bats", "")

    if {"yearID", "birthYear"}.issubset(plot_df.columns):
        plot_df["Age"] = _baseball_age_series(plot_df)
    # Keep games labeled as G only. Do not create a duplicate "Games" field.
    if "G" in plot_df.columns:
        plot_df["G"] = pd.to_numeric(plot_df["G"], errors="coerce")
    return plot_df

@st.cache_data(show_spinner=False)
def _prepare_career_scatter_data(career_df, filtered_source_df=None):
    """Build plot-ready data for Career Totals.

    Career age is less natural than season age, so this adds Debut Age, Final Age,
    and Average Age when birth/year fields are available in the filtered source.
    """
    if career_df is None or career_df.empty:
        return pd.DataFrame()
    plot_df = career_df.copy()
    plot_df["Player"] = plot_df.get("fullName", plot_df.get("Player", ""))
    plot_df = _add_scatter_context_columns(plot_df)
    plot_df["Primary Position"] = plot_df.get("displayPosition", plot_df.get("Primary Position", plot_df.get("careerPrimaryPos", plot_df.get("primaryPos", ""))))
    plot_df["Bats"] = plot_df.get("bats", plot_df.get("Bats", ""))
    # Keep games labeled as G only. Do not create a duplicate "Games" field.
    if "G" in plot_df.columns:
        plot_df["G"] = pd.to_numeric(plot_df["G"], errors="coerce")

    if filtered_source_df is not None and not filtered_source_df.empty and "playerID" in plot_df.columns:
        src = filtered_source_df.copy()
        if {"yearID", "birthYear"}.issubset(src.columns):
            src["Season Age"] = _baseball_age_series(src)
            weight_col = "AB" if "AB" in src.columns else ("G" if "G" in src.columns else None)
            if weight_col:
                src["_age_weight"] = pd.to_numeric(src[weight_col], errors="coerce").fillna(0)
                def wavg(g):
                    ages = pd.to_numeric(g["Season Age"], errors="coerce")
                    weights = pd.to_numeric(g["_age_weight"], errors="coerce").fillna(0)
                    mask = ages.notna() & (weights > 0)
                    if mask.sum() == 0:
                        return ages.mean()
                    return np.average(ages[mask], weights=weights[mask])
                age_summary = src.groupby("playerID").apply(
                    lambda g: pd.Series({
                        "Debut Age": pd.to_numeric(g["Season Age"], errors="coerce").min(),
                        "Final Age": pd.to_numeric(g["Season Age"], errors="coerce").max(),
                        "Average Age": wavg(g)
                    })
                ).reset_index()
            else:
                age_summary = src.groupby("playerID")["Season Age"].agg(
                    **{"Debut Age": "min", "Final Age": "max", "Average Age": "mean"}
                ).reset_index()
            plot_df = plot_df.merge(age_summary, on="playerID", how="left")
    return plot_df

def _year_axis_domain(series):
    """Zoom year axes around the dense part of the plotted data.

    This prevents a few very old/new rows from forcing a huge 1871-2025 range when
    nearly all visible dots are clustered in a narrower era.
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 10:
        return None
    full_min, full_max = float(s.min()), float(s.max())
    q_low, q_high = float(s.quantile(0.02)), float(s.quantile(0.98))
    if not np.isfinite(q_low) or not np.isfinite(q_high) or q_high <= q_low:
        return None
    full_span = full_max - full_min
    dense_span = q_high - q_low
    # Only zoom if the dense range is meaningfully tighter than the full range.
    if full_span > 20 and dense_span < 0.75 * full_span:
        pad = max(1, round(dense_span * 0.06))
        return [int(np.floor(q_low - pad)), int(np.ceil(q_high + pad))]
    return [int(np.floor(full_min)), int(np.ceil(full_max))]

def _smart_axis_domain(series, pad=0.08, q_low=0.05, q_high=0.95):
    """Fit scatterplot axes to the dense part of the currently plotted data.

    This keeps charts readable when one or two outliers would otherwise force a
    huge empty range. It uses percentile clipping plus a small padding.
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 3:
        return None
    low = float(s.quantile(q_low))
    high = float(s.quantile(q_high))
    if not np.isfinite(low) or not np.isfinite(high):
        return None
    if high <= low:
        val = float(s.median()) if len(s) else 0.0
        width = max(abs(val) * 0.05, 1.0)
        return [val - width, val + width]
    padding = (high - low) * pad
    return [low - padding, high + padding]


def _axis_config_for_column(col_name, series):
    """Return an Altair scale/axis pair tuned for the selected statistic."""
    name = str(col_name).lower().strip()
    domain = _smart_axis_domain(series)
    axis_kwargs = {"title": col_name}

    if name == "year":
        domain = _year_axis_domain(series) or domain
        axis_kwargs["format"] = "d"
    elif name == "debut age":
        axis_kwargs["values"] = [18, 20, 22, 24, 26, 28]
    elif name == "final age":
        axis_kwargs["values"] = [32, 34, 36, 38, 40, 42]
    elif name == "average age":
        axis_kwargs["values"] = [23, 26, 29, 32, 35, 38, 41]
    elif name in {"ba", "avg", "batting average", "obp", "slg", "ops"}:
        axis_kwargs["format"] = ".3f" if name != "ops" else ".3f"

    return alt.Scale(domain=domain, zero=False) if domain else alt.Scale(zero=False), alt.Axis(**axis_kwargs)




def _full_axis_config_for_column(col_name, series):
    """Return an Altair scale/axis pair that includes every non-null point.

    Used for Full Outlier View. It avoids passing format=None to Altair, and it
    pads the min/max slightly so outliers do not sit directly on the chart border.
    """
    name = str(col_name).lower().strip()
    s = pd.to_numeric(series, errors="coerce").dropna()

    if name == "year":
        axis = alt.Axis(title=col_name, format="d")
    else:
        axis = alt.Axis(title=col_name)

    if s.empty:
        return alt.Scale(zero=False), axis

    low = float(s.min())
    high = float(s.max())

    if not np.isfinite(low) or not np.isfinite(high):
        return alt.Scale(zero=False), axis

    if high == low:
        pad = max(abs(high) * 0.05, 1.0)
    else:
        pad = (high - low) * 0.06

    domain = [low - pad, high + pad]

    if name == "year":
        domain = [int(np.floor(low)), int(np.ceil(high))]

    return alt.Scale(domain=domain, zero=False, nice=True), axis

def _scatter_size_encoding(chart_df, size_col):
    """Scale dot size dynamically to the filtered data.

    Uses the 5th-95th percentile domain so one extreme outlier does not make all
    other dots look the same size.
    """
    if size_col == "None" or size_col not in chart_df.columns:
        return None
    vals = pd.to_numeric(chart_df[size_col], errors="coerce").dropna()
    if vals.empty:
        return None
    low = float(vals.quantile(0.05))
    high = float(vals.quantile(0.95))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low, high = float(vals.min()), float(vals.max())
    if high <= low:
        high = low + 1e-9
    return alt.Size(
        f"{size_col}:Q",
        title=size_col,
        scale=alt.Scale(domain=[low, high], range=[20, 300], clamp=True),
        legend=alt.Legend(title=size_col)
    )


def _scatter_color_encoding(chart_df, color_col):
    """Consistent color rules for league, handedness, team, and position scatterplots."""
    if color_col == "None" or color_col not in chart_df.columns:
        return None

    col_lower = color_col.lower()

    if "league" in col_lower:
        chart_df[color_col] = (
            chart_df[color_col]
            .replace({"AL": "American League", "NL": "National League", "Unknown League": "Unknown", "": "Unknown", None: "Unknown"})
            .fillna("Unknown")
        )
        return alt.Color(
            f"{color_col}:N",
            title=color_col,
            scale=alt.Scale(
                domain=["American League", "National League", "Unknown"],
                range=["#08519c", "#fb6a4a", "#bdbdbd"]
            ),
            legend=alt.Legend(title=color_col)
        )

    if color_col == "Bats":
        chart_df[color_col] = (
            chart_df[color_col]
            .replace({"": "Unknown", None: "Unknown"})
            .fillna("Unknown")
        )
        domain = ["L", "B", "R", "Unknown"]
        colors = ["#2ca25f", "#3182bd", "#de2d26", "#bdbdbd"]
        return alt.Color(
            f"{color_col}:N",
            title=color_col,
            scale=alt.Scale(domain=domain, range=colors),
            legend=alt.Legend(title=color_col)
        )

    if "position" in col_lower or color_col in ["POS", "Primary Position"]:
        chart_df[color_col] = (
            chart_df[color_col]
            .replace({"": "Unknown", None: "Unknown"})
            .fillna("Unknown")
        )
        return alt.Color(
            f"{color_col}:N",
            title=color_col,
            scale=alt.Scale(
                domain=["1B", "2B", "SS", "3B", "OF", "DH", "C", "P", "Unknown"],
                range=["#08306b", "#8c510a", "#238b45", "#ffd92f", "#e31a1c", "#756bb1", "#000000", "#bdbdbd", "#ffffff"]
            ),
            legend=alt.Legend(title=color_col)
        )

    if color_col == "Team":
        # Team color uses current 2025/2026 MLB franchise group, while tooltip can still show the historical team.
        TEAM_SCATTER_COLORS = {
            # American League — darker primary shades
            "Baltimore Orioles": "#df4601",
            "Boston Red Sox": "#8b1e2d",
            "New York Yankees": "#0c2340",
            "Tampa Bay Rays": "#092c5c",
            "Toronto Blue Jays": "#134a8e",
            "Chicago White Sox": "#000000",
            "Cleveland Guardians": "#8b0000",
            "Detroit Tigers": "#0c2340",
            "Kansas City Royals": "#004687",
            "Minnesota Twins": "#002b5c",
            "Houston Astros": "#002d62",
            "Los Angeles Angels": "#8b0000",
            "Athletics": "#003831",
            "Seattle Mariners": "#005c5c",
            "Texas Rangers": "#003278",

            # National League — lighter primary shades
            "Arizona Diamondbacks": "#c86b75",
            "Atlanta Braves": "#ce6b75",
            "Chicago Cubs": "#6baed6",
            "Cincinnati Reds": "#fb6a4a",
            "Colorado Rockies": "#b39ddb",
            "Los Angeles Dodgers": "#6baed6",
            "Miami Marlins": "#66c2a5",
            "Milwaukee Brewers": "#f2c94c",
            "New York Mets": "#74a9cf",
            "Philadelphia Phillies": "#fb6a4a",
            "Pittsburgh Pirates": "#f2c94c",
            "San Diego Padres": "#c2a477",
            "San Francisco Giants": "#fdae6b",
            "St. Louis Cardinals": "#fb6a4a",
            "Washington Nationals": "#fb6a4a",
            "Unknown": "#bdbdbd",
        }

        color_field = "Team Color Group" if "Team Color Group" in chart_df.columns else color_col
        chart_df[color_field] = chart_df[color_field].apply(normalize_current_team_name).fillna("Unknown")
        teams = [t for t in sorted(chart_df[color_field].dropna().astype(str).unique()) if t]
        colors = [TEAM_SCATTER_COLORS.get(t, "#bdbdbd") for t in teams]
        return alt.Color(
            f"{color_field}:N",
            title="Team",
            scale=alt.Scale(domain=teams, range=colors),
            legend=alt.Legend(title="Team")
        )

    return alt.Color(f"{color_col}:N", title=color_col, legend=alt.Legend(title=color_col))

def _safe_r2(y_true, y_pred):
    try:
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)
        mask = np.isfinite(y_true) & np.isfinite(y_pred)
        y_true, y_pred = y_true[mask], y_pred[mask]
        if len(y_true) < 3 or np.nanvar(y_true) == 0:
            return np.nan
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        return float(1 - ss_res / ss_tot) if ss_tot != 0 else np.nan
    except Exception:
        return np.nan


def _poly_equation(coeffs, x_col, y_col):
    coeffs = list(coeffs)
    degree = len(coeffs) - 1
    terms = []
    for i, c in enumerate(coeffs):
        power = degree - i
        sign = " + " if c >= 0 else " - "
        mag = _format_equation_number(abs(c))
        if power == 0:
            term = mag
        elif power == 1:
            term = f"{mag}×{x_col}"
        else:
            term = f"{mag}×{x_col}^{power}"
        if not terms:
            terms.append(term if c >= 0 else f"-{term}")
        else:
            terms.append(sign + term)
    return f"{y_col} = {''.join(terms)}"


def _fit_model_for_scatter(fit_df, x_col, y_col, model_type):
    x = pd.to_numeric(fit_df[x_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(fit_df[y_col], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 4 or len(np.unique(x)) < 2 or len(np.unique(y)) < 2:
        return None

    order = np.argsort(x)
    x_sorted, y_sorted = x[order], y[order]
    x_line = np.linspace(float(np.nanmin(x_sorted)), float(np.nanmax(x_sorted)), 200)

    try:
        if model_type == "Linear":
            coeffs = np.polyfit(x_sorted, y_sorted, 1)
            y_hat = np.polyval(coeffs, x_sorted)
            y_line = np.polyval(coeffs, x_line)
            equation = _poly_equation(coeffs, x_col, y_col)

        elif model_type == "Polynomial (2nd Order)":
            if len(np.unique(x_sorted)) < 3:
                return None
            coeffs = np.polyfit(x_sorted, y_sorted, 2)
            y_hat = np.polyval(coeffs, x_sorted)
            y_line = np.polyval(coeffs, x_line)
            equation = _poly_equation(coeffs, x_col, y_col)

        elif model_type == "Polynomial (3rd Order)":
            if len(np.unique(x_sorted)) < 4:
                return None
            coeffs = np.polyfit(x_sorted, y_sorted, 3)
            y_hat = np.polyval(coeffs, x_sorted)
            y_line = np.polyval(coeffs, x_line)
            equation = _poly_equation(coeffs, x_col, y_col)

        elif model_type == "Logarithmic":
            mask2 = x_sorted > 0
            if mask2.sum() < 4 or len(np.unique(x_sorted[mask2])) < 2:
                return None
            x2, y2 = x_sorted[mask2], y_sorted[mask2]
            coeffs = np.polyfit(np.log(x2), y2, 1)
            y_hat = coeffs[0] * np.log(x2) + coeffs[1]
            x_line = np.linspace(float(np.nanmin(x2)), float(np.nanmax(x2)), 200)
            y_line = coeffs[0] * np.log(x_line) + coeffs[1]
            x_sorted, y_sorted = x2, y2
            equation = f"{y_col} = {_format_equation_number(coeffs[0])}×ln({x_col}) + {_format_equation_number(coeffs[1])}"

        elif model_type == "Exponential":
            mask2 = y_sorted > 0
            if mask2.sum() < 4 or len(np.unique(x_sorted[mask2])) < 2:
                return None
            x2, y2 = x_sorted[mask2], y_sorted[mask2]
            coeffs = np.polyfit(x2, np.log(y2), 1)
            a = float(np.exp(coeffs[1])); b = float(coeffs[0])
            y_hat = a * np.exp(b * x2)
            x_line = np.linspace(float(np.nanmin(x2)), float(np.nanmax(x2)), 200)
            y_line = a * np.exp(b * x_line)
            x_sorted, y_sorted = x2, y2
            equation = f"{y_col} = {_format_equation_number(a)}×e^({_format_equation_number(b)}×{x_col})"
        else:
            return None

        r2 = _safe_r2(y_sorted, y_hat)
        corr = float(np.corrcoef(x_sorted, y_sorted)[0, 1]) if len(x_sorted) > 2 else np.nan
        line_df = pd.DataFrame({x_col: x_line, y_col: y_line})
        return {
            "model_type": model_type,
            "corr": corr,
            "r2": r2,
            "line_df": line_df,
            "n": len(x_sorted),
            "equation": equation,
        }
    except Exception:
        return None


def _best_fit_stats(chart_df, x_col, y_col, model_type="Linear"):
    """Compute selected scatterplot fit statistics and line data."""
    fit_df = chart_df[[x_col, y_col]].copy()
    fit_df[x_col] = pd.to_numeric(fit_df[x_col], errors="coerce")
    fit_df[y_col] = pd.to_numeric(fit_df[y_col], errors="coerce")
    fit_df = fit_df.dropna()
    fit_df = fit_df[np.isfinite(fit_df[x_col]) & np.isfinite(fit_df[y_col])]
    if len(fit_df) < 4 or fit_df[x_col].nunique() < 2 or fit_df[y_col].nunique() < 2:
        return None

    if model_type == "Auto Best Fit":
        candidates = ["Linear", "Polynomial (2nd Order)", "Polynomial (3rd Order)", "Logarithmic", "Exponential"]
        fits = []
        for m in candidates:
            f = _fit_model_for_scatter(fit_df, x_col, y_col, m)
            if f is not None and np.isfinite(f.get("r2", np.nan)):
                fits.append(f)
        if not fits:
            return None
        return max(fits, key=lambda f: f["r2"])

    return _fit_model_for_scatter(fit_df, x_col, y_col, model_type)


def _relationship_slope_direction_blurb(fit, plot_df, x_col, y_col):
    """Short slope or direction line for the chosen Auto Best Fit model (not a causal claim)."""
    if fit is None or x_col not in plot_df.columns or y_col not in plot_df.columns:
        return "—"
    sub = plot_df[[x_col, y_col]].copy()
    sub[x_col] = pd.to_numeric(sub[x_col], errors="coerce")
    sub[y_col] = pd.to_numeric(sub[y_col], errors="coerce")
    sub = sub.dropna()
    sub = sub[np.isfinite(sub[x_col]) & np.isfinite(sub[y_col])]
    if len(sub) < 4:
        return "—"
    x = sub[x_col].to_numpy(dtype=float)
    y = sub[y_col].to_numpy(dtype=float)
    corr = fit.get("corr", np.nan)
    arrow = "↑" if np.isfinite(corr) and corr > 0.05 else ("↓" if np.isfinite(corr) and corr < -0.05 else "↔")
    mt = fit.get("model_type", "")
    if mt == "Linear":
        slope = float(np.polyfit(x, y, 1)[0])
        return f"{arrow} OLS slope {slope:.4g} ({y_col} per {x_col} unit)"
    if mt == "Logarithmic":
        return f"{arrow} log curve in {x_col} (not a constant dY/dX)"
    if mt == "Exponential":
        return f"{arrow} exponential curve in {x_col}"
    if "Polynomial" in str(mt):
        return f"{arrow} curved fit ({mt})"
    return f"{arrow} {mt}"


def _relationship_math_overlap_pair(x_col, y_col):
    """True when tight fits are partly expected from definitions or shared numerators."""
    if x_col == y_col:
        return True
    rates = set(RATE_STATS)
    if x_col in rates and y_col in rates:
        return True
    pair = {x_col, y_col}
    if pair <= {"H", "AB"} or pair <= {"H", "BA"} or pair <= {"AB", "BA"}:
        return True
    if "OPS" in pair and (pair & {"OBP", "SLG"}):
        return True
    # Strong formula / component links beyond generic rate-vs-rate
    if pair in ({"HR", "SLG"}, {"TB", "SLG"}, {"OBP", "BB"}, {"RBI", "HR"}):
        return True
    return False


def _relationship_causality_label_note(x_col, y_col, r2, n, model_type):
    """Pick one causality-warning label and a single short sentence (interpretation layer only)."""
    n = int(n)
    r2 = float(r2) if np.isfinite(r2) else 0.0
    mt = str(model_type)

    notes = {
        "likely direct relationship": "Mostly volume or bookkeeping coupling—still not proof X causes Y.",
        "related but not necessarily causal": "Co-moves in this slice; other forces may drive both.",
        "possibly spurious": "Thin rows or a flexible in-sample curve can inflate R².",
        "mathematically overlapping stats": "Shared definitions or components partly tie the axes together.",
        "needs out-of-sample testing": "Strong in-filter fit—confirm on other seasons/players before leaning on it.",
    }

    if _relationship_math_overlap_pair(x_col, y_col):
        k = "mathematically overlapping stats"
        return k, notes[k]

    if (n < 35 and r2 > 0.22) or (n < 70 and r2 > 0.52):
        k = "possibly spurious"
        return k, notes[k]
    if mt == "Polynomial (3rd Order)" and n < 140:
        k = "possibly spurious"
        return k, notes[k]
    if mt == "Exponential" and n < 120:
        k = "possibly spurious"
        return k, notes[k]
    if "Polynomial" in mt and n < 55 and r2 > 0.32:
        k = "possibly spurious"
        return k, notes[k]

    if {x_col, y_col} == {"AB", "H"} and n >= 80 and r2 >= 0.22 and mt in ("Linear", "Logarithmic"):
        k = "likely direct relationship"
        return k, notes[k]

    if r2 >= 0.42 and n >= 90:
        k = "needs out-of-sample testing"
        return k, notes[k]

    k = "related but not necessarily causal"
    return k, notes[k]


@st.cache_data(show_spinner=False)
def _relationship_finder_autofit_cached(plot_df, max_cols):
    """Auto Best Fit (same candidate set as scatterplots) for directed pairs; ranked by R² then n."""
    cols = _numeric_plot_columns(plot_df)[: int(max_cols)]
    rows = []
    for xc in cols:
        for yc in cols:
            if xc == yc:
                continue
            fit = _best_fit_stats(plot_df, xc, yc, "Auto Best Fit")
            if fit is None:
                continue
            r2 = fit.get("r2", np.nan)
            if not np.isfinite(r2):
                continue
            n = int(fit.get("n", 0) or 0)
            mt = fit.get("model_type", "")
            sdir = _relationship_slope_direction_blurb(fit, plot_df, xc, yc)
            label, note = _relationship_causality_label_note(xc, yc, r2, n, mt)
            rows.append({
                "X stat": xc,
                "Y stat": yc,
                "Sample size": n,
                "Fitted model": mt,
                "R-squared": float(r2),
                "Slope / direction": sdir,
                "Causality warning": label,
                "Note": note,
            })
    if not rows:
        return pd.DataFrame(
            columns=[
                "X stat", "Y stat", "Sample size", "Fitted model", "R-squared",
                "Slope / direction", "Causality warning", "Note",
            ]
        )
    out = pd.DataFrame(rows)
    out = out.sort_values(by=["R-squared", "Sample size"], ascending=[False, False], ignore_index=True)
    return out


def render_relationship_finder_section(plot_df, *, key_prefix, row_context):
    """Surface the strongest Auto Best Fit relationships for the current filtered rows."""
    if plot_df is None or plot_df.empty:
        return
    numeric_cols = _numeric_plot_columns(plot_df)
    if len(numeric_cols) < 2:
        return

    with st.expander("Relationship Finder", expanded=False):
        st.caption(
            "Uses the same **Auto Best Fit** logic as the scatterplot (linear / polynomial / log / exponential). "
            "Scans numeric columns on your current filters, then lists only the **strongest** pairs. "
            "**High R² is not causation** and **not a forecast**; larger **sample size** usually makes a pattern more believable."
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            top_k = st.slider("Max relationships to list", 3, 12, 8, key=f"{key_prefix}_rf_top_k")
        with c2:
            min_r2 = st.slider("Minimum R² to include", 0.05, 0.55, 0.18, 0.01, key=f"{key_prefix}_rf_min_r2")
        with c3:
            max_cols = st.slider("Max numeric columns to scan", 8, min(24, len(numeric_cols)), min(18, len(numeric_cols)), key=f"{key_prefix}_rf_max_cols")

        hide_formula_overlap = st.checkbox(
            "Hide mathematically overlapping stats",
            value=True,
            key=f"{key_prefix}_rf_hide_formula_overlap",
            help="Hides rows where X and Y are tightly linked by definitions (e.g. two rate stats, H/BA/AB, OPS with OBP/SLG, HR vs SLG, TB vs SLG, OBP vs BB, RBI vs HR). "
            "The cached scan still evaluates every pair; only this table is filtered.",
        )

        approx_pairs = max(0, int(max_cols) * (int(max_cols) - 1))
        st.caption(
            f"Up to ~{approx_pairs:,} directed pairs on {len(plot_df):,} {row_context} "
            f"(first {int(max_cols)} numeric fields from the scatterplot list)."
            + (" Formula-linked pairs are omitted from the table below." if hide_formula_overlap else "")
        )

        result = _relationship_finder_autofit_cached(plot_df, int(max_cols))
        if result.empty:
            st.info("No pairs produced a valid Auto Best Fit (need enough variation on both axes).")
            return
        display_df = result
        if hide_formula_overlap:
            keep = [
                not _relationship_math_overlap_pair(str(a), str(b))
                for a, b in zip(display_df["X stat"], display_df["Y stat"])
            ]
            display_df = display_df[keep].reset_index(drop=True)
            if display_df.empty:
                st.info(
                    "Every scanned pair matched the formula-overlap rules for this column set. "
                    "Uncheck “Hide mathematically overlapping stats”, widen “Max numeric columns to scan”, or loosen filters."
                )
                return
        qualified = display_df[display_df["R-squared"] >= float(min_r2)].head(int(top_k))
        if qualified.empty:
            st.info("Nothing met the minimum R² — lower the threshold or widen filters.")
            return
        show = qualified.copy()
        show["R-squared"] = show["R-squared"].map(lambda v: round(float(v), 4) if pd.notna(v) else np.nan)
        st.dataframe(show, width="stretch", hide_index=True)


def fit_interpretation_markdown(fit, x_col, y_col):
    """Plain-English guidance for a displayed scatterplot fit."""
    if fit is None:
        return ""

    r2 = fit.get("r2", np.nan)
    corr = fit.get("corr", np.nan)
    n = int(fit.get("n", 0) or 0)
    model_type = fit.get("model_type", "fit")

    if not np.isfinite(r2):
        return (
            "**Fit interpretation:** Not enough stable variation to judge this fit. "
            "Treat the line as a visual guide only."
        )

    abs_corr = abs(float(corr)) if np.isfinite(corr) else np.nan
    if r2 >= 0.65:
        fit_use = "The fit looks useful for summarizing the main pattern."
        r2_text = "R-squared is strong, so the line explains a large share of the variation."
        caution = "Predictions can be directional, but still check outliers and baseball context."
    elif r2 >= 0.35:
        fit_use = "The fit is moderately useful."
        r2_text = "R-squared is moderate, so the line captures part of the relationship."
        caution = "Use predictions cautiously and as rough ranges, not exact estimates."
    elif r2 >= 0.15:
        fit_use = "The fit shows a weak relationship."
        r2_text = "R-squared is weak, so many points move away from the fitted line."
        caution = "Use the line as a rough visual cue, not a reliable prediction."
    else:
        fit_use = "The fit is not very useful for prediction."
        r2_text = "R-squared is very weak, so the line explains little of the variation."
        caution = "Avoid reading precise predictions from this chart."

    if np.isfinite(abs_corr) and abs_corr >= 0.65:
        noise_text = "The relationship is fairly clear, though individual players can still differ."
    elif np.isfinite(abs_corr) and abs_corr >= 0.35:
        noise_text = "The relationship has visible noise around the line."
    else:
        noise_text = "The relationship appears noisy."

    return (
        f"**Fit interpretation ({x_col} vs {y_col}, {model_type}, {n:,} rows):** {fit_use} "
        f"{r2_text} {noise_text} {caution}"
    )


def _format_equation_number(value):
    if not np.isfinite(value):
        return "nan"
    if abs(value) >= 100:
        return f"{value:.1f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    if abs(value) >= 1:
        return f"{value:.3f}"
    return f"{value:.4f}"


def render_scatterplot_section(plot_df, *, key_prefix, title="Visualize Results"):
    """Interactive scatterplot for the current filtered result set."""
    if plot_df is None or plot_df.empty:
        return

    plot_df = plot_df.copy()
    numeric_cols = _numeric_plot_columns(plot_df)
    if len(numeric_cols) < 2:
        return

    st.subheader(title)

    default_x = "HR" if "HR" in numeric_cols else numeric_cols[0]
    default_y = "SB" if "SB" in numeric_cols else ("OPS" if "OPS" in numeric_cols else numeric_cols[min(1, len(numeric_cols)-1)])

    with st.expander("Scatterplot options", expanded=False):
        p1, p2, p3, p4 = st.columns([1, 1, 1, 1])
        with p1:
            x_col = st.selectbox("X-axis", numeric_cols, index=numeric_cols.index(default_x), key=f"{key_prefix}_scatter_x")
        with p2:
            y_col = st.selectbox("Y-axis", numeric_cols, index=numeric_cols.index(default_y), key=f"{key_prefix}_scatter_y")
        cat_options = ["None"] + _categorical_plot_columns(plot_df)
        with p3:
            color_col = st.selectbox("Color by", cat_options, index=0, key=f"{key_prefix}_scatter_color")
        size_options = ["None"] + numeric_cols
        with p4:
            size_col = st.selectbox("Size by", size_options, index=0, key=f"{key_prefix}_scatter_size")

        max_points = st.slider(
            "Maximum points to plot",
            min_value=250,
            max_value=5000,
            value=min(1500, max(250, len(plot_df))),
            step=250,
            key=f"{key_prefix}_scatter_max_points",
            help="Lower values make very large charts more responsive."
        )

        view_mode = st.radio(
            "Scatterplot view",
            ["Focused View", "Full Outlier View"],
            horizontal=True,
            key=f"{key_prefix}_scatter_view_mode",
            help="Focused View keeps the main cluster readable. Full Outlier View expands the axes to include every outlier."
        )

        show_trendline = st.checkbox("Show trendline", value=False, key=f"{key_prefix}_scatter_show_trendline")
        trendline_type = "Linear"
        if show_trendline:
            trendline_type = st.selectbox(
                "Trendline type",
                ["Linear", "Polynomial (2nd Order)", "Polynomial (3rd Order)", "Logarithmic", "Exponential", "Auto Best Fit"],
                index=0,
                key=f"{key_prefix}_scatter_trendline_type",
                help="Choose a curve for the selected X/Y relationship."
            )

    chart_df = plot_df.copy()
    chart_df[x_col] = pd.to_numeric(chart_df[x_col], errors="coerce")
    chart_df[y_col] = pd.to_numeric(chart_df[y_col], errors="coerce")
    chart_df = chart_df.dropna(subset=[x_col, y_col])
    if chart_df.empty:
        st.info("No rows have valid values for both selected axes.")
        return

    domain_df = chart_df.copy()

    if len(chart_df) > max_points:
        if view_mode == "Full Outlier View":
            extreme_idx = set()
            for _col in [x_col, y_col]:
                extreme_idx.update(chart_df.nlargest(min(25, len(chart_df)), _col).index.tolist())
                extreme_idx.update(chart_df.nsmallest(min(25, len(chart_df)), _col).index.tolist())
            remaining = chart_df.drop(index=list(extreme_idx), errors="ignore")
            needed = max_points - len(extreme_idx)
            if needed > 0 and not remaining.empty:
                sampled = remaining.sample(n=min(needed, len(remaining)), random_state=42)
                chart_df = pd.concat([chart_df.loc[list(extreme_idx)], sampled], axis=0)
            else:
                chart_df = chart_df.loc[list(extreme_idx)].head(max_points)
            st.caption(f"Showing {len(chart_df):,} plotted points with extreme outliers preserved. Export or narrow filters for all rows.")
        else:
            chart_df = chart_df.sort_values(y_col, ascending=False).head(max_points)
            st.caption(f"Showing {max_points:,} plotted points. Narrow filters for a complete visual.")

    if key_prefix == "career":
        tooltip_order = [
            "Player", "Debut Age", "Final Age", "Team", "Primary Position", "Bats", "League",
            "HR", "OPS", "G", "SB", x_col, y_col
        ]
    else:
        tooltip_order = [
            "Player", "Year", "Team", "Age", "Primary Position", "Bats", "League",
            "HR", "OPS", "G", "SB", "BB", x_col, y_col
        ]
    tooltip_cols = [c for c in tooltip_order if c in chart_df.columns]
    tooltip_cols = list(dict.fromkeys(tooltip_cols))

    if view_mode == "Full Outlier View":
        x_scale, x_axis = _full_axis_config_for_column(x_col, domain_df[x_col])
        y_scale, y_axis = _full_axis_config_for_column(y_col, domain_df[y_col])
    else:
        x_scale, x_axis = _axis_config_for_column(x_col, chart_df[x_col])
        y_scale, y_axis = _axis_config_for_column(y_col, chart_df[y_col])

    enc = {
        "x": alt.X(f"{x_col}:Q", title=x_col, scale=x_scale, axis=x_axis),
        "y": alt.Y(f"{y_col}:Q", title=y_col, scale=y_scale, axis=y_axis),
        "tooltip": [alt.Tooltip(c, title=c) for c in tooltip_cols],
    }

    color_encoding = _scatter_color_encoding(chart_df, color_col)
    if color_encoding is not None:
        enc["color"] = color_encoding

    size_encoding = _scatter_size_encoding(chart_df, size_col)
    if size_encoding is not None:
        enc["size"] = size_encoding

    mark_kwargs = {"opacity": 0.74, "stroke": "#444444", "strokeWidth": 0.45}
    if size_encoding is None:
        mark_kwargs["size"] = 85

    points = alt.Chart(chart_df).mark_circle(**mark_kwargs).encode(**enc)

    fit = _best_fit_stats(chart_df, x_col, y_col, trendline_type) if show_trendline else None
    chart = points
    if fit is not None:
        fit_line = (
            alt.Chart(fit["line_df"])
            .mark_line(color="#111111", strokeWidth=2.5, strokeDash=[8, 5])
            .encode(
                x=alt.X(f"{x_col}:Q", scale=x_scale),
                y=alt.Y(f"{y_col}:Q", scale=y_scale),
            )
        )
        chart = points + fit_line

    chart = chart.interactive().properties(height=520)
    st.altair_chart(chart, width="stretch")

    if fit is not None:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Fit Type", fit.get("model_type", trendline_type))
        m2.metric("Correlation (r)", f"{fit['corr']:.3f}" if np.isfinite(fit.get('corr', np.nan)) else "N/A")
        m3.metric("R²", f"{fit['r2']:.3f}" if np.isfinite(fit.get('r2', np.nan)) else "N/A")
        m4.metric("Rows Used", f"{fit['n']:,}")
        st.caption(f"Best-fit equation: {fit.get('equation', '')}")
        st.info(fit_interpretation_markdown(fit, x_col, y_col))
    elif show_trendline:
        st.caption("Best-fit curve unavailable because there are not enough valid numeric points, one axis has no variation, or the selected model requires positive values.")

def clean_feature_name(feature):
    """Make model feature names readable for the UI."""
    text = str(feature)
    replacements = {
        "age_entering_year": "Age",
        "hist_G_total": "Recent Games",
        "hist_AB_total": "Recent AB",
        "_mean_3yr": " 3-Year Avg",
        "_mean_4yr": " 4-Year Avg",
        "_mean_5yr": " 5-Year Avg",
        "_last": " Last Season",
        "_trend": " Trend",
        "yearID": "Year",
        "fullName": "Player",
        "bats": "Bats",
        "teamID": "Team",
        "playerID": "Player",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("_", " ").strip()
    return text

def clean_ui_columns(df):
    """Final safeguard so backend ID-style columns never appear in displayed tables."""
    df = df.copy()
    rename_map = {
        "yearID": "Year",
        "fullName": "Player",
        "bats": "Bats",
        "primaryPos": "Primary Position",
        "primaryHistoricalTeamName": "Team",
        "prediction_year": "Prediction Year",
        "predict_year": "Prediction Year",
        "last_year": "Last Year",
        "age_entering_year": "Age",
        "hist_G_total": "Recent Games",
        "hist_AB_total": "Recent AB",
        "score": "Score",
        "Trend_Score": "Trend Score",
        "Perf_Score": "Current Score",
        "Valuation_Score": "Valuation Score",
    }
    df = df.rename(columns=rename_map)
    drop_cols = [c for c in df.columns if str(c).lower().endswith("id") or "playerid" in str(c).lower() or "teamid" in str(c).lower()]
    return df.drop(columns=drop_cols, errors="ignore")




# ----------------------------
# FantasyPros / market-data helpers
# ----------------------------
def normalize_player_name_for_merge(name):
    """Normalize player names so Lahman/app names can match FantasyPros names."""
    if pd.isna(name):
        return ""
    text = str(name)
    text = text.replace("(Batter)", "").replace("(Pitcher)", "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


# Backward-compatible alias used by Draft Assistant code
normalize_player_name = normalize_player_name_for_merge

def read_optional_csv(filename):
    """Read an optional CSV from the same app folder. Return empty df if missing."""
    path = BASE_DIR / filename
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False, dtype=str)
    except Exception:
        try:
            return pd.read_csv(path, low_memory=False, dtype=str, engine="python")
        except Exception:
            return pd.DataFrame()


def first_existing_col(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def to_numeric_safe_series(s):
    return pd.to_numeric(s.astype(str).str.replace("-", "", regex=False).str.replace(",", "", regex=False), errors="coerce")


@st.cache_data(show_spinner=False)
def load_fantasypros_market_data():
    """Load FantasyPros expert rankings and ADP if the CSVs are in the app folder.

    Expected optional files:
    - FantasyPros_2026_Draft_H_Rankings.csv
    - FantasyPros_2026_Hitter_MLB_ADP_Rankings.csv

    The ADP export can have awkward headers, so this function detects the useful columns.
    """
    rank_file = "FantasyPros_2026_Draft_H_Rankings.csv"
    adp_file = "FantasyPros_2026_Hitter_MLB_ADP_Rankings.csv"

    rankings = read_optional_csv(rank_file)
    adp = read_optional_csv(adp_file)
    pieces = []

    if not rankings.empty:
        r = rankings.copy()
        player_col = first_existing_col(r, ["PLAYER NAME", "Player", "PLAYER", "Name"])
        if player_col:
            out = pd.DataFrame()
            out["Player"] = r[player_col].astype(str).str.strip()
            out["Player Key"] = out["Player"].apply(normalize_player_name_for_merge)
            out["FantasyPros Rank"] = to_numeric_safe_series(r[first_existing_col(r, ["RK", "Rank", "ECR"])] if first_existing_col(r, ["RK", "Rank", "ECR"]) else pd.Series(np.nan, index=r.index))
            out["Expert Avg Rank"] = to_numeric_safe_series(r[first_existing_col(r, ["AVG.", "AVG", "Average"])] if first_existing_col(r, ["AVG.", "AVG", "Average"]) else pd.Series(np.nan, index=r.index))
            out["Expert Std Dev"] = to_numeric_safe_series(r[first_existing_col(r, ["STD.DEV", "STD DEV", "Std Dev"])] if first_existing_col(r, ["STD.DEV", "STD DEV", "Std Dev"]) else pd.Series(np.nan, index=r.index))
            out["ECR vs ADP"] = r[first_existing_col(r, ["ECR VS ADP", "ECR vs ADP"])] if first_existing_col(r, ["ECR VS ADP", "ECR vs ADP"]) else np.nan
            out["FantasyPros Team"] = r[first_existing_col(r, ["TEAM", "Team"])] if first_existing_col(r, ["TEAM", "Team"]) else ""
            out["FantasyPros Position"] = r[first_existing_col(r, ["POS", "Positions", "Position"])] if first_existing_col(r, ["POS", "Positions", "Position"]) else ""
            out = out[out["Player Key"] != ""]
            pieces.append(out)

    if not adp.empty:
        a = adp.copy()
        # Normal clean export: Player column is actually player names.
        player_col = first_existing_col(a, ["Player", "PLAYER NAME", "PLAYER", "Name"])
        # The uploaded FantasyPros ADP file appears to put player names in the first "Positions" column.
        # If the Player column looks like positions (many comma-separated position strings), switch to Positions.
        if player_col and player_col in a.columns:
            sample = a[player_col].dropna().astype(str).head(20).str.contains(r"^(C|1B|2B|3B|SS|OF|LF|CF|RF|DH|SP|RP)(,|$)", regex=True).mean()
            if sample > 0.4 and "Positions" in a.columns:
                player_col = "Positions"
        elif "Positions" in a.columns:
            player_col = "Positions"

        if player_col:
            out = pd.DataFrame()
            out["Player"] = a[player_col].astype(str).str.strip()
            out["Player Key"] = out["Player"].apply(normalize_player_name_for_merge)
            # Prefer AVG if populated; otherwise use the first rank column, which is often hitter ADP rank.
            avg_col = first_existing_col(a, ["AVG", "AVG.", "Average"])
            hitter_rank_col = first_existing_col(a, ["Hitters", "Hitter", "Rank"])
            if avg_col and to_numeric_safe_series(a[avg_col]).notna().sum() > 5:
                out["ADP"] = to_numeric_safe_series(a[avg_col])
            elif hitter_rank_col:
                out["ADP"] = to_numeric_safe_series(a[hitter_rank_col])
            else:
                out["ADP"] = np.nan
            out["ADP Rank"] = out["ADP"].rank(method="min", ascending=True)
            # Best-effort team/position fields from messy export.
            team_candidate = first_existing_col(a, ["Overall", "TEAM", "Team"])
            out["ADP Team"] = a[team_candidate] if team_candidate else ""
            pos_candidate = first_existing_col(a, ["Player", "POS", "Positions"])
            out["ADP Position"] = a[pos_candidate] if pos_candidate and pos_candidate != player_col else ""
            out = out[out["Player Key"] != ""]
            pieces.append(out)

    if not pieces:
        return pd.DataFrame()

    market = pieces[0]
    for piece in pieces[1:]:
        market = market.merge(piece.drop(columns=["Player"], errors="ignore"), on="Player Key", how="outer", suffixes=("", "_adp"))
    if "Player" not in market.columns:
        market["Player"] = market["Player Key"]
    # Consolidate duplicate columns from the outer merge.
    for col in ["FantasyPros Rank", "Expert Avg Rank", "Expert Std Dev", "ADP", "ADP Rank"]:
        dup = f"{col}_adp"
        if dup in market.columns:
            market[col] = pd.to_numeric(market.get(col), errors="coerce").fillna(pd.to_numeric(market[dup], errors="coerce"))
            market = market.drop(columns=[dup])
    market["Market Rank"] = pd.to_numeric(market.get("ADP Rank"), errors="coerce")
    market["Market Rank"] = market["Market Rank"].fillna(pd.to_numeric(market.get("FantasyPros Rank"), errors="coerce"))
    market = market.sort_values("Market Rank", na_position="last").drop_duplicates("Player Key", keep="first")
    return market


def normalize_score(series):
    s = pd.to_numeric(series, errors="coerce")
    mn, mx = s.min(), s.max()
    if pd.isna(mn) or pd.isna(mx) or mx == mn:
        return pd.Series(0.5, index=s.index)
    return (s - mn) / (mx - mn)


def make_fantasy_market_reason(row, kind="sleeper"):
    """Create individualized sleeper/bust explanations using model-vs-market gap and projected stat profile."""
    player = row.get("fullName", row.get("Player", "This player"))
    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    market_rank = pd.to_numeric(row.get("Market Rank", row.get("ADP Rank", np.nan)), errors="coerce")
    model_rank = pd.to_numeric(row.get("Model Rank", np.nan), errors="coerce")

    proj_hr = pd.to_numeric(row.get("Projected HR", row.get("proj_HR", np.nan)), errors="coerce")
    proj_rbi = pd.to_numeric(row.get("Projected RBI", row.get("proj_RBI", np.nan)), errors="coerce")
    proj_r = pd.to_numeric(row.get("Projected R", row.get("proj_R", np.nan)), errors="coerce")
    proj_sb = pd.to_numeric(row.get("Projected SB", row.get("proj_SB", np.nan)), errors="coerce")
    proj_ba = pd.to_numeric(row.get("Projected BA", row.get("proj_BA", np.nan)), errors="coerce")
    proj_ops = pd.to_numeric(row.get("Projected OPS", row.get("proj_OPS", np.nan)), errors="coerce")
    prod = pd.to_numeric(row.get("Projected Production Score", np.nan), errors="coerce")

    strengths = []
    if pd.notna(proj_hr) and proj_hr >= 25:
        strengths.append(f"power upside ({fmt_count_1(proj_hr)} projected HR)")
    if pd.notna(proj_rbi) and proj_rbi >= 80:
        strengths.append(f"run-production upside ({fmt_count_1(proj_rbi)} projected RBI)")
    if pd.notna(proj_r) and proj_r >= 80:
        strengths.append(f"run-scoring upside ({fmt_count_1(proj_r)} projected R)")
    if pd.notna(proj_sb) and proj_sb >= 15:
        strengths.append(f"speed upside ({fmt_count_1(proj_sb)} projected SB)")
    if pd.notna(proj_ba) and proj_ba >= 0.275:
        strengths.append(f"batting-average support ({fmt_rate_3(proj_ba)} projected BA)")
    if pd.notna(proj_ops) and proj_ops >= 0.820:
        strengths.append(f"strong overall bat ({fmt_rate_3(proj_ops)} projected OPS)")

    if kind == "sleeper":
        if pd.notna(edge):
            if edge >= 50:
                gap_text = f"your model is extremely ahead of the market by {fmt_int(edge)} ranking spots"
            elif edge >= 25:
                gap_text = f"your model is meaningfully ahead of the market by {fmt_int(edge)} ranking spots"
            elif edge > 0:
                gap_text = f"your model is slightly ahead of the market by {fmt_int(edge)} spots"
            else:
                gap_text = "the market gap is not large, so this is more of a watch-list value than a major sleeper"
        else:
            gap_text = "market rank is missing, so this is based mostly on the projection"

        if strengths:
            return f"{player} is flagged because {gap_text}, and the projection shows " + "; ".join(strengths[:3]) + "."
        if pd.notna(prod) and prod >= 0.65:
            return f"{player} is flagged because {gap_text}, with a strong overall projected production score."
        return f"{player} is flagged because {gap_text}."

    if pd.notna(edge):
        if edge <= -50:
            gap_text = f"the market is extremely higher than your model by {fmt_int(abs(edge))} ranking spots"
        elif edge <= -25:
            gap_text = f"the market is meaningfully higher than your model by {fmt_int(abs(edge))} ranking spots"
        elif edge < 0:
            gap_text = f"the market is slightly higher than your model by {fmt_int(abs(edge))} spots"
        else:
            gap_text = "your model is not strongly below the market, so the bust signal is modest"
    else:
        gap_text = "market rank is missing, so bust risk is harder to judge"

    weak_notes = []
    if pd.notna(proj_hr) and proj_hr < 15:
        weak_notes.append("limited projected power")
    if pd.notna(proj_sb) and proj_sb < 8:
        weak_notes.append("limited projected speed")
    if pd.notna(proj_ops) and proj_ops < 0.740:
        weak_notes.append("weaker projected OPS")
    if pd.notna(proj_ba) and proj_ba < 0.245:
        weak_notes.append("batting-average risk")

    if weak_notes:
        return f"{player} is a bust-risk flag because {gap_text}, with " + ", ".join(weak_notes[:3]) + "."
    return f"{player} is a bust-risk flag because {gap_text}; the projection does not appear to justify the market price."

def baseball_age_for_season(season_year, birth_year, birth_month=np.nan, birth_day=np.nan):
    """Approximate MLB season age using July 1 of the season, not simply season_year - birth_year.
    This prevents late-year birthdays from being overstated by one year.
    """
    try:
        season_year = int(season_year)
        birth_year = int(float(birth_year))
    except Exception:
        return np.nan
    try:
        birth_month = int(float(birth_month))
        birth_day = int(float(birth_day))
    except Exception:
        birth_month, birth_day = 7, 1
    age = season_year - birth_year
    if (birth_month, birth_day) > (7, 1):
        age -= 1
    return age

@st.cache_data(show_spinner=False)
def add_latest_and_projection_columns(base_df, recent_data):
    """Add latest-season stats and simple next-season trend projections.

    Safe for pages like Draft Assistant that may not already have *_trend columns.
    Missing trend columns are treated as 0, so projection becomes latest season + 0.
    """
    df = base_df.copy()

    latest_cols = ["playerID", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]
    latest_available = [c for c in latest_cols if c in recent_data.columns]

    latest_stats = (
        recent_data.sort_values(["playerID", "yearID"])
        .groupby("playerID")
        .tail(1)[latest_available]
        .rename(columns={
            "R": "latest_R", "H": "latest_H", "2B": "latest_2B", "3B": "latest_3B",
            "HR": "latest_HR", "RBI": "latest_RBI", "SB": "latest_SB", "BB": "latest_BB",
            "BA": "latest_BA", "OBP": "latest_OBP", "SLG": "latest_SLG", "OPS": "latest_OPS"
        })
    )

    df = df.merge(latest_stats, on="playerID", how="left")

    # If this helper is called from a page without precomputed trends, create neutral trends.
    for stat in ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]:
        trend_col = f"{stat}_trend"
        if trend_col not in df.columns:
            df[trend_col] = 0.0
        df[trend_col] = pd.to_numeric(df[trend_col], errors="coerce").fillna(0)

        latest_col = f"latest_{stat}"
        if latest_col not in df.columns:
            df[latest_col] = 0.0
        df[latest_col] = pd.to_numeric(df[latest_col], errors="coerce").fillna(0)

    df["XBH_noHR_trend"] = df["2B_trend"] + df["3B_trend"]
    df["latest_XBH_noHR"] = df["latest_2B"] + df["latest_3B"]

    df["proj_R"] = df["latest_R"] + df["R_trend"]
    df["proj_H"] = df["latest_H"] + df["H_trend"]
    df["proj_XBH"] = df["latest_XBH_noHR"] + df["XBH_noHR_trend"]
    df["proj_HR"] = df["latest_HR"] + df["HR_trend"]
    df["proj_RBI"] = df["latest_RBI"] + df["RBI_trend"]
    df["proj_SB"] = df["latest_SB"] + df["SB_trend"]
    df["proj_BB"] = df["latest_BB"] + df["BB_trend"]
    df["proj_BA"] = df["latest_BA"] + df["BA_trend"]
    df["proj_OBP"] = df["latest_OBP"] + df["OBP_trend"]
    df["proj_SLG"] = df["latest_SLG"] + df["SLG_trend"]
    df["proj_OPS"] = df["latest_OPS"] + df["OPS_trend"]
    return df


@st.cache_data(show_spinner=False)
def prepare_ml_yearly_source(yearly_source):
    """Add ML-ready context and derived features once, then cache it.

    This function is intentionally cached because it is used by both training-row creation
    and current-player projection creation.
    """
    df = yearly_source.copy()
    for col in ["yearID", "birthYear", "birthMonth", "birthDay"] + ML_BASE_FEATURE_STATS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["PA_est"] = df["AB"] + df["BB"]
    safe_pa = df["PA_est"].replace(0, np.nan)
    safe_ab = df["AB"].replace(0, np.nan)
    steal_attempts = (df["SB"] + df["CS"]).replace(0, np.nan)
    df["BB_rate"] = (df["BB"] / safe_pa).fillna(0)
    df["K_rate"] = (df["SO"] / safe_pa).fillna(0)
    df["SB_rate"] = (df["SB"] / steal_attempts).fillna(0)
    df["XBH"] = df["2B"] + df["3B"] + df["HR"]
    df["XBH_rate"] = (df["XBH"] / safe_ab).fillna(0)
    df["HR_rate"] = (df["HR"] / safe_ab).fillna(0)
    df["Speed_Index"] = (df["SB"] + 2 * df["3B"]) / df["G"].replace(0, np.nan)
    df["Speed_Index"] = df["Speed_Index"].fillna(0)
    df["bats"] = df.get("bats", "Unknown").fillna("Unknown").replace({"": "Unknown"})
    df["primaryPos"] = df.get("primaryPos", "DH").fillna("DH").replace({"": "DH"})
    df["careerPrimaryPos"] = df.get("careerPrimaryPos", df["primaryPos"]).fillna(df["primaryPos"]).replace({"": "DH"})
    df["primaryTeamID"] = df.get("primaryTeamID", "UNK").fillna("UNK").replace({"": "UNK"})
    df["League"] = df["primaryTeamID"].apply(team_league)
    df["Park_Factor"] = df["primaryTeamID"].map(TEAM_PARK_FACTOR).fillna(1.0)
    return df.sort_values(["playerID", "yearID"]).reset_index(drop=True)


def add_context_dummy_features(row, source_row):
    """Add low-cardinality categorical features as numeric dummy variables."""
    bats = str(source_row.get("bats", "Unknown") or "Unknown")
    pos = str(source_row.get("primaryPos", "DH") or "DH")
    league = str(source_row.get("League", "Unknown") or "Unknown")
    team = str(source_row.get("primaryTeamID", "UNK") or "UNK")
    for b in ["L", "R", "B", "Unknown"]:
        row[f"bats_{b}"] = 1 if bats == b else 0
    for p in ["C", "1B", "2B", "3B", "SS", "OF", "P", "DH"]:
        row[f"pos_{p}"] = 1 if pos == p else 0
    for lg in ["AL", "NL", "Unknown"]:
        row[f"league_{lg}"] = 1 if league == lg else 0
    # Keep team as broad context without allowing hundreds of sparse old team codes.
    for t in sorted(AL_TEAMS | NL_TEAMS):
        row[f"team_{t}"] = 1 if team == t else 0
    row["Park_Factor"] = pd.to_numeric(source_row.get("Park_Factor", 1.0), errors="coerce")
    return row


@st.cache_data(show_spinner=False)
def build_ml_training_set(yearly_source, lookback_years=3, min_games_per_window=50, target_stats_tuple=tuple(ML_TARGET_STATS)):
    """Create supervised learning rows: last N years of features -> following-year stats.

    Added features include age/age², bats, primary position, team, league, park factor,
    recent stats, rolling means, trend slopes, playing time, walk rate, strikeout rate,
    OPS, and speed/durability proxies.
    """
    target_stats = list(target_stats_tuple)
    df = prepare_ml_yearly_source(yearly_source)
    rows = []
    all_feature_stats = ML_BASE_FEATURE_STATS + ML_DERIVED_FEATURE_STATS
    for player_id, g in df.groupby("playerID", sort=False):
        g = g.sort_values("yearID").reset_index(drop=True)
        for idx in range(lookback_years, len(g)):
            history = g.iloc[idx - lookback_years:idx]
            target = g.iloc[idx]
            expected_years = list(range(int(target["yearID"]) - lookback_years, int(target["yearID"])))
            if history["yearID"].astype(int).tolist() != expected_years:
                continue
            if pd.to_numeric(history["G"], errors="coerce").sum() < min_games_per_window:
                continue
            birth_year = pd.to_numeric(target.get("birthYear", np.nan), errors="coerce")
            age = baseball_age_for_season(target["yearID"], birth_year, target.get("birthMonth", np.nan), target.get("birthDay", np.nan))
            row = {
                "playerID": player_id,
                "fullName": target.get("fullName", ""),
                "bats": target.get("bats", ""),
                "primaryPos": target.get("primaryPos", ""),
                "League": target.get("League", "Unknown"),
                "primaryTeamID": target.get("primaryTeamID", "UNK"),
                "predict_year": int(target["yearID"]),
                "last_year": int(target["yearID"]) - 1,
                "age_entering_year": age,
                "age_squared": age ** 2 if pd.notna(age) else np.nan,
                "hist_G_total": pd.to_numeric(history["G"], errors="coerce").sum(),
                "hist_AB_total": pd.to_numeric(history["AB"], errors="coerce").sum(),
                "durability_3yr_avg_G": pd.to_numeric(history["G"], errors="coerce").mean(),
                "durability_3yr_min_G": pd.to_numeric(history["G"], errors="coerce").min(),
            }
            row = add_context_dummy_features(row, target)
            # weighted recency: latest year gets the largest weight
            weights = np.arange(1, len(history) + 1, dtype=float)
            weights = weights / weights.sum()
            for stat in all_feature_stats:
                if stat not in history.columns:
                    continue
                values = pd.to_numeric(history[stat], errors="coerce").fillna(0)
                row[f"{stat}_mean_{lookback_years}yr"] = values.mean()
                row[f"{stat}_weighted_recent"] = float(np.dot(values.to_numpy(), weights))
                row[f"{stat}_last"] = values.iloc[-1]
                row[f"{stat}_trend"] = compute_trend_slope(history, stat)
            for stat in target_stats:
                row[f"target_{stat}"] = pd.to_numeric(target.get(stat, np.nan), errors="coerce")
            rows.append(row)
    ml_df = pd.DataFrame(rows)
    if ml_df.empty:
        return ml_df, []
    exclude = {"playerID", "fullName", "bats", "primaryPos", "League", "primaryTeamID", "predict_year", "last_year"}
    feature_cols = [c for c in ml_df.columns if c not in exclude and not c.startswith("target_")]
    ml_df[feature_cols] = ml_df[feature_cols].apply(pd.to_numeric, errors="coerce")
    target_cols = [f"target_{stat}" for stat in target_stats]
    ml_df[target_cols] = ml_df[target_cols].apply(pd.to_numeric, errors="coerce")
    ml_df = ml_df.dropna(subset=target_cols, how="all")
    return ml_df, feature_cols


@st.cache_resource(show_spinner=False)
def train_random_forest_models(ml_training_df, feature_cols_tuple, target_stats_tuple=tuple(ML_TARGET_STATS), random_state=42):
    """Train compact Random Forest models once and cache them for Streamlit Cloud speed."""
    target_stats = list(target_stats_tuple)
    feature_cols = list(feature_cols_tuple)
    results = {}
    if ml_training_df.empty or not feature_cols:
        return results
    X = ml_training_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
    for stat in target_stats:
        target_col = f"target_{stat}"
        if target_col not in ml_training_df.columns:
            continue
        y = pd.to_numeric(ml_training_df[target_col], errors="coerce")
        valid = y.notna()
        if valid.sum() < 40:
            continue
        X_valid = X.loc[valid]
        y_valid = y.loc[valid]
        if len(X_valid) >= 80:
            X_train, X_test, y_train, y_test = train_test_split(X_valid, y_valid, test_size=0.25, random_state=random_state)
        else:
            X_train, X_test, y_train, y_test = X_valid, X_valid, y_valid, y_valid
        model = RandomForestRegressor(
            n_estimators=12,
            max_depth=8,
            min_samples_leaf=10,
            max_features="sqrt",
            random_state=random_state,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        importances = pd.DataFrame({"Feature": feature_cols, "Importance": model.feature_importances_}).sort_values("Importance", ascending=False)
        results[stat] = {
            "model": model,
            "mae": float(mean_absolute_error(y_test, preds)),
            "r2": float(r2_score(y_test, preds)) if len(y_test) > 1 else np.nan,
            "importance": importances,
        }
    return results


@st.cache_data(show_spinner=False)
def build_current_prediction_rows(yearly_source, lookback_years=3, min_games_per_window=50, max_player_pool=300):
    """Create one current row per active/recent player using each player's true max(yearID).

    Optimized for Streamlit Cloud:
    - only active/recent players are projected
    - optional cap on player pool, sorted by recent AB
    - feature construction mirrors training features exactly
    """
    df = prepare_ml_yearly_source(yearly_source)
    df = df.dropna(subset=["playerID", "yearID"]).copy()
    df["yearID"] = df["yearID"].astype(int)
    max_data_year = int(df["yearID"].max())
    rows = []
    all_feature_stats = ML_BASE_FEATURE_STATS + ML_DERIVED_FEATURE_STATS
    for player_id, g in df.groupby("playerID", sort=False):
        g = g.sort_values("yearID").reset_index(drop=True)
        latest_year = int(g["yearID"].max())
        if latest_year < max_data_year - 1:
            continue
        latest = g[g["yearID"] == latest_year].iloc[0]
        history = g[g["yearID"] <= latest_year].tail(lookback_years).copy()
        if len(history) < lookback_years:
            continue
        expected_years = list(range(latest_year - lookback_years + 1, latest_year + 1))
        if history["yearID"].astype(int).tolist() != expected_years:
            continue
        if pd.to_numeric(history["G"], errors="coerce").sum() < min_games_per_window:
            continue
        birth_year = pd.to_numeric(latest.get("birthYear", np.nan), errors="coerce")
        age = baseball_age_for_season(latest_year + 1, birth_year, latest.get("birthMonth", np.nan), latest.get("birthDay", np.nan))
        row = {
            "playerID": player_id,
            "fullName": latest.get("fullName", ""),
            "bats": latest.get("bats", ""),
            "primaryPos": latest.get("primaryPos", ""),
            "League": latest.get("League", "Unknown"),
            "primaryTeamID": latest.get("primaryTeamID", "UNK"),
            "last_year": latest_year,
            "prediction_year": latest_year + 1,
            "age_entering_year": age,
            "age_squared": age ** 2 if pd.notna(age) else np.nan,
            "hist_G_total": pd.to_numeric(history["G"], errors="coerce").sum(),
            "hist_AB_total": pd.to_numeric(history["AB"], errors="coerce").sum(),
            "durability_3yr_avg_G": pd.to_numeric(history["G"], errors="coerce").mean(),
            "durability_3yr_min_G": pd.to_numeric(history["G"], errors="coerce").min(),
        }
        row = add_context_dummy_features(row, latest)
        for stat in ML_BASE_FEATURE_STATS:
            row[f"Last {stat}"] = pd.to_numeric(latest.get(stat, np.nan), errors="coerce")
        weights = np.arange(1, len(history) + 1, dtype=float)
        weights = weights / weights.sum()
        for stat in all_feature_stats:
            if stat not in history.columns:
                continue
            values = pd.to_numeric(history[stat], errors="coerce").fillna(0)
            row[f"{stat}_mean_{lookback_years}yr"] = values.mean()
            row[f"{stat}_weighted_recent"] = float(np.dot(values.to_numpy(), weights))
            row[f"{stat}_last"] = values.iloc[-1]
            row[f"{stat}_trend"] = compute_trend_slope(history, stat)
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty and max_player_pool:
        out = out.sort_values("hist_AB_total", ascending=False).head(int(max_player_pool)).reset_index(drop=True)
    return out


@st.cache_data(show_spinner=False)
def get_target_baselines(ml_training_df, target_stats_tuple=tuple(ML_TARGET_STATS)):
    """Per-stat training-set means for regression-to-the-mean (cached on training frame + stat list)."""
    target_stats = list(target_stats_tuple)
    baselines = {}
    for stat in target_stats:
        col = f"target_{stat}"
        if col in ml_training_df.columns:
            baselines[stat] = pd.to_numeric(ml_training_df[col], errors="coerce").mean()
    return baselines


def _ml_year_pool_signature(yl_df):
    """Cheap signature for whether the Lahman yearly pool changed (length + year span)."""
    if yl_df is None or getattr(yl_df, "empty", True):
        return (0, 0, 0)
    ys = pd.to_numeric(yl_df["yearID"], errors="coerce").dropna()
    if ys.empty:
        return (len(yl_df), 0, 0)
    return (len(yl_df), int(ys.min()), int(ys.max()))


_ML_PROJ_SESSION_KEYS = (
    "_ml_proj_sig",
    "_ml_proj_pred_df",
    "_ml_proj_age_curve_df",
    "_ml_proj_comp_df",
    "_ml_proj_training_df",
    "_ml_proj_feature_cols",
    "_ml_proj_models",
    "_ml_proj_current_rows",
)


def _clear_ml_projection_session_cache():
    for k in _ML_PROJ_SESSION_KEYS:
        st.session_state.pop(k, None)


def _ml_projection_run_signature(yl_df, lookback, min_games, max_players, reg, age_s, comp_w, k_nei, min_ab):
    """Inputs that affect base ML + adjustment layer; used to skip redundant work on Streamlit reruns."""
    return (
        _ml_year_pool_signature(yl_df),
        int(lookback),
        int(min_games),
        int(max_players),
        float(reg),
        float(age_s),
        float(comp_w),
        int(k_nei),
        int(min_ab),
    )


@st.cache_data(show_spinner=False)
def get_age_curve_adjustments(ml_training_df, target_stats_tuple=tuple(ML_TARGET_STATS)):
    """Estimate aging effects from historical training rows."""
    target_stats = list(target_stats_tuple)
    rows = []
    if ml_training_df.empty or "age_entering_year" not in ml_training_df.columns:
        return pd.DataFrame(columns=["Stat", "Age", "Age Adjustment"])
    tmp = ml_training_df.copy()
    tmp["age_bucket"] = pd.to_numeric(tmp["age_entering_year"], errors="coerce").round().clip(18, 45)
    for stat in target_stats:
        target_col = f"target_{stat}"
        last_col = f"{stat}_last"
        if target_col not in tmp.columns or last_col not in tmp.columns:
            continue
        stat_tmp = tmp[["age_bucket", target_col, last_col]].copy()
        stat_tmp[target_col] = pd.to_numeric(stat_tmp[target_col], errors="coerce")
        stat_tmp[last_col] = pd.to_numeric(stat_tmp[last_col], errors="coerce")
        stat_tmp["delta"] = stat_tmp[target_col] - stat_tmp[last_col]
        stat_tmp = stat_tmp.dropna(subset=["age_bucket", "delta"])
        grouped = stat_tmp.groupby("age_bucket")["delta"].agg(["mean", "count"]).reset_index()
        grouped = grouped[grouped["count"] >= 10].sort_values("age_bucket")
        if grouped.empty:
            continue
        grouped["smoothed"] = grouped["mean"].rolling(window=3, min_periods=1, center=True).mean()
        for r in grouped.itertuples(index=False):
            rows.append({"Stat": stat, "Age": int(r.age_bucket), "Age Adjustment": float(r.smoothed)})
    return pd.DataFrame(rows)


def lookup_age_adjustment(age_curve_df, stat, age):
    if age_curve_df.empty or pd.isna(age):
        return 0.0
    stat_curve = age_curve_df[age_curve_df["Stat"] == stat].copy()
    if stat_curve.empty:
        return 0.0
    age = int(round(float(age)))
    stat_curve["age_distance"] = (stat_curve["Age"] - age).abs()
    return float(stat_curve.sort_values("age_distance").iloc[0]["Age Adjustment"])


@st.cache_data(show_spinner=False)
def build_base_ml_predictions(yearly_source, lookback_years, min_games_per_window, max_player_pool=300):
    """Train once, predict once, and return reusable base objects for fast UI filtering."""
    target_stats_tuple = tuple(ML_TARGET_STATS)
    ml_training_df, feature_cols = build_ml_training_set(yearly_source, lookback_years, min_games_per_window, target_stats_tuple)
    if ml_training_df.empty or not feature_cols:
        return ml_training_df, [], {}, pd.DataFrame(), pd.DataFrame()
    feature_cols_tuple = tuple(feature_cols)
    ml_models = train_random_forest_models(ml_training_df, feature_cols_tuple, target_stats_tuple)
    current_rows = build_current_prediction_rows(yearly_source, lookback_years, min_games_per_window, max_player_pool=max_player_pool)
    if current_rows.empty:
        return ml_training_df, feature_cols, ml_models, current_rows, pd.DataFrame()
    X_current = current_rows.reindex(columns=feature_cols).replace([np.inf, -np.inf], np.nan).fillna(0)
    base_pred_cols = ["playerID", "fullName", "bats", "primaryPos", "League", "primaryTeamID", "last_year", "prediction_year", "age_entering_year", "hist_G_total", "hist_AB_total"]
    last_audit_cols = [f"Last {s}" for s in ML_BASE_FEATURE_STATS if f"Last {s}" in current_rows.columns]
    pred_df = current_rows[[c for c in base_pred_cols + last_audit_cols if c in current_rows.columns]].copy()
    for stat, info in ml_models.items():
        pred_df[f"Raw ML {stat}"] = info["model"].predict(X_current)
    return ml_training_df, feature_cols, ml_models, current_rows, pred_df


@st.cache_data(show_spinner=False)
def build_similar_player_predictions(current_rows, ml_training_df, feature_cols_tuple, target_stats_tuple=tuple(ML_TARGET_STATS), k_neighbors=25, max_age_gap=3):
    """Fast nearest-neighbor comps. Excludes the target player from his own comps."""
    feature_cols = list(feature_cols_tuple)
    target_stats = list(target_stats_tuple)
    if current_rows.empty or ml_training_df.empty or not feature_cols:
        return pd.DataFrame()
    # Use a smaller, high-signal subset for similarity to avoid slow/noisy hundreds-column distances.
    preferred = [
        "age_entering_year", "age_squared", "hist_G_total", "hist_AB_total", "Park_Factor",
        "G_last", "AB_last", "HR_last", "RBI_last", "SB_last", "BB_last", "SO_last", "OPS_last", "BA_last", "OBP_last", "SLG_last",
        "BB_rate_last", "K_rate_last", "HR_rate_last", "XBH_rate_last", "Speed_Index_last",
        "HR_trend", "OPS_trend", "SB_trend", "BB_rate_trend", "K_rate_trend", "Speed_Index_trend",
    ]
    sim_cols = [c for c in preferred if c in feature_cols]
    if len(sim_cols) < 5:
        sim_cols = feature_cols[:30]
    train_X = ml_training_df.reindex(columns=sim_cols).replace([np.inf, -np.inf], np.nan).fillna(0).astype(float)
    current_X = current_rows.reindex(columns=sim_cols).replace([np.inf, -np.inf], np.nan).fillna(0).astype(float)
    means = train_X.mean(axis=0)
    stds = train_X.std(axis=0).replace(0, 1)
    train_Z = ((train_X - means) / stds).to_numpy()
    current_Z = ((current_X - means) / stds).to_numpy()
    train_ages = pd.to_numeric(ml_training_df.get("age_entering_year", np.nan), errors="coerce").to_numpy()
    current_ages = pd.to_numeric(current_rows.get("age_entering_year", np.nan), errors="coerce").to_numpy()
    train_player_ids = ml_training_df.get("playerID", pd.Series([""] * len(ml_training_df))).astype(str).to_numpy()
    out_rows = []
    current_reset = current_rows.reset_index(drop=True)
    for i, row in current_reset.iterrows():
        diff = train_Z - current_Z[i]
        distances = np.sqrt(np.einsum("ij,ij->i", diff, diff))
        age = current_ages[i] if i < len(current_ages) else np.nan
        candidate_mask = np.ones(len(distances), dtype=bool)
        if pd.notna(row.get("playerID")):
            candidate_mask &= (train_player_ids != str(row.get("playerID")))
        if pd.notna(age):
            age_mask = np.abs(train_ages - age) <= max_age_gap
            if (candidate_mask & age_mask).sum() >= max(k_neighbors, 10):
                candidate_mask &= age_mask
        candidate_idx = np.where(candidate_mask)[0]
        if len(candidate_idx) == 0:
            continue
        # Pick nearest UNIQUE comparable players. The training set can contain multiple
        # seasons for the same historical player, so a simple top-k can repeat names.
        # Keep only the closest season for each comparable player.
        sorted_candidates = candidate_idx[np.argsort(distances[candidate_idx])]
        unique_nearest = []
        seen_comp_players = set()
        target_pid = str(row.get("playerID")) if pd.notna(row.get("playerID")) else ""
        for idx in sorted_candidates:
            comp_pid = str(train_player_ids[idx]) if idx < len(train_player_ids) else ""
            if not comp_pid or comp_pid == target_pid or comp_pid in seen_comp_players:
                continue
            unique_nearest.append(idx)
            seen_comp_players.add(comp_pid)
            if len(unique_nearest) >= k_neighbors:
                break
        if not unique_nearest:
            continue
        comps = ml_training_df.iloc[unique_nearest]
        out = {
            "playerID": row.get("playerID"),
            "Similar Player Sample": len(comps),
        }
        for stat in target_stats:
            tcol = f"target_{stat}"
            if tcol in comps.columns:
                out[f"Similar {stat}"] = pd.to_numeric(comps[tcol], errors="coerce").mean()
        out_rows.append(out)
    return pd.DataFrame(out_rows)


def apply_advanced_projection_adjustments(pred_df, current_rows, ml_training_df, feature_cols, target_stats,
                                          regression_strength=0.20, age_strength=0.50, comp_weight=0.25, k_neighbors=25):
    """Blend compact RF output, similar-player comps, age curve, and regression-to-the-mean."""
    if pred_df.empty:
        return pred_df, pd.DataFrame(), pd.DataFrame()
    adjusted = pred_df.copy()
    baselines = get_target_baselines(ml_training_df, tuple(target_stats))
    age_curve_df = get_age_curve_adjustments(ml_training_df, tuple(target_stats))
    if comp_weight and comp_weight > 0:
        comp_df = build_similar_player_predictions(current_rows, ml_training_df, tuple(feature_cols), tuple(target_stats), k_neighbors=k_neighbors)
    else:
        comp_df = pd.DataFrame()
    if not comp_df.empty:
        adjusted = adjusted.merge(comp_df, on="playerID", how="left")
    else:
        adjusted["Similar Player Sample"] = np.nan
    for stat in target_stats:
        rf_col = f"Raw ML {stat}"
        final_col = f"Predicted {stat}"
        comp_col = f"Similar {stat}"
        if rf_col not in adjusted.columns:
            continue
        rf_pred = pd.to_numeric(adjusted[rf_col], errors="coerce")
        baseline = baselines.get(stat, rf_pred.mean())
        if comp_col in adjusted.columns:
            comp_pred = pd.to_numeric(adjusted[comp_col], errors="coerce")
            blended = (1 - comp_weight) * rf_pred + comp_weight * comp_pred.fillna(rf_pred)
        else:
            blended = rf_pred.copy()
        if "age_entering_year" in adjusted.columns:
            age_adj = adjusted["age_entering_year"].apply(lambda a: lookup_age_adjustment(age_curve_df, stat, a))
            blended = blended + age_strength * pd.to_numeric(age_adj, errors="coerce").fillna(0)
        recent_ab = pd.to_numeric(adjusted.get("hist_AB_total", np.nan), errors="coerce")
        reliability = (recent_ab / 1200).clip(lower=0.20, upper=1.0).fillna(0.50)
        dynamic_regression = regression_strength * (1.15 - reliability)
        final = (1 - dynamic_regression) * blended + dynamic_regression * baseline
        if stat in ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB"]:
            final = final.clip(lower=0)
        if stat in RATE_STATS:
            final = final.clip(lower=0, upper=1.5)
        adjusted[final_col] = final
    return adjusted, age_curve_df, comp_df


def make_ml_prediction_summary(row, sort_stat):
    player = row.get("Player", "This player")
    stat_val = row.get(f"Predicted {sort_stat}", np.nan)
    ops = row.get("Predicted OPS", np.nan)
    hr = row.get("Predicted HR", np.nan)
    rbi = row.get("Predicted RBI", np.nan)
    sb = row.get("Predicted SB", np.nan)
    stat_text = fmt_rate_3(stat_val) if sort_stat in RATE_STATS else fmt_int(stat_val)
    return (
        f"{player}'s advanced ML projection is strongest on {sort_stat}: {stat_text}. "
        f"The model projects about {fmt_rate_3(ops)} OPS, {fmt_int(hr)} HR, {fmt_int(rbi)} RBI, and {fmt_int(sb)} SB. "
        f"The displayed projection blends Random Forest, age/age², position, bats, league/team context, playing time, trends, similar-player history, aging curves, and regression-to-the-mean."
    )


@st.cache_data(show_spinner=False)
def aggregate_player_year_team(df):
    """One row per player-year-actual team. Used when Historical Explorer shows split seasons."""
    if df.empty:
        return df.copy()
    group_cols = [
        "playerID", "fullName", "bats", "throws", "birthYear", "birthMonth", "birthDay", "birthCountry",
        "yearID", "teamID", "teamName", "teamHistoricalName", "teamLeague", "primaryPos", "careerPrimaryPos"
    ]
    group_cols = [c for c in group_cols if c in df.columns]
    stat_cols = [c for c in ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "IBB", "HBP", "SH", "SF", "GIDP"] if c in df.columns]
    out = df.groupby(group_cols, as_index=False)[stat_cols].sum()
    out = add_rate_stats(out)
    return out


@st.cache_data(show_spinner=False)
def aggregate_player_year_primary_team(df):
    """One row per player-year, with stats combined and Team set to the primary team in the filtered data."""
    if df.empty:
        return df.copy()
    team_basis = aggregate_player_year_team(df)
    basis_col = "G" if "G" in team_basis.columns else "AB"
    primary_team = (
        team_basis.sort_values(["playerID", "yearID", basis_col, "AB"], ascending=[True, True, False, False])
        .drop_duplicates(["playerID", "yearID"])
        [["playerID", "yearID", "teamID", "teamName", "teamHistoricalName", "teamLeague"]]
        .rename(columns={"teamID": "primaryTeamID", "teamName": "primaryTeamName", "teamHistoricalName": "primaryHistoricalTeamName", "teamLeague": "primaryLeague"})
    )
    group_cols = [
        "playerID", "fullName", "bats", "throws", "birthYear", "birthMonth", "birthDay", "birthCountry", "careerPrimaryPos", "yearID"
    ]
    group_cols = [c for c in group_cols if c in df.columns]
    stat_cols = [c for c in ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "IBB", "HBP", "SH", "SF", "GIDP"] if c in df.columns]
    out = df.groupby(group_cols, as_index=False)[stat_cols].sum()
    out = add_rate_stats(out)
    out = out.merge(primary_team, on=["playerID", "yearID"], how="left")
    pos_basis = (
        df.groupby(["playerID", "yearID", "primaryPos"], as_index=False)["G"].sum()
        .sort_values(["playerID", "yearID", "G", "primaryPos"], ascending=[True, True, False, True])
        .drop_duplicates(["playerID", "yearID"])[["playerID", "yearID", "primaryPos"]]
    )
    out = out.merge(pos_basis, on=["playerID", "yearID"], how="left")
    return out


@st.cache_data(show_spinner=False)
def add_primary_team_for_career(grouped_df, source_df):
    """Attach primary team/position to player-level career totals based on most games/AB in the filtered source."""
    if grouped_df.empty or source_df.empty:
        return grouped_df
    team_basis = aggregate_player_year_team(source_df)
    team_games = (
        team_basis.groupby(["playerID", "teamName", "teamHistoricalName"], as_index=False)[["G", "AB"]]
        .sum()
        .sort_values(["playerID", "G", "AB", "teamName"], ascending=[True, False, False, True])
        .drop_duplicates("playerID")
        [["playerID", "teamName", "teamHistoricalName"]]
        .rename(columns={"teamName": "primaryTeamName", "teamHistoricalName": "primaryHistoricalTeamName"})
    )
    season_pos_basis = (
        source_df.groupby(["playerID", "primaryPos"], as_index=False)[["G", "AB"]]
        .sum()
        .sort_values(["playerID", "G", "AB", "primaryPos"], ascending=[True, False, False, True])
        .drop_duplicates("playerID")
        [["playerID", "primaryPos"]]
    )
    career_pos_basis = source_df[["playerID", "careerPrimaryPos"]].drop_duplicates("playerID") if "careerPrimaryPos" in source_df.columns else pd.DataFrame(columns=["playerID", "careerPrimaryPos"])
    return (
        grouped_df
        .merge(team_games, on="playerID", how="left")
        .merge(season_pos_basis, on="playerID", how="left")
        .merge(career_pos_basis, on="playerID", how="left")
    )

@st.cache_data(show_spinner=False)
def load_data():
    people = read_required_csv("People.csv")
    batting = read_required_csv("Batting.csv")
    fielding = read_required_csv("Fielding.csv")

    batting["teamID_original"] = batting["teamID"]
    fielding["teamID_original"] = fielding["teamID"]
    batting["teamHistoricalName"] = batting.apply(lambda r: historical_team_name(r["teamID_original"], r.get("yearID", None)), axis=1)
    fielding["teamHistoricalName"] = fielding.apply(lambda r: historical_team_name(r["teamID_original"], r.get("yearID", None)), axis=1)

    batting["teamID"] = batting["teamID"].replace(team_id_mapping)
    fielding["teamID"] = fielding["teamID"].replace(team_id_mapping)

    keep_people = ["playerID", "nameFirst", "nameLast", "birthYear", "birthMonth", "birthDay", "birthCountry", "bats", "throws"]
    keep_people = [c for c in keep_people if c in people.columns]
    people = people[keep_people].copy()
    people["nameFirst"] = people["nameFirst"].fillna("").astype(str).str.strip()
    people["nameLast"] = people["nameLast"].fillna("").astype(str).str.strip()
    people["fullName"] = (people["nameFirst"] + " " + people["nameLast"]).str.strip()

    batting_num_cols = ["yearID", "G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "IBB", "HBP", "SH", "SF", "GIDP"]
    for col in batting_num_cols:
        if col in batting.columns:
            batting[col] = pd.to_numeric(batting[col], errors="coerce").fillna(0)

    if "yearID" in fielding.columns:
        fielding["yearID"] = pd.to_numeric(fielding["yearID"], errors="coerce").fillna(0)
    if "G" in fielding.columns:
        fielding["G"] = pd.to_numeric(fielding["G"], errors="coerce").fillna(0)
    else:
        fielding["G"] = 0

    # Group LF/CF/RF together so outfielders are classified as OF instead of splitting their games.
    fielding["POS_grouped"] = fielding["POS"].replace({"LF": "OF", "CF": "OF", "RF": "OF"})
    valid_primary_positions = ["C", "1B", "2B", "3B", "SS", "OF", "P", "DH"]
    fielding_for_pos = fielding[fielding["POS_grouped"].isin(valid_primary_positions)].copy()

    fielding_counts = (
        fielding_for_pos
        .groupby(["playerID", "yearID", "POS_grouped"], as_index=False)["G"]
        .sum()
        .rename(columns={"G": "games_at_pos"})
    )
    # Season primary position: most fielding games at a grouped position in that specific season.
    primary_positions = (
        fielding_counts.sort_values(["playerID", "yearID", "games_at_pos", "POS_grouped"], ascending=[True, True, False, True])
        .drop_duplicates(subset=["playerID", "yearID"])
        [["playerID", "yearID", "POS_grouped"]]
        .rename(columns={"POS_grouped": "primaryPos"})
    )

    # Career primary position: most fielding games at a grouped position across the player's entire career.
    # This is the correct career-page position definition: it is based on Fielding.csv games, not at-bats.
    career_primary_positions = (
        fielding_for_pos
        .groupby(["playerID", "POS_grouped"], as_index=False)["G"]
        .sum()
        .rename(columns={"G": "career_games_at_pos"})
        .sort_values(["playerID", "career_games_at_pos", "POS_grouped"], ascending=[True, False, True])
        .drop_duplicates(subset=["playerID"])
        [["playerID", "POS_grouped"]]
        .rename(columns={"POS_grouped": "careerPrimaryPos"})
    )

    batting = batting.merge(people, on="playerID", how="left")
    batting = batting.merge(primary_positions, on=["playerID", "yearID"], how="left")
    batting = batting.merge(career_primary_positions, on="playerID", how="left")
    batting["primaryPos"] = batting["primaryPos"].fillna("DH")
    batting["careerPrimaryPos"] = batting["careerPrimaryPos"].fillna(batting["primaryPos"]).fillna("DH")
    batting["teamName"] = batting["teamID"].map(team_id_to_name).fillna(batting["teamID"])
    batting["teamLeague"] = batting.apply(lambda r: team_league(r["teamID"], r["yearID"]), axis=1)
    batting = add_rate_stats(batting)

    yearly = (
        batting.groupby(["playerID", "fullName", "bats", "throws", "birthYear", "birthMonth", "birthDay", "birthCountry", "careerPrimaryPos", "yearID"], as_index=False)
        [["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "IBB", "HBP", "SH", "SF", "GIDP"]]
        .sum()
    )
    yearly = add_rate_stats(yearly)

    year_team_totals = batting.groupby(["playerID", "yearID", "teamID", "teamHistoricalName", "teamLeague"], as_index=False).agg({"AB": "sum"})
    primary_teams = (
        year_team_totals.sort_values(["playerID", "yearID", "AB"], ascending=[True, True, False])
        .drop_duplicates(subset=["playerID", "yearID"])
        [["playerID", "yearID", "teamID", "teamHistoricalName", "teamLeague"]]
        .rename(columns={"teamID": "primaryTeamID", "teamHistoricalName": "primaryHistoricalTeamName", "teamLeague": "primaryLeague"})
    )
    yearly = yearly.merge(primary_teams, on=["playerID", "yearID"], how="left")
    yearly["primaryTeamName"] = yearly["primaryTeamID"].map(team_id_to_name).fillna(yearly["primaryTeamID"])
    yearly["primaryHistoricalTeamName"] = yearly["primaryHistoricalTeamName"].fillna(yearly["primaryTeamName"])
    yearly["primaryLeague"] = yearly["primaryLeague"].fillna(yearly.apply(lambda r: team_league(r["primaryTeamID"], r["yearID"]), axis=1))

    yearly_pos = batting[["playerID", "yearID", "primaryPos"]].drop_duplicates(subset=["playerID", "yearID"])
    yearly = yearly.merge(yearly_pos, on=["playerID", "yearID"], how="left")
    yearly["primaryPos"] = yearly["primaryPos"].fillna("DH")
    yearly["careerPrimaryPos"] = yearly["careerPrimaryPos"].fillna(yearly["primaryPos"]).fillna("DH")
    yearly = yearly[~yearly["primaryPos"].isin(["PH", "PR"])]

    return batting, yearly, people



def build_realistic_draft_ml_adjustments(df, fantasy_format="5x5 Roto", projection_mode="Balanced"):
    """Build a more realistic ML-style adjustment for draft pages.

    Philosophy:
    - Base fantasy projection remains the main signal.
    - ML is only a modest adjustment for breakout/risk/context.
    - Reduces multicollinearity by using category dimensions instead of repeatedly
      counting correlated HR/RBI/OPS/trend features.
    - Applies regression-to-mean, capped trends, age curve, playing-time stability,
      and simple similar-player anchoring.

    ``projection_mode`` (Conservative / Balanced / Aggressive) scales those steps via
    ``get_draft_projection_factors``; Balanced matches the original defaults.

    Optional factor keys (Aggressive may set): ``raw_adj_clip_neg`` / ``raw_adj_clip_pos``,
    ``ml_adj_clip_neg`` / ``ml_adj_clip_pos``, ``ml_residual_scale``, ``context_risk_scale``,
    ``anchor_elite_relax_quantile`` / ``anchor_elite_boost``,
    ``contextual_blend_pre_normalize`` (skip second ``normalize_series`` on contextual blend for ML residual).
    """
    out = df.copy()
    fac = get_draft_projection_factors(projection_mode)

    # Safe numeric helpers
    for c in [
        "proj_R", "proj_HR", "proj_RBI", "proj_SB", "proj_BA", "proj_OPS", "proj_BB",
        "R_trend", "HR_trend", "RBI_trend", "SB_trend", "BA_trend", "OPS_trend",
        "Age", "G", "AB"
    ]:
        if c not in out.columns:
            out[c] = np.nan
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # Optional: weight recent-season actuals more before regression (Aggressive only by default).
    w_rec = float(fac.get("recency_weight_latest", 0.0) or 0.0)
    if w_rec > 0:
        _recency_pairs = [
            ("proj_R", "latest_R"),
            ("proj_HR", "latest_HR"),
            ("proj_RBI", "latest_RBI"),
            ("proj_SB", "latest_SB"),
            ("proj_BA", "latest_BA"),
            ("proj_OPS", "latest_OPS"),
            ("proj_BB", "latest_BB"),
        ]
        for pc, lc in _recency_pairs:
            if pc in out.columns and lc in out.columns:
                pv = pd.to_numeric(out[pc], errors="coerce")
                lv = pd.to_numeric(out[lc], errors="coerce")
                out[pc] = pv * (1.0 - w_rec) + lv.fillna(pv) * w_rec

    # League/category anchors for regression-to-mean.
    med = {}
    for c in ["proj_R", "proj_HR", "proj_RBI", "proj_SB", "proj_BA", "proj_OPS", "proj_BB"]:
        med[c] = out[c].replace([np.inf, -np.inf], np.nan).median()
        if pd.isna(med[c]):
            med[c] = 0

    age = out["Age"].fillna(29)
    games = out["G"].fillna(0)
    ab = out["AB"].fillna(0)

    # Stability: high playing time means we trust the projection more.
    stability = (games / 150).clip(lower=0.20, upper=1.00)
    # Young players and low-playing-time players should be regressed more.
    reg_mult = float(fac["regression_strength_multiplier"])
    youth_bump = float(fac["youth_bump"])
    reg_min = float(fac["reg_strength_min"])
    reg_max = float(fac["reg_strength_max"])
    regression_strength = (0.35 - stability * 0.18).clip(lower=0.10, upper=0.35) * reg_mult
    regression_strength = regression_strength + np.where(age < 24, youth_bump, 0)
    regression_strength = pd.Series(regression_strength, index=out.index).clip(lower=reg_min, upper=reg_max)

    # Regression-to-mean category projections.
    for c in ["proj_R", "proj_HR", "proj_RBI", "proj_SB", "proj_BA", "proj_OPS", "proj_BB"]:
        out[f"rtm_{c}"] = out[c] * (1 - regression_strength) + med[c] * regression_strength

    # Capped trend signals avoid runaway projections.
    _hr_lo, _hr_hi = fac["trend_clip_hr"]
    _sb_lo, _sb_hi = fac["trend_clip_sb"]
    _ops_lo, _ops_hi = fac["trend_clip_ops"]
    _ba_lo, _ba_hi = fac["trend_clip_ba"]
    out["Power Trend Signal"] = normalize_series(out["HR_trend"].clip(_hr_lo, _hr_hi).fillna(0))
    out["Speed Trend Signal"] = normalize_series(out["SB_trend"].clip(_sb_lo, _sb_hi).fillna(0))
    out["Plate Skill Trend Signal"] = normalize_series(out["OPS_trend"].clip(_ops_lo, _ops_hi).fillna(0))
    out["Average Trend Signal"] = normalize_series(out["BA_trend"].clip(_ba_lo, _ba_hi).fillna(0))

    # Category dimensions reduce multicollinearity:
    # HR/RBI/OPS are not all allowed to stack as separate full-strength power features.
    power_dim = normalize_series(
        normalize_series(out["rtm_proj_HR"]) * 0.60 +
        normalize_series(out["rtm_proj_RBI"]) * 0.25 +
        normalize_series(out["rtm_proj_OPS"]) * 0.15
    )
    speed_dim = normalize_series(out["rtm_proj_SB"])
    run_context_dim = normalize_series(
        normalize_series(out["rtm_proj_R"]) * 0.55 +
        normalize_series(out["rtm_proj_RBI"]) * 0.25 +
        normalize_series(out["rtm_proj_OPS"]) * 0.20
    )
    bat_quality_dim = normalize_series(
        normalize_series(out["rtm_proj_BA"]) * 0.50 +
        normalize_series(out["rtm_proj_OPS"]) * 0.50
    )

    # Age curve / breakout and decline context.
    age_curve = 1 - (abs(age - 28) / 18)
    age_curve = pd.Series(age_curve, index=out.index).clip(lower=0.55, upper=1.05)
    prime_age_signal = normalize_series(age_curve)

    young_breakout_signal = (
        ((age >= 22) & (age <= 25)).astype(float) * 0.50 +
        (out["Power Trend Signal"] * 0.25) +
        (out["Plate Skill Trend Signal"] * 0.25)
    )
    young_breakout_signal = normalize_series(young_breakout_signal)

    decline_risk_signal = (
        ((age >= 33).astype(float) * 0.45) +
        ((games < 100).astype(float) * 0.25) +
        normalize_series((-out["Plate Skill Trend Signal"]).clip(lower=0)) * 0.30
    )
    decline_risk_signal = normalize_series(decline_risk_signal)

    playing_time_signal = normalize_series(games.fillna(0))

    # Similar-player anchor: group players by age band and position; partially pull toward
    # similar-player expected value rather than letting raw categories explode.
    pos = out.get("Primary Position", pd.Series("DH", index=out.index)).fillna("DH").astype(str)
    age_band = pd.cut(age.fillna(29), bins=[0, 24, 27, 30, 33, 60], labels=["Young", "Growth", "Prime", "LatePrime", "Veteran"])
    out["_sim_group"] = pos + "_" + age_band.astype(str)

    if fantasy_format == "5x5 Roto":
        base_category_score = normalize_series(
            normalize_series(out["rtm_proj_R"]) * 0.20 +
            normalize_series(out["rtm_proj_HR"]) * 0.20 +
            normalize_series(out["rtm_proj_RBI"]) * 0.20 +
            normalize_series(out["rtm_proj_SB"]) * 0.20 +
            normalize_series(out["rtm_proj_BA"]) * 0.20
        )
    else:
        base_category_score = normalize_series(
            out["rtm_proj_HR"] * 4 +
            out["rtm_proj_RBI"] +
            out["rtm_proj_R"] +
            out["rtm_proj_SB"] * 2 +
            out["rtm_proj_BB"] +
            out["rtm_proj_OPS"] * 20
        )

    group_anchor = out.assign(_base_category_score=base_category_score).groupby("_sim_group")["_base_category_score"].transform("median")
    group_anchor = group_anchor.fillna(base_category_score.median())

    # Similar-player adjusted baseline: mostly player projection, modest similar-player pull.
    apw = float(fac["anchor_player_weight"])
    bcs_num = pd.to_numeric(base_category_score, errors="coerce").fillna(0.0)
    elite_q = fac.get("anchor_elite_relax_quantile")
    elite_boost = float(fac.get("anchor_elite_boost", 0.0) or 0.0)
    if elite_q is not None and float(elite_q) > 0 and elite_boost > 0:
        thr = float(bcs_num.quantile(float(elite_q)))
        apw_eff = np.where(bcs_num >= thr, np.minimum(0.985, apw + elite_boost), apw)
        similar_player_adjusted = normalize_series(
            base_category_score * apw_eff + group_anchor * (1.0 - apw_eff)
        )
    else:
        similar_player_adjusted = normalize_series(
            base_category_score * apw + group_anchor * (1.0 - apw)
        )

    # ML is now contextual adjustment, not the whole projection.
    # Trend/breakout/risk are deliberately modest so power does not get counted 4 times.
    bw = fac["breakout_weights"]
    breakout_probability = normalize_series(
        young_breakout_signal * bw[0] +
        out["Power Trend Signal"] * bw[1] +
        out["Speed Trend Signal"] * bw[2] +
        out["Plate Skill Trend Signal"] * bw[3] +
        playing_time_signal * bw[4]
    )
    risk_score = normalize_series(
        decline_risk_signal * 0.45 +
        (1 - playing_time_signal) * 0.30 +
        (1 - prime_age_signal) * 0.25
    )

    category_balance = normalize_series(
        power_dim * 0.25 +
        speed_dim * 0.25 +
        run_context_dim * 0.25 +
        bat_quality_dim * 0.25
    )

    cw = fac["context_weights"]
    risk_scale = float(fac.get("context_risk_scale", 1.0) or 1.0)
    _ctx_blend = (
        similar_player_adjusted * cw[0] +
        category_balance * cw[1] +
        breakout_probability * cw[2] -
        risk_score * cw[3] * risk_scale
    )
    # Balanced / Conservative: second min–max on the blend (legacy). Aggressive: raw blend vs anchor
    # preserves tail spread so ML residual is not over-compressed for elites/breakouts.
    if fac.get("contextual_blend_pre_normalize"):
        contextual_ml_score = _ctx_blend
    else:
        contextual_ml_score = normalize_series(_ctx_blend)

    # ML adjustment is intentionally small (clip size varies by projection style).
    raw_lim = float(fac["raw_adj_clip"])
    raw_lo = float(fac.get("raw_adj_clip_neg", -raw_lim))
    raw_hi = float(fac.get("raw_adj_clip_pos", raw_lim))
    ml_lim = float(fac["ml_adj_clip"])
    ml_lo = float(fac.get("ml_adj_clip_neg", -ml_lim))
    ml_hi = float(fac.get("ml_adj_clip_pos", ml_lim))
    res_scale = float(fac.get("ml_residual_scale", 1.0) or 1.0)
    raw_adjustment = (contextual_ml_score - similar_player_adjusted) * res_scale
    raw_adjustment = raw_adjustment.clip(raw_lo, raw_hi)
    out["ML Adjustment"] = raw_adjustment.clip(ml_lo, ml_hi)
    out["Breakout Probability"] = breakout_probability
    out["Risk Score"] = risk_score
    out["Similar Player Anchor"] = group_anchor
    out["ML Projection Score"] = normalize_series(contextual_ml_score)

    # Final expected value: realistic baseline first, small ML boost/downgrade second.
    out["Realistic Base Projection Score"] = similar_player_adjusted
    out["Expected Fantasy Value"] = normalize_series(
        similar_player_adjusted * (1 + out["ML Adjustment"])
    )

    return out




def compute_team_aware_draft_room_fit(
    available_df,
    my_team_df,
    fantasy_format="5x5 Roto"
):
    """Team-aware recommendation engine for Draft Room Simulator."""

    out = available_df.copy()

    if my_team_df is None or len(my_team_df) == 0:
        out["Team Need Score"] = 0.50
        out["Position Need Score"] = 0.50
        out["Category Fit Score"] = 0.50
        out["Roster Balance Score"] = 0.50
        out["Team Aware Draft Fit"] = normalize_series(
            pd.to_numeric(out["Draft Fit Score"], errors="coerce").fillna(0)
        )
        return out

    roster = my_team_df.copy()

    needed_positions = {
        "C": 1,
        "1B": 1,
        "2B": 1,
        "3B": 1,
        "SS": 1,
        "OF": 3,
        "DH": 1,
    }

    current_pos_counts = (
        roster["Primary Position"]
        .fillna("DH")
        .astype(str)
        .value_counts()
        .to_dict()
    )

    def calc_position_need(pos):
        pos = str(pos)
        needed = needed_positions.get(pos, 1)
        current = current_pos_counts.get(pos, 0)

        if current < needed:
            return 1.00
        elif current == needed:
            return 0.60
        elif current == needed + 1:
            return 0.35
        else:
            return 0.15

    out["Position Need Score"] = out["Primary Position"].apply(calc_position_need)

    roster_hr = pd.to_numeric(roster.get("proj_HR", 0), errors="coerce").fillna(0).mean()
    roster_sb = pd.to_numeric(roster.get("proj_SB", 0), errors="coerce").fillna(0).mean()
    roster_ba = pd.to_numeric(roster.get("proj_BA", 0), errors="coerce").fillna(0).mean()
    roster_r = pd.to_numeric(roster.get("proj_R", 0), errors="coerce").fillna(0).mean()
    roster_rbi = pd.to_numeric(roster.get("proj_RBI", 0), errors="coerce").fillna(0).mean()

    league_hr = pd.to_numeric(out.get("proj_HR", 0), errors="coerce").fillna(0).median()
    league_sb = pd.to_numeric(out.get("proj_SB", 0), errors="coerce").fillna(0).median()
    league_ba = pd.to_numeric(out.get("proj_BA", 0), errors="coerce").fillna(0).median()
    league_r = pd.to_numeric(out.get("proj_R", 0), errors="coerce").fillna(0).median()
    league_rbi = pd.to_numeric(out.get("proj_RBI", 0), errors="coerce").fillna(0).median()

    power_need = max(0, league_hr - roster_hr)
    speed_need = max(0, league_sb - roster_sb)
    avg_need = max(0, league_ba - roster_ba)
    runs_need = max(0, league_r - roster_r)
    rbi_need = max(0, league_rbi - roster_rbi)

    out["Category Fit Score"] = normalize_series(
        normalize_series(out["proj_HR"]) * (0.15 + power_need * 0.20) +
        normalize_series(out["proj_SB"]) * (0.15 + speed_need * 0.20) +
        normalize_series(out["proj_BA"]) * (0.15 + avg_need * 4.0) +
        normalize_series(out["proj_R"]) * (0.15 + runs_need * 0.12) +
        normalize_series(out["proj_RBI"]) * (0.15 + rbi_need * 0.12)
    )

    power_heavy = roster_hr > (league_hr * 1.30)
    speed_heavy = roster_sb > (league_sb * 1.30)

    roster_balance = []
    for _, r in out.iterrows():
        bal = 0.50

        if power_heavy and r.get("proj_HR", 0) < league_hr:
            bal += 0.20

        if speed_heavy and r.get("proj_SB", 0) < league_sb:
            bal += 0.20

        if not power_heavy and r.get("proj_HR", 0) > league_hr:
            bal += 0.15

        if not speed_heavy and r.get("proj_SB", 0) > league_sb:
            bal += 0.15

        roster_balance.append(bal)

    out["Roster Balance Score"] = normalize_series(pd.Series(roster_balance, index=out.index))

    out["Team Need Score"] = normalize_series(
        out["Category Fit Score"] * 0.50 +
        out["Position Need Score"] * 0.30 +
        out["Roster Balance Score"] * 0.20
    )

    out["Team Aware Draft Fit"] = normalize_series(
        normalize_series(pd.to_numeric(out["Draft Fit Score"], errors="coerce").fillna(0)) * 0.55 +
        normalize_series(pd.to_numeric(out["Expected Fantasy Value"], errors="coerce").fillna(0)) * 0.20 +
        normalize_series(out["Team Need Score"]) * 0.25
    )

    return out




def build_draft_room_roster_view(draft_results, fantasy_team):
    """Create a lineup-style roster view for a selected fantasy team in Draft Room."""
    if draft_results is None or draft_results.empty:
        return pd.DataFrame()

    team_df = draft_results[
        (draft_results["Team"] == fantasy_team) &
        (draft_results["Player"].astype(str).str.strip() != "")
    ].copy()

    if team_df.empty:
        return pd.DataFrame()

    slot_counts = {}
    roster_rows = []
    for _, r in team_df.sort_values(["Primary Position", "Pick"]).iterrows():
        pos = str(r.get("Primary Position", "DH"))
        slot_counts[pos] = slot_counts.get(pos, 0) + 1
        slot = f"{pos}{slot_counts[pos]}"

        roster_rows.append({
            "Roster Slot": slot,
            "Player": r.get("Player", ""),
            "Primary Position": pos,
            "MLB Team": r.get("MLB Team", ""),
            "Pick": r.get("Pick", np.nan),
            "Market Rank": r.get("Market Rank", np.nan),
            "Model Rank": r.get("Model Rank", np.nan),
            "Fantasy Edge": r.get("Fantasy Edge", np.nan),
            "Draft Fit Score": r.get("Draft Fit Score", np.nan),
            "ML Projection Score": r.get("ML Projection Score", np.nan),
            "Expected Fantasy Value": r.get("Expected Fantasy Value", np.nan),
            "Projected HR": r.get("proj_HR", np.nan),
            "Projected RBI": r.get("proj_RBI", np.nan),
            "Projected R": r.get("proj_R", np.nan),
            "Projected SB": r.get("proj_SB", np.nan),
            "Projected BA": r.get("proj_BA", np.nan),
            "Projected OPS": r.get("proj_OPS", np.nan),
        })

    roster_view = pd.DataFrame(roster_rows)

    if "Roster Slot" in roster_view.columns:
        def slot_sort_key(slot):
            s = str(slot)
            pos = "".join([ch for ch in s if not ch.isdigit()])
            num = "".join([ch for ch in s if ch.isdigit()])
            base = POSITION_ORDER.index(pos) if pos in POSITION_ORDER else 999
            return base * 100 + (int(num) if num else 0)

        roster_view["_slot_sort"] = roster_view["Roster Slot"].apply(slot_sort_key)
        roster_view = roster_view.sort_values("_slot_sort").drop(columns=["_slot_sort"])

    return roster_view




def normalize_uploaded_stat_columns(df):
    """Normalize common uploaded 2026 stat column names for fantasy standings/trades."""
    out = df.copy()
    rename_map = {}
    for c in out.columns:
        lc = str(c).strip().lower()
        if lc in ["name", "player name", "player_name", "full name", "fullname"]:
            rename_map[c] = "Player"
        elif lc in ["team", "mlb team", "tm"]:
            rename_map[c] = "MLB Team"
        elif lc in ["pos", "position", "primary position", "primary_position"]:
            rename_map[c] = "Primary Position"
        elif lc in ["hr", "home runs", "homeruns", "home_runs"]:
            rename_map[c] = "HR"
        elif lc in ["rbi", "rbis"]:
            rename_map[c] = "RBI"
        elif lc in ["r", "runs", "run"]:
            rename_map[c] = "R"
        elif lc in ["sb", "stolen bases", "stolen_bases"]:
            rename_map[c] = "SB"
        elif lc in ["ba", "avg", "batting average", "batting_average"]:
            rename_map[c] = "BA"
        elif lc in ["obp"]:
            rename_map[c] = "OBP"
        elif lc in ["slg"]:
            rename_map[c] = "SLG"
        elif lc in ["ops"]:
            rename_map[c] = "OPS"
        elif lc in ["ab", "at bats", "at_bats"]:
            rename_map[c] = "AB"
        elif lc in ["h", "hits"]:
            rename_map[c] = "H"
        elif lc in ["bb", "walks"]:
            rename_map[c] = "BB"
    out = out.rename(columns=rename_map)
    if "Player" not in out.columns and "fullName" in out.columns:
        out = out.rename(columns={"fullName": "Player"})
    if "Player" in out.columns:
        out["Player Key"] = out["Player"].apply(normalize_player_name_for_merge)
    for c in ["HR", "RBI", "R", "SB", "BA", "OBP", "SLG", "OPS", "AB", "H", "BB"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out






def format_post_draft_roster_grades(df):
    """Format Draft Room post-draft roster grades cleanly."""
    out = df.copy()

    def fmt_trim(v, decimals):
        try:
            if pd.isna(v):
                return ""
            s = f"{float(v):.{decimals}f}".rstrip("0").rstrip(".")
            if s == "-0":
                s = "0"
            if s.startswith("."):
                s = "0" + s
            if s.startswith("-."):
                s = s.replace("-.", "-0.", 1)
            return s
        except Exception:
            return v

    # Projection totals: one decimal, no trailing zeros.
    for c in ["Total HR Projection", "Total RBI Projection", "Total R Projection", "Total SB Projection"]:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_trim(v, 1))

    # Rate stats: four decimals, no trailing zeros.
    for c in ["Average OPS Projection", "Average BA Projection"]:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_trim(v, 4))

    # Average fantasy edge: two decimals, no trailing zeros.
    if "Average Fantasy Edge" in out.columns:
        out["Average Fantasy Edge"] = out["Average Fantasy Edge"].apply(lambda v: fmt_trim(v, 2))

    # Overall score and rank as integers.
    for c in ["Overall Draft Grade Score", "Draft Room Rank", "Players Drafted"]:
        if c in out.columns:
            try:
                out[c] = pd.to_numeric(out[c], errors="coerce").round(0).astype("Int64")
            except Exception:
                out[c] = out[c].apply(lambda v: fmt_trim(v, 0))

    return out


def format_fantasy_standings_table(df):
    """Format Fantasy Standings Tracker output cleanly."""
    out = df.copy()

    # Four decimals for rate stats, remove trailing zeros.
    for c in ["Average BA", "Average OPS", "BA", "OPS", "OBP", "SLG"]:
        if c in out.columns:
            def _fmt_rate(v):
                try:
                    if pd.isna(v):
                        return ""
                    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
                    if s.startswith("."):
                        s = "0" + s
                    if s.startswith("-."):
                        s = s.replace("-.", "-0.", 1)
                    return s
                except Exception:
                    return v
            out[c] = out[c].apply(_fmt_rate)

    # Integer columns: totals, roto points, estimated points, league rank.
    for c in out.columns:
        c_text = str(c)
        if (
            c_text.startswith("Total ")
            or c_text.endswith(" Points")
            or c_text in ["League Rank", "Players", "Estimated Points"]
        ):
            try:
                out[c] = pd.to_numeric(out[c], errors="coerce").round(0).astype("Int64")
            except Exception:
                pass

    return out


def score_fantasy_rosters_from_stats(roster_df, scoring_format="5x5 Roto"):
    """Score drafted teams using uploaded/current stats."""
    df = roster_df.copy()
    for c in ["HR", "RBI", "R", "SB", "BA", "OPS", "OBP", "SLG"]:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")

    team_rows = []
    for team, g in df.groupby("Team"):
        row = {
            "Fantasy Team": team,
            "Players": g["Player"].nunique(),
            "Total HR": g["HR"].sum(),
            "Total RBI": g["RBI"].sum(),
            "Total R": g["R"].sum(),
            "Total SB": g["SB"].sum(),
            "Average BA": g["BA"].mean(),
            "Average OPS": g["OPS"].mean(),
        }
        team_rows.append(row)

    standings = pd.DataFrame(team_rows)
    if standings.empty:
        return standings

    if scoring_format == "5x5 Roto":
        categories = ["Total HR", "Total RBI", "Total R", "Total SB", "Average BA"]
        for cat in categories:
            standings[f"{cat} Points"] = standings[cat].rank(ascending=True, method="min")
        standings["Total Roto Points"] = standings[[f"{c} Points" for c in categories]].sum(axis=1)
        standings["League Rank"] = standings["Total Roto Points"].rank(ascending=False, method="min")
        standings = standings.sort_values(["League Rank", "Fantasy Team"])
    else:
        standings["Estimated Points"] = (
            standings["Total HR"] * 4 +
            standings["Total RBI"] +
            standings["Total R"] +
            standings["Total SB"] * 2 +
            standings["Average OPS"].fillna(0) * 25
        )
        standings["League Rank"] = standings["Estimated Points"].rank(ascending=False, method="min")
        standings = standings.sort_values(["League Rank", "Fantasy Team"])

    return standings


def summarize_team_category_needs(standings, team_name):
    if standings is None or standings.empty or team_name not in standings["Fantasy Team"].values:
        return {}
    row = standings[standings["Fantasy Team"] == team_name].iloc[0]
    needs = {}
    category_map = {
        "HR": "Total HR",
        "RBI": "Total RBI",
        "R": "Total R",
        "SB": "Total SB",
        "BA": "Average BA",
        "OPS": "Average OPS",
    }
    for label, col in category_map.items():
        if col in standings.columns:
            rank = standings[col].rank(ascending=False, method="min")[row.name]
            if rank > max(1, len(standings) / 2):
                needs[label] = True
    return needs








def plot_single_player_multi_stat_dashboard(player_df, player_name, stats, mode="Actual Values", smooth_window=3):
    """Create separate trend charts for one player across multiple stats."""
    player_df = player_df.sort_values("yearID").copy()
    player_df = safe_round_rate_stats(player_df)

    for stat in stats:
        if stat not in player_df.columns:
            continue

        y = pd.to_numeric(player_df[stat], errors="coerce")
        if y.notna().sum() == 0:
            continue

        if mode == "Smoothed Moving Average":
            y_plot = y.rolling(window=int(smooth_window), min_periods=1).mean()
        else:
            y_plot = y

        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(player_df["yearID"], y_plot, marker="o", label=f"{stat} — {mode}")
        trend_years = sorted(pd.to_numeric(player_df["yearID"], errors="coerce").dropna().astype(int).unique())
        ax.set_xticks(trend_years)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel("Year")
        ax.set_ylabel(stat)
        ax.set_title(f"{player_name} — {stat} Trend")
        ax.legend()
        ax.grid(True, alpha=0.3)
        try:
            st.pyplot(fig, clear_figure=True)
        except TypeError:
            st.pyplot(fig)
        plt.close(fig)


def build_lineup_assistant_scores(roster_stats, scoring_format="5x5 Roto", custom_weights=None):
    """Create start/sit style scores from current roster stats.

    Uses current-season stat columns when available. If the Fantasy Standings Tracker
    has already loaded MLB API/current stats, this page reuses that data.
    """
    df = roster_stats.copy()
    if df.empty:
        return df

    for c in ["HR", "RBI", "R", "SB", "BA", "OBP", "SLG", "OPS", "AB", "H", "BB", "G"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Core current production signals.
    if scoring_format == "Points League":
        if custom_weights is None:
            custom_weights = {"R": 1.0, "RBI": 1.0, "HR": 4.0, "SB": 2.0, "H": 1.0, "BB": 1.0, "OPS": 10.0}
        raw_score = pd.Series(0.0, index=df.index)
        for stat, weight in custom_weights.items():
            if stat in df.columns:
                raw_score += pd.to_numeric(df[stat], errors="coerce").fillna(0) * float(weight)
        df["Current Fantasy Score"] = normalize_series(raw_score)
    else:
        parts = []
        for c in ["R", "HR", "RBI", "SB", "BA", "OPS"]:
            if c in df.columns:
                parts.append(normalize_series(pd.to_numeric(df[c], errors="coerce")))
        df["Current Fantasy Score"] = sum(parts) / len(parts) if parts else 0.0

    # Momentum proxy: current rates + power/speed blend. This is a season-to-date proxy,
    # not true last-7-day game logs unless such data is uploaded later.
    momentum_parts = []
    for c, w in [("OPS", 0.35), ("HR", 0.20), ("RBI", 0.15), ("R", 0.15), ("SB", 0.10), ("BA", 0.05)]:
        if c in df.columns:
            momentum_parts.append(normalize_series(pd.to_numeric(df[c], errors="coerce")) * w)
    df["Momentum Score"] = sum(momentum_parts) if momentum_parts else df["Current Fantasy Score"]

    # Consistency proxy: rate stability and playing-time volume.
    volume = normalize_series(pd.to_numeric(df.get("AB", 0), errors="coerce")) if "AB" in df.columns else pd.Series(0.5, index=df.index)
    rate_floor = normalize_series(pd.to_numeric(df.get("OPS", df.get("BA", 0)), errors="coerce"))
    df["Consistency Score"] = normalize_series(volume * 0.55 + rate_floor * 0.45)

    # Volatility proxy: power/speed profiles can win weeks but are less stable than contact/volume.
    power_speed = pd.Series(0.0, index=df.index)
    if "HR" in df.columns:
        power_speed += normalize_series(df["HR"]) * 0.55
    if "SB" in df.columns:
        power_speed += normalize_series(df["SB"]) * 0.35
    if "BA" in df.columns:
        power_speed -= normalize_series(df["BA"]) * 0.10
    df["Volatility Meter"] = normalize_series(power_speed)

    df["Lineup Confidence"] = normalize_series(
        df["Current Fantasy Score"] * 0.45 +
        df["Momentum Score"] * 0.30 +
        df["Consistency Score"] * 0.25
    )

    def classify_action(row):
        conf = pd.to_numeric(row.get("Lineup Confidence", np.nan), errors="coerce")
        mom = pd.to_numeric(row.get("Momentum Score", np.nan), errors="coerce")
        vol = pd.to_numeric(row.get("Volatility Meter", np.nan), errors="coerce")
        if pd.isna(conf):
            return "Watch"
        if conf >= 0.72:
            return "Start"
        if conf >= 0.55 and mom >= 0.55:
            return "Lean Start"
        if conf < 0.35 and vol >= 0.55:
            return "Bench / Risk"
        if conf < 0.40:
            return "Sit"
        return "Matchup Dependent"

    def make_lineup_reason(row):
        name = row.get("Player", row.get("fullName", "This player"))
        action = row.get("Start/Sit Recommendation", "Watch")
        reasons = []
        if pd.to_numeric(row.get("Momentum Score", np.nan), errors="coerce") >= 0.70:
            reasons.append("strong current momentum")
        if pd.to_numeric(row.get("Consistency Score", np.nan), errors="coerce") >= 0.70:
            reasons.append("stable volume/rate profile")
        if pd.to_numeric(row.get("Volatility Meter", np.nan), errors="coerce") >= 0.70:
            reasons.append("higher volatility/upside profile")
        if "OPS" in row and pd.to_numeric(row.get("OPS"), errors="coerce") >= 0.800:
            reasons.append("strong OPS foundation")
        if "HR" in row and pd.to_numeric(row.get("HR"), errors="coerce") >= 10:
            reasons.append("useful power production")
        if "SB" in row and pd.to_numeric(row.get("SB"), errors="coerce") >= 8:
            reasons.append("speed contribution")
        if not reasons:
            reasons.append("middle-tier current profile")
        return f"{action}: {name} is rated this way because of " + ", ".join(reasons[:3]) + "."

    df["Start/Sit Recommendation"] = df.apply(classify_action, axis=1)
    df["Lineup Reason"] = df.apply(make_lineup_reason, axis=1)

    return df


def format_lineup_assistant_table(df):
    out = df.copy()
    for c in ["Current Fantasy Score", "Momentum Score", "Consistency Score", "Volatility Meter", "Lineup Confidence"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").round(4)
    for c in ["BA", "OBP", "SLG", "OPS"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").map(lambda v: "" if pd.isna(v) else f"{v:.4f}".rstrip("0").rstrip("."))
    for c in ["HR", "RBI", "R", "SB", "AB", "H", "BB", "G"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").round(0).astype("Int64")
    return out


def format_trade_eval_table(df):
    """Format Trade Analyzer category comparison."""
    out = df.copy()

    def fmt_trim(v, decimals):
        try:
            if pd.isna(v):
                return ""
            s = f"{float(v):.{decimals}f}".rstrip("0").rstrip(".")
            if s == "-0":
                s = "0"
            if s.startswith("."):
                s = "0" + s
            if s.startswith("-."):
                s = s.replace("-.", "-0.", 1)
            return s
        except Exception:
            return v

    if "Category" not in out.columns:
        return out

    for col in ["Give Away", "Receive", "Net Gain"]:
        if col in out.columns:
            out[col] = out.apply(
                lambda r: fmt_trim(r[col], 4) if str(r["Category"]).upper() in ["BA", "OPS", "OBP", "SLG"] else fmt_trim(r[col], 1),
                axis=1
            )
    return out


def evaluate_trade(my_give, my_get, my_roster, all_rosters, standings, my_team):
    """Evaluate a proposed fantasy trade from the user's perspective."""
    give_df = all_rosters[all_rosters["Player"].isin(my_give)].copy()
    get_df = all_rosters[all_rosters["Player"].isin(my_get)].copy()

    cats = ["HR", "RBI", "R", "SB", "BA", "OPS"]
    rows = []
    for cat in cats:
        give_val = pd.to_numeric(give_df.get(cat, pd.Series(dtype=float)), errors="coerce").mean() if cat in ["BA", "OPS"] else pd.to_numeric(give_df.get(cat, pd.Series(dtype=float)), errors="coerce").sum()
        get_val = pd.to_numeric(get_df.get(cat, pd.Series(dtype=float)), errors="coerce").mean() if cat in ["BA", "OPS"] else pd.to_numeric(get_df.get(cat, pd.Series(dtype=float)), errors="coerce").sum()
        rows.append({"Category": cat, "Give Away": give_val, "Receive": get_val, "Net Gain": get_val - give_val})

    trade_df = pd.DataFrame(rows)
    needs = summarize_team_category_needs(standings, my_team)
    weighted_gain = 0
    for _, r in trade_df.iterrows():
        weight = 1.5 if needs.get(r["Category"], False) else 1.0
        weighted_gain += r["Net Gain"] * weight

    verdict = "Neutral"
    if weighted_gain > 2:
        verdict = "Good for your team"
    elif weighted_gain < -2:
        verdict = "Bad for your team"

    return trade_df, verdict, weighted_gain


def suggest_trade_targets(my_team, target_team, all_rosters, standings):
    """Suggest simple one-for-one trades that address the user's weak categories."""
    if all_rosters.empty:
        return pd.DataFrame()

    needs = summarize_team_category_needs(standings, my_team)
    my_players = all_rosters[all_rosters["Team"] == my_team].copy()
    other_players = all_rosters[all_rosters["Team"] == target_team].copy()

    if my_players.empty or other_players.empty:
        return pd.DataFrame()

    suggestions = []
    for _, mine in my_players.iterrows():
        for _, theirs in other_players.iterrows():
            fit_gain = 0
            reason_parts = []
            for cat in ["HR", "RBI", "R", "SB", "BA", "OPS"]:
                mv = pd.to_numeric(mine.get(cat), errors="coerce")
                tv = pd.to_numeric(theirs.get(cat), errors="coerce")
                if pd.isna(mv) or pd.isna(tv):
                    continue
                diff = tv - mv
                if needs.get(cat, False) and diff > 0:
                    fit_gain += diff * (5 if cat in ["BA", "OPS"] else 1)
                    reason_parts.append(f"helps {cat}")
                elif diff < 0:
                    fit_gain += diff * 0.25

            # fairness proxy: projected/current fantasy value, if available
            mine_val = pd.to_numeric(mine.get("Expected Fantasy Value", np.nan), errors="coerce")
            theirs_val = pd.to_numeric(theirs.get("Expected Fantasy Value", np.nan), errors="coerce")
            fairness_gap = theirs_val - mine_val if pd.notna(mine_val) and pd.notna(theirs_val) else np.nan
            if pd.notna(fairness_gap):
                fit_gain -= abs(fairness_gap) * 0.15

            if fit_gain > 0:
                suggestions.append({
                    "Give": mine.get("Player"),
                    "Receive": theirs.get("Player"),
                    "Other Team": target_team,
                    "Trade Fit Score": fit_gain,
                    "Fairness Gap": fairness_gap,
                    "Why It Helps": ", ".join(reason_parts[:4]) if reason_parts else "improves category balance"
                })

    out = pd.DataFrame(suggestions)
    if not out.empty:
        out = out.sort_values("Trade Fit Score", ascending=False).head(20)
    return out




def normalize_imported_draft_columns(df):
    """Normalize uploaded draft board columns into Round/Pick/Team/Player."""
    out = df.copy()
    rename_map = {}
    for c in out.columns:
        lc = str(c).strip().lower()
        if lc in ["team", "owner", "fantasy team", "fantasy_team", "manager"]:
            rename_map[c] = "Team"
        elif lc in ["player", "name", "player name", "player_name", "full name", "fullname"]:
            rename_map[c] = "Player"
        elif lc in ["round", "rd"]:
            rename_map[c] = "Round"
        elif lc in ["pick", "pick number", "pick_number", "overall pick", "overall_pick"]:
            rename_map[c] = "Pick"
    out = out.rename(columns=rename_map)
    if "Team" not in out.columns:
        out["Team"] = ""
    if "Player" not in out.columns:
        out["Player"] = ""
    out["Team"] = out["Team"].astype(str).str.strip()
    out["Player"] = out["Player"].astype(str).str.strip()
    out = out[(out["Team"] != "") & (out["Player"] != "")].copy()
    if "Pick" not in out.columns:
        out["Pick"] = range(1, len(out) + 1)
    out["Pick"] = pd.to_numeric(out["Pick"], errors="coerce")
    out = out.sort_values("Pick", na_position="last").reset_index(drop=True)
    out["Pick"] = range(1, len(out) + 1)
    if "Round" not in out.columns:
        team_count = max(1, out["Team"].nunique())
        out["Round"] = ((out["Pick"] - 1) // team_count) + 1
    out["Round"] = pd.to_numeric(out["Round"], errors="coerce").fillna(1).astype(int)
    return out[["Round", "Pick", "Team", "Player"]]


def read_imported_draft_file(uploaded_file):
    """Read uploaded draft CSV or Excel."""
    name = str(getattr(uploaded_file, "name", "")).lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)




@st.cache_data(ttl=60 * 60 * 6)
def fetch_mlb_api_hitter_stats(season=2026):
    """Fetch current-season MLB hitter stats from the public MLB Stats API.

    Uses MLB's public stats endpoint. Returns a normalized dataframe with:
    Player, HR, RBI, R, SB, BA, OBP, SLG, OPS, AB, H, BB.
    """
    import requests

    url = "https://statsapi.mlb.com/api/v1/stats"
    params = {
        "stats": "season",
        "group": "hitting",
        "playerPool": "ALL",
        "season": int(season),
        "sportIds": 1,
        "limit": 5000,
        "hydrate": "person"
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        raise RuntimeError(f"Could not fetch MLB API stats: {e}")

    rows = []
    for split in payload.get("stats", [{}])[0].get("splits", []):
        player = split.get("player", {}) or {}
        stat = split.get("stat", {}) or {}
        rows.append({
            "Player": player.get("fullName", ""),
            "Player Key": normalize_player_name_for_merge(player.get("fullName", "")),
            "MLBAM ID": player.get("id", None),
            "MLB Team": (split.get("team", {}) or {}).get("name", ""),
            "Primary Position": (player.get("primaryPosition", {}) or {}).get("abbreviation", ""),
            "G": stat.get("gamesPlayed", np.nan),
            "AB": stat.get("atBats", np.nan),
            "H": stat.get("hits", np.nan),
            "2B": stat.get("doubles", np.nan),
            "3B": stat.get("triples", np.nan),
            "HR": stat.get("homeRuns", np.nan),
            "RBI": stat.get("rbi", np.nan),
            "R": stat.get("runs", np.nan),
            "SB": stat.get("stolenBases", np.nan),
            "BB": stat.get("baseOnBalls", np.nan),
            "BA": stat.get("avg", np.nan),
            "OBP": stat.get("obp", np.nan),
            "SLG": stat.get("slg", np.nan),
            "OPS": stat.get("ops", np.nan),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for c in ["G", "AB", "H", "2B", "3B", "HR", "RBI", "R", "SB", "BB", "BA", "OBP", "SLG", "OPS"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Map MLB position abbreviations for fantasy pages.
    if "Primary Position" in df.columns:
        df["Primary Position"] = df["Primary Position"].replace({
            "LF": "OF", "CF": "OF", "RF": "OF",
            "RF/LF": "OF", "OF": "OF",
            "TWP": "DH", "PH": "DH", "PR": "DH"
        }).fillna("DH")

    return df








def build_clean_player_label_map_from_ids(df):
    """Clean name-only labels for player dropdowns; duplicates get career span, not playerID."""
    base = df[["playerID", "fullName", "yearID"]].dropna(subset=["playerID", "fullName"]).copy()
    base["yearID"] = pd.to_numeric(base["yearID"], errors="coerce")
    spans = base.groupby(["playerID", "fullName"], as_index=False)["yearID"].agg(["min", "max"]).reset_index()
    counts = spans["fullName"].value_counts().to_dict()
    label_map = {}
    for _, r in spans.sort_values(["fullName", "min"]).iterrows():
        name = str(r["fullName"])
        if counts.get(name, 0) > 1 and pd.notna(r["min"]) and pd.notna(r["max"]):
            label = f"{name} ({int(r['min'])}-{int(r['max'])})"
        else:
            label = name
        label_map[label] = r["playerID"]
    return label_map






def add_player_to_queue(player_name):
    player_name = str(player_name).strip()
    if not player_name:
        return "No player selected."
    q = st.session_state.get("draft_queue", [])
    if not isinstance(q, list):
        q = []
    if player_name not in q:
        q.append(player_name)
    st.session_state["draft_queue"] = q
    _workflow_normalize_draft_queue()
    return f"Queued {player_name}."


def simulate_drafting_player(player_name, team_name):
    table = st.session_state.get("draft_room_table", pd.DataFrame()).copy()
    if table.empty or "Player" not in table.columns or "Team" not in table.columns:
        return pd.DataFrame(), "No Draft Room table exists yet."

    sim_table = table.copy()
    player_name = str(player_name).strip()
    team_name = str(team_name).strip()

    existing = sim_table["Player"].dropna().astype(str).str.strip().tolist()
    if player_name in existing:
        return sim_table, f"{player_name} is already drafted, so the simulation did not add him again."

    open_mask = sim_table["Player"].fillna("").astype(str).str.strip().eq("")
    team_open = sim_table.index[open_mask & sim_table["Team"].astype(str).eq(team_name)].tolist()
    if team_open:
        idx = team_open[0]
    else:
        any_open = sim_table.index[open_mask].tolist()
        if not any_open:
            return sim_table, "Draft Room is full. No simulation slot available."
        idx = any_open[0]
        sim_table.loc[idx, "Team"] = team_name

    sim_table.loc[idx, "Player"] = player_name
    pick_num = sim_table.loc[idx, "Pick"] if "Pick" in sim_table.columns else idx + 1
    return sim_table, f"Simulation: {player_name} would be drafted by {team_name} at pick {pick_num}."




def player_on_fantasy_team(player_name, fantasy_team):
    """Return True if player_name is already on fantasy_team in Draft Room."""
    if not fantasy_team:
        return False
    table = st.session_state.get("draft_room_table", pd.DataFrame()).copy()
    if table.empty or "Team" not in table.columns or "Player" not in table.columns:
        return False
    team_rows = table[table["Team"].astype(str) == str(fantasy_team)]
    return str(player_name).strip() in team_rows["Player"].dropna().astype(str).str.strip().tolist()


def execute_player_action_once(selected_player, action, team_name, user_draft_team, label_map_compare):
    """Apply one action for one player. No Streamlit widgets. Returns a single-line result message."""
    sp = str(selected_player).strip()
    teams = get_draft_room_team_options()
    if not sp:
        return "Skipped (empty name)."

    record_workflow_recent_player(sp)

    if action == "Draft player to next pick":
        if not is_users_draft_turn(user_draft_team):
            return "Skipped — not your team's pick on the board right now."
        if not teams:
            return "Skipped — no Draft Room teams."
        return add_player_to_next_draft_room_pick(sp, team_name)

    if action == "Queue player":
        return add_player_to_queue(sp)

    if action == "Send to Comparison Tool":
        if append_compare_player_ordered(sp, label_map_compare):
            pp = st.session_state.get("pending_compare_players")
            if isinstance(pp, list) and len(pp) >= 2:
                record_workflow_comparison_pair(pp[0], pp[1])
            return "Sent to Comparison Tool (fills Player A, then Player B; a new send with both filled replaces Player B)."
        return "Skipped — name could not be matched to the database for Comparison."

    if action == "Send to Trend Page":
        if register_players_sent_to_trend_page(sp, label_map_compare):
            return "Sent to Trend Value (single-player anchor + multi chart queue updated)."
        return "Skipped — name could not be matched for Trend."

    if action == "Send to Draft Assistant":
        st.session_state["pending_draft_assistant_player"] = sp
        focus = st.session_state.get("draft_assistant_focus_players", [])
        if not isinstance(focus, list):
            focus = []
        if sp not in focus:
            focus.append(sp)
        st.session_state["draft_assistant_focus_players"] = focus[-10:]
        return "Added to Draft Assistant focus/watch list."

    if action == "Add as trade target to acquire":
        acquire = st.session_state.get("pending_trade_acquire_players", [])
        if sp not in acquire:
            acquire.append(sp)
        st.session_state["pending_trade_acquire_players"] = acquire
        return "Added to trade targets (acquire) list."

    if action == "Add as player to trade away":
        give = st.session_state.get("pending_trade_away_players", [])
        if sp not in give:
            give.append(sp)
        st.session_state["pending_trade_away_players"] = give
        return "Added to trade-away list."

    if action == "Simulate drafting this player":
        if not teams:
            return "Skipped — no Draft Room table / teams."
        sim_table, msg = simulate_drafting_player(sp, team_name)
        st.session_state["simulated_draft_room_table"] = sim_table
        return msg

    return f"Unknown action: {action}"


def player_action_menu(
    player_options,
    key,
    default_team=None,
    source_label="this table",
    user_draft_team=None,
    projection_lookup_df=None,
    projection_lookup_name_col="fullName",
    help_text=None,
):
    """Delegate to the same page-only player action UI as compact_player_action_center."""
    return compact_player_action_center(
        player_options,
        key,
        default_team=default_team,
        label="Player actions",
        user_draft_team=user_draft_team,
        projection_lookup_df=projection_lookup_df,
        projection_lookup_name_col=projection_lookup_name_col,
        help_text=help_text,
    )


def compact_player_action_center(
    player_options,
    key,
    default_team=None,
    label="Player Action Center",
    user_draft_team=None,
    projection_lookup_df=None,
    projection_lookup_name_col="fullName",
    help_text=None,
):
    """Primary player workflow: one popover with per-action buttons (no duplicate menus).

    Replaces the legacy multiselect + action dropdown + Run Action control. Trade
    routing still follows roster (inside the popover). Batch multi-select is gone;
    run an action per player inside the popover for the same outcomes.
    """
    ctx = [str(p).strip() for p in list(player_options or []) if str(p).strip()]
    ctx = list(dict.fromkeys(ctx))

    if not ctx:
        st.info("No players in this section for actions.")
        return None

    st.caption("Open Player Actions to queue, compare, trend, draft, simulate, trade, or view a projection breakdown.")
    player_quick_actions_popover(
        ctx,
        key=key,
        user_draft_team=user_draft_team,
        default_team=default_team,
        projection_lookup_df=projection_lookup_df,
        projection_lookup_name_col=projection_lookup_name_col,
        label=label or "Player actions",
        help_text=help_text
        or "Pick a player, then choose an action.",
    )

    _workflow_normalize_draft_queue()
    q = st.session_state.get("draft_queue", [])
    if q:
        with st.expander("Current Draft Queue / Watch List", expanded=False):
            st.write(q)

    return ctx[0] if ctx else None


def _qa_key_suffix(text):
    h = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:10]
    return h


def build_projection_breakdown_markdown(player_display_name, draft_row=None, yearly_df_local=None):
    """Narrative projection breakdown using existing model fields only (no new formulas)."""
    lines = [f"### Projection breakdown: {player_display_name}", ""]
    if draft_row is not None and hasattr(draft_row, "index"):
        def _g(col):
            try:
                if col in draft_row.index:
                    return draft_row[col]
            except Exception:
                return None
            return None

        pos = _g("Primary Position")
        age = _g("Age")
        g = _g("G")
        ab = _g("AB")
        if pos is not None or pd.notna(age):
            lines.append(
                f"- **Profile:** position `{pos}`, age `{fmt_int(age) if pd.notna(age) else 'n/a'}`, "
                f"recent volume **G={fmt_int(g)}**, **AB={fmt_int(ab)}** (from the projection window inputs)."
            )
        mr = _g("Market Rank")
        mdl = _g("Model Rank")
        fe = _g("Fantasy Edge")
        if any(pd.notna(x) for x in (mr, mdl, fe)):
            lines.append(
                f"- **Market vs model:** Market rank `{fmt_int(mr)}`, model rank `{fmt_int(mdl)}`, "
                f"fantasy edge `{fmt_int(fe)}` (positive means your model is higher on the player than ADP/market)."
            )
        efv = _g("Expected Fantasy Value")
        rbase = _g("Realistic Base Projection Score")
        ml_adj = _g("ML Adjustment")
        ml_score = _g("ML Projection Score")
        if rbase is not None or efv is not None:
            lines.append(
                f"- **Value stack:** realistic base projection score `{fmt_rate_4(rbase)}` feeds expected fantasy value "
                f"`{fmt_rate_4(efv)}` after the small ML/context layer."
            )
        if ml_adj is not None and pd.notna(ml_adj):
            lines.append(
                f"- **ML/context layer:** ML adjustment `{float(ml_adj):+.4f}` (capped in the model) with "
                f"ML projection score `{fmt_rate_4(ml_score)}` — this nudges the baseline for breakout/risk/playing-time signals, not a full re-rank."
            )
        brk = _g("Breakout Probability")
        risk = _g("Risk Score")
        if brk is not None or risk is not None:
            lines.append(
                f"- **Shape signals:** breakout probability `{fmt_rate_4(brk)}`, risk score `{fmt_rate_4(risk)}` "
                "(from capped trends, age curve, and similar-player anchoring inside the realistic projection builder)."
            )
        for tlab, tcol in [
            ("HR trend", "HR_trend"),
            ("OPS trend", "OPS_trend"),
            ("SB trend", "SB_trend"),
            ("BA trend", "BA_trend"),
        ]:
            tv = _g(tcol)
            if tv is not None and pd.notna(tv):
                lines.append(f"- **{tlab} (window slope):** `{float(tv):+.4f}` — used in capped form so one hot year does not dominate.")
        lines.append("")
        lines.append(
            "*This text summarizes fields already computed by `build_realistic_draft_ml_adjustments` and related "
            "draft scoring — it does not re-fit or change any formulas.*"
        )
        return "\n".join(lines)

    if yearly_df_local is not None and "fullName" in yearly_df_local.columns:
        base = str(player_display_name).split(" (")[0].strip()
        sub = yearly_df_local[yearly_df_local["fullName"].astype(str).str.strip().eq(base)]
        if sub.empty:
            lines.append("No matching Lahman rows for this name — open Historical Explorer to verify spelling or duplicates.")
        else:
            last = sub.sort_values("yearID").tail(1).iloc[0]
            yr = last.get("yearID")
            lines.append(
                f"- **Latest season on file ({yr}):** HR `{fmt_int(last.get('HR'))}`, RBI `{fmt_int(last.get('RBI'))}`, "
                f"R `{fmt_int(last.get('R'))}`, SB `{fmt_int(last.get('SB'))}`, OPS `{fmt_rate_3(last.get('OPS'))}`."
            )
            lines.append("- Draft Assistant / fantasy pages add market + model layers on top of this history.")
        return "\n".join(lines)

    lines.append("No projection row available for this player on this page.")
    return "\n".join(lines)


@st.dialog("Projection breakdown")
def _projection_breakdown_dialog(body_md: str):
    st.markdown(body_md)


def player_quick_actions_popover(
    player_options,
    *,
    key,
    user_draft_team=None,
    default_team=None,
    projection_lookup_df=None,
    projection_lookup_name_col="fullName",
    label="Player quick actions",
    help_text="Pick a player, then choose an action.",
):
    """Contextual one-click player actions."""
    ctx = [str(p).strip() for p in list(player_options or []) if str(p).strip()]
    ctx = list(dict.fromkeys(ctx))
    if not ctx:
        return

    label_map = get_clean_player_label_map_yearly(yearly_df)
    teams = get_draft_room_team_options()
    team_for_draft = default_team or user_draft_team or st.session_state.get("room_your_team")
    if teams and team_for_draft not in teams:
        team_for_draft = teams[0]

    with st.popover(label):
        if help_text:
            st.caption(help_text)
        pick = st.selectbox(
            "Player",
            ctx,
            index=0,
            key=f"{key}_qa_player_pick",
        )
        sfx = _qa_key_suffix(f"{key}|{pick}")
        on_my = player_on_fantasy_team(pick, team_for_draft) if team_for_draft else False
        can_draft = bool(user_draft_team) and is_users_draft_turn(user_draft_team)

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("Add to Draft Queue", key=f"{key}_qa_queue_{sfx}"):
                msg = execute_player_action_once(pick, "Queue player", team_for_draft, user_draft_team, label_map)
                st.success(msg)
        with b2:
            if st.button("Send to Comparison", key=f"{key}_qa_cmp_{sfx}"):
                msg = execute_player_action_once(pick, "Send to Comparison Tool", team_for_draft, user_draft_team, label_map)
                st.success(msg)
                request_sidebar_page("Comparison Tool")
        with b3:
            if st.button("Send to Trend", key=f"{key}_qa_tr_{sfx}"):
                msg = execute_player_action_once(pick, "Send to Trend Page", team_for_draft, user_draft_team, label_map)
                st.success(msg)
                request_sidebar_page("Trend Value")

        b4, b5, b6 = st.columns(3)
        with b4:
            if st.button("Send to Draft Assistant", key=f"{key}_qa_da_{sfx}"):
                msg = execute_player_action_once(pick, "Send to Draft Assistant", team_for_draft, user_draft_team, label_map)
                st.success(msg)
        with b5:
            if not on_my:
                if st.button("Trade · Acquire", key=f"{key}_qa_tacq_{sfx}"):
                    msg = execute_player_action_once(pick, "Add as trade target to acquire", team_for_draft, user_draft_team, label_map)
                    st.success(msg)
            else:
                st.caption("On your roster — *Trade · Acquire* is hidden.")
        with b6:
            if on_my:
                if st.button("Trade · Away", key=f"{key}_qa_taw_{sfx}"):
                    msg = execute_player_action_once(pick, "Add as player to trade away", team_for_draft, user_draft_team, label_map)
                    st.success(msg)
            else:
                st.caption("Not on your roster — *Trade · Away* is hidden.")

        b7, b8, b9 = st.columns(3)
        with b7:
            if can_draft:
                if st.button("Draft this player", key=f"{key}_qa_draft_{sfx}"):
                    msg = execute_player_action_once(pick, "Draft player to next pick", team_for_draft, user_draft_team, label_map)
                    st.success(msg)
            else:
                st.caption("Not your pick — *Draft this player* hidden.")
        with b8:
            if st.button("Simulate draft fit", key=f"{key}_qa_sim_{sfx}"):
                msg = execute_player_action_once(pick, "Simulate drafting this player", team_for_draft, user_draft_team, label_map)
                st.success(msg)
                last_sim = st.session_state.get("simulated_draft_room_table")
                if last_sim is not None and not getattr(last_sim, "empty", True):
                    st.caption("Latest simulated board after this pick:")
                    st.dataframe(last_sim, use_container_width=True, hide_index=True)
        with b9:
            if st.button("Projection breakdown", key=f"{key}_qa_proj_{sfx}"):
                record_workflow_recent_player(pick)
                row = None
                if projection_lookup_df is not None and projection_lookup_name_col in projection_lookup_df.columns:
                    m = projection_lookup_df[projection_lookup_df[projection_lookup_name_col].astype(str).str.strip() == str(pick).strip()]
                    if not m.empty:
                        row = m.iloc[0]
                md = build_projection_breakdown_markdown(pick, draft_row=row, yearly_df_local=yearly_df)
                _projection_breakdown_dialog(md)


def clickable_player_draft_table(df, player_col="Player", team_name=None, key="clickable_draft_table", title="Clickable Draft Table"):
    """Interactive player table: select one row and draft that player to the next Draft Room pick.

    Uses Streamlit's built-in dataframe row-selection events, so it does not require extra packages.
    """
    if df is None or df.empty:
        st.info(f"{title}: no players available.")
        return None

    table = df.copy()
    if player_col not in table.columns:
        st.warning(f"{title}: missing player column.")
        return None

    st.caption("Click a row in the table below, then press the draft button.")
    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key=key
    )

    selected_player = None
    try:
        selected_rows = event.selection.rows
        if selected_rows:
            selected_player = str(table.iloc[selected_rows[0]][player_col])
    except Exception:
        selected_player = None

    if selected_player:
        st.success(f"Selected: {selected_player}")
        draft_teams = get_draft_room_team_options()
        if draft_teams:
            if team_name is None:
                default_team = st.session_state.get("room_your_team", draft_teams[0])
                default_idx = draft_teams.index(default_team) if default_team in draft_teams else 0
                team_name = st.selectbox(
                    "Draft Room team",
                    draft_teams,
                    index=default_idx,
                    key=f"{key}_team"
                )
            else:
                st.caption(f"Drafting to: {team_name}")

            if is_users_draft_turn(team_name):
                if st.button(f"Draft {selected_player} To Next Pick", key=f"{key}_draft_button"):
                    msg = add_player_to_next_draft_room_pick(selected_player, team_name)
                    st.success(msg)
            else:
                st.info(
                    "It is not your team's turn on the Draft Room board — **Draft to next pick** is disabled. "
                    "Use Player Actions below to **queue** the player or **simulate** a draft."
                )
        else:
            st.info("Open Draft Room Simulator first so the app knows the fantasy teams.")
    return selected_player


def get_draft_room_team_options():
    table = st.session_state.get("draft_room_table", pd.DataFrame()).copy()
    if table.empty or "Team" not in table.columns:
        return []
    return sorted(table["Team"].dropna().astype(str).unique().tolist())


def add_player_to_next_draft_room_pick(player_name, team_name):
    """Add selected player to the next open Draft Room row for the selected team.

    If the selected team's next row is unavailable, use the next open row.
    Returns a message string.
    """
    if "draft_room_table" not in st.session_state:
        return "No Draft Room table exists yet. Open Draft Room Simulator first."

    table = st.session_state["draft_room_table"].copy()
    if table.empty or "Player" not in table.columns or "Team" not in table.columns:
        return "Draft Room table is missing Team/Player columns."

    player_name = str(player_name).strip()
    team_name = str(team_name).strip()

    if not player_name:
        return "No player selected."

    # Do not draft the same player twice.
    existing_players = table["Player"].dropna().astype(str).str.strip().tolist()
    if player_name in existing_players:
        return f"{player_name} is already drafted."

    open_mask = table["Player"].fillna("").astype(str).str.strip().eq("")
    team_open_idx = table.index[open_mask & table["Team"].astype(str).eq(team_name)].tolist()

    if team_open_idx:
        idx = team_open_idx[0]
    else:
        any_open_idx = table.index[open_mask].tolist()
        if not any_open_idx:
            return "Draft Room is full. No open pick rows remain."
        idx = any_open_idx[0]
        table.loc[idx, "Team"] = team_name

    table.loc[idx, "Player"] = player_name
    st.session_state["draft_room_table"] = table
    pick_num = table.loc[idx, "Pick"] if "Pick" in table.columns else idx + 1
    return f"Drafted {player_name} to {team_name} at pick {pick_num}."


def build_draft_room_table_from_assistant(my_roster, other_rosters, my_team_name="My Team", other_team_name="Other Rosters"):
    rows = []
    pick = 1
    for p in list(my_roster or []):
        if str(p).strip():
            rows.append({"Round": pick, "Pick": pick, "Team": my_team_name, "Player": str(p).strip()})
            pick += 1
    for p in list(other_rosters or []):
        if str(p).strip():
            rows.append({"Round": pick, "Pick": pick, "Team": other_team_name, "Player": str(p).strip()})
            pick += 1
    return pd.DataFrame(rows, columns=["Round", "Pick", "Team", "Player"])


def sync_draft_room_to_assistant_from_table(draft_room_table, my_team_name):
    if draft_room_table is None or len(draft_room_table) == 0:
        return [], []
    df = draft_room_table.copy()
    if "Player" not in df.columns or "Team" not in df.columns:
        return [], []
    df = df[df["Player"].astype(str).str.strip() != ""].copy()
    my_roster = df[df["Team"].astype(str) == str(my_team_name)]["Player"].dropna().astype(str).tolist()
    other_rosters = df[df["Team"].astype(str) != str(my_team_name)]["Player"].dropna().astype(str).tolist()
    return sorted(list(dict.fromkeys(my_roster))), sorted(list(dict.fromkeys(other_rosters)))


batting_df, yearly_df, people_df = load_data()


def get_clean_player_label_map_yearly(yl_df):
    """Session cache for Lahman label map (same ``yearly_df`` ref from ``load_data`` across reruns)."""
    vid = id(yl_df)
    if st.session_state.get("_clean_label_map_vid") != vid:
        st.session_state["_clean_label_map_vid"] = vid
        st.session_state["_clean_label_map"] = build_clean_player_label_map(yl_df)
        st.session_state["_clean_label_keys_sorted"] = sorted(st.session_state["_clean_label_map"].keys())
    return st.session_state["_clean_label_map"]


def get_sorted_clean_player_label_keys(yl_df):
    """Alphabetical label list for large dropdowns (built once per ``yearly_df`` identity)."""
    get_clean_player_label_map_yearly(yl_df)
    return st.session_state.get("_clean_label_keys_sorted", [])


def get_pid_to_clean_label_map_yearly(yl_df):
    lm = get_clean_player_label_map_yearly(yl_df)
    return {pid: lbl for lbl, pid in lm.items()}


def _hist_explorer_pos_options(source_col):
    cache = st.session_state.setdefault("_hist_explorer_pos_cache", {})
    if source_col not in cache:
        s = batting_df[source_col]
        cache[source_col] = sorted(
            x for x in s.dropna().unique() if str(x).strip() != "" and x not in ("PH", "PR")
        )
    return cache[source_col]


def _hist_explorer_franchise_names_for_teams():
    cache = st.session_state.setdefault("_hist_explorer_team_cache", {})
    if "franchise" not in cache:
        cache["franchise"] = sorted(
            set(batting_df["teamName"].dropna().astype(str)).intersection(set(team_id_to_name.values()))
        )
    return cache["franchise"]


all_years = sorted(pd.to_numeric(yearly_df["yearID"], errors="coerce").dropna().astype(int).unique())
year_min = int(min(all_years))
year_max = int(max(all_years))
default_start_hist = max(year_min, 2010)
default_start_leaders = max(year_min, 2020)

def record_workflow_recent_player(display_name):
    """MRU list of display names the user acted on (session only)."""
    name = str(display_name).strip()
    if not name:
        return
    lst = st.session_state.get("workflow_recently_viewed", [])
    st.session_state["workflow_recently_viewed"] = wf_sb.merge_mru(lst, name, wf_sb.RECENT_VIEW_CAP)


def record_workflow_comparison_pair(label_a, label_b):
    """Store ordered A vs B pairs for one-click reload (deduped by unordered pair)."""
    pairs = st.session_state.get("workflow_recent_compare_pairs", [])
    st.session_state["workflow_recent_compare_pairs"] = wf_sb.merge_comparison_pairs(
        pairs, label_a, label_b, wf_sb.RECENT_COMPARE_CAP
    )


def _workflow_normalize_draft_queue():
    st.session_state["draft_queue"] = wf_sb.normalize_dedupe_queue(st.session_state.get("draft_queue"))


def render_persistent_workflow_sidebar(_yearly_df_local=None):
    """Fantasy Workflow Center: draft queue + recently viewed (``st.sidebar`` only)."""
    _workflow_normalize_draft_queue()

    active = str(st.session_state.get("active_page", "")).strip()
    _fantasy_draft_pages = frozenset({
        "Fantasy Sleepers & Busts",
        "Draft Room Simulator",
        "Draft Assistant Simulator",
        "Fantasy Standings Tracker",
        "Fantasy Lineup Assistant",
    })
    if active not in _fantasy_draft_pages:
        return

    flash = st.session_state.pop("workflow_sidebar_flash", None)
    if flash:
        st.sidebar.warning(str(flash))

    dq = st.session_state.get("draft_queue", []) or []
    rv = st.session_state.get("workflow_recently_viewed", [])
    if not isinstance(rv, list):
        rv = []

    st.sidebar.divider()
    st.sidebar.markdown("### Fantasy Workflow Center")
    st.sidebar.caption("Lists persist in this session while you move between pages.")

    with st.sidebar.expander("Draft queue", expanded=bool(dq)):
        if not dq:
            st.caption("Empty — add players with **Add to Draft Queue** in player actions.")
        else:
            for pname in dq[-12:]:
                st.caption(str(pname).strip()[:48] + ("…" if len(str(pname).strip()) > 48 else ""))
            if len(dq) > 12:
                st.caption(f"+{len(dq) - 12} more")

    with st.sidebar.expander("Recently viewed players", expanded=False):
        if not rv:
            st.caption("Updates when you select, send, or analyze a player.")
        else:
            for pname in reversed(rv[-12:]):
                st.caption(str(pname).strip()[:48] + ("…" if len(str(pname).strip()) > 48 else ""))
            if len(rv) > 12:
                st.caption(f"+{len(rv) - 12} older")


PAGE_OPTIONS = ["Historical Explorer", "Career Totals", "Leaderboards", "Comparison Tool", "Trend Value", "Valuation", "ML Predictions", "Fantasy Sleepers & Busts", "Draft Room Simulator", "Draft Assistant Simulator", "Fantasy Standings Tracker", "Fantasy Lineup Assistant"]
_PAGE_OPTION_SET = frozenset(PAGE_OPTIONS)


def request_sidebar_page(page: str):
    """Defer page changes until before ``st.sidebar.radio`` — avoids StreamlitAPIException."""
    p = str(page).strip()
    if p in _PAGE_OPTION_SET:
        st.session_state["_pending_active_page"] = p
        st.rerun()

# Persist navigation and page-specific widget settings.
# IMPORTANT: Do not manually reassign widget keys in st.session_state.
# Streamlit forbids programmatic assignment for button/download_button widgets.
# Stable widget keys plus radio-style page navigation preserve filters and charts
# when moving between pages during the same session.

# Page navigation is handled by one stable sidebar radio key.
# Streamlit may clean up widget values from pages that are not currently rendered.
# This safe keep-alive loop preserves filters/settings from previously visited pages
# while avoiding button/download/form-submit keys, which Streamlit does not allow
# to be reassigned programmatically. Also skip player_quick_actions_popover keys
# Skip all player_quick_actions_popover widget keys (…_qa_…) — selectbox + buttons;
# reassigning their session_state triggers StreamlitValueAssignmentNotAllowedError.
for _state_key in list(st.session_state.keys()):
    _key_text = str(_state_key).lower()
    if (
        _key_text == "active_page"
        or _key_text == "_pending_active_page"
        or _key_text.startswith("download")
        or _key_text.startswith("export")
        or _key_text.startswith("button")
        or _key_text.startswith("form_submit")
        or _key_text.endswith("_button")
        or "_button" in _key_text
        or "download" in _key_text
        or "upload" in _key_text
        or "uploader" in _key_text
        or "file_uploader" in _key_text
        or "export_csv" in _key_text
        or "form_submit" in _key_text
        or "compact_run_action" in _key_text
        or "compact_action" in _key_text
        or "compact_player" in _key_text
        or "run_player_action" in _key_text
        or "player_action" in _key_text
        or "draft_button" in _key_text
        or "gobtn" in _key_text
        or "_gobtn" in _key_text
        or "run_action" in _key_text
        or "_run_action" in _key_text
        or "cpa_submit" in _key_text
        or "cpa_selgrid" in _key_text
        or "clear" in _key_text
        or "reset" in _key_text
        or "send_queue" in _key_text
        or "trend_clear" in _key_text
        or _key_text == "trend_clear_send_queue"
        or "draft_assistant_import" in _key_text
        or "button" in _key_text
        or "dismiss" in _key_text
        or "highlight" in _key_text
        or "reset" in _key_text
        or "clear" in _key_text
        or "generate_roster_view" in _key_text
        or "load_uploaded" in _key_text
        or "suggest_trade" in _key_text
        or "upload" in _key_text
        or "uploader" in _key_text
        or "file_uploader" in _key_text
        or "standings_stats_upload" in _key_text
        or "data_editor" in _key_text
        or "draft_room_editor" in _key_text
        or "data_editor" in _key_text
        or "draft_room_editor" in _key_text
        or "_qa_" in _key_text
        or _key_text.startswith("wf_")
    ):
        continue
    try:
        st.session_state[_state_key] = st.session_state[_state_key]
    except Exception:
        pass

_pending_nav = st.session_state.pop("_pending_active_page", None)
if _pending_nav and _pending_nav in _PAGE_OPTION_SET:
    st.session_state["active_page"] = _pending_nav

st.session_state.setdefault("active_page", "Historical Explorer")
active_page = st.sidebar.radio("Choose Page", PAGE_OPTIONS, key="active_page")
st.sidebar.caption("Filters are remembered as you move between pages.")
render_persistent_workflow_sidebar(yearly_df)

if active_page == "Historical Explorer":
    render_section_header(
        "🔎 Historical Explorer",
        "Find individual player seasons. Split-team seasons can stay as separate team rows or be combined into one primary-team season row."
    )
    c1, c2, c_mode, c3, c4 = st.columns([1.05, 1.0, 1.25, 1.0, 1.35])
    with c1:
        hist_year_range = st.slider("Year Range", year_min, year_max, (default_start_hist, year_max), key="hist_year")
    with c2:
        bats_options = sorted([x for x in batting_df["bats"].dropna().unique() if str(x).strip() != ""])
        hist_bats = st.multiselect("Batting Hand", bats_options, default=bats_options, key="hist_bats")
    with c_mode:
        hist_position_filter_mode = st.selectbox(
            "Position Filter Mode",
            ["Season Primary Position", "Career Primary Position"],
            index=0,
            key="hist_position_filter_mode",
            help="Season mode filters by the player’s primary position for that season. Career mode filters by the player’s full-career primary position from Fielding.csv games."
        )
    hist_position_source_col = "careerPrimaryPos" if hist_position_filter_mode == "Career Primary Position" else "primaryPos"
    with c3:
        pos_options = _hist_explorer_pos_options(hist_position_source_col)
        hist_pos = st.multiselect("Primary Position", pos_options, default=pos_options, key="hist_pos")
    with c4:
        actual_team_names = _hist_explorer_franchise_names_for_teams()
        hist_team_options = ["All Teams", "American League", "National League"] + actual_team_names
        hist_teams = st.multiselect("Franchise / League", hist_team_options, default=["All Teams"], key="hist_team")

    combine_split_seasons = st.toggle(
        "Combine split-team seasons into one primary-team row",
        value=False,
        key="hist_combine_split_seasons",
        help="OFF = one row per player/year/team. ON = one row per player/year, with Team assigned to the team where he had the most games/AB in that season."
    )

    hist_source = batting_df[(batting_df["yearID"] >= hist_year_range[0]) & (batting_df["yearID"] <= hist_year_range[1])].copy()
    if hist_bats:
        hist_source = hist_source[hist_source["bats"].isin(hist_bats)]
    if hist_pos:
        hist_source = hist_source[hist_source[hist_position_source_col].isin(hist_pos)]

    hist_selected_all = (not hist_teams) or ("All Teams" in hist_teams)
    hist_selected_franchises = [x for x in hist_teams if x not in ["All Teams", "American League", "National League"]]
    hist_selected_leagues = []
    if "American League" in hist_teams:
        hist_selected_leagues.append("AL")
    if "National League" in hist_teams:
        hist_selected_leagues.append("NL")

    # Split-team mode: apply league/franchise filter to each actual displayed team row.
    if not combine_split_seasons and not hist_selected_all:
        hist_team_mask = pd.Series(False, index=hist_source.index)
        if hist_selected_franchises:
            hist_team_mask = hist_team_mask | hist_source["teamName"].isin(hist_selected_franchises)
        if hist_selected_leagues:
            hist_team_mask = hist_team_mask | hist_source["teamLeague"].isin(hist_selected_leagues)
        hist_source = hist_source[hist_team_mask]

    if combine_split_seasons:
        hist = aggregate_player_year_primary_team(hist_source)
        team_col_for_display = "primaryHistoricalTeamName"
        team_sort_col = "primaryTeamName"
        hist_note = "Combined mode: one row per player-season. Team is the primary team for that season. League filters use that primary team."
        if not hist_selected_all and not hist.empty:
            hist_team_mask = pd.Series(False, index=hist.index)
            if hist_selected_franchises:
                hist_team_mask = hist_team_mask | hist["primaryTeamName"].isin(hist_selected_franchises)
            if hist_selected_leagues and "primaryLeague" in hist.columns:
                hist_team_mask = hist_team_mask | hist["primaryLeague"].isin(hist_selected_leagues)
            hist = hist[hist_team_mask]
    else:
        hist = aggregate_player_year_team(hist_source)
        team_col_for_display = "teamHistoricalName"
        team_sort_col = "teamName"
        hist_note = "Split mode: one row per player-season-team. Split seasons stay separate."

    if hist_position_source_col in hist.columns:
        hist["displayPosition"] = hist[hist_position_source_col]
    elif "primaryPos" in hist.columns:
        hist["displayPosition"] = hist["primaryPos"]
    else:
        hist["displayPosition"] = ""

    hist = apply_stat_min_filters(hist, "hist")
    hist = safe_round_rate_stats(hist)
    st.caption(hist_note)

    c5, c6 = st.columns(2)
    # Keep Historical Explorer sorting focused on baseball statistics only.
    # Do not expose backend/name/team/position fields in the sort dropdown.
    sort_options_hist = [
        "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"
    ]
    with c5:
        hist_sort_stat = st.selectbox(
            "Sort Historical Explorer By",
            sort_options_hist,
            index=sort_options_hist.index("HR"),
            key="hist_sort_stat"
        )
    with c6:
        hist_sort_order = st.selectbox("Sort Order", ["Descending", "Ascending"], index=0, key="hist_sort_order")

    display_cols_hist = [
        "yearID", "fullName", "bats", "displayPosition", team_col_for_display,
        "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"
    ]
    display_cols_hist = [c for c in display_cols_hist if c in hist.columns]
    hist_display_raw = hist[display_cols_hist].copy()
    if hist_sort_stat in hist_display_raw.columns:
        hist_display_raw = hist_display_raw.sort_values(by=hist_sort_stat, ascending=(hist_sort_order == "Ascending"), na_position="last")

    top_bar_chart(hist_display_raw, "fullName", hist_sort_stat, f"Top 10 Seasons by {hist_sort_stat}")

    c7, c8, c9 = st.columns(3)
    c7.metric("Rows Returned", len(hist_display_raw))
    top_value = pd.to_numeric(hist_display_raw[hist_sort_stat], errors="coerce").max() if len(hist_display_raw) and hist_sort_stat in hist_display_raw.columns else 0
    c8.metric("Top Stat Value", fmt_rate_3(top_value) if hist_sort_stat in RATE_STATS else (fmt_int(top_value) if hist_sort_stat in COUNT_STATS or hist_sort_stat == "yearID" else str(top_value)))
    c9.metric("Year Range", f"{hist_year_range[0]}-{hist_year_range[1]}")

    hist_display = hist_display_raw.rename(columns={
        "yearID": "Year", "fullName": "Player", "bats": "Bats", "displayPosition": "Primary Position",
        team_col_for_display: "Team"
    })
    st.divider()
    hist_table = format_display_table(clean_ui_columns(hist_display), count_cols=["Year", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB"], rate_cols=["BA", "OBP", "SLG", "OPS"])
    render_output_table(hist_table, key="historical_explorer", file_name="historical_explorer.csv")
    st.divider()
    hist_plot_df = _prepare_historical_scatter_data(hist, team_col_for_display)
    render_scatterplot_section(hist_plot_df, key_prefix="hist", title="Visualize Historical Results")
    render_relationship_finder_section(
        hist_plot_df, key_prefix="hist", row_context="filtered player-season rows"
    )

if active_page == "Career Totals":
    render_section_header(
        "📚 Career Totals",
        "Aggregate career production with an independent display toggle: one primary-team career row or separate totals by each team."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        range_career = st.slider("Select Year Range", year_min, year_max, (max(year_min, 2010), year_max), key="career_year")
    with c2:
        bats_options_career = sorted([x for x in batting_df["bats"].dropna().unique() if str(x).strip() != ""])
        bats_filter_career = st.multiselect("Batting Hand", bats_options_career, default=bats_options_career, key="career_bats")
    with c3:
        position_filter_mode = st.selectbox(
            "Position Filter Mode",
            ["Career Primary Position", "Season Primary Position"],
            index=0,
            key="career_position_filter_mode",
            help="Career mode uses each player's full-career primary position from Fielding.csv games. Season mode includes only seasons where the selected position was that player's primary position that year."
        )
    with c4:
        position_source_col = "careerPrimaryPos" if position_filter_mode == "Career Primary Position" else "primaryPos"
        pos_options_career = sorted([x for x in batting_df[position_source_col].dropna().unique() if str(x).strip() != "" and x not in ["PH", "PR"]])
        pos_filter_career = st.multiselect("Position", pos_options_career, default=pos_options_career, key="career_pos")
    with c5:
        actual_team_names_career = sorted(set(batting_df["teamName"].dropna().astype(str)).intersection(set(team_id_to_name.values())))
        team_options_career = ["All Teams", "American League", "National League"] + actual_team_names_career
        team_filter_career = st.multiselect("Franchise / League", team_options_career, default=["All Teams"], key="career_team")

    show_career_by_team = st.toggle(
        "Show career totals separately by team",
        value=False,
        key="career_by_team_toggle",
        help="OFF = one row per player with a Primary Team. ON = one row per player/team, and stat minimums are applied to each team row separately."
    )

    filtered_career = batting_df[(batting_df["yearID"] >= range_career[0]) & (batting_df["yearID"] <= range_career[1])].copy()
    if bats_filter_career:
        filtered_career = filtered_career[filtered_career["bats"].isin(bats_filter_career)]
    if pos_filter_career:
        # Position filtering is explicitly based on fielding games, not at-bats.
        # Career Primary Position = most games at a grouped position over the full career.
        # Season Primary Position = most games at a grouped position in that season.
        filtered_career = filtered_career[filtered_career[position_source_col].isin(pos_filter_career)]
    career_selected_all = (not team_filter_career) or ("All Teams" in team_filter_career)
    career_selected_franchises = [x for x in team_filter_career if x not in ["All Teams", "American League", "National League"]]
    career_selected_leagues = []
    if "American League" in team_filter_career:
        career_selected_leagues.append("AL")
    if "National League" in team_filter_career:
        career_selected_leagues.append("NL")

    # League/franchise filtering changes the DATA included.
    # The by-team toggle only changes the DISPLAY structure after this filter is applied.
    if not career_selected_all:
        career_team_mask = pd.Series(False, index=filtered_career.index)
        if career_selected_franchises:
            career_team_mask = career_team_mask | filtered_career["teamName"].isin(career_selected_franchises)
        if career_selected_leagues and "teamLeague" in filtered_career.columns:
            career_team_mask = career_team_mask | filtered_career["teamLeague"].isin(career_selected_leagues)
        filtered_career = filtered_career[career_team_mask]

    stat_cols_career = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF", "G"]
    stat_cols_career = [c for c in stat_cols_career if c in filtered_career.columns]

    if show_career_by_team:
        # Filter first, aggregate by player + actual team second, then apply stat minimum filters to each team row.
        grouped_source = aggregate_player_year_team(filtered_career)
        group_cols = ["playerID", "fullName", "bats", "teamName", "teamHistoricalName"]
        career_totals = grouped_source.groupby(group_cols, as_index=False)[stat_cols_career].sum()
        if position_filter_mode == "Career Primary Position":
            pos_mode = grouped_source[["playerID", "careerPrimaryPos"]].drop_duplicates("playerID").rename(columns={"careerPrimaryPos": "displayPosition"})
            career_totals = career_totals.merge(pos_mode, on="playerID", how="left")
        else:
            pos_mode = (
                grouped_source.groupby(["playerID", "teamName", "primaryPos"], as_index=False)[["G", "AB"]]
                .sum()
                .sort_values(["playerID", "teamName", "G", "AB", "primaryPos"], ascending=[True, True, False, False, True])
                .drop_duplicates(["playerID", "teamName"])[["playerID", "teamName", "primaryPos"]]
                .rename(columns={"primaryPos": "displayPosition"})
            )
            career_totals = career_totals.merge(pos_mode, on=["playerID", "teamName"], how="left")
        career_totals["displayTeam"] = career_totals["teamHistoricalName"]
        career_mode_note = "By-team mode: each player/team row must pass stat minimum filters on its own. Franchise/league filters first limit the data included; position is based on Fielding.csv games."
    else:
        # Filter first, aggregate by player second, then apply stat minimum filters to the total row.
        career_totals = filtered_career.groupby(["playerID", "fullName", "bats"], as_index=False)[stat_cols_career].sum()
        career_totals = add_primary_team_for_career(career_totals, filtered_career)
        if position_filter_mode == "Career Primary Position":
            career_totals["displayPosition"] = career_totals["careerPrimaryPos"] if "careerPrimaryPos" in career_totals.columns else career_totals.get("primaryPos")
        else:
            career_totals["displayPosition"] = career_totals.get("primaryPos")
        career_totals["displayTeam"] = career_totals["primaryHistoricalTeamName"]
        career_mode_note = "Total-career mode: one row per player. Franchise/league filters first limit the data included, then Team becomes the primary team within that filtered data. Position is based on Fielding.csv games."

    career_totals = add_rate_stats(career_totals)
    career_totals = apply_stat_min_filters(career_totals, "career")
    career_totals = safe_round_rate_stats(career_totals)
    st.caption(career_mode_note)

    sort_stat_career = st.selectbox("Sort By", ["HR", "RBI", "SB", "R", "H", "2B", "3B", "BB", "BA", "OBP", "SLG", "OPS", "AB"], index=0, key="career_sort")
    top_bar_chart(career_totals, "fullName", sort_stat_career, f"Top 10 Career Totals by {sort_stat_career}")

    c5, c6, c7 = st.columns(3)
    c5.metric("Rows", len(career_totals))
    c6.metric("Top Player", career_totals.sort_values(sort_stat_career, ascending=False).iloc[0]["fullName"] if len(career_totals) and sort_stat_career in career_totals.columns else "N/A")
    top_career_value = pd.to_numeric(career_totals[sort_stat_career], errors="coerce").max() if len(career_totals) and sort_stat_career in career_totals.columns else 0
    c7.metric("Top Value", fmt_rate_3(top_career_value) if sort_stat_career in RATE_STATS else fmt_int(top_career_value))

    career_display_cols = [
        "fullName", "bats", "displayPosition", "displayTeam",
        "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"
    ]
    career_display_cols = [c for c in career_display_cols if c in career_totals.columns]
    career_display = career_totals[career_display_cols].copy()
    if sort_stat_career in career_display.columns:
        career_display = career_display.sort_values(sort_stat_career, ascending=False)
    career_display = career_display.rename(columns={
        "fullName": "Player", "bats": "Bats", "displayPosition": "Primary Position", "displayTeam": "Team"
    })
    st.divider()
    career_table = format_display_table(clean_ui_columns(career_display), count_cols=["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB"], rate_cols=["BA", "OBP", "SLG", "OPS"])
    render_output_table(career_table, key="career_totals", file_name="career_totals.csv")
    st.divider()
    career_plot_df = _prepare_career_scatter_data(career_totals, filtered_career)
    render_scatterplot_section(career_plot_df, key_prefix="career", title="Visualize Career Results")
    render_relationship_finder_section(
        career_plot_df, key_prefix="career", row_context="filtered career rows"
    )

if active_page == "Leaderboards":
    render_section_header("🏆 Leaderboards", "Build custom offensive rankings with weighted stats, filters, summary cards, and charts.")
    c1, c2 = st.columns(2)
    with c1:
        range_leaders = st.slider("Select Year Range", year_min, year_max, (max(year_min, 2020), year_max), key="leaders_year")
    with c2:
        top_n_leaders = st.slider("Show Top N Players", 5, 100, 25, key="leaders_top_n")

    weight_stats = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]
    default_weights = {"HR": 1.0, "RBI": 1.0, "SB": 1.0}
    weight_values = {}
    with st.expander("Custom stat weights (defaults: HR / RBI / SB at 1.0; others 0)", expanded=False):
        st.caption("Weights feed the Score column only; raw counting and rate stats in the table are unchanged.")
        weight_cols = st.columns(4)
        for i, stat in enumerate(weight_stats):
            with weight_cols[i % 4]:
                weight_values[stat] = st.number_input(f"Weight for {stat}", min_value=0.0, max_value=10.0, value=default_weights.get(stat, 0.0), step=0.5, key=f"leaders_w_{stat}")

    filtered_leaders = yearly_df[(yearly_df["yearID"] >= range_leaders[0]) & (yearly_df["yearID"] <= range_leaders[1])].copy()
    leaderboard = filtered_leaders.groupby(["fullName", "bats"], as_index=False)[["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]].sum()
    leaderboard = add_rate_stats(leaderboard)
    leaderboard = apply_stat_min_filters(leaderboard, "leaders")
    leaderboard = safe_round_rate_stats(leaderboard)

    leaderboard["score"] = 0.0
    for stat, weight in weight_values.items():
        leaderboard["score"] += weight * (leaderboard[stat] * 100 if stat in RATE_STATS else leaderboard[stat])

    sort_stat_leaders = st.selectbox("Sort Leaderboard By", ["score", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"], index=0, key="leaders_sort")
    top_bar_chart(leaderboard, "fullName", sort_stat_leaders, f"Top 10 by {sort_stat_leaders}")

    c12, c13, c14 = st.columns(3)
    c12.metric("Top HR", fmt_int(leaderboard["HR"].max() if not leaderboard.empty else 0))
    c13.metric("Top OPS", fmt_rate_3(leaderboard["OPS"].max() if not leaderboard.empty else 0))
    c14.metric("Average OPS", fmt_rate_3(leaderboard["OPS"].mean() if not leaderboard.empty else 0))

    leaderboard_display = leaderboard[[
        "fullName", "bats", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS", "score"
    ]].sort_values(sort_stat_leaders, ascending=False).head(top_n_leaders).rename(columns={"fullName": "Player", "bats": "Bats", "score": "Score"})

    st.divider()
    leaderboard_table = format_display_table(clean_ui_columns(leaderboard_display), count_cols=["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB"], rate_cols=["BA", "OBP", "SLG", "OPS"], score_cols=["Score"])
    render_output_table(leaderboard_table, key="leaderboards", file_name="leaderboards.csv")



# ----------------------------
# Comparison Tool statistical tests
# ----------------------------
def _normal_two_sided_p_from_z(z):
    """Approximate two-sided p-value using the standard normal distribution."""
    try:
        import math
        return float(math.erfc(abs(float(z)) / math.sqrt(2)))
    except Exception:
        return np.nan


def _welch_test_summary(a, b):
    """Return Welch-style difference test using a normal approximation for p-value."""
    a = pd.to_numeric(pd.Series(a), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    b = pd.to_numeric(pd.Series(b), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return {"n1": n1, "n2": n2, "mean1": np.nan, "mean2": np.nan, "difference": np.nan,
                "stat": np.nan, "p_value": np.nan, "ci_low": np.nan, "ci_high": np.nan, "enough_data": False}
    mean1, mean2 = float(a.mean()), float(b.mean())
    var1 = float(a.var(ddof=1))
    var2 = float(b.var(ddof=1))
    se = np.sqrt(var1 / n1 + var2 / n2)
    if not np.isfinite(se) or se == 0:
        return {"n1": n1, "n2": n2, "mean1": mean1, "mean2": mean2, "difference": mean1 - mean2,
                "stat": np.nan, "p_value": np.nan, "ci_low": np.nan, "ci_high": np.nan, "enough_data": False}
    stat = (mean1 - mean2) / se
    p_value = _normal_two_sided_p_from_z(stat)
    diff = mean1 - mean2
    return {"n1": n1, "n2": n2, "mean1": mean1, "mean2": mean2, "difference": diff,
            "stat": float(stat), "p_value": p_value, "ci_low": float(diff - 1.96 * se),
            "ci_high": float(diff + 1.96 * se), "enough_data": True}


def _interpret_significance(player_a, player_b, stat, diff, p_value, alpha):
    if pd.isna(p_value):
        return "Not enough usable data or no variation to test."
    if p_value < alpha:
        if diff > 0:
            return f"{player_a} is significantly better at {stat}."
        if diff < 0:
            return f"{player_b} is significantly better at {stat}."
    if diff > 0:
        return f"{player_a} is higher at {stat}, but the difference is not statistically significant."
    if diff < 0:
        return f"{player_b} is higher at {stat}, but the difference is not statistically significant."
    return f"No meaningful difference in {stat}."


def _format_sig_table(df):
    """Format the displayed significance-test table.

    Counting stats display to 1 decimal place.
    Rate stats display up to 4 decimals, with trailing zeros removed.
    Confidence interval columns are removed from the output.
    """
    df = df.copy()

    # Remove confidence interval columns entirely from the displayed table.
    for ci_col in ["95% CI Low", "95% CI High", "CI Low", "CI High", " Low", " High"]:
        if ci_col in df.columns:
            df = df.drop(columns=[ci_col])

    counting_stats = {"R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "AB", "G"}
    rate_stats = {"BA", "OBP", "SLG", "OPS"}

    def fmt_by_stat(stat, value):
        if pd.isna(value):
            return ""
        stat = str(stat).upper()
        try:
            v = float(value)
        except Exception:
            return value

        if stat in rate_stats:
            s = f"{v:.4f}".rstrip("0").rstrip(".")
            if s.startswith("."):
                s = "0" + s
            if s.startswith("-."):
                s = s.replace("-.", "-0.", 1)
            return s

        if stat in counting_stats:
            return f"{v:.1f}"

        return f"{v:.4f}".rstrip("0").rstrip(".")

    for c in ["Player A Avg", "Player B Avg", "Difference"]:
        if c in df.columns and "Stat" in df.columns:
            df[c] = df.apply(lambda r: fmt_by_stat(r["Stat"], r[c]), axis=1)

    if "Test Statistic" in df.columns:
        df["Test Statistic"] = pd.to_numeric(df["Test Statistic"], errors="coerce").round(4)

    if "p-value" in df.columns:
        df["p-value"] = pd.to_numeric(df["p-value"], errors="coerce").round(4)

    return df






def compare_top_changed():
    selected = st.session_state.get("compare_players", [])
    if isinstance(selected, list):
        if len(selected) >= 1:
            st.session_state["pending_sig_player_a"] = selected[0]
        if len(selected) >= 2:
            st.session_state["pending_sig_player_b"] = selected[1]
            record_workflow_comparison_pair(selected[0], selected[1])


def sig_players_changed():
    a = st.session_state.get("sig_player_a_clean")
    b = st.session_state.get("sig_player_b_clean")
    selected = []
    if a:
        selected.append(a)
    if b and b not in selected:
        selected.append(b)
    current = st.session_state.get("compare_players", [])
    if isinstance(current, list):
        for p in current:
            if p not in selected and len(selected) < 3:
                selected.append(p)
    st.session_state["pending_compare_players"] = selected[:3]


if active_page == "Comparison Tool":
    render_section_header("📈 Comparison Tool", "Compare up to three players across years with tables and trend charts.")
    clean_label_map_compare = get_clean_player_label_map_yearly(yearly_df)
    pid_to_clean_label_compare = {pid: lbl for lbl, pid in clean_label_map_compare.items()}
    compare_player_options = list(clean_label_map_compare.keys())

    # Safe two-way sync setup.
    # Apply pending Player A/B changes to the top selector BEFORE the widget is created.
    pending_compare = st.session_state.pop("pending_compare_players", None)
    if isinstance(pending_compare, list) and pending_compare:
        opts_set = set(compare_player_options)
        normalized = [p for p in pending_compare if p in opts_set][:3]
        if not normalized:
            st.warning(
                "Send to Comparison: could not match those names to Lahman player labels. "
                "Try the Comparison page dropdown if the table uses nicknames or extra text."
            )
        else:
            # Drop stale multiselect session so navigation from other pages always applies the send.
            st.session_state.pop("compare_players", None)
            st.session_state["compare_players"] = normalized

    if st.session_state.pop("pending_compare_clear_player_b", False):
        st.session_state.pop("sig_player_b_clean", None)

    default_compare_labels = []
    for _sig_key in ["pending_sig_player_a", "pending_sig_player_b", "sig_player_a_clean", "sig_player_b_clean"]:
        _lbl = st.session_state.get(_sig_key)
        if _lbl in compare_player_options and _lbl not in default_compare_labels:
            default_compare_labels.append(_lbl)

    selected_labels_compare = st.multiselect(
        "Select up to 3 players",
        options=compare_player_options,
        default=default_compare_labels[:3],
        max_selections=3,
        key="compare_players",
        on_change=compare_top_changed
    )
    selected_ids_compare = [clean_label_map_compare[label] for label in selected_labels_compare]
    with st.expander("Chart options", expanded=False):
        stat_choice_compare = st.selectbox("Choose stat to plot", ["R", "HR", "RBI", "SB", "H", "2B", "3B", "AB", "BA", "OBP", "SLG", "OPS", "BB"], index=0, key="compare_stat")
        compare_x_axis_mode = st.radio(
            "Comparison X-Axis",
            ["Season Year", "Player Age"],
            horizontal=True,
            key="compare_x_axis_mode"
        )
        compare_age_range = (20, 40)
        if compare_x_axis_mode == "Player Age":
            compare_age_range = st.slider("Age Range to Compare", 16, 50, (22, 30), key="compare_age_range")
        compare_trend_mode = st.radio(
            "Comparison Chart Mode",
            ["Actual Values", "Smoothed Moving Average"],
            horizontal=True,
            key="compare_trend_mode"
        )
        compare_smooth_window = 3
        if compare_trend_mode == "Smoothed Moving Average":
            compare_smooth_window = st.slider("Comparison Smoothing Window", 2, 7, 3, key="compare_smooth_window")

    if selected_ids_compare:
        compare = yearly_df[yearly_df["playerID"].isin(selected_ids_compare)].copy()
        compare = safe_round_rate_stats(compare)

        st.subheader("Year-by-Year Comparison")
        compare_display = compare[["yearID", "fullName", "R", "H", "2B", "3B", "HR", "RBI", "SB", "AB", "BA", "OBP", "SLG", "OPS"]].sort_values(["fullName", "yearID"]).rename(columns={"yearID": "Year", "fullName": "Player"})
        compare_table = format_display_table(clean_ui_columns(compare_display), count_cols=["Year", "R", "H", "2B", "3B", "HR", "RBI", "SB", "AB"], rate_cols=["BA", "OBP", "SLG", "OPS"])
        render_output_table(compare_table, key="comparison_yearly", file_name="comparison_year_by_year.csv")

        st.subheader("Career Totals")
        career_compare = compare.groupby(["fullName"], as_index=False)[["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]].sum()
        career_compare = add_rate_stats(career_compare)
        career_compare = safe_round_rate_stats(career_compare)
        career_compare_display = career_compare[["fullName", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS"]].sort_values("HR", ascending=False).rename(columns={"fullName": "Player"})
        career_compare_table = format_display_table(clean_ui_columns(career_compare_display), count_cols=["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB"], rate_cols=["BA", "OBP", "SLG", "OPS"])
        render_output_table(career_compare_table, key="comparison_career", file_name="comparison_career_totals.csv")

        st.subheader(f"{stat_choice_compare} Trends")
        fig, ax = plt.subplots(figsize=(10, 5))

        if compare_x_axis_mode == "Player Age":
            compare_age_df = compare.copy()
            if "Age" not in compare_age_df.columns:
                compare_age_df["Age"] = compare_age_df.apply(
                    lambda r: baseball_age_for_season(
                        r.get("yearID"),
                        r.get("birthYear", np.nan),
                        r.get("birthMonth", np.nan),
                        r.get("birthDay", np.nan)
                    ),
                    axis=1
                )
            compare_age_df["Age"] = pd.to_numeric(compare_age_df["Age"], errors="coerce")
            compare_age_df = compare_age_df[
                (compare_age_df["Age"] >= compare_age_range[0]) &
                (compare_age_df["Age"] <= compare_age_range[1])
            ].copy()

            for pid in selected_ids_compare:
                subset = compare_age_df[compare_age_df["playerID"] == pid].sort_values("Age").copy()
                if subset.empty or stat_choice_compare not in subset.columns:
                    continue
                player_name = subset["fullName"].iloc[0]
                y = pd.to_numeric(subset[stat_choice_compare], errors="coerce")
                if compare_trend_mode == "Smoothed Moving Average":
                    y = y.rolling(window=int(compare_smooth_window), min_periods=1).mean()
                    label = f"{player_name} — smoothed"
                else:
                    label = player_name
                ax.plot(subset["Age"], y, marker="o", label=label)

            ax.set_xlabel("Player Age")
            ax.set_title(f"{stat_choice_compare} by Player Age — {compare_age_range[0]} to {compare_age_range[1]}")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        else:
            plot_player_stat_trends(
                ax,
                compare,
                selected_ids_compare,
                stat_choice_compare,
                mode=compare_trend_mode,
                smooth_window=compare_smooth_window
            )
            all_compare_years = sorted(pd.to_numeric(compare["yearID"], errors="coerce").dropna().astype(int).unique())
            ax.set_xticks(all_compare_years)
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_xlabel("Year")
            ax.set_title(f"{stat_choice_compare} Trends — {compare_trend_mode}")

        ax.set_ylabel(stat_choice_compare)
        ax.legend()
        ax.grid(True, alpha=0.3)
        try:
            st.pyplot(fig, clear_figure=True)
        except TypeError:
            st.pyplot(fig)
        plt.close(fig)

        st.subheader("Advanced Trend Intelligence")
        compare_intel = build_advanced_trend_intelligence(compare, selected_ids_compare, stat_choice_compare)
        if compare_intel.empty:
            st.info("Not enough data to generate advanced trend intelligence for the selected players/stat.")
        else:
            st.info(make_advanced_trend_commentary(compare_intel, stat_choice_compare))
            render_output_table(
                format_advanced_trend_table(clean_ui_columns(compare_intel)),
                key="comparison_advanced_trend_intelligence",
                file_name="comparison_advanced_trend_intelligence.csv",
                display_rows=10,
                style_cols=["Slope", "Recent Slope", "Net Change"]
            )


    st.divider()
    st.subheader("Statistical Significance Test")
    with st.expander("How Player A/B sync works with the comparison list", expanded=False):
        st.caption(
            "Compare two players over chosen year ranges. The app tests whether averages differ meaningfully for selected stats, "
            "plus one overall row. The top multiselect and Player A/B below stay in sync via session state on the next rerun."
        )

    sig_col1, sig_col2 = st.columns(2)
    clean_label_map_sig = clean_label_map_compare
    all_player_options_sig = compare_player_options

    # Apply pending top-player changes to Player A/B BEFORE the selectboxes are created.
    pending_a = st.session_state.pop("pending_sig_player_a", None)
    pending_b = st.session_state.pop("pending_sig_player_b", None)
    if pending_a in all_player_options_sig:
        st.session_state["sig_player_a_clean"] = pending_a
    if pending_b in all_player_options_sig:
        st.session_state["sig_player_b_clean"] = pending_b

    # Bottom Player A/B dropdowns show the top-selected comparison players first,
    # but still allow any player in the database.
    sig_priority_options = [p for p in selected_labels_compare if p in all_player_options_sig]
    sig_dropdown_options = sig_priority_options + [p for p in all_player_options_sig if p not in sig_priority_options]

    sig_default_a_index = 0
    sig_default_b_index = 1 if len(sig_dropdown_options) > 1 else 0

    saved_a = st.session_state.get("sig_player_a_clean")
    saved_b = st.session_state.get("sig_player_b_clean")

    if saved_a in sig_dropdown_options:
        sig_default_a_index = sig_dropdown_options.index(saved_a)
    elif len(selected_labels_compare) >= 1 and selected_labels_compare[0] in sig_dropdown_options:
        sig_default_a_index = sig_dropdown_options.index(selected_labels_compare[0])

    if saved_b in sig_dropdown_options:
        sig_default_b_index = sig_dropdown_options.index(saved_b)
    elif len(selected_labels_compare) >= 2 and selected_labels_compare[1] in sig_dropdown_options:
        sig_default_b_index = sig_dropdown_options.index(selected_labels_compare[1])

    with sig_col1:
        sig_player_a_label = st.selectbox(
            "Player A",
            sig_dropdown_options,
            index=sig_default_a_index,
            key="sig_player_a_clean",
            on_change=sig_players_changed
        )
        pid_a_preview = clean_label_map_sig[sig_player_a_label]
        a_min_year, a_max_year = get_player_career_span(yearly_df, pid_a_preview)
        st.caption(f"Career span: {a_min_year}–{a_max_year}")
        if a_min_year == a_max_year:
            st.info(f"Player A only has one available season in the data: {a_min_year}.")
            sig_years_a = (a_min_year, a_max_year)
        else:
            sig_years_a = st.slider(
                "Player A Year Range",
                min_value=a_min_year,
                max_value=a_max_year,
                value=(a_min_year, a_max_year),
                key=f"sig_years_a_{pid_a_preview}"
            )

    with sig_col2:
        sig_player_b_label = st.selectbox(
            "Player B",
            sig_dropdown_options,
            index=sig_default_b_index,
            key="sig_player_b_clean",
            on_change=sig_players_changed
        )
        pid_b_preview = clean_label_map_sig[sig_player_b_label]
        b_min_year, b_max_year = get_player_career_span(yearly_df, pid_b_preview)
        st.caption(f"Career span: {b_min_year}–{b_max_year}")
        if b_min_year == b_max_year:
            st.info(f"Player B only has one available season in the data: {b_min_year}.")
            sig_years_b = (b_min_year, b_max_year)
        else:
            sig_years_b = st.slider(
                "Player B Year Range",
                min_value=b_min_year,
                max_value=b_max_year,
                value=(b_min_year, b_max_year),
                key=f"sig_years_b_{pid_b_preview}"
            )

    sig_stats = st.multiselect(
        "Stats to Test",
        ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"],
        default=["HR", "RBI", "SB", "OPS"],
        key="sig_stats"
    )
    alpha = st.selectbox("Significance Level", [0.10, 0.05, 0.01], index=1, key="sig_alpha")

    if sig_player_a_label and sig_player_b_label and sig_stats:
        pid_a = clean_label_map_sig[sig_player_a_label]
        pid_b = clean_label_map_sig[sig_player_b_label]
        player_a_name = yearly_df.loc[yearly_df["playerID"] == pid_a, "fullName"].dropna().iloc[0] if not yearly_df.loc[yearly_df["playerID"] == pid_a, "fullName"].dropna().empty else sig_player_a_label
        player_b_name = yearly_df.loc[yearly_df["playerID"] == pid_b, "fullName"].dropna().iloc[0] if not yearly_df.loc[yearly_df["playerID"] == pid_b, "fullName"].dropna().empty else sig_player_b_label

        data_a = yearly_df[
            (yearly_df["playerID"] == pid_a) &
            (pd.to_numeric(yearly_df["yearID"], errors="coerce") >= sig_years_a[0]) &
            (pd.to_numeric(yearly_df["yearID"], errors="coerce") <= sig_years_a[1])
        ].copy()
        data_b = yearly_df[
            (yearly_df["playerID"] == pid_b) &
            (pd.to_numeric(yearly_df["yearID"], errors="coerce") >= sig_years_b[0]) &
            (pd.to_numeric(yearly_df["yearID"], errors="coerce") <= sig_years_b[1])
        ].copy()

        if data_a.empty or data_b.empty:
            st.warning("One of the selected players has no data in the selected year range.")
        else:
            sig_rows = []
            overall_z_values = []
            for stat in sig_stats:
                if stat not in data_a.columns or stat not in data_b.columns:
                    continue
                result = _welch_test_summary(data_a[stat], data_b[stat])
                diff = result["difference"]
                p_value = result["p_value"]
                test_stat = result["stat"]
                if pd.notna(test_stat) and np.isfinite(test_stat):
                    overall_z_values.append(test_stat)
                sig_rows.append({
                    "Stat": stat,
                    f"{player_a_name} Years": f"{sig_years_a[0]}-{sig_years_a[1]}",
                    f"{player_b_name} Years": f"{sig_years_b[0]}-{sig_years_b[1]}",
                    "Player A Avg": result["mean1"],
                    "Player B Avg": result["mean2"],
                    "Difference": diff,
                    "Test Statistic": test_stat,
                    "p-value": p_value,
                    "Winner": (
                        player_a_name if pd.notna(diff) and diff > 0 else
                        player_b_name if pd.notna(diff) and diff < 0 else
                        "Tie"
                    ),
                    "Significance Result": (
                        "Significant" if pd.notna(p_value) and p_value < alpha else
                        "Borderline" if pd.notna(p_value) and p_value < 0.10 else
                        "Not significant"
                    ),
                    "Interpretation": _interpret_significance(player_a_name, player_b_name, stat, diff, p_value, alpha)
                })

            sig_df = pd.DataFrame(sig_rows)
            if sig_df.empty:
                st.warning("No valid stats were available for testing.")
            else:
                # Calculate and append the OVERALL row BEFORE rendering the table,
                # so the user actually sees it inside the displayed output.
                valid_z = [z for z in overall_z_values if pd.notna(z) and np.isfinite(z)]
                if len(valid_z) >= 2:
                    overall_score = float(np.mean(valid_z))
                    overall_strength = abs(overall_score)

                    if overall_strength >= 1.96:
                        overall_winner = player_a_name if overall_score > 0 else player_b_name
                        overall_interpretation = (
                            f"{overall_winner} has the stronger overall profile across the selected stats, and the combined result is statistically significant."
                        )
                    elif overall_strength >= 1.00:
                        overall_winner = player_a_name if overall_score > 0 else player_b_name
                        overall_interpretation = (
                            f"{overall_winner} has the better overall profile across the selected stats, but the combined edge is not statistically significant."
                        )
                    else:
                        overall_winner = "Not significant"
                        overall_interpretation = (
                            "Overall result: no statistically meaningful difference across the selected stats."
                        )

                    overall_row = {
                        "Stat": "OVERALL",
                        f"{player_a_name} Years": f"{sig_years_a[0]}-{sig_years_a[1]}",
                        f"{player_b_name} Years": f"{sig_years_b[0]}-{sig_years_b[1]}",
                        "Player A Avg": np.nan,
                        "Player B Avg": np.nan,
                        "Difference": overall_score,
                        "Test Statistic": overall_score,
                        "p-value": _normal_two_sided_p_from_z(overall_score),
                        "Winner": overall_winner,
                        "Significance Result": ("Significant" if _normal_two_sided_p_from_z(overall_score) < alpha else "Not significant"),
                        "Interpretation": overall_interpretation
                    }
                else:
                    overall_row = {
                        "Stat": "OVERALL",
                        f"{player_a_name} Years": f"{sig_years_a[0]}-{sig_years_a[1]}",
                        f"{player_b_name} Years": f"{sig_years_b[0]}-{sig_years_b[1]}",
                        "Player A Avg": np.nan,
                        "Player B Avg": np.nan,
                        "Difference": np.nan,
                        "Test Statistic": np.nan,
                        "p-value": np.nan,
                        "Winner": "Not enough data",
                        "Significance Result": "Not enough data",
                        "Interpretation": "Not enough valid stat tests to make an overall comparison."
                    }

                sig_df = pd.concat([sig_df, pd.DataFrame([overall_row])], ignore_index=True)

                st.caption(
                    "Color guide: Difference/Test Statistic/p-value are green when Player A is significantly higher, "
                    "red when Player B is significantly higher, and gray when the result is not statistically significant. "
                    "The Winner column shows who had the higher average stat, while Significance Result tells whether that difference is statistically meaningful."
                )

                render_output_table(
                    _format_sig_table(clean_ui_columns(sig_df)),
                    key="comparison_significance_tests",
                    file_name="comparison_significance_tests.csv",
                    display_rows=50,
                    style_cols=["Difference", "Test Statistic"]
                )


if active_page == "Trend Value":
    render_section_header("🔥 Trend Value", "Analyze trend direction, volatility, consistency, breakout momentum, decline risk, and fantasy relevance over recent seasons.")
    c1, c2 = st.columns(2)
    with c1:
        lag_trend = st.selectbox("Trend Window (Years)", [3, 4, 5], index=0, key="trend_lag")
    with c2:
        min_g_trend = st.number_input("Minimum Games Played", 0, 800, 50, key="trend_min_g")

    max_year_trend = int(yearly_df["yearID"].max())
    recent_years_trend = list(range(max_year_trend - lag_trend + 1, max_year_trend + 1))
    st.write(f"Analyzing seasons: **{recent_years_trend[0]}–{recent_years_trend[-1]}**")
    st.caption(f"Trend estimates are next-season estimates for **{max_year_trend + 1}**, calculated as the player's latest season value plus the yearly trend slope from the selected window.")
    recent_baseline_trend = yearly_df[yearly_df["yearID"].isin(recent_years_trend)].copy().sort_values(["playerID", "yearID"])
    recent_data_trend = recent_baseline_trend.copy()

    st.markdown("#### Draft Room Sync")
    trend_sync_enabled = st.checkbox(
        "Remove already drafted players and allow drafting from Trend page",
        value=True,
        key="trend_use_draft_room_sync"
    )
    trend_drafted_names = []
    trend_sync_team = None
    if trend_sync_enabled:
        trend_room_table = st.session_state.get("draft_room_table", pd.DataFrame()).copy()
        if not trend_room_table.empty and "Player" in trend_room_table.columns:
            trend_drafted_names = trend_room_table["Player"].dropna().astype(str).str.strip().tolist()
            trend_team_options = get_draft_room_team_options()
            if trend_team_options:
                default_trend_team = st.session_state.get("room_your_team", trend_team_options[0])
                default_trend_idx = trend_team_options.index(default_trend_team) if default_trend_team in trend_team_options else 0
                trend_sync_team = st.selectbox(
                    "My Draft Room Team",
                    trend_team_options,
                    index=default_trend_idx,
                    key="trend_sync_team_for_draft"
                )
            st.caption(f"Removed {len(set(trend_drafted_names))} already drafted player(s) from Trend page views.")
        else:
            st.caption("No Draft Room picks found yet.")

    if trend_sync_enabled and trend_drafted_names:
        recent_data_trend = recent_data_trend[~recent_data_trend["fullName"].astype(str).isin(set(trend_drafted_names))].copy()

    agg_trend = recent_data_trend.groupby(["playerID", "fullName", "bats"], as_index=False)[["G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]].sum()
    agg_trend = add_rate_stats(agg_trend)
    agg_trend = agg_trend[agg_trend["G"] >= min_g_trend].copy()
    agg_trend = apply_stat_min_filters(agg_trend, "trend")

    _trend_slope_cols = [
        "R_trend", "H_trend", "2B_trend", "3B_trend", "HR_trend", "RBI_trend", "SB_trend", "BB_trend",
        "BA_trend", "OBP_trend", "SLG_trend", "OPS_trend",
    ]
    if recent_data_trend.empty:
        trend_table = pd.DataFrame(columns=["playerID"] + _trend_slope_cols)
    else:
        def _trend_slopes_for_player(g):
            return pd.Series({
                "R_trend": compute_trend_slope(g, "R"), "H_trend": compute_trend_slope(g, "H"),
                "2B_trend": compute_trend_slope(g, "2B"), "3B_trend": compute_trend_slope(g, "3B"),
                "HR_trend": compute_trend_slope(g, "HR"), "RBI_trend": compute_trend_slope(g, "RBI"),
                "SB_trend": compute_trend_slope(g, "SB"), "BB_trend": compute_trend_slope(g, "BB"),
                "BA_trend": compute_trend_slope(g, "BA"), "OBP_trend": compute_trend_slope(g, "OBP"),
                "SLG_trend": compute_trend_slope(g, "SLG"), "OPS_trend": compute_trend_slope(g, "OPS"),
            })

        _gb = recent_data_trend.groupby("playerID", group_keys=False)
        try:
            trend_table = _gb.apply(_trend_slopes_for_player, include_groups=False).reset_index()
        except TypeError:
            trend_table = _gb.apply(_trend_slopes_for_player).reset_index()
        if trend_table.columns.duplicated().any():
            trend_table = trend_table.loc[:, ~trend_table.columns.duplicated()]

    trend_value_df = agg_trend.merge(trend_table, on="playerID", how="left")
    trend_value_df = add_latest_and_projection_columns(trend_value_df, recent_data_trend)

    trend_display = trend_value_df[["fullName", "bats", "R_trend", "H_trend", "2B_trend", "3B_trend", "HR_trend", "RBI_trend", "SB_trend", "BB_trend", "BA_trend", "OBP_trend", "SLG_trend", "OPS_trend"]].copy()
    trend_display.columns = ["Player", "Bats", "R Δ", "H Δ", "2B Δ", "3B Δ", "HR Δ", "RBI Δ", "SB Δ", "BB Δ", "BA Δ", "OBP Δ", "SLG Δ", "OPS Δ"]

    sort_col = st.selectbox("Sort By Trend", ["R Δ", "H Δ", "2B Δ", "3B Δ", "HR Δ", "RBI Δ", "SB Δ", "BB Δ", "BA Δ", "OBP Δ", "SLG Δ", "OPS Δ"], index=11, key="trend_sort_col")
    trend_label_to_column = {"R Δ": "R_trend", "H Δ": "H_trend", "2B Δ": "2B_trend", "3B Δ": "3B_trend", "HR Δ": "HR_trend", "RBI Δ": "RBI_trend", "SB Δ": "SB_trend", "BB Δ": "BB_trend", "BA Δ": "BA_trend", "OBP Δ": "OBP_trend", "SLG Δ": "SLG_trend", "OPS Δ": "OPS_trend"}
    selected_trend_col = trend_label_to_column[sort_col]
    selected_trend_name = sort_col.replace(" Δ", "")
    selected_values = pd.to_numeric(trend_value_df[selected_trend_col], errors="coerce")

    c3m, c4m, c5m = st.columns(3)
    if selected_trend_name in RATE_STATS:
        c3m.metric(f"Best {selected_trend_name} Trend", fmt_rate_4(selected_values.max()))
        c4m.metric(f"Worst {selected_trend_name} Trend", fmt_rate_4(selected_values.min()))
        c5m.metric(f"Average {selected_trend_name} Trend", fmt_rate_4(selected_values.mean()))
    else:
        c3m.metric(f"Best {selected_trend_name} Trend", fmt_count_1(selected_values.max()))
        c4m.metric(f"Worst {selected_trend_name} Trend", fmt_count_1(selected_values.min()))
        c5m.metric(f"Average {selected_trend_name} Trend", fmt_count_1(selected_values.mean()))

    trend_sorted = clean_ui_columns(trend_display.sort_values(sort_col, ascending=False))
    st.subheader("Trend Table")
    st.caption("Showing the top 500 rows. Use filters to narrow the table further. Green cells are improving trends; red cells are declining trends.")
    trend_heat_cols = [c for c in TREND_COUNT_COLS + TREND_RATE_COLS if c in trend_sorted.columns]
    trend_sorted_display = trend_sorted.head(500).copy()
    for col in trend_heat_cols:
        is_rate = col in TREND_RATE_COLS
        trend_sorted_display[col] = trend_sorted_display[col].apply(lambda x, is_rate=is_rate: format_trend_arrow_value(x, is_rate=is_rate))
    styled_trend = trend_sorted_display.style.apply(
        lambda s: [trend_heatmap_style_dynamic(v, s.name) for v in s],
        subset=trend_heat_cols
    )
    st.dataframe(styled_trend, width="stretch", hide_index=True)
    st.download_button(
        "Export CSV for Excel",
        data=_df_to_csv_bytes(trend_sorted),
        file_name="trend_value.csv",
        mime="text/csv",
        width="content",
    )
    compact_player_action_center(
        trend_sorted_display["Player"].dropna().astype(str).tolist(),
        key="trend_table_actions_final",
        default_team=trend_sync_team,
        label="Actions for Trend Table Players",
        user_draft_team=trend_sync_team,
        projection_lookup_df=trend_value_df,
        projection_lookup_name_col="fullName",
        help_text="Trend leaderboard — send players to Comparison, Draft Assistant, or the draft queue without retyping names.",
    )

    breakout_df = trend_value_df[["fullName", "bats", "OPS_trend", "HR_trend", "XBH_noHR_trend", "RBI_trend", "SB_trend"]].copy()
    top_breakouts = breakout_df.sort_values("OPS_trend", ascending=False).head(10)
    biggest_declines = breakout_df.sort_values("OPS_trend", ascending=True).head(10)

    rename_breakout = {"fullName": "Player", "bats": "Bats", "OPS_trend": "OPS Δ", "HR_trend": "HR Δ", "XBH_noHR_trend": "2B+3B Δ", "RBI_trend": "RBI Δ", "SB_trend": "SB Δ"}
    top_breakouts_display = clean_ui_columns(top_breakouts.rename(columns=rename_breakout))
    biggest_declines_display = clean_ui_columns(biggest_declines.rename(columns=rename_breakout))

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("🔥 Top Breakout Players")
        breakout_table = format_display_table(top_breakouts_display, count_cols=["HR Δ", "2B+3B Δ", "RBI Δ", "SB Δ"], rate_cols=["OPS Δ"], count_decimals=1, rate_decimals=4)
        render_output_table(breakout_table, key="top_breakouts", file_name="top_breakouts.csv", style_cols=[c for c in breakout_table.columns if "Δ" in c])
    with c4:
        st.subheader("❄️ Biggest Declines")
        declines_table = format_display_table(biggest_declines_display, count_cols=["HR Δ", "2B+3B Δ", "RBI Δ", "SB Δ"], rate_cols=["OPS Δ"], count_decimals=1, rate_decimals=4)
        render_output_table(declines_table, key="biggest_declines", file_name="biggest_declines.csv", style_cols=[c for c in declines_table.columns if "Δ" in c])

    breakout_decline_players = []
    if "Player" in top_breakouts_display.columns:
        breakout_decline_players += top_breakouts_display["Player"].dropna().astype(str).tolist()
    if "Player" in biggest_declines_display.columns:
        breakout_decline_players += biggest_declines_display["Player"].dropna().astype(str).tolist()
    compact_player_action_center(
        list(dict.fromkeys(breakout_decline_players)),
        key="trend_breakout_decline_actions_final",
        default_team=trend_sync_team,
        label="Actions for Breakout / Decline Players",
        user_draft_team=trend_sync_team,
        projection_lookup_df=trend_value_df,
        projection_lookup_name_col="fullName",
        help_text="Breakout / decline callouts — same actions as the main trend table.",
    )

    st.subheader("Insight Summaries")
    top_breakout_row = trend_value_df.sort_values("OPS_trend", ascending=False).head(1)
    top_decline_row = trend_value_df.sort_values("OPS_trend", ascending=True).head(1)
    if not top_breakout_row.empty: st.success(make_trend_insight_summary(top_breakout_row.iloc[0]))
    if not top_decline_row.empty: st.error(make_trend_insight_summary(top_decline_row.iloc[0]))

    dash_hdr_1, dash_hdr_2 = st.columns([4, 1])
    with dash_hdr_1:
        st.subheader("Single-Player Trend Dashboard")
    with dash_hdr_2:
        if st.button("Reset trend sends", help="Clears Send-to-Trend anchor and multi-player queue", key="trend_clear_send_queue"):
            for _k in ("trend_anchor_fullname", "trend_multi_queue_fullnames", "trend_force_single_label", "trend_force_multi_labels"):
                st.session_state.pop(_k, None)
            st.session_state.pop("single_trend_dashboard_player", None)
            st.session_state.pop("trend_players_multi", None)
            st.rerun()

    full_trend_label_map = get_clean_player_label_map_yearly(yearly_df)
    full_trend_labels = get_sorted_clean_player_label_keys(yearly_df)

    # Streamlit raises if widget session_state is not in options (e.g. plain name vs "Name (years)" label).
    _stp = st.session_state.get("single_trend_dashboard_player")
    if _stp is not None and full_trend_labels and _stp not in full_trend_labels:
        st.session_state.pop("single_trend_dashboard_player", None)
    _tmp_multi = st.session_state.get("trend_players_multi")
    if isinstance(_tmp_multi, list) and full_trend_labels:
        _filtered_multi = [x for x in _tmp_multi if x in full_trend_labels]
        if _filtered_multi != _tmp_multi:
            st.session_state["trend_players_multi"] = _filtered_multi

    if "trend_force_single_label" in st.session_state:
        _tsl = st.session_state.pop("trend_force_single_label")
        if _tsl in full_trend_labels:
            st.session_state["single_trend_dashboard_player"] = _tsl

    if "trend_force_multi_labels" in st.session_state:
        _tml = st.session_state.pop("trend_force_multi_labels")
        _tml = [x for x in _tml if x in full_trend_labels][:3]
        if _tml:
            st.session_state["trend_players_multi"] = _tml

    st.caption(
        "Pick any player from the **full database**. When you use **Send to Trend Page** elsewhere, the **first** player you send anchors this dashboard; "
        "the **last three** sends populate **Player Trend Visualization** below."
    )

    recent_span_df = recent_baseline_trend

    single_trend_label = st.selectbox(
        "Select Player (full database)",
        full_trend_labels,
        key="single_trend_dashboard_player"
    )
    single_trend_id = full_trend_label_map[single_trend_label]
    single_player_name = single_trend_label.split(" (")[0].strip()

    dashboard_stat_options = ["HR", "RBI", "R", "SB", "BA", "OBP", "SLG", "OPS", "H", "BB"]
    default_dashboard_stats = ["HR", "RBI", "R", "SB", "OPS"]
    dashboard_stats = st.multiselect(
        "Stats to graph for selected player",
        dashboard_stat_options,
        default=default_dashboard_stats,
        key="single_trend_dashboard_stats"
    )

    dash_mode_col1, dash_mode_col2 = st.columns(2)
    with dash_mode_col1:
        single_dashboard_mode = st.radio(
            "Single-Player Dashboard Mode",
            ["Actual Values", "Smoothed Moving Average"],
            horizontal=True,
            key="single_trend_dashboard_mode"
        )
    with dash_mode_col2:
        single_dashboard_smooth_window = 3
        if single_dashboard_mode == "Smoothed Moving Average":
            single_dashboard_smooth_window = st.slider(
                "Single-Player Smoothing Window",
                2, 7, 3,
                key="single_trend_dashboard_smooth_window"
            )

    selected_player_history = recent_span_df[recent_span_df["playerID"] == single_trend_id].copy()
    if selected_player_history.empty:
        st.info("No trend history available for that player in the selected window.")
    else:
        selected_player_summary = trend_value_df[trend_value_df["playerID"] == single_trend_id]
        if not selected_player_summary.empty:
            st.info(make_trend_insight_summary(selected_player_summary.iloc[0]))

            trend_snapshot_cols = [
                "fullName", "R_trend", "HR_trend", "RBI_trend", "SB_trend",
                "BA_trend", "OBP_trend", "SLG_trend", "OPS_trend"
            ]
            trend_snapshot = selected_player_summary[[c for c in trend_snapshot_cols if c in selected_player_summary.columns]].rename(columns={
                "fullName": "Player",
                "R_trend": "R Δ",
                "HR_trend": "HR Δ",
                "RBI_trend": "RBI Δ",
                "SB_trend": "SB Δ",
                "BA_trend": "BA Δ",
                "OBP_trend": "OBP Δ",
                "SLG_trend": "SLG Δ",
                "OPS_trend": "OPS Δ",
            })
            render_output_table(
                format_display_table(
                    clean_ui_columns(trend_snapshot),
                    count_cols=["R Δ", "HR Δ", "RBI Δ", "SB Δ"],
                    rate_cols=["BA Δ", "OBP Δ", "SLG Δ", "OPS Δ"],
                    count_decimals=1,
                    rate_decimals=4
                ),
                key="single_player_trend_snapshot",
                file_name="single_player_trend_snapshot.csv",
                display_rows=3,
                style_cols=[c for c in trend_snapshot.columns if "Δ" in c]
            )

        if dashboard_stats:
            plot_single_player_multi_stat_dashboard(
                selected_player_history,
                single_player_name,
                dashboard_stats,
                mode=single_dashboard_mode,
                smooth_window=single_dashboard_smooth_window
            )
        else:
            st.info("Choose at least one stat to graph for the selected player.")

    st.subheader("Player Trend Visualization")
    selected_labels_trend = st.multiselect(
        "Select up to 3 Players to View Trend",
        full_trend_labels,
        max_selections=3,
        key="trend_players_multi"
    )
    selected_ids_trend = [full_trend_label_map[label] for label in selected_labels_trend]
    stat_choice_trend = st.selectbox("Choose Trend Stat to Plot", ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"], key="trend_plot_stat")
    trend_chart_mode = st.radio(
        "Trend Chart Mode",
        ["Actual Values", "Smoothed Moving Average"],
        horizontal=True,
        key="trend_chart_mode"
    )
    trend_smooth_window = 3
    if trend_chart_mode == "Smoothed Moving Average":
        trend_smooth_window = st.slider("Trend Smoothing Window", 2, 7, 3, key="trend_smooth_window")

    if selected_ids_trend:
        player_trend = recent_span_df[recent_span_df["playerID"].isin(selected_ids_trend)].sort_values(["fullName", "yearID"])
        player_trend = safe_round_rate_stats(player_trend)

        fig, ax = plt.subplots(figsize=(10, 5))
        plot_player_stat_trends(
            ax,
            player_trend,
            selected_ids_trend,
            stat_choice_trend,
            mode=trend_chart_mode,
            smooth_window=trend_smooth_window
        )
        trend_years = sorted(pd.to_numeric(player_trend["yearID"], errors="coerce").dropna().astype(int).unique())
        ax.set_xticks(trend_years)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel("Year")
        ax.set_ylabel(stat_choice_trend)
        ax.set_title(f"{stat_choice_trend} Trend Comparison over {lag_trend} Years — {trend_chart_mode}")
        ax.legend()
        ax.grid(True, alpha=0.3)
        try:
            st.pyplot(fig, clear_figure=True)
        except TypeError:
            st.pyplot(fig)
        plt.close(fig)

        st.subheader("Advanced Trend Intelligence")
        trend_intel = build_advanced_trend_intelligence(player_trend, selected_ids_trend, stat_choice_trend)
        if trend_intel.empty:
            st.info("Not enough data to generate advanced trend intelligence for the selected players/stat.")
        else:
            st.info(make_advanced_trend_commentary(trend_intel, stat_choice_trend))
            render_output_table(
                format_advanced_trend_table(clean_ui_columns(trend_intel)),
                key="trend_advanced_intelligence",
                file_name="trend_advanced_intelligence.csv",
                display_rows=10,
                style_cols=["Slope", "Recent Slope", "Net Change"]
            )

        st.subheader("Fantasy-Style Player Notes")
        trend_multi_names = []
        for selected_id_trend in selected_ids_trend:
            player_summary_row = trend_value_df[trend_value_df["playerID"] == selected_id_trend]
            if not player_summary_row.empty:
                trend_multi_names.append(player_summary_row.iloc[0].get("fullName", ""))
                st.info(make_trend_insight_summary(player_summary_row.iloc[0]))
    else:
        st.info("Select one to three players to view trend charts.")


if active_page == "Fantasy Sleepers & Busts":
    render_section_header(
        "🧠 Fantasy Sleepers & Busts",
        "Compare projections against FantasyPros rankings and ADP to find market sleepers and bust risks."
    )

    market_df = load_fantasypros_market_data()
    if market_df.empty:
        st.warning(
            "FantasyPros files were not found. Upload FantasyPros_2026_Draft_H_Rankings.csv and "
            "FantasyPros_2026_Hitter_MLB_ADP_Rankings.csv to the same folder/repository as streamlit_app.py."
        )

    with st.expander("How to read this page", expanded=False):
        st.markdown(
            "**Current Production Score** — recent actual fantasy production from R, HR, RBI, SB and BA/OPS. "
            "**Expected Fantasy Value** — future value from the app’s projection logic. "
            "**Fantasy Edge** = Market Rank − Model Rank; positive means your model likes the player more than the market, negative suggests bust risk. "
            "**Risk / Disagreement** — expert rank spread; higher means more uncertainty."
        )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        fantasy_window = st.selectbox("Projection Window (Years)", [3, 4, 5], index=0, key="fantasy_market_window")
    with c2:
        fantasy_format = st.selectbox("Fantasy Format", ["5x5 Roto", "Points League"], index=0, key="fantasy_market_format")
    with c3:
        fantasy_min_g = st.number_input("Minimum Games", 0, 800, 50, key="fantasy_market_min_g")
    with c4:
        fantasy_min_ab = st.number_input("Minimum AB", 0, 2500, 150, key="fantasy_market_min_ab")

    st.markdown("#### Table filters")
    with st.expander("Sleeper / bust relevance filters", expanded=False):
        st.caption("Narrow draft-relevant players; loosen if tables look empty.")
        sf1, sf2, sf3, sf4 = st.columns(4)
        with sf1:
            sleeper_max_market_rank = st.number_input("Worst Market Rank to Include", 1, 1000, 350, step=10, key="sleeper_max_market_rank")
        with sf2:
            sleeper_max_model_rank = st.number_input("Worst Model Rank to Include", 1, 1000, 350, step=10, key="sleeper_max_model_rank")
        with sf3:
            sleeper_min_proj_hr = st.number_input("Minimum Projected HR", min_value=0, max_value=80, value=0, step=1, key="sleeper_min_proj_hr")
        with sf4:
            sleeper_min_expected_value = st.slider("Minimum Expected Fantasy Value", 0.00, 1.00, 0.10, step=0.01, key="sleeper_min_expected_value")

    st.markdown("#### Draft-Room-Aware Sleeper Filter")
    st.caption(
        "Optional: connect this page to your Draft Room so the sleeper map focuses on available players who fit your current roster needs."
    )
    sleeper_sync_enabled = st.checkbox(
        "Use Draft Room needs and remove already drafted players",
        value=False,
        key="sleeper_use_draft_room_needs"
    )
    sleeper_team_name = None
    sleeper_synced_roster = []
    sleeper_synced_drafted = []
    sleeper_auto_positions = []

    if sleeper_sync_enabled:
        draft_room_for_sleepers = st.session_state.get("draft_room_table", pd.DataFrame()).copy()
        if draft_room_for_sleepers.empty or "Player" not in draft_room_for_sleepers.columns or "Team" not in draft_room_for_sleepers.columns:
            st.warning("No Draft Room picks found yet. Enter picks in Draft Room Simulator first.")
        else:
            draft_room_for_sleepers = draft_room_for_sleepers[
                draft_room_for_sleepers["Player"].astype(str).str.strip() != ""
            ].copy()
            sleeper_team_options = sorted(draft_room_for_sleepers["Team"].dropna().astype(str).unique().tolist())
            if sleeper_team_options:
                sleeper_default_team = st.session_state.get("room_your_team", sleeper_team_options[0])
                sleeper_default_idx = sleeper_team_options.index(sleeper_default_team) if sleeper_default_team in sleeper_team_options else 0
                sleeper_team_name = st.selectbox(
                    "My Draft Room Team",
                    sleeper_team_options,
                    index=sleeper_default_idx,
                    key="sleeper_sync_team"
                )
                sleeper_synced_roster = draft_room_for_sleepers[
                    draft_room_for_sleepers["Team"].astype(str) == str(sleeper_team_name)
                ]["Player"].dropna().astype(str).tolist()
                sleeper_synced_drafted = draft_room_for_sleepers["Player"].dropna().astype(str).tolist()

                st.caption(
                    f"Synced {len(sleeper_synced_roster)} players on your roster and "
                    f"{len(sleeper_synced_drafted)} total drafted players from Draft Room."
                )

    max_year_fantasy = int(yearly_df["yearID"].max())
    fantasy_years = list(range(max_year_fantasy - fantasy_window + 1, max_year_fantasy + 1))
    st.write(f"Analyzing seasons: **{fantasy_years[0]}–{fantasy_years[-1]}**")

    recent_fantasy = yearly_df[yearly_df["yearID"].isin(fantasy_years)].copy().sort_values(["playerID", "yearID"])
    agg_fantasy = recent_fantasy.groupby(["playerID", "fullName", "bats"], as_index=False)[
        ["G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]
    ].sum()
    agg_fantasy = add_rate_stats(agg_fantasy)
    agg_fantasy = agg_fantasy[
        (pd.to_numeric(agg_fantasy["G"], errors="coerce") >= fantasy_min_g) &
        (pd.to_numeric(agg_fantasy["AB"], errors="coerce") >= fantasy_min_ab)
    ].copy()

    fantasy_trends = recent_fantasy.groupby("playerID").apply(lambda g: pd.Series({
        "R_trend": compute_trend_slope(g, "R"), "H_trend": compute_trend_slope(g, "H"),
        "2B_trend": compute_trend_slope(g, "2B"), "3B_trend": compute_trend_slope(g, "3B"),
        "HR_trend": compute_trend_slope(g, "HR"), "RBI_trend": compute_trend_slope(g, "RBI"),
        "SB_trend": compute_trend_slope(g, "SB"), "BB_trend": compute_trend_slope(g, "BB"),
        "BA_trend": compute_trend_slope(g, "BA"), "OBP_trend": compute_trend_slope(g, "OBP"),
        "SLG_trend": compute_trend_slope(g, "SLG"), "OPS_trend": compute_trend_slope(g, "OPS")
    })).reset_index()

    fantasy_df = agg_fantasy.merge(fantasy_trends, on="playerID", how="left")
    fantasy_df = add_latest_and_projection_columns(fantasy_df, recent_fantasy)

    latest_cols = ["playerID", "primaryHistoricalTeamName", "primaryTeamName", "primaryLeague", "careerPrimaryPos", "primaryPos", "yearID", "birthYear", "birthMonth", "birthDay"]
    latest_context = recent_fantasy.sort_values(["playerID", "yearID"]).groupby("playerID").tail(1)[[c for c in latest_cols if c in recent_fantasy.columns]].copy()
    latest_context["Age"] = latest_context.apply(
        lambda r: baseball_age_for_season(r.get("yearID"), r.get("birthYear"), r.get("birthMonth", np.nan), r.get("birthDay", np.nan)),
        axis=1
    )
    fantasy_df = fantasy_df.merge(latest_context, on="playerID", how="left")
    fantasy_df["Team"] = fantasy_df.get("primaryHistoricalTeamName", "").fillna(fantasy_df.get("primaryTeamName", ""))
    fantasy_df["Team"] = fantasy_df["Team"].replace({"ATH": "Athletics", "OAK": "Athletics"}).fillna("Unknown")
    fantasy_df["Primary Position"] = fantasy_df.get("careerPrimaryPos", fantasy_df.get("primaryPos", "DH")).fillna(fantasy_df.get("primaryPos", "DH")).fillna("DH")
    fantasy_df["Primary Position"] = fantasy_df["Primary Position"].replace({"": "DH", "PH": "DH", "PR": "DH"}).fillna("DH")
    fantasy_df["Bats"] = fantasy_df.get("bats", "Unknown").replace({"": "Unknown"}).fillna("Unknown")
    if "primaryLeague" in fantasy_df.columns:
        fantasy_df["League"] = fantasy_df["primaryLeague"].replace({"AL": "American League", "NL": "National League", "": "Unknown"}).fillna("Unknown")
    elif "primaryTeamName" in fantasy_df.columns:
        fantasy_df["League"] = fantasy_df["primaryTeamName"].apply(lambda x: "American League" if x in [team_id_to_name.get(t) for t in AL_TEAMS] else ("National League" if x in [team_id_to_name.get(t) for t in NL_TEAMS] else "Unknown"))
    else:
        fantasy_df["League"] = "Unknown"

    # Safety fix for Athletics/A's franchise color grouping on fantasy scatterplots.
    if "Team" in fantasy_df.columns:
        athletics_mask = fantasy_df["Team"].astype(str).isin(["Athletics", "Oakland Athletics", "OAK", "ATH"])
        fantasy_df.loc[athletics_mask, "League"] = "American League"
    if "primaryTeamName" in fantasy_df.columns:
        athletics_mask2 = fantasy_df["primaryTeamName"].astype(str).isin(["Athletics", "Oakland Athletics", "OAK", "ATH"])
        fantasy_df.loc[athletics_mask2, "League"] = "American League"

    if fantasy_format == "5x5 Roto":
        # Roto rewards balanced category value: R, HR, RBI, SB, BA.
        fantasy_df["Current Production Score"] = (
            normalize_score(fantasy_df["R"]) + normalize_score(fantasy_df["HR"]) + normalize_score(fantasy_df["RBI"]) +
            normalize_score(fantasy_df["SB"]) + normalize_score(fantasy_df["BA"])
        ) / 5
        fantasy_df["Projected Production Score"] = (
            normalize_score(fantasy_df["proj_R"]) + normalize_score(fantasy_df["proj_HR"]) + normalize_score(fantasy_df["proj_RBI"]) +
            normalize_score(fantasy_df["proj_SB"]) + normalize_score(fantasy_df["proj_BA"])
        ) / 5
    else:
        with st.expander("Points League Scoring Settings"):
            p1, p2, p3, p4, p5 = st.columns(5)
            with p1: pts_r = st.number_input("Run", value=1.0, step=0.5, key="fantasy_pts_r")
            with p2: pts_rbi = st.number_input("RBI", value=1.0, step=0.5, key="fantasy_pts_rbi")
            with p3: pts_hr = st.number_input("HR", value=4.0, step=0.5, key="fantasy_pts_hr")
            with p4: pts_sb = st.number_input("SB", value=2.0, step=0.5, key="fantasy_pts_sb")
            with p5: pts_bb = st.number_input("BB", value=1.0, step=0.5, key="fantasy_pts_bb")
            p6, p7, p8 = st.columns(3)
            with p6: pts_h = st.number_input("Hit", value=1.0, step=0.5, key="fantasy_pts_h")
            with p7: pts_2b3b = st.number_input("2B+3B Bonus", value=1.0, step=0.5, key="fantasy_pts_xbh")
            with p8: pts_ab_penalty = st.number_input("AB Penalty", value=0.0, step=0.1, key="fantasy_pts_ab_penalty")
        fantasy_df["Current Points Proxy"] = (
            fantasy_df["R"] * pts_r + fantasy_df["RBI"] * pts_rbi + fantasy_df["HR"] * pts_hr +
            fantasy_df["SB"] * pts_sb + fantasy_df["BB"] * pts_bb + fantasy_df["H"] * pts_h +
            (fantasy_df["2B"] + fantasy_df["3B"]) * pts_2b3b - fantasy_df["AB"] * pts_ab_penalty
        )
        fantasy_df["Projected Points Proxy"] = (
            fantasy_df["proj_R"] * pts_r + fantasy_df["proj_RBI"] * pts_rbi + fantasy_df["proj_HR"] * pts_hr +
            fantasy_df["proj_SB"] * pts_sb + fantasy_df["proj_BB"] * pts_bb + fantasy_df["proj_H"] * pts_h +
            fantasy_df["proj_XBH"] * pts_2b3b - fantasy_df["latest_AB" if "latest_AB" in fantasy_df.columns else "AB"] * pts_ab_penalty
        )
        fantasy_df["Current Production Score"] = normalize_score(fantasy_df["Current Points Proxy"])
        fantasy_df["Projected Production Score"] = normalize_score(fantasy_df["Projected Points Proxy"])

    fantasy_df["Expected Fantasy Value"] = fantasy_df["Projected Production Score"]
    fantasy_df["Model Rank"] = fantasy_df["Projected Production Score"].rank(method="min", ascending=False)
    fantasy_df["Current Rank"] = fantasy_df["Current Production Score"].rank(method="min", ascending=False)
    fantasy_df["Player Key"] = fantasy_df["fullName"].apply(normalize_player_name_for_merge)

    if not market_df.empty:
        fantasy_df = fantasy_df.merge(
            market_df[[c for c in ["Player Key", "ADP", "ADP Rank", "FantasyPros Rank", "Expert Avg Rank", "Expert Std Dev", "Market Rank"] if c in market_df.columns]],
            on="Player Key",
            how="left"
        )
    else:
        for c in ["ADP", "ADP Rank", "FantasyPros Rank", "Expert Avg Rank", "Expert Std Dev", "Market Rank"]:
            fantasy_df[c] = np.nan

    fantasy_df["Market Rank"] = pd.to_numeric(fantasy_df["Market Rank"], errors="coerce")
    fantasy_df["Fantasy Edge"] = fantasy_df["Market Rank"] - fantasy_df["Model Rank"]
    fantasy_df["Projected OPS"] = fantasy_df["proj_OPS"]
    fantasy_df["Projected HR"] = fantasy_df["proj_HR"]
    fantasy_df["Projected RBI"] = fantasy_df["proj_RBI"]
    fantasy_df["Projected SB"] = fantasy_df["proj_SB"]
    fantasy_df["Risk / Disagreement"] = pd.to_numeric(fantasy_df.get("Expert Std Dev"), errors="coerce")

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        standard_fantasy_positions = ["C", "1B", "2B", "3B", "SS", "OF", "DH", "P"]
        existing_fantasy_positions = sorted([
            p for p in fantasy_df["Primary Position"].dropna().astype(str).unique()
            if p.strip() and p not in standard_fantasy_positions and p not in ["PH", "PR"]
        ])
        pos_options_fantasy = standard_fantasy_positions + existing_fantasy_positions
        fantasy_positions = st.multiselect("Primary Position", pos_options_fantasy, default=pos_options_fantasy, key="fantasy_market_positions")
    with f2:
        max_age_fantasy = int(pd.to_numeric(fantasy_df["Age"], errors="coerce").max()) if not fantasy_df.empty else 45
        fantasy_age_range = st.slider("Age Range", 18, max(45, max_age_fantasy), (18, max(45, max_age_fantasy)), key="fantasy_market_age_range")
    with f3:
        st.caption("FantasyPros/ADP matching is optional. Players without market ranks can stay in the pool, but rank-based charts use matched rows.")
    with f4:
        fantasy_top_n = st.slider("Show Top N", 5, 50, 15, key="fantasy_market_top_n")

    if fantasy_positions:
        fantasy_df = fantasy_df[fantasy_df["Primary Position"].isin(fantasy_positions)].copy()
    fantasy_df = fantasy_df[
        (pd.to_numeric(fantasy_df["Age"], errors="coerce") >= fantasy_age_range[0]) &
        (pd.to_numeric(fantasy_df["Age"], errors="coerce") <= fantasy_age_range[1])
    ].copy()

    # Apply sleeper/bust relevance filters to the scatterplot AND output tables.
    if "Market Rank" in fantasy_df.columns:
        fantasy_df = fantasy_df[
            pd.to_numeric(fantasy_df["Market Rank"], errors="coerce").fillna(9999) <= sleeper_max_market_rank
        ].copy()
    if "Model Rank" in fantasy_df.columns:
        fantasy_df = fantasy_df[
            pd.to_numeric(fantasy_df["Model Rank"], errors="coerce").fillna(9999) <= sleeper_max_model_rank
        ].copy()
    if "proj_HR" in fantasy_df.columns:
        fantasy_df = fantasy_df[
            pd.to_numeric(fantasy_df["proj_HR"], errors="coerce").fillna(0) >= sleeper_min_proj_hr
        ].copy()
    if "Projected Production Score" in fantasy_df.columns:
        fantasy_df = fantasy_df[
            pd.to_numeric(fantasy_df["Projected Production Score"], errors="coerce").fillna(0) >= sleeper_min_expected_value
        ].copy()

    if sleeper_sync_enabled:
        if sleeper_synced_drafted:
            fantasy_df = fantasy_df[~fantasy_df["fullName"].astype(str).isin(set(sleeper_synced_drafted))].copy()

        if sleeper_synced_roster and "Primary Position" in fantasy_df.columns:
            sleeper_roster_df = fantasy_df.iloc[0:0].copy()
            # Use the larger pre-filter draft pool if possible by matching names before drafted-player removal.
            # This keeps the position need logic simple and robust.
            roster_names_set = set(sleeper_synced_roster)
            # Derive current roster positions from yearly/fantasy data still available in memory.
            # If not found, skip position narrowing rather than crashing.
            try:
                roster_pos_counts = fantasy_df[fantasy_df["fullName"].isin(roster_names_set)]["Primary Position"].value_counts().to_dict()
            except Exception:
                roster_pos_counts = {}

            target_counts = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1}
            sleeper_auto_positions = [
                pos for pos, target in target_counts.items()
                if int(roster_pos_counts.get(pos, 0)) < target
            ]
            if sleeper_auto_positions:
                use_pos_filter = st.checkbox(
                    f"Focus sleeper page on needed positions: {', '.join(sleeper_auto_positions)}",
                    value=True,
                    key="sleeper_focus_needed_positions"
                )
                if use_pos_filter:
                    fantasy_df = fantasy_df[fantasy_df["Primary Position"].isin(sleeper_auto_positions)].copy()

    if fantasy_df.empty:
        st.warning("No players met the fantasy filters. Try lowering minimum AB/G, expanding age/position filters, or loosening the sleeper/bust relevance filters.")
    else:
        top_sleeper = fantasy_df.sort_values("Fantasy Edge", ascending=False).iloc[0]
        top_bust = fantasy_df.sort_values("Fantasy Edge", ascending=True).iloc[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Top Sleeper", str(top_sleeper["fullName"]))
        m2.metric("Top Bust Risk", str(top_bust["fullName"]))
        m3.metric("Matched Players", f"{fantasy_df['Market Rank'].notna().sum():,.0f}")
        m4.metric("Avg Fantasy Edge", fmt_count_1(fantasy_df["Fantasy Edge"].mean()))

        st.subheader("Fantasy Edge Map: Market Rank vs Model Rank")
        st.caption("Above the diagonal = sleeper value: your model rank is better/lower than the market rank. Below the diagonal = possible bust risk: the market ranks the player better than your model.")

        fantasy_plot_cols = [
            "fullName", "Player", "Team", "Primary Position", "Bats", "League", "Age",
            "Market Rank", "Model Rank", "Fantasy Edge",
            "Expected Fantasy Value",
            "ADP", "FantasyPros Rank", "Expert Std Dev",
            "Projected OPS", "Projected HR", "Projected RBI", "Projected SB"
        ]
        available_fantasy_plot_cols = [col for col in fantasy_plot_cols if col in fantasy_df.columns]
        fantasy_plot_df = fantasy_df[available_fantasy_plot_cols].copy()
        if "fullName" in fantasy_plot_df.columns:
            fantasy_plot_df = fantasy_plot_df.rename(columns={"fullName": "Player"})
        if "Player" not in fantasy_plot_df.columns:
            fantasy_plot_df["Player"] = "Unknown"

        # Make sure optional visual columns exist so tooltips and dropdowns never crash.
        for _col in ["Team", "Primary Position", "Bats", "League"]:
            if _col not in fantasy_plot_df.columns:
                fantasy_plot_df[_col] = "Unknown"
        for _col in ["Age", "Fantasy Edge", "Expected Fantasy Value", "ADP", "FantasyPros Rank", "Expert Std Dev", "Projected OPS", "Projected HR", "Projected RBI", "Projected SB", "Curve Edge"]:
            if _col not in fantasy_plot_df.columns:
                fantasy_plot_df[_col] = np.nan
        fantasy_plot_df = format_fantasy_table(fantasy_plot_df)

        fantasy_color_col = st.selectbox(
            "Color by",
            ["None", "Primary Position", "Bats", "Team", "League"],
            index=1,
            key="fantasy_market_scatter_color"
        )
        fantasy_size_options = [c for c in ["Fantasy Edge", "Curve Edge", "Expected Fantasy Value", "Expert Std Dev", "None"] if c == "None" or c in fantasy_plot_df.columns]
        fantasy_size_col = st.selectbox(
            "Size by",
            fantasy_size_options,
            index=0,
            key="fantasy_market_scatter_size"
        )
        fantasy_view_mode = st.radio(
            "Scatterplot View",
            ["Focused View", "Full Outlier View"],
            horizontal=True,
            key="fantasy_edge_scatter_view_mode",
            help="Focused View keeps the main cluster readable. Full Outlier View expands the axes to include every player/outlier."
        )

        fantasy_trendline_type = st.selectbox(
            "Market Edge Trendline Type",
            ["Linear", "Polynomial (2nd Order)", "Polynomial (3rd Order)", "Logarithmic", "Exponential", "Auto Best Fit"],
            index=5,
            key="fantasy_market_edge_trendline_type",
            help="Auto Best Fit tests linear, polynomial, logarithmic, and exponential curves, then chooses the curve with the highest R². The curve estimates the typical model rank for a given market rank."
        )
        st.caption("Black diagonal = equal ranking. Red curve = expected model rank at each market rank.")

        required_plot_cols = ["Market Rank", "Model Rank"]
        missing_plot_cols = [col for col in required_plot_cols if col not in fantasy_plot_df.columns]
        if missing_plot_cols:
            st.warning("Fantasy Edge Map cannot load yet because these columns are missing: " + ", ".join(missing_plot_cols))
        else:
            chart_source = fantasy_plot_df.dropna(subset=["Market Rank", "Model Rank"]).copy()
            if chart_source.empty:
                st.info("No matched FantasyPros/ADP rows are available for the current filters. Try loosening the rank filters or lowering minimum AB/G.")
            else:
                base = alt.Chart(chart_source).mark_circle(
                    opacity=0.74, stroke="#333333", strokeWidth=0.45
                )
                tooltip_cols = [c for c in [
                    "Player", "Age", "Team", "Primary Position", "Bats",
                    "Market Rank", "Model Rank", "Fantasy Edge",
                    "Curve Edge", "Expected Fantasy Value"
                ] if c in chart_source.columns]
                fantasy_tooltip_specs = [
                    alt.Tooltip("Curve Edge:Q", title="Curve Edge", format=".1f")
                    if c == "Curve Edge"
                    else alt.Tooltip(c, title=c)
                    for c in tooltip_cols
                ]

                if fantasy_view_mode == "Full Outlier View":
                    x_scale = alt.Scale(zero=False, reverse=True)
                    y_scale = alt.Scale(zero=False, reverse=True)
                else:
                    x_domain = _smart_axis_domain(chart_source["Market Rank"])
                    y_domain = _smart_axis_domain(chart_source["Model Rank"])
                    x_scale = alt.Scale(domain=x_domain, zero=False, reverse=True) if x_domain else alt.Scale(zero=False, reverse=True)
                    y_scale = alt.Scale(domain=y_domain, zero=False, reverse=True) if y_domain else alt.Scale(zero=False, reverse=True)

                edge_fit = _best_fit_stats(chart_source, "Market Rank", "Model Rank", fantasy_trendline_type)
                if edge_fit is not None:
                    fit_curve = edge_fit["line_df"].sort_values("Market Rank")
                    chart_source["Curve Expected Model Rank"] = np.interp(
                        pd.to_numeric(chart_source["Market Rank"], errors="coerce"),
                        pd.to_numeric(fit_curve["Market Rank"], errors="coerce"),
                        pd.to_numeric(fit_curve["Model Rank"], errors="coerce")
                    )
                    chart_source["Curve Edge"] = (
                        chart_source["Curve Expected Model Rank"] -
                        pd.to_numeric(chart_source["Model Rank"], errors="coerce")
                    )

                enc = {
                    "x": alt.X("Market Rank:Q", title="Market Rank", scale=x_scale),
                    "y": alt.Y("Model Rank:Q", title="Model Rank", scale=y_scale),
                    "tooltip": fantasy_tooltip_specs,
                }
                color_encoding = _scatter_color_encoding(chart_source, fantasy_color_col)
                if color_encoding is not None:
                    enc["color"] = color_encoding
                size_values = pd.to_numeric(chart_source.get(fantasy_size_col, pd.Series(dtype=float)), errors="coerce")
                if fantasy_size_col != "None" and fantasy_size_col in chart_source.columns and size_values.notna().any():
                    enc["size"] = alt.Size(f"{fantasy_size_col}:Q", title=fantasy_size_col, scale=alt.Scale(range=[25, 350], clamp=True))
                else:
                    base = base.mark_circle(size=85, opacity=0.74, stroke="#333333", strokeWidth=0.45)
                points = base.encode(**enc)
                max_rank = pd.to_numeric(chart_source[["Market Rank", "Model Rank"]].stack(), errors="coerce").max()
                if pd.isna(max_rank) or max_rank <= 1:
                    max_rank = 300
                diagonal_df = pd.DataFrame({"Market Rank": [1, max_rank], "Model Rank": [1, max_rank]})
                diagonal = alt.Chart(diagonal_df).mark_line(color="#111111", strokeDash=[6, 4]).encode(x="Market Rank:Q", y="Model Rank:Q")

                chart_layers = points + diagonal

                if edge_fit is not None:
                    fit_line = (
                        alt.Chart(edge_fit["line_df"])
                        .mark_line(color="#b00020", strokeWidth=3, strokeDash=[10, 4])
                        .encode(
                            x=alt.X("Market Rank:Q", scale=x_scale),
                            y=alt.Y("Model Rank:Q", scale=y_scale),
                        )
                    )
                    chart_layers = chart_layers + fit_line

                st.altair_chart(chart_layers.interactive().properties(height=540), width="stretch")

                if edge_fit is not None:
                    e1, e2, e3, e4 = st.columns(4)
                    e1.metric("Best Curve", edge_fit.get("model_type", fantasy_trendline_type))
                    e2.metric("Correlation (r)", f"{edge_fit['corr']:.3f}" if np.isfinite(edge_fit.get("corr", np.nan)) else "N/A")
                    e3.metric("R²", f"{edge_fit['r2']:.3f}" if np.isfinite(edge_fit.get("r2", np.nan)) else "N/A")
                    e4.metric("Rows Used", f"{edge_fit['n']:,}")
                    st.caption(f"Curve equation: {edge_fit.get('equation', '')}")
                    st.info(fit_interpretation_markdown(edge_fit, "Market Rank", "Model Rank"))

                    # Curve-adjusted edge: expected model rank from market rank minus actual model rank.
                    # Positive means your model is better/lower than the curve expectation for that market rank.
                    curve_df = chart_source.copy()
                    fit_curve = edge_fit["line_df"].sort_values("Market Rank")
                    curve_df["Curve Expected Model Rank"] = np.interp(
                        pd.to_numeric(curve_df["Market Rank"], errors="coerce"),
                        pd.to_numeric(fit_curve["Market Rank"], errors="coerce"),
                        pd.to_numeric(fit_curve["Model Rank"], errors="coerce")
                    )
                    curve_df["Curve Edge"] = curve_df["Curve Expected Model Rank"] - pd.to_numeric(curve_df["Model Rank"], errors="coerce")
                    curve_df["Curve Edge Rank"] = curve_df["Curve Edge"].rank(ascending=False, method="min")
                    curve_cols = [
                        "Player", "Team", "Primary Position", "Age", "Market Rank", "Model Rank",
                        "Fantasy Edge", "Curve Expected Model Rank", "Curve Edge", "Curve Edge Rank"
                    ]
                    curve_display = curve_df[[c for c in curve_cols if c in curve_df.columns]].sort_values("Curve Edge", ascending=False).head(15).copy()
                    for c in ["Curve Expected Model Rank", "Curve Edge"]:
                        if c in curve_display.columns:
                            curve_display[c] = pd.to_numeric(curve_display[c], errors="coerce").map(lambda v: "" if pd.isna(v) else f"{v:.1f}")
                    if "Curve Edge Rank" in curve_display.columns:
                        curve_display["Curve Edge Rank"] = pd.to_numeric(curve_display["Curve Edge Rank"], errors="coerce").round(0).astype("Int64")
                    st.subheader("Curve-Adjusted Sleepers")
                    st.caption(
                        "Curve Expected Model Rank is the rank predicted by the red curve for that player's Market Rank. "
                        "Curve Edge = Curve Expected Model Rank − actual Model Rank. Positive Curve Edge means your model ranks the player better than expected after accounting for the market/model curve."
                    )
                    render_output_table(
                        format_fantasy_table(clean_ui_columns(curve_display)),
                        key="fantasy_curve_adjusted_sleepers",
                        file_name="fantasy_curve_adjusted_sleepers.csv",
                        display_rows=15,
                        style_cols=["Fantasy Edge", "Curve Edge"]
                    )
                    if "Player" in curve_display.columns:
                        compact_player_action_center(
                            curve_display["Player"].dropna().astype(str).tolist(),
                            key="fantasy_curve_actions_final",
                            default_team=sleeper_team_name,
                            label="Actions for curve-adjusted sleepers",
                            user_draft_team=sleeper_team_name,
                            projection_lookup_df=fantasy_df,
                            projection_lookup_name_col="fullName",
                            help_text="Curve-adjusted sleeper short list.",
                        )
                else:
                    st.caption("Advanced market-edge curve unavailable because the selected model needs more valid rows or positive values.")

        # fantasy_df has already been filtered for draft relevance above.
        fantasy_output_pool = fantasy_df.copy()
        sleepers = fantasy_output_pool.sort_values("Fantasy Edge", ascending=False).head(fantasy_top_n).copy()
        busts = fantasy_output_pool.sort_values("Fantasy Edge", ascending=True).head(fantasy_top_n).copy()
        sleepers["Reason"] = sleepers.apply(lambda r: make_fantasy_market_reason(r, "sleeper"), axis=1)
        busts["Reason"] = busts.apply(lambda r: make_fantasy_market_reason(r, "bust"), axis=1)

        display_cols = [
            "fullName", "Team", "Primary Position", "Age", "Market Rank", "Model Rank", "Fantasy Edge",
            "Expected Fantasy Value", "Reason"
        ]
        display_rename = {"fullName": "Player"}
        sleepers_display = sleepers[[c for c in display_cols if c in sleepers.columns]].rename(columns=display_rename)
        busts_display = busts[[c for c in display_cols if c in busts.columns]].rename(columns=display_rename)
        sleepers_display = format_fantasy_table(clean_ui_columns(sleepers_display))
        busts_display = format_fantasy_table(clean_ui_columns(busts_display))

        st.caption("Sleepers and bust risks are filtered by market rank, model rank, projected HR, and expected fantasy value so the output focuses on draftable players rather than fringe names.")

        c8, c9 = st.columns(2)
        with c8:
            st.subheader("🔥 Market Sleepers")
            render_output_table(sleepers_display, key="fantasy_market_sleepers", file_name="fantasy_market_sleepers.csv", style_cols=["Fantasy Edge"])
        with c9:
            st.subheader("⚠️ Market Bust Risks")
            render_output_table(busts_display, key="fantasy_market_busts", file_name="fantasy_market_busts.csv", style_cols=["Fantasy Edge"])

        compact_player_action_center(
            pd.concat([sleepers["fullName"], busts["fullName"]], ignore_index=True).dropna().astype(str).drop_duplicates().tolist(),
            key="sleeper_bust_actions_final",
            default_team=sleeper_team_name,
            label="Actions for Sleeper / Bust Players",
            user_draft_team=sleeper_team_name,
            projection_lookup_df=fantasy_output_pool,
            projection_lookup_name_col="fullName",
            help_text="Sleepers and busts in this section — projection breakdown uses fantasy pool rows.",
        )

        st.subheader("Fantasy Market Insight Summary")
        st.success(
            f"Top sleeper: {top_sleeper['fullName']} has a Fantasy Edge of {fmt_int(top_sleeper['Fantasy Edge'])}. "
            f"Market Rank is {fmt_int(top_sleeper['Market Rank'])}, while your Model Rank is {fmt_int(top_sleeper['Model Rank'])}. "
            f"That means your model values him meaningfully higher than the draft market."
        )
        st.warning(
            f"Top bust risk: {top_bust['fullName']} has a Fantasy Edge of {fmt_int(top_bust['Fantasy Edge'])}. "
            f"Market Rank is {fmt_int(top_bust['Market Rank'])}, while your Model Rank is {fmt_int(top_bust['Model Rank'])}. "
            f"That means the draft market is valuing him higher than your model does."
        )


if active_page == "Draft Assistant Simulator":
    render_section_header(
        "🧩 Draft Assistant Simulator",
        "Decision engine: next-pick rankings, team needs, scarcity, and plain-language explanations—fed by your Draft Room board."
    )
    wf1, wf2 = st.columns([2, 1])
    with wf1:
        st.caption(
            "Enter and edit picks in **Draft Room Simulator**; this page reads them automatically and excludes drafted players from recommendations."
        )
    with wf2:
        st.caption("Workflow: Draft Room → Draft Assistant → back to Draft Room to log the pick.")

    market_df = load_fantasypros_market_data()
    if market_df.empty:
        st.warning(
            "FantasyPros files were not found. Upload FantasyPros_2026_Draft_H_Rankings.csv and "
            "FantasyPros_2026_Hitter_MLB_ADP_Rankings.csv to the same folder/repository as streamlit_app.py."
        )
    else:
        d1, d2, d3 = st.columns(3)
        with d1:
            draft_window = st.selectbox("Projection Window", [3, 4, 5], index=0, key="draft_window")
        with d2:
            draft_format = st.selectbox("League Format", ["5x5 Roto", "Points League"], index=0, key="draft_format")
        with d3:
            draft_top_n = st.slider("Recommendations to Show", 5, 30, 10, key="draft_top_n")

        st.selectbox(
            "Projection style",
            list(PROJECTION_STYLE_OPTIONS),
            index=1,
            key="fantasy_draft_projection_style",
            help=(
                "**Conservative** — stronger regression/shrinkage and peer anchoring; smaller breakout continuation. "
                "**Balanced** — same as the historical default. **Aggressive / Upside** — less pull to medians, "
                "more weight on recent seasons and trend/breakout signals (still capped; not a flat boost to everyone)."
            ),
        )

        with st.expander("ML blend settings (optional)", expanded=False):
            mlb1, mlb2, mlb3 = st.columns(3)
            with mlb1:
                use_ml_in_draft = st.checkbox(
                    "Blend ML projection signal into Draft Fit Score",
                    value=True,
                    key="draft_use_ml_blend",
                    help="Adds a lightweight machine-learning-style projection component to the Draft Assistant score."
                )
            with mlb2:
                ml_blend_weight = st.slider(
                    "ML Signal Weight",
                    0.00, 0.30, 0.12, 0.01,
                    key="draft_ml_blend_weight",
                    help="Higher values make the Draft Assistant trust the ML projection signal more."
                )
            with mlb3:
                ml_min_games_for_signal = st.number_input(
                    "ML Signal Min Recent Games",
                    min_value=0,
                    max_value=500,
                    value=50,
                    step=10,
                    key="draft_ml_min_games_signal"
                )

        max_year_draft = int(yearly_df["yearID"].max())
        draft_years = list(range(max_year_draft - draft_window + 1, max_year_draft + 1))
        recent_draft = yearly_df[yearly_df["yearID"].isin(draft_years)].copy().sort_values(["playerID", "yearID"])

        agg_draft = recent_draft.groupby(["playerID", "fullName", "bats"], as_index=False)[
            ["G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]
        ].sum()
        agg_draft = add_rate_stats(agg_draft)
        agg_draft = agg_draft[(agg_draft["G"] >= 30) & (agg_draft["AB"] >= 75)].copy()

        draft_trends = recent_draft.groupby("playerID").apply(lambda g: pd.Series({
            "R_trend": compute_trend_slope(g, "R"), "HR_trend": compute_trend_slope(g, "HR"),
            "RBI_trend": compute_trend_slope(g, "RBI"), "SB_trend": compute_trend_slope(g, "SB"),
            "BA_trend": compute_trend_slope(g, "BA"), "OPS_trend": compute_trend_slope(g, "OPS"),
            "BB_trend": compute_trend_slope(g, "BB")
        })).reset_index()
        draft_df = agg_draft.merge(draft_trends, on="playerID", how="left")
        draft_df = add_latest_and_projection_columns(draft_df, recent_draft)

        latest_cols = ["playerID", "primaryHistoricalTeamName", "primaryTeamName", "primaryLeague", "careerPrimaryPos", "primaryPos", "yearID", "birthYear", "birthMonth", "birthDay"]
        latest_context = recent_draft.sort_values(["playerID", "yearID"]).groupby("playerID").tail(1)[[c for c in latest_cols if c in recent_draft.columns]].copy()
        latest_context["Age"] = latest_context.apply(
            lambda r: baseball_age_for_season(r.get("yearID"), r.get("birthYear"), r.get("birthMonth", np.nan), r.get("birthDay", np.nan)),
            axis=1
        )
        draft_df = draft_df.merge(latest_context, on="playerID", how="left")
        draft_df["Team"] = draft_df.get("primaryTeamName", "").fillna(draft_df.get("primaryHistoricalTeamName", ""))
        draft_df["Team"] = draft_df["Team"].apply(current_franchise_name)
        draft_df["Primary Position"] = draft_df.get("careerPrimaryPos", draft_df.get("primaryPos", "DH")).fillna(draft_df.get("primaryPos", "DH")).fillna("DH")
        draft_df["Primary Position"] = draft_df["Primary Position"].replace({"": "DH", "PH": "DH", "PR": "DH"}).fillna("DH")
        draft_df["Bats"] = draft_df.get("bats", "Unknown").replace({"": "Unknown"}).fillna("Unknown")
        draft_df["League"] = draft_df.get("primaryLeague", "Unknown").replace({"AL": "American League", "NL": "National League", "": "Unknown"}).fillna("Unknown")
        draft_df["Player Key"] = draft_df["fullName"].apply(normalize_player_name_for_merge)

        market_cols = [c for c in ["Player Key", "ADP", "ADP Rank", "FantasyPros Rank", "Expert Avg Rank", "Expert Std Dev", "Market Rank"] if c in market_df.columns]
        draft_df = draft_df.merge(market_df[market_cols], on="Player Key", how="left")
        draft_df["Market Rank"] = pd.to_numeric(draft_df.get("Market Rank"), errors="coerce")

        if draft_format == "5x5 Roto":
            draft_df["Current Production Score"] = normalize_series(draft_df["R"]) * 0.20 + normalize_series(draft_df["HR"]) * 0.20 + normalize_series(draft_df["RBI"]) * 0.20 + normalize_series(draft_df["SB"]) * 0.20 + normalize_series(draft_df["BA"]) * 0.20
            draft_df["Projected Production Score"] = normalize_series(draft_df["proj_R"]) * 0.20 + normalize_series(draft_df["proj_HR"]) * 0.20 + normalize_series(draft_df["proj_RBI"]) * 0.20 + normalize_series(draft_df["proj_SB"]) * 0.20 + normalize_series(draft_df["proj_BA"]) * 0.20
        else:
            draft_df["Current Production Score"] = normalize_series(draft_df["HR"] * 4 + draft_df["RBI"] + draft_df["R"] + draft_df["SB"] * 2 + draft_df["BB"] + draft_df["OPS"] * 20)
            draft_df["Projected Production Score"] = normalize_series(draft_df["proj_HR"] * 4 + draft_df["proj_RBI"] + draft_df["proj_R"] + draft_df["proj_SB"] * 2 + draft_df["proj_BB"] + draft_df["proj_OPS"] * 20)

        # Realistic projection + modest ML adjustment for the Draft Assistant.
        # Base projection uses regression-to-mean, age context, similar-player anchoring,
        # capped trends, and category-balanced scoring. ML now acts as a small contextual
        # boost/downgrade rather than fully driving the projection.
        draft_df = build_realistic_draft_ml_adjustments(
            draft_df,
            draft_format,
            projection_mode=st.session_state.get("fantasy_draft_projection_style", "Balanced"),
        )
        draft_df["ML Signal Eligible"] = pd.to_numeric(draft_df.get("G", 0), errors="coerce").fillna(0) >= ml_min_games_for_signal
        draft_df.loc[~draft_df["ML Signal Eligible"], "ML Projection Score"] *= 0.90
        draft_df.loc[~draft_df["ML Signal Eligible"], "Expected Fantasy Value"] = (
            pd.to_numeric(draft_df.loc[~draft_df["ML Signal Eligible"], "Expected Fantasy Value"], errors="coerce") * 0.96
        )

        # Blended model score: user controls how much of the modest ML adjustment is used.
        if use_ml_in_draft and ml_blend_weight > 0:
            draft_df["Blended Projection Score"] = normalize_series(
                pd.to_numeric(draft_df["Realistic Base Projection Score"], errors="coerce").fillna(0) * (1 - ml_blend_weight) +
                pd.to_numeric(draft_df["Expected Fantasy Value"], errors="coerce").fillna(0) * ml_blend_weight
            )
        else:
            draft_df["Blended Projection Score"] = draft_df["Realistic Base Projection Score"]

        draft_df["Model Rank"] = draft_df["Blended Projection Score"].rank(ascending=False, method="min")
        draft_df["Fantasy Edge"] = draft_df["Market Rank"] - draft_df["Model Rank"]

        with st.expander("Draft Room connection & pick number", expanded=True):
            st.caption(
                "Picks come from **Draft Room Simulator** (`draft_room_table`). "
                "Choose your fantasy team name so needs and availability match your roster."
            )

            draft_room_table_for_assistant = st.session_state.get("draft_room_table", pd.DataFrame()).copy()

            if draft_room_table_for_assistant.empty or "Player" not in draft_room_table_for_assistant.columns:
                st.warning("No Draft Room picks yet. Add picks in Draft Room Simulator, then return here.")
                drafted_players = []
                my_roster = []
                assistant_team_names = [st.session_state.get("room_your_team", "My Team")]
            else:
                draft_room_table_for_assistant = draft_room_table_for_assistant[
                    draft_room_table_for_assistant["Player"].astype(str).str.strip() != ""
                ].copy()
                assistant_team_names = sorted(draft_room_table_for_assistant["Team"].dropna().astype(str).unique().tolist())
                if not assistant_team_names:
                    assistant_team_names = [st.session_state.get("room_your_team", "My Team")]

            default_team_name = st.session_state.get("room_your_team", assistant_team_names[0])
            default_team_index = assistant_team_names.index(default_team_name) if default_team_name in assistant_team_names else 0

            assistant_my_team_name = st.selectbox(
                "Which Draft Room team is yours?",
                assistant_team_names,
                index=default_team_index,
                key="draft_assistant_synced_team"
            )

            _da_highlight = st.session_state.get("pending_draft_assistant_player")
            if _da_highlight:
                st.info(
                    f"**Highlighted player (from another page):** {_da_highlight}. "
                    "Informational only — does not change scores or write picks."
                )
                if st.button("Dismiss highlight", key="dismiss_draft_assistant_highlight"):
                    st.session_state.pop("pending_draft_assistant_player", None)
                    st.rerun()

            if draft_room_table_for_assistant.empty:
                my_roster = []
                drafted_players = []
            else:
                my_roster = (
                    draft_room_table_for_assistant[
                        draft_room_table_for_assistant["Team"].astype(str) == str(assistant_my_team_name)
                    ]["Player"].dropna().astype(str).tolist()
                )
                drafted_players = (
                    draft_room_table_for_assistant[
                        draft_room_table_for_assistant["Team"].astype(str) != str(assistant_my_team_name)
                    ]["Player"].dropna().astype(str).tolist()
                )

            my_roster = sorted(list(dict.fromkeys([p for p in my_roster if str(p).strip()])))
            drafted_players = sorted(list(dict.fromkeys([p for p in drafted_players if str(p).strip()])))
            drafted_or_owned_players = set(drafted_players).union(set(my_roster))

            s1, s2, s3 = st.columns(3)
            s1.metric("My roster", len(my_roster))
            s2.metric("Other rosters", len(drafted_players))
            s3.metric("League pick #", len(drafted_or_owned_players) + 1)

            total_players_picked = len(drafted_or_owned_players)
            auto_current_pick = total_players_picked + 1

            pick_col1, pick_col2, pick_col3 = st.columns([1, 1, 2])
            with pick_col1:
                pick_adjustment = st.number_input(
                    "Manual pick adjustment",
                    min_value=-50,
                    max_value=50,
                    value=0,
                    step=1,
                    key="draft_pick_adjustment",
                    help="Usually 0. Adjust only if the board and this page disagree on pick number."
                )
            current_pick = max(1, int(auto_current_pick + pick_adjustment))
            with pick_col2:
                st.metric("Pick # for model", current_pick)
            with pick_col3:
                st.caption(
                    f"From Draft Room: {total_players_picked} drafted "
                    f"({len(drafted_players)} others + {len(my_roster)} yours) + 1"
                    + (f"; adjustment {pick_adjustment:+d}." if pick_adjustment else ".")
                )

        # Automatically infer position needs from your synced roster.
        roster_df_auto = draft_df[draft_df["fullName"].isin(set(my_roster))].copy()
        target_position_counts = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0}
        current_position_counts = (
            roster_df_auto["Primary Position"].value_counts().to_dict()
            if not roster_df_auto.empty and "Primary Position" in roster_df_auto.columns
            else {}
        )

        auto_needed_positions = []
        for pos in POSITION_ORDER:
            target = target_position_counts.get(pos, 1)
            current = int(current_position_counts.get(pos, 0))
            if target > 0 and current < target:
                auto_needed_positions.append(pos)

        if not auto_needed_positions:
            auto_needed_positions = ["OF", "DH"]

        # Automatically infer category needs from your roster averages compared with the draft pool.
        if draft_format == "5x5 Roto":
            cat_defs_auto = {"R": "proj_R", "HR": "proj_HR", "RBI": "proj_RBI", "SB": "proj_SB", "BA": "proj_BA"}
            default_cat_fallback = ["HR", "RBI"]
        else:
            cat_defs_auto = {"Power": "proj_HR", "Run Production": "proj_RBI", "Speed": "proj_SB", "Walks/OPS": "proj_OPS", "Volume": "AB"}
            default_cat_fallback = ["Power", "Run Production"]

        auto_category_needs = []
        if not roster_df_auto.empty:
            for label, col in cat_defs_auto.items():
                if col not in roster_df_auto.columns or col not in draft_df.columns:
                    continue
                roster_val = pd.to_numeric(roster_df_auto[col], errors="coerce").mean()
                pool_val = pd.to_numeric(draft_df[col], errors="coerce").mean()
                if pd.notna(roster_val) and pd.notna(pool_val) and roster_val < pool_val:
                    auto_category_needs.append(label)

        if not auto_category_needs:
            auto_category_needs = default_cat_fallback

        roster_means = {}
        pool_means = {}
        _tf_cols = (
            ["proj_R", "proj_HR", "proj_RBI", "proj_SB", "proj_BA", "proj_OBP", "proj_OPS"]
            if draft_format == "5x5 Roto"
            else ["proj_HR", "proj_RBI", "proj_SB", "proj_OPS", "proj_R", "AB", "proj_OBP", "proj_BB"]
        )
        for _c in _tf_cols:
            if _c in roster_df_auto.columns and not roster_df_auto.empty:
                roster_means[_c] = pd.to_numeric(roster_df_auto[_c], errors="coerce").mean()
            if _c in draft_df.columns:
                pool_means[_c] = pd.to_numeric(draft_df[_c], errors="coerce").mean()

        roster_expert_std_mean = None
        pool_expert_std_mean = None
        if "Expert Std Dev" in draft_df.columns:
            _ps = pd.to_numeric(draft_df["Expert Std Dev"], errors="coerce").mean()
            pool_expert_std_mean = float(_ps) if pd.notna(_ps) else None
        if (
            pool_expert_std_mean is not None
            and not roster_df_auto.empty
            and "Expert Std Dev" in roster_df_auto.columns
        ):
            _rs = pd.to_numeric(roster_df_auto["Expert Std Dev"], errors="coerce").mean()
            roster_expert_std_mean = float(_rs) if pd.notna(_rs) else None

        with st.expander("Position & category priorities (auto-filled; override if needed)", expanded=False):
            st.markdown("#### Auto-detected team needs")
            st.caption("Derived from your Draft Room roster. Change only if you want a different build.")
            r1, r2 = st.columns(2)
            with r1:
                needed_positions = st.multiselect(
                    "Positions to prioritize",
                    POSITION_ORDER,
                    default=auto_needed_positions,
                    key=f"draft_need_positions_auto_{assistant_my_team_name}_{'_'.join(auto_needed_positions)}",
                    help="Auto-filled from your Draft Room roster."
                )
            with r2:
                category_options_auto = list(cat_defs_auto.keys())
                category_needs = st.multiselect(
                    "Categories / skills to strengthen",
                    category_options_auto,
                    default=[c for c in auto_category_needs if c in category_options_auto],
                    key=f"draft_category_needs_auto_{assistant_my_team_name}_{'_'.join(auto_category_needs)}",
                    help="Auto-filled vs draft pool averages."
                )

        # Remove every player who is already off the board:
        # players on other rosters + players on my roster.
        available = draft_df[~draft_df["fullName"].isin(drafted_or_owned_players)].copy()


        available["Position Need Bonus"] = available["Primary Position"].apply(lambda p: 0.08 if p in needed_positions else 0.0)
        if draft_format == "5x5 Roto":
            cat_bonus = pd.Series(0.0, index=available.index)
            if "R" in category_needs: cat_bonus += normalize_series(available["proj_R"]) * 0.05
            if "HR" in category_needs: cat_bonus += normalize_series(available["proj_HR"]) * 0.06
            if "RBI" in category_needs: cat_bonus += normalize_series(available["proj_RBI"]) * 0.06
            if "SB" in category_needs: cat_bonus += normalize_series(available["proj_SB"]) * 0.07
            if "BA" in category_needs: cat_bonus += normalize_series(available["proj_BA"]) * 0.05
            available["Category Need Bonus"] = cat_bonus
        else:
            cat_bonus = pd.Series(0.0, index=available.index)
            if "Power" in category_needs: cat_bonus += normalize_series(available["proj_HR"]) * 0.07
            if "Run Production" in category_needs: cat_bonus += normalize_series(available["proj_RBI"] + available["proj_R"]) * 0.06
            if "Speed" in category_needs: cat_bonus += normalize_series(available["proj_SB"]) * 0.05
            if "Walks/OPS" in category_needs: cat_bonus += normalize_series(available["proj_BB"] + available["proj_OPS"] * 50) * 0.05
            if "Volume" in category_needs: cat_bonus += normalize_series(available["AB"]) * 0.04
            available["Category Need Bonus"] = cat_bonus

        available["Risk Penalty"] = normalize_series(pd.to_numeric(available.get("Expert Std Dev", 0), errors="coerce").fillna(0)) * 0.08
        available["Expected Fantasy Value"] = available["Blended Projection Score"]
        # ML component is now a small contextual boost/downgrade based on breakout probability,
        # risk, similar-player anchor, and capped trends.
        available["ML Component"] = normalize_series(available["ML Adjustment"].fillna(0).clip(lower=0)) * ml_blend_weight if use_ml_in_draft else 0.0

        # Position Scarcity Model: value over replacement by position among remaining players.
        # This rewards players who are substantially better than the replacement-level option at their position.
        replacement_depths = {
            "C": 12,
            "1B": 12,
            "2B": 12,
            "3B": 12,
            "SS": 12,
            "OF": 36,
            "DH": 12,
            "P": 12,
        }

        position_summary_rows = []
        replacement_values = {}
        for pos, pos_group in available.groupby("Primary Position"):
            pos_group = pos_group.copy().sort_values("Expected Fantasy Value", ascending=False)
            depth = replacement_depths.get(pos, 12)
            if pos_group.empty:
                continue
            if len(pos_group) >= depth:
                replacement_value = pd.to_numeric(pos_group.iloc[depth - 1]["Expected Fantasy Value"], errors="coerce")
            else:
                replacement_value = pd.to_numeric(pos_group["Expected Fantasy Value"], errors="coerce").min()
            replacement_values[pos] = replacement_value
            top_row = pos_group.iloc[0]
            top_value = pd.to_numeric(top_row.get("Expected Fantasy Value", np.nan), errors="coerce")
            position_summary_rows.append({
                "Position": pos,
                "Available Players": len(pos_group),
                "Replacement Depth": depth,
                "Replacement Value": replacement_value,
                "Top Available": top_row.get("fullName", ""),
                "Top Available Value": top_value,
                "Scarcity Dropoff": top_value - replacement_value if pd.notna(top_value) and pd.notna(replacement_value) else np.nan,
            })

        available["Position Replacement Value"] = available["Primary Position"].map(replacement_values).fillna(available["Expected Fantasy Value"].median())
        available["Position Scarcity Score"] = (
            pd.to_numeric(available["Expected Fantasy Value"], errors="coerce") -
            pd.to_numeric(available["Position Replacement Value"], errors="coerce")
        ).clip(lower=0)
        available["Position Scarcity Bonus"] = normalize_series(available["Position Scarcity Score"]) * 0.12
        # If the position is also a user-selected need, scarcity should matter a bit more.
        available.loc[available["Primary Position"].isin(needed_positions), "Position Scarcity Bonus"] *= 1.25

        available["Availability Probability"] = 1 / (1 + np.exp(-(pd.to_numeric(available.get("Market Rank"), errors="coerce").fillna(current_pick) - float(current_pick)) / 35))
        # Improved Draft Fit Score
        # This score is designed to behave more like a draft-decision model:
        #   1. Expected Fantasy Value = player quality / projected production.
        #   2. Fantasy Edge = where your model disagrees positively with the market.
        #   3. Position Need Bonus = whether this player fills an open roster need.
        #   4. Position Scarcity Bonus = whether this position is drying up quickly.
        #   5. Category Need Bonus = whether the player helps categories you selected.
        #   6. Availability Probability = how likely the player is to still be around later.
        #   7. Risk Penalty = expert disagreement / uncertainty.
        #
        # Higher score = better pick for your team right now.
        base_value_weight = 0.38 - (ml_blend_weight * 0.25 if use_ml_in_draft else 0.0)
        available["Player Value Component"] = normalize_series(available["Expected Fantasy Value"]) * max(base_value_weight, 0.28)
        available["ML Projection Component"] = available["ML Component"]
        available["Market Edge Component"] = normalize_series(available["Fantasy Edge"].fillna(0)) * 0.22
        available["Roster Need Component"] = normalize_series(available["Position Need Bonus"].fillna(0)) * 0.14
        available["Scarcity Component"] = normalize_series(available["Position Scarcity Bonus"].fillna(0)) * 0.12
        available["Category Fit Component"] = normalize_series(available["Category Need Bonus"].fillna(0)) * 0.08

        # Availability urgency: if a strong player is unlikely to last until your next pick,
        # he gets a small urgency boost. If he is very likely to be available later,
        # the app is less aggressive about recommending him now.
        available["Availability Urgency Component"] = (
            1 - pd.to_numeric(available["Availability Probability"], errors="coerce").fillna(0.50)
        ) * 0.06

        available["Risk Component"] = normalize_series(available["Risk Penalty"].fillna(0)) * 0.08

        available["Draft Fit Score"] = (
            available["Player Value Component"] +
            available["ML Projection Component"] +
            available["Market Edge Component"] +
            available["Roster Need Component"] +
            available["Scarcity Component"] +
            available["Category Fit Component"] +
            available["Availability Urgency Component"] -
            available["Risk Component"]
        )

        available["Recommendation Score"] = available["Draft Fit Score"]
        available["Draft Fit Rank"] = available["Draft Fit Score"].rank(ascending=False, method="min")
        available["Recommendation Rank"] = available["Draft Fit Rank"]

        def make_draft_reason(r):
            pieces = []
            if pd.notna(r.get("Fantasy Edge", np.nan)) and r.get("Fantasy Edge", 0) > 0:
                pieces.append(f"your model is {fmt_int(r['Fantasy Edge'])} ranks ahead of the market")
            elif pd.notna(r.get("Fantasy Edge", np.nan)) and r.get("Fantasy Edge", 0) < 0:
                pieces.append("market is higher than your model, so this is less of a value pick")

            # Explain WHY the ML projection boosted the player.
            ml_component = pd.to_numeric(r.get("ML Projection Component", 0), errors="coerce")
            ml_score = pd.to_numeric(r.get("ML Projection Score", np.nan), errors="coerce")

            proj_hr = pd.to_numeric(r.get("proj_HR", r.get("Projected HR", np.nan)), errors="coerce")
            proj_rbi = pd.to_numeric(r.get("proj_RBI", r.get("Projected RBI", np.nan)), errors="coerce")
            proj_r = pd.to_numeric(r.get("proj_R", r.get("Projected R", np.nan)), errors="coerce")
            proj_sb = pd.to_numeric(r.get("proj_SB", r.get("Projected SB", np.nan)), errors="coerce")
            proj_ba = pd.to_numeric(r.get("proj_BA", r.get("Projected BA", np.nan)), errors="coerce")
            proj_ops = pd.to_numeric(r.get("proj_OPS", r.get("Projected OPS", np.nan)), errors="coerce")

            hr_trend = pd.to_numeric(r.get("HR_trend", np.nan), errors="coerce")
            ops_trend = pd.to_numeric(r.get("OPS_trend", np.nan), errors="coerce")
            ba_trend = pd.to_numeric(r.get("BA_trend", np.nan), errors="coerce")
            sb_trend = pd.to_numeric(r.get("SB_trend", np.nan), errors="coerce")

            age = pd.to_numeric(r.get("Age", np.nan), errors="coerce")
            games = pd.to_numeric(r.get("G", np.nan), errors="coerce")
            ab = pd.to_numeric(r.get("AB", np.nan), errors="coerce")

            if pd.notna(ml_component) and ml_component > 0.02:
                ml_reasons = []

                if pd.notna(proj_hr) and proj_hr >= 30:
                    ml_reasons.append(f"major projected power ({fmt_count_1(proj_hr)} HR)")
                elif pd.notna(proj_hr) and proj_hr >= 25:
                    ml_reasons.append(f"strong projected power ({fmt_count_1(proj_hr)} HR)")

                if pd.notna(proj_rbi) and proj_rbi >= 90:
                    ml_reasons.append(f"high RBI projection ({fmt_count_1(proj_rbi)} RBI)")
                elif pd.notna(proj_rbi) and proj_rbi >= 75:
                    ml_reasons.append(f"useful run-production projection ({fmt_count_1(proj_rbi)} RBI)")

                if pd.notna(proj_r) and proj_r >= 90:
                    ml_reasons.append(f"strong run-scoring projection ({fmt_count_1(proj_r)} R)")

                if pd.notna(proj_sb) and proj_sb >= 20:
                    ml_reasons.append(f"plus speed projection ({fmt_count_1(proj_sb)} SB)")
                elif pd.notna(proj_sb) and proj_sb >= 12:
                    ml_reasons.append(f"some speed contribution ({fmt_count_1(proj_sb)} SB)")

                if pd.notna(proj_ops) and proj_ops >= 0.850:
                    ml_reasons.append(f"strong overall bat ({fmt_rate_3(proj_ops)} OPS)")
                elif pd.notna(proj_ops) and proj_ops >= 0.800:
                    ml_reasons.append(f"solid projected OPS ({fmt_rate_3(proj_ops)})")

                if pd.notna(proj_ba) and proj_ba >= 0.275:
                    ml_reasons.append(f"batting-average support ({fmt_rate_3(proj_ba)} BA)")

                if pd.notna(hr_trend) and hr_trend > 2:
                    ml_reasons.append("improving power trend")
                if pd.notna(ops_trend) and ops_trend > 0.020:
                    ml_reasons.append("improving OPS trend")
                if pd.notna(ba_trend) and ba_trend > 0.010:
                    ml_reasons.append("improving batting-average trend")
                if pd.notna(sb_trend) and sb_trend > 2:
                    ml_reasons.append("improving stolen-base trend")

                if pd.notna(age) and 26 <= age <= 30:
                    ml_reasons.append("prime-age profile")
                elif pd.notna(age) and 23 <= age <= 25:
                    ml_reasons.append("young growth/upside profile")

                if pd.notna(games) and games >= 140:
                    ml_reasons.append("stable playing time")
                elif pd.notna(ab) and ab >= 500:
                    ml_reasons.append("strong recent volume")

                if pd.notna(ml_score):
                    if ml_score >= 0.80:
                        ml_prefix = "strong ML projection boost"
                    elif ml_score >= 0.65:
                        ml_prefix = "moderate ML projection boost"
                    else:
                        ml_prefix = "ML projection boost"
                else:
                    ml_prefix = "ML projection boost"

                if ml_reasons:
                    pieces.append(f"{ml_prefix} driven by " + ", ".join(ml_reasons[:4]))
                else:
                    pieces.append(f"{ml_prefix} based on the blended projection, trend, age, and playing-time signal")

            if r.get("Primary Position") in needed_positions:
                pieces.append(f"fills a needed {r.get('Primary Position')} slot")
            if r.get("Position Scarcity Bonus", 0) > 0.05:
                pieces.append(f"has strong value over replacement at {r.get('Primary Position')}")
            if r.get("Category Need Bonus", 0) > 0:
                pieces.append("helps your selected category needs")
            if r.get("Risk Penalty", 0) > 0.04:
                pieces.append("has some expert-disagreement risk")
            if not pieces:
                pieces.append("has one of the strongest expected fantasy value scores among available players")
            return "Recommended because " + ", ".join(pieces) + "."

        available["Reason"] = available.apply(make_draft_reason, axis=1)

        recs = available.sort_values("Draft Fit Score", ascending=False).head(draft_top_n).copy()

        def _team_fit_for_row(r):
            return team_fit_summary_line(
                r,
                draft_format=draft_format,
                needed_positions=needed_positions,
                category_needs=category_needs,
                roster_means=roster_means,
                pool_means=pool_means,
                current_position_counts=dict(current_position_counts),
                target_position_counts=target_position_counts,
                roster_expert_std_mean=roster_expert_std_mean,
                pool_expert_std_mean=pool_expert_std_mean,
            )

        recs["Team fit"] = recs.apply(_team_fit_for_row, axis=1)

        position_meta_by_pos: dict[str, dict] = {}
        _drop_vals: list[float] = []
        for _row in position_summary_rows:
            _p = str(_row.get("Position", "")).strip()
            if not _p:
                continue
            _dv = _row.get("Scarcity Dropoff", np.nan)
            position_meta_by_pos[_p] = {
                "dropoff": _dv,
                "available": int(_row.get("Available Players", 0) or 0),
            }
            if pd.notna(_dv):
                try:
                    _drop_vals.append(float(_dv))
                except (TypeError, ValueError):
                    pass
        median_scarcity_dropoff = float(np.median(_drop_vals)) if _drop_vals else None
        _sb_floor = 12 if draft_format == "5x5 Roto" else 10
        remaining_high_sb_count = (
            int((pd.to_numeric(available["proj_SB"], errors="coerce") >= _sb_floor).sum())
            if "proj_SB" in available.columns
            else 0
        )
        remaining_high_hr_count = (
            int((pd.to_numeric(available["proj_HR"], errors="coerce") >= 22).sum())
            if "proj_HR" in available.columns
            else 0
        )

        def _strategy_for_row(r):
            return draft_strategy_line(
                r,
                draft_format=draft_format,
                current_pick=int(current_pick),
                position_meta_by_pos=position_meta_by_pos,
                median_scarcity_dropoff=median_scarcity_dropoff,
                remaining_high_sb_count=remaining_high_sb_count,
                remaining_high_hr_count=remaining_high_hr_count,
                category_needs=category_needs,
                roster_means=roster_means,
                pool_means=pool_means,
                needed_positions=needed_positions,
                current_position_counts=dict(current_position_counts),
                target_position_counts=target_position_counts,
            )

        recs["Strategy"] = recs.apply(_strategy_for_row, axis=1)
        best_value = available.sort_values("Expected Fantasy Value", ascending=False).head(1).copy()
        best_fit = available.sort_values("Draft Fit Score", ascending=False).head(1).copy()

        st.subheader("Next pick recommendations")
        bv1, bv2 = st.columns(2)
        with bv1:
            if not best_fit.empty:
                bf = best_fit.iloc[0]
                st.success(
                    f"**Primary recommendation:** {bf['fullName']} — Draft Fit {fmt_rate_4(bf.get('Draft Fit Score'))}. "
                    f"Market {fmt_int(bf.get('Market Rank'))}, model {fmt_int(bf.get('Model Rank'))}, edge {fmt_int(bf.get('Fantasy Edge'))}. "
                    f"{bf['Reason']}"
                )
        with bv2:
            if not best_value.empty:
                bv = best_value.iloc[0]
                alt = not best_fit.empty and best_fit.iloc[0]["fullName"] != bv["fullName"]
                if alt:
                    st.info(
                        f"**Highest raw value:** {bv['fullName']} — EFV {fmt_rate_4(bv.get('Expected Fantasy Value'))} "
                        f"(before roster-fit bonuses)."
                    )
                else:
                    st.caption("Best team fit and best raw value align on the same player.")

        rec_cols = ["fullName", "Team", "Primary Position", "Age", "Market Rank", "Model Rank", "Fantasy Edge", "ML Projection Score", "Expected Fantasy Value", "Draft Fit Score", "Team fit", "Strategy", "Reason"]
        recs_display = recs[[c for c in rec_cols if c in recs.columns]].rename(columns={"fullName": "Player"})
        recs_display = format_fantasy_table(clean_ui_columns(recs_display))
        focus_players = st.session_state.get("draft_assistant_focus_players", [])
        if focus_players:
            with st.expander("Draft Assistant focus / watch list", expanded=False):
                st.caption("Players sent here from other pages for draft review.")
                st.write(focus_players)

        st.caption("Recommendation table with roster fit, strategy context, and CSV export.")
        render_output_table(recs_display, key="draft_assistant_recommendations", file_name="draft_assistant_recommendations.csv", style_cols=["Fantasy Edge", "Draft Fit Score"])
        compact_player_action_center(
            recs_display["Player"].dropna().astype(str).tolist(),
            key="draft_assistant_recs_actions_final",
            default_team=assistant_my_team_name,
            label="Actions for recommended picks",
            user_draft_team=assistant_my_team_name,
            projection_lookup_df=draft_df,
            projection_lookup_name_col="fullName",
            help_text="Pick a name from the recommendation table, then send it to another tool in one click.",
        )

        with st.expander("Position scarcity & roster category heatmap", expanded=False):
            st.subheader("Position scarcity")
            st.caption(
                "Top available vs replacement at each position. Larger dropoff = thinner position."
            )
            position_scarcity_df = pd.DataFrame(position_summary_rows)

            if not position_scarcity_df.empty and "DH" not in position_scarcity_df["Position"].astype(str).tolist():
                dh_group = available[available["Primary Position"].astype(str).eq("DH")].copy() if "Primary Position" in available.columns else pd.DataFrame()
                if not dh_group.empty:
                    dh_group = dh_group.sort_values("Expected Fantasy Value", ascending=False)
                    dh_depth = replacement_depths.get("DH", 12)
                    dh_replacement = pd.to_numeric(dh_group.iloc[min(len(dh_group), dh_depth) - 1]["Expected Fantasy Value"], errors="coerce")
                    dh_top = dh_group.iloc[0]
                    dh_top_value = pd.to_numeric(dh_top.get("Expected Fantasy Value", np.nan), errors="coerce")
                    position_scarcity_df = pd.concat([position_scarcity_df, pd.DataFrame([{
                        "Position": "DH",
                        "Available Players": len(dh_group),
                        "Replacement Depth": dh_depth,
                        "Replacement Value": dh_replacement,
                        "Top Available": dh_top.get("fullName", ""),
                        "Top Available Value": dh_top_value,
                        "Scarcity Dropoff": dh_top_value - dh_replacement if pd.notna(dh_replacement) and pd.notna(dh_top_value) else np.nan,
                    }])], ignore_index=True)

            if position_scarcity_df.empty:
                st.info("Position scarcity could not be calculated yet.")
            else:
                position_scarcity_df["Position"] = pd.Categorical(
                    position_scarcity_df["Position"],
                    categories=POSITION_ORDER,
                    ordered=True
                )
                position_scarcity_df = position_scarcity_df.sort_values("Position")
                position_scarcity_display = position_scarcity_df[[
                    "Position", "Available Players", "Replacement Depth", "Replacement Value",
                    "Top Available", "Top Available Value", "Scarcity Dropoff"
                ]].copy()
                position_scarcity_display["Position"] = position_scarcity_display["Position"].astype(str)
                for col in ["Replacement Value", "Top Available Value", "Scarcity Dropoff"]:
                    position_scarcity_display[col] = pd.to_numeric(position_scarcity_display[col], errors="coerce").round(4)
                render_output_table(
                    position_scarcity_display,
                    key="draft_position_scarcity",
                    file_name="draft_position_scarcity.csv",
                    display_rows=20,
                    style_cols=["Scarcity Dropoff"]
                )

            st.subheader("Roster construction heatmap")
            roster_df = draft_df[draft_df["fullName"].isin(set(my_roster))].copy()
            if roster_df.empty:
                st.info("Draft players onto your team in Draft Room to see category strength vs the pool.")
            else:
                if draft_format == "5x5 Roto":
                    cat_defs = {"R": "proj_R", "HR": "proj_HR", "RBI": "proj_RBI", "SB": "proj_SB", "BA": "proj_BA"}
                else:
                    cat_defs = {"Power": "proj_HR", "Run Production": "proj_RBI", "Speed": "proj_SB", "Walks/OPS": "proj_OPS", "Volume": "AB"}
                heat_rows = []
                for label, col in cat_defs.items():
                    roster_val = pd.to_numeric(roster_df.get(col, 0), errors="coerce").sum() if col != "proj_BA" else pd.to_numeric(roster_df.get(col, np.nan), errors="coerce").mean()
                    pool_avg = pd.to_numeric(draft_df.get(col, 0), errors="coerce").mean()
                    pool_std = pd.to_numeric(draft_df.get(col, 0), errors="coerce").std()
                    z = 0 if pd.isna(pool_std) or pool_std == 0 else (roster_val / max(len(roster_df), 1) - pool_avg) / pool_std
                    if z >= 0.75:
                        strength = "Strong"
                    elif z <= -0.75:
                        strength = "Weak"
                    else:
                        strength = "Average"
                    heat_rows.append({"Category": label, "Team Strength": strength, "Strength Score": z})
                heat_df = pd.DataFrame(heat_rows)
                def roster_heat_style(val):
                    try:
                        v = float(val)
                        if v >= 0.75:
                            return "background-color:#006400; color:white; font-weight:bold;"
                        if v > 0:
                            return "background-color:#c6efce; color:#006100;"
                        if v <= -0.75:
                            return "background-color:#8b0000; color:white; font-weight:bold;"
                        if v < 0:
                            return "background-color:#ffc7ce; color:#9c0006;"
                    except Exception:
                        return ""
                    return ""
                st.dataframe(
                    heat_df.style.map(roster_heat_style, subset=["Strength Score"]).format({"Strength Score": "{:.2f}"}),
                    use_container_width=True,
                    hide_index=True
                )


if active_page == "Draft Room Simulator":
    render_section_header(
        "🧾 Draft Room Simulator",
        "Live draft control center: enter picks, track rosters, attach model scores, view team lineups, and grade each roster after the draft."
    )

    dr_track1, dr_track2 = st.columns(2)
    with dr_track1:
        st.caption("**Operations center** — snake draft grid, exportable pick log, and roster views for every team.")
    with dr_track2:
        st.caption("**Draft Assistant** reads this board automatically for next-pick rankings.")

    market_df = load_fantasypros_market_data()

    st.selectbox(
        "Projection style",
        list(PROJECTION_STYLE_OPTIONS),
        index=1,
        key="fantasy_draft_projection_style",
        help=(
            "**Conservative** — stronger pull to league and peer-group medians, tighter caps on trend spikes, "
            "smaller ML up/down tweaks. **Balanced** — original app default. **Aggressive / Upside** — lighter "
            "regression-to-mean, slightly more trust in recent-year counting stats, wider trend caps, and a larger "
            "(still bounded) ML tweak so hot profiles can rank higher."
        ),
    )

    dr_tab_board, dr_tab_rosters, dr_tab_setup = st.tabs(["Board", "Rosters & grades", "League setup & import"])

    with dr_tab_setup:
        dr1, dr2, dr3, dr4 = st.columns(4)
        with dr1:
            room_team_count = st.number_input("Number of Teams", min_value=2, max_value=16, value=2, step=1, key="room_team_count")
        with dr2:
            room_rounds = st.number_input("Rounds", min_value=1, max_value=40, value=20, step=1, key="room_rounds")
        with dr3:
            room_format = st.selectbox("Scoring Format", ["5x5 Roto", "Points League"], index=0, key="room_format")
        with dr4:
            room_window = st.selectbox("Projection Window", [3, 4, 5], index=0, key="room_window")

        default_names = ["Daniel"] + [f"Team {i}" for i in range(2, int(room_team_count) + 1)]
        team_name_text = st.text_area(
            "Team Names, one per line",
            value="\n".join(default_names),
            key="room_team_names",
            help="Put each fantasy team on its own line. The draft table will use these names."
        )
        room_team_names = [x.strip() for x in team_name_text.splitlines() if x.strip()]
        if len(room_team_names) < int(room_team_count):
            room_team_names += [f"Team {i}" for i in range(len(room_team_names) + 1, int(room_team_count) + 1)]
        room_team_names = room_team_names[:int(room_team_count)]

        your_team = st.selectbox("Your Team", room_team_names, index=0, key="room_your_team")

        st.subheader("Import existing draft")
        st.caption(
            "CSV or Excel with Team/Owner and Player columns. Loads into the board below; model scores attach when you view the pick log or rosters."
        )
        imported_draft_file = st.file_uploader(
            "Upload existing draft board CSV or Excel",
            type=["csv", "xlsx", "xls"]
        )
        if imported_draft_file is not None:
            try:
                imported_raw = read_imported_draft_file(imported_draft_file)
                imported_draft = normalize_imported_draft_columns(imported_raw)
                if imported_draft.empty:
                    st.warning("No usable Team/Player rows were found in the uploaded draft.")
                else:
                    if st.button("Load Uploaded Draft Into Draft Room"):
                        st.session_state["draft_room_table"] = imported_draft.copy()
                        st.success(f"Loaded {len(imported_draft)} drafted players into the Draft Room.")
                    st.caption("Uploaded draft preview:")
                    render_output_table(
                        clean_ui_columns(imported_draft.head(50)),
                        key="uploaded_draft_preview",
                        file_name="uploaded_draft_preview.csv",
                        display_rows=50
                    )
            except Exception as e:
                st.error(f"Could not read uploaded draft file: {e}")

    room_team_count = int(st.session_state.get("room_team_count", 2))
    room_rounds = int(st.session_state.get("room_rounds", 20))
    total_picks = room_team_count * room_rounds
    room_format = st.session_state.get("room_format", "5x5 Roto")
    room_window = int(st.session_state.get("room_window", 3))
    _team_lines = st.session_state.get("room_team_names", "")
    room_team_names = [x.strip() for x in str(_team_lines).splitlines() if x.strip()]
    if len(room_team_names) < room_team_count:
        room_team_names += [f"Team {i}" for i in range(len(room_team_names) + 1, room_team_count + 1)]
    room_team_names = room_team_names[:room_team_count]
    your_team = st.session_state.get("room_your_team", room_team_names[0] if room_team_names else "Team 1")

    max_year_room = int(yearly_df["yearID"].max())
    room_years = list(range(max_year_room - int(room_window) + 1, max_year_room + 1))
    recent_room = yearly_df[yearly_df["yearID"].isin(room_years)].copy().sort_values(["playerID", "yearID"])

    agg_room = recent_room.groupby(["playerID", "fullName", "bats"], as_index=False)[
        ["G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]
    ].sum()
    agg_room = add_rate_stats(agg_room)
    agg_room = agg_room[(agg_room["G"] >= 30) & (agg_room["AB"] >= 75)].copy()

    room_trends = recent_room.groupby("playerID").apply(lambda g: pd.Series({
        "R_trend": compute_trend_slope(g, "R"), "HR_trend": compute_trend_slope(g, "HR"),
        "RBI_trend": compute_trend_slope(g, "RBI"), "SB_trend": compute_trend_slope(g, "SB"),
        "BA_trend": compute_trend_slope(g, "BA"), "OPS_trend": compute_trend_slope(g, "OPS"),
        "BB_trend": compute_trend_slope(g, "BB")
    })).reset_index()

    room_df = agg_room.merge(room_trends, on="playerID", how="left")
    room_df = add_latest_and_projection_columns(room_df, recent_room)

    latest_cols_room = ["playerID", "primaryHistoricalTeamName", "primaryTeamName", "primaryLeague", "careerPrimaryPos", "primaryPos", "yearID", "birthYear", "birthMonth", "birthDay"]
    latest_context_room = recent_room.sort_values(["playerID", "yearID"]).groupby("playerID").tail(1)[[c for c in latest_cols_room if c in recent_room.columns]].copy()
    latest_context_room["Age"] = latest_context_room.apply(
        lambda r: baseball_age_for_season(r.get("yearID"), r.get("birthYear"), r.get("birthMonth", np.nan), r.get("birthDay", np.nan)),
        axis=1
    )
    room_df = room_df.merge(latest_context_room, on="playerID", how="left")
    room_df["Team"] = room_df.get("primaryTeamName", "").fillna(room_df.get("primaryHistoricalTeamName", ""))
    room_df["Team"] = room_df["Team"].apply(current_franchise_name)
    room_df["Primary Position"] = room_df.get("careerPrimaryPos", room_df.get("primaryPos", "DH")).fillna(room_df.get("primaryPos", "DH")).fillna("DH")
    room_df["Primary Position"] = room_df["Primary Position"].replace({"": "DH", "PH": "DH", "PR": "DH"}).fillna("DH")
    room_df["Bats"] = room_df.get("bats", "Unknown").replace({"": "Unknown"}).fillna("Unknown")
    room_df["Player Key"] = room_df["fullName"].apply(normalize_player_name_for_merge)

    if not market_df.empty:
        market_cols_room = [c for c in ["Player Key", "ADP", "ADP Rank", "FantasyPros Rank", "Expert Avg Rank", "Expert Std Dev", "Market Rank"] if c in market_df.columns]
        room_df = room_df.merge(market_df[market_cols_room], on="Player Key", how="left")
    else:
        room_df["Market Rank"] = np.nan

    room_df["Market Rank"] = pd.to_numeric(room_df.get("Market Rank"), errors="coerce")

    if room_format == "5x5 Roto":
        room_df["Projected Production Score"] = (
            normalize_series(room_df["proj_R"]) * 0.20 +
            normalize_series(room_df["proj_HR"]) * 0.20 +
            normalize_series(room_df["proj_RBI"]) * 0.20 +
            normalize_series(room_df["proj_SB"]) * 0.20 +
            normalize_series(room_df["proj_BA"]) * 0.20
        )
    else:
        room_df["Projected Production Score"] = normalize_series(
            room_df["proj_HR"] * 4 +
            room_df["proj_RBI"] +
            room_df["proj_R"] +
            room_df["proj_SB"] * 2 +
            room_df["proj_BB"] +
            room_df["proj_OPS"] * 20
        )

    # Realistic projection + modest ML adjustment for draft room.
    # Uses regression-to-mean, similar-player anchoring, capped trends, age curve,
    # breakout probability, and risk assessment to avoid overinflating HR/RBI/OPS-heavy profiles.
    room_df = build_realistic_draft_ml_adjustments(
        room_df,
        room_format,
        projection_mode=st.session_state.get("fantasy_draft_projection_style", "Balanced"),
    )
    room_df["Model Rank"] = room_df["Expected Fantasy Value"].rank(ascending=False, method="min")
    room_df["Fantasy Edge"] = room_df["Market Rank"] - room_df["Model Rank"]

    # Available-player draft fit uses global value + edge. Team-specific need is displayed via roster grades after picks.
    room_df["Draft Fit Score"] = (
        normalize_series(room_df["Expected Fantasy Value"]) * 0.55 +
        normalize_series(room_df["Fantasy Edge"].fillna(0)) * 0.25 +
        normalize_series(room_df["ML Projection Score"].fillna(0)) * 0.20
    )

    player_options_room = [""] + sorted(room_df["fullName"].dropna().unique().tolist())

    if "draft_room_table" not in st.session_state:
        pick_rows = []
        for pick in range(1, total_picks + 1):
            rnd = ((pick - 1) // int(room_team_count)) + 1
            within_round = (pick - 1) % int(room_team_count)
            if rnd % 2 == 1:
                team = room_team_names[within_round]
            else:
                team = room_team_names[::-1][within_round]
            pick_rows.append({"Round": rnd, "Pick": pick, "Team": team, "Player": ""})
        st.session_state["draft_room_table"] = pd.DataFrame(pick_rows)

    current_table = st.session_state.get("draft_room_table", pd.DataFrame())
    has_real_picks = (
        not current_table.empty
        and "Player" in current_table.columns
        and current_table["Player"].astype(str).str.strip().ne("").any()
    )
    if (not has_real_picks) and len(current_table) != total_picks:
        pick_rows = []
        for pick in range(1, total_picks + 1):
            rnd = ((pick - 1) // int(room_team_count)) + 1
            within_round = (pick - 1) % int(room_team_count)
            if rnd % 2 == 1:
                team = room_team_names[within_round]
            else:
                team = room_team_names[::-1][within_round]
            pick_rows.append({"Round": rnd, "Pick": pick, "Team": team, "Player": ""})
        st.session_state["draft_room_table"] = pd.DataFrame(pick_rows)

    with dr_tab_board:
        st.subheader("Live draft board")
        st.caption(
            "Snake-draft grid. **Draft Assistant** reads this state automatically for next-pick rankings "
            "(including **Strategy** hints on scarcity, timing, and value vs ADP — hitter pool only here)."
        )

        # Keep the saved draft table in the non-widget key "draft_room_table".
        # Do not use a data_editor widget key here, because Streamlit can throw
        # StreamlitValueAssignmentNotAllowedError when a keyed widget is also given
        # a default value from session_state.
        edited_draft = st.data_editor(
            st.session_state["draft_room_table"],
            num_rows="fixed",
            use_container_width=True,
            column_config={
                "Team": st.column_config.SelectboxColumn("Team", options=room_team_names, required=True),
                "Player": st.column_config.SelectboxColumn("Player", options=player_options_room),
            }
        )
        st.session_state["draft_room_table"] = edited_draft.copy()
        st.caption("Same board is used by **Fantasy Standings Tracker** when you score this league.")

        pick_info = room_df[[
            "fullName", "Team", "Primary Position", "Market Rank", "Model Rank", "Fantasy Edge",
            "Draft Fit Score", "ML Projection Score", "Expected Fantasy Value",
            "proj_R", "proj_HR", "proj_RBI", "proj_SB", "proj_BA", "proj_OPS"
        ]].rename(columns={"fullName": "Player", "Team": "MLB Team"})

        draft_results = edited_draft.merge(pick_info, on="Player", how="left")
        with st.expander("Pick log with model scores (export)", expanded=False):
            st.caption("Same picks as the board, with market/model columns attached. Open when you need CSV export or a read-only review.")
            result_cols = [
                "Round", "Pick", "Team", "Player", "Primary Position", "MLB Team",
                "Market Rank", "Model Rank", "Fantasy Edge", "Draft Fit Score",
                "ML Projection Score", "Expected Fantasy Value"
            ]
            render_output_table(
                format_fantasy_table(clean_ui_columns(draft_results[[c for c in result_cols if c in draft_results.columns]])),
                key="draft_room_results",
                file_name="draft_room_results.csv",
                display_rows=200,
                style_cols=["Fantasy Edge", "Draft Fit Score"]
            )

    with dr_tab_rosters:
        st.subheader("Roster lineup views")
        st.caption(
            "Lineup-style tables by fantasy team: projections plus model/market scores."
        )

        view_col1, view_col2 = st.columns([1, 2])
        with view_col1:
            roster_team_to_view = st.selectbox(
                "Team to View",
                room_team_names,
                index=room_team_names.index(your_team) if your_team in room_team_names else 0,
                key="draft_room_roster_team_to_view"
            )
        with view_col2:
            show_all_rosters = st.checkbox(
                "Show all team rosters",
                value=False,
                key="draft_room_show_all_rosters"
            )

        if st.button("Generate Roster View"):
            st.session_state["draft_room_roster_view_requested"] = True

        if st.session_state.get("draft_room_roster_view_requested", False):
            if show_all_rosters:
                for _team_name in room_team_names:
                    _roster_view = build_draft_room_roster_view(draft_results, _team_name)
                    st.markdown(f"#### {_team_name} Roster")
                    if _roster_view.empty:
                        st.info(f"No drafted players entered yet for {_team_name}.")
                    else:
                        render_output_table(
                            format_fantasy_table(clean_ui_columns(_roster_view)),
                            key=f"draft_room_roster_view_{_team_name}".replace(" ", "_").replace("/", "_"),
                            file_name=f"draft_room_roster_view_{_team_name}.csv".replace(" ", "_").replace("/", "_"),
                            display_rows=100,
                            style_cols=["Fantasy Edge", "Draft Fit Score"]
                        )
            else:
                roster_view = build_draft_room_roster_view(draft_results, roster_team_to_view)
                st.markdown(f"#### {roster_team_to_view} Roster")
                if roster_view.empty:
                    st.info(f"No drafted players entered yet for {roster_team_to_view}.")
                else:
                    render_output_table(
                        format_fantasy_table(clean_ui_columns(roster_view)),
                        key="draft_room_selected_roster_view",
                        file_name="draft_room_selected_roster_view.csv",
                        display_rows=100,
                        style_cols=["Fantasy Edge", "Draft Fit Score"]
                    )

                    summary = {}
                    for _col in ["Projected HR", "Projected RBI", "Projected R", "Projected SB"]:
                        if _col in roster_view.columns:
                            summary[_col.replace("Projected ", "Total Projected ")] = pd.to_numeric(roster_view[_col], errors="coerce").sum()
                    if "Projected BA" in roster_view.columns:
                        summary["Average Projected BA"] = pd.to_numeric(roster_view["Projected BA"], errors="coerce").mean()
                    if "Projected OPS" in roster_view.columns:
                        summary["Average Projected OPS"] = pd.to_numeric(roster_view["Projected OPS"], errors="coerce").mean()

                    if summary:
                        st.markdown("##### Roster Projection Summary")
                        summary_df = pd.DataFrame([summary])
                        render_output_table(
                            format_fantasy_table(clean_ui_columns(summary_df)),
                            key="draft_room_roster_projection_summary",
                            file_name="draft_room_roster_projection_summary.csv",
                            display_rows=5
                        )

        st.subheader("Post-draft roster grades")
        completed_picks = draft_results[draft_results["Player"].astype(str).str.strip() != ""].copy()
        if completed_picks.empty:
            st.info("Enter draft picks on the Board tab to generate team grades.")
        else:
            grade_rows = []
            for team_name, team_df in completed_picks.groupby("Team"):
                grade_rows.append({
                    "Fantasy Team": team_name,
                    "Players Drafted": len(team_df),
                    "Total Expected Fantasy Value": pd.to_numeric(team_df["Expected Fantasy Value"], errors="coerce").sum(),
                    "Average Expected Fantasy Value": pd.to_numeric(team_df["Expected Fantasy Value"], errors="coerce").mean(),
                    "Average Draft Fit Score": pd.to_numeric(team_df["Draft Fit Score"], errors="coerce").mean(),
                    "Average Fantasy Edge": pd.to_numeric(team_df["Fantasy Edge"], errors="coerce").mean(),
                    "Total HR Projection": pd.to_numeric(team_df["proj_HR"], errors="coerce").sum(),
                    "Total RBI Projection": pd.to_numeric(team_df["proj_RBI"], errors="coerce").sum(),
                    "Total R Projection": pd.to_numeric(team_df["proj_R"], errors="coerce").sum(),
                    "Total SB Projection": pd.to_numeric(team_df["proj_SB"], errors="coerce").sum(),
                    "Average OPS Projection": pd.to_numeric(team_df["proj_OPS"], errors="coerce").mean(),
                })
            grades_df = pd.DataFrame(grade_rows)
            grades_df["Overall Draft Grade Score"] = (
                normalize_series(grades_df["Total Expected Fantasy Value"]) * 0.45 +
                normalize_series(grades_df["Average Draft Fit Score"]) * 0.25 +
                normalize_series(grades_df["Average Fantasy Edge"].fillna(0)) * 0.15 +
                normalize_series(grades_df["Total HR Projection"]) * 0.05 +
                normalize_series(grades_df["Total RBI Projection"]) * 0.05 +
                normalize_series(grades_df["Total SB Projection"]) * 0.05
            )
            grades_df["Draft Room Rank"] = grades_df["Overall Draft Grade Score"].rank(ascending=False, method="min")
            grades_df = grades_df.sort_values("Draft Room Rank")

            render_output_table(
                format_post_draft_roster_grades(format_fantasy_table(clean_ui_columns(grades_df))),
                key="draft_room_roster_grades",
                file_name="draft_room_roster_grades.csv",
                display_rows=30,
                style_cols=["Average Fantasy Edge", "Overall Draft Grade Score"]
            )

            if your_team in grades_df["Fantasy Team"].values:
                your_row = grades_df[grades_df["Fantasy Team"] == your_team].iloc[0]
                st.info(
                    f"{your_team} is currently ranked #{fmt_int(your_row['Draft Room Rank'])} out of {len(grades_df)} teams "
                    f"with an Overall Draft Grade Score of {fmt_rate_4(your_row['Overall Draft Grade Score'])}."
                )



if active_page == "Fantasy Standings Tracker":
    render_section_header(
        "🏆 Fantasy Standings Tracker",
        "Upload current-season player stats and score all drafted fantasy teams by roto or points-league rules."
    )

    with st.expander("What to upload", expanded=False):
        st.markdown(
            "Upload a CSV of current-season hitter stats with player names and columns such as HR, RBI, R, SB, BA, OPS. "
            "The page matches those stats to Draft Room picks and ranks every fantasy team."
        )

    scoring_format_tracker = st.selectbox(
        "Scoring Format",
        ["5x5 Roto", "Points League"],
        index=0,
        key="standings_scoring_format"
    )

    # Do not use a session_state key on file_uploader here.
    # Keyed upload widgets can trigger StreamlitValueAssignmentNotAllowedError
    # when combined with page-state preservation logic.
    stats_source = st.radio(
        "Current Stats Source",
        ["MLB API Auto-Fetch", "Upload CSV"],
        index=0,
        horizontal=True,
        key="standings_stats_source"
    )

    api_season = st.number_input(
        "MLB API Season",
        min_value=2020,
        max_value=2035,
        value=2026,
        step=1,
        key="standings_api_season"
    )

    stats_file = None
    current_stats = pd.DataFrame()

    if stats_source == "Upload CSV":
        stats_file = st.file_uploader(
            "Upload current-season hitter stats CSV",
            type=["csv"]
        )

    draft_import_for_standings = st.file_uploader(
        "Optional: Upload draft board CSV/Excel if Draft Room is empty",
        type=["csv", "xlsx", "xls"]
    )
    if draft_import_for_standings is not None:
        try:
            draft_import_raw = read_imported_draft_file(draft_import_for_standings)
            draft_import_norm = normalize_imported_draft_columns(draft_import_raw)
            if st.button("Use Uploaded Draft Board For Standings"):
                st.session_state["draft_room_table"] = draft_import_norm.copy()
                st.success(f"Loaded {len(draft_import_norm)} picks for standings/trade analysis.")
        except Exception as e:
            st.error(f"Could not read draft board upload: {e}")

    if stats_source == "MLB API Auto-Fetch":
        try:
            current_stats = fetch_mlb_api_hitter_stats(api_season)
            if current_stats.empty:
                st.warning("MLB API returned no hitter stats for the selected season. Try uploading a CSV instead.")
            else:
                st.success(f"Loaded {len(current_stats)} hitter stat rows from the MLB Stats API for {api_season}.")
        except Exception as e:
            st.error(f"MLB API fetch failed: {e}")
            st.info("You can still use this page by switching Current Stats Source to Upload CSV.")

    elif stats_file is not None:
        current_stats = pd.read_csv(stats_file)
        current_stats = normalize_uploaded_stat_columns(current_stats)

    if not current_stats.empty:
        draft_table = st.session_state.get("draft_room_table", pd.DataFrame())
        if draft_table.empty:
            st.warning("No Draft Room picks found yet. Enter picks in Draft Room Simulator first.")
        else:
            drafted = draft_table[draft_table["Player"].astype(str).str.strip() != ""].copy()
            drafted["Player Key"] = drafted["Player"].apply(normalize_player_name_for_merge)
            roster_stats = drafted.merge(current_stats, on="Player Key", how="left", suffixes=("", "_stats"))

            # Prefer uploaded player names/stats, keep draft ownership.
            if "Player_stats" in roster_stats.columns:
                roster_stats["Player"] = roster_stats["Player"].fillna(roster_stats["Player_stats"])

            st.subheader("Drafted Rosters With Current Stats")
            show_cols = ["Team", "Player", "Primary Position", "HR", "RBI", "R", "SB", "BA", "OPS"]
            render_output_table(
                format_fantasy_standings_table(format_fantasy_table(clean_ui_columns(roster_stats[[c for c in show_cols if c in roster_stats.columns]]))),
                key="standings_roster_current_stats",
                file_name="fantasy_rosters_current_stats.csv",
                display_rows=300
            )

            standings = score_fantasy_rosters_from_stats(roster_stats, scoring_format_tracker)
            st.subheader("Live Fantasy Standings")
            render_output_table(
                format_fantasy_standings_table(format_fantasy_table(clean_ui_columns(standings))),
                key="fantasy_live_standings",
                file_name="fantasy_live_standings.csv",
                display_rows=50,
                style_cols=["Total Roto Points", "Estimated Points"]
            )

            st.session_state["fantasy_current_roster_stats"] = roster_stats
            st.session_state["fantasy_current_standings"] = standings
    else:
        st.warning("Choose MLB API Auto-Fetch or upload a current-season stats CSV to calculate standings.")






def build_trade_verdict_text(trade_eval, weighted_gain):
    """Plain-English trade verdict for Fantasy Lineup Assistant."""
    try:
        wg = float(weighted_gain)
    except Exception:
        wg = 0.0

    if wg >= 5:
        verdict = "Strong accept"
        reason = "The trade appears to improve your roster in important need areas."
    elif wg >= 1:
        verdict = "Slight accept"
        reason = "The trade looks modestly helpful, especially if it addresses a weak category or roster need."
    elif wg > -1:
        verdict = "Fair / neutral"
        reason = "The trade is close enough that team context, injury risk, and category needs should decide it."
    elif wg > -5:
        verdict = "Slight decline"
        reason = "The trade appears slightly unfavorable unless it solves a specific roster problem."
    else:
        verdict = "Decline"
        reason = "The trade appears to cost too much projected value or category balance."

    return f"{verdict}: {reason} Team-need weighted score: {wg:.2f}."


def filter_trade_suggestions_by_requested_players(suggestions, forced_give=None, forced_get=None):
    """Filter trade suggestions using optional user-desired give/acquire players."""
    if suggestions is None or suggestions.empty:
        return suggestions
    out = suggestions.copy()
    forced_give = [str(x) for x in (forced_give or []) if str(x).strip()]
    forced_get = [str(x) for x in (forced_get or []) if str(x).strip()]
    if forced_give and "Give" in out.columns:
        out = out[out["Give"].astype(str).isin(forced_give)]
    if forced_get and "Receive" in out.columns:
        out = out[out["Receive"].astype(str).isin(forced_get)]
    return out


if active_page == "Fantasy Lineup Assistant":
    render_section_header(
        "🧠 Fantasy Lineup Assistant / Start-Sit AI",
        "Use current stats, roster context, momentum, consistency, and league format to recommend who to start, bench, sit, or watch."
    )

    st.info(
        "This page uses your Draft Room roster plus current-season stats loaded in Fantasy Standings Tracker. "
        "For now, momentum is based on current season-to-date production because true last-7-day game logs, injuries, matchups, and ballparks would need deeper live data feeds."
    )

    roster_stats = st.session_state.get("fantasy_current_roster_stats", pd.DataFrame()).copy()

    if roster_stats.empty:
        st.warning(
            "No current roster stats found yet. First go to Fantasy Standings Tracker, load stats from MLB API or upload a CSV, "
            "and make sure Draft Room has your roster entered."
        )
    else:
        lineup_teams = sorted(roster_stats["Team"].dropna().astype(str).unique().tolist())
        default_lineup_team = st.session_state.get("room_your_team", lineup_teams[0] if lineup_teams else "")
        default_lineup_idx = lineup_teams.index(default_lineup_team) if default_lineup_team in lineup_teams else 0

        l1, l2, l3 = st.columns(3)
        with l1:
            lineup_team = st.selectbox("Fantasy Team", lineup_teams, index=default_lineup_idx, key="lineup_team")
        with l2:
            lineup_format = st.selectbox(
                "Lineup Scoring Mode",
                ["5x5 Roto", "Points League", "Head-to-Head Categories"],
                index=0,
                key="lineup_format"
            )
        with l3:
            starters_to_show = st.slider("Recommended Starters to Show", 3, 15, 9, key="lineup_starters_to_show")

        custom_weights = None
        if lineup_format == "Points League":
            with st.expander("Custom Points Scoring"):
                pw1, pw2, pw3, pw4 = st.columns(4)
                with pw1:
                    w_r = st.number_input("Run Pts", value=1.0, step=0.5, key="lineup_pts_r")
                    w_rbi = st.number_input("RBI Pts", value=1.0, step=0.5, key="lineup_pts_rbi")
                with pw2:
                    w_hr = st.number_input("HR Pts", value=4.0, step=0.5, key="lineup_pts_hr")
                    w_sb = st.number_input("SB Pts", value=2.0, step=0.5, key="lineup_pts_sb")
                with pw3:
                    w_h = st.number_input("Hit Pts", value=1.0, step=0.5, key="lineup_pts_h")
                    w_bb = st.number_input("Walk Pts", value=1.0, step=0.5, key="lineup_pts_bb")
                with pw4:
                    w_ops = st.number_input("OPS Weight", value=10.0, step=1.0, key="lineup_pts_ops")
                custom_weights = {"R": w_r, "RBI": w_rbi, "HR": w_hr, "SB": w_sb, "H": w_h, "BB": w_bb, "OPS": w_ops}

        team_roster = roster_stats[roster_stats["Team"].astype(str) == str(lineup_team)].copy()
        if team_roster.empty:
            st.warning("No players found for the selected team.")
        else:
            scored = build_lineup_assistant_scores(team_roster, lineup_format, custom_weights)
            scored = scored.sort_values("Lineup Confidence", ascending=False)

            st.subheader("Recommended Starters")
            starter_cols = [
                "Player", "Primary Position", "MLB Team", "Start/Sit Recommendation",
                "Lineup Confidence", "Momentum Score", "Consistency Score", "Volatility Meter",
                "HR", "RBI", "R", "SB", "BA", "OPS", "Lineup Reason"
            ]
            starters = scored.head(starters_to_show).copy()
            render_output_table(
                format_lineup_assistant_table(clean_ui_columns(starters[[c for c in starter_cols if c in starters.columns]])),
                key="lineup_recommended_starters",
                file_name="lineup_recommended_starters.csv",
                display_rows=starters_to_show,
            )

            st.subheader("Bench / Sit / Watch List")
            bench = scored.tail(max(1, min(10, len(scored)))).sort_values("Lineup Confidence", ascending=True).copy()
            render_output_table(
                format_lineup_assistant_table(clean_ui_columns(bench[[c for c in starter_cols if c in bench.columns]])),
                key="lineup_bench_watch",
                file_name="lineup_bench_watch.csv",
                display_rows=10,
            )

            st.subheader("Lineup Intelligence Summary")
            best_row = scored.iloc[0]
            weakest_row = scored.iloc[-1]
            st.success(
                f"Best start candidate: {best_row.get('Player', 'Unknown')} — "
                f"{best_row.get('Lineup Reason', '')}"
            )
            st.warning(
                f"Most questionable option: {weakest_row.get('Player', 'Unknown')} — "
                f"{weakest_row.get('Lineup Reason', '')}"
            )

            st.subheader("Roster Alerts")
            alert_rows = []
            for _, r in scored.iterrows():
                player = r.get("Player", "")
                rec = r.get("Start/Sit Recommendation", "")
                mom = pd.to_numeric(r.get("Momentum Score", np.nan), errors="coerce")
                conf = pd.to_numeric(r.get("Lineup Confidence", np.nan), errors="coerce")
                vol = pd.to_numeric(r.get("Volatility Meter", np.nan), errors="coerce")
                if rec in ["Start", "Lean Start"]:
                    alert_rows.append({"Player": player, "Alert Type": "Start Signal", "Alert": "Strong lineup option based on current production and confidence score."})
                elif rec in ["Sit", "Bench / Risk"]:
                    alert_rows.append({"Player": player, "Alert Type": "Sit / Risk Signal", "Alert": "Lower confidence profile; consider benching unless matchup context is favorable."})
                if pd.notna(mom) and mom >= 0.75 and pd.notna(conf) and conf < 0.60:
                    alert_rows.append({"Player": player, "Alert Type": "High-Upside Volatile", "Alert": "Momentum is interesting, but overall confidence is not elite."})
                if pd.notna(vol) and vol >= 0.75:
                    alert_rows.append({"Player": player, "Alert Type": "Volatility Meter", "Alert": "Higher boom/bust profile; useful in upside-seeking lineup decisions."})

            alerts_df = pd.DataFrame(alert_rows)
            if alerts_df.empty:
                st.info("No major lineup alerts were detected.")
            else:
                render_output_table(
                    clean_ui_columns(alerts_df),
                    key="lineup_alerts",
                    file_name="lineup_alerts.csv",
                    display_rows=30
                )


            st.divider()
            st.subheader("🔁 Trade Analyzer / Roster Move Assistant")
            st.caption(
                "Use this section after reviewing start/sit recommendations. It evaluates proposed trades and suggests roster moves using current stats, standings, and category needs."
            )

            lineup_trade_roster_stats = st.session_state.get("fantasy_current_roster_stats", pd.DataFrame())
            lineup_trade_standings = st.session_state.get("fantasy_current_standings", pd.DataFrame())

            if lineup_trade_roster_stats.empty:
                st.info(
                    "First use the Fantasy Standings Tracker page and load current-season stats. "
                    "Then this trade section can evaluate deals using those live/current stats."
                )
            else:
                trade_teams = sorted(lineup_trade_roster_stats["Team"].dropna().astype(str).unique())
                default_trade_idx = trade_teams.index(lineup_team) if lineup_team in trade_teams else 0
                my_team_trade = st.selectbox("Trade Analyzer: Your Team", trade_teams, index=default_trade_idx, key="lineup_trade_my_team")
                other_trade_teams = [t for t in trade_teams if t != my_team_trade]

                if not other_trade_teams:
                    st.info("Need at least two fantasy teams in Draft Room/current stats to analyze trades.")
                else:
                    other_team_trade = st.selectbox("Other Team", other_trade_teams, index=0, key="lineup_trade_other_team")

                    my_trade_players = sorted(
                        lineup_trade_roster_stats[lineup_trade_roster_stats["Team"] == my_team_trade]["Player"]
                        .dropna().astype(str).unique()
                    )
                    other_trade_players = sorted(
                        lineup_trade_roster_stats[lineup_trade_roster_stats["Team"] == other_team_trade]["Player"]
                        .dropna().astype(str).unique()
                    )

                    st.markdown("##### Analyze a Proposed Trade")
                    pending_give = [p for p in st.session_state.get("pending_trade_away_players", []) if p in my_trade_players]
                    pending_get = [p for p in st.session_state.get("pending_trade_acquire_players", []) if p in other_trade_players]
                    give_players = st.multiselect("Players You Give Up", my_trade_players, default=pending_give, key="lineup_trade_give_players")
                    get_players = st.multiselect("Players You Receive", other_trade_players, default=pending_get, key="lineup_trade_get_players")

                    if give_players and get_players:
                        trade_eval, verdict, weighted_gain = evaluate_trade(
                            give_players,
                            get_players,
                            lineup_trade_roster_stats,
                            lineup_trade_roster_stats,
                            lineup_trade_standings,
                            my_team_trade
                        )
                        st.metric("Trade Verdict", verdict)
                        st.caption(build_trade_verdict_text(trade_eval, weighted_gain))
                        render_output_table(
                            format_trade_eval_table(clean_ui_columns(trade_eval)),
                            key="lineup_trade_eval_table",
                            file_name="lineup_trade_evaluation.csv",
                            display_rows=20,
                            style_cols=["Net Gain"]
                        )

                    st.markdown("##### Generate Trade Ideas")
                    st.caption(
                        "The app looks for trades that are somewhat fair while improving your weak categories. "
                        "For example, if you are low in batting average but strong in power, it may suggest trading power for AVG/OPS."
                    )

                    trade_mode = st.radio(
                        "Trade Idea Mode",
                        [
                            "General fair-but-helpful ideas",
                            "I want to trade away specific player(s)",
                            "I want to acquire specific player(s)",
                            "I want to choose both trade-away and acquire targets"
                        ],
                        horizontal=False,
                        key="lineup_trade_idea_mode"
                    )

                    forced_give = []
                    forced_get = []
                    if trade_mode in ["I want to trade away specific player(s)", "I want to choose both trade-away and acquire targets"]:
                        forced_give = st.multiselect(
                            "Player(s) on my team I am willing to trade away",
                            my_trade_players,
                            key="lineup_trade_ideas_forced_give"
                        )
                    if trade_mode in ["I want to acquire specific player(s)", "I want to choose both trade-away and acquire targets"]:
                        forced_get = st.multiselect(
                            "Player(s) on the other team I want to acquire",
                            other_trade_players,
                            key="lineup_trade_ideas_forced_get"
                        )

                    if st.button("Suggest Trades For My Team", key="lineup_suggest_trades_button"):
                        suggestions = suggest_trade_targets(
                            my_team_trade,
                            other_team_trade,
                            lineup_trade_roster_stats,
                            lineup_trade_standings
                        )

                        suggestions = filter_trade_suggestions_by_requested_players(
                            suggestions,
                            forced_give=forced_give,
                            forced_get=forced_get
                        )

                        if suggestions.empty:
                            st.info("No clear trade suggestions found for those constraints. Try choosing fewer specific players or a different other team.")
                        else:
                            render_output_table(
                                format_fantasy_table(clean_ui_columns(suggestions)),
                                key="lineup_trade_suggestions",
                                file_name="lineup_trade_suggestions.csv",
                                display_rows=20,
                                style_cols=["Trade Fit Score", "Fairness Gap"]
                            )

if active_page == "Valuation":
    render_section_header("💰 Valuation", "Blend recent production and trend momentum into a valuation score.")
    c1, c2 = st.columns(2)
    with c1:
        lag_value = st.selectbox("Valuation Window (Years)", [3, 4, 5], index=0, key="value_lag")
    with c2:
        min_g_value = st.number_input("Minimum Games Played", 0, 800, 50, key="value_min_g")

    max_year_value = int(yearly_df["yearID"].max())
    recent_years_value = list(range(max_year_value - lag_value + 1, max_year_value + 1))
    st.write(f"Analyzing seasons: **{recent_years_value[0]}–{recent_years_value[-1]}**")
    recent_data_value = yearly_df[yearly_df["yearID"].isin(recent_years_value)].copy().sort_values(["playerID", "yearID"])

    st.markdown("#### Draft Room Sync")
    value_sync_enabled = st.checkbox(
        "Remove already drafted players and allow drafting from Valuation page",
        value=True,
        key="value_use_draft_room_sync"
    )
    value_drafted_names = []
    value_sync_team = None
    if value_sync_enabled:
        value_room_table = st.session_state.get("draft_room_table", pd.DataFrame()).copy()
        if not value_room_table.empty and "Player" in value_room_table.columns:
            value_drafted_names = value_room_table["Player"].dropna().astype(str).str.strip().tolist()
            value_team_options = get_draft_room_team_options()
            if value_team_options:
                default_value_team = st.session_state.get("room_your_team", value_team_options[0])
                default_value_idx = value_team_options.index(default_value_team) if default_value_team in value_team_options else 0
                value_sync_team = st.selectbox(
                    "My Draft Room Team",
                    value_team_options,
                    index=default_value_idx,
                    key="value_sync_team_for_draft"
                )
            st.caption(f"Removed {len(set(value_drafted_names))} already drafted player(s) from Valuation page views.")
        else:
            st.caption("No Draft Room picks found yet.")

    if value_sync_enabled and value_drafted_names:
        recent_data_value = recent_data_value[~recent_data_value["fullName"].astype(str).isin(set(value_drafted_names))].copy()

    agg_value = recent_data_value.groupby(["playerID", "fullName", "bats"], as_index=False)[["G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]].sum()
    agg_value = add_rate_stats(agg_value)
    agg_value = agg_value[agg_value["G"] >= min_g_value].copy()
    agg_value = apply_stat_min_filters(agg_value, "value")

    trend_value = recent_data_value.groupby("playerID").apply(lambda g: pd.Series({
        "R_trend": compute_trend_slope(g, "R"), "H_trend": compute_trend_slope(g, "H"),
        "2B_trend": compute_trend_slope(g, "2B"), "3B_trend": compute_trend_slope(g, "3B"),
        "HR_trend": compute_trend_slope(g, "HR"), "RBI_trend": compute_trend_slope(g, "RBI"),
        "SB_trend": compute_trend_slope(g, "SB"), "BB_trend": compute_trend_slope(g, "BB"),
        "BA_trend": compute_trend_slope(g, "BA"), "OBP_trend": compute_trend_slope(g, "OBP"),
        "SLG_trend": compute_trend_slope(g, "SLG"), "OPS_trend": compute_trend_slope(g, "OPS")
    })).reset_index()

    valuation_df = agg_value.merge(trend_value, on="playerID", how="left")
    valuation_df = add_latest_and_projection_columns(valuation_df, recent_data_value)

    with st.expander("Valuation blend weights", expanded=False):
        st.caption("These weights only scale how much current vs trend contributes to Valuation Score below.")
        c5, c6 = st.columns(2)
        with c5:
            w_current = st.number_input("Weight: Current Score", 0.0, 10.0, 1.0, key="value_w_current")
        with c6:
            w_trend = st.number_input("Weight: Trend Score", 0.0, 10.0, 1.0, key="value_w_trend")

    valuation_df["Trend_Score"] = (
        valuation_df["R_trend"].fillna(0) * 1.0 + valuation_df["H_trend"].fillna(0) * 0.5 +
        valuation_df["2B_trend"].fillna(0) * 0.75 + valuation_df["3B_trend"].fillna(0) * 0.75 +
        valuation_df["HR_trend"].fillna(0) * 2.0 + valuation_df["RBI_trend"].fillna(0) * 1.5 +
        valuation_df["SB_trend"].fillna(0) * 1.0 + valuation_df["BB_trend"].fillna(0) * 0.5 +
        valuation_df["BA_trend"].fillna(0) * 100 + valuation_df["OBP_trend"].fillna(0) * 100 +
        valuation_df["SLG_trend"].fillna(0) * 100 + valuation_df["OPS_trend"].fillna(0) * 100
    )
    valuation_df["Perf_Score"] = (
        valuation_df["R"] * 0.10 + valuation_df["H"] * 0.05 + valuation_df["2B"] * 0.05 +
        valuation_df["3B"] * 0.05 + valuation_df["HR"] * 0.25 + valuation_df["RBI"] * 0.20 +
        valuation_df["SB"] * 0.10 + valuation_df["BA"].fillna(0) * 100 * 0.05 +
        valuation_df["OBP"].fillna(0) * 100 * 0.10 + valuation_df["SLG"].fillna(0) * 100 * 0.10 +
        valuation_df["OPS"].fillna(0) * 100 * 0.10
    )
    valuation_df["Valuation_Raw"] = w_current * valuation_df["Perf_Score"] + w_trend * valuation_df["Trend_Score"]
    val_min = valuation_df["Valuation_Raw"].min()
    val_max = valuation_df["Valuation_Raw"].max()
    if pd.notna(val_min) and pd.notna(val_max) and val_max != val_min:
        valuation_df["Valuation_Score"] = (valuation_df["Valuation_Raw"] - val_min) / (val_max - val_min)
    else:
        valuation_df["Valuation_Score"] = 0.0

    valuation_df = safe_round_rate_stats(valuation_df)
    top_bar_chart(valuation_df, "fullName", "Valuation_Score", "Top 10 Valuation Score")

    c7, c8, c9 = st.columns(3)
    c7.metric("Top Valuation Score", fmt_rate_4(valuation_df["Valuation_Score"].max() if not valuation_df.empty else 0))
    c8.metric("Average Valuation Score", fmt_rate_4(valuation_df["Valuation_Score"].mean() if not valuation_df.empty else 0))
    c9.metric("Top Valuation Player", valuation_df.sort_values("Valuation_Score", ascending=False).iloc[0]["fullName"] if not valuation_df.empty else "N/A")

    valuation_display = valuation_df[["fullName", "bats", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS", "Trend_Score", "Perf_Score", "Valuation_Score"]].sort_values("Valuation_Score", ascending=False).rename(columns={
        "fullName": "Player", "bats": "Bats", "Trend_Score": "Trend Score", "Perf_Score": "Current Score", "Valuation_Score": "Valuation Score"
    })
    valuation_table = format_display_table(clean_ui_columns(valuation_display), count_cols=["R", "H", "2B", "3B", "HR", "RBI", "SB"], rate_cols=["BA", "OBP", "SLG", "OPS"], score_cols=["Trend Score", "Current Score", "Valuation Score"])
    render_output_table(valuation_table, key="valuation", file_name="valuation.csv")
    if not valuation_table.empty:
        compact_player_action_center(
            valuation_table["Player"].dropna().astype(str).tolist(),
            key="valuation_actions_final",
            default_team=value_sync_team,
            label="Actions for Valuation Table Players",
            user_draft_team=value_sync_team,
            projection_lookup_df=valuation_df,
            projection_lookup_name_col="fullName",
            help_text="Valuation table — projection breakdown uses window stats + trends (not full fantasy market ranks unless merged on this page).",
        )


    st.subheader("Valuation Insight Summaries")
    best_value_row = valuation_df.sort_values("Valuation_Score", ascending=False).head(1)
    worst_value_row = valuation_df.sort_values("Valuation_Score", ascending=True).head(1)
    if not best_value_row.empty:
        st.success(f"💰 Best valuation profile: {make_valuation_summary(best_value_row.iloc[0])}")
    if not worst_value_row.empty:
        st.warning(f"⚠️ Weakest valuation profile: {make_valuation_summary(worst_value_row.iloc[0])}")

if active_page == "ML Predictions":
    render_section_header(
        "🤖 ML Predictions",
        "Generate next-season projections using machine learning, aging curves, regression-to-the-mean, and similar-player comparisons."
    )

    if not SKLEARN_AVAILABLE:
        st.error("Scikit-learn is not installed. In Command Prompt, run: pip install scikit-learn")
    else:
        c1, c2, c3, c4top = st.columns(4)
        with c1:
            ml_lookback = st.selectbox("Lookback Window", [3, 4, 5], index=0, key="ml_lookback")
        with c2:
            ml_min_games = st.number_input("Minimum Games in Lookback Window", 0, 800, 150, key="ml_min_games")
        with c3:
            ml_sort_stat = st.selectbox("Rank Predictions By", ["OPS", "HR", "RBI", "SB", "R", "H", "BA", "OBP", "SLG", "BB"], index=0, key="ml_sort_stat")
        with c4top:
            ml_max_players = st.selectbox("Projection Scope", [100, 150, 300, 500], index=1, key="ml_max_players", help="Lower numbers are much faster on Streamlit Cloud.")

        ml_min_ab = st.number_input(
            "Minimum Recent AB in Lookback Window",
            0,
            2500,
            300,
            key="ml_min_ab",
            help="Filters players before similarity + aging adjustments so unused low-AB rows are not computed.",
        )

        with st.expander("Advanced projection tuning (defaults work well)", expanded=False):
            st.caption("Adjust how strongly the projection blends regression, age, and similar-player context.")
            a1, a2, a3, a4 = st.columns(4)
            with a1:
                regression_strength = st.slider("Regression to Mean", 0.00, 0.60, 0.20, 0.05, key="ml_regression_strength")
            with a2:
                age_strength = st.slider("Aging Curve Strength", 0.00, 1.00, 0.50, 0.05, key="ml_age_strength")
            with a3:
                comp_weight = st.slider("Similar Player Weight", 0.00, 0.60, 0.10, 0.05, key="ml_comp_weight")
            with a4:
                k_neighbors = st.slider("Similar Players Used", 5, 50, 10, 5, key="ml_k_neighbors")

        run_ml_predictions = st.button("Generate / Refresh ML Predictions", type="primary", key="run_ml_predictions_button")
        if run_ml_predictions:
            st.session_state["ml_predictions_have_run"] = True
            _clear_ml_projection_session_cache()

        if not st.session_state.get("ml_predictions_have_run", False):
            st.info(
                "Choose settings, then click **Generate / Refresh ML Predictions**."
            )
        else:
            run_sig = _ml_projection_run_signature(
                yearly_df,
                ml_lookback,
                ml_min_games,
                ml_max_players,
                regression_strength,
                age_strength,
                comp_weight,
                k_neighbors,
                ml_min_ab,
            )
            if st.session_state.get("_ml_proj_sig") == run_sig and "_ml_proj_pred_df" in st.session_state:
                ml_training_df = st.session_state["_ml_proj_training_df"]
                ml_feature_cols = st.session_state["_ml_proj_feature_cols"]
                ml_models = st.session_state["_ml_proj_models"]
                pred_df = st.session_state["_ml_proj_pred_df"].copy()
                age_curve_df = st.session_state["_ml_proj_age_curve_df"].copy()
                comp_df = st.session_state["_ml_proj_comp_df"].copy()
            else:
                with st.spinner("Building projections..."):
                    ml_training_df, ml_feature_cols, ml_models, current_rows, base_pred_df = build_base_ml_predictions(
                        yearly_df, ml_lookback, ml_min_games, max_player_pool=ml_max_players
                    )
                pred_df = pd.DataFrame()
                age_curve_df = pd.DataFrame()
                comp_df = pd.DataFrame()
                if (
                    not ml_training_df.empty
                    and ml_feature_cols
                    and not current_rows.empty
                    and not base_pred_df.empty
                ):
                    ab_ok = pd.to_numeric(base_pred_df["hist_AB_total"], errors="coerce").fillna(0) >= float(ml_min_ab)
                    base_f = base_pred_df.loc[ab_ok].reset_index(drop=True)
                    pids = set(base_f["playerID"].astype(str))
                    cur_f = current_rows[current_rows["playerID"].astype(str).isin(pids)].reset_index(drop=True)
                    pred_df = base_f.copy()
                    if not pred_df.empty and not cur_f.empty:
                        with st.spinner("Applying aging, regression, and similarity..."):
                            pred_df, age_curve_df, comp_df = apply_advanced_projection_adjustments(
                                pred_df,
                                cur_f,
                                ml_training_df,
                                ml_feature_cols,
                                ML_TARGET_STATS,
                                regression_strength=regression_strength,
                                age_strength=age_strength,
                                comp_weight=comp_weight,
                                k_neighbors=k_neighbors,
                            )
                        if not pred_df.empty:
                            st.session_state["_ml_proj_sig"] = run_sig
                            st.session_state["_ml_proj_pred_df"] = pred_df.copy()
                            st.session_state["_ml_proj_age_curve_df"] = age_curve_df.copy()
                            st.session_state["_ml_proj_comp_df"] = (
                                comp_df.copy() if comp_df is not None and not comp_df.empty else pd.DataFrame()
                            )
                            st.session_state["_ml_proj_training_df"] = ml_training_df
                            st.session_state["_ml_proj_feature_cols"] = ml_feature_cols
                            st.session_state["_ml_proj_models"] = ml_models

            if ml_training_df.empty or not ml_feature_cols:
                st.warning("Not enough historical data to train the model with these settings. Lower the minimum games or use a shorter lookback window.")
            else:

                c4, c5, c6 = st.columns(3)
                c4.metric("Training Examples", f"{len(ml_training_df):,}")
                c5.metric("Features Used", f"{len(ml_feature_cols):,}")
                c6.metric("Models Trained", f"{len(ml_models):,}")

                metric_rows = []
                for stat, info in ml_models.items():
                    metric_rows.append({"Stat": stat, "MAE": info["mae"], "R²": info["r2"]})
                metrics_df = pd.DataFrame(metric_rows)
                if not metrics_df.empty:
                    st.subheader("Model Accuracy Check")
                    st.caption("MAE means average miss. For example, HR MAE of 4 means the model is typically off by about 4 home runs on the test seasons.")
                    metrics_table = clean_ui_columns(metrics_df.round({"MAE": 3, "R²": 3}))
                    render_output_table(metrics_table, key="ml_accuracy", file_name="ml_model_accuracy.csv")

                if pred_df.empty:
                    st.warning(
                        "No player projections to display. Raise **Minimum Recent AB** or **Minimum Games**, "
                        "or click **Generate / Refresh** after changing scope."
                    )
                else:
                    st.success(f"Generated {len(pred_df):,} player projections.")

                    sort_col = f"Predicted {ml_sort_stat}"
                    if sort_col in pred_df.columns:
                        pred_df = pred_df.sort_values(sort_col, ascending=False)

                    # User-facing ML output: show only identifying info and the recommended predicted stats.
                    # Historical/diagnostic columns such as Last Year, Last HR, Recent AB, Final, raw model outputs,
                    # and similar-player columns are intentionally hidden from the main table.
                    display_cols = [
                        "fullName", "bats", "prediction_year", "age_entering_year",
                        "Predicted R", "Predicted H", "Predicted 2B", "Predicted 3B", "Predicted HR", "Predicted RBI", "Predicted SB", "Predicted BB",
                        "Predicted BA", "Predicted OBP", "Predicted SLG", "Predicted OPS"
                    ]
                    display_cols = [c for c in display_cols if c in pred_df.columns]
                    projection_rename = {
                        "fullName": "Player", "bats": "Bats", "prediction_year": "Prediction Year",
                        "age_entering_year": "Age"
                    }
                    ml_display = clean_ui_columns(pred_df[display_cols].rename(columns=projection_rename))

                    st.subheader("Next-Season ML Projections")
                    st.caption("Predictions use machine learning with aging, regression-to-the-mean, and similarity adjustments. The table shows the recommended projected stats only.")
                    for _col in ml_display.columns:
                        if _col.startswith("Predicted "):
                            _stat = _col.replace("Predicted ", "")
                            ml_display[_col] = pd.to_numeric(ml_display[_col], errors="coerce").round(3 if _stat in RATE_STATS else 0)
                    if "Age" in ml_display.columns:
                        ml_display["Age"] = pd.to_numeric(ml_display["Age"], errors="coerce").round(0)
                    render_output_table(ml_display, key="ml_predictions", file_name="ml_predictions.csv")

                    if not ml_display.empty:
                        st.subheader("Top Prediction Summary")
                        st.success(make_ml_prediction_summary(ml_display.iloc[0], ml_sort_stat))

                    with st.expander("Show age curve details", expanded=False):
                        st.write("The age curve estimates typical year-to-year changes by age.")
                        if not age_curve_df.empty:
                            age_stats = [s for s in ML_TARGET_STATS if s in age_curve_df["Stat"].unique()]
                            if age_stats:
                                age_view_stat = st.selectbox("Age Curve Stat", age_stats, index=0, key="ml_age_curve_stat")
                                age_view = age_curve_df[age_curve_df["Stat"] == age_view_stat].rename(columns={"Age Adjustment": "Expected Age Change"})
                                age_curve_table = format_display_table(age_view, rate_cols=["Expected Age Change"])
                                render_output_table(age_curve_table, key="ml_age_curve", file_name="ml_age_curve.csv")

                    st.subheader("What Stats Matter Most?")
                    importance_options = [s for s in ML_TARGET_STATS if s in ml_models]
                    if importance_options:
                        importance_stat = st.selectbox("Feature Importance For", importance_options, index=0, key="ml_importance_stat")
                        importance_df = ml_models[importance_stat]["importance"].head(15).copy()
                        importance_df["Feature"] = importance_df["Feature"].apply(clean_feature_name)
                        importance_table = format_display_table(clean_ui_columns(importance_df), rate_cols=["Importance"])
                        render_output_table(importance_table, key="ml_feature_importance", file_name="ml_feature_importance.csv")
                        with st.expander("Feature importance chart", expanded=False):
                            top_bar_chart(importance_df, "Feature", "Importance", f"Top Feature Importance for Predicting {importance_stat}", top_n=15)

