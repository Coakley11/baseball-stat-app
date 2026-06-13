"""Answer quality audit — would a fantasy player find this useful and believable?

Evaluates nine dimensions for each question family:
  1. Factual grounding
  2. Answers the actual question
  3. Uses page context
  4. Uses draft context (when relevant)
  5. Provides a recommendation
  6. Explains why
  7. Compares alternatives
  8. Avoids invented facts
  9. Player trustworthy (composite)

Usage:
  python ami_answer_quality_audit.py
  python ami_answer_quality_audit.py --save docs/ami_answer_quality_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ami_audit_common import (
    ALTERNATIVE_WORDS,
    check_compares_alternatives,
    check_explains_why,
    check_forbidden_names,
    check_has_evidence,
    check_names_present,
    check_no_generic_filler,
    check_not_recommending_drafted,
    check_pick_round_grounding,
    check_recommends,
    check_scarcity_has_players,
    context_blob,
    context_pick_round,
    direct_answer_text,
    drafted_names,
    pool_player_names,
    solver_text,
)

ROOT = Path(__file__).resolve().parent
AMI_REPO = ROOT.parent / "applied-mathematical-intelligence"


@dataclass
class QualityDimension:
    id: str
    label: str
    passed: bool
    note: str = ""


@dataclass
class QualityCase:
    case_id: str
    category: str
    page: str
    question: str
    scenario: str
    uses_draft_context: bool = False
    required_names: tuple[str, ...] = ()
    forbidden_names: tuple[str, ...] = ()
    question_themes: tuple[str, ...] = ()
    must_recommend: bool = True
    must_explain: bool = True
    must_compare: bool = False
    must_name_players: bool = False
    allow_insufficient_data: bool = False


@dataclass
class QualityResult:
    case_id: str
    category: str
    question: str
    passed: bool = False
    player_trustworthy: bool = False
    dimensions: list[QualityDimension] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    route_id: str = ""
    draft_mode: str = ""
    short_answer: str = ""


QUALITY_CASES: list[QualityCase] = [
    QualityCase(
        "next_catcher",
        "Next catcher",
        "Draft Assistant Simulator",
        "Who is likely to be the next catcher picked in this draft?",
        "draft_market",
        uses_draft_context=True,
        required_names=("contreras", "catcher"),
        forbidden_names=("julio rodriguez",),
        question_themes=("catcher", "next", "likely"),
        must_recommend=False,
        must_name_players=True,
        must_compare=True,
    ),
    QualityCase(
        "position_run",
        "Position run",
        "Draft Assistant Simulator",
        "Is a catcher run coming?",
        "draft_market",
        uses_draft_context=True,
        required_names=("catcher",),
        question_themes=("run", "catcher"),
        must_recommend=False,
        must_name_players=True,
    ),
    QualityCase(
        "make_it_back",
        "Make it back to me",
        "Live Draft Room",
        "Will William Contreras make it back to me?",
        "make_it_back",
        uses_draft_context=True,
        required_names=("contreras",),
        question_themes=("make it back", "contreras", "pick"),
        must_recommend=False,
    ),
    QualityCase(
        "wait_on_player",
        "Wait on player",
        "Draft Assistant Simulator",
        "How long can I wait on catcher?",
        "draft_market",
        uses_draft_context=True,
        required_names=("catcher", "wait"),
        question_themes=("wait", "catcher", "round"),
        must_recommend=True,
    ),
    QualityCase(
        "olson_vs_schwarber",
        "Olson vs Schwarber",
        "Draft Assistant Simulator",
        "Which player would be better to draft, Matt Olson or Kyle Schwarber?",
        "draft_compare",
        uses_draft_context=True,
        required_names=("olson", "schwarber"),
        forbidden_names=("juan soto", "aaron judge", "bobby witt", "julio rodriguez"),
        question_themes=("olson", "schwarber", "better", "draft"),
        must_compare=True,
    ),
    QualityCase(
        "jose_ramirez",
        "Jose Ramirez",
        "Draft Assistant Simulator",
        "Why is Jose Ramirez the best player to draft for me right now?",
        "jose_ramirez",
        uses_draft_context=True,
        required_names=("jose ramirez",),
        question_themes=("ramirez", "fit", "board"),
        must_explain=True,
    ),
    QualityCase(
        "team_needs",
        "Team needs",
        "Draft Assistant Simulator",
        "What does my roster need?",
        "team_needs",
        uses_draft_context=True,
        question_themes=("need", "roster", "position", "category"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "hitter_vs_pitcher",
        "Hitter vs pitcher",
        "Draft Assistant Simulator",
        "Should I take a hitter or pitcher?",
        "hitter_pitcher",
        uses_draft_context=True,
        required_names=("hitter", "pitcher"),
        question_themes=("hitter", "pitcher"),
        must_recommend=True,
        must_compare=True,
    ),
    QualityCase(
        "best_values",
        "Best values available",
        "Draft Assistant Simulator",
        "Who are the best values left?",
        "best_values",
        uses_draft_context=True,
        question_themes=("value", "best", "available"),
        must_name_players=True,
        must_recommend=True,
    ),
    QualityCase(
        "sleepers",
        "Sleepers",
        "Fantasy Sleepers & Busts",
        "Should I take this sleeper?",
        "sleepers",
        uses_draft_context=False,
        required_names=("sleeper",),
        question_themes=("sleeper", "take", "upside"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "trend_interpretation",
        "Trend interpretation",
        "Trend Value",
        "This player has a good trend. Is he likely to do well next season in doubles?",
        "trend",
        required_names=("trend",),
        question_themes=("trend", "slope", "meaningful", "significant", "2b", "double"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "historical_filters",
        "Historical filter interpretation",
        "Historical Explorer",
        "Why does Barry Bonds keep showing up with these filters?",
        "historical",
        required_names=("bonds",),
        question_themes=("bonds", "filter", "historical"),
        must_recommend=False,
        must_explain=True,
    ),
    QualityCase(
        "comparison_power",
        "Comparison (power)",
        "Comparison Tool",
        "Which player is more valuable for power?",
        "comparison",
        required_names=("juan soto", "aaron judge"),
        forbidden_names=("julio rodriguez",),
        question_themes=("power", "lead", "score", "hr"),
        must_recommend=True,
        must_compare=True,
    ),
    QualityCase(
        "comparison_why",
        "Comparison (why better)",
        "Comparison Tool",
        "Why is Juan Soto better than Aaron Judge?",
        "comparison",
        required_names=("juan soto", "aaron judge"),
        question_themes=("soto", "judge", "better", "lead"),
        must_recommend=True,
        must_explain=True,
        must_compare=True,
    ),
]


def _ensure_ami() -> None:
    path = str(AMI_REPO)
    if path not in sys.path:
        sys.path.insert(0, path)


def _scenario_context(case: QualityCase) -> dict[str, Any]:
    from ami_acceptance_harness import (
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

    sc = case.scenario
    if sc == "draft_market":
        _, ctx = build_draft_market_catcher_context()
        return dict(ctx)
    if sc == "make_it_back":
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
    if sc == "draft_compare":
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
    if sc == "jose_ramirez":
        _, ctx = build_jose_ramirez_question_context()
        return dict(ctx)
    if sc == "team_needs":
        return dict(build_realistic_draft_assistant_session()["_acceptance_ctx"])
    if sc == "hitter_pitcher":
        _, ctx = build_draft_category_context()
        return dict(ctx)
    if sc == "best_values":
        session = build_realistic_draft_assistant_session()
        ctx = dict(session["_acceptance_ctx"])
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        values = [
            {"player": "Kyle Schwarber", "Primary Position": "OF", "Market Rank": 18, "Fantasy Edge": 12},
            {"player": "Matt Olson", "Primary Position": "1B", "Market Rank": 30, "Fantasy Edge": 22},
            {"player": "Eugenio Suarez", "Primary Position": "3B", "Market Rank": 59, "Fantasy Edge": 43},
        ]
        snap["best_available_players"] = values
        snap["available_players"] = values
        ctx["draft_snapshot"] = snap
        ctx["best_available"] = values
        ctx["available_players"] = values
        return ctx
    if sc == "sleepers":
        return dict(build_realistic_sleepers_session()["_acceptance_ctx"])
    if sc == "trend":
        tv = build_realistic_trend_valuation_session()
        ctx = dict(tv["_trend_ctx"])
        ctx["trend_summary"] = {
            "player": "Junior Caminero",
            "stat": "2B",
            "slope": 1.8,
            "r2": 0.55,
            "direction": "Up",
            "delta": 6,
        }
        ctx["player"] = "Junior Caminero"
        ctx["metrics"] = ["2B"]
        return ctx
    if sc == "historical":
        return dict(build_realistic_historical_session()["_acceptance_ctx"])
    if sc == "comparison":
        return dict(build_realistic_comparison_session()["_acceptance_ctx"])
    return dict(build_realistic_draft_assistant_session()["_acceptance_ctx"])


def evaluate_answer_quality(
    case: QualityCase,
    ctx: dict[str, Any],
    answer: str,
) -> QualityResult:
    """Score one answer against fantasy-player usefulness criteria."""
    row = QualityResult(case_id=case.case_id, category=case.category, question=case.question)
    direct = direct_answer_text(answer)
    low = answer.lower()
    direct_low = direct.lower()
    failures: list[str] = []
    strengths: list[str] = []
    dims: list[QualityDimension] = []

    # 1. Factual grounding
    ground_failures = (
        check_pick_round_grounding(ctx, answer)
        + check_no_generic_filler(answer)
        + check_not_recommending_drafted(ctx, answer)
    )
    if case.must_name_players:
        pool = pool_player_names(ctx)
        ground_failures.extend(check_scarcity_has_players(answer, pool))
    dim1 = QualityDimension(
        "factual_grounding",
        "Is the answer factually grounded?",
        not ground_failures,
        "; ".join(ground_failures[:2]) or "Pick/round and availability align with context",
    )
    dims.append(dim1)
    failures.extend(ground_failures)

    # 2. Answers the actual question
    theme_missing = [t for t in case.question_themes if t.lower() not in low]
    answers_q = len(theme_missing) <= max(1, len(case.question_themes) // 3)
    dim2 = QualityDimension(
        "answers_question",
        "Does it answer the actual question?",
        answers_q,
        f"Missing themes: {theme_missing}" if not answers_q else "Addresses question themes",
    )
    dims.append(dim2)
    if not answers_q:
        failures.append(f"Does not address question themes: {theme_missing}")

    # 3. Uses page context
    page_key = case.page.lower().split()[0]
    page_markers = {
        "draft": ("draft_snapshot", "recommended_players", "available_players", "roster"),
        "live": ("draft_snapshot", "current_pick"),
        "fantasy": ("sleeper_candidates", "sleepers_snapshot"),
        "trend": ("trend_summary", "player"),
        "historical": ("historical_snapshot", "filters_applied"),
        "comparison": ("player_a", "player_b", "comparison_stats"),
        "valuation": ("valuation_snapshot",),
    }
    markers = page_markers.get(page_key, ())
    blob = context_blob(ctx)
    uses_page = any(m.lower() in blob or ctx.get(m) for m in markers) if markers else bool(blob)
    answer_uses_page = check_has_evidence(answer) or bool(case.required_names and not theme_missing)
    dim3 = QualityDimension(
        "uses_page_context",
        "Does it use the page context?",
        uses_page and answer_uses_page,
        "Context present and answer cites page evidence" if uses_page and answer_uses_page else "Weak page-context use",
    )
    dims.append(dim3)
    if not (uses_page and answer_uses_page):
        failures.append("Answer does not convincingly use page context")

    # 4. Draft context when relevant
    if case.uses_draft_context:
        pick, rnd = context_pick_round(ctx)
        draft_blob_ok = "draft_snapshot" in blob or pick is not None or pool_player_names(ctx)
        draft_answer_ok = (
            pick is not None
            and (f"pick **{pick}**" in answer or f"pick {pick}" in low or "pick and round not" in low)
        ) or pool_player_names(ctx) and any(n.lower() in low for n in pool_player_names(ctx)[:3])
        dim4 = QualityDimension(
            "uses_draft_context",
            "Does it use draft context when relevant?",
            draft_blob_ok and draft_answer_ok,
            "Draft board/pick evidence in answer" if draft_blob_ok and draft_answer_ok else "Draft context underused",
        )
    else:
        dim4 = QualityDimension("uses_draft_context", "Does it use draft context when relevant?", True, "N/A")
    dims.append(dim4)
    if case.uses_draft_context and not dim4.passed:
        failures.append("Draft context not reflected in answer")

    # 5. Recommendation
    rec = check_recommends(direct) if case.must_recommend else True
    dim5 = QualityDimension(
        "provides_recommendation",
        "Does it provide a recommendation?",
        rec,
        "Clear take/lean" if rec else "No actionable recommendation",
    )
    dims.append(dim5)
    if case.must_recommend and not rec:
        failures.append("No clear recommendation for a decision question")

    # 6. Explains why
    why = check_explains_why(answer) if case.must_explain else True
    dim6 = QualityDimension(
        "explains_why",
        "Does it explain why?",
        why,
        "Evidence-based reasoning present" if why else "Conclusion without explanation",
    )
    dims.append(dim6)
    if case.must_explain and not why:
        failures.append("Conclusion without evidence-based why")

    # 7. Compare alternatives
    alt = check_compares_alternatives(answer) if case.must_compare else True
    dim7 = QualityDimension(
        "compares_alternatives",
        "Does it compare alternatives?",
        alt,
        "Alternatives or tradeoffs mentioned" if alt else "No alternatives discussed",
    )
    dims.append(dim7)
    if case.must_compare and not alt:
        failures.append("Does not compare alternatives")

    # 8. Avoids invented facts
    invented = check_pick_round_grounding(ctx, answer) + check_no_generic_filler(answer)
    if case.required_names:
        invented.extend(check_names_present(direct, case.required_names, full_text=answer))
    dim8 = QualityDimension(
        "avoids_invented_facts",
        "Does it avoid invented facts?",
        not invented,
        "; ".join(invented[:2]) or "No invented pick/filler detected",
    )
    dims.append(dim8)

    # Required / forbidden names (use full answer for comparisons — direct line may only name winner)
    name_src = direct if case.forbidden_names else answer
    failures.extend(check_names_present(name_src, case.required_names, full_text=answer))
    failures.extend(check_forbidden_names(answer, case.forbidden_names))

    # 9. Player trustworthy — composite
    critical = [d for d in dims if d.id in ("factual_grounding", "answers_question", "avoids_invented_facts")]
    trustworthy = all(d.passed for d in critical) and check_has_evidence(answer)
    if case.must_recommend:
        trustworthy = trustworthy and rec
    if case.must_explain:
        trustworthy = trustworthy and why
    dim9 = QualityDimension(
        "player_trustworthy",
        "Would a fantasy player trust this answer?",
        trustworthy,
        "Believable and useful" if trustworthy else "Would not pass knowledgeable-player sniff test",
    )
    dims.append(dim9)

    if trustworthy:
        strengths.append("Passes fantasy-player trust bar")
    if check_has_evidence(answer):
        strengths.append("Cites measurable evidence")

    row.dimensions = dims
    row.failures = list(dict.fromkeys(failures))
    row.strengths = strengths
    row.player_trustworthy = trustworthy
    row.passed = trustworthy and not row.failures
    return row


def audit_case_by_id(case_id: str, ctx: dict[str, Any], question: str, answer: str) -> QualityResult | None:
    for case in QUALITY_CASES:
        if case.case_id == case_id:
            q = QualityCase(**{**asdict(case), "question": question})
            return evaluate_answer_quality(q, ctx, answer)
    return None


def run_answer_quality_audit() -> dict[str, Any]:
    _ensure_ami()
    from components.applied_math_solvers import solve_suite_question

    results: list[QualityResult] = []
    for case in QUALITY_CASES:
        ctx = _scenario_context(case)
        ctx["page"] = case.page
        route, solved = solve_suite_question(case.question, source_app="baseball", context=ctx)
        text = solver_text(solved)
        row = evaluate_answer_quality(case, ctx, text)
        row.route_id = str(getattr(route, "problem_type_id", "") or "")
        row.draft_mode = str((getattr(solved, "computed", {}) or {}).get("draft_mode") or "")
        row.short_answer = str(getattr(solved, "short_answer", "") or "")[:220]
        results.append(row)

    passed = sum(1 for r in results if r.passed)
    trustworthy = sum(1 for r in results if r.player_trustworthy)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "criteria": [
            "factual_grounding",
            "answers_question",
            "uses_page_context",
            "uses_draft_context",
            "provides_recommendation",
            "explains_why",
            "compares_alternatives",
            "avoids_invented_facts",
            "player_trustworthy",
        ],
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "player_trustworthy": trustworthy,
            "ready_for_manual_acceptance": passed == len(results),
        },
        "results": [
            {
                **asdict(r),
                "dimensions": [asdict(d) for d in r.dimensions],
            }
            for r in results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AMI answer quality audit")
    parser.add_argument("--save", default=str(ROOT / "docs" / "ami_answer_quality_report.json"))
    args = parser.parse_args()
    report = run_answer_quality_audit()
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    s = report["summary"]
    print(f"Answer quality audit: {s['passed']}/{s['total']} passed · trustworthy={s['player_trustworthy']}")
    print(f"Saved: {out}")
    for row in report["results"]:
        status = "PASS" if row["passed"] else "FAIL"
        trust = "trust" if row["player_trustworthy"] else "no-trust"
        print(f"  [{status}/{trust}] {row['case_id']}: {row['category']}")
        for f in row["failures"][:4]:
            print(f"         - {f}")
    if s["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
