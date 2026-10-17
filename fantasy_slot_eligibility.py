"""Fantasy slot tokens and slot eligibility used by the Lineup Assistant and position filters.

Moved verbatim from streamlit_app.py; the app imports these names back.

Two eligibility rules exist today, and callers must know which one they use:

* ``player_eligible_for_slot`` (this module) — the older token rule used by the
  Recommended Starters builder and the research/waiver position filters. It still treats
  1B<->3B and 2B<->SS as interchangeable.
* ``fantasy_weekly_lineup.player_eligible_for_slot`` / ``fantasy_lineup_fill.can_fill`` with
  ``fantasy_position_eligibility`` (Phase D3) — games-played eligibility, used by the lineup
  board, lineup saves, roster checks and trade warnings. That one is authoritative for
  whether a saved lineup is legal.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


LINEUP_DEFAULT_HITTING_SLOTS = ("C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL")


LINEUP_ALLOWED_SLOT_TOKENS = frozenset({"C", "1B", "2B", "3B", "SS", "OF", "UTIL"})


def _normalize_pos_token(tok):
    t = str(tok).strip().upper()
    if t in ("LF", "CF", "RF"):
        return "OF"
    if t in ("TWP", "PH", "PR", "") or t == "NAN":
        return "DH"
    if t in ("SP", "RP", "P"):
        return "P"
    return t


def _split_primary_positions(primary_val):
    """Split Primary Position on / , + into normalized tokens (e.g. 1B/3B → 1B, 3B)."""
    if primary_val is None or (isinstance(primary_val, float) and np.isnan(primary_val)):
        return []
    s = str(primary_val).upper().replace(" ", "")
    parts = re.split(r"[,/\+]", s)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        out.append(_normalize_pos_token(p))
    if not out:
        out.append(_normalize_pos_token(primary_val))
    return list(dict.fromkeys(out))


FANTASY_POSITION_FILTER_OPTIONS = [
    "All positions",
    "C",
    "1B",
    "2B",
    "3B",
    "SS",
    "OF",
    "DH/UTIL",
]


def _fantasy_position_display_tokens(career_pos, season_pos=None):
    """Fantasy-facing position label (LF/CF/RF → OF, DH → DH/UTIL) and normalized tokens."""
    primary_raw = career_pos
    if primary_raw is None or (isinstance(primary_raw, float) and np.isnan(primary_raw)) or not str(primary_raw).strip():
        primary_raw = season_pos
    tokens = _split_primary_positions(primary_raw)
    if not tokens:
        tokens = ["DH"]
    display_parts = ["DH/UTIL" if t == "DH" else t for t in tokens]
    display = "/".join(dict.fromkeys(display_parts))
    return display, tokens


def player_matches_fantasy_position_filter(row, filter_choice: str | list | None) -> bool:
    """True when player is eligible for the selected fantasy slot filter(s)."""
    if isinstance(filter_choice, (list, tuple, set)):
        choices = [str(c).strip() for c in filter_choice if str(c).strip()]
        if not choices:
            return True
        return any(player_matches_fantasy_position_filter(row, c) for c in choices)
    choice = str(filter_choice or "").strip()
    if not choice or choice in ("All positions", "All"):
        return True
    getter = row.get if hasattr(row, "get") else lambda _k, _d=None: _d
    tokens = getter("_position_tokens")
    if tokens is None or (isinstance(tokens, float) and pd.isna(tokens)):
        tokens = getter("_pos_tokens")
    if tokens is None or (isinstance(tokens, float) and pd.isna(tokens)):
        for col in ("Primary Position", "Position", "Eligibility", "Positions"):
            raw = getter(col)
            if raw not in (None, "", np.nan):
                tokens = _split_primary_positions(raw)
                break
    if tokens is None or (isinstance(tokens, float) and pd.isna(tokens)):
        tokens = _fantasy_position_display_tokens(getter("careerPrimaryPos"), getter("primaryPos"))[1]
    elif isinstance(tokens, str):
        tokens = _split_primary_positions(tokens)
    if choice == "DH/UTIL":
        return "DH" in tokens or _player_eligible_for_slot(tokens, "UTIL")
    if choice == "OF":
        return any(t == "OF" for t in tokens)
    return _player_eligible_for_slot(tokens, choice)


def filter_players_by_fantasy_position(df: pd.DataFrame, filter_choice: str | list | None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if isinstance(filter_choice, (list, tuple, set)):
        choices = [str(c).strip() for c in filter_choice if str(c).strip()]
        if not choices:
            return df
        mask = df.apply(lambda r: player_matches_fantasy_position_filter(r, choices), axis=1)
        return df.loc[mask].copy()
    choice = str(filter_choice or "").strip()
    if not choice or choice in ("All positions", "All"):
        return df
    mask = df.apply(lambda r: player_matches_fantasy_position_filter(r, choice), axis=1)
    return df.loc[mask].copy()


def _player_eligible_for_slot(pos_tokens, slot):
    """slot is C,1B,2B,3B,SS,OF, or UTIL (UTIL = any non-pitcher)."""
    if slot == "UTIL":
        for p in pos_tokens:
            if p in ("P", "SP", "RP"):
                return False
        return True
    if slot == "OF":
        return any(p == "OF" for p in pos_tokens)
    if slot in ("C", "1B", "2B", "3B", "SS"):
        if pos_tokens == ["DH"] or (len(pos_tokens) == 1 and pos_tokens[0] == "DH"):
            return False
        if slot in pos_tokens:
            return True
        # Corner / middle infield flexibility when eligibility lists multiple IF spots.
        if slot == "1B" and "3B" in pos_tokens:
            return True
        if slot == "3B" and "1B" in pos_tokens:
            return True
        if slot == "2B" and "SS" in pos_tokens:
            return True
        if slot == "SS" and "2B" in pos_tokens:
            return True
        return False
    return False


def _parse_custom_lineup_slots(text):
    """Return ordered list of valid slot tokens, or None if empty."""
    if not text or not str(text).strip():
        return None
    raw = [s.strip().upper() for s in str(text).split(",") if s.strip()]
    cleaned = []
    for s in raw:
        if s in ("LF", "CF", "RF"):
            s = "OF"
        if s not in LINEUP_ALLOWED_SLOT_TOKENS:
            continue
        cleaned.append(s)
    return cleaned if cleaned else None


def enrich_lineup_roster_positions(roster_df: pd.DataFrame) -> pd.DataFrame:
    """Attach merged position eligibility tokens for lineup slot assignment."""
    if roster_df is None or roster_df.empty:
        return roster_df
    out = roster_df.copy()
    tokens_list = []
    for _, row in out.iterrows():
        toks: list[str] = []
        for col in ("Primary Position", "Position", "Eligibility", "Positions"):
            if col in row.index and row.get(col) not in (None, "", np.nan):
                toks.extend(_split_primary_positions(row.get(col)))
        if isinstance(row.get("_position_tokens"), list):
            toks = list(dict.fromkeys(toks + list(row.get("_position_tokens"))))
        if isinstance(row.get("_pos_tokens"), list):
            toks = list(dict.fromkeys(toks + list(row.get("_pos_tokens"))))
        if not toks:
            toks = ["DH"]
        tokens_list.append(list(dict.fromkeys(toks)))
    out["_pos_tokens"] = tokens_list
    out["_position_tokens"] = tokens_list
    return out


# Public names (the underscored originals stay for existing callers).
split_primary_positions = _split_primary_positions
player_eligible_for_slot = _player_eligible_for_slot
parse_custom_lineup_slots = _parse_custom_lineup_slots
