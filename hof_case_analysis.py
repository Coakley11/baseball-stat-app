"""Compose a statistical Hall of Fame case memo from a hof_case_packet."""

from __future__ import annotations

from typing import Any

from hall_of_fame_data import CASE_SCORE_BUCKETS, CASE_SCORE_LABEL

_FILTER_CONTEXTUAL = frozenset({"batting_hand", "bats", "team_filter", "by_team", "year_range"})
_FILTER_STRUCTURAL = frozenset({"position", "position_mode", "hof_membership_filter", "stat_minimums"})
_MEANINGFUL_THRESHOLDS = {
    ("HR", 500): "500+ home runs is a historically Hall-heavy bar.",
    ("HR", 400): "400+ home runs signals elite power and a meaningful Hall marker.",
    ("H", 3000): "3,000 hits is one of the strongest traditional Hall markers.",
    ("H", 2500): "2,500+ hits is a highly selective longevity cohort.",
    ("RBI", 1500): "1,500+ RBI filters to established run producers.",
}
_STAT_LABELS = {
    "HR": "home runs",
    "H": "hits",
    "RBI": "RBI",
    "R": "runs",
    "SB": "stolen bases",
    "BB": "walks",
    "2B": "doubles",
    "3B": "triples",
    "BA": "batting average",
    "OBP": "on-base percentage",
    "SLG": "slugging",
    "OPS": "OPS",
    "G": "games",
    "AB": "at-bats",
}

# Rate-stat floors below which a minimum filter is non-selective (e.g. OPS >= 0.0).
_TRIVIAL_RATE_CEILINGS: dict[str, float] = {
    "BA": 0.250,
    "OBP": 0.300,
    "SLG": 0.350,
    "OPS": 0.700,
}
# Counting-stat floors — below this, the filter adds no meaningful cohort shape.
_TRIVIAL_COUNT_CEILINGS: dict[str, int] = {
    "G": 500,
    "AB": 2000,
    "R": 800,
    "H": 2000,
    "2B": 300,
    "3B": 50,
    "HR": 200,
    "RBI": 1000,
    "SB": 200,
    "BB": 500,
}

_POSITION_HOF_CONTEXT: dict[str, str] = {
    "1B": (
        "First base is offense-first — inducted 1Bs typically combine sustained power and/or elite "
        "on-base value over a long peak."
    ),
    "DH": (
        "Designated hitters are judged almost entirely on bat — the bar is elite offensive production, "
        "not defensive value."
    ),
    "OF": "Outfield Hall cases usually require a clear power/speed or all-around offensive peak.",
    "C": "Catchers are often evaluated with a lower offensive bar, but sustained excellence and longevity still matter.",
    "SS": "Shortstop cases can lean on defense and longevity; offensive standouts are compared within a lower baseline.",
    "2B": "Second base profiles vary — sustained offensive value above the positional norm strengthens the case.",
    "3B": "Third base inductees often show multi-category offensive value (power plus on-base skills).",
}

