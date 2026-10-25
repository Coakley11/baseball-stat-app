"""Player action helpers — dedupe lists, identity normalization, and eligibility (no Streamlit)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


def normalize_player_display_name(name: Any) -> str:
    """Normalize player names for roster matching."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = str(name)
    text = text.replace("(Batter)", "").replace("(Pitcher)", "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def player_display_base(name: Any) -> str:
    return str(name or "").split(" (")[0].strip()


def player_names_match(left: Any, right: Any) -> bool:
    return normalize_player_display_name(left) == normalize_player_display_name(right)


def is_active_current_player(player: Any, source_df: pd.DataFrame | None = None) -> bool:
    """True when ``player`` belongs to the current/recent MLB player pool."""
    if source_df is None or source_df.empty or "yearID" not in source_df.columns:
        return False

    player_id = ""
    display_name = ""
    if isinstance(player, pd.Series):
        player = player.to_dict()
    if isinstance(player, dict):
        player_id = str(player.get("playerID") or player.get("Player ID") or "").strip()
        display_name = player_display_base(
            player.get("fullName")
            or player.get("Player")
            or player.get("Name")
            or player.get("player")
            or ""
        )
    else:
        display_name = player_display_base(player)

    match = pd.DataFrame()
    if player_id and "playerID" in source_df.columns:
        match = source_df[source_df["playerID"].astype(str).str.strip() == player_id]

    if match.empty and display_name and "fullName" in source_df.columns:
        key = normalize_player_display_name(display_name)
        match = source_df[
            source_df["fullName"]
            .fillna("")
            .astype(str)
            .map(normalize_player_display_name)
            .eq(key)
        ]

    if match.empty:
        return False

    years = pd.to_numeric(match["yearID"], errors="coerce").dropna()
    all_years = pd.to_numeric(source_df["yearID"], errors="coerce").dropna()
    if years.empty or all_years.empty:
        return False

    latest_player_year = int(years.max())
    latest_dataset_year = int(all_years.max())
    return latest_player_year in (2025, 2026) or latest_player_year >= latest_dataset_year - 1


def dedupe_append_name(existing, name: str, *, cap: int | None = None) -> list:
    """Append a display name if not already present (order preserved)."""
    out = []
    seen = set()
    for x in list(existing or []):
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    n = str(name or "").strip()
    if n and n not in seen:
        out.append(n)
    if cap is not None:
        return out[-int(cap) :]
    return out


def merge_chart_labels(existing, new_label: str, *, max_labels: int = 3) -> list:
    """Trend multi-chart label list: bump new label to end, cap length, no duplicates."""
    labels = [str(x).strip() for x in list(existing or []) if str(x).strip()]
    nl = str(new_label or "").strip()
    if not nl:
        return labels[:max_labels]
    labels = [x for x in labels if x != nl]
    labels.append(nl)
    return labels[-max_labels:]
