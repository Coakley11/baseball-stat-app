"""Smart, differentiated recommendation badges for Live Draft Room cards."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_BADGE_CSS = {
    "gold": "gold",
    "value": "fire",
    "scarcity": "need",
    "category": "need",
    "position": "need",
    "safe": "safe",
    "upside": "fire",
    "bargain": "fire",
}


def _num(row: Any, col: str, default: float = np.nan) -> float:
    return pd.to_numeric(row.get(col, default), errors="coerce")


def _best_name_at_position(rec_df: Any, pos: str) -> str:
    if rec_df is None or getattr(rec_df, "empty", True) or not pos:
        return ""
    if "Primary Position" not in rec_df.columns:
        return ""
    subset = rec_df[rec_df["Primary Position"].astype(str) == str(pos)]
    if subset.empty:
        return ""
    for sort_col in ("Decision Score", "Expected Fantasy Value", "Draft Fit Score"):
        if sort_col in subset.columns:
            top = subset.sort_values(sort_col, ascending=False).head(1)
            return str(top.iloc[0].get("fullName") or "").strip()
    return str(subset.iloc[0].get("fullName") or "").strip()


def _category_badge(strengths: list[str] | None, category_needs: list[str] | None) -> tuple[str, str] | None:
    strength_map = {
        "HR": ("Power Upgrade", "category"),
        "RBI": ("Run Production Boost", "category"),
        "SB": ("Speed Upgrade", "category"),
        "AVG": ("Average Stabilizer", "category"),
        "Runs": ("Runs Boost", "category"),
        "R": ("Runs Boost", "category"),
        "OBP": ("On-Base Boost", "category"),
        "Contact": ("Contact Boost", "category"),
    }
    for s in strengths or []:
        key = str(s).strip()
        if key in strength_map:
            label, kind = strength_map[key]
            return label, _BADGE_CSS[kind]
    for cat in category_needs or []:
        cat_s = str(cat).strip()
        if not cat_s:
            continue
        if cat_s.upper() in ("HR",):
            return "Category Boost: HR", _BADGE_CSS["category"]
        if cat_s.upper() in ("SB",):
            return "Category Boost: SB", _BADGE_CSS["category"]
        if cat_s.upper() in ("RBI",):
            return "Category Boost: RBI", _BADGE_CSS["category"]
        if cat_s.upper() in ("BA", "AVG"):
            return "Category Boost: AVG", _BADGE_CSS["category"]
        return f"Category Boost: {cat_s}", _BADGE_CSS["category"]
    return None


def _edge_badge(edge: float, *, already_has_value: bool) -> tuple[str, str] | None:
    if pd.isna(edge):
        return None
    val = float(edge)
    if val >= 15 and not already_has_value:
        return "ADP Bargain", _BADGE_CSS["bargain"]
    if val >= 10 and not already_has_value:
        return "Market Discount", _BADGE_CSS["bargain"]
    if val >= 6:
        return "Projection Bargain", _BADGE_CSS["value"]
    return None


def build_smart_recommendation_badges(
    rank: int,
    row: Any,
    rec_df: Any,
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    strengths: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return up to four specific (label, css_class) badges — avoid generic Position Need."""
    badges: list[tuple[str, str]] = []
    seen: set[str] = set()
    pos = str(row.get("Primary Position") or "").strip()
    name = str(row.get("fullName") or "").strip()

    def _add(label: str, css: str) -> None:
        if label in seen or len(badges) >= 4:
            return
        seen.add(label)
        badges.append((label, css))

    rank_labels = {1: "Best Overall", 2: "Second Best", 3: "Third Best"}
    rank_badge: tuple[str, str] | None = None
    if rank in rank_labels:
        rank_badge = (rank_labels[rank], _BADGE_CSS["gold"])

    edge = _num(row, "Fantasy Edge")
    top_edge = np.nan
    if rec_df is not None and not getattr(rec_df, "empty", True) and "Fantasy Edge" in rec_df.columns:
        top_edge = pd.to_numeric(rec_df["Fantasy Edge"], errors="coerce").max()
    has_best_value = False
    if pd.notna(edge) and pd.notna(top_edge) and float(edge) >= float(top_edge):
        _add("Best Value", _BADGE_CSS["value"])
        has_best_value = True

    if pos and gaps and pos in gaps:
        best_at_pos = _best_name_at_position(rec_df, pos)
        if best_at_pos and name and best_at_pos == name:
            _add(f"Best Remaining {pos}", _BADGE_CSS["position"])
        else:
            open_of = sum(1 for g in gaps if g == "OF")
            if pos == "OF" and open_of >= 2:
                _add(f"Fills {open_of} OF Slots", _BADGE_CSS["position"])
            else:
                _add(f"Fills {pos} Slot", _BADGE_CSS["position"])

    cat_b = _category_badge(strengths, category_needs)
    if cat_b and cat_b[0] not in seen:
        cat_bonus = _num(row, "Category Need Bonus")
        if pd.isna(cat_bonus) or float(cat_bonus) > 0:
            _add(cat_b[0], cat_b[1])

    edge_b = _edge_badge(edge, already_has_value=has_best_value)
    if edge_b:
        _add(edge_b[0], edge_b[1])
    scarcity = _num(row, "Scarcity Score")
    if pd.notna(scarcity) and float(scarcity) >= 0.6:
        if rec_df is not None and "Scarcity Score" in getattr(rec_df, "columns", []):
            top_scarcity = pd.to_numeric(rec_df["Scarcity Score"], errors="coerce").max()
            if float(scarcity) >= float(top_scarcity or 0):
                _add("Best Scarcity Pick", _BADGE_CSS["scarcity"])
            elif float(scarcity) >= 0.75:
                _add("Scarcity Alert", _BADGE_CSS["scarcity"])

    efv = _num(row, "Expected Fantasy Value")
    if pd.notna(efv) and float(efv) >= 0.82:
        _add("Elite Ceiling", _BADGE_CSS["upside"])
    elif pd.notna(efv) and float(efv) >= 0.72 and rank <= 3:
        _add("Highest Upside", _BADGE_CSS["upside"])

    conf = _num(row, "Projection Confidence")
    risk = _num(row, "Risk Penalty")
    if pd.notna(conf) and float(conf) >= 0.65 and (pd.isna(risk) or float(risk) <= 0.35):
        _add("Safest Pick", _BADGE_CSS["safe"])

    dec = _num(row, "Decision Score")
    if rank == 1 and "Best Overall" not in seen and pd.notna(dec) and float(dec) >= 0.75:
        _add("League Winner Potential", _BADGE_CSS["gold"])

    fit = _num(row, "Positional Fit")
    if pd.notna(fit) and float(fit) >= 0.8 and not any("Fills" in b[0] or "Best Remaining" in b[0] for b in badges):
        _add("Elite Floor", _BADGE_CSS["safe"])

    if rank_badge and len(badges) < 4:
        _add(rank_badge[0], rank_badge[1])

    return badges[:4]


