"""Compose a statistical Hall of Fame case memo from a hof_case_packet."""

from __future__ import annotations

import json
import re
from datetime import datetime
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
    (("H", "2B"), "similar hit volume and doubles profile"),
    (("OPS",), "similar overall offensive value"),
    (("RBI",), "similar run production"),
    (("SB",), "similar speed value"),
)

_POSITION_STAT_PRIORITY: dict[str, tuple[str, ...]] = {
    "1B": ("2B", "H", "BA", "RBI", "OBP", "OPS", "HR", "SLG", "R", "BB"),
    "DH": ("HR", "SLG", "OPS", "OBP", "RBI", "H", "BA", "2B"),
    "OF": ("HR", "OPS", "SLG", "SB", "RBI", "H", "OBP", "2B"),
    "C": ("OPS", "OBP", "HR", "RBI", "H", "2B", "BA"),
    "SS": ("OPS", "OBP", "HR", "RBI", "SB", "H", "2B"),
    "2B": ("OPS", "OBP", "2B", "H", "RBI", "HR", "SB"),
    "3B": ("HR", "OPS", "SLG", "RBI", "OBP", "H", "2B"),
}
_DEFAULT_STAT_PRIORITY = ("OBP", "OPS", "2B", "H", "BA", "RBI", "HR", "SLG", "BB", "R", "SB")

_HOF_DISCLAIMER = (
    "Statistical case score only — not Hall of Fame induction odds or election probability."
)

MEMO_QUALITY_VERSION = "hof_memo_quality_v3"

_STAT_MILESTONE_THRESHOLDS: dict[str, tuple[tuple[int, str], ...]] = {
    "HR": ((500, "500-HR"), (400, "400-HR"), (300, "300-HR")),
    "H": ((3000, "3,000-hit"), (2500, "2,500-hit"), (2000, "2,000-hit")),
    "RBI": ((1500, "1,500-RBI"), (1000, "1,000-RBI")),
    "R": ((2000, "2,000-run"),),
    "2B": ((600, "600-double"), (500, "500-double"), (400, "400-double")),
    "BB": ((1500, "1,500-walk"), (1000, "1,000-walk")),
    "SB": ((500, "500-SB"), (300, "300-SB")),
    "G": ((3000, "3,000-game"), (2000, "2,000-game")),
    "AB": ((10000, "10,000-AB"), (8000, "8,000-AB")),
}


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


def _format_count(val: Any) -> str:
    return f"{_safe_int(val):,}"


def _highest_milestone_line(stat: str, raw_val: Any) -> str | None:
    """Return actual total with highest cleared milestone, e.g. '569 home runs, clearing the 500-HR milestone'."""
    stat_key = str(stat or "").strip().upper()
    if stat_key in ("BA", "OBP", "SLG", "OPS"):
        val = _safe_float(raw_val)
        if val <= 0:
            return None
        return f"{_format_stat_value(stat_key, val)} {_STAT_LABELS.get(stat_key, stat_key)}"
    val = _safe_int(raw_val)
    if val <= 0:
        return None
    label = _STAT_LABELS.get(stat_key, stat_key)
    for threshold, milestone_name in _STAT_MILESTONE_THRESHOLDS.get(stat_key, ()):
        if val >= threshold:
            return f"{_format_count(val)} {label}, clearing the {milestone_name} milestone"
    return None


def _build_career_total_evidence(packet: dict[str, Any], *, limit: int = 5) -> list[str]:
    """Player career totals with one highest milestone per stat — not generic milestone labels."""
    target_stats = _target_stats(packet)
    strengths = set(packet.get("cohort_strength_stats") or [])
    primary_pos = _normalize_position(str(packet.get("primary_position") or "Unknown"))
    priority = list(_stat_priority_for_position(primary_pos))
    for stat in ("HR", "H", "2B", "RBI", "G", "R", "BB", "SB", "AB"):
        if stat not in priority:
            priority.append(stat)
    lines: list[str] = []
    used: set[str] = set()
    for stat in priority:
        if stat in used:
            continue
        raw = target_stats.get(stat)
        if raw is None:
            continue
        line = _highest_milestone_line(stat, raw)
        if not line:
            continue
        val_n = _safe_int(raw) if stat not in ("BA", "OBP", "SLG", "OPS") else 0
        thresholds = _STAT_MILESTONE_THRESHOLDS.get(stat, ())
        has_milestone = any(val_n >= threshold for threshold, _ in thresholds)
        if has_milestone or stat in strengths:
            lines.append(line + ".")
            used.add(stat)
        if len(lines) >= limit:
            break
    return lines


