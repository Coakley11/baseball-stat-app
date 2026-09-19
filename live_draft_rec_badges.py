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


def _proj(row: Any, *cols: str) -> float:
    for col in cols:
        val = _num(row, col)
        if pd.notna(val):
            return float(val)
    return float("nan")


def _eligible_trait_badges(
    row: Any,
    *,
    gaps: list[str] | None,
    category_needs: list[str] | None,
    strengths: list[str] | None,
    rec_df: Any,
) -> list[tuple[float, str, str, str]]:
    """Return scored (score, label, css, concept) trait candidates — higher = better."""
    traits: list[tuple[float, str, str, str]] = []
    pos = str(row.get("Primary Position") or "").strip()
    name = str(row.get("fullName") or "").strip()
    needs = {str(c).strip().upper() for c in (category_needs or []) if str(c).strip()}
    strength_set = {str(s).strip().upper() for s in (strengths or []) if str(s).strip()}

    hr = _proj(row, "proj_HR", "HR", "Projected HR")
    rbi = _proj(row, "proj_RBI", "RBI", "Projected RBI")
    sb = _proj(row, "proj_SB", "SB", "Projected SB")
    avg = _proj(row, "proj_AVG", "AVG", "BA", "Projected AVG")
    runs = _proj(row, "proj_R", "R", "Runs", "Projected R")

    if pd.notna(hr) and float(hr) >= 30:
        traits.append((90.0 + float(hr) / 10.0, "Elite Power", _BADGE_CSS["upside"], "power"))
    elif pd.notna(hr) and float(hr) >= 22:
        traits.append((70.0 + float(hr) / 10.0, "Top HR Projection", _BADGE_CSS["category"], "power"))

    if pd.notna(rbi) and float(rbi) >= 90:
        traits.append((75.0 + float(rbi) / 20.0, "Strong RBI", _BADGE_CSS["category"], "rbi"))

    if pd.notna(sb) and float(sb) >= 20:
        traits.append((80.0 + float(sb) / 10.0, "Speed Boost", _BADGE_CSS["upside"], "speed"))
    elif pd.notna(sb) and float(sb) >= 12 and ("SB" in needs or "SB" in strength_set):
        traits.append((72.0, "Fills SB Need", _BADGE_CSS["category"], "speed_need"))

    if pd.notna(avg) and float(avg) >= 0.290:
        traits.append((68.0 + float(avg) * 10.0, "High AVG", _BADGE_CSS["category"], "avg"))
    elif pd.notna(avg) and float(avg) >= 0.270 and ("AVG" in needs or "BA" in needs):
        traits.append((66.0, "Fills Low-AVG Need", _BADGE_CSS["category"], "avg_need"))

    if pd.notna(runs) and float(runs) >= 90:
        traits.append((60.0 + float(runs) / 20.0, "Strong Runs", _BADGE_CSS["category"], "runs"))

    if "HR" in needs and pd.notna(hr) and float(hr) >= 18:
        traits.append((85.0, "Category Need: HR", _BADGE_CSS["category"], "cat_hr"))
    if "RBI" in needs and pd.notna(rbi) and float(rbi) >= 70:
        traits.append((78.0, "Category Need: RBI", _BADGE_CSS["category"], "cat_rbi"))

    # Strength labels from scoring (when projections are sparse on the card row).
    strength_badge_map = {
        "HR": (76.0, "Power Upgrade", "power"),
        "RBI": (64.0, "Strong RBI", "rbi"),
        "SB": (73.0, "Speed Boost", "speed"),
        "AVG": (62.0, "High AVG", "avg"),
        "R": (58.0, "Strong Runs", "runs"),
        "RUNS": (58.0, "Strong Runs", "runs"),
    }
    for s in strength_set:
        mapped = strength_badge_map.get(s)
        if mapped:
            score, label, concept = mapped
            # Boost when the category is also a current team need.
            if s in needs or (s == "AVG" and "BA" in needs):
                score += 8.0
                if s == "HR":
                    label = "Category Need: HR"
                elif s == "SB":
                    label = "Fills SB Need"
                elif s == "AVG":
                    label = "Fills Low-AVG Need"
            traits.append((score, label, _BADGE_CSS["category"], concept))

    edge = _num(row, "Fantasy Edge")
    mdl = _num(row, "Model Rank")
    mkt = _num(row, "Market Rank")
    if pd.notna(edge) and float(edge) >= 10 and pd.notna(mdl) and pd.notna(mkt) and float(mdl) < float(mkt):
        traits.append((88.0 + min(float(edge), 40.0) / 4.0, "Model Bargain", _BADGE_CSS["bargain"], "bargain"))
    elif pd.notna(edge) and float(edge) >= 6 and pd.notna(mdl) and pd.notna(mkt) and float(mdl) < float(mkt):
        traits.append((74.0, "Market Value", _BADGE_CSS["value"], "value"))

    toks: list[str] = []
    for col in ("Positions", "Eligible Positions", "Position"):
        raw = row.get(col) if hasattr(row, "get") else None
        if raw is None:
            continue
        toks.extend(str(p).strip().upper() for p in str(raw).replace("/", ",").split(",") if str(p).strip())
    if pos:
        toks.append(pos.upper())
    uniq = {t for t in toks if t and t not in ("UTIL", "DH", "NA")}
    if len(uniq) >= 2:
        traits.append((55.0 + len(uniq), "Multi-Position", _BADGE_CSS["position"], "multi_pos"))

    if pos and gaps and pos in gaps:
        best_at_pos = _best_name_at_position(rec_df, pos)
        if best_at_pos and name and best_at_pos == name:
            traits.append((82.0, f"Best Available {pos}", _BADGE_CSS["position"], f"best_{pos}"))
        elif pos == "C":
            traits.append((70.0, "Scarce Catcher", _BADGE_CSS["scarcity"], "catcher"))
        else:
            # Keep position fill secondary so category/value badges can win.
            traits.append((48.0, f"Fills {pos} Slot", _BADGE_CSS["position"], "fill_position"))

    scarcity = _num(row, "Scarcity Score")
    if pd.notna(scarcity) and float(scarcity) >= 0.65 and pos:
        traits.append((58.0 + float(scarcity) * 10.0, f"{pos} Scarcity", _BADGE_CSS["scarcity"], "scarcity"))

    return traits


