"""Pure player-name normalization for roster/stat merges (no Streamlit)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


def normalize_player_name_for_merge(name: Any) -> str:
    """Normalize player names so Lahman/app names can match FantasyPros names."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
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
