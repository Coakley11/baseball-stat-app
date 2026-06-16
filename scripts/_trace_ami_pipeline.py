"""End-to-end AMI pipeline trace for the three real test questions.

Mirrors the live send path (build_submit_context order) then runs the actual
AMI solver (solve_suite_question from the sibling AMI repo). Prints every stage
so we can see exactly where the intended workflow becomes the wrong workflow.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AMI = ROOT.parent / "Applied-mathematical-intelligence"
sys.path.insert(0, str(ROOT))
if AMI.is_dir():
    sys.path.insert(0, str(AMI))

from applied_math_context import attach_question_player_to_context
from baseball_ami_pages import promote_page_ami_context_at_send

try:
    from components.applied_math_solvers import solve_suite_question
    from components.applied_math_problem_router import route_suite_question
    _HAVE_SOLVER = True
except Exception as exc:  # pragma: no cover
    print(f"!! AMI solver unavailable: {exc}")
    _HAVE_SOLVER = False


def _build_ctx(source_page: str, session: dict, question: str) -> dict:
    """Replicate build_submit_context's non-draft path for tracing."""
    ctx: dict = {
        "source_app": "baseball",
        "source_page": source_page,
        "page": source_page,
        "workflow": "baseball",
    }
    attach_question_player_to_context(ctx, question, session)
    promote_page_ami_context_at_send(ctx, session, source_page=source_page, question=question)
    return ctx


def _build_draft_ctx(session: dict, question: str) -> dict:
    from applied_math_context import (
        attach_draft_team_to_context,
        build_baseball_applied_math_context,
        finalize_draft_context_for_send,
    )
    ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
    ctx["source_app"] = "baseball"
    ctx["source_page"] = "Draft Assistant Simulator"
    ctx["page"] = "Draft Assistant Simulator"
    attach_question_player_to_context(ctx, question, session)
    finalize_draft_context_for_send(ctx, session)
    attach_draft_team_to_context(ctx, question, session)
    return ctx


def _report(label: str, question: str, ctx: dict) -> None:
    print("\n" + "=" * 72)
    print(f"{label}")
    print("=" * 72)
    print(f"Q: {question}")
    print("\n-- baseball-side ctx (entity / constraint / routing) --")
    for k in (
        "player", "player_a", "player_b", "players", "question_player",
        "intent", "routing_hint", "problem_type_hint", "trend_comparison_mode",
        "comparison_age_range", "comparison_season_range", "comparison_constraint_note",
        "historical_comparison", "draft_mode_hint", "draft_review_team",
    ):
        if k in ctx and ctx.get(k) not in (None, "", [], {}):
            print(f"   {k:28} = {ctx.get(k)!r}")
    ts = ctx.get("trend_summary")
    if isinstance(ts, dict):
        print(f"   trend_summary.player        = {ts.get('player')!r}")
    print(f"   category_diagnostics present = {bool(ctx.get('category_diagnostics'))}")
    print(f"   position_scarcity present    = {bool(ctx.get('position_scarcity_table') or ctx.get('position_scarcity'))}")
    ami_g = ctx.get("ami_guidance")
    if ami_g:
        print(f"   ami_guidance                 = {str(ami_g)[:90]}...")

    if not _HAVE_SOLVER:
        return
    route = route_suite_question(question, source_app="baseball", context=ctx)
    print("\n-- AMI route (solver-side workflow selection) --")
    print(f"   problem_type_id  = {route.problem_type_id}")
    print(f"   problem_type     = {route.problem_type}")
    print(f"   confidence       = {route.confidence}")
    print(f"   intent_restate   = {route.intent_restatement[:90]}")
    result = solve_suite_question(question, source_app="baseball", context=ctx)
    res = result[1] if isinstance(result, tuple) else result
    print("\n-- AMI rendered answer --")
    print(f"   short_answer = {(res.short_answer or '')[:240]}")
    print(f"   why          = {(res.why or '')[:240]}")


def trace_trend() -> None:
    # Stale chart shows A.J. Burnett (previously viewed). Question is a 2-player comparison.
    session = {
        "active_page": "Trend Value",
        "single_trend_dashboard_player": "A.J. Burnett",
        "single_trend_dashboard_stats": ["OPS"],
        "_ami_trend_summary": {"player": "A.J. Burnett", "stat": "HR", "slope": 0.4, "r2": 0.6},
        "_ami_trend_snapshot": {"player": "A.J. Burnett", "metrics": ["OPS"]},
    }
    q = "Is Kameron Misner a better pick than Stone Garrett even though he has a lower trend in OPS?"
    ctx = _build_ctx("Trend Value", session, q)
    _report("PRIORITY 2 — TREND VALUE (A.J. Burnett injection?)", q, ctx)


def trace_comparison() -> None:
    session = {
        "active_page": "Comparison Tool",
        "compare_players": ["Juan Soto", "Ken Griffey Jr."],
    }
    q = "Was Soto a better player than Griffey between ages 19-27?"
    ctx = _build_ctx("Comparison Tool", session, q)
    _report("PRIORITY 3 — COMPARISON TOOL (age range applied?)", q, ctx)


def trace_draft() -> None:
    try:
        from ami_acceptance_harness import build_realistic_draft_assistant_session
        session = build_realistic_draft_assistant_session()
    except Exception as exc:
        print(f"\n(draft session fixture unavailable: {exc}; using minimal session)")
        session = {
            "active_page": "Draft Assistant Simulator",
            "room_your_team": "Daniel",
        }
    q = "What is Daniel's biggest statistical and position weakness in this draft?"
    ctx = _build_draft_ctx(session, q)
    _report("PRIORITY 4 — DRAFT ASSISTANT (roster_needs survives?)", q, ctx)


def main() -> None:
    trace_trend()
    trace_comparison()
    trace_draft()


if __name__ == "__main__":
    main()
