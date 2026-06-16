"""Debug Tier 1 Q2 routing — roster weakness question."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AMI = ROOT.parent / "applied-mathematical-intelligence"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AMI))

from ami_acceptance_harness import build_realistic_draft_assistant_session
from applied_math_context import build_baseball_applied_math_context
from components.applied_math_problem_router import route_suite_question
from components.applied_math_question_intent import classify_question_intent
from components.applied_math_problem_interpreter import interpret_suite_question
from components.applied_math_solvers import _draft_question_mode, dispatch_solver

QUESTIONS = [
    "What's my biggest roster weakness right now?",
    "What is my biggest roster weakness?",
    "What does my roster need?",
]


def run_scenario(name: str, ctx: dict, q: str) -> None:
    route = route_suite_question(q, source_app="baseball", context=ctx)
    interp = interpret_suite_question(q, source_app="baseball", context=ctx)
    mode = _draft_question_mode(q)
    result = dispatch_solver(route, q, ctx)
    print("---", name)
    print("  route:", route.problem_type_id, route.problem_type, route.confidence)
    print("  interp:", interp.model_id, interp.math_purpose)
    print("  restatement:", interp.restatement[:100])
    print("  _draft_question_mode:", mode)
    print("  draft_mode:", (result.computed or {}).get("draft_mode"))
    print("  short:", (result.short_answer or "")[:160])
    print()


def main() -> None:
    session = build_realistic_draft_assistant_session()
    import copy

    for q in QUESTIONS:
        print("=" * 72)
        print("Q:", q)
        ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
        ctx["question"] = q
        intent = classify_question_intent(q)
        interp = interpret_suite_question(q, source_app="baseball", context=ctx)
        route = route_suite_question(q, source_app="baseball", context=ctx)
        mode = _draft_question_mode(q)
        print("  intent_id:", intent.intent_id)
        print("  interp.model_id:", interp.model_id)
        print("  interp.math_purpose:", interp.math_purpose)
        print("  interp.restatement:", interp.restatement)
        print("  route.problem_type_id:", route.problem_type_id)
        print("  route.problem_type:", route.problem_type)
        print("  route.confidence:", route.confidence)
        print("  _draft_question_mode:", mode)
        print("  draft_snapshot:", bool(ctx.get("draft_snapshot")))
        print("  needed_positions:", ctx.get("needed_positions"))
        print("  player_a:", ctx.get("player_a"))
        print("  player_b:", ctx.get("player_b"))
        result = dispatch_solver(route, q, ctx)
        print("  solver.problem_type_id:", result.problem_type_id)
        print("  solver.draft_mode:", (result.computed or {}).get("draft_mode"))
        print("  short_answer:", (result.short_answer or "")[:240])

    q = QUESTIONS[0]
    base = build_baseball_applied_math_context("Draft Assistant Simulator", session)
    base["question"] = q
    print("\n" + "=" * 72)
    print("MISSING-CONTEXT SCENARIOS for:", q)
    c = copy.deepcopy(base)
    c.pop("draft_snapshot", None)
    run_scenario("no_draft_snapshot", c, q)
    c = copy.deepcopy(base)
    c.pop("needed_positions", None)
    c.pop("category_needs", None)
    run_scenario("no_needed_positions", c, q)
    c = copy.deepcopy(base)
    c["player_a"] = "Cal Raleigh"
    c["player_b"] = "Bobby Witt Jr."
    run_scenario("with_player_a_b", c, q)
    c = copy.deepcopy(base)
    for k in list(c.keys()):
        if "draft" in k.lower() or k in ("needed_positions", "category_needs", "recommended_players", "roster"):
            c.pop(k, None)
    run_scenario("strip_all_draft_keys", c, q)
    c = copy.deepcopy(base)
    c["draft_snapshot"] = {}
    c.pop("needed_positions", None)
    c.pop("category_needs", None)
    c.pop("roster", None)
    run_scenario("empty_draft_snapshot_no_needs", c, q)
    c = copy.deepcopy(base)
    c.pop("player", None)
    c.pop("draft_queue", None)
    if isinstance(c.get("draft_snapshot"), dict):
        c["draft_snapshot"].pop("draft_queue", None)
    run_scenario("no_queue_no_player", c, q)


if __name__ == "__main__":
    main()
