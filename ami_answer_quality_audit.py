"""Answer quality audit — would a fantasy player find this useful and believable?

Primary bar (more important than routing alone):
  1. Did it understand the actual question?
  2. Did it use the correct page context?
  3. Did it use the draft board and roster when relevant?
  4. Did it use the available player pool when relevant?
  5. Did it mention real players and real data?
  6. Did it explain why?
  7. Did it compare alternatives when appropriate?
  8. Did it avoid generic filler?
  9. Would a knowledgeable fantasy baseball player trust the answer?

Pipeline tracked per case: A context → B route → C mode → D analysis → E clarity → F trust.

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
    family: str = ""
    uses_draft_context: bool = False
    uses_player_pool: bool = False
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
    family: str = ""
    passed: bool = False
    player_trustworthy: bool = False
    routing_only_pass: bool = False
    dimensions: list[QualityDimension] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    route_id: str = ""
    draft_mode: str = ""
    short_answer: str = ""
    pipeline: dict[str, Any] = field(default_factory=dict)


QUALITY_CASES: list[QualityCase] = [
    QualityCase(
        "next_catcher",
        "Next catcher",
        "Draft Assistant Simulator",
        "Who is likely to be the next catcher picked in this draft?",
        "draft_market",
        family="Draft Market",
        uses_draft_context=True,
        uses_player_pool=True,
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
        family="Draft Market",
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
        family="Draft Market",
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
        family="Draft Market",
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
        family="Player Evaluation",
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
        family="Player Evaluation",
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
        family="Draft Assistant",
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
        family="Draft Assistant",
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
        family="Draft Assistant",
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
        family="Sleepers",
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
        family="Trend",
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
        family="Historical Explorer",
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
        family="Comparison",
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
        family="Comparison",
        required_names=("juan soto", "aaron judge"),
        question_themes=("soto", "judge", "better", "lead"),
        must_recommend=True,
        must_explain=True,
        must_compare=True,
    ),
    # --- Expanded families (answer-quality north star) ---
    QualityCase(
        "prioritize_steals",
        "Prioritize steals",
        "Draft Assistant Simulator",
        "Should I prioritize steals right now?",
        "steals_priority",
        family="Draft Assistant",
        uses_draft_context=True,
        uses_player_pool=True,
        question_themes=("steal", "sb", "priorit"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "roster_weakness",
        "Roster weakness",
        "Draft Assistant Simulator",
        "What is my biggest roster weakness?",
        "team_needs",
        family="Draft Assistant",
        uses_draft_context=True,
        question_themes=("weakness", "need", "roster", "gap", "category"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "draft_next",
        "Draft next pick",
        "Draft Assistant Simulator",
        "Who should I draft next?",
        "draft_next",
        family="Draft Assistant",
        uses_draft_context=True,
        uses_player_pool=True,
        question_themes=("draft", "next", "pick", "recommend"),
        must_recommend=True,
        must_name_players=True,
    ),
    QualityCase(
        "closer_run",
        "Closer run",
        "Draft Assistant Simulator",
        "Is a closer run coming?",
        "draft_market",
        family="Draft Market",
        uses_draft_context=True,
        question_themes=("closer", "run", "relief"),
        must_recommend=False,
        must_explain=True,
    ),
    QualityCase(
        "hitter_roster_fit",
        "Hitter roster fit",
        "Draft Assistant Simulator",
        "Which hitter fits my roster better?",
        "hitter_fit",
        family="Player Evaluation",
        uses_draft_context=True,
        uses_player_pool=True,
        question_themes=("hitter", "fit", "roster", "better"),
        must_recommend=True,
        must_compare=True,
        must_explain=True,
    ),
    QualityCase(
        "sleeper_risk",
        "Sleeper risk",
        "Fantasy Sleepers & Busts",
        "Is this sleeper worth the risk?",
        "sleepers",
        family="Sleepers",
        uses_player_pool=True,
        required_names=("caminero",),
        question_themes=("sleeper", "risk", "worth", "upside"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "trend_noise",
        "Trend noise",
        "Trend Value",
        "Is this trend meaningful or just noise?",
        "trend_noise",
        family="Trend",
        required_names=("caminero", "trend"),
        question_themes=("trend", "noise", "meaningful", "slope", "r2"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "trend_improve",
        "Trend improve",
        "Trend Value",
        "Is this player likely to improve next season?",
        "trend",
        family="Trend",
        required_names=("caminero",),
        question_themes=("improve", "next", "season", "trend"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "valuation_why",
        "Valuation why",
        "Valuation",
        "Why is this player rated so highly?",
        "valuation",
        family="Valuation",
        required_names=("caminero", "valuation"),
        question_themes=("rated", "highly", "valuation", "score"),
        must_recommend=False,
        must_explain=True,
    ),
    QualityCase(
        "valuation_justified",
        "Valuation justified",
        "Valuation",
        "Is this valuation justified?",
        "valuation",
        family="Valuation",
        required_names=("caminero",),
        question_themes=("justified", "valuation", "score"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "historical_filters_cause",
        "Historical filters",
        "Historical Explorer",
        "What filters are causing this outcome?",
        "historical",
        family="Historical Explorer",
        required_names=("bonds", "filter"),
        question_themes=("filter", "year", "hr", "outcome"),
        must_recommend=False,
        must_explain=True,
    ),
    QualityCase(
        "historical_comparison",
        "Historical comparison",
        "Historical Explorer",
        "What does this historical comparison actually show?",
        "historical",
        family="Historical Explorer",
        required_names=("bonds",),
        question_themes=("historical", "show", "comparison", "top"),
        must_recommend=False,
        must_explain=True,
    ),
    # --- Comparison AMI quality (manual testing gate) ---
    QualityCase(
        "comparison_draft_pick_qs",
        "Comparison — draft-pick question",
        "Comparison Tool",
        "Is Juan Soto vs Aaron Judge the better draft pick right now?",
        "comparison",
        family="Comparison",
        required_names=("juan soto", "aaron judge"),
        question_themes=("soto", "judge", "draft", "pick", "better"),
        must_recommend=True,
        must_compare=True,
        must_explain=True,
    ),
    QualityCase(
        "comparison_long_term",
        "Comparison — long-term value",
        "Comparison Tool",
        "Who has better long-term fantasy value, Mookie Betts or Ronald Acuna?",
        "comparison_betts_acuna",
        family="Comparison",
        required_names=("betts", "acuna"),
        question_themes=("long", "value", "betts", "acuna", "better"),
        must_recommend=True,
        must_compare=True,
        must_explain=True,
    ),
    QualityCase(
        "comparison_ros",
        "Comparison — rest-of-season",
        "Comparison Tool",
        "Who is the better rest-of-season value: Kyle Tucker or Corbin Carroll?",
        "comparison_tucker_carroll",
        family="Comparison",
        required_names=("tucker", "carroll"),
        question_themes=("tucker", "carroll", "rest", "season", "better"),
        must_recommend=True,
        must_compare=True,
        must_explain=True,
    ),
    # --- Trend Value AMI quality (manual testing gate) ---
    QualityCase(
        "trend_named_player",
        "Trend — named player trajectory",
        "Trend Value",
        "Is Junior Caminero's trend sustainable or will he regress?",
        "trend",
        family="Trend",
        required_names=("caminero",),
        question_themes=("caminero", "trend", "sustain", "regress"),
        must_recommend=True,
        must_explain=True,
    ),
    QualityCase(
        "trend_doubles_specific",
        "Trend — specific stat focus",
        "Trend Value",
        "What does this doubles trend actually mean for next season?",
        "trend",
        family="Trend",
        required_names=("caminero", "trend"),
        question_themes=("double", "2b", "trend", "season"),
        must_recommend=True,
        must_explain=True,
    ),
    # --- Sleepers/Busts quality ---
    QualityCase(
        "bust_risk_section",
        "Bust risk — section review",
        "Fantasy Sleepers & Busts",
        "Are there any players in Market Bust Risks that I should consider drafting?",
        "sleepers",
        family="Sleepers",
        required_names=("bust",),
        question_themes=("bust", "risk", "market", "draft", "consider"),
        must_recommend=True,
        must_explain=True,
        must_name_players=True,
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
    if sc == "steals_priority":
        _, ctx = build_draft_category_context()
        return dict(ctx)
    if sc == "draft_next":
        return dict(build_realistic_draft_assistant_session()["_acceptance_ctx"])
    if sc == "hitter_fit":
        session = build_realistic_draft_assistant_session()
        ctx = dict(session["_acceptance_ctx"])
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        hitters = [
            {"player": "Cal Raleigh", "Primary Position": "C", "Market Rank": 35, "Fantasy Edge": 7},
            {"player": "Bobby Witt Jr.", "Primary Position": "SS", "Market Rank": 12, "Fantasy Edge": -3},
        ]
        snap["recommended_players"] = hitters
        snap["available_players"] = hitters
        ctx["draft_snapshot"] = snap
        ctx["recommended_players"] = hitters
        return ctx
    if sc == "trend_noise":
        tv = build_realistic_trend_valuation_session()
        ctx = dict(tv["_trend_ctx"])
        ctx["trend_summary"] = {
            "player": "Junior Caminero",
            "stat": "HR",
            "slope": 0.4,
            "r2": 0.22,
            "direction": "Up",
            "delta": 2,
        }
        ctx["player"] = "Junior Caminero"
        return ctx
    if sc == "valuation":
        tv = build_realistic_trend_valuation_session()
        return dict(tv["_valuation_ctx"])
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
        session = build_realistic_comparison_session()
        ctx = dict(session["_acceptance_ctx"])
        # Enrich with explicit comparison routing fields for quality audit
        from baseball_ami_pages import finalize_comparison_context_for_send

        finalize_comparison_context_for_send(ctx, session, question=case.question)
        return ctx
    if sc == "comparison_betts_acuna":
        session = build_realistic_comparison_session()
        session["sig_player_a_clean"] = "Mookie Betts"
        session["sig_player_b_clean"] = "Ronald Acuna"
        session["_ami_comparison_context"] = {
            "comparison_stats": ["OPS", "SB"],
            "comparison_differences": [
                {"player": "Mookie Betts", "Slope": 0.8, "R-squared": 0.55, "Net Change": 3},
                {"player": "Ronald Acuna", "Slope": 1.5, "R-squared": 0.70, "Net Change": 6},
            ],
        }
        from applied_math_context import build_baseball_applied_math_context
        from baseball_ami_pages import finalize_comparison_context_for_send

        ctx = build_baseball_applied_math_context("Comparison Tool", session)
        finalize_comparison_context_for_send(ctx, session, question=case.question)
        return ctx
    if sc == "comparison_tucker_carroll":
        session = build_realistic_comparison_session()
        session["sig_player_a_clean"] = "Kyle Tucker"
        session["sig_player_b_clean"] = "Corbin Carroll"
        session["_ami_comparison_context"] = {
            "comparison_stats": ["SB", "HR"],
            "comparison_differences": [
                {"player": "Kyle Tucker", "Slope": 1.1, "R-squared": 0.60, "Net Change": 4},
                {"player": "Corbin Carroll", "Slope": 0.9, "R-squared": 0.51, "Net Change": 3},
            ],
        }
        from applied_math_context import build_baseball_applied_math_context
        from baseball_ami_pages import finalize_comparison_context_for_send

        ctx = build_baseball_applied_math_context("Comparison Tool", session)
        finalize_comparison_context_for_send(ctx, session, question=case.question)
        return ctx
    return dict(build_realistic_draft_assistant_session()["_acceptance_ctx"])


def evaluate_answer_quality(
    case: QualityCase,
    ctx: dict[str, Any],
    answer: str,
) -> QualityResult:
    """Score one answer against fantasy-player usefulness criteria."""
    row = QualityResult(
        case_id=case.case_id,
        category=case.category,
        question=case.question,
        family=case.family or case.category,
    )
    direct = direct_answer_text(answer)
    low = answer.lower()
    direct_low = direct.lower()
    failures: list[str] = []
    strengths: list[str] = []
    dims: list[QualityDimension] = []

    # Theme coverage (question understanding)
    theme_missing = [t for t in case.question_themes if t.lower() not in low]
    answers_q = len(theme_missing) <= max(1, len(case.question_themes) // 3) if case.question_themes else True

    # 1. Grounding + question fit
    ground_failures = (
        check_pick_round_grounding(ctx, answer)
        + check_no_generic_filler(answer)
        + check_not_recommending_drafted(ctx, answer)
    )
    if case.must_name_players:
        pool = pool_player_names(ctx)
        ground_failures.extend(check_scarcity_has_players(answer, pool))
    dim1 = QualityDimension(
        "understands_question",
        "Did it understand the actual question?",
        answers_q and not ground_failures,
        "; ".join(ground_failures[:2]) or ("Addresses question themes" if answers_q else f"Missing: {theme_missing}"),
    )
    dims.append(dim1)
    failures.extend(ground_failures)

    dim2 = QualityDimension(
        "answers_question",
        "Does the answer match what was asked?",
        answers_q,
        f"Missing themes: {theme_missing}" if not answers_q else "On-topic",
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
        "Did it use the correct page context?",
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
            "Did it use draft board and roster when relevant?",
            draft_blob_ok and draft_answer_ok,
            "Draft board/pick evidence in answer" if draft_blob_ok and draft_answer_ok else "Draft context underused",
        )
    else:
        dim4 = QualityDimension(
            "uses_draft_context",
            "Did it use draft board and roster when relevant?",
            True,
            "N/A",
        )
    dims.append(dim4)
    if case.uses_draft_context and not dim4.passed:
        failures.append("Draft context not reflected in answer")

    # 4b. Player pool when relevant
    if case.uses_player_pool:
        pool_names = pool_player_names(ctx)
        pool_in_ctx = bool(pool_names)
        pool_in_answer = any(n.lower() in low for n in pool_names[:8]) if pool_names else check_has_evidence(answer)
        dim_pool = QualityDimension(
            "uses_player_pool",
            "Did it use the available player pool when relevant?",
            pool_in_ctx and pool_in_answer,
            "Names pool players or cites pool stats" if pool_in_ctx and pool_in_answer else "Pool underused in answer",
        )
    else:
        dim_pool = QualityDimension(
            "uses_player_pool",
            "Did it use the available player pool when relevant?",
            True,
            "N/A",
        )
    dims.append(dim_pool)
    if case.uses_player_pool and not dim_pool.passed:
        failures.append("Available player pool not reflected in answer")

    # 5. Real players and data
    name_failures = check_names_present(direct if case.forbidden_names else answer, case.required_names, full_text=answer)
    has_evidence = check_has_evidence(answer)
    dim5 = QualityDimension(
        "real_players_and_data",
        "Did it mention real players and real data?",
        (not case.required_names or not name_failures) and has_evidence,
        "; ".join(name_failures[:2]) or ("Evidence-backed" if has_evidence else "Thin evidence"),
    )
    dims.append(dim5)
    failures.extend(name_failures)
    if not has_evidence:
        failures.append("Answer lacks measurable evidence")

    # 6. Explains why
    why = check_explains_why(answer) if case.must_explain else True
    dim6 = QualityDimension(
        "explains_why",
        "Did it explain why?",
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
        "Did it compare alternatives when appropriate?",
        alt,
        "Alternatives or tradeoffs mentioned" if alt else "No alternatives discussed",
    )
    dims.append(dim7)
    if case.must_compare and not alt:
        failures.append("Does not compare alternatives")

    # 8. Avoids filler / invented facts
    invented = check_pick_round_grounding(ctx, answer) + check_no_generic_filler(answer)
    dim8 = QualityDimension(
        "avoids_filler",
        "Did it avoid generic filler and invented facts?",
        not invented,
        "; ".join(invented[:2]) or "No invented pick/filler detected",
    )
    dims.append(dim8)

    failures.extend(check_forbidden_names(answer, case.forbidden_names))

    # 9. Player trustworthy — composite
    critical = [d for d in dims if d.id in ("understands_question", "real_players_and_data", "avoids_filler")]
    rec = check_recommends(direct) if case.must_recommend else True
    trustworthy = all(d.passed for d in critical) and has_evidence
    if case.must_recommend:
        trustworthy = trustworthy and rec
    if case.must_explain:
        trustworthy = trustworthy and why
    dim9 = QualityDimension(
        "player_trustworthy",
        "Would a knowledgeable fantasy baseball player trust this answer?",
        trustworthy,
        "Believable and useful" if trustworthy else "Would not pass knowledgeable-player sniff test",
    )
    dims.append(dim9)

    if case.must_recommend and not rec:
        failures.append("No clear recommendation for a decision question")
        dim_rec = QualityDimension(
            "provides_recommendation",
            "Does it provide a actionable recommendation?",
            False,
            "No actionable recommendation",
        )
    else:
        dim_rec = QualityDimension(
            "provides_recommendation",
            "Does it provide a actionable recommendation?",
            rec if case.must_recommend else True,
            "Clear take/lean" if rec or not case.must_recommend else "No actionable recommendation",
        )
    dims.insert(5, dim_rec)

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
        row.family = case.family or case.category
        row.routing_only_pass = bool(row.route_id) and not row.player_trustworthy
        row.pipeline = {
            "A_context_keys": len(ctx),
            "A_has_draft_snapshot": bool(ctx.get("draft_snapshot")),
            "B_route_id": row.route_id,
            "C_draft_mode": row.draft_mode or row.route_id,
            "D_answer_chars": len(text),
            "E_has_evidence": check_has_evidence(text),
            "F_player_trustworthy": row.player_trustworthy,
        }
        results.append(row)

    passed = sum(1 for r in results if r.passed)
    trustworthy = sum(1 for r in results if r.player_trustworthy)
    routing_only = sum(1 for r in results if r.routing_only_pass)
    by_family: dict[str, dict[str, int]] = {}
    for r in results:
        fam = r.family or "Other"
        bucket = by_family.setdefault(fam, {"total": 0, "trustworthy": 0, "routing_only_fail": 0})
        bucket["total"] += 1
        if r.player_trustworthy:
            bucket["trustworthy"] += 1
        if r.routing_only_pass:
            bucket["routing_only_fail"] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "north_star": "Routing pass with a useless answer is still a failure.",
        "criteria": [
            "understands_question",
            "uses_page_context",
            "uses_draft_context",
            "uses_player_pool",
            "real_players_and_data",
            "explains_why",
            "compares_alternatives",
            "avoids_filler",
            "player_trustworthy",
        ],
        "pipeline_stages": [
            "A: Baseball sends context",
            "B: AMI classifies question (route)",
            "C: AMI selects reasoning mode (draft_mode)",
            "D: Meaningful baseball analysis in answer",
            "E: Clear explanation",
            "F: Fantasy-player trust",
        ],
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "player_trustworthy": trustworthy,
            "routing_only_failures": routing_only,
            "ready_for_manual_acceptance": passed == len(results),
            "by_family": by_family,
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
    if s.get("routing_only_failures"):
        print(f"  routing-only failures (routed but not trustworthy): {s['routing_only_failures']}")
    print(f"Saved: {out}")
    for fam, stats in (s.get("by_family") or {}).items():
        print(f"  [{fam}] trustworthy {stats['trustworthy']}/{stats['total']} · routing-only fail {stats['routing_only_fail']}")
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
