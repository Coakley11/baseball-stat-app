"""Command Center activity for Hall of Fame Case Mode."""

from __future__ import annotations

import re
from typing import Any


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return s or "player"


def log_hof_case_analysis_submitted(
    session: dict[str, Any] | None,
    *,
    target_player: str,
    packet: dict[str, Any],
    question_id: str = "",
) -> None:
    try:
        from suite_activity_client import record_activity
    except ImportError:
        return
    target = str(target_player or "").strip()
    metrics = {
        "activity_type": "hof_case_analysis_submitted",
        "feature": "Hall of Fame Case Mode",
        "target_player": target,
        "total_players_returned": packet.get("total_players_returned"),
        "hall_of_famers_returned": packet.get("hall_of_famers_returned"),
        "hall_of_fame_rate_pct": packet.get("hall_of_fame_rate_pct"),
        "target_rank": packet.get("target_rank"),
        "sort_stat": packet.get("sort_stat"),
    }
    if question_id:
        metrics["question_id"] = question_id
    record_activity(
        "baseball",
        "hof_case_analysis_submitted",
        page="Career Totals",
        metrics=metrics,
        summary=f"Hall of Fame case analysis — {target}",
        resume_key=f"bb:hof_case:{_slug(target)}",
        resume_title="Review Hall of Fame Case",
        resume_subtitle=target,
    )
