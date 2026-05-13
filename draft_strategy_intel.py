"""Evidence-backed draft strategy lines for Draft Assistant (no new scoring formulas).

Two short sentences max: roster/category numbers, positional depth, undrafted
tier drop-offs, availability vs pick, and Fantasy Edge — all from existing
columns and the same aggregates used for Draft Fit / scarcity heatmap.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


def _f(x, default=np.nan):
    try:
        v = float(pd.to_numeric(x, errors="coerce"))
        return v if pd.notna(v) else default
    except Exception:
        return default


def _fmt_ct(v: float) -> str:
    if pd.isna(v):
        return "—"
    v = float(v)
    return f"{v:.0f}" if abs(v) >= 10 else f"{v:.1f}"


def _fmt_ba(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):.3f}"


def _fmt_rate3(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):.3f}"


def _fmt_drop(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):.3f}"


def _weak_lift_pairs_55(
    row: Mapping[str, Any],
    roster_means: Mapping[str, Any],
    pool_means: Mapping[str, Any],
) -> list[tuple[str, str, float, float, float, str]]:
    """Return tuples (key, label, roster_mean, pool_mean, player_val, fmt_kind) where roster trails pool and player meets/exceeds pool."""
    specs = [
        ("SB", "stolen bases", "proj_SB", "ct"),
        ("BA", "batting average", "proj_BA", "ba"),
        ("HR", "home runs", "proj_HR", "ct"),
        ("RBI", "RBI", "proj_RBI", "ct"),
        ("R", "runs", "proj_R", "ct"),
    ]
    out: list[tuple[str, str, float, float, float, str]] = []
    for key, label, col, fmt_kind in specs:
        if col not in roster_means or col not in pool_means:
            continue
        rm = _f(roster_means.get(col))
        pm = _f(pool_means.get(col))
        pv = _f(row.get(col))
        if np.isnan(rm) or np.isnan(pm) or np.isnan(pv):
            continue
        if rm >= pm * 0.995:
            continue
        if pv < pm * 0.98:
            continue
        out.append((key, label, rm, pm, pv, fmt_kind))
    return out


def _weak_lift_pairs_points(
    row: Mapping[str, Any],
    roster_means: Mapping[str, Any],
    pool_means: Mapping[str, Any],
) -> list[tuple[str, str, float, float, float, str]]:
    specs = [
        ("Speed", "SB", "proj_SB", "ct"),
        ("Power", "HR", "proj_HR", "ct"),
        ("Run Production", "RBI", "proj_RBI", "ct"),
        ("Walks/OPS", "OPS", "proj_OPS", "rate3"),
    ]
    out: list[tuple[str, str, float, float, float, str]] = []
    for need_key, label, col, fmt_kind in specs:
        if col not in roster_means or col not in pool_means:
            continue
        rm = _f(roster_means.get(col))
        pm = _f(pool_means.get(col))
        pv = _f(row.get(col))
        if np.isnan(rm) or np.isnan(pm) or np.isnan(pv):
            continue
        if rm >= pm * 0.995:
            continue
        if pv < pm * 0.98:
            continue
        out.append((need_key, label, rm, pm, pv, fmt_kind))
    return out


def draft_strategy_line(
    row: Mapping[str, Any],
    *,
    draft_format: str,
    current_pick: int,
    position_meta_by_pos: Mapping[str, Mapping[str, Any]],
    median_scarcity_dropoff: float | None,
    remaining_high_sb_count: int,
    remaining_high_hr_count: int,
    category_needs: Iterable[str],
    roster_means: Mapping[str, Any],
    pool_means: Mapping[str, Any],
    needed_positions: Iterable[str],
    current_position_counts: Mapping[str, Any],
    target_position_counts: Mapping[str, Any],
) -> str:
    """Return up to two sentences with concrete numbers (no change to any score)."""
    pos = str(row.get("Primary Position", "") or "").strip()
    needed = {str(p).strip() for p in needed_positions if str(p).strip()}
    cat_need = {str(c).strip() for c in category_needs if str(c).strip()}

    sentences: list[str] = []

    # --- (1) Roster shortage + this player's projection number ---
    if draft_format == "5x5 Roto":
        lifts = _weak_lift_pairs_55(row, roster_means, pool_means)
        # Prefer a category the user flagged, else strongest SB/BA gap
        preferred = [x for x in lifts if x[0] in cat_need]
        pick_lift = preferred[0] if preferred else (lifts[0] if lifts else None)
        if pick_lift:
            _, label, rm, pm, pv, fmt_kind = pick_lift
            if fmt_kind == "ba":
                sentences.append(
                    f"Synced roster mean {label} is {_fmt_ba(rm)} vs {_fmt_ba(pm)} on the remaining pool; "
                    f"this player projects {_fmt_ba(pv)}."
                )
            else:
                sentences.append(
                    f"Synced roster mean {label} sits at {_fmt_ct(rm)} vs pool {_fmt_ct(pm)} among undrafted hitters; "
                    f"this player projects {_fmt_ct(pv)}."
                )
    else:
        lifts = _weak_lift_pairs_points(row, roster_means, pool_means)
        preferred = [x for x in lifts if x[0] in cat_need]
        pick_lift = preferred[0] if preferred else (lifts[0] if lifts else None)
        if pick_lift:
            _, label, rm, pm, pv, fmt_kind = pick_lift
            if fmt_kind == "rate3":
                sentences.append(
                    f"Roster mean {label} is {_fmt_rate3(rm)} vs pool {_fmt_rate3(pm)}; this player projects {_fmt_rate3(pv)}."
                )
            else:
                sentences.append(
                    f"Roster mean {label} is {_fmt_ct(rm)} vs pool {_fmt_ct(pm)}; this player projects {_fmt_ct(pv)}."
                )

    # --- (2a) Positional need + depth on the wire ---
    if pos and pos in needed:
        tgt = int(target_position_counts.get(pos, 0) or 0)
        cur = int(current_position_counts.get(pos, 0) or 0)
        meta = position_meta_by_pos.get(pos, {}) or {}
        avail = int(meta.get("available", 0) or 0)
        sentences.append(
            f"You still need {pos} on the synced roster ({cur}/{tgt} filled); "
            f"{avail} undrafted players list {pos} right now."
        )

    # --- (2b) Tier drop-off with numeric gap (avoid generic "cliff" copy) ---
    meta = position_meta_by_pos.get(pos, {}) or {}
    drop = _f(meta.get("dropoff"), np.nan)
    avail = int(meta.get("available", 0) or 0)
    md = median_scarcity_dropoff
    if len(sentences) < 2 and not np.isnan(drop) and md is not None and not np.isnan(md) and md > 0:
        if drop >= md * 1.12:
            sentences.append(
                f"Among undrafted {pos}, top blended EFV vs replacement sits about {_fmt_drop(drop)} above replacement "
                f"({avail} bodies); that gap is wider than the median position on the board ({_fmt_drop(md)})."
            )

    # --- (2c) HR surplus / duplicate shape (numbers) ---
    if len(sentences) < 2 and draft_format == "5x5 Roto" and "proj_HR" in roster_means and "proj_HR" in pool_means:
        rh = _f(roster_means.get("proj_HR"))
        ph = _f(pool_means.get("proj_HR"))
        pvh = _f(row.get("proj_HR"))
        if not np.isnan(rh) and not np.isnan(ph) and rh > ph * 1.06 and not np.isnan(pvh) and pvh >= ph:
            sentences.append(
                f"Your roster mean HR projection ({_fmt_ct(rh)}) already clears the undrafted pool mean ({_fmt_ct(ph)}); "
                f"this {pos} still projects {_fmt_ct(pvh)} HR — mostly stacking an existing strength."
            )

    # --- (2d) BA lift without tanking HR (5x5) ---
    if len(sentences) < 2 and draft_format == "5x5 Roto":
        pba = _f(row.get("proj_BA"))
        phr = _f(row.get("proj_HR"))
        pm_ba = _f(pool_means.get("proj_BA")) if pool_means else np.nan
        pm_hr = _f(pool_means.get("proj_HR")) if pool_means else np.nan
        if (
            not np.isnan(pba)
            and not np.isnan(pm_ba)
            and pba >= pm_ba * 1.01
            and not np.isnan(phr)
            and not np.isnan(pm_hr)
            and phr >= pm_hr * 0.92
        ):
            sentences.append(
                f"Projection {_fmt_ba(pba)} AVG clears the pool mean ({_fmt_ba(pm_ba)}) while HR stays near "
                f"the pool bar ({_fmt_ct(phr)} vs {_fmt_ct(pm_hr)})."
            )

    # --- (2e) Speed on the wire + this row SB ---
    if len(sentences) < 2 and draft_format == "5x5 Roto":
        sb = _f(row.get("proj_SB"))
        if remaining_high_sb_count <= 16 and not np.isnan(sb) and sb >= 14:
            sentences.append(
                f"Only {remaining_high_sb_count} undrafted hitters still project {_fmt_ct(12.0)}+ SB; "
                f"this player is at {_fmt_ct(sb)} SB."
            )

    # --- (2f) Power on the wire ---
    if len(sentences) < 2 and draft_format == "5x5 Roto":
        hr = _f(row.get("proj_HR"))
        if remaining_high_hr_count <= 20 and not np.isnan(hr) and hr >= 24:
            sentences.append(
                f"Roughly {remaining_high_hr_count} undrafted bats still show 22+ HR projections; "
                f"this player sits at {_fmt_ct(hr)} HR in that tier."
            )

    # --- (2g) Availability vs pick (numeric) ---
    if len(sentences) < 2:
        ap = _f(row.get("Availability Probability"))
        mr = _f(row.get("Market Rank"))
        pick = float(current_pick) if current_pick else np.nan
        if not np.isnan(ap) and not np.isnan(mr) and not np.isnan(pick):
            if ap <= 0.42:
                sentences.append(
                    f"Pick {int(pick)} vs market rank {int(round(mr))}: modeled stay-now probability is about {ap * 100:.0f}% "
                    f"— lean take-now if the stat line matters this turn."
                )
            elif ap >= 0.78:
                sentences.append(
                    f"Pick {int(pick)} vs market rank {int(round(mr))}: modeled stay-now probability is about {ap * 100:.0f}% "
                    f"— ADP usually lets you circle back unless the positional gap above worries you."
                )

    # --- (2h) Fantasy Edge numeric ---
    if len(sentences) < 2:
        fe = _f(row.get("Fantasy Edge"))
        mrank = _f(row.get("Market Rank"))
        drank = _f(row.get("Model Rank"))
        if not np.isnan(fe) and fe >= 15 and not np.isnan(mrank) and not np.isnan(drank):
            sentences.append(
                f"Fantasy Edge +{fe:.0f} ranks (market {int(round(mrank))} vs model {int(round(drank))}) — same edge math as the table."
            )

    # --- (2i) Risk / breakout with numbers from row ---
    if len(sentences) < 2:
        risk = _f(row.get("Risk Penalty"), 0.0)
        brk = _f(row.get("Breakout Probability"))
        if not np.isnan(brk) and brk >= 0.55 and not np.isnan(risk) and risk > 0.04:
            sentences.append(
                f"Breakout signal {brk:.2f} pairs with a higher expert-rank risk penalty ({risk:.3f}) than calmer names in this band."
            )
        elif not np.isnan(risk) and risk < 0.022:
            sentences.append(
                f"Expert-rank risk penalty is low ({risk:.3f}) versus other options here — steadier projection disagreement profile."
            )

    # Trim to 2 sentences, de-duplicate similar starts
    out: list[str] = []
    for s in sentences:
        s = str(s).strip()
        if not s or s in out:
            continue
        if out and s[:24] == out[-1][:24]:
            continue
        out.append(s)
        if len(out) >= 2:
            break

    text = " ".join(out).strip()
    if len(text) > 420:
        text = text[:417].rsplit(".", 1)[0] + "."
    if not text:
        return "No extra strategy tension vs current filters — Draft Fit and Team fit already summarize value and roster fit."
    return text
