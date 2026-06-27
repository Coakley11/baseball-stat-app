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


def _fmt_rank(rank_info: dict[str, Any]) -> str:
    rank = rank_info.get("rank")
    total = rank_info.get("of")
    stat = str(rank_info.get("stat") or "")
    label = _STAT_LABELS.get(stat, stat)
    val = rank_info.get("value")
    tier = str(rank_info.get("tier") or "").strip()
    val_s = f" ({int(val)})" if val is not None and stat not in ("BA", "OBP", "SLG", "OPS") else ""
    if rank and total:
        base = f"#{rank} of {total} in cohort by {label}{val_s}"
        return f"{base} ({tier})" if tier else base
    return ""


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
    """Return 'strong', 'moderate', or 'context' for a stat minimum."""
    try:
        n = int(float(val))
    except (TypeError, ValueError):
        return "context"
    stat = str(stat or "").strip().upper()
    if stat == "HR" and n >= 400:
        return "strong"
    if stat == "H" and n >= 3000:
        return "strong"
    if stat == "RBI" and n >= 1500:
        return "strong"
    if stat == "HR" and n >= 300:
        return "moderate"
    if stat == "H" and n >= 2500:
        return "moderate"
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
        if level == "strong":
            meaningful_thresholds.append(
                f"{label} ≥ {val} is a meaningful Hall marker — it selects an elite peer group, "
                "not merely an arbitrary slice."
            )
        elif level == "moderate":
            meaningful_thresholds.append(
                f"{label} ≥ {val} defines a selective comparison group with some Hall relevance."
            )
        else:
            cohort_context.append(
                f"{label} ≥ {val} defines the comparison group only — meeting the filter is context, "
                "not evidence of Hall of Fame quality by itself."
            )
    pos = filters.get("position")
    if pos:
        if isinstance(pos, list):
            pos_text = ", ".join(str(p) for p in pos if str(p).strip())
        else:
            pos_text = str(pos)
        if pos_text.strip():
            meaningful_thresholds.append(
                f"Position filter ({pos_text}) — position-relative excellence is meaningful evidence; "
                "the filter itself only defines who is compared."
            )
    hand = filters.get("batting_hand")
    if hand:
        hand_text = ", ".join(hand) if isinstance(hand, list) else str(hand)
        if "S" in hand_text.upper() or "switch" in hand_text.lower():
            cohort_context.append(
                f"Switch-hitter filter ({hand_text}) defines the cohort only — "
                "shared handedness is not evidence of Hall quality."
            )
        else:
            cohort_context.append(
                f"Batting-hand filter ({hand_text}) defines the cohort only — "
                "handedness is not, by itself, a Hall of Fame quality signal."
            )
    team = filters.get("team_filter")
    if team:
        cohort_context.append(
            "Team/franchise filter defines the comparison group — organizational context, not merit evidence."
        )
    yr = filters.get("year_range")
    if isinstance(yr, (list, tuple)) and len(yr) >= 2:
        cohort_context.append(
            f"Year range {yr[0]}–{yr[1]} limits which seasons count — useful context for totals, "
            "not standalone evidence of Hall quality."
        )
    sort_stat = str(filters.get("sort_stat") or "").strip()
    sort_note = ""
    if sort_stat:
        sort_note = (
            f"The table is sorted by {sort_stat}, but a player's case may rest on other categories "
            f"({', '.join(_STAT_LABELS.get(s, s) for s in ('H', 'OBP', 'SB', 'RBI') if s != sort_stat)[:3]} etc.)."
        )
    return {
        "meaningful_thresholds": meaningful_thresholds,
        "cohort_context": cohort_context,
        "sort_stat_note": sort_note,
    }


