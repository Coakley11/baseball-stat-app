"""Smart, differentiated recommendation badges for Live Draft Room cards.

Badge thresholds are evidence-based relative to the current recommendation pool
(and roster needs) — never crude absolute HR cutoffs that call 26 HR "Elite"
when the same board shows 40–55 HR hitters.
"""

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


def _pool_percentile(rec_df: Any, col_candidates: tuple[str, ...], value: float) -> float:
    """Fraction of pool with a lower value (0–1). NaN if pool too small."""
    if rec_df is None or getattr(rec_df, "empty", True) or not pd.notna(value):
        return float("nan")
    series = None
    for col in col_candidates:
        if col in getattr(rec_df, "columns", []):
            series = pd.to_numeric(rec_df[col], errors="coerce")
            break
    if series is None:
        return float("nan")
    clean = series.dropna()
    if len(clean) < 4:
        return float("nan")
    return float((clean < float(value)).mean())


def _pool_rank(rec_df: Any, col_candidates: tuple[str, ...], value: float, *, ascending: bool = False) -> tuple[int, int]:
    """1-based rank among pool and pool size."""
    if rec_df is None or getattr(rec_df, "empty", True) or not pd.notna(value):
        return 0, 0
    series = None
    for col in col_candidates:
        if col in getattr(rec_df, "columns", []):
            series = pd.to_numeric(rec_df[col], errors="coerce")
            break
    if series is None:
        return 0, 0
    clean = series.dropna()
    n = int(len(clean))
    if n < 1:
        return 0, 0
    if ascending:
        better = int((clean < float(value)).sum())
    else:
        better = int((clean > float(value)).sum())
    return better + 1, n


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

    hr_pct = _pool_percentile(rec_df, ("proj_HR", "HR", "Projected HR"), hr)
    rbi_pct = _pool_percentile(rec_df, ("proj_RBI", "RBI", "Projected RBI"), rbi)
    sb_pct = _pool_percentile(rec_df, ("proj_SB", "SB", "Projected SB"), sb)
    avg_pct = _pool_percentile(rec_df, ("proj_AVG", "proj_BA", "AVG", "BA"), avg)
    runs_pct = _pool_percentile(rec_df, ("proj_R", "R", "Runs"), runs)

    # Elite Power: top ~12% of THIS candidate pool, or truly elite absolute HR.
    if pd.notna(hr):
        hr_rank, hr_n = _pool_rank(rec_df, ("proj_HR", "HR", "Projected HR"), hr)
        elite_by_pct = pd.notna(hr_pct) and hr_pct >= 0.85
        elite_by_rank = hr_n >= 4 and hr_rank > 0 and hr_rank <= max(1, int(hr_n * 0.12 + 0.999))
        elite_by_abs = float(hr) >= 40
        if elite_by_pct or elite_by_rank or elite_by_abs:
            traits.append((92.0 + float(hr) / 20.0, "Elite Power", _BADGE_CSS["upside"], "power"))
        elif (pd.notna(hr_pct) and hr_pct >= 0.70) or float(hr) >= 30:
            traits.append((74.0 + float(hr) / 20.0, "Strong Power", _BADGE_CSS["category"], "power"))
        elif "HR" in needs and float(hr) >= 18:
            traits.append((80.0, "Category Need: HR", _BADGE_CSS["category"], "cat_hr"))

    if pd.notna(rbi):
        if (pd.notna(rbi_pct) and rbi_pct >= 0.85) or (pd.isna(rbi_pct) and float(rbi) >= 110):
            traits.append((86.0 + float(rbi) / 40.0, "Elite Run Production", _BADGE_CSS["upside"], "rbi"))
        elif (pd.notna(rbi_pct) and rbi_pct >= 0.65) or (pd.isna(rbi_pct) and float(rbi) >= 90):
            traits.append((72.0 + float(rbi) / 40.0, "Strong RBI", _BADGE_CSS["category"], "rbi"))
        elif "RBI" in needs and float(rbi) >= 70:
            traits.append((78.0, "Category Need: RBI", _BADGE_CSS["category"], "cat_rbi"))

    if pd.notna(runs):
        if (pd.notna(runs_pct) and runs_pct >= 0.85) or (pd.isna(runs_pct) and float(runs) >= 100):
            traits.append((78.0 + float(runs) / 40.0, "Elite Run Producer", _BADGE_CSS["upside"], "runs"))
        elif (pd.notna(runs_pct) and runs_pct >= 0.65) or (pd.isna(runs_pct) and float(runs) >= 85):
            traits.append((64.0 + float(runs) / 40.0, "Run Producer", _BADGE_CSS["category"], "runs"))
        elif "R" in needs and float(runs) >= 60:
            traits.append((70.0, "Helps Runs Need", _BADGE_CSS["category"], "runs_need"))

    if pd.notna(sb):
        speed_needed = "SB" in needs or "SB" in strength_set
        if (pd.notna(sb_pct) and sb_pct >= 0.80) or (pd.isna(sb_pct) and float(sb) >= 20):
            traits.append((84.0 + float(sb) / 15.0, "Speed Boost", _BADGE_CSS["upside"], "speed"))
        elif speed_needed and float(sb) >= 10:
            traits.append((76.0, "Fills SB Need", _BADGE_CSS["category"], "speed_need"))
        elif pos in {"1B", "C", "DH"} and ((pd.notna(sb_pct) and sb_pct >= 0.70) or float(sb) >= 15):
            traits.append((73.0, f"Speed at {pos}", _BADGE_CSS["upside"], "speed"))

    if pd.notna(avg):
        if (pd.notna(avg_pct) and avg_pct >= 0.85) or (pd.isna(avg_pct) and float(avg) >= 0.295):
            traits.append((70.0 + float(avg) * 10.0, "High AVG", _BADGE_CSS["category"], "avg"))
        elif ("AVG" in needs or "BA" in needs) and float(avg) >= 0.265:
            traits.append((68.0, "Fills Low-AVG Need", _BADGE_CSS["category"], "avg_need"))

    edge = _num(row, "Fantasy Edge")
    mdl = _num(row, "Model Rank")
    mkt = _num(row, "Market Rank")
    rank_edge = (
        float(mkt) - float(mdl)
        if pd.notna(mdl) and pd.notna(mkt)
        else float("nan")
    )
    bargain_edge = float(edge) if pd.notna(edge) else float("nan")
    if pd.isna(bargain_edge) and pd.notna(rank_edge):
        bargain_edge = rank_edge
    elif pd.notna(rank_edge):
        bargain_edge = max(float(bargain_edge), float(rank_edge))
    if (
        pd.notna(bargain_edge)
        and float(bargain_edge) >= 10
        and pd.notna(mdl)
        and pd.notna(mkt)
        and float(mdl) < float(mkt)
    ):
        traits.append(
            (88.0 + min(float(bargain_edge), 40.0) / 4.0, "Model Bargain", _BADGE_CSS["bargain"], "bargain")
        )
    elif (
        pd.notna(bargain_edge)
        and float(bargain_edge) >= 6
        and pd.notna(mdl)
        and pd.notna(mkt)
        and float(mdl) < float(mkt)
    ):
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
            traits.append((86.0, "Fills C Need", _BADGE_CSS["scarcity"], "catcher"))
        else:
            traits.append((70.0, f"Fills {pos} Need", _BADGE_CSS["position"], "fill_position"))

    scarcity = _num(row, "Scarcity Score")
    if pd.notna(scarcity) and float(scarcity) >= 0.65 and pos:
        # Only badge scarcity when the position is still an open need (or truly scarce).
        if gaps and pos in gaps:
            traits.append((68.0 + float(scarcity) * 10.0, "Scarce Position", _BADGE_CSS["scarcity"], "scarcity"))
        elif float(scarcity) >= 0.80:
            traits.append((58.0 + float(scarcity) * 10.0, f"{pos} Scarcity", _BADGE_CSS["scarcity"], "scarcity"))

    grade = _num(row, "Expected Fantasy Value")
    if pd.notna(grade):
        g = float(grade)
        g100 = g * 100.0 if g <= 1.5 else g
        grade_pct = _pool_percentile(rec_df, ("Expected Fantasy Value", "Player Grade"), g100 if g <= 1.5 else g)
        if (pd.notna(grade_pct) and grade_pct >= 0.85) or g100 >= 85:
            traits.append((71.0, "High Player Grade", _BADGE_CSS["gold"], "grade"))

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
    """Return up to two specific (label, css_class) badges — player-distinctive traits."""
    badges: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    seen_concepts: set[str] = set()

    def _add(label: str, css: str, *, concept: str = "") -> None:
        if label in seen_labels or len(badges) >= 2:
            return
        concept_key = concept or label.lower()
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
        if len(badges) >= 2:
            break

    if len(badges) < 2:
        pos = str(row.get("Primary Position") or "").strip()
        if gaps and pos and pos in gaps:
            _add(f"Fills {pos} Need", _BADGE_CSS["position"], concept="fill_position")
        if len(badges) < 1:
            rank_labels = {1: "Best Overall", 2: "Second Best", 3: "Third Best"}
            if rank in rank_labels:
                _add(rank_labels[rank], _BADGE_CSS["gold"], concept=f"rank_{rank}")

    return badges[:2]


