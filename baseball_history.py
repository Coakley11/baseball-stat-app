"""The historical stats layer, without Streamlit: Lahman loading, team names, rate stats,
season aggregation, player labels, Historical Explorer filtering, stat minimums and the
Leaderboards score.

Moved verbatim from streamlit_app.py (WEB-PREP1) so the page and the read-only API compute the
same rows. The app keeps its own ``st.cache_data`` wrappers around the slow functions; nothing
here reads or writes session state, renders, or persists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

RATE_STATS = ["BA", "OBP", "SLG", "OPS"]  # same list as streamlit_app.RATE_STATS


class HistoryDataMissing(FileNotFoundError):
    """A required Lahman file is missing (the API maps this to 503 "data unavailable")."""


def _csv_reader(base_dir: Path) -> Callable[[str], pd.DataFrame]:
    def read(filename: str) -> pd.DataFrame:
        path = Path(base_dir) / filename
        if not path.exists():
            raise HistoryDataMissing(filename)
        return pd.read_csv(path, low_memory=False)

    return read


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


def load_history_frames(base_dir: Path, *, read_csv: Callable[[str], pd.DataFrame] | None = None):
    """Lahman batting, one row per player-season (``yearly``) and people, exactly as the app
    builds them. ``read_csv(filename)`` reads one file from ``base_dir`` (the app passes its
    cached reader)."""
    base_dir = Path(base_dir)
    read_csv = read_csv or _csv_reader(base_dir)
    people = read_csv("People.csv")
    batting = read_csv("Batting.csv")
    fielding = read_csv("Fielding.csv")

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
        # dropna=False: thousands of early and Negro Leagues players have an unknown birth
        # date or batting hand; NaN group keys would silently drop their seasons.
        batting.groupby(["playerID", "fullName", "bats", "throws", "birthYear", "birthMonth", "birthDay", "birthCountry", "careerPrimaryPos", "yearID"], as_index=False, dropna=False)
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

    try:
        from hall_of_fame_data import attach_hof_flag, load_hall_of_fame_player_ids

        hof_ids = load_hall_of_fame_player_ids(base_dir)
        people = attach_hof_flag(people, hof_ids)
        batting = attach_hof_flag(batting, hof_ids)
        yearly = attach_hof_flag(yearly, hof_ids)
    except ImportError:
        pass

    return batting, yearly, people


def historical_rows(
    batting_df: pd.DataFrame,
    *,
    year_range: Sequence[int],
    bats: Iterable[str] = (),
    positions: Iterable[str] = (),
    position_source_col: str = "primaryPos",
    teams: Iterable[str] = (),
    combine_split_seasons: bool = False,
    aggregate_team: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    aggregate_primary: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, str, str, str]:
    """Historical Explorer rows before stat minimums: (rows, team display column, team sort
    column, note). Moved verbatim from the page; ``aggregate_*`` let the app pass its cached
    aggregators."""
    aggregate_player_year_team_fn = aggregate_team or aggregate_player_year_team
    aggregate_player_year_primary_team_fn = aggregate_primary or aggregate_player_year_primary_team
    hist_year_range = tuple(year_range)
    hist_bats = list(bats or [])
    hist_pos = list(positions or [])
    hist_teams = list(teams or [])
    hist_position_source_col = position_source_col
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
        hist = aggregate_player_year_primary_team_fn(hist_source)
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
        hist = aggregate_player_year_team_fn(hist_source)
        team_col_for_display = "teamHistoricalName"
        team_sort_col = "teamName"
        hist_note = "Split mode: one row per player-season-team. Split seasons stay separate."

    if hist_position_source_col in hist.columns:
        hist["displayPosition"] = hist[hist_position_source_col]
    elif "primaryPos" in hist.columns:
        hist["displayPosition"] = hist["primaryPos"]
    else:
        hist["displayPosition"] = ""
    return hist, team_col_for_display, team_sort_col, hist_note


STAT_MINIMUM_COLUMNS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]


def apply_stat_minimums(df: pd.DataFrame, mins: Mapping[str, Any]) -> pd.DataFrame:
    """Keep rows meeting every non-zero minimum (the app's "Stat minimum filters" rule)."""
    mask = pd.Series(True, index=df.index)
    for stat, min_val in mins.items():
        if min_val:
            mask &= df[stat].fillna(-np.inf) >= min_val
    return df.loc[mask].copy()


def add_leaderboard_score(leaderboard: pd.DataFrame, weights: Mapping[str, float]) -> pd.DataFrame:
    """Leaderboards "Score": the weighted sum of each stat (rate stats ×100)."""
    leaderboard["score"] = 0.0
    for stat, weight in weights.items():
        leaderboard["score"] += weight * (leaderboard[stat] * 100 if stat in RATE_STATS else leaderboard[stat])
    return leaderboard