_COMPARABLE_PROFILE_GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("HR", "SLG"), "similar power production"),
    (("OBP", "BB"), "similar on-base and walk profile"),
    (("H", "2B"), "similar hit volume"),
    (("OPS",), "similar overall offensive value"),
    (("RBI",), "similar run production"),
    (("SB",), "similar speed value"),
)


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce packet numeric fields without crashing on NaN, floats, or bad strings."""
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        if isinstance(value, float) and value != value:  # NaN
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        f = float(value)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def _is_trivial_stat_minimum(stat: str, val: Any) -> bool:
    """True when a stat minimum is effectively a default and should not appear in the memo."""
    stat_key = str(stat or "").strip().upper()
    if stat_key in _TRIVIAL_RATE_CEILINGS:
        return _safe_float(val, default=-1.0) <= _TRIVIAL_RATE_CEILINGS[stat_key]
    ceiling = _TRIVIAL_COUNT_CEILINGS.get(stat_key, 1)
    return _safe_int(val) < ceiling


def _target_stats(packet: dict[str, Any]) -> dict[str, Any]:
    for key in ("target_career_stats", "target_player_row", "career_stats_full"):
        block = packet.get(key)
        if isinstance(block, dict) and block:
            return block
    return {}


def _format_stat_value(stat: str, val: Any) -> str:
    if stat in ("BA", "OBP", "SLG", "OPS"):
        v = _safe_float(val)
        return f"{v:.3f}"
    return str(_safe_int(val))


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        text = str(line or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _normalize_position(pos: str) -> str:
    p = str(pos or "").strip()
    if not p or p.lower() == "unknown":
        return "Unknown"
    return p.upper()


def _fmt_rank(rank_info: dict[str, Any]) -> str:
    rank = rank_info.get("rank")
    total = rank_info.get("of")
    stat = str(rank_info.get("stat") or "")
    label = _STAT_LABELS.get(stat, stat)
    val = rank_info.get("value")
    tier = str(rank_info.get("tier") or "").strip()
    val_s = ""
    if val is not None:
        if stat in ("BA", "OBP", "SLG", "OPS"):
            val_s = f" ({_format_stat_value(stat, val)})"
        elif stat:
            val_s = f" ({_format_stat_value(stat, val)})"
    if rank and total:
        base = f"#{rank} of {total} in cohort by {label}{val_s}"
        return f"{base} ({tier})" if tier else base
    return ""


def _fmt_player_strength(stat: str, rank_info: dict[str, Any], target_stats: dict[str, Any]) -> str:
    """Player-centric cohort standing — not filter boilerplate."""
    label = _STAT_LABELS.get(stat, stat)
    rank = rank_info.get("rank")
    total = rank_info.get("of")
    tier = str(rank_info.get("tier") or "").strip()
    val = rank_info.get("value") if rank_info.get("value") is not None else target_stats.get(stat)
    val_s = f" ({_format_stat_value(stat, val)})" if val is not None else ""
    pct = _safe_float(rank_info.get("percentile_top"))
    if pct >= 90 or "top" in tier.lower():
        lead = f"Elite {label}{val_s}"
    elif pct >= 75:
        lead = f"Strong {label}{val_s}"
    else:
        lead = f"Notable {label}{val_s}"
    if rank and total:
        lead += f" — #{rank} of {total} in this cohort"
    if tier:
        lead += f" ({tier})"
    return lead + "."


def _player_names(rows: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    names: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("fullName") or row.get("player") or "").strip()
        if name:
            names.append(name.replace("⭐ ", "").replace("🔴 ", "").strip())
    return names


def _stat_min_meaning(stat: str, val: Any) -> str:
    """Return 'strong', 'moderate', 'context', or 'skip' for a stat minimum."""
    if _is_trivial_stat_minimum(stat, val):
        return "skip"
    n = _safe_int(val, default=-1)
    if n < 0:
        return "skip"
    stat = str(stat or "").strip().upper()
    if stat == "HR" and n >= 400:
        return "strong"
    if stat == "H" and n >= 3000:
        return "strong"
    if stat == "RBI" and n >= 1500:
        return "strong"
    if stat == "BB" and n >= 1000:
        return "strong"
    if stat == "HR" and n >= 300:
        return "moderate"
    if stat == "H" and n >= 2500:
        return "moderate"
    if stat == "RBI" and n >= 1200:
        return "moderate"
    if stat in _TRIVIAL_RATE_CEILINGS:
        return "skip"
    return "context"


def _interpret_filters(filters: dict[str, Any]) -> dict[str, Any]:
    filters = dict(filters or {})
    meaningful_thresholds: list[str] = []
    cohort_context: list[str] = []
    stat_mins = filters.get("stat_minimums") if isinstance(filters.get("stat_minimums"), dict) else {}
    for stat, val in stat_mins.items():
        if val is None:
            continue
        label = _STAT_LABELS.get(str(stat), str(stat))
        level = _stat_min_meaning(str(stat), val)
        if level == "skip":
            continue
        if level == "strong":
            meaningful_thresholds.append(
                f"{label} ≥ {val} is a meaningful Hall marker — it selects an elite peer group."
            )
        elif level == "moderate":
            meaningful_thresholds.append(
                f"{label} ≥ {val} defines a selective comparison group with Hall relevance."
            )
        # Non-trivial but low-selectivity mins are omitted — they add noise, not insight.
    pos = filters.get("position")
    if pos:
        if isinstance(pos, list):
            pos_text = ", ".join(str(p) for p in pos if str(p).strip())
        else:
            pos_text = str(pos)
        if pos_text.strip():
            meaningful_thresholds.append(
                f"Position filter ({pos_text}) — comparison is position-relative."
            )
    hand = filters.get("batting_hand")
    if hand:
        hand_text = ", ".join(hand) if isinstance(hand, list) else str(hand)
        if hand_text.strip():
            cohort_context.append(f"Batting-hand filter ({hand_text}) defines the cohort only.")
    team = filters.get("team_filter")
    if team:
        cohort_context.append("Team/franchise filter limits organizational context only.")
    yr = filters.get("year_range")
    if isinstance(yr, (list, tuple)) and len(yr) >= 2:
        try:
            span = _safe_int(yr[1]) - _safe_int(yr[0])
            if span < 40:
                cohort_context.append(
                    f"Year range {yr[0]}–{yr[1]} limits which seasons count — era context, not merit by itself."
                )
        except (TypeError, ValueError):
            pass
    sort_stat = str(filters.get("sort_stat") or "").strip()
    sort_note = ""
    if sort_stat:
        alt = [s for s in ("H", "OBP", "BB", "RBI", "OPS", "SLG") if s != sort_stat]
        sort_note = (
            f"The cohort table is sorted by {sort_stat}; the player's case may rest more on "
            f"{', '.join(_STAT_LABELS.get(s, s) for s in alt[:3])}."
        )
    return {
        "meaningful_thresholds": meaningful_thresholds[:3],
        "cohort_context": cohort_context[:2],
        "sort_stat_note": sort_note,
    }


def _build_notable_profile_lines(packet: dict[str, Any]) -> list[str]:
    """What actually makes this player notable — awards, milestones, elite ranks."""
    lines: list[str] = []
    target_stats = _target_stats(packet)
    ranks = packet.get("target_cohort_ranks") if isinstance(packet.get("target_cohort_ranks"), dict) else {}
    strengths = list(packet.get("cohort_strength_stats") or [])

    awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    major = _safe_int(awards.get("major_awards") or awards.get("mvp_count"))
    if major >= 1:
        detail = str(awards.get("mvp_summary") or awards.get("award_summary") or "").strip()
        line = f"{major} major award(s) at MVP/Cy Young level"
        if detail:
            line += f" ({detail})"
        lines.append(line + " — peak-value evidence, not cohort context.")

    for ms in packet.get("career_milestones") or []:
        if isinstance(ms, dict) and ms.get("label"):
            lines.append(str(ms["label"]) + ".")

    priority_stats = ("OBP", "OPS", "BB", "HR", "SLG", "H", "RBI", "R", "SB", "BA")
    ordered = [s for s in priority_stats if s in strengths]
    ordered += [s for s in strengths if s not in ordered]
    for stat in ordered[:5]:
        info = ranks.get(stat)
        if isinstance(info, dict) and _safe_float(info.get("percentile_top")) >= 70:
            line = _fmt_player_strength(stat, info, target_stats)
            if line:
                lines.append(line)

    for note in packet.get("position_rarity_findings") or []:
        text = str(note).strip()
        if text:
            lines.append(text if text.endswith(".") else text + ".")

    return _dedupe_lines(lines)[:8]


def _build_position_analysis(packet: dict[str, Any], bucket: str) -> list[str]:
    """Position-relative Hall context — not just 'Primary position: 1B.'"""
    pos = _normalize_position(str(packet.get("primary_position") or "Unknown"))
    if pos == "Unknown":
        return []

    lines: list[str] = []
    bar = _POSITION_HOF_CONTEXT.get(pos)
    if bar:
        lines.append(bar)

    pos_pct = packet.get("position_percentiles") if isinstance(packet.get("position_percentiles"), dict) else {}
    pos_ranks = packet.get("position_stat_ranks") if isinstance(packet.get("position_stat_ranks"), dict) else {}

    elite: list[str] = []
    strong: list[str] = []
    weak: list[str] = []
    for stat, info in pos_pct.items():
        if not isinstance(info, dict):
            continue
        pct = _safe_float(info.get("percentile_top"))
        tier = str(info.get("tier") or "")
        label = _STAT_LABELS.get(str(stat), str(stat))
        rank_info = pos_ranks.get(stat) if isinstance(pos_ranks.get(stat), dict) else {}
        rank = rank_info.get("rank")
        peer_n = rank_info.get("of")
        tag = f"{label} (#{rank} of {peer_n} {pos}s)" if rank and peer_n else label
        if pct >= 90 or any(x in tier.lower() for x in ("top 1", "top 5", "top 10")):
            elite.append(tag)
        elif pct >= 75 or "quartile" in tier.lower():
            strong.append(tag)
        elif pct < 50:
            weak.append(tag)

    offense_first = pos in ("1B", "DH", "OF", "3B")
    if elite:
        lines.append(
            f"Relative to other {pos}s in this dataset, the profile ranks near the top in "
            f"{', '.join(elite[:4])} — above typical Hall-caliber offensive production at the position."
            if offense_first
            else f"Relative to other {pos}s, near the top in {', '.join(elite[:4])}."
        )
    elif strong:
        lines.append(
            f"Solid {pos} offensive standing: top-quartile among position peers in {', '.join(strong[:3])}."
        )
    elif bucket in ("Borderline", "Weak") and offense_first:
        lines.append(
            f"The offensive profile does not clearly separate from typical inducted {pos} production in this dataset."
        )

    if weak and bucket in ("Borderline", "Weak", "Solid"):
        lines.append(
            f"Below-median among {pos}s in {', '.join(weak[:3])}"
            + (" — a meaningful drag at an offense-first position." if offense_first else ".")
        )

    comparables = packet.get("comparable_players") if isinstance(packet.get("comparable_players"), dict) else {}
    hof_names = _player_names(comparables.get("hall_of_famers") or [], limit=2)
    if hof_names and elite:
        lines.append(
            f"Inducted {pos} peers in this cohort (e.g. {', '.join(hof_names)}) show a comparable or stronger "
            "offensive tier — the target must be weighed against that bar."
        )
    elif hof_names and bucket in ("Strong", "Very Strong", "Solid"):
        lines.append(
            f"Among inducted {pos}s here ({', '.join(hof_names)}), the target's best categories "
            "hold up statistically — supporting the verdict."
        )

    return _dedupe_lines(lines)[:5]


def _comparable_shared_reason(target_stats: dict[str, Any], comp: dict[str, Any]) -> str:
    reasons: list[str] = []
    for stats, phrase in _COMPARABLE_PROFILE_GROUPS:
        matched = True
        for stat in stats:
            t_val = _safe_float(target_stats.get(stat), default=-1.0)
            c_val = _safe_float(comp.get(stat), default=-1.0)
            if t_val < 0 or c_val < 0:
                matched = False
                break
            if max(t_val, c_val) <= 0:
                matched = False
                break
            if abs(t_val - c_val) / max(t_val, c_val) > 0.22:
                matched = False
                break
        if matched:
            reasons.append(phrase)
    if reasons:
        return reasons[0] if len(reasons) == 1 else f"{reasons[0]} and {reasons[1]}"
    sort_stat = str(comp.get("_sort_stat") or "")
    if sort_stat:
        label = _STAT_LABELS.get(sort_stat, sort_stat)
        return f"similar overall {label} tier in this cohort"
    return "similar overall statistical shape in this cohort"


def _build_comparable_notes(packet: dict[str, Any]) -> list[str]:
    """Explain why comparables matter — not just a name list."""
    comparables = packet.get("comparable_players") if isinstance(packet.get("comparable_players"), dict) else {}
    target_stats = _target_stats(packet)
    sort_stat = str(packet.get("sort_stat") or "HR")
    notes: list[str] = []

    hof_rows = comparables.get("hall_of_famers") or []
    if hof_rows:
        notes.append("**Closest Hall of Fame statistical peers**")
        for comp in hof_rows[:3]:
            if not isinstance(comp, dict):
                continue
            comp = {**comp, "_sort_stat": sort_stat}
            name = str(comp.get("fullName") or comp.get("player") or "").replace("⭐ ", "").strip()
            if not name:
                continue
            reason = _comparable_shared_reason(target_stats, comp)
            notes.append(f"- **{name}** — {reason}; inducted in this cohort.")

    non_rows = comparables.get("non_hall_of_famers") or []
    if non_rows:
        notes.append("**Closest non-inducted comparables**")
        for comp in non_rows[:3]:
            if not isinstance(comp, dict):
                continue
            comp = {**comp, "_sort_stat": sort_stat}
            name = str(comp.get("fullName") or comp.get("player") or "").replace("⭐ ", "").strip()
            if not name:
                continue
            reason = _comparable_shared_reason(target_stats, comp)
            notes.append(
                f"- **{name}** — {reason}; similar production without induction — a cautionary comp."
            )

    return notes


def _build_signal_vs_context(packet: dict[str, Any], filter_interp: dict[str, Any]) -> dict[str, list[str]]:
    """Separate evidence that strengthens the case from context that defines the cohort."""
    case_evidence: list[str] = []
    cohort_context: list[str] = list(filter_interp.get("cohort_context") or [])

    case_evidence.extend(_build_notable_profile_lines(packet))

    hof_n = packet.get("hall_of_famers_returned")
    total = packet.get("total_players_returned")
    rate = _safe_float(packet.get("hall_of_fame_rate_pct"))
    total_n = _safe_int(total)
    if total and hof_n is not None:
        if rate >= 50 and total_n >= 5:
            case_evidence.append(
                f"{hof_n}/{total} players in this cohort are Hall of Famers ({rate}%) — "
                "the peer group itself is Hall-heavy."
            )
        elif rate >= 30 and total_n >= 8:
            case_evidence.append(
                f"{hof_n}/{total} Hall of Famers ({rate}%) — a meaningful share of the cohort is inducted."
            )
        elif rate <= 15 and total_n >= 10:
            cohort_context.append(
                f"Only {rate}% of this cohort is inducted — the case must rest on standing out within the group."
            )

    meaningful_filters = filter_interp.get("meaningful_thresholds") or []
    if meaningful_filters and total_n <= 25:
        case_evidence.extend(meaningful_filters[:2])

    selectivity = packet.get("cohort_selectivity") if isinstance(packet.get("cohort_selectivity"), dict) else {}
    for note in (selectivity.get("threshold_notes") or []):
        text = str(note)
        lower = text.lower()
        if any(k in lower for k in ("hall-of-fame heavy", "hall marker", "selective", "high hall", "3,000", "500+")):
            if text not in case_evidence:
                case_evidence.append(text)
        elif "broad" in lower and text not in cohort_context:
            cohort_context.append(text)

    awards_cmp = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if awards_cmp.get("data_available") and target_awards.get("data_available"):
        total_aw = _safe_int(target_awards.get("total_awards"))
        major = _safe_int(target_awards.get("major_awards") or target_awards.get("mvp_count"))
        if major < 1 and total_aw >= 3:
            case_evidence.append(f"{total_aw} career awards — supporting evidence for the statistical case.")
        fewer = _safe_int(awards_cmp.get("players_with_more_total_awards"))
        if total and fewer >= total_n // 2 and major < 1:
            cohort_context.append(
                f"{fewer} cohort peers have more total awards — awards do not clearly separate the target."
            )

    sel = str(selectivity.get("selectivity") or "")
    if sel == "broad":
        cohort_context.append(
            "Broad cohort — rank within the group should be weighted cautiously."
        )

    return {
        "case_evidence": _dedupe_lines(case_evidence)[:10],
        "cohort_context_only": _dedupe_lines(cohort_context)[:4],
    }


def _era_note(identity: dict[str, Any]) -> str:
    span = identity.get("career_span") if isinstance(identity.get("career_span"), dict) else {}
    debut = span.get("debut_year")
    final = span.get("final_year")
    seasons = span.get("seasons")
    if not debut or not final:
        return ""
    note = f"Career span {debut}–{final}"
    if seasons:
        note += f" ({seasons} seasons)"
    note += ". "
    if _safe_int(debut) < 1970:
        note += "Earlier-era counting totals can look stronger in raw numbers; compare within cohort and position."
    elif _safe_int(final) >= 2010:
        note += "Modern-era offense and roster usage can depress raw counting totals relative to older peers."
    return note


def _score_case(packet: dict[str, Any]) -> tuple[int, str]:
    """Return (0–100 score, verdict bucket)."""
    score = 42
    sort_stat = str(packet.get("sort_stat") or "").strip()
    strengths = list(packet.get("cohort_strength_stats") or [])
    weaknesses = list(packet.get("cohort_weakness_stats") or [])
    ranks = packet.get("target_cohort_ranks") if isinstance(packet.get("target_cohort_ranks"), dict) else {}
    pos_ranks = packet.get("position_stat_ranks") if isinstance(packet.get("position_stat_ranks"), dict) else {}
    pos_findings = list(packet.get("position_rarity_findings") or [])
    milestones = list(packet.get("career_milestones") or [])
    selectivity = packet.get("cohort_selectivity") if isinstance(packet.get("cohort_selectivity"), dict) else {}
    hof_rate = _safe_float(packet.get("hall_of_fame_rate_pct"))
    total = _safe_int(packet.get("total_players_returned"))
    target_rank = packet.get("target_rank")

    score += min(len(strengths) * 6, 24)
    score -= min(len(weaknesses) * 4, 16)
    score += min(len(milestones) * 4, 16)
    score += min(len(pos_findings) * 5, 15)

    pos_pct = packet.get("position_percentiles") if isinstance(packet.get("position_percentiles"), dict) else {}
    top_pos_tiers = 0
    for info in pos_pct.values():
        if not isinstance(info, dict):
            continue
        pct = info.get("percentile_top")
        tier = str(info.get("tier") or "")
        if pct is not None and _safe_float(pct) >= 90:
            top_pos_tiers += 1
        elif "top" in tier.lower():
            top_pos_tiers += 1
    score += min(top_pos_tiers * 4, 12)

    awards_cmp = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    if awards_cmp.get("data_available"):
        fewer = _safe_int(awards_cmp.get("players_with_more_total_awards"))
        if total and fewer <= max(1, total // 4):
            score += 8
        elif fewer >= total // 2:
            score -= 6

    sel = str(selectivity.get("selectivity") or "")
    if sel == "selective":
        score += 6
    elif sel == "broad":
        score -= 4
    if hof_rate >= 60 and total >= 8:
        score += 4
    elif hof_rate <= 20 and total >= 15:
        score -= 3

    if sort_stat and sort_stat in strengths:
        score += 8
    elif sort_stat and sort_stat in weaknesses and strengths:
        score += 2
    elif sort_stat and sort_stat in weaknesses:
        score -= 6

    if target_rank and total:
        rank_n = _safe_int(target_rank)
        pct_in_cohort = 100.0 * (1 - (rank_n - 1) / max(total - 1, 1))
        if pct_in_cohort >= 90:
            score += 10
        elif pct_in_cohort >= 75:
            score += 5
        elif pct_in_cohort < 40 and sort_stat in strengths:
            score -= 8

    score = max(0, min(100, int(round(score))))
    if score >= 82:
        bucket = "Very Strong"
    elif score >= 67:
        bucket = "Strong"
    elif score >= 52:
        bucket = "Solid"
    elif score >= 36:
        bucket = "Borderline"
    else:
        bucket = "Weak"
    return score, bucket


def compose_hof_statistical_case(packet: dict[str, Any]) -> dict[str, Any]:
    """Build a compact statistical case memo — not induction odds."""
    target = str(packet.get("target_player") or "").strip()
    sort_stat = str(packet.get("sort_stat") or "").strip()
    primary_pos = _normalize_position(str(packet.get("primary_position") or "Unknown"))
    filters = packet.get("filters_used") if isinstance(packet.get("filters_used"), dict) else {}
    filter_interp = _interpret_filters(filters)
    signal_context = _build_signal_vs_context(packet, filter_interp)
    identity = packet.get("target_identity") if isinstance(packet.get("target_identity"), dict) else {}
    ranks = packet.get("target_cohort_ranks") if isinstance(packet.get("target_cohort_ranks"), dict) else {}
    strengths = list(packet.get("cohort_strength_stats") or [])
    weaknesses = list(packet.get("cohort_weakness_stats") or [])
    selectivity = packet.get("cohort_selectivity") if isinstance(packet.get("cohort_selectivity"), dict) else {}
    comparables = packet.get("comparable_players") if isinstance(packet.get("comparable_players"), dict) else {}
    target_stats = _target_stats(packet)
    score, bucket = _score_case(packet)

    profile_lines = _build_notable_profile_lines(packet)
    strongest: list[str] = list(profile_lines[:6])
    if not strongest:
        for stat in strengths[:4]:
            info = ranks.get(stat)
            if isinstance(info, dict):
                line = _fmt_player_strength(stat, info, target_stats)
                if line:
                    strongest.append(line)

    weakest: list[str] = []
    for stat in weaknesses[:3]:
        info = ranks.get(stat)
        if isinstance(info, dict):
            line = _fmt_rank(info)
            if line:
                weakest.append(
                    f"Limited relative value by {_STAT_LABELS.get(stat, stat)} — {line}."
                )
    if sort_stat and sort_stat in weaknesses and sort_stat not in strengths:
        rank = packet.get("target_rank")
        total = packet.get("total_players_returned")
        if rank and total:
            alt = [s for s in strengths[:3] if s != sort_stat]
            alt_text = f"; the case rests more on {', '.join(_STAT_LABELS.get(s, s) for s in alt)}" if alt else ""
            weakest.append(
                f"Only #{rank} of {total} in this cohort by {_STAT_LABELS.get(sort_stat, sort_stat)}{alt_text}."
            )

    cohort_lines: list[str] = []
    hof_n = packet.get("hall_of_famers_returned")
    total = packet.get("total_players_returned")
    rate = packet.get("hall_of_fame_rate_pct")
    if total is not None:
        cohort_lines.append(f"Cohort: {total} players, {hof_n} inducted ({rate}%).")
    sel = str(selectivity.get("selectivity") or "")
    if sel == "selective":
        cohort_lines.append("Selective cohort — standing within the group carries weight.")
    elif sel == "broad":
        cohort_lines.append("Broad cohort — interpret ranks cautiously.")

    position_era = _build_position_analysis(packet, bucket)
    era = _era_note(identity)
    if era:
        position_era.append(era)

    comparison = _build_comparable_notes(packet)
    hof_names = _player_names(comparables.get("hall_of_famers") or [])
    non_hof_names = _player_names(comparables.get("non_hall_of_famers") or [])

    strength_labels = [_STAT_LABELS.get(s, s) for s in strengths[:3]]
    thesis_parts = [f"{target}'s statistical Hall of Fame case is **{bucket}**"]
    if strengths and sort_stat in weaknesses:
        thesis_parts.append(
            f"with the real signal in {', '.join(strength_labels)} rather than {_STAT_LABELS.get(sort_stat, sort_stat)} rank"
        )
    elif strengths:
        thesis_parts.append(f"driven by {', '.join(strength_labels)} within this cohort")
    if primary_pos != "Unknown":
        thesis_parts.append(f"evaluated at {primary_pos}")
    thesis = " — ".join(thesis_parts) + "."

    takeaway_bits = [
        f"**{bucket}** on the {CASE_SCORE_LABEL} — not induction odds.",
    ]
    if strongest:
        takeaway_bits.append(f"Strongest evidence: {strongest[0].rstrip('.')}.")
    if weakest:
        takeaway_bits.append(f"Main caution: {weakest[0].rstrip('.')}.")
    if hof_names:
        takeaway_bits.append(
            f"Compare to inducted peers ({', '.join(hof_names[:2])}) and non-inducted comps "
            f"({', '.join(non_hof_names[:2]) if non_hof_names else 'similar profiles'}) for context."
        )
    if primary_pos != "Unknown":
        takeaway_bits.append(f"At {primary_pos}, the verdict reflects position-relative production and era context.")
    takeaway = " ".join(takeaway_bits)

    case_evidence = list(signal_context.get("case_evidence") or [])
    cohort_context_only = list(signal_context.get("cohort_context_only") or [])
    if filter_interp.get("sort_stat_note") and sort_stat in weaknesses:
        cohort_context_only.append(str(filter_interp["sort_stat_note"]))

    supporting = strongest[:4] + ([weakest[0]] if weakest else [])
    memo_sections = {
        "verdict": bucket,
        "thesis": thesis,
        "strongest_evidence": strongest,
        "weakest_evidence": weakest,
        "case_evidence": case_evidence,
        "cohort_context_only": cohort_context_only,
        "cohort_interpretation": cohort_lines,
        "position_era_context": position_era,
        "hof_comparisons": hof_names,
        "non_hof_comparisons": non_hof_names,
        "comparison_notes": comparison,
        "final_takeaway": takeaway,
        "sort_stat_caution": filter_interp.get("sort_stat_note") or "",
    }

    return {
        "verdict_bucket": bucket,
        "score": score,
        "score_label": CASE_SCORE_LABEL,
        "score_buckets": list(CASE_SCORE_BUCKETS),
        "thesis": thesis,
        "recommendation": f"**Verdict: {bucket}** — {thesis}",
        "supporting_points": supporting,
        "case_memo": memo_sections,
        "disclaimer": str(packet.get("disclaimer") or "").strip()
        or (
            "Statistical Hall of Fame case analysis only — not true Hall of Fame induction odds "
            "or a guaranteed probability."
        ),
        "confidence": str(selectivity.get("confidence") or "moderate"),
        "target_player": target,
    }


def build_hof_case_subtitle(packet: dict[str, Any]) -> str:
    """One-line cohort / position / career span context for page headers."""
    parts: list[str] = []
    hof_n = packet.get("hall_of_famers_returned")
    total = packet.get("total_players_returned")
    rate = packet.get("hall_of_fame_rate_pct")
    if total is not None:
        parts.append(f"Cohort {hof_n}/{total} Hall of Famers ({rate}%)")
    rank = packet.get("target_rank")
    sort_stat = str(packet.get("sort_stat") or "").strip()
    if rank and sort_stat:
        parts.append(f"#{rank} in cohort by {sort_stat}")
    pos = str(packet.get("primary_position") or "").strip()
    if pos and pos != "Unknown":
        parts.append(f"Primary position {pos}")
    identity = packet.get("target_identity") if isinstance(packet.get("target_identity"), dict) else {}
    span = identity.get("career_span") if isinstance(identity.get("career_span"), dict) else {}
    debut = span.get("debut_year")
    final = span.get("final_year")
    if debut and final:
        parts.append(f"Career {debut}–{final}")
    return " · ".join(parts)


def resolve_hof_case_analysis(
    packet: dict[str, Any],
    verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Best available composed analysis dict for memo rendering."""
    if isinstance(verdict, dict) and verdict.get("case_memo"):
        return verdict
    analysis = packet.get("hof_case_analysis") if isinstance(packet.get("hof_case_analysis"), dict) else {}
    if isinstance(analysis, dict) and analysis.get("case_memo"):
        return analysis
    try:
        composed = compose_hof_statistical_case(packet)
        if composed.get("case_memo"):
            return composed
    except Exception:
        pass
    if isinstance(analysis, dict) and analysis:
        return analysis
    if isinstance(verdict, dict) and verdict:
        return verdict
    return {}