_GENERIC_RANK_BADGES = frozenset({"Best Overall", "Second Best", "Third Best"})


def primary_recommendation_reason(
    rank: int,
    row: Any,
    *,
    badges: list[tuple[str, str]] | None = None,
    strengths: list[str] | None = None,
    gaps: list[str] | None = None,
    category_needs: list[str] | None = None,
    rec_df: Any = None,
) -> str:
    """One-line prose headline for the card — never repeats badge pill text."""
    pos = str(row.get("Primary Position") or "")
    edge = _num(row, "Fantasy Edge")
    badge_labels = {label for label, _css in (badges or [])}
    needs = {str(c).strip().upper() for c in (category_needs or []) if str(c).strip()}

    hr = _proj(row, "proj_HR", "HR")
    sb = _proj(row, "proj_SB", "SB")
    hr_pct = _pool_percentile(rec_df, ("proj_HR", "HR"), hr) if rec_df is not None else float("nan")
    if pd.notna(hr) and "Elite Power" not in badge_labels:
        if (pd.notna(hr_pct) and hr_pct >= 0.88) or (pd.isna(hr_pct) and float(hr) >= 40):
            return f"Projects {int(round(float(hr)))} HR — elite power vs this board"
        if pd.notna(hr) and float(hr) >= 30:
            return f"Projects {int(round(float(hr)))} HR"
    if pd.notna(sb) and float(sb) >= 18 and "Speed Boost" not in badge_labels:
        if "SB" in needs:
            return f"Projects for {int(round(float(sb)))} SB and directly improves your weakest category"
        return f"Projects {int(round(float(sb)))} SB — real speed contribution"

    if gaps and pos in gaps:
        if pos == "C":
            return "Fills your final catcher slot at a position with limited remaining depth"
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
