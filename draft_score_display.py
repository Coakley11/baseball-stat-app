"""User-facing draft score names, formatting, and roster-fit context notes.

Internal dataframe columns (Expected Fantasy Value, Decision Score, Draft Fit Score)
are unchanged. Call ``prepare_draft_scores_for_display`` only at display/export boundaries.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

# Internal column names (do not rename in scoring logic)
COL_EFV = "Expected Fantasy Value"
COL_PICK = "Decision Score"
COL_ROSTER_FIT = "Draft Fit Score"
COL_RELATIVE_GRADE = "Overall Draft Grade Score"
COL_DRAFT_RANK = "Draft Room Rank"

# User-facing display names
DISPLAY_PLAYER_GRADE = "Player Grade"
DISPLAY_PICK_SCORE = "Pick Score"
DISPLAY_ROSTER_FIT = "Roster Fit Score"
DISPLAY_RELATIVE_GRADE = "Relative Draft Grade"
DISPLAY_DRAFT_RANK = "Draft Rank"

COLUMN_RENAME_MAP: dict[str, str] = {
    COL_EFV: DISPLAY_PLAYER_GRADE,
    COL_PICK: DISPLAY_PICK_SCORE,
    COL_ROSTER_FIT: DISPLAY_ROSTER_FIT,
    COL_RELATIVE_GRADE: DISPLAY_RELATIVE_GRADE,
    COL_DRAFT_RANK: DISPLAY_DRAFT_RANK,
    "Average Expected Fantasy Value": "Average Player Grade",
    "Total Expected Fantasy Value": "Total Player Grade",
    "Total Projected Fantasy Value": "Total Player Grade",
    "Average Draft Fit Score": "Average Roster Fit Score",
    "Draft Fit Rank": "Roster Fit Rank",
}

# Multiply internal 0–1 values by 100 for display (roster fit is NOT scaled)
SCALE_TO_DISPLAY_100: frozenset[str] = frozenset(
    {
        COL_EFV,
        COL_PICK,
        COL_RELATIVE_GRADE,
        "Average Expected Fantasy Value",
        "Total Expected Fantasy Value",
        "Total Projected Fantasy Value",
    }
)

SCORE_TOOLTIPS: dict[str, str] = {
    DISPLAY_PLAYER_GRADE: (
        "How strong the player is overall based on projections and model adjustments."
    ),
    DISPLAY_ROSTER_FIT: (
        "How well this player fits your current roster construction and needs."
    ),
    DISPLAY_PICK_SCORE: "How strong this recommendation is right now.",
    "Fantasy Edge": "How much higher or lower the model ranks this player compared with the market.",
    DISPLAY_RELATIVE_GRADE: (
        "How this team's draft compares with other teams in the current draft room."
    ),
    DISPLAY_DRAFT_RANK: "Rank within this draft room (1 = best relative grade).",
}
SCORE_TOOLTIPS["Average Roster Fit Score"] = SCORE_TOOLTIPS[DISPLAY_ROSTER_FIT]

ROSTER_FIT_CONTEXT_NOTES: dict[str, str] = {
    "draft_assistant": (
        "**Roster Fit Score** is recalculated live using your synced roster, position needs, "
        "category needs, and the current pick."
    ),
    "live_draft": (
        "**Roster Fit Score** uses the on-clock team's live roster and remaining pool at this pick."
    ),
    "draft_room_simulator": (
        "**Roster Fit Score** on the board export uses a single snapshot (empty roster, current pick "
        "number) — not each team's roster at pick time. Use **Draft Assistant Simulator** for live "
        "roster-context fit. **Player Grade** is the same player-quality score everywhere."
    ),
    "draft_sim_test": (
        "**Roster Fit Score** on each row was calculated at that pick with the sim team's roster "
        "at that moment (historical context)."
    ),
}

ROSTER_FIT_AUDIT_SUMMARY = """
Roster Fit Score uses the same ``apply_draft_pick_scoring`` formula everywhere, but roster context differs:
- Draft Assistant: your synced roster, live each render.
- Live Draft Room: on-clock team roster, live each pick.
- Draft Simulation Test Mode: each team's roster at the pick when the row was drafted.
- Draft Room Simulator board export: empty roster snapshot at page load (not pick-time context).
"""


def _num(val: Any) -> float | None:
    n = pd.to_numeric(val, errors="coerce")
    if pd.isna(n):
        return None
    return float(n)


SLEEPER_MIN_PLAYER_GRADE_DEFAULT = 10.0


def fmt_player_grade(val: Any) -> str:
    """Format raw EFV (0–1) as Player Grade display."""
    n = _num(val)
    if n is None:
        return ""
    return f"{n * 100:.2f}"


def coerce_sleeper_min_player_grade(value: Any, *, default: float = SLEEPER_MIN_PLAYER_GRADE_DEFAULT) -> float:
    """Normalize stored minimum Player Grade slider value to 0–100 display scale."""
    n = _num(value)
    if n is None:
        return default
    # Legacy slider stored internal EFV scale (0–1).
    if 0 < n <= 1.0:
        n = n * 100.0
    return max(0.0, min(100.0, float(n)))


def sleeper_min_player_grade_to_internal(display_grade: Any) -> float:
    """Convert 0–100 Player Grade threshold to internal 0–1 projection score."""
    return coerce_sleeper_min_player_grade(display_grade, default=0.0) / 100.0


def fmt_pick_score(val: Any) -> str:
    """Format raw Decision Score (0–1) as Pick Score display."""
    n = _num(val)
    if n is None:
        return ""
    return f"{n * 100:.2f}"


def fmt_roster_fit_score(val: Any) -> str:
    """Format raw Draft Fit Score (unscaled)."""
    n = _num(val)
    if n is None:
        return ""
    return f"{n:.2f}"


def fmt_relative_draft_grade(val: Any) -> str:
    """Format raw Overall Draft Grade (0–1) as Relative Draft Grade display."""
    n = _num(val)
    if n is None:
        return ""
    return f"{n * 100:.2f}"


def fmt_draft_rank(rank: Any, total: int | None = None) -> str:
    r = _num(rank)
    if r is None:
        return "—"
    label = f"#{int(round(r))}"
    if total is not None and total > 0:
        label = f"{label} of {int(total)}"
    return label


def display_column_name(internal: str) -> str:
    return COLUMN_RENAME_MAP.get(internal, internal)


def style_cols_for_display(style_cols: list[str] | None) -> list[str]:
    if not style_cols:
        return []
    return [COLUMN_RENAME_MAP.get(c, c) for c in style_cols]


def prepare_draft_scores_for_display(df: pd.DataFrame | None) -> pd.DataFrame:
    """Scale and rename draft score columns for tables/exports (display only)."""
    if df is None or getattr(df, "empty", True):
        return df if df is not None else pd.DataFrame()
    out = df.copy()
    for col in list(out.columns):
        if col not in SCALE_TO_DISPLAY_100:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce") * 100.0
    rename = {k: v for k, v in COLUMN_RENAME_MAP.items() if k in out.columns}
    if rename:
        out = out.rename(columns=rename)
    for col in (DISPLAY_PLAYER_GRADE, DISPLAY_PICK_SCORE, DISPLAY_RELATIVE_GRADE, "Average Player Grade", "Total Player Grade"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(2)
    if DISPLAY_ROSTER_FIT in out.columns:
        out[DISPLAY_ROSTER_FIT] = pd.to_numeric(out[DISPLAY_ROSTER_FIT], errors="coerce").round(2)
    return out


def draft_score_column_config(st: Any, columns: list[str]) -> dict[str, Any]:
    """Streamlit column_config help text for draft score columns."""
    cfg: dict[str, Any] = {}
    for col in columns:
        help_text = SCORE_TOOLTIPS.get(col)
        if help_text:
            cfg[col] = st.column_config.NumberColumn(col, help=help_text, format="%.2f")
    return cfg


# Legacy terms that must not appear in user-facing generated text or AMI context keys.
FORBIDDEN_USER_SCORE_TERMS: frozenset[str] = frozenset(
    {
        "EFV",
        "ESV",
        "Expected Fantasy Value",
        "Decision Score",
        "Draft Fit Score",
        "Drafted Score",
    }
)

_LEGACY_TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("Expected Fantasy Value", DISPLAY_PLAYER_GRADE),
    ("Decision Score", DISPLAY_PICK_SCORE),
    ("Draft Fit Score", DISPLAY_ROSTER_FIT),
    ("Drafted Score", DISPLAY_PICK_SCORE),
    ("Average Expected Fantasy Value", "Average Player Grade"),
    ("Total Expected Fantasy Value", "Total Player Grade"),
    ("Average Draft Fit Score", "Average Roster Fit Score"),
)


def sanitize_draft_terminology_text(text: str) -> str:
    """Replace legacy score names in prose (Reason, Strategy, AMI commentary)."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for old, new in _LEGACY_TEXT_REPLACEMENTS:
        out = out.replace(old, new)
    out = re.sub(r"\bEFV\b", DISPLAY_PLAYER_GRADE, out)
    out = re.sub(r"\bESV\b", DISPLAY_PLAYER_GRADE, out)
    out = re.sub(r"\bexpected fantasy value\b", DISPLAY_PLAYER_GRADE, out, flags=re.IGNORECASE)
    out = re.sub(r"\bdecision score\b", DISPLAY_PICK_SCORE, out, flags=re.IGNORECASE)
    out = re.sub(r"\bdraft fit score\b", DISPLAY_ROSTER_FIT, out, flags=re.IGNORECASE)
    out = re.sub(r"\bdrafted score\b", DISPLAY_PICK_SCORE, out, flags=re.IGNORECASE)
    return out


