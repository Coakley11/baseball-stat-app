"""Lineup Assistant scoring, recommended starters and lineup diagnosis.

Moved verbatim from streamlit_app.py (build_lineup_assistant_scores, build_position_aware_lineup,
lineup_diagnosis_report and their helpers); the app keeps a cached wrapper for the scores and
imports the rest back.

Inputs are roster frames with *current season-to-date* stats (the Standings/Lineup pages load
them from the MLB feed). Nothing here fetches data, reads the session, or writes anything.
Recommended starters use the fantasy slot rule (``player_eligible_for_slot_strict``), the same
rule Save Lineup enforces, so a recommended lineup is always one the user could save.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from fantasy_slot_eligibility import (
    LINEUP_DEFAULT_HITTING_SLOTS,
    _split_primary_positions,
    player_eligible_for_slot_strict,
)
from stat_helpers import fmt_int, fmt_rate_3, normalize_series, safe_numeric_series


def build_lineup_assistant_scores(roster_stats, scoring_format="5x5 Roto", custom_weights=None):
    """Create start/sit style scores from current roster stats.

    Uses current-season stat columns when available. If the Fantasy Standings Tracker
    has already loaded MLB API/current stats, this page reuses that data.
    """
    df = roster_stats.copy()
    if df.empty:
        return df

    for c in ["HR", "RBI", "R", "SB", "BA", "OBP", "SLG", "OPS", "AB", "H", "BB", "G"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Core current production signals.
    if scoring_format == "Points League":
        if custom_weights is None:
            custom_weights = {"R": 1.0, "RBI": 1.0, "HR": 4.0, "SB": 2.0, "H": 1.0, "BB": 1.0, "OPS": 10.0}
        raw_score = pd.Series(0.0, index=df.index)
        for stat, weight in custom_weights.items():
            if stat in df.columns:
                raw_score += pd.to_numeric(df[stat], errors="coerce").fillna(0) * float(weight)
        df["Current Fantasy Score"] = normalize_series(raw_score)
    else:
        parts = []
        for c in ["R", "HR", "RBI", "SB", "BA", "OPS"]:
            if c in df.columns:
                parts.append(normalize_series(pd.to_numeric(df[c], errors="coerce")))
        df["Current Fantasy Score"] = sum(parts) / len(parts) if parts else 0.0

    # Momentum proxy: current rates + power/speed blend. This is a season-to-date proxy,
    # not true last-7-day game logs unless such data is uploaded later.
    momentum_parts = []
    for c, w in [("OPS", 0.35), ("HR", 0.20), ("RBI", 0.15), ("R", 0.15), ("SB", 0.10), ("BA", 0.05)]:
        if c in df.columns:
            momentum_parts.append(normalize_series(pd.to_numeric(df[c], errors="coerce")) * w)
    df["Momentum Score"] = sum(momentum_parts) if momentum_parts else df["Current Fantasy Score"]

    # Consistency proxy: rate stability and playing-time volume.
    volume = normalize_series(safe_numeric_series(df, "AB", 0)) if "AB" in df.columns else pd.Series(0.5, index=df.index)
    rate_floor = normalize_series(safe_numeric_series(df, "OPS", np.nan).fillna(safe_numeric_series(df, "BA", 0)))
    df["Consistency Score"] = normalize_series(volume * 0.55 + rate_floor * 0.45)

    # Volatility proxy: power/speed profiles can win weeks but are less stable than contact/volume.
    power_speed = pd.Series(0.0, index=df.index)
    if "HR" in df.columns:
        power_speed += normalize_series(df["HR"]) * 0.55
    if "SB" in df.columns:
        power_speed += normalize_series(df["SB"]) * 0.35
    if "BA" in df.columns:
        power_speed -= normalize_series(df["BA"]) * 0.10
    df["Volatility Meter"] = normalize_series(power_speed)

    df["Lineup Confidence"] = normalize_series(
        df["Current Fantasy Score"] * 0.45 +
        df["Momentum Score"] * 0.30 +
        df["Consistency Score"] * 0.25
    )

    def classify_action(row):
        conf = pd.to_numeric(row.get("Lineup Confidence", np.nan), errors="coerce")
        mom = pd.to_numeric(row.get("Momentum Score", np.nan), errors="coerce")
        vol = pd.to_numeric(row.get("Volatility Meter", np.nan), errors="coerce")
        if pd.isna(conf):
            return "Watch"
        if conf >= 0.72:
            return "Start"
        if conf >= 0.55 and mom >= 0.55:
            return "Lean Start"
        if conf < 0.35 and vol >= 0.55:
            return "Bench / Risk"
        if conf < 0.40:
            return "Sit"
        return "Matchup Dependent"

    def _confidence_label(conf_val: float | None) -> str:
        if conf_val is None or pd.isna(conf_val):
            return "Low"
        if conf_val >= 0.72:
            return "High"
        if conf_val >= 0.55:
            return "Medium"
        return "Low"

    def make_lineup_reason(row):
        action = str(row.get("Start/Sit Recommendation") or "Watch")
        conf = pd.to_numeric(row.get("Lineup Confidence", np.nan), errors="coerce")
        mom = pd.to_numeric(row.get("Momentum Score", np.nan), errors="coerce")
        consistency = pd.to_numeric(row.get("Consistency Score", np.nan), errors="coerce")
        vol = pd.to_numeric(row.get("Volatility Meter", np.nan), errors="coerce")
        current = pd.to_numeric(row.get("Current Fantasy Score", np.nan), errors="coerce")
        conf_label = _confidence_label(conf if pd.notna(conf) else None)
        reasons: list[str] = []

        if action in ("Start", "Lean Start"):
            if pd.notna(current) and current >= 0.70:
                reasons.append("Strong current production trend")
            if pd.notna(mom) and mom >= 0.65:
                reasons.append("Positive momentum vs bench alternatives")
            if pd.notna(consistency) and consistency >= 0.65:
                reasons.append("Consistent playing time and rate support")
            if "HR" in row and pd.to_numeric(row.get("HR"), errors="coerce") >= 10:
                reasons.append(f"Above-average HR contribution ({fmt_int(row.get('HR'))} HR)")
            if "RBI" in row and pd.to_numeric(row.get("RBI"), errors="coerce") >= 30:
                reasons.append(f"Strong RBI category contribution ({fmt_int(row.get('RBI'))} RBI)")
        elif action in ("Sit", "Bench / Risk"):
            if pd.notna(current) and current < 0.45:
                reasons.append("Current production below roster alternatives")
            if pd.notna(mom) and mom < 0.45:
                reasons.append("Production trend declining recently")
            if pd.notna(consistency) and consistency < 0.45:
                reasons.append("Limited playing time or unstable rates")
            if pd.notna(vol) and vol >= 0.60:
                reasons.append("Boom/bust profile adds risk this week")
        else:
            if pd.notna(vol) and vol >= 0.60:
                reasons.append("Boom/bust profile — upside with inconsistency")
            if pd.notna(mom) and mom >= 0.55:
                reasons.append("Strong upside when hot, but streaky")
            if pd.notna(consistency) and consistency < 0.55:
                reasons.append("Depends on category needs and matchup this week")

        if "OPS" in row and pd.to_numeric(row.get("OPS"), errors="coerce") >= 0.820 and len(reasons) < 4:
            reasons.append(f"Strong OPS ({fmt_rate_3(row.get('OPS'))})")
        if "SB" in row and pd.to_numeric(row.get("SB"), errors="coerce") >= 8 and len(reasons) < 4:
            reasons.append(f"Useful speed contribution ({fmt_int(row.get('SB'))} SB)")
        if not reasons:
            reasons.append("Best available fit for this roster slot")

        bullets = "\n".join(f"- {line}" for line in reasons[:4])
        return f"Confidence: {conf_label}\nReason:\n{bullets}"

    df["Start/Sit Recommendation"] = df.apply(classify_action, axis=1)
    df["Lineup Reason"] = df.apply(make_lineup_reason, axis=1)

    return df


def _top_category_contributors(df, cat: str, n: int = 3) -> list[str]:
    """Top player names driving a counting category on this roster subset."""
    if df is None or df.empty or cat not in df.columns or "Player" not in df.columns:
        return []
    sub = df[["Player", cat]].copy()
    sub[cat] = pd.to_numeric(sub[cat], errors="coerce").fillna(0)
    sub = sub[sub[cat] > 0].sort_values(cat, ascending=False).head(n)
    return [f"**{r.Player}** ({fmt_int(r[cat])} {cat})" for _, r in sub.iterrows()]


def _weak_category_explanation(df, cat: str, rate_col: str = "BA") -> str:
    """Explain a weak category with roster context."""
    if df is None or df.empty:
        return ""
    if cat in ("AVG", "OBP"):
        src = "OBP" if cat == "OBP" and "OBP" in df.columns else "BA"
        if src not in df.columns:
            return f"Limited {cat} support on this roster."
        vals = pd.to_numeric(df[src], errors="coerce")
        low = df.loc[vals.nsmallest(2).index, "Player"].astype(str).tolist() if "Player" in df.columns else []
        if low:
            return f"Soft {cat} — power-heavy bats like {', '.join(low[:2])} pull the rate down."
        return f"Soft {cat} relative to counting categories."
    if cat not in df.columns:
        return ""
    totals = pd.to_numeric(df[cat], errors="coerce").fillna(0)
    if cat == "SB" and totals.sum() < 20:
        names = df.loc[totals.nlargest(3).index, "Player"].astype(str).tolist() if "Player" in df.columns else []
        if names:
            return f"Light on steals — top speed is {', '.join(names[:2])} ({fmt_int(totals.max())} SB max)."
        return "Roster lacks high-volume base stealers."
    if cat == "HR" and totals.sum() > 0:
        top = _top_category_contributors(df, "HR", 3)
        if top:
            return f"Power comes from {', '.join(top)}."
    contributors = _top_category_contributors(df, cat, 2)
    if contributors:
        return f"Top {cat}: {', '.join(contributors)}."
    return ""


def _slot_gap_trade_rows(missing_slots):
    """One recommendation row per unfilled slot *type* (OF count rolled into copy)."""
    if not missing_slots:
        return []
    rows = []
    for slot, cnt in Counter(missing_slots).items():
        if slot == "UTIL":
            detail = (
                "Your lineup has no eligible **UTIL** starter for the UTIL slot. "
                "Add or trade for a versatile non-pitcher bat (multi-position eligibility helps)."
            )
        elif slot == "OF":
            detail = (
                f"Your lineup leaves **{cnt}** outfield starter slot(s) empty (no eligible OF/LF/CF/RF). "
                "Add or trade for outfielders or bats with OF eligibility."
            )
        elif slot == "C":
            detail = (
                "Your lineup has no eligible **C** starter. "
                "Target a catcher or a flexible bat with C eligibility."
            )
        elif slot == "SS":
            detail = (
                "Your lineup has no eligible **SS** starter. "
                "Target a shortstop or middle-infield (2B/SS) profile."
            )
        elif slot == "2B":
            detail = (
                "Your lineup has no eligible **2B** starter. "
                "Target a second baseman or middle-infield (2B/SS) profile."
            )
        elif slot == "3B":
            detail = (
                "Your lineup has no eligible **3B** starter. "
                "Target a third baseman or corner infield (1B/3B) profile."
            )
        elif slot == "1B":
            detail = (
                "Your lineup has no eligible **1B** starter. "
                "Target a first baseman or multi-position corner infielder (1B/3B)."
            )
        else:
            detail = (
                f"Your lineup has no eligible **{slot}** starter. "
                f"Add or trade for a player with **{slot}** on the eligibility card."
            )
        rows.append({"Type": "Roster / slot", "Label": "Need", "Detail": detail})
    return rows


def build_position_aware_lineup(scored_df, *, slots=None, pos_col="Primary Position"):
    """Assign each required slot to the best remaining eligible player by Lineup Confidence.

    Returns dict: lineup_df (with Fantasy slot), slot_warnings, missing_slots, slots_used.
    """
    if slots is None:
        slots = list(LINEUP_DEFAULT_HITTING_SLOTS)
    else:
        slots = list(slots)
    out_empty = {
        "lineup_df": pd.DataFrame(),
        "slot_warnings": [],
        "missing_slots": [],
        "slots_used": slots,
    }
    if scored_df is None or scored_df.empty:
        return out_empty

    df = scored_df.sort_values("Lineup Confidence", ascending=False, na_position="last").copy()
    if "_pos_tokens" in df.columns:
        df["_pos_tokens"] = df["_pos_tokens"].apply(
            lambda x: x if isinstance(x, list) and x else _split_primary_positions("")
        )
    elif pos_col in df.columns:
        df["_pos_tokens"] = df[pos_col].apply(_split_primary_positions)
    else:
        df["_pos_tokens"] = [[] for _ in range(len(df))]

    assigned_idx = set()
    lineup_rows = []
    slot_warnings = []
    missing_slots = []
    of_count = 0

    for slot in slots:
        display_slot = slot
        if slot == "OF":
            of_count += 1
            display_slot = f"OF{of_count}"
        elig_idx = []
        for ix in df.index:
            if ix in assigned_idx:
                continue
            toks = df.at[ix, "_pos_tokens"]
            if not isinstance(toks, list):
                toks = []
            if player_eligible_for_slot_strict(toks, slot):  # same rule as Save Lineup
                elig_idx.append(ix)
        if not elig_idx:
            if slot == "OF":
                slot_warnings.append("No eligible OF available for this lineup slot.")
            else:
                slot_warnings.append(f"No eligible {slot} available for this lineup slot.")
            missing_slots.append(slot)
            continue
        best_ix = max(
            elig_idx,
            key=lambda i: float(df.loc[i, "Lineup Confidence"]) if pd.notna(df.loc[i, "Lineup Confidence"]) else -1.0,
        )
        assigned_idx.add(best_ix)
        row = df.loc[best_ix].copy()
        row["Fantasy slot"] = display_slot
        lineup_rows.append(row)

    lineup_df = pd.DataFrame(lineup_rows) if lineup_rows else pd.DataFrame()
    if not lineup_df.empty and "_pos_tokens" in lineup_df.columns:
        lineup_df = lineup_df.drop(columns=["_pos_tokens"], errors="ignore")

    return {
        "lineup_df": lineup_df,
        "slot_warnings": slot_warnings,
        "missing_slots": missing_slots,
        "slots_used": slots,
    }


_ROSTER_SLOT_DISPLAY_ORDER = ("C", "1B", "2B", "3B", "SS", "OF", "UTIL")


def _roster_position_slot_list(roster_df: pd.DataFrame) -> list[str]:
    """Slot list derived from the roster's own positions (no invented defaults).

    Used for mock drafts saved without roster-slot rules: every rostered position
    becomes a slot so the position-aware builder can seat players without ever
    reporting a 'missing' slot the league never had.
    """
    if roster_df is None or roster_df.empty:
        return []
    pos_col = None
    for candidate in ("Primary Position", "Position", "primaryPos"):
        if candidate in roster_df.columns:
            pos_col = candidate
            break
    counts: dict[str, int] = {}
    if pos_col is not None:
        for val in roster_df[pos_col].tolist():
            tokens = _split_primary_positions(val)
            token = tokens[0] if tokens else "DH"
            slot = "UTIL" if token in ("DH", "P", "SP", "RP") else token
            counts[slot] = counts.get(slot, 0) + 1
    if not counts:
        counts = {"UTIL": len(roster_df)}
    slot_list: list[str] = []
    for slot in _ROSTER_SLOT_DISPLAY_ORDER:
        slot_list.extend([slot] * counts.get(slot, 0))
    for slot, n in counts.items():
        if slot not in _ROSTER_SLOT_DISPLAY_ORDER:
            slot_list.extend([slot] * n)
    return slot_list


def _lineup_team_rate(st_df, rate_col):
    """Combined rate for a subset (H/AB for BA; mean OBP if no PA weights)."""
    if st_df is None or st_df.empty:
        return np.nan
    rate_col = str(rate_col).upper()
    if rate_col == "BA" and "H" in st_df.columns and "AB" in st_df.columns:
        h = pd.to_numeric(st_df["H"], errors="coerce").fillna(0).sum()
        ab = pd.to_numeric(st_df["AB"], errors="coerce").fillna(0).sum()
        return float(h / ab) if ab > 0 else np.nan
    if rate_col == "OBP" and "OBP" in st_df.columns:
        w = None
        if "PA" in st_df.columns:
            w = pd.to_numeric(st_df["PA"], errors="coerce").fillna(0)
        elif "AB" in st_df.columns and "BB" in st_df.columns:
            w = pd.to_numeric(st_df["AB"], errors="coerce").fillna(0) + pd.to_numeric(st_df["BB"], errors="coerce").fillna(0)
        obp = pd.to_numeric(st_df["OBP"], errors="coerce")
        if w is not None and w.sum() > 0:
            return float((obp * w).sum() / w.sum())
        return float(obp.mean()) if obp.notna().any() else np.nan
    if rate_col == "BA" and "BA" in st_df.columns:
        return float(pd.to_numeric(st_df["BA"], errors="coerce").mean())
    return np.nan


def _lineup_pitching_block(pdf):
    """Return dict of pitching aggregates if roster has pitching columns."""
    cols = {c.lower(): c for c in pdf.columns}
    wcol = cols.get("w")
    kcol = cols.get("so") or cols.get("k")
    svcol = cols.get("sv")
    eracol = cols.get("era")
    whipcol = cols.get("whip")
    if not any([wcol, kcol, svcol, eracol, whipcol]):
        return None
    out = {}
    if wcol:
        out["W"] = float(pd.to_numeric(pdf[wcol], errors="coerce").fillna(0).sum())
    if kcol:
        out["SO"] = float(pd.to_numeric(pdf[kcol], errors="coerce").fillna(0).sum())
    if svcol:
        out["SV"] = float(pd.to_numeric(pdf[svcol], errors="coerce").fillna(0).sum())
    if eracol:
        out["ERA"] = float(pd.to_numeric(pdf[eracol], errors="coerce").mean())
    if whipcol:
        out["WHIP"] = float(pd.to_numeric(pdf[whipcol], errors="coerce").mean())
    return out if out else None


def lineup_diagnosis_report(
    starters_df,
    full_team_df,
    lineup_format,
    rate_col="BA",
    *,
    missing_slots=None,
    slot_warnings=None,
    league_roster_df=None,
):
    """Build category strength summary and recommendation rows from current roster stats (no new formulas on raw MLB stats)."""
    out = {
        "hitting_table": pd.DataFrame(),
        "pitching_table": pd.DataFrame(),
        "archetype": "",
        "strongest": [],
        "weakest": [],
        "strongest_detail": "",
        "weakest_detail": "",
        "balance_label": "",
        "position_note": "",
        "dragger_note": "",
        "surplus_note": "",
        "recommendations": [],
        "slot_gaps": "",
    }
    missing_slots = list(missing_slots or [])
    slot_warnings = list(slot_warnings or [])
    ms_counts = Counter(missing_slots)
    if ms_counts:
        parts = []
        for k in ("C", "1B", "2B", "3B", "SS", "OF", "UTIL"):
            if k not in ms_counts:
                continue
            n = ms_counts[k]
            parts.append(f"**{k}**" + (f" (×{n})" if n > 1 else ""))
        out["slot_gaps"] = (
            "**Roster is not yet complete.** Analysis is based on currently assigned players. "
            "Open roster slots: "
            + ", ".join(parts)
            + "."
        )

    if full_team_df is None or full_team_df.empty:
        out["archetype"] = "Add roster stats to run a lineup diagnosis."
        warn_rows = [{"Type": "Slot", "Label": "Alert", "Detail": w} for w in dict.fromkeys(slot_warnings)]
        out["recommendations"] = (warn_rows + _slot_gap_trade_rows(missing_slots))[:5]
        return out

    tm_df = full_team_df.copy()

    if starters_df is None or starters_df.empty:
        if ms_counts:
            out["archetype"] = "**Incomplete lineup:** one or more required fantasy slots have no eligible starter on this roster."
        else:
            out["archetype"] = "No recommended starters to analyze — check roster and position columns."
        pitch = _lineup_pitching_block(tm_df)
        if pitch:
            out["pitching_table"] = pd.DataFrame([{"Category": k, "Team total": v} for k, v in pitch.items()])
        out["recommendations"] = (
            [{"Type": "Slot", "Label": "Alert", "Detail": w} for w in dict.fromkeys(slot_warnings)]
            + _slot_gap_trade_rows(missing_slots)
        )[:5]
        if out.get("slot_gaps"):
            out["position_note"] = out["slot_gaps"]
        return out

    st_df = starters_df.copy()
    rate_col = "OBP" if str(rate_col).upper() == "OBP" and "OBP" in st_df.columns else "BA"

    cats_count = [c for c in ["HR", "RBI", "R", "SB"] if c in st_df.columns]
    if not cats_count and rate_col not in st_df.columns and "H" not in st_df.columns:
        out["archetype"] = "Not enough stat columns (HR/RBI/R/SB or rate) on this roster to diagnose."
        out["recommendations"] = (
            [{"Type": "Slot", "Label": "Alert", "Detail": w} for w in dict.fromkeys(slot_warnings)]
            + _slot_gap_trade_rows(missing_slots)
        )[:5]
        if ms_counts and not out.get("position_note"):
            out["position_note"] = out.get("slot_gaps", "")
        return out

    rows = []
    for c in cats_count:
        s_sum = pd.to_numeric(st_df[c], errors="coerce").fillna(0).sum()
        t_sum = pd.to_numeric(tm_df[c], errors="coerce").fillna(0).sum()
        pct = (s_sum / t_sum * 100.0) if t_sum > 0 else np.nan
        rows.append({"Category": c, "Lineup total": s_sum, "% of team": pct})

    r_line = _lineup_team_rate(st_df, rate_col)
    r_team = _lineup_team_rate(tm_df, rate_col)
    rate_label = "AVG" if rate_col == "BA" else "OBP"
    pct_rate = (r_line / r_team * 100.0) if pd.notna(r_line) and pd.notna(r_team) and r_team > 0 else np.nan
    rows.append(
        {
            "Category": rate_label,
            "Lineup total": r_line,
            "% of team": pct_rate,
        }
    )

    hit_tbl = pd.DataFrame(rows)
    hit_tbl["Rel. strength (0–100)"] = np.nan

    strengths = {}
    for _, r in hit_tbl.iterrows():
        cat = r["Category"]
        if cat in ("AVG", "OBP"):
            v = float(r["Lineup total"]) if pd.notna(r["Lineup total"]) else np.nan
            t_rt = _lineup_team_rate(tm_df, "OBP" if cat == "OBP" else "BA")
            if pd.notna(v) and pd.notna(t_rt) and t_rt > 0:
                strengths[cat] = float(np.clip(v / t_rt, 0.0, 1.5))
            else:
                strengths[cat] = 0.5
        else:
            s_sum = float(r["Lineup total"])
            t_sum = float(pd.to_numeric(tm_df[cat], errors="coerce").fillna(0).sum()) if cat in tm_df.columns else 0.0
            strengths[cat] = (s_sum / t_sum) if t_sum > 0 else 0.0

    vals = list(strengths.values())
    mn, mx = (min(vals), max(vals)) if vals else (0.0, 1.0)
    rel_list = []
    for _, r in hit_tbl.iterrows():
        cat = r["Category"]
        raw = strengths.get(cat, 0.5)
        rel = 50.0 if mx <= mn else (raw - mn) / (mx - mn) * 100.0
        rel_list.append(rel)
    rel_std = float(np.std(rel_list)) if rel_list else 0.0
    if mx <= mn or rel_std < 5.0:
        hit_tbl["Rel. strength (0–100)"] = np.nan
    else:
        hit_tbl["Rel. strength (0–100)"] = np.round(rel_list, 1)

    ranked = hit_tbl.sort_values("Rel. strength (0–100)", ascending=False).reset_index(drop=True)
    out["strongest"] = ranked.head(2)["Category"].tolist()
    out["weakest"] = ranked.tail(2)["Category"].tolist()
    out["hitting_table"] = hit_tbl

    strongest_cat = ranked.iloc[0]["Category"] if len(ranked) else None
    weakest_cat = ranked.iloc[-1]["Category"] if len(ranked) else None

    if strongest_cat:
        if strongest_cat in ("AVG", "OBP"):
            out["strongest_detail"] = _weak_category_explanation(st_df, strongest_cat, rate_col=rate_col)
        else:
            top = _top_category_contributors(st_df, strongest_cat if strongest_cat != "AVG" else "HR", 4)
            if strongest_cat == "HR" and top:
                out["strongest_detail"] = f"Strong **{strongest_cat}** — driven by {', '.join(top)}."
            elif top:
                out["strongest_detail"] = f"Strong **{strongest_cat}** — top contributors: {', '.join(top)}."
    if weakest_cat:
        rate_src_early = "OBP" if rate_col == "OBP" else "BA"
        out["weakest_detail"] = _weak_category_explanation(
            tm_df if weakest_cat == "SB" else st_df,
            weakest_cat,
            rate_col=rate_col,
        )
        if not out["weakest_detail"] and weakest_cat in st_df.columns:
            sort_col = weakest_cat if weakest_cat not in ("AVG", "OBP") else rate_src_early
            if sort_col in st_df.columns:
                low = _top_category_contributors(
                    st_df.sort_values(sort_col, ascending=True),
                    sort_col,
                    2,
                )
                if low:
                    out["weakest_detail"] = f"Weak **{weakest_cat}** — thin production beyond {', '.join(low)}."

    z_parts = []
    if "HR" in strengths and "SB" in strengths:
        hr_s, sb_s = strengths["HR"], strengths["SB"]
        if hr_s > 0.65 and sb_s < 0.35:
            z_parts.append("power-heavy")
        elif sb_s > 0.65 and hr_s < 0.35:
            z_parts.append("speed-focused")
        elif hr_s > 0.55 and sb_s > 0.55:
            z_parts.append("balanced power/speed")
    rk_key = "OBP" if rate_label == "OBP" else "AVG"
    if rk_key in strengths:
        rk = strengths[rk_key]
        if rk < 0.38:
            z_parts.append("soft rate stats")
        elif rk > 0.68:
            z_parts.append("strong rate stats")
    try:
        from fantasy_actionable_recommendations import plain_lineup_archetype

        out["archetype"] = plain_lineup_archetype(strengths, rate_label=rate_label)
    except ImportError:
        out["archetype"] = (
            "This lineup: **" + "**, **".join(z_parts) + "** (shown starters vs full-team stat mix)."
            if z_parts
            else "No extreme skew across HR/R/RBI/SB/" + rate_label + " among these starters — profile is fairly mixed."
        )

    cv = float(hit_tbl["Rel. strength (0–100)"].std()) if len(hit_tbl) > 1 else 0.0
    try:
        from fantasy_actionable_recommendations import plain_balance_label

        out["balance_label"] = plain_balance_label(cv)
    except ImportError:
        if cv >= 28:
            out["balance_label"] = "**Unbalanced:** category spread is wide — big gaps between best and worst areas."
        elif cv <= 12:
            out["balance_label"] = "**Balanced:** strengths are spread across categories."
        else:
            out["balance_label"] = "**Moderately tilted:** clear strengths with identifiable soft categories."

    if "Fantasy slot" in st_df.columns or "Primary Position" in st_df.columns:
        grp_col = "Fantasy slot" if "Fantasy slot" in st_df.columns else "Primary Position"
        agg = {}
        for pos, g in st_df.groupby(grp_col, dropna=False):
            tot = 0.0
            for c in ["HR", "RBI", "R"]:
                if c in g.columns:
                    tot += pd.to_numeric(g[c], errors="coerce").fillna(0).sum()
            agg[str(pos)] = tot
        if agg:
            worst_pos = min(agg, key=agg.get)
            best_pos = max(agg, key=agg.get)
            slot_benchmark = None
            league_df = league_roster_df
            if league_df is not None and not getattr(league_df, "empty", True):
                league_grp = "Fantasy slot" if "Fantasy slot" in league_df.columns else (
                    "Primary Position" if "Primary Position" in league_df.columns else None
                )
                if league_grp and "Team" in league_df.columns:
                    slot_team_totals: list[float] = []
                    for _, tdf in league_df.groupby(league_df["Team"].astype(str), sort=False):
                        g = tdf[tdf[league_grp].astype(str) == str(worst_pos)]
                        if g.empty:
                            continue
                        tot = 0.0
                        for c in ["HR", "RBI", "R"]:
                            if c in g.columns:
                                tot += pd.to_numeric(g[c], errors="coerce").fillna(0).sum()
                        slot_team_totals.append(tot)
                    if slot_team_totals:
                        slot_benchmark = float(sum(slot_team_totals) / len(slot_team_totals))
            if agg.get(best_pos, 0) > 0 and agg[worst_pos] < 0.55 * agg[best_pos]:
                out["weakest_pos"] = worst_pos
                out["weakest_pos_val"] = agg[worst_pos]
                out["weakest_pos_benchmark"] = slot_benchmark
                try:
                    from fantasy_actionable_recommendations import build_actionable_position_weakness_note

                    worst_starters = st_df[st_df[grp_col].astype(str) == str(worst_pos)]
                    out["position_note"] = build_actionable_position_weakness_note(
                        worst_pos=worst_pos,
                        worst_val=agg[worst_pos],
                        starter_df=worst_starters,
                        waiver_pool=out.get("_waiver_pool_preview"),
                        needs=out.get("_needs_preview"),
                        benchmark=slot_benchmark,
                    )
                except ImportError:
                    try:
                        from fantasy_actionable_recommendations import plain_position_weakness_note

                        label = "Fantasy slot" if grp_col == "Fantasy slot" else "position"
                        out["position_note"] = plain_position_weakness_note(
                            worst_pos, agg[worst_pos], best_pos, agg[best_pos], grp_label=label,
                            benchmark=slot_benchmark,
                        )
                    except ImportError:
                        label = "Fantasy slot" if grp_col == "Fantasy slot" else "Primary Position"
                        out["position_note"] = (
                            f"**Position weakness ({label}):** **{worst_pos}** totals **{agg[worst_pos]:.0f}** HR+R+RBI among these starters "
                            f"vs **{best_pos}** (**{agg[best_pos]:.0f}**). Consider upgrading that slot via add/drop or trade."
                        )
            else:
                out["position_note"] = "**Position shape:** HR+R+RBI is fairly even across starter slots in this set."

    rate_src = "OBP" if rate_col == "OBP" else "BA"
    if rate_src in st_df.columns or (rate_src == "BA" and "H" in st_df.columns and "AB" in st_df.columns):
        sort_col = rate_src if rate_src in st_df.columns else "BA"
        if sort_col in st_df.columns:
            low_rate_df = st_df.sort_values(sort_col, ascending=True, na_position="last").head(2)
            low_rate_df = low_rate_df[pd.to_numeric(low_rate_df[sort_col], errors="coerce").notna()]
        else:
            low_rate_df = pd.DataFrame()
        if len(low_rate_df) >= 1 and "Player" in low_rate_df.columns:
            names = ", ".join(low_rate_df["Player"].astype(str).tolist()[:2])
            team_rate = _lineup_team_rate(tm_df, rate_col)
            line_rate = _lineup_team_rate(st_df, rate_col)
            if names and pd.notna(team_rate) and pd.notna(line_rate) and line_rate < team_rate - 1e-6:
                out["dragger_note"] = (
                    f"**{rate_label} drag:** shown starters **{line_rate:.3f}** vs full team **{team_rate:.3f}** — "
                    f"lowest **{rate_label}** marks: **{names}**."
                )

    if strongest_cat and weakest_cat and strongest_cat != weakest_cat:
        top_pct = hit_tbl.loc[hit_tbl["Category"] == strongest_cat, "% of team"]
        top_pct = float(top_pct.iloc[0]) if len(top_pct) else np.nan
        if pd.notna(top_pct) and top_pct >= 82 and strongest_cat not in ("AVG", "OBP"):
            out["surplus_note"] = (
                f"**Trade From:** starters carry **~{top_pct:.0f}%** of team **{strongest_cat}** while **{weakest_cat}** is weakest — "
                f"swap some **{strongest_cat}** for **{weakest_cat}**-shaped help."
            )

    recs = []
    sb_tot = float(hit_tbl.loc[hit_tbl["Category"] == "SB", "Lineup total"].iloc[0]) if "SB" in hit_tbl["Category"].values else 0.0
    hr_tot = float(hit_tbl.loc[hit_tbl["Category"] == "HR", "Lineup total"].iloc[0]) if "HR" in hit_tbl["Category"].values else 0.0
    r_tot = float(hit_tbl.loc[hit_tbl["Category"] == "R", "Lineup total"].iloc[0]) if "R" in hit_tbl["Category"].values else 0.0

    if weakest_cat == "SB" or (weakest_cat and "SB" in out["weakest"] and sb_tot < 15):
        recs.append({
            "Type": "Draft target",
            "Label": "Need",
            "Detail": f"You only have **{sb_tot:.0f}** SB from this starting group. Look for middle infielders or outfielders with steady steals and a playable {rate_label}.",
        })
    if weakest_cat in ("AVG", "OBP") or (weakest_cat and weakest_cat in out["weakest"] and weakest_cat in ("AVG", "OBP")):
        tr = _lineup_team_rate(st_df, rate_col)
        recs.append({
            "Type": "Category repair",
            "Label": "Need",
            "Detail": f"Your starters’ {weakest_cat} is **{tr:.3f}**. Add contact hitters or bench the lowest-{rate_label} names in this lineup.",
        })
    if weakest_cat == "R" or (weakest_cat and "R" in out["weakest"] and r_tot < 40):
        recs.append({
            "Type": "Draft target",
            "Label": "Target profile",
            "Detail": f"Starters total only **{r_tot:.0f}** runs. Target table-setters and on-base bats who score, not only home-run hitters.",
        })
    if out.get("surplus_note"):
        recs.append({
            "Type": "Trade recommendation",
            "Label": "Trade From → Target profile",
            "Detail": f"Ship **{strongest_cat}** surplus for **{weakest_cat}** without emptying your best starters.",
        })
    elif strongest_cat and weakest_cat and strongest_cat not in ("AVG", "OBP") and weakest_cat not in ("AVG", "OBP"):
        recs.append({
            "Type": "Trade recommendation",
            "Label": "Strength / Need",
            "Detail": f"**Strength:** **{strongest_cat}**. **Need:** **{weakest_cat}** — explore 2-for-2 style swaps that move counting shape in that direction.",
        })
    if out.get("position_note") and "Position weakness" in out["position_note"]:
        recs.append({
            "Type": "Position upgrade",
            "Label": "Need",
            "Detail": "Upgrade the weakest starter slot (see position note) with HR+R+RBI that matches your best slot’s production tier, or trade for that shape.",
        })

    pitch = _lineup_pitching_block(tm_df)
    if pitch:
        p_rows = [{"Category": k, "Team total": v} for k, v in pitch.items()]
        out["pitching_table"] = pd.DataFrame(p_rows)
        sv = pitch.get("SV", 0) or 0
        so = pitch.get("SO", 0) or 0
        if sv < 8 and so > 150:
            recs.append({
                "Type": "Category repair",
                "Label": "Need",
                "Detail": f"Pitching snapshot: **{so:.0f}** SO but only **{sv:.0f}** SV on roster — target closers or vulture saves without dumping strikeouts.",
            })

    if lineup_format != "5x5 Roto" and len(recs) < 3:
        recs.append({
            "Type": "Note",
            "Label": "Strength",
            "Detail": "Category table still uses raw hitter stats from Standings Tracker; align adds with your points/H2H settings.",
        })

    slot_rows = _slot_gap_trade_rows(missing_slots)
    warn_rows = [{"Type": "Slot", "Label": "Alert", "Detail": w} for w in dict.fromkeys(slot_warnings)]
    recs = warn_rows + slot_rows + recs
    out["recommendations"] = recs[:5]

    if ms_counts:
        gap = out.get("slot_gaps", "")
        if gap:
            if out.get("position_note"):
                out["position_note"] = gap + " " + out["position_note"]
            else:
                out["position_note"] = gap
    return out


# Public names (the underscored originals stay for existing callers).
roster_position_slot_list = _roster_position_slot_list
