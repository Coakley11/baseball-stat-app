"""Roster-context explanations for Draft Assistant (no new scoring formulas).

Builds 1–2 short sentences from synced roster projection means vs the full draft pool,
player projections on the same columns, positional targets, and optional expert-volatility.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

POS_LABEL = {
    "C": "catcher",
    "1B": "first base",
    "2B": "second base",
    "3B": "third base",
    "SS": "shortstop",
    "OF": "outfield",
    "DH": "DH",
    "P": "pitcher",
}


def _f(x, default=np.nan):
    try:
        v = float(pd.to_numeric(x, errors="coerce"))
        return v if pd.notna(v) else default
    except Exception:
        return default


def _oxford(phrases: list[str]) -> str:
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def _has_roster_projection_context(roster_means: dict) -> bool:
    return any(v is not None and pd.notna(v) for v in roster_means.values())


def _weak_strong_help(
    row: Mapping[str, Any],
    roster_means: dict,
    pool_means: dict,
    triples: list[tuple[str, str, str]],
) -> tuple[list[str], list[str], list[str]]:
    """Return (weak_phrases, strong_phrases, helps_weak_phrases) using roster vs pool and player vs pool."""
    weak: list[str] = []
    strong: list[str] = []
    helps: list[str] = []
    for phrase, col, _short in triples:
        rm = roster_means.get(col)
        pm = pool_means.get(col)
        if rm is None or pm is None or pd.isna(rm) or pd.isna(pm):
            continue
        if rm < pm:
            weak.append(phrase)
            pv = _f(row.get(col))
            if not pd.isna(pv) and not pd.isna(pm) and pv >= pm:
                helps.append(phrase)
        elif rm > pm:
            strong.append(phrase)
    return weak, strong, helps


def _triples_for_format(draft_format: str) -> list[tuple[str, str, str]]:
    if draft_format == "5x5 Roto":
        return [
            ("runs", "proj_R", "R"),
            ("home runs", "proj_HR", "HR"),
            ("RBI", "proj_RBI", "RBI"),
            ("stolen bases", "proj_SB", "SB"),
            ("batting average", "proj_BA", "BA"),
            ("on-base percentage", "proj_OBP", "OBP"),
            ("OPS", "proj_OPS", "OPS"),
        ]
    return [
        ("home-run power", "proj_HR", "HR"),
        ("RBI", "proj_RBI", "RBI"),
        ("runs scored", "proj_R", "R"),
        ("stolen bases", "proj_SB", "SB"),
        ("OPS", "proj_OPS", "OPS"),
        ("on-base percentage", "proj_OBP", "OBP"),
        ("plate appearances (AB)", "AB", "AB"),
    ]


def team_fit_summary_line(
    row: Mapping[str, Any],
    *,
    draft_format: str,
    needed_positions: Iterable[str],
    category_needs: Iterable[str],
    roster_means: dict,
    pool_means: dict,
    current_position_counts: dict,
    target_position_counts: dict,
    roster_expert_std_mean: float | None = None,
    pool_expert_std_mean: float | None = None,
) -> str:
    """Return 1–2 concise sentences grounded in this roster vs the pool (existing projections only)."""
    needed = {str(p).strip() for p in needed_positions if str(p).strip()}
    cat_need = [str(c).strip() for c in category_needs if str(c).strip()]
    triples = _triples_for_format(draft_format)
    has_roster = _has_roster_projection_context(roster_means)

    sentences: list[str] = []

    pos = str(row.get("Primary Position", "") or "").strip()
    tgt = int(target_position_counts.get(pos, 0) or 0) if pos else 0
    cur = int(current_position_counts.get(pos, 0) or 0) if pos else 0

    if pos and pos in needed and tgt > 0:
        slot = POS_LABEL.get(pos, pos)
        if cur < tgt:
            sentences.append(
                f"You still need {slot} ({cur} rostered vs {tgt} target); this player fills that positional gap."
            )
        else:
            sentences.append(
                f"Your build still prioritizes {slot}; this player matches that positional priority."
            )

    weak: list[str] = []
    strong: list[str] = []
    helps: list[str] = []
    if has_roster:
        weak, strong, helps = _weak_strong_help(row, roster_means, pool_means, triples)

        if helps:
            huniq = list(dict.fromkeys(helps))
            if len(huniq) >= 2:
                sentences.append(
                    f"Your synced roster averages trail the draft pool in {_oxford(huniq)}; "
                    f"this player's projections meet or beat the pool average in those categories."
                )
            else:
                sentences.append(
                    f"Your roster runs below the pool in {huniq[0]}; this player's projection clears the pool bar there."
                )
        elif weak and not sentences:
            wshow = list(dict.fromkeys(weak))[:4]
            sentences.append(
                f"Your roster is softer than the pool in {_oxford(wshow)}; "
                f"this player's projection still sits under the pool average in those spots, so it is not the clean stat patch."
            )
        elif weak and len(sentences) >= 1 and not helps:
            wshow = list(dict.fromkeys(weak))[:3]
            sentences.append(
                f"Separately, your roster already trails the pool in {_oxford(wshow)}, and this row does not lift every one of those gaps."
            )

        hr_phrase = "home runs" if draft_format == "5x5 Roto" else "home-run power"
        obp_phrase = "on-base percentage"
        if len(sentences) < 2 and hr_phrase in strong:
            pm_hr = pool_means.get("proj_HR")
            pv_hr = _f(row.get("proj_HR"))
            if not pd.isna(pv_hr) and not pd.isna(pm_hr) and pv_hr >= pm_hr and hr_phrase not in helps:
                rm_obp = roster_means.get("proj_OBP")
                pm_obp = pool_means.get("proj_OBP")
                pv_obp = _f(row.get("proj_OBP"))
                if (
                    obp_phrase in weak
                    and rm_obp is not None
                    and pm_obp is not None
                    and not pd.isna(rm_obp)
                    and not pd.isna(pm_obp)
                    and not pd.isna(pv_obp)
                    and pv_obp >= pm_obp
                ):
                    sentences.append(
                        "Your roster already skews power-heavy vs the pool; this player still upgrades OBP where you lag."
                    )
                elif len(sentences) < 2:
                    sentences.append(
                        "Your roster already clears the pool in home-run projections; this player stacks more of the same power shape."
                    )

    if not has_roster:
        lifted: list[str] = []
        if draft_format == "5x5 Roto":
            lab_map = {"R": "runs", "HR": "home runs", "RBI": "RBI", "SB": "stolen bases", "BA": "batting average"}
            col_map = {"R": "proj_R", "HR": "proj_HR", "RBI": "proj_RBI", "SB": "proj_SB", "BA": "proj_BA"}
            for lab in cat_need:
                col = col_map.get(lab)
                if not col or col not in pool_means:
                    continue
                pm = pool_means[col]
                pv = _f(row.get(col))
                if not pd.isna(pv) and not pd.isna(pm) and pv >= pm:
                    lifted.append(lab_map[lab])
        else:
            pts = [
                ("Power", "home-run power", "proj_HR"),
                ("Run Production", "RBI", "proj_RBI"),
                ("Speed", "stolen bases", "proj_SB"),
                ("Walks/OPS", "OPS", "proj_OPS"),
                ("Volume", "plate appearances", "AB"),
            ]
            for _key, phrase, col in pts:
                if _key not in cat_need or col not in pool_means:
                    continue
                pm = pool_means[col]
                pv = _f(row.get(col))
                if not pd.isna(pv) and not pd.isna(pm) and pv >= pm:
                    lifted.append(phrase)
        if lifted:
            sentences.append(
                f"No synced roster yet — against your category priorities, this player clears the pool projection average in {_oxford(lifted)}."
            )
        elif not sentences:
            sentences.append(
                "Sync your Draft Room roster to compare your real category averages to the pool; table rankings and scores stay the same."
            )

    risk_pen = _f(row.get("Risk Penalty"), 0.0)
    brk = _f(row.get("Breakout Probability"))
    fe = _f(row.get("Fantasy Edge"))
    sc_b = _f(row.get("Position Scarcity Bonus"), 0.0)

    if len(sentences) < 2:
        if (
            roster_expert_std_mean is not None
            and pool_expert_std_mean is not None
            and pd.notna(roster_expert_std_mean)
            and pd.notna(pool_expert_std_mean)
            and roster_expert_std_mean > pool_expert_std_mean * 1.03
            and not np.isnan(risk_pen)
            and risk_pen < 0.028
        ):
            sentences.append(
                "Your roster already carries more expert-rank disagreement than the average board player; this pick leans steadier on that axis."
            )
        elif not np.isnan(brk) and brk >= 0.55 and not np.isnan(risk_pen) and risk_pen > 0.038:
            sentences.append(
                "Breakout-weighted projection with elevated expert disagreement — more ceiling, more volatility."
            )
        elif not np.isnan(fe) and fe >= 22:
            sentences.append("Model rank runs well ahead of market rank on this player (same signal as Fantasy Edge).")
        elif not np.isnan(sc_b) and sc_b > 0.055:
            sentences.append("Among remaining players at this position, value above replacement stands out.")

    out = [s for s in sentences if s]
    if not out:
        return "Team fit needs a synced Draft Room roster or category priorities to personalize; draft scores in the table are unchanged."

    text = " ".join(out[:2]).strip()
    if len(text) > 420:
        text = text[:417].rsplit(" ", 1)[0] + "…"
    return text