def render_hof_case_full_analysis(
    st: Any,
    packet: dict[str, Any],
    *,
    verdict: dict[str, Any] | None = None,
) -> bool:
    """Dedicated Hall of Fame case memo — not the generic Applied Math insight card."""
    if not isinstance(packet, dict) or not packet:
        return False
    target = str(packet.get("target_player") or "").strip()
    analysis = resolve_hof_case_analysis(packet, verdict)
    memo_md = format_hof_case_memo_markdown(analysis) if analysis else ""
    summary_line = str(packet.get("hof_case_summary") or "").strip()
    if not memo_md or (summary_line and memo_md.strip() == summary_line):
        try:
            analysis = compose_hof_statistical_case(packet)
            memo_md = format_hof_case_memo_markdown(analysis)
        except Exception:
            pass
    st.markdown(f"## Hall of Fame Case — {target or 'Analysis'}")
    subtitle = build_hof_case_subtitle(packet)
    if subtitle:
        st.caption(subtitle)
    score_label = str(packet.get("score_label") or analysis.get("score_label") or CASE_SCORE_LABEL).strip()
    if score_label:
        st.caption(score_label)
    if memo_md and "### Verdict:" in memo_md:
        st.markdown(memo_md)
        return True
    if memo_md:
        st.markdown(memo_md)
        return True
    thesis = str(analysis.get("thesis") or "").strip()
    if thesis:
        st.markdown(thesis)
        return True
    if summary_line:
        st.markdown(summary_line)
        return True
    return False