def _context_value_for_display(internal_col: str, val: Any) -> Any:
    if internal_col in SCALE_TO_DISPLAY_100:
        n = _num(val)
        if n is not None:
            return round(n * 100.0, 2)
    if internal_col == COL_ROSTER_FIT:
        n = _num(val)
        if n is not None:
            return round(n, 2)
    return val


def compact_context_row_for_display(row: dict[str, Any]) -> dict[str, Any]:
    """Rename score keys and sanitize text fields for AMI / insight payloads."""
    out: dict[str, Any] = {}
    for key, val in row.items():
        if key == "player":
            out["player"] = val
            continue
        if key in ("Reason", "reason", "Strategy", "strategy", "Team fit", "team_fit"):
            norm_key = key.lower() if key in ("Reason", "Strategy", "Team fit") else key
            out[norm_key] = sanitize_draft_terminology_text(str(val))[:300] if val else val
            continue
        display_key = COLUMN_RENAME_MAP.get(key, key)
        if key in COLUMN_RENAME_MAP or key in SCALE_TO_DISPLAY_100 or key == COL_ROSTER_FIT:
            out[display_key] = _context_value_for_display(key, val)
        else:
            out[key] = val
    return out


def compact_context_records_for_display(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_context_row_for_display(dict(r)) for r in records if isinstance(r, dict)]


def format_detail_line(internal_col: str, val: Any) -> tuple[str, str]:
    """Return (display_label, formatted_value) for recommendation Details rows."""
    if internal_col == COL_EFV:
        return DISPLAY_PLAYER_GRADE, fmt_player_grade(val)
    if internal_col == COL_PICK:
        return DISPLAY_PICK_SCORE, fmt_pick_score(val)
    if internal_col == COL_ROSTER_FIT:
        return DISPLAY_ROSTER_FIT, fmt_roster_fit_score(val)
    if internal_col in ("Model Rank", "Market Rank"):
        try:
            return internal_col, str(int(round(float(val))))
        except (TypeError, ValueError):
            return internal_col, str(val)
    if internal_col == "Fantasy Edge":
        try:
            n = float(val)
            sign = "+" if n > 0 else ""
            return "Fantasy Edge", f"{sign}{int(round(n))}"
        except (TypeError, ValueError):
            return internal_col, str(val)
    return internal_col, str(val) if val is not None else "—"
