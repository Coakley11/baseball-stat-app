"""Plain-language lineup diagnosis copy and actionable recommendation helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _format_category_value(cat: str, val: float | None) -> str:
    if val is None:
        return "—"
    if cat in ("AVG", "OBP", "SLG", "OPS"):
        return f"{float(val):.3f}".lstrip("0") if float(val) < 1 else f"{float(val):.3f}"
    if cat in ("ERA", "WHIP"):
        return f"{float(val):.2f}"
    return f"{int(round(float(val))):,}"


def format_league_rank_phrase(rank: int | None, *, n_teams: int = 0) -> str:
    if not rank:
        return ""
    suffix = _ordinal(int(rank))
    if n_teams > 1:
        return f"{int(rank)}{suffix} of {n_teams} teams"
    return f"{int(rank)}{suffix}"


def format_category_rank_line(
    cat: str,
    rank: int | None,
    *,
    n_teams: int = 0,
    value: float | None = None,
) -> str:
    rank_phrase = format_league_rank_phrase(rank, n_teams=n_teams)
    val_text = _format_category_value(cat, value)
    if rank_phrase and value is not None:
        return f"🟢 **{cat}** — {val_text} ({rank_phrase})"
    if rank_phrase:
        return f"🟢 **{cat}** ({rank_phrase})"
    return f"🟢 **{cat}**"


def format_category_weakness_line(
    cat: str,
    rank: int | None,
    *,
    n_teams: int = 0,
    value: float | None = None,
) -> str:
    rank_phrase = format_league_rank_phrase(rank, n_teams=n_teams)
    val_text = _format_category_value(cat, value)
    if rank_phrase and value is not None:
        return f"🔴 **{cat}** — {val_text} ({rank_phrase})"
    if rank_phrase:
        return f"🔴 **{cat}** ({rank_phrase})"
    return f"🔴 **{cat}**"


def league_strength_categories(
    category_ranks: dict[str, int] | None,
    *,
    n_teams: int = 0,
    limit: int = 2,
) -> list[str]:
    """League rank 1 = strongest category for this team."""
    ranks = dict(category_ranks or {})
    if not ranks:
        return []
    ordered = sorted(ranks.items(), key=lambda kv: (int(kv[1]), kv[0]))
    return [cat for cat, _ in ordered[: max(1, int(limit))]]


def league_weakness_categories(
    category_ranks: dict[str, int] | None,
    *,
    n_teams: int = 0,
    limit: int = 2,
) -> list[str]:
    """Highest league rank = weakest category for this team."""
    ranks = dict(category_ranks or {})
    if not ranks:
        return []
    ordered = sorted(ranks.items(), key=lambda kv: (-int(kv[1]), kv[0]))
    return [cat for cat, _ in ordered[: max(1, int(limit))]]


def plain_lineup_archetype(
    strengths: dict[str, float],
    *,
    rate_label: str = "AVG",
    strong_cats: tuple[str, ...] | list[str] | None = None,
    weak_cats: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Translate league category ranks into user-facing lineup summary."""
    strong_set = {str(c).upper() for c in (strong_cats or [])}
    weak_set = {str(c).upper() for c in (weak_cats or [])}
    rate_key = "OBP" if rate_label == "OBP" else "AVG"
    if strong_set and not weak_set:
        return f"This roster has clear strengths in **{', '.join(sorted(strong_set))}**."
    if weak_set and not strong_set:
        return f"This roster needs help in **{', '.join(sorted(weak_set))}**."
    if strong_set and weak_set:
        return (
            f"This roster has several strengths (**{', '.join(sorted(strong_set))}**) "
            f"but still has upgrade spots in **{', '.join(sorted(weak_set))}**."
        )
    hr_s = float(strengths.get("HR") or 0.5)
    sb_s = float(strengths.get("SB") or 0.5)
    rk = float(strengths.get(rate_key) or strengths.get("AVG") or strengths.get("OBP") or 0.5)
    if hr_s > 0.65 and sb_s < 0.35:
        return "This lineup leans on **power** more than **speed**."
    if sb_s > 0.65 and hr_s < 0.35:
        return "This lineup is **speed-first** with lighter power."
    if hr_s > 0.55 and sb_s > 0.55:
        return "This lineup has a **balanced power and speed** mix."
    if rk < 0.38:
        return f"**{rate_label}** is the primary risk area in league standings."
    if rk > 0.68:
        return f"**{rate_label}** is a clear strength for this group."
    return "Category production is fairly mixed across HR, RBI, R, SB, and rate stats."