_GENERIC_RANK_BADGES = frozenset({"Best Overall", "Second Best", "Third Best"})


def primary_recommendation_reason(
    rank: int,
    row: Any,
    *,
    badges: list[tuple[str, str]] | None = None,
    strengths: list[str] | None = None,
    gaps: list[str] | None = None,
) -> str:
    """One-line prose headline for the card — never repeats badge pill text."""
    pos = str(row.get("Primary Position") or "")
    edge = _num(row, "Fantasy Edge")
    badge_labels = {label for label, _css in (badges or [])}

    if gaps and pos in gaps:
        open_of = sum(1 for g in gaps if g == "OF")
        if pos == "OF" and open_of >= 2:
            return f"Best option to cover {open_of} open outfield slots"
        return f"Top fit for your open {pos} slot"

    if strengths:
        return f"Strengthens {' & '.join(strengths[:2])}"

    if pd.notna(edge) and float(edge) >= 8:
        return f"Strong value vs market (+{int(round(float(edge)))})"

    scarcity = _num(row, "Scarcity Score")
    if pd.notna(scarcity) and float(scarcity) >= 0.65:
        return f"{pos} tier is thinning — act before quality drops" if pos else "Position scarcity is rising"

    for label in badge_labels:
        if label in _GENERIC_RANK_BADGES:
            continue
        if "Bargain" in label or "Discount" in label:
            if pd.notna(edge):
                return f"Market undervalues this pick (+{int(round(float(edge)))} edge)"
            return "Market undervalues this pick"
        if "Scarcity" in label:
            return f"{pos} options are fading fast" if pos else "Scarcity is building at this position"

    if rank == 1 and ("Best Overall" in badge_labels or not badges):
        return "Highest Decision Score on the board"
    if rank <= 3:
        return "Strong option at this pick"
    return "Solid value among remaining players"
