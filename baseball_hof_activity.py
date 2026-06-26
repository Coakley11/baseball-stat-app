"""Command Center activity for Hall of Fame Case Mode."""

from __future__ import annotations

from typing import Any

from hall_of_fame_data import hof_case_target_slug


def log_hof_case_analysis_submitted(
    session: dict[str, Any] | None,
    *,
    target_player: str,
    packet: dict[str, Any],
    question_id: str = "",
    ami_insight_id: str = "",
    source_state: dict[str, Any] | None = None,
) -> None:
    try:
        from suite_activity_client import record_activity
    except ImportError:
        return
    target = str(target_player or "").strip()
    slug = hof_case_target_slug(target)
    filters_used = packet.get("filters_used") if isinstance(packet.get("filters_used"), dict) else {}
    metrics: dict[str, Any] = {
        "activity_type": "hof_case_analysis_submitted",
        "feature": "Hall of Fame Case Mode",
        "target_player": target,
        "hof_case_mode": True,
        "hof_case_target": target,
        "total_players_returned": packet.get("total_players_returned"),
        "hall_of_famers_returned": packet.get("hall_of_famers_returned"),
        "hall_of_fame_rate_pct": packet.get("hall_of_fame_rate_pct"),
        "target_rank": packet.get("target_rank"),
        "sort_stat": packet.get("sort_stat"),
        "primary_position": packet.get("primary_position"),
        "filters_used": filters_used,
        "hof_case_summary": packet.get("hof_case_summary"),
    }
    if question_id:
        metrics["question_id"] = question_id
        metrics["ami_question_id"] = question_id
        metrics["suite_ai_question_id"] = question_id
    if ami_insight_id:
        metrics["ami_insight"] = ami_insight_id
    if isinstance(source_state, dict) and source_state:
        metrics["hof_case_source_state"] = source_state
    try:
        from suite_deep_links import build_resume_action_url

        metrics["continue_url"] = build_resume_action_url(
            "baseball",
            resume_key=f"bb:hof_case:{slug}",
            page="Career Totals",
            metrics={
                "target_player": target,
                "hof_case_mode": True,
                "question_id": question_id,
            },
        )
    except ImportError:
        pass
    record_activity(
        "baseball",
        "hof_case_analysis_submitted",
        page="Career Totals",
        metrics=metrics,
        summary=f"Hall of Fame case analysis — {target}",
        resume_key=f"bb:hof_case:{slug}",
        resume_title="Review Hall of Fame Case",
        resume_subtitle=target,
    )