def _fmt_position_rank_clause(stat: str, rank_info: dict[str, Any], target_stats: dict[str, Any]) -> str:
    label = _STAT_LABELS.get(str(stat), str(stat))
    stat_key = str(stat)
    # Rank payloads may carry season highs or rate-column artifacts — career totals are authoritative.
    val = target_stats.get(stat_key)
    if val is None:
        val = rank_info.get("value")
    rank = rank_info.get("rank")
    peer_n = rank_info.get("of")
    if str(stat) in ("BA", "OBP", "SLG", "OPS"):
        val_s = _format_stat_value(str(stat), val)
    else:
        val_s = _format_count(val)
    if rank and peer_n:
        return f"{label} ({val_s}; #{rank} of {_format_count(peer_n)})"
    return f"{label} ({val_s})"


def _analysis_is_current(analysis: dict[str, Any] | None, packet: dict[str, Any] | None = None) -> bool:
    if not isinstance(analysis, dict):
        return False
    memo = _case_memo_dict(analysis.get("case_memo"))
    if str(memo.get("memo_quality_version") or "") != MEMO_QUALITY_VERSION:
        return False
    if not _structured_case_memo_present(memo):
        return False
    if isinstance(packet, dict) and _packet_has_awards_context(packet):
        if not _memo_includes_awards_section("", analysis):
            return False
    return True


def _normalize_bullet_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip().rstrip(".")


def _exclude_duplicate_bullets(candidates: list[str], existing: list[str]) -> list[str]:
    """Drop supporting bullets that repeat strongest-evidence lines."""
    seen = {_normalize_bullet_key(x) for x in existing if str(x or "").strip()}
    out: list[str] = []
    for line in candidates:
        text = str(line or "").strip()
        if not text:
            continue
        key = _normalize_bullet_key(text)
        if key in seen:
            continue
        if any((len(s) > 24 and (key in s or s in key)) for s in seen):
            continue
        seen.add(key)
        out.append(text)
    return out


def _comparable_primary_position(row: dict[str, Any]) -> str:
    for key in ("careerPrimaryPos", "primary_position", "Primary Position", "displayPosition", "POS", "primaryPos"):
        val = str(row.get(key) or "").strip()
        if val:
            return _normalize_position(val)
    return "Unknown"


def _filter_position_peers(rows: list[Any], target_pos: str) -> list[dict[str, Any]]:
    pos = _normalize_position(target_pos)
    if pos == "Unknown":
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict) and _comparable_primary_position(row) == pos:
            out.append(row)
    return out


def _stat_priority_for_position(primary_pos: str) -> tuple[str, ...]:
    return _POSITION_STAT_PRIORITY.get(_normalize_position(primary_pos), _DEFAULT_STAT_PRIORITY)


def _build_strongest_evidence(packet: dict[str, Any], *, limit: int = 5) -> list[str]:
    """Top player-specific signals — actual career totals, awards, and elite cohort ranks."""
    lines: list[str] = []
    target_stats = _target_stats(packet)
    ranks = packet.get("target_cohort_ranks") if isinstance(packet.get("target_cohort_ranks"), dict) else {}
    strengths = list(packet.get("cohort_strength_stats") or [])
    sort_stat = str(packet.get("sort_stat") or "").strip()

    lines.extend(_build_career_total_evidence(packet, limit=limit))

    awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    major_count = _safe_int(awards.get("major_award_count"))
    major_list = awards.get("major_awards") if isinstance(awards.get("major_awards"), list) else []
    if major_count >= 1 and major_list:
        peak_bits: list[str] = []
        for aw in major_list[:4]:
            if not isinstance(aw, dict):
                continue
            label = str(aw.get("display_name") or aw.get("award") or "").strip()
            cnt = _safe_int(aw.get("count"), default=1)
            if label:
                peak_bits.append(f"{cnt}× {label}" if cnt > 1 else label)
        peak_text = ", ".join(peak_bits) if peak_bits else f"{major_count} major award(s)"
        lines.append(
            f"{peak_text} — peak recognition that strengthens the Hall of Fame argument beyond counting stats."
        )
    elif major_count >= 1:
        lines.append(
            f"{major_count} major award(s) — peak-value support for the statistical case."
        )

    priority_stats = _stat_priority_for_position(str(packet.get("primary_position") or "Unknown"))
    ordered = [s for s in priority_stats if s in strengths]
    ordered += [s for s in strengths if s not in ordered]
    for stat in ordered:
        info = ranks.get(stat)
        if not isinstance(info, dict):
            continue
        pct = _safe_float(info.get("percentile_top"))
        if pct >= 75 or stat == sort_stat:
            line = _fmt_player_strength(stat, info, target_stats)
            if line:
                lines.append(line)
        if len(lines) >= limit + 2:
            break

    return _dedupe_lines(lines)[:limit]


def _build_notable_profile_lines(packet: dict[str, Any]) -> list[str]:
    """Backward-compatible alias — strongest-evidence builder."""
    return _build_strongest_evidence(packet, limit=8)