def build_smart_recommendation_badges(
    rank: int,
    row: Any,
    rec_df: Any,
    *,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    strengths: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Return up to three specific (label, css_class) badges — player-distinctive traits."""
    badges: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    seen_concepts: set[str] = set()

    def _add(label: str, css: str, *, concept: str = "") -> None:
        if label in seen_labels or len(badges) >= 3:
            return
        concept_key = concept or label.lower()
        # Collapse near-duplicate concepts (power/hr, speed/sb).
        family = concept_key.split("_")[0]
        if family in seen_concepts or concept_key in seen_concepts:
            return
        seen_labels.add(label)
        seen_concepts.add(concept_key)
        seen_concepts.add(family)
        badges.append((label, css))

    ranked = sorted(
        _eligible_trait_badges(
            row, gaps=gaps, category_needs=category_needs, strengths=strengths, rec_df=rec_df
        ),
        key=lambda t: t[0],
        reverse=True,
    )
    for _score, label, css, concept in ranked:
        _add(label, css, concept=concept)
        if len(badges) >= 3:
            break

    # Rank ordinals only as last-resort filler — never the dominant badge set.
    if len(badges) < 1:
        rank_labels = {1: "Best Overall", 2: "Second Best", 3: "Third Best"}
        if rank in rank_labels:
            _add(rank_labels[rank], _BADGE_CSS["gold"], concept=f"rank_{rank}")

    return badges[:3]


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

    hr = _proj(row, "proj_HR", "HR")
    sb = _proj(row, "proj_SB", "SB")
    if pd.notna(hr) and float(hr) >= 28 and "Elite Power" not in badge_labels:
        return f"Projects {int(round(float(hr)))} HR — elite power upside"
    if pd.notna(sb) and float(sb) >= 18 and "Speed Boost" not in badge_labels:
        return f"Projects {int(round(float(sb)))} SB — real speed contribution"

    if gaps and pos in gaps:
        open_of = sum(1 for g in gaps if g == "OF")
        if pos == "OF" and open_of >= 2:
            return f"Best option to cover {open_of} open outfield slots"
        return f"Top fit for your open {pos} slot"

    if strengths:
        return f"Strengthens {' & '.join(strengths[:2])}"

    if pd.notna(edge) and float(edge) >= 8:
        return f"Model ranks him {int(round(float(edge)))} spots ahead of market"

    if rank == 1:
        return "Highest decision score among available fits"
    return "Strong blend of production, fit, and availability"