def _read_projected_stat(row: pd.Series, cat: str) -> float | None:
    for col in (f"proj_{cat}", f"Projected {cat}", cat):
        if col in row.index and pd.notna(row.get(col)):
            val = pd.to_numeric(row.get(col), errors="coerce")
            if pd.notna(val):
                return float(val)
    return None


def format_waiver_target_gain_lines(
    row: pd.Series,
    *,
    weak_cats: list[str] | None = None,
    extra_cats: tuple[str, ...] = ("HR", "RBI", "R", "SB"),
) -> list[str]:
    """Projected counting-stat lines for waiver recommendations (e.g. +12 HR)."""
    lines: list[str] = []
    show_cats: list[str] = []
    for cat in list(weak_cats or []) + list(extra_cats):
        key = str(cat).upper()
        if key not in show_cats:
            show_cats.append(key)
    for cat in show_cats[:4]:
        val = _read_projected_stat(row, cat)
        if val is None:
            continue
        if cat in ("AVG", "OBP", "SLG", "OPS", "ERA", "WHIP"):
            lines.append(f"+{_format_category_value(cat, val)} {cat}")
        else:
            lines.append(f"+{int(round(val))} {cat}")
    return lines


def _waiver_target_rows(
    waiver_pool: pd.DataFrame | None,
    needs: dict[str, Any] | None,
    *,
    limit: int = 3,
    context: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if waiver_pool is None or getattr(waiver_pool, "empty", True):
        return pd.DataFrame()
    pool = waiver_pool.copy()
    if context:
        try:
            from fantasy_waiver_wire import rostered_player_names

            rostered = rostered_player_names(context)
            name_col = "Player" if "Player" in pool.columns else "fullName"
            if rostered and name_col in pool.columns:
                pool = pool[~pool[name_col].astype(str).str.strip().isin(rostered)]
        except ImportError:
            pass
    if pool.empty:
        return pd.DataFrame()
    try:
        from fantasy_waiver_wire import recommend_adds_current

        adds = recommend_adds_current(pool, needs or {}, limit=int(limit))
        return adds.copy() if adds is not None and not adds.empty else pd.DataFrame()
    except ImportError:
        return pd.DataFrame()


def _waiver_target_names(
    waiver_pool: pd.DataFrame | None,
    needs: dict[str, Any] | None,
    *,
    limit: int = 3,
    context: dict[str, Any] | None = None,
) -> list[str]:
    if waiver_pool is None or getattr(waiver_pool, "empty", True):
        return []
    adds = _waiver_target_rows(waiver_pool, needs, limit=int(limit), context=context)
    if adds.empty:
        return []
    for col in ("Player", "fullName"):
        if col in adds.columns:
            return [str(x).strip() for x in adds[col].astype(str).head(int(limit)).tolist() if str(x).strip()]
    return []


def _trade_target_names(
    league_rosters: pd.DataFrame | None,
    *,
    my_team: str = "",
    weak_cats: list[str] | None = None,
    limit: int = 3,
) -> list[str]:
    if league_rosters is None or getattr(league_rosters, "empty", True):
        return []
    df = league_rosters.copy()
    if "Team" not in df.columns:
        return []
    others = df[df["Team"].astype(str) != str(my_team or "")]
    if others.empty:
        return []
    weak = [str(c).upper() for c in (weak_cats or []) if str(c).strip()]
    sort_cols: list[str] = []
    for cat in weak + ["HR", "RBI", "R"]:
        if cat in others.columns and cat not in sort_cols:
            sort_cols.append(cat)
    if not sort_cols:
        return []
    primary = sort_cols[0]
    ranked = others.copy()
    ranked["_sort_val"] = pd.to_numeric(ranked[primary], errors="coerce").fillna(0)
    ranked = ranked.sort_values("_sort_val", ascending=False)
    names: list[str] = []
    name_col = "Player" if "Player" in ranked.columns else "fullName"
    if name_col not in ranked.columns:
        return []
    for name in ranked[name_col].astype(str).tolist():
        clean = str(name).strip()
        if clean and clean not in names:
            names.append(clean)
        if len(names) >= int(limit):
            break
    return names


def _trade_target_hint(weak_cats: list[str]) -> str:
    weak = weak_cats[0] if weak_cats else "balance"
    hints = {
        "HR": "25+ HR pace · middle-order hitter · RBI producer",
        "RBI": "100+ RBI pace · run producer · lineup anchor",
        "R": "leadoff/top-of-order · 80+ R pace",
        "SB": "20+ SB pace · everyday role",
        "AVG": "high-contact bat · .280+ AVG pace",
        "OBP": "OBP-first bat · table-setter profile",
    }
    return hints.get(str(weak).upper(), f"upgrade **{weak}** without giving up your best categories")


def build_team_actionable_summary(
    *,
    strong_cats: list[str] | None = None,
    weak_cats: list[str] | None = None,
    strongest_detail: str = "",
    weakest_detail: str = "",
    position_note: str = "",
    needs: dict[str, Any] | None = None,
    waiver_pool: pd.DataFrame | None = None,
    league_rosters: pd.DataFrame | None = None,
    my_team: str = "",
    league_context: dict[str, Any] | None = None,
) -> list[str]:
    """Short actionable blocks for lineup / team analysis pages (league ranks only)."""
    lines: list[str] = []
    strong_cats = list(strong_cats or [])
    weak_cats = list(weak_cats or [])
    cat_values = dict((needs or {}).get("category_values") or {})
    if strong_cats:
        top = strong_cats[0]
        val = cat_values.get(top)
        val_bit = f" ({_format_category_value(top, val)})" if val is not None else ""
        lines.append(f"**Biggest strength:** **{top}**{val_bit} leads your league profile.")
    if weak_cats:
        weak = weak_cats[0]
        val = cat_values.get(weak)
        val_bit = f" ({_format_category_value(weak, val)})" if val is not None else ""
        lines.append(f"**Biggest weakness:** **{weak}**{val_bit} is your clearest upgrade area.")
        add_rows = _waiver_target_rows(waiver_pool, needs, limit=3, context=league_context)
        if not add_rows.empty:
            lines.append("**Best waiver strategy:** Recommended targets:")
            name_col = "Player" if "Player" in add_rows.columns else "fullName"
            for _, row in add_rows.iterrows():
                pname = str(row.get(name_col) or row.get("Player") or "").strip()
                if not pname:
                    continue
                gain_lines = format_waiver_target_gain_lines(row, weak_cats=weak_cats)
                block = f"**{pname}**"
                if gain_lines:
                    block += "\n" + "\n".join(gain_lines)
                lines.append(block)
        elif _waiver_target_names(waiver_pool, needs, limit=1, context=league_context):
            targets = _waiver_target_names(waiver_pool, needs, limit=3, context=league_context)
            why = ", ".join(weak_cats[:2])
            lines.append(
                "**Best waiver strategy:** Recommended targets: "
                + ", ".join(f"**{name}**" for name in targets)
                + f" — {why} upside · everyday role."
            )
        else:
            lines.append(
                "**Best waiver strategy:** No strong waiver upgrades are currently available in this league."
            )
        trade_from = strong_cats[0] if strong_cats else "surplus counting stats"
        trade_targets = _trade_target_names(
            league_rosters,
            my_team=str(my_team or ""),
            weak_cats=weak_cats,
            limit=3,
        )
        trade_line = (
            f"**Best trade strategy:** Trade excess **{trade_from}** production for **{weak}**. "
            f"Trade profile: {_trade_target_hint(weak_cats)}."
        )
        if trade_targets:
            trade_line += " Potential targets: " + ", ".join(f"**{name}**" for name in trade_targets) + "."
        lines.append(trade_line)
    elif position_note:
        lines.append(f"**Next move:** {position_note}")
    return lines


def plain_balance_label(cv: float) -> str:
    if cv >= 28:
        return "This roster relies on a few categories for most of its value; other areas lag behind."
    if cv <= 12:
        return "Category production is spread fairly evenly across the lineup."
    return "This roster has several strengths but still has a few areas that could be upgraded."


def team_outlook_explanation(
    *,
    strong_cats: list[str] | None = None,
    weak_cats: list[str] | None = None,
    category_ranks: dict[str, int] | None = None,
    category_values: dict[str, float] | None = None,
    n_teams: int = 0,
    missing_slots: list[str] | None = None,
) -> list[str]:
    """Plain bullets explaining why outlook is Strong / Mixed / etc."""
    lines: list[str] = []
    ranks = dict(category_ranks or {})
    values = dict(category_values or {})
    n = int(n_teams or 0) or (max(ranks.values()) if ranks else 0)
    strengths = list(strong_cats or [])
    weaknesses = list(weak_cats or [])
    if not strengths and ranks and n > 1:
        ordered = sorted(ranks.items(), key=lambda kv: (int(kv[1]), kv[0]))
        strengths = [cat for cat, r in ordered[:2] if int(r) <= max(1, n // 2)]
    if not weaknesses and ranks and n > 1:
        ordered = sorted(ranks.items(), key=lambda kv: (-int(kv[1]), kv[0]))
        weaknesses = [cat for cat, r in ordered[:2] if int(r) > max(2, n // 2)]
    if strengths:
        strength_bits: list[str] = []
        for cat in strengths[:3]:
            val = values.get(cat)
            rank_phrase = format_league_rank_phrase(ranks.get(cat), n_teams=n)
            if val is not None:
                strength_bits.append(f"• Strong **{cat}** ({_format_category_value(cat, val)}{f', {rank_phrase}' if rank_phrase else ''})")
            elif rank_phrase:
                strength_bits.append(f"• Strong **{cat}** ({rank_phrase})")
            else:
                strength_bits.append(f"• Strong **{cat}**")
        lines.append("**Strengths driving outlook:**\n" + "\n".join(strength_bits))
    if weaknesses:
        concern_bits: list[str] = []
        for cat in weaknesses[:3]:
            rank = ranks.get(cat)
            rank_phrase = format_league_rank_phrase(rank, n_teams=n) if rank and n > 1 else ""
            val = values.get(cat)
            if rank_phrase and val is not None:
                concern_bits.append(f"• **{cat}** ({_format_category_value(cat, val)}, {rank_phrase})")
            elif rank_phrase:
                concern_bits.append(f"• **{cat}** ({rank_phrase})")
            else:
                concern_bits.append(f"• **{cat}**")
        lines.append("**Concerns:**\n" + "\n".join(concern_bits))
    open_slots = list(missing_slots or [])
    if open_slots:
        from collections import Counter

        ms_counts = Counter(open_slots)
        slot_parts: list[str] = []
        for slot in ("C", "1B", "2B", "3B", "SS", "OF", "UTIL"):
            if slot in ms_counts:
                cnt = ms_counts[slot]
                slot_parts.append(slot + (f" (×{cnt})" if cnt > 1 else ""))
        if slot_parts:
            slot_line = f"• Several roster slots still open ({', '.join(slot_parts)})"
            if lines and lines[-1].startswith("**Concerns:**"):
                lines[-1] = lines[-1] + "\n" + slot_line
            else:
                lines.append(f"**Concerns:**\n{slot_line}")
    return lines


def team_outlook_confidence_reasons(
    *,
    confidence: str = "",
    category_ranks: dict[str, int] | None = None,
    n_teams: int = 0,
    missing_slots: list[str] | None = None,
    roster_complete: bool = True,
) -> list[str]:
    """Short bullets explaining why confidence is High / Medium / Low."""
    reasons: list[str] = []
    ranks = dict(category_ranks or {})
    n = int(n_teams or 0) or (max(ranks.values()) if ranks else 0)
    if missing_slots or not roster_complete:
        reasons.append("Partial roster — lineup slots are not fully filled")
    if missing_slots:
        reasons.append("Open slots remain — category totals may shift as you add players")
    if ranks and n > 1:
        spread = max(int(v) for v in ranks.values()) - min(int(v) for v in ranks.values())
        if spread <= 1:
            reasons.append("Rankings are consistent across categories")
        elif spread == 2:
            reasons.append("Rankings are mostly consistent with a few outliers")
        else:
            reasons.append("Category rankings vary widely — harder to predict overall outlook")
    if not reasons:
        label = str(confidence or "Medium").strip().lower()
        if label == "high":
            reasons.append("Category balance and league ranks are tightly clustered")
        elif label == "low":
            reasons.append("Limited league context or incomplete roster data")
        else:
            reasons.append("Mixed signals across categories and roster coverage")
    return reasons


def team_outlook_confidence_help() -> str:
    return (
        "Confidence reflects category balance, positional coverage, and how consistent your league "
        "rankings are across categories (tighter spread = higher confidence)."
    )


def team_outlook_summary(
    *,
    strong_cats: list[str],
    weak_cats: list[str],
    category_ranks: dict[str, int] | None = None,
    n_teams: int = 0,
) -> tuple[str, str, str]:
    """Return (outlook label, confidence label, star display)."""
    ranks = dict(category_ranks or {})
    n = int(n_teams or 0) or (max(ranks.values()) if ranks else 0)
    if not ranks or n <= 1:
        return "Mixed", "Low", "⭐⭐☆☆☆"
    best = min(int(ranks.get(c, n)) for c in ranks)
    worst = max(int(ranks.get(c, 1)) for c in ranks)
    spread = worst - best
    if best == 1 and worst <= max(2, n // 2):
        outlook = "Strong"
    elif worst >= n and best >= n - 1:
        outlook = "Needs work"
    elif spread <= 1:
        outlook = "Balanced"
    else:
        outlook = "Mixed"
    if n <= 2:
        confidence = "Low"
    elif spread <= 1:
        confidence = "High"
    elif spread == 2:
        confidence = "Medium"
    else:
        confidence = "Medium"
    stars = {"Strong": "⭐⭐⭐⭐☆", "Balanced": "⭐⭐⭐☆☆", "Mixed": "⭐⭐⭐☆☆", "Needs work": "⭐⭐☆☆☆"}
    return outlook, confidence, stars.get(outlook, "⭐⭐⭐☆☆")


def plain_position_weakness_note(
    worst_pos: str,
    worst_val: float,
    best_pos: str,
    best_val: float,
    *,
    grp_label: str = "position",
    benchmark: float | None = None,
) -> str:
    bench_line = f"\n\nLeague benchmark: **{benchmark:.0f}**" if benchmark is not None else ""
    return (
        f"**Weakest Position**\n\n"
        f"**{worst_pos}**\n\n"
        f"Current contribution: **{worst_val:.0f}** HR+R+RBI{bench_line}\n\n"
        f"Recommendation: Upgrade **{worst_pos}** through the waiver wire or a trade."
    )


def enrich_recommendations_with_waiver_targets(
    recs: list[dict[str, Any]],
    waiver_pool: pd.DataFrame | None,
    *,
    needs: dict[str, Any] | None = None,
    league_context: dict[str, Any] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Attach specific waiver player names to category-repair recommendations."""
    if not recs or waiver_pool is None or getattr(waiver_pool, "empty", True):
        return recs
    names = _waiver_target_names(waiver_pool, needs, limit=limit, context=league_context)
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
