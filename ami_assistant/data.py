"""The season frame AMI's tools read — the same ``yearly`` table the pages use.

Inside the app the panel hands over the already-loaded ``yearly_df`` (no second CSV load).
Outside Streamlit (tests, scripts) ``load_standalone_dataset`` builds it with
``lahman_data.build_lahman_frames``, the function ``streamlit_app.load_data`` delegates to.
"""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from player_name_normalization import normalize_player_name_for_merge
from rate_stat_qualification import season_lengths

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_SOURCE_LABEL = "Lahman Baseball Database (Sean Lahman / SABR)"
# Players whose last season is this close to the latest season count as "recent" when a
# bare surname has to be disambiguated ("Soto" → Juan Soto, not Geovany Soto).
RECENT_SEASONS = 3


@dataclass(frozen=True)
class BaseballDataset:
    yearly: pd.DataFrame
    players: pd.DataFrame  # one row per playerID, see ``build_player_table``
    season_games: dict[int, int] = field(default_factory=dict)
    first_season: int = 0
    latest_season: int = 0
    source: str = "app"
    fingerprint: tuple = ()  # content key for per-dataset caches

    def player_rows(self, player_id: str) -> pd.DataFrame:
        return self.yearly[self.yearly["playerID"] == player_id].sort_values("yearID")

    def player_name(self, player_id: str) -> str:
        try:
            return str(self.players.at[player_id, "fullName"])
        except KeyError:
            return str(player_id)

    def describe(self) -> str:
        return f"{DATA_SOURCE_LABEL}, {self.first_season}–{self.latest_season} seasons"


def build_player_table(yearly: pd.DataFrame, latest_season: int) -> pd.DataFrame:
    """playerID → name, career span, AB, primary position and normalized name keys."""
    cols = ["playerID", "fullName", "yearID", "AB", "G", "careerPrimaryPos", "bats"]
    frame = yearly[[c for c in cols if c in yearly.columns]]
    grouped = frame.groupby("playerID", sort=True)
    table = pd.DataFrame(
        {
            "fullName": grouped["fullName"].first(),
            "first_season": grouped["yearID"].min().astype(int),
            "last_season": grouped["yearID"].max().astype(int),
            "career_ab": grouped["AB"].sum(),
            "career_g": grouped["G"].sum(),
        }
    )
    if "careerPrimaryPos" in frame.columns:
        table["position"] = grouped["careerPrimaryPos"].first()
    if "bats" in frame.columns:
        table["bats"] = grouped["bats"].first()
    recent = frame[frame["yearID"] > latest_season - RECENT_SEASONS]
    table["recent_ab"] = recent.groupby("playerID")["AB"].sum().reindex(table.index).fillna(0)
    table["fullName"] = table["fullName"].fillna("").astype(str)
    table["norm_full"] = table["fullName"].map(normalize_player_name_for_merge)
    table["norm_last"] = table["norm_full"].str.split(" ").str[-1].fillna("")
    return table


def _fingerprint(yearly: pd.DataFrame) -> tuple:
    # st.cache_data hands back a fresh copy each rerun, so identity can't key the cache.
    return (len(yearly), int(yearly["yearID"].max()), int(pd.to_numeric(yearly["AB"], errors="coerce").sum()))


_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple, BaseballDataset] = {}


def dataset_from_yearly(yearly: pd.DataFrame, *, source: str = "app") -> BaseballDataset:
    """Wrap a loaded season frame (cached per frame contents, newest only)."""
    key = _fingerprint(yearly)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            return hit
    first, latest = int(yearly["yearID"].min()), int(yearly["yearID"].max())
    ds = BaseballDataset(
        yearly=yearly,
        players=build_player_table(yearly, latest),
        season_games=season_lengths(yearly),
        first_season=first,
        latest_season=latest,
        source=source,
        fingerprint=key,
    )
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE[key] = ds
    return ds


@functools.lru_cache(maxsize=1)
def _frames(base_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from lahman_data import build_lahman_frames, read_lahman_csv

    return build_lahman_frames(read_lahman_csv(Path(base_dir)), Path(base_dir))


def load_standalone_frames(base_dir: Path | str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(batting, yearly, people)`` from the repo's CSVs, exactly as ``load_data`` builds them."""
    return _frames(str(Path(base_dir or REPO_ROOT).resolve()))


def load_standalone_dataset(base_dir: Path | str | None = None) -> BaseballDataset:
    """The season frame outside Streamlit (tests, scripts, timing runs)."""
    return dataset_from_yearly(load_standalone_frames(base_dir)[1], source="standalone")
