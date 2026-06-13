"""Internal AMI hardening pass — question families across Baseball pages.

Validates the five-stage pipeline before manual user acceptance:
  A. Baseball sent the right data
  B. AMI classified the question correctly (route)
  C. AMI chose the right resources (solver mode / problem type)
  D. AMI reasoned from the data (answer cites context)
  E. AMI explained clearly (analyst structure)

Usage:
  python ami_hardening_pass.py
  python ami_hardening_pass.py --save docs/ami_hardening_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
AMI_REPO = ROOT.parent / "applied-mathematical-intelligence"

# Routes that indicate misclassification for draft-market / draft-flow questions.
_FORBIDDEN_MISROUTES = frozenset(
    {
        "baseball_future_accumulation",
        "baseball_generic",
    }
)

ANALYST_LEVELS: list[tuple[str, tuple[str, ...]]] = [
    ("direct_recommendation", ("recommend", "lean", "draft", "prioritize", "take", "target", "yes", "no")),
    ("why", ("why", "because", "fit", "need", "gap", "roster", "category")),
    ("scarcity", ("scarcity", "replacement", "tier", "thinning", "pool", "available")),
    ("risk_upside", ("risk", "upside", "variance", "floor", "ceiling", "volatil")),
    ("alternatives", ("alternative", "instead", "over", " vs ", "compare", "tradeoff")),
    ("what_if", ("what-if", "what if", "if you", "if your", "→", "priority")),
]


@dataclass
class HardeningCase:
    family_id: str
    page: str
    question: str
    expected_route: str
    expected_draft_mode: str = ""
    forbidden_routes: tuple[str, ...] = ()
    context_markers: tuple[str, ...] = ()
    answer_markers: tuple[str, ...] = ()
    forbidden_answer: tuple[str, ...] = ()
    min_analyst_levels: int = 3


@dataclass
class HardeningResult:
    family_id: str
    page: str
    question: str
    passed: bool = False
    stage_a_context: bool = False
    stage_b_route: bool = False
    stage_c_mode: bool = False
    stage_d_cites_data: bool = False
    stage_e_analyst: bool = False
    stage_f_grounded: bool = True
    stage_g_quality: bool = True
    player_trustworthy: bool = False
    route_id: str = ""
    draft_mode: str = ""
    missing_context: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    short_answer: str = ""
    notes: list[str] = field(default_factory=list)


QUESTION_FAMILIES: list[HardeningCase] = [
    # --- Draft Assistant ---
    HardeningCase(
        "draft_next_pick",
        "Draft Assistant Simulator",
        "Who should I draft next?",
        "baseball_draft_decision",
        "next_pick",
        context_markers=("draft_snapshot", "recommended_players"),
        answer_markers=("draft", "roster", "cal raleigh"),
    ),
    HardeningCase(
        "draft_roster_needs",
        "Draft Assistant Simulator",
        "What does my roster need?",
        "baseball_draft_decision",
        "roster_needs",
        context_markers=("needed_positions", "category_needs"),
        answer_markers=("c", "ss", "need"),
    ),
    HardeningCase(
        "draft_category_steals",
        "Draft Assistant Simulator",
        "Should I prioritize steals right now based on my draft?",
        "baseball_draft_decision",
        "category",
        context_markers=("category_needs", "available_players"),
        answer_markers=("sb", "steal", "category", "speed"),
    ),
    HardeningCase(
        "draft_hitter_pitcher",
        "Draft Assistant Simulator",
        "Should I take a hitter or pitcher?",
        "baseball_draft_decision",
        "hitter_pitcher",
        context_markers=("draft_snapshot", "roster"),
        answer_markers=("hitter", "pitcher"),
    ),
    HardeningCase(
        "draft_market_next_catcher",
        "Draft Assistant Simulator",
        "Who is likely to be the next catcher picked in this draft?",
        "baseball_draft_decision",
        "draft_market_prediction",
        forbidden_routes=("baseball_future_accumulation",),
        context_markers=("draft_snapshot", "drafted_players"),
        answer_markers=("cal raleigh", "contreras", "catcher"),
        forbidden_answer=("julio rodriguez", "no clear remaining", "pick 19", "pick **19**"),
    ),
    HardeningCase(
        "draft_compare_olson_schwarber",
        "Draft Assistant Simulator",
        "Which player would be better to draft, Matt Olson or Kyle Schwarber?",
        "baseball_draft_decision",
        "draft_player_compare",
        context_markers=("draft_snapshot", "available_players"),
        answer_markers=("olson", "schwarber"),
        forbidden_answer=("juan soto", "aaron judge", "julio rodriguez", "attach ops"),
    ),
    HardeningCase(
        "draft_player_why",
        "Draft Assistant Simulator",
        "Why is Jose Ramirez the best player to draft for me right now?",
        "baseball_draft_decision",
        "player_why",
        context_markers=("question_player", "draft_snapshot"),
        answer_markers=("jose ramirez", "cal raleigh", "fit"),
    ),
    HardeningCase(
        "draft_weakest_category",
        "Draft Assistant Simulator",
        "Which category am I weakest in?",
        "baseball_draft_decision",
        "weakest_category",
        context_markers=("category_needs",),
        answer_markers=("category", "need", "sb", "hr"),
    ),
    HardeningCase(
        "draft_safety_upside",
        "Draft Assistant Simulator",
        "Who is safest vs highest upside?",
        "baseball_draft_decision",
        "safety_upside",
        context_markers=("recommended_players",),
        answer_markers=("safe", "upside", "risk", "floor", "ceiling"),
    ),
    # --- Live Draft ---
    HardeningCase(
        "live_on_clock",
        "Live Draft Room",
        "I'm on the clock. Who should I take?",
        "baseball_draft_decision",
        "next_pick",
        context_markers=("draft_snapshot", "current_pick"),
        answer_markers=("draft", "pick"),
    ),
    HardeningCase(
        "live_make_it_back",
        "Live Draft Room",
        "Will William Contreras make it back to me?",
        "baseball_draft_decision",
        "draft_market_prediction",
        forbidden_routes=("baseball_future_accumulation",),
        context_markers=("draft_snapshot",),
        answer_markers=("next pick", "contreras", "drafted before"),
    ),
    # --- Sleepers ---
    HardeningCase(
        "sleepers_take",
        "Fantasy Sleepers & Busts",
        "Should I take this sleeper?",
        "baseball_draft_decision",
        "sleeper",
        context_markers=("sleeper_candidates",),
        answer_markers=("junior caminero", "sleeper", "upside"),
    ),
    # --- Trend ---
    HardeningCase(
        "trend_forecast",
        "Trend Value",
        "This player has a good trend. Is he likely to do well next season in doubles?",
        "baseball_trend_significance",
        forbidden_routes=("baseball_future_accumulation", "baseball_generic"),
        context_markers=("trend_summary", "player"),
        answer_markers=("slope", "trend", "r²", "r2", "2b", "double"),
    ),
    # --- Valuation ---
    HardeningCase(
        "valuation_over_under",
        "Valuation",
        "Is this player overvalued or undervalued?",
        "baseball_valuation",
        context_markers=("valuation_snapshot", "top_valuation_players"),
        answer_markers=("valuation", "score", "over", "under"),
    ),
    # --- Comparison ---
    HardeningCase(
        "compare_power",
        "Comparison Tool",
        "Which player is more valuable for power?",
        "baseball_player_comparison",
        context_markers=("player_a", "player_b", "comparison_stats"),
        answer_markers=("juan soto", "aaron judge", "hr", "power"),
        min_analyst_levels=2,
    ),
    HardeningCase(
        "compare_why_better",
        "Comparison Tool",
        "Why is Juan Soto better than Aaron Judge?",
        "baseball_player_comparison",
        context_markers=("player_a", "player_b"),
        answer_markers=("better", "compare", "soto", "judge"),
        min_analyst_levels=2,
    ),
    # --- Historical ---
    HardeningCase(
        "historical_bonds",
        "Historical Explorer",
        "Why does Barry Bonds keep showing up with these filters?",
        "baseball_historical_comparison",
        context_markers=("historical_snapshot", "filters_applied"),
        answer_markers=("bonds", "hr", "filter", "outlier"),
        min_analyst_levels=2,
    ),
]


QUALITY_BY_FAMILY: dict[str, str] = {
    "draft_market_next_catcher": "next_catcher",
    "draft_compare_olson_schwarber": "olson_vs_schwarber",
    "draft_player_why": "jose_ramirez",
    "draft_roster_needs": "team_needs",
    "draft_hitter_pitcher": "hitter_vs_pitcher",
    "live_make_it_back": "make_it_back",
    "sleepers_take": "sleepers",
    "trend_forecast": "trend_interpretation",
    "historical_bonds": "historical_filters",
    "compare_power": "comparison_power",
    "compare_why_better": "comparison_why",
}


def _ensure_ami_import() -> None:
    if not AMI_REPO.is_dir():
        raise SystemExit(f"Applied Intelligence repo not found: {AMI_REPO}")
    ami_path = str(AMI_REPO)
    if ami_path not in sys.path:
        sys.path.insert(0, ami_path)


def _scenario_for_family(case: HardeningCase) -> dict[str, Any]:
    from ami_acceptance_harness import (
        audit_page_context,
        build_draft_category_context,
        build_draft_market_catcher_context,
        build_jose_ramirez_question_context,
        build_realistic_comparison_session,
        build_realistic_draft_assistant_session,
        build_realistic_historical_session,
        build_realistic_live_draft_session,
        build_realistic_sleepers_session,
        build_realistic_trend_valuation_session,
    )

    fid = case.family_id
    if fid == "draft_compare_olson_schwarber":
        session = build_realistic_draft_assistant_session()
        from applied_math_context import attach_question_player_to_context, build_baseball_applied_math_context

        ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
        rows = [
            {"player": "Matt Olson", "Primary Position": "1B", "Market Rank": 30, "Fantasy Edge": 22},
            {"player": "Kyle Schwarber", "Primary Position": "OF", "Market Rank": 18, "Fantasy Edge": 12},
        ]
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        snap["available_players"] = rows
        snap["current_pick"] = 8
        snap["draft_round"] = 1
        ctx["draft_snapshot"] = snap
        ctx["available_players"] = rows
        ctx["current_pick"] = 8
        ctx["draft_round"] = 1
        attach_question_player_to_context(ctx, case.question, session)
        return ctx
    if fid == "draft_player_why":
        _, ctx = build_jose_ramirez_question_context()
        return dict(ctx)
    if fid == "live_on_clock":
        return dict(build_realistic_live_draft_session()["_acceptance_ctx"])
    if fid.startswith("draft_market"):
        _, ctx = build_draft_market_catcher_context()
        return dict(ctx)
    if fid == "live_make_it_back":
        session = build_realistic_live_draft_session()
        ctx = dict(session["_acceptance_ctx"])
        _, market_ctx = build_draft_market_catcher_context()
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        market_snap = market_ctx.get("draft_snapshot") if isinstance(market_ctx.get("draft_snapshot"), dict) else {}
        snap.update(market_snap)
        ctx["draft_snapshot"] = snap
        ctx["drafted_players"] = market_ctx.get("drafted_players")
        from applied_math_context import attach_question_player_to_context

        attach_question_player_to_context(ctx, case.question, session)
        return ctx
    if fid in ("draft_category_steals", "draft_hitter_pitcher", "draft_weakest_category", "draft_safety_upside"):
        _, ctx = build_draft_category_context()
        return dict(ctx)
    if fid == "sleepers_take":
        return dict(build_realistic_sleepers_session()["_acceptance_ctx"])
    if fid == "trend_forecast":
        tv = build_realistic_trend_valuation_session()
        ctx = dict(tv["_trend_ctx"])
        ctx["trend_summary"] = ctx.get("trend_summary") or {
            "player": "Junior Caminero",
            "stat": "2B",
            "slope": 1.8,
            "r2": 0.55,
            "direction": "Up",
            "delta": 6,
        }
        ctx["metrics"] = ["2B"]
        ctx["player"] = "Junior Caminero"
        return ctx
    if fid == "valuation_over_under":
        tv = build_realistic_trend_valuation_session()
        return dict(tv["_valuation_ctx"])
    if fid == "compare_power" or fid == "compare_why_better":
        return dict(build_realistic_comparison_session()["_acceptance_ctx"])
    if fid == "historical_bonds":
        return dict(build_realistic_historical_session()["_acceptance_ctx"])
    return dict(build_realistic_draft_assistant_session()["_acceptance_ctx"])


def _solver_text(result: Any) -> str:
    parts = [
        str(getattr(result, "short_answer", "") or ""),
        str(getattr(result, "why", "") or ""),
        str(getattr(result, "interpretation", "") or ""),
        str(getattr(result, "sensitivity_plain", "") or ""),
    ]
    coach = (getattr(result, "computed", None) or {}).get("coach_sections")
    if isinstance(coach, dict):
        for key in ("direct_answer", "analyst_framing", "tradeoffs", "formatted_answer"):
            parts.append(str(coach.get(key) or ""))
    return "\n".join(p for p in parts if p.strip())


def _analyst_levels(text: str) -> int:
    low = text.lower()
    return sum(1 for _, kws in ANALYST_LEVELS if any(k in low for k in kws))


def _context_has_markers(ctx: dict[str, Any], markers: tuple[str, ...]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    blob = json.dumps(ctx, default=str).lower()
    for m in markers:
        if m.lower() not in blob and not ctx.get(m):
            missing.append(m)
    return not missing, missing


def run_hardening_pass() -> dict[str, Any]:
    _ensure_ami_import()
    from ami_acceptance_harness import audit_page_context

    from ami_grounded_answer_audit import audit_draft_compare_olson_schwarber, audit_draft_market_catcher
    from ami_answer_quality_audit import QUALITY_CASES, evaluate_answer_quality

    from components.applied_math_solvers import solve_suite_question

    from suite_deploy_marker import GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

    results: list[HardeningResult] = []
    for case in QUESTION_FAMILIES:
        ctx = _scenario_for_family(case)
        ctx["page"] = case.page
        ctx.setdefault("source_app", "Baseball")

        row = HardeningResult(family_id=case.family_id, page=case.page, question=case.question)

        audit = audit_page_context(ctx, case.page)
        row.missing_context = [a.key for a in audit if not a.present]
        row.stage_a_context = not row.missing_context
        if case.context_markers:
            ok, miss = _context_has_markers(ctx, case.context_markers)
            if not ok:
                row.stage_a_context = False
                row.missing_context.extend(miss)

        route, solved = solve_suite_question(case.question, source_app="baseball", context=ctx)
        row.route_id = str(getattr(route, "problem_type_id", "") or "")
        row.draft_mode = str((getattr(solved, "computed", {}) or {}).get("draft_mode") or "")
        text = _solver_text(solved)
        row.short_answer = str(getattr(solved, "short_answer", "") or "")[:200]
        low = text.lower()

        row.stage_b_route = row.route_id == case.expected_route
        if case.forbidden_routes and row.route_id in case.forbidden_routes:
            row.stage_b_route = False
            row.failures.append(f"Misrouted to {row.route_id}")

        if case.expected_draft_mode:
            row.stage_c_mode = row.draft_mode == case.expected_draft_mode
        else:
            row.stage_c_mode = row.stage_b_route

        if case.answer_markers:
            row.stage_d_cites_data = any(m.lower() in low for m in case.answer_markers)
        else:
            row.stage_d_cites_data = len(text) > 40

        for bad in case.forbidden_answer:
            if bad.lower() in low:
                row.stage_d_cites_data = False
                row.failures.append(f"Answer incorrectly cited {bad}")

        generic_phrases = ("attach draft_snapshot", "without context", "consult expert rankings")
        if any(p in low for p in generic_phrases):
            row.stage_d_cites_data = False
            row.failures.append("Answer looks generic")

        if case.expected_route == "baseball_draft_decision":
            row.stage_e_analyst = _analyst_levels(text) >= case.min_analyst_levels
        else:
            row.stage_e_analyst = len(text) > 30 and row.stage_d_cites_data

        row.stage_f_grounded = True
        if case.family_id == "draft_market_next_catcher":
            ga = audit_draft_market_catcher(case.question, ctx, text, thin_context=False)
            row.stage_f_grounded = ga.passed
            if not ga.passed:
                row.failures.extend(ga.failures)
        elif case.family_id == "draft_compare_olson_schwarber":
            ga = audit_draft_compare_olson_schwarber(case.question, ctx, text)
            row.stage_f_grounded = ga.passed
            if not ga.passed:
                row.failures.extend(ga.failures)

        quality_id = QUALITY_BY_FAMILY.get(case.family_id)
        if quality_id:
            qcase = next((c for c in QUALITY_CASES if c.case_id == quality_id), None)
            if qcase:
                qa = evaluate_answer_quality(qcase, ctx, text)
                row.stage_g_quality = qa.player_trustworthy
                row.player_trustworthy = qa.player_trustworthy
                if not qa.player_trustworthy:
                    row.failures.extend(qa.failures[:4])

        if not row.stage_a_context:
            row.failures.append(f"Missing context: {row.missing_context[:5]}")
        if not row.stage_b_route:
            row.failures.append(f"Expected route {case.expected_route}, got {row.route_id}")
        if case.expected_draft_mode and not row.stage_c_mode:
            row.failures.append(f"Expected mode {case.expected_draft_mode}, got {row.draft_mode}")
        if not row.stage_d_cites_data:
            row.failures.append(f"Answer missing markers {case.answer_markers}")
        if not row.stage_e_analyst:
            if case.expected_route == "baseball_draft_decision":
                row.failures.append(
                    f"Fewer than {case.min_analyst_levels} analyst structure levels detected"
                )
            else:
                row.failures.append("Answer too thin for quantitative explanation")
        if not row.stage_f_grounded:
            row.failures.append("Grounded answer audit failed")
        if not row.stage_g_quality:
            row.failures.append("Answer quality audit failed (fantasy-player trust bar)")

        row.passed = not row.failures
        row.notes.append(f"analyst_levels={_analyst_levels(text)}")
        results.append(row)

    passed = sum(1 for r in results if r.passed)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_label": SUITE_BUILD_LABEL,
        "commit": GIT_COMMIT_SHORT,
        "method": "question_family_hardening_pass",
        "pipeline_stages": [
            "A_context",
            "B_route",
            "C_mode",
            "D_cites_data",
            "E_analyst_structure",
            "F_grounded_answer",
            "G_answer_quality",
        ],
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "ready_for_manual_acceptance": passed == len(results),
        },
        "results": [asdict(r) for r in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AMI hardening pass across question families")
    parser.add_argument(
        "--save",
        default=str(ROOT / "docs" / "ami_hardening_report.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()
    report = run_hardening_pass()
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    s = report["summary"]
    print(f"AMI hardening pass: {s['passed']}/{s['total']} passed")
    print(f"Ready for manual acceptance: {s['ready_for_manual_acceptance']}")
    print(f"Saved: {out}")
    for row in report["results"]:
        status = "PASS" if row["passed"] else "FAIL"
        print(f"  [{status}] {row['family_id']}: {row['question'][:55]}")
        if row["failures"]:
            for f in row["failures"][:3]:
                print(f"         - {f}")


if __name__ == "__main__":
    main()
