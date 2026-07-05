"""Plain-language lineup diagnosis copy and actionable recommendation helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        return f"{n}th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def format_category_rank_line(cat: str, rank: int | None, *, n_teams: int = 0) -> str:
    if not rank:
        return f"🟢 {cat}"
    suffix = _ordinal(int(rank))
    if n_teams > 1:
        return f"🟢 {cat} (#{rank}{suffix} of {n_teams})"
    return f"🟢 {cat} (#{rank}{suffix})"


def format_category_weakness_line(cat: str, rank: int | None, *, n_teams: int = 0) -> str:
    if not rank:
        return f"🔴 {cat}"
    suffix = _ordinal(int(rank))
    if n_teams > 1:
        return f"🔴 {cat} (#{rank}{suffix} of {n_teams})"
    return f"🔴 {cat} (#{rank}{suffix})"


def plain_lineup_archetype(
    strengths: dict[str, float],
    *,
    rate_label: str = "AVG",
) -> str:
    """Translate internal strength ratios into user-facing lineup summary."""
    parts: list[str] = []
    hr_s = float(strengths.get("HR") or 0.5)
    sb_s = float(strengths.get("SB") or 0.5)
    rk = float(strengths.get("AVG" if rate_label == "AVG" else "OBP") or 0.5)
    if hr_s > 0.65 and sb_s < 0.35:
        parts.append("This lineup leans on **power** more than **speed**.")
    elif sb_s > 0.65 and hr_s < 0.35:
        parts.append("This lineup is **speed-first** with lighter power.")
    elif hr_s > 0.55 and sb_s > 0.55:
        parts.append("This lineup has a **balanced power and speed** mix.")
    if rk < 0.38:
        parts.append(f"**{rate_label}** is a soft spot relative to counting stats.")
    elif rk > 0.68:
        parts.append(f"**{rate_label}** is a clear strength for this group.")
    if not parts:
        return "Category production is fairly mixed across HR, RBI, R, SB, and rate stats."
    return " ".join(parts)


def plain_balance_label(cv: float) -> str:
    if cv >= 28:
        return "**Unbalanced:** a few categories carry most of the value; others lag behind."
    if cv <= 12:
        return "**Balanced:** category production is spread evenly across the lineup."
    return "**Moderately tilted:** clear strengths with identifiable soft spots to upgrade."


def plain_position_weakness_note(
    worst_pos: str,
    worst_val: float,
    best_pos: str,
    best_val: float,
    *,
    grp_label: str = "position",
) -> str:
    return (
        f"**Weakest {grp_label}: {worst_pos}** — current contribution **{worst_val:.0f}** HR+R+RBI. "
        f"**Strongest: {best_pos}** at **{best_val:.0f}**. "
        f"Consider upgrading **{worst_pos}** through the waiver wire or a trade."
    )


def enrich_recommendations_with_waiver_targets(
    recs: list[dict[str, Any]],
    waiver_pool: pd.DataFrame | None,
    *,
    needs: dict[str, Any] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Attach specific waiver player names to category-repair recommendations."""
    if not recs or waiver_pool is None or getattr(waiver_pool, "empty", True):
        return recs
    try:
        from fantasy_waiver_wire import recommend_adds_current

        adds = recommend_adds_current(waiver_pool, needs or {})
        names = []
        if not adds.empty:
            for col in ("Player", "fullName"):
                if col in adds.columns:
                    names = adds[col].astype(str).head(int(limit)).tolist()
                    break
        if not names:
            return recs
        names_text = ", ".join(names)
        out: list[dict[str, Any]] = []
        for row in recs:
            item = dict(row)
            detail = str(item.get("Detail") or "")
            label = str(item.get("Label") or "")
            if label in {"Need", "Target profile", "Category repair"} and "Recommended targets" not in detail:
                item["Detail"] = f"{detail} Recommended targets: **{names_text}**."
            out.append(item)
        return out
    except ImportError:
        return recs