def _build_position_analysis(packet: dict[str, Any], bucket: str) -> list[str]:
    """Position-relative Hall context — not just 'Primary position: 1B.'"""
    pos = _normalize_position(str(packet.get("primary_position") or "Unknown"))
    target = str(packet.get("target_player") or "").strip() or "The target"
    if pos == "Unknown":
        return []

    lines: list[str] = []
    target_stats = _target_stats(packet)
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
        rank_info = pos_ranks.get(stat) if isinstance(pos_ranks.get(stat), dict) else {}
        clause = _fmt_position_rank_clause(str(stat), rank_info, target_stats)
        if pct >= 90 or any(x in tier.lower() for x in ("top 1", "top 5", "top 10")):
            elite.append(clause)
        elif pct >= 75 or "quartile" in tier.lower():
            strong.append(clause)
        elif pct < 50:
            weak.append(clause)

    offense_first = pos in ("1B", "DH", "OF", "3B")
    if elite:
        lines.append(
            f"Relative to other {pos}s in this dataset, {target} ranks near the top in "
            f"{', '.join(elite[:4])} — above typical Hall-caliber offensive production at the position."
            if offense_first
            else f"Relative to other {pos}s, {target} ranks near the top in {', '.join(elite[:4])}."
        )
    elif strong:
        lines.append(
            f"Solid {pos} offensive standing: {target} is top-quartile among position peers in {', '.join(strong[:3])}."
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
    hof_peers = _filter_position_peers(comparables.get("hall_of_famers") or [], pos)
    hof_names = _player_names(hof_peers, limit=2)
    if hof_names and elite:
        lines.append(
            f"Same-position Hall of Fame peers in this dataset (e.g. {', '.join(hof_names)}) show a comparable or "
            "stronger offensive tier — the target must be weighed against that positional bar."
        )
    elif hof_names and bucket in ("Strong", "Very Strong", "Solid"):
        lines.append(
            f"Among same-position inducted {pos}s here ({', '.join(hof_names)}), the target's best categories "
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
    """Comparison notes — separate same-position peers from broader statistical comps."""
    comparables = packet.get("comparable_players") if isinstance(packet.get("comparable_players"), dict) else {}
    target_stats = _target_stats(packet)
    sort_stat = str(packet.get("sort_stat") or "HR")
    target_pos = _normalize_position(str(packet.get("primary_position") or "Unknown"))
    notes: list[str] = []

    hof_rows = comparables.get("hall_of_famers") or []
    hof_same = _filter_position_peers(hof_rows, target_pos) if target_pos != "Unknown" else []
    hof_same_names = {str(r.get("fullName") or r.get("player") or "").strip() for r in hof_same if isinstance(r, dict)}
    hof_broader = [
        r for r in hof_rows if isinstance(r, dict) and str(r.get("fullName") or r.get("player") or "").strip() not in hof_same_names
    ]

    if hof_same:
        notes.append("**Same-position Hall of Fame peers**")
        for comp in hof_same[:3]:
            comp = {**comp, "_sort_stat": sort_stat}
            name = str(comp.get("fullName") or comp.get("player") or "").replace("⭐ ", "").strip()
            if not name:
                continue
            reason = _comparable_shared_reason(target_stats, comp)
            notes.append(f"- **{name}** — {reason}; inducted in this dataset.")

    if hof_broader:
        notes.append("**Broader Hall of Fame statistical comps**")
        for comp in hof_broader[:3]:
            comp = {**comp, "_sort_stat": sort_stat}
            name = str(comp.get("fullName") or comp.get("player") or "").replace("⭐ ", "").strip()
            if not name:
                continue
            reason = _comparable_shared_reason(target_stats, comp)
            comp_pos = _comparable_primary_position(comp)
            pos_note = ""
            if target_pos != "Unknown" and comp_pos != "Unknown" and comp_pos != target_pos:
                pos_note = f"; {comp_pos} profile — broader comp, not a {target_pos} positional peer"
            notes.append(f"- **{name}** — {reason}{pos_note}; inducted in this cohort.")

    non_rows = comparables.get("non_hall_of_famers") or []
    if non_rows:
        notes.append("**Not-yet-inducted / non-HOF-flagged comps in this dataset**")
        for comp in non_rows[:3]:
            if not isinstance(comp, dict):
                continue
            comp = {**comp, "_sort_stat": sort_stat}
            name = str(comp.get("fullName") or comp.get("player") or "").replace("⭐ ", "").strip()
            if not name:
                continue
            reason = _comparable_shared_reason(target_stats, comp)
            comp_pos = _comparable_primary_position(comp)
            pos_note = ""
            if target_pos != "Unknown" and comp_pos != "Unknown" and comp_pos != target_pos:
                pos_note = f"; {comp_pos} profile — broader comp, not a {target_pos} peer"
            notes.append(
                f"- **{name}** — {reason}{pos_note}; not yet inducted / non-HOF-flagged in this dataset "
                "(may reflect active, recent, or not-yet-eligible career)."
            )

    return notes


def _build_signal_vs_context(packet: dict[str, Any], filter_interp: dict[str, Any]) -> dict[str, list[str]]:
    """Separate supporting case context from strongest player-specific signals."""
    case_evidence: list[str] = []
    cohort_context: list[str] = list(filter_interp.get("cohort_context") or [])

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


def _awards_thesis_clause(packet: dict[str, Any]) -> str:
    """Short awards phrase for thesis / takeaway weaving."""
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if not target_awards.get("data_available"):
        return ""
    major_list = target_awards.get("major_awards") if isinstance(target_awards.get("major_awards"), list) else []
    major_count = _safe_int(target_awards.get("major_award_count"))
    if major_count >= 1 and major_list:
        labels = [
            str(a.get("display_name") or a.get("award") or "").strip()
            for a in major_list[:2]
            if isinstance(a, dict) and str(a.get("display_name") or a.get("award") or "").strip()
        ]
        if labels:
            return f"supported by {major_count} major award(s) including {', '.join(labels)}"
    total = _safe_int(target_awards.get("total_award_count"))
    if total >= 3:
        return f"with {total} career awards as supporting hardware"
    if major_count < 1 and total > 0:
        return "with limited major-award recognition relative to typical inductees"
    return ""


def _build_awards_case_analysis(packet: dict[str, Any]) -> list[str]:
    """Narrative awards analysis woven into the Hall of Fame argument."""
    lines: list[str] = []
    target = str(packet.get("target_player") or "").strip() or "The target"
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    comparison = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    target_rank = packet.get("target_award_rank") if isinstance(packet.get("target_award_rank"), dict) else {}
    cohort_summary = packet.get("cohort_awards_summary") if isinstance(packet.get("cohort_awards_summary"), dict) else {}

    if not target_awards.get("data_available"):
        msg = str(target_awards.get("message") or "").strip()
        if msg:
            lines.append(f"Awards context unavailable ({msg}) — evaluate the case on career totals and cohort ranks.")
        return lines

    major_list = target_awards.get("major_awards") if isinstance(target_awards.get("major_awards"), list) else []
    major_count = _safe_int(target_awards.get("major_award_count"))
    total_count = _safe_int(target_awards.get("total_award_count"))

    if major_count >= 1:
        detail_parts: list[str] = []
        for aw in major_list[:6]:
            if not isinstance(aw, dict):
                continue
            label = str(aw.get("display_name") or aw.get("award") or "").strip()
            cnt = _safe_int(aw.get("count"), default=1)
            years = aw.get("years") if isinstance(aw.get("years"), list) else []
            if not label:
                continue
            year_note = ""
            if years and len(years) <= 4:
                year_note = f" ({', '.join(str(y) for y in years)})"
            elif years:
                year_note = f" ({years[0]}–{years[-1]})"
            detail_parts.append(f"{cnt}× {label}{year_note}" if cnt > 1 else f"{label}{year_note}")
        if detail_parts:
            lines.append(
                f"{target}'s major awards — {', '.join(detail_parts)} — signal peak dominance that "
                "belongs in the overall Hall of Fame argument, not as a footnote."
            )
        rank_major = target_rank.get("rank_by_major_awards")
        if rank_major == 1:
            lines.append("Leads this cohort in major awards — hardware that reinforces the statistical case.")
        elif rank_major is not None and _safe_int(rank_major) <= 3:
            lines.append(f"Ranks #{rank_major} in the cohort for major awards — competitive recognition among peers.")
    elif total_count >= 1:
        lines.append(
            f"{total_count} total awards on record, but no MVP/Cy Young-level hardware — "
            "the case must rest primarily on career totals and cohort standing."
        )
    else:
        lines.append(
            "No major awards listed — the Hall of Fame argument depends on sustained production and milestones, not peak accolades."
        )

    if comparison.get("data_available"):
        fewer_total = _safe_int(comparison.get("players_with_more_total_awards"))
        more_total = _safe_int(comparison.get("players_with_fewer_total_awards"))
        rank_total = target_rank.get("rank_by_total_awards")
        total_players = _safe_int(packet.get("total_players_returned"))
        if rank_total == 1 and total_count > 0:
            lines.append("Most decorated player in this cohort by total awards.")
        elif fewer_total >= max(1, total_players // 2) and major_count < 2:
            lines.append(
                f"{fewer_total} cohort peers have more total awards — awards do not clearly separate "
                f"{target} from the comparison group."
            )
        elif more_total >= max(1, total_players // 2) and major_count >= 1:
            lines.append(
                f"More total awards than {more_total} peers in this cohort — supporting evidence alongside the stat line."
            )
        avg_major = _safe_float(cohort_summary.get("average_major_award_count"))
        if major_count >= 2 and avg_major > 0 and major_count >= avg_major * 1.5:
            lines.append(
                f"Major-award count ({major_count}) exceeds the cohort average ({avg_major:.1f}) — "
                "a meaningful differentiator for peak value."
            )

    return _dedupe_lines(lines)[:6]


def _era_note(identity: dict[str, Any]) -> str:
    span = identity.get("career_span") if isinstance(identity.get("career_span"), dict) else {}
    debut = span.get("debut_year")
    final = span.get("final_year")
    seasons = span.get("seasons")
    if not debut or not final:
        return ""
    note = f"Career span in this dataset: {debut}–{final}"
    if seasons:
        note += f" ({seasons} seasons)"
    note += ". "
    current_year = datetime.now().year
    final_year = _safe_int(final)
    debut_year = _safe_int(debut)
    if final_year >= current_year - 1:
        note += (
            "Compare counting totals with care — the player is still active and modern roster usage "
            "differs from older retired peers."
        )
    elif debut_year >= 2000:
        note += (
            "Compare counting totals with care — modern-era usage and bullpen patterns differ from "
            "older players in this cohort."
        )
    elif debut_year < 1970:
        note += (
            "Earlier-era counting totals can read higher in raw numbers; weight cohort rank and "
            "position-relative production."
        )
    return note


def _summarize_strength_themes(strengths: list[str], primary_pos: str) -> str:
    labels = [_STAT_LABELS.get(s, s) for s in strengths[:4]]
    if labels:
        return ", ".join(labels)
    if primary_pos != "Unknown":
        return f"sustained {primary_pos} offensive value"
    return "sustained offensive production within this cohort"


def _build_final_takeaway(
    *,
    target: str,
    bucket: str,
    primary_pos: str,
    sort_stat: str,
    strengths: list[str],
    weaknesses: list[str],
    career_totals: list[str],
    weakest: list[str],
) -> str:
    """Explain why the verdict follows from the evidence."""
    strength_theme = _summarize_strength_themes(strengths, primary_pos)
    pos_clause = f" at {primary_pos}" if primary_pos != "Unknown" else ""

    if bucket in ("Very Strong", "Strong"):
        lead = f"**{bucket}** because {target} combines elite {strength_theme}{pos_clause}"
    elif bucket == "Solid":
        lead = f"**{bucket}** because {target} shows clear {strength_theme}{pos_clause}"
    elif bucket == "Borderline":
        lead = (
            f"**{bucket}** because {target} has real value in {strength_theme}{pos_clause}, "
            "but the case is mixed"
        )
    else:
        lead = (
            f"**{bucket}** because {target} does not separate clearly on "
            f"{strength_theme or 'core categories'}{pos_clause}"
        )

    caution_parts: list[str] = []
    if sort_stat and sort_stat in weaknesses and strengths:
        alt = [s for s in strengths if s != sort_stat][:3]
        if alt:
            alt_text = ", ".join(_STAT_LABELS.get(s, s) for s in alt)
            caution_parts.append(
                f"the caution is that {_STAT_LABELS.get(sort_stat, sort_stat)} rank is not elite in this "
                f"{_STAT_LABELS.get(sort_stat, sort_stat)}-sorted cohort, so the case rests more on "
                f"{alt_text}, longevity, and complete offensive profile than pure power"
            )
    elif weakest:
        caution_parts.append(weakest[0].rstrip("."))

    body = lead + "."
    if career_totals:
        totals_text = "; ".join(str(x).rstrip(".") for x in career_totals[:3])
        body += f" Key totals: {totals_text}."
    if caution_parts:
        body += f" {'; '.join(caution_parts)}."
    body += f" Verdict reflects the {CASE_SCORE_LABEL} — not induction odds."
    return body


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
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if target_awards.get("data_available"):
        major_count = _safe_int(target_awards.get("major_award_count"))
        if major_count >= 3:
            score += 12
        elif major_count >= 1:
            score += 8
        target_rank = packet.get("target_award_rank") if isinstance(packet.get("target_award_rank"), dict) else {}
        if target_rank.get("rank_by_major_awards") == 1 and major_count >= 1:
            score += 6
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

    profile_lines = _build_strongest_evidence(packet, limit=5)
    strongest: list[str] = list(profile_lines)
    if not strongest:
        for stat in strengths[:4]:
            info = ranks.get(stat)
            if isinstance(info, dict):
                line = _fmt_player_strength(stat, info, target_stats)
                if line:
                    strongest.append(line)
    strongest = _dedupe_lines(strongest)[:5]

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

    strength_labels = [_STAT_LABELS.get(s, s) for s in strengths[:4]]
    awards_clause = _awards_thesis_clause(packet)
    thesis_parts = [f"{target}'s statistical Hall of Fame case is **{bucket}**"]
    if strengths and sort_stat in weaknesses:
        thesis_parts.append(
            f"with the clearest signal in {', '.join(strength_labels)} rather than "
            f"{_STAT_LABELS.get(sort_stat, sort_stat)} rank in this cohort"
        )
    elif strengths:
        thesis_parts.append(f"driven by {', '.join(strength_labels)} within this cohort")
    if awards_clause:
        thesis_parts.append(awards_clause)
    if primary_pos != "Unknown":
        thesis_parts.append(f"evaluated against {primary_pos} offensive standards")
    thesis = " — ".join(thesis_parts) + "."

    awards_analysis = _build_awards_case_analysis(packet)

    career_totals = _build_career_total_evidence(packet, limit=4)

    takeaway = _build_final_takeaway(
        target=target,
        bucket=bucket,
        primary_pos=primary_pos,
        sort_stat=sort_stat,
        strengths=strengths,
        weaknesses=weaknesses,
        career_totals=career_totals,
        weakest=weakest,
    )

    case_evidence = _exclude_duplicate_bullets(
        list(signal_context.get("case_evidence") or []),
        strongest + career_totals,
    )
    cohort_context_only = list(signal_context.get("cohort_context_only") or [])
    if filter_interp.get("sort_stat_note") and sort_stat in weaknesses:
        cohort_context_only.append(str(filter_interp["sort_stat_note"]))

    supporting = strongest[:3] + awards_analysis[:2] + ([weakest[0]] if weakest else [])
    memo_sections = {
        "memo_quality_version": MEMO_QUALITY_VERSION,
        "verdict": bucket,
        "thesis": thesis,
        "strongest_evidence": strongest,
        "weakest_evidence": weakest,
        "awards_analysis": awards_analysis,
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
        "recommendation": f"**{CASE_SCORE_LABEL}: {bucket}** — {thesis}",
        "supporting_points": supporting,
        "case_memo": memo_sections,
        "disclaimer": _hof_disclaimer_for_packet(packet, awards_analysis),
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


_MEMO_SECTION_KEYS = (
    "strongest_evidence",
    "weakest_evidence",
    "awards_analysis",
    "case_evidence",
    "cohort_context_only",
    "cohort_interpretation",
    "position_era_context",
    "comparison_notes",
    "final_takeaway",
)
_MEMO_FULL_MIN_LEN = 500
_MEMO_MIN_LEN = 80


def _case_memo_dict(raw: Any) -> dict[str, Any]:
    """Normalize case_memo from dict, JSON string, or pre-rendered markdown."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        if "### Verdict" in text or "#### Statistical case" in text or "#### Final takeaway" in text:
            return {"_preformatted_markdown": text}
    return {}


def _structured_case_memo_present(raw: Any) -> bool:
    memo = _case_memo_dict(raw)
    if not memo:
        return False
    if memo.get("_preformatted_markdown"):
        return True
    if str(memo.get("verdict") or "").strip():
        return True
    if str(memo.get("thesis") or "").strip():
        return True
    return any(memo.get(key) for key in _MEMO_SECTION_KEYS)


def _normalize_hof_analysis(analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}
    out = dict(analysis)
    memo = _case_memo_dict(out.get("case_memo"))
    if memo:
        out["case_memo"] = memo
    elif "case_memo" in out:
        out.pop("case_memo", None)
    return out


def _packet_has_awards_context(packet: dict[str, Any]) -> bool:
    awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    return bool(awards.get("data_available"))


def _memo_includes_awards_section(memo_md: str, analysis: dict[str, Any]) -> bool:
    text = str(memo_md or "")
    if "#### Awards & accolades" in text or "Awards & accolades" in text:
        return True
    memo = _case_memo_dict(analysis.get("case_memo"))
    return bool(memo.get("awards_analysis"))


def _hof_memo_is_full(memo_md: str, summary_line: str = "") -> bool:
    text = str(memo_md or "").strip()
    if len(text) < _MEMO_MIN_LEN:
        return False
    if summary_line and text == summary_line.strip():
        return False
    if "### Verdict:" in text or "### Verdict" in text:
        return len(text) >= _MEMO_MIN_LEN
    return len(text) >= _MEMO_FULL_MIN_LEN and any(
        marker in text
        for marker in ("#### Statistical case", "Strongest evidence", "Final takeaway", "Weakest evidence")
    )


def _detect_memo_sections(memo: dict[str, Any]) -> list[str]:
    return [key for key in _MEMO_SECTION_KEYS if memo.get(key)]


def _build_hof_memo_render_diag(
    *,
    packet: dict[str, Any],
    verdict: dict[str, Any] | None,
    analysis: dict[str, Any],
    memo_md: str,
    summary_line: str,
    fallback_reason: str,
) -> dict[str, Any]:
    verdict_dict = verdict if isinstance(verdict, dict) else {}
    packet_dict = packet if isinstance(packet, dict) else {}
    analysis_dict = analysis if isinstance(analysis, dict) else {}
    hof_analysis = (
        packet_dict.get("hof_case_analysis") if isinstance(packet_dict.get("hof_case_analysis"), dict) else {}
    )
    case_memo = _case_memo_dict(
        analysis_dict.get("case_memo")
        or verdict_dict.get("case_memo")
        or hof_analysis.get("case_memo")
    )
    memo_len = len(str(case_memo.get("_preformatted_markdown") or memo_md or ""))
    return {
        "render_hof_case_full_analysis_entered": True,
        "packet_keys": sorted(packet_dict.keys()) if packet_dict else [],
        "hof_case_analysis_keys": sorted(hof_analysis.keys()) if hof_analysis else [],
        "verdict_context_keys": sorted(verdict_dict.keys()) if verdict_dict else [],
        "case_memo_present": bool(case_memo),
        "case_memo_len": memo_len,
        "verdict_present": bool(str(case_memo.get("verdict") or analysis_dict.get("verdict_bucket") or "").strip()),
        "thesis_present": bool(str(case_memo.get("thesis") or analysis_dict.get("thesis") or "").strip()),
        "sections_detected": _detect_memo_sections(case_memo),
        "memo_md_len": len(str(memo_md or "")),
        "memo_is_full": _hof_memo_is_full(str(memo_md or ""), summary_line),
        "fallback_reason": fallback_reason or "",
    }


def _store_hof_memo_render_diag(st: Any, diag: dict[str, Any]) -> None:
    try:
        ss = st.session_state
        ss["_hof_case_memo_render_diag"] = dict(diag)
        hydrate_diag = dict(ss.get("_suite_ai_hydrate_diag") or {})
        hydrate_diag.update(diag)
        ss["_suite_ai_hydrate_diag"] = hydrate_diag
    except Exception:
        pass


def _render_hof_memo_render_diagnostics(st: Any, diag: dict[str, Any]) -> None:
    try:
        from components.applied_math_context_diagnostics import applied_math_developer_mode_enabled

        if not applied_math_developer_mode_enabled(st):
            return
    except ImportError:
        return
    with st.expander("HOF memo render diagnostics", expanded=False):
        st.json(diag)


def _hof_disclaimer_for_packet(packet: dict[str, Any], awards_analysis: list[str] | None = None) -> str:
    packet_disclaimer = str(packet.get("disclaimer") or "").strip()
    if packet_disclaimer:
        return packet_disclaimer
    try:
        from hall_of_fame_data import hof_case_disclaimer_text

        include_awards = bool(awards_analysis) or _packet_has_awards_context(packet)
        return hof_case_disclaimer_text(packet, include_awards=include_awards)
    except ImportError:
        return _HOF_DISCLAIMER


def resolve_hof_case_analysis(
    packet: dict[str, Any],
    verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Best available composed analysis dict for memo rendering."""
    packet_dict = packet if isinstance(packet, dict) else {}
    verdict_dict = _normalize_hof_analysis(verdict if isinstance(verdict, dict) else None)
    packet_analysis = _normalize_hof_analysis(
        packet_dict.get("hof_case_analysis") if isinstance(packet_dict.get("hof_case_analysis"), dict) else None
    )
    try:
        composed = compose_hof_statistical_case(packet_dict)
        if _structured_case_memo_present(composed.get("case_memo")):
            if _packet_has_awards_context(packet_dict):
                if _memo_includes_awards_section("", composed):
                    return composed
            elif _analysis_is_current(composed, packet_dict):
                return composed
    except Exception:
        composed = {}
    if _analysis_is_current(packet_analysis, packet_dict):
        return packet_analysis
    if isinstance(composed, dict) and composed.get("case_memo"):
        return composed
    if _analysis_is_current(verdict_dict, packet_dict):
        return verdict_dict
    if packet_analysis:
        return packet_analysis
    if verdict_dict:
        return verdict_dict
    return {}


def _force_compose_hof_memo(packet: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """Compose a full memo from packet; returns (analysis, memo_md, error)."""
    try:
        composed = compose_hof_statistical_case(packet)
        memo_md = format_hof_case_memo_markdown(composed)
        if _structured_case_memo_present(composed.get("case_memo")) or _hof_memo_is_full(memo_md):
            return composed, memo_md, ""
    except Exception as exc:
        return {}, "", f"compose_failed:{type(exc).__name__}:{exc}"
    return {}, "", "compose_empty_memo"


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
    summary_line = str(
        packet.get("hof_case_summary")
        or (verdict or {}).get("hof_case_summary")
        or ""
    ).strip()
    fallback_reason = ""
    composed, composed_md, compose_error = _force_compose_hof_memo(packet)
    if composed_md and _hof_memo_is_full(composed_md, summary_line):
        analysis = composed
        memo_md = composed_md
    else:
        analysis = resolve_hof_case_analysis(packet, verdict)
        memo_md = format_hof_case_memo_markdown(analysis) if analysis else ""

    if (
        _packet_has_awards_context(packet)
        and not _memo_includes_awards_section(memo_md, analysis)
    ):
        composed, composed_md, compose_error = _force_compose_hof_memo(packet)
        if composed_md and _memo_includes_awards_section(composed_md, composed):
            analysis = composed
            memo_md = composed_md
            fallback_reason = ""

    if not _hof_memo_is_full(memo_md, summary_line):
        composed, composed_md, compose_error = _force_compose_hof_memo(packet)
        if compose_error:
            fallback_reason = compose_error
        if _hof_memo_is_full(composed_md, summary_line):
            analysis = composed
            memo_md = composed_md
            fallback_reason = ""

    if not _hof_memo_is_full(memo_md, summary_line):
        if summary_line and memo_md.strip() == summary_line:
            fallback_reason = fallback_reason or "memo_md_equals_hof_case_summary"
        elif not memo_md:
            fallback_reason = fallback_reason or "memo_md_empty_after_compose"
        else:
            fallback_reason = fallback_reason or "memo_md_too_short_for_full_memo"

    diag = _build_hof_memo_render_diag(
        packet=packet,
        verdict=verdict,
        analysis=analysis,
        memo_md=memo_md,
        summary_line=summary_line,
        fallback_reason=fallback_reason,
    )
    _store_hof_memo_render_diag(st, diag)

    subtitle = build_hof_case_subtitle(packet)
    score_label = str(packet.get("score_label") or analysis.get("score_label") or CASE_SCORE_LABEL).strip()
    header_sub = subtitle
    if score_label:
        header_sub = f"{subtitle} · {score_label}" if subtitle else score_label
    identity = packet.get("target_identity") if isinstance(packet.get("target_identity"), dict) else {}
    photo_info = (
        identity.get("player_photo")
        if isinstance(identity.get("player_photo"), dict)
        else {}
    )
    try:
        from player_photos import get_player_photo_info, render_player_headshot_row

        if not photo_info.get("headshot_url"):
            photo_info = get_player_photo_info(
                player_id=identity.get("player_id"),
                full_name=target,
                mlbam_id=photo_info.get("mlbam_id"),
                use_api=True,
            )
        render_player_headshot_row(st, photo_info, title=f"Hall of Fame Case — {target or 'Analysis'}", subtitle=header_sub)
    except ImportError:
        st.markdown(f"## Hall of Fame Case — {target or 'Analysis'}")
        if subtitle:
            st.caption(subtitle)
        if score_label:
            st.caption(score_label)

    if _hof_memo_is_full(memo_md, summary_line):
        st.markdown(memo_md)
        diag["fallback_reason"] = ""
        _store_hof_memo_render_diag(st, diag)
        _render_hof_memo_render_diagnostics(st, diag)
        return True

    thesis = str(analysis.get("thesis") or "").strip()
    if thesis and _hof_memo_is_full(thesis, summary_line):
        st.markdown(thesis)
        diag["fallback_reason"] = ""
        _store_hof_memo_render_diag(st, diag)
        _render_hof_memo_render_diagnostics(st, diag)
        return True

    if summary_line:
        st.markdown(summary_line)
        if not fallback_reason:
            fallback_reason = "used_hof_case_summary_fallback"
        diag["fallback_reason"] = fallback_reason
        _store_hof_memo_render_diag(st, diag)
        _render_hof_memo_render_diagnostics(st, diag)
        return True

    _render_hof_memo_render_diagnostics(st, diag)
    return False


def format_hof_case_memo_markdown(analysis: dict[str, Any]) -> str:
    """Render case memo as markdown for AMI / insight panels."""
    memo = _case_memo_dict(analysis.get("case_memo"))
    if memo.get("_preformatted_markdown"):
        return str(memo["_preformatted_markdown"]).strip()
    if not memo:
        recommendation = str(analysis.get("recommendation") or "").strip()
        if recommendation and _hof_memo_is_full(recommendation):
            return recommendation
        return recommendation
    lines = [
        f"### {CASE_SCORE_LABEL}: {memo.get('verdict', '—')}",
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
    if memo.get("awards_analysis"):
        lines.append("")
        lines.append("#### Awards & accolades")
        for item in memo["awards_analysis"]:
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