def _build_signal_vs_context(packet: dict[str, Any], filter_interp: dict[str, Any]) -> dict[str, list[str]]:
    """Separate evidence that strengthens the case from context that defines the cohort."""
    case_evidence: list[str] = []
    cohort_context: list[str] = list(filter_interp.get("cohort_context") or [])

    hof_n = packet.get("hall_of_famers_returned")
    total = packet.get("total_players_returned")
    rate = float(packet.get("hall_of_fame_rate_pct") or 0)
    if total and hof_n is not None:
        if rate >= 50 and int(total) >= 5:
            case_evidence.append(
                f"{hof_n}/{total} players in this cohort are Hall of Famers ({rate}%) — "
                "high prevalence is evidence the filter created a Hall-like peer group."
            )
        elif rate >= 30 and int(total) >= 8:
            case_evidence.append(
                f"{hof_n}/{total} Hall of Famers ({rate}%) — a meaningful share of the cohort is inducted."
            )
        elif rate <= 15 and int(total) >= 10:
            cohort_context.append(
                f"Only {rate}% of this cohort is inducted — filter membership is context; "
                "the case must rest on standing out within the group."
            )

    case_evidence.extend(filter_interp.get("meaningful_thresholds") or [])

    selectivity = packet.get("cohort_selectivity") if isinstance(packet.get("cohort_selectivity"), dict) else {}
    for note in (selectivity.get("threshold_notes") or []):
        text = str(note)
        lower = text.lower()
        if any(k in lower for k in ("hall-of-fame heavy", "hall marker", "selective", "high hall")):
            if text not in case_evidence:
                case_evidence.append(text)
        elif "broad" in lower:
            if text not in cohort_context:
                cohort_context.append(text)

    for ms in packet.get("career_milestones") or []:
        if isinstance(ms, dict) and ms.get("label"):
            line = str(ms["label"])
            if line not in case_evidence:
                case_evidence.append(line)

    for note in packet.get("position_rarity_findings") or []:
        text = str(note)
        if text and text not in case_evidence:
            case_evidence.append(text)

    awards_cmp = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if awards_cmp.get("data_available") and target_awards.get("data_available"):
        major = int(target_awards.get("major_awards") or target_awards.get("mvp_count") or 0)
        total_aw = int(target_awards.get("total_awards") or 0)
        if major >= 1:
            case_evidence.append(
                f"{major} major award(s) (MVP/Cy Young etc.) — meaningful evidence, not cohort context."
            )
        elif total_aw >= 3:
            case_evidence.append(f"{total_aw} career awards — supporting evidence for the statistical case.")
        fewer = int(awards_cmp.get("players_with_more_total_awards") or 0)
        if total and fewer >= int(total) // 2:
            cohort_context.append(
                f"{fewer} cohort peers have more total awards — awards do not clearly separate the target."
            )

    sel = str(selectivity.get("selectivity") or "")
    if sel == "broad":
        cohort_context.append(
            "Broad cohort — do not treat filter selection or a single rank as strong evidence."
        )

    return {"case_evidence": case_evidence, "cohort_context_only": cohort_context}


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
    if int(debut) < 1970:
        note += "Earlier-era counting totals can look stronger in raw numbers; compare within cohort and position."
    elif int(final) >= 2010:
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
    hof_rate = float(packet.get("hall_of_fame_rate_pct") or 0)
    total = int(packet.get("total_players_returned") or 0)
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
        if pct is not None and float(pct) >= 90:
            top_pos_tiers += 1
        elif "top" in tier.lower():
            top_pos_tiers += 1
    score += min(top_pos_tiers * 4, 12)

    awards_cmp = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    if awards_cmp.get("data_available"):
        fewer = int(awards_cmp.get("players_with_more_total_awards") or 0)
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
        pct_in_cohort = 100.0 * (1 - (int(target_rank) - 1) / max(total - 1, 1))
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
    primary_pos = str(packet.get("primary_position") or "Unknown").strip()
    filters = packet.get("filters_used") if isinstance(packet.get("filters_used"), dict) else {}
    filter_interp = _interpret_filters(filters)
    signal_context = _build_signal_vs_context(packet, filter_interp)
    identity = packet.get("target_identity") if isinstance(packet.get("target_identity"), dict) else {}
    ranks = packet.get("target_cohort_ranks") if isinstance(packet.get("target_cohort_ranks"), dict) else {}
    strengths = list(packet.get("cohort_strength_stats") or [])
    weaknesses = list(packet.get("cohort_weakness_stats") or [])
    selectivity = packet.get("cohort_selectivity") if isinstance(packet.get("cohort_selectivity"), dict) else {}
    comparables = packet.get("comparable_players") if isinstance(packet.get("comparable_players"), dict) else {}
    milestones = list(packet.get("career_milestones") or [])
    pos_findings = list(packet.get("position_rarity_findings") or [])
    score, bucket = _score_case(packet)

    strongest: list[str] = []
    for stat in strengths[:4]:
        info = ranks.get(stat)
        if isinstance(info, dict):
            line = _fmt_rank(info)
            if line:
                strongest.append(line)
    for ms in milestones[:3]:
        if isinstance(ms, dict) and ms.get("label"):
            strongest.append(str(ms["label"]))
    for note in pos_findings[:2]:
        strongest.append(str(note))

    weakest: list[str] = []
    for stat in weaknesses[:3]:
        info = ranks.get(stat)
        if isinstance(info, dict):
            line = _fmt_rank(info)
            if line:
                weakest.append(line)
    if sort_stat and sort_stat in weaknesses and sort_stat not in strengths:
        rank = packet.get("target_rank")
        total = packet.get("total_players_returned")
        if rank and total:
            weakest.append(
                f"Only #{rank} of {total} in this cohort by {_STAT_LABELS.get(sort_stat, sort_stat)} — "
                "but that sort key may not capture the player's primary value."
            )

    cohort_lines: list[str] = []
    hof_n = packet.get("hall_of_famers_returned")
    total = packet.get("total_players_returned")
    rate = packet.get("hall_of_fame_rate_pct")
    if total is not None:
        cohort_lines.append(f"Cohort size: {total} players ({hof_n} Hall of Famers, {rate}%).")
    sel = str(selectivity.get("selectivity") or "")
    if sel == "selective":
        cohort_lines.append("Selective cohort — standing within the group carries meaningful weight.")
    elif sel == "broad":
        cohort_lines.append("Broad cohort — rank and filter membership should be weighted cautiously.")

    position_era: list[str] = []
    if primary_pos and primary_pos != "Unknown":
        position_era.append(f"Primary position: {primary_pos}.")
    era = _era_note(identity)
    if era:
        position_era.append(era)

    hof_names = _player_names(comparables.get("hall_of_famers") or [])
    non_hof_names = _player_names(comparables.get("non_hall_of_famers") or [])
    comparison: list[str] = []
    if hof_names:
        comparison.append(f"Closest Hall of Fame statistical peers in this cohort: {', '.join(hof_names)}.")
    if non_hof_names:
        comparison.append(f"Similar non-inducted comparables: {', '.join(non_hof_names)}.")

    thesis_parts = [f"{target}'s statistical Hall of Fame case is **{bucket}**"]
    if strengths and sort_stat in weaknesses:
        thesis_parts.append(
            f"despite a modest rank by {sort_stat}, with stronger evidence in "
            f"{', '.join(_STAT_LABELS.get(s, s) for s in strengths[:3])}"
        )
    elif strengths:
        thesis_parts.append(
            f"supported by top-cohort standing in {', '.join(_STAT_LABELS.get(s, s) for s in strengths[:3])}"
        )
    thesis = " — ".join(thesis_parts) + "."

    takeaway = (
        f"This is a **{CASE_SCORE_LABEL}** assessment only — not true Hall of Fame induction odds. "
        f"Given career totals, position context, awards, comparables, and cohort selectivity, "
        f"the profile reads as **{bucket}**."
    )
    if sort_stat in weaknesses and strengths:
        takeaway += (
            f" Do not read #{packet.get('target_rank')} by {sort_stat} alone; "
            f"the case rests more on {', '.join(strengths[:3])}."
        )
    if signal_context.get("cohort_context_only"):
        takeaway += (
            " Cohort-defining filters (handedness, year windows, etc.) are context — "
            "not equal to career totals, awards, or position-relative excellence."
        )

    case_evidence = list(signal_context.get("case_evidence") or [])
    cohort_context_only = list(signal_context.get("cohort_context_only") or [])
    if filter_interp.get("sort_stat_note"):
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
            lines.append(f"- {item}")
    if memo.get("final_takeaway"):
        lines.append("")
        lines.append("#### Final takeaway")
        lines.append(str(memo["final_takeaway"]))
    if analysis.get("disclaimer"):
        lines.append("")
        lines.append(f"*{analysis['disclaimer']}*")
    return "\n".join(lines)