def format_hof_case_memo_markdown(analysis: dict[str, Any]) -> str:
    """Render case memo as markdown for AMI / insight panels."""
    memo = analysis.get("case_memo") if isinstance(analysis.get("case_memo"), dict) else {}
    if not memo:
        return str(analysis.get("recommendation") or "").strip()
    lines = [
        f"### Verdict: {memo.get('verdict', '—')}",
        "",
        str(memo.get("thesis") or analysis.get("thesis") or "").strip(),
        "",
        "#### Statistical case",
    ]
    if memo.get("strongest_evidence"):
        lines.append("**Strongest evidence**")
        for item in memo["strongest_evidence"]:
            lines.append(f"- {item}")
    if memo.get("weakest_evidence"):
        lines.append("")
        lines.append("**Weakest evidence / cautions**")
        for item in memo["weakest_evidence"]:
            lines.append(f"- {item}")
    if memo.get("case_evidence"):
        lines.append("")
        lines.append("**Evidence that strengthens the case**")
        for item in memo["case_evidence"]:
            lines.append(f"- {item}")
    if memo.get("cohort_context_only"):
        lines.append("")
        lines.append("**Cohort context only (not evidence by itself)**")
        for item in memo["cohort_context_only"]:
            lines.append(f"- {item}")
    if memo.get("cohort_interpretation"):
        lines.append("")
        lines.append("**Cohort interpretation**")
        for item in memo["cohort_interpretation"]:
            lines.append(f"- {item}")
    if memo.get("position_era_context"):
        lines.append("")
        lines.append("**Position & era context**")
        for item in memo["position_era_context"]:
            lines.append(f"- {item}")
    if memo.get("comparison_notes"):
        lines.append("")
        lines.append("**Comparison notes**")
        for item in memo["comparison_notes"]:
            text = str(item).strip()
            if not text:
                continue
            if text.startswith("**") and text.endswith("**") and "\n" not in text:
                lines.append("")
                lines.append(text)
            elif text.startswith("- "):
                lines.append(text)
            else:
                lines.append(f"- {text}")
    if memo.get("final_takeaway"):
        lines.append("")
        lines.append("#### Final takeaway")
        lines.append(str(memo["final_takeaway"]))
    if analysis.get("disclaimer"):
        lines.append("")
        lines.append(f"*{analysis['disclaimer']}*")
    return "\n".join(lines)
