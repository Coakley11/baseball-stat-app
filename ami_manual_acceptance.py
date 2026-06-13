"""Manual AMI acceptance — real Applied Intelligence solver path (not harness stub).

Builds the same rich Baseball context as deploy send time, runs
``solve_suite_question`` from applied-mathematical-intelligence, and scores
whether answers cite saved draft state vs generic rankings.

Usage:
  python ami_manual_acceptance.py
  python ami_manual_acceptance.py --save docs/ami_manual_acceptance_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
AMI_REPO = ROOT.parent / "applied-mathematical-intelligence"

MANUAL_QUESTIONS: list[tuple[str, str, str]] = [
    ("Draft Assistant Simulator", "Who should I draft next?", "draft_assistant"),
    ("Draft Assistant Simulator", "What does my roster need?", "draft_assistant"),
    ("Fantasy Sleepers & Busts", "Should I take this sleeper?", "sleepers"),
    ("Draft Assistant Simulator", "Who are the best values left?", "draft_assistant"),
    ("Draft Assistant Simulator", "How risky is this pick?", "draft_assistant"),
    (
        "Draft Assistant Simulator",
        "What changes if I prioritize power, speed, pitching, safety, or upside?",
        "draft_assistant",
    ),
    (
        "Draft Assistant Simulator",
        "Why is Jose Ramirez the best player to draft for me right now?",
        "jose_ramirez",
    ),
    (
        "Draft Assistant Simulator",
        "Who is likely to be the next catcher picked in this draft?",
        "draft_market_catcher",
    ),
    (
        "Draft Assistant Simulator",
        "Which position is likely to run next?",
        "draft_market_position_run",
    ),
    (
        "Draft Assistant Simulator",
        "Will William Contreras make it back to me?",
        "draft_market_make_it_back",
    ),
    (
        "Draft Assistant Simulator",
        "Is a catcher run coming?",
        "draft_market_catcher_run",
    ),
]

WRONG_DRAFT_MARKET_ROUTES: frozenset[str] = frozenset(
    {
        "baseball_future_accumulation",
        "baseball_player_comparison",
        "baseball_projection_realism",
        "baseball_valuation",
    }
)

ANALYST_LEVELS: list[tuple[str, tuple[str, ...]]] = [
    ("direct_recommendation", ("draft", "lean", "recommend", "take", "target", "prioritize")),
    ("why", ("why", "roster", "fit", "need", "category", "gap", "because")),
    ("scarcity", ("scarcity", "replacement", "tier", "thinning", "pool", "available")),
    ("risk_upside", ("risk", "upside", "variance", "floor", "ceiling", "volatil")),
    ("alternatives", ("alternative", "instead", "over", "vs", "compare", "tradeoff")),
    ("what_if", ("what-if", "what if", "if you", "if your", "→", "priority")),
]

CONTEXT_CITATION_MARKERS: dict[str, tuple[str, ...]] = {
    "draft_board": ("aaron judge", "juan soto", "corbin carroll", "mookie betts", "elly de la cruz"),
    "queue_watchlist": ("cal raleigh", "bobby witt", "junior caminero"),
    "tracked": ("vladimir guerrero", "yordan alvarez"),
    "needs": ("c", "ss", "catcher", "shortstop", "hr", "sb"),
    "scarcity": ("scarcity", "2.4"),
    "recommendations": ("cal raleigh", "recommendation", "board"),
    "alternatives_pool": ("bobby witt", "junior caminero", "vladimir guerrero"),
}


@dataclass
class ManualAcceptanceResult:
    page: str
    question: str
    scenario_key: str
    route_problem_type: str = ""
    route_problem_type_id: str = ""
    route_confidence: float = 0.0
    route_missing_fields: list[str] = field(default_factory=list)
    short_answer: str = ""
    why: str = ""
    interpretation: str = ""
    sensitivity_plain: str = ""
    full_text: str = ""
    analyst_levels_present: list[str] = field(default_factory=list)
    analyst_levels_missing: list[str] = field(default_factory=list)
    context_citations: dict[str, bool] = field(default_factory=dict)
    context_keys_received: list[str] = field(default_factory=list)
    draft_snapshot_keys: list[str] = field(default_factory=list)
    generic_risk: bool = False
    passed: bool = False
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ensure_ami_import() -> None:
    if not AMI_REPO.is_dir():
        raise SystemExit(f"Applied Intelligence repo not found: {AMI_REPO}")
    ami_components = str(AMI_REPO)
    if ami_components not in sys.path:
        sys.path.insert(0, ami_components)


def _scenario_context(scenario_key: str, question: str = "") -> dict[str, Any]:
    from ami_acceptance_harness import (
        build_draft_market_catcher_context,
        build_jose_ramirez_question_context,
        build_realistic_draft_assistant_session,
        build_realistic_sleepers_session,
    )

    if scenario_key == "jose_ramirez":
        _, ctx = build_jose_ramirez_question_context()
        return dict(ctx)
    if scenario_key.startswith("draft_market"):
        _, ctx = build_draft_market_catcher_context()
        if scenario_key == "draft_market_make_it_back":
            from applied_math_context import attach_question_player_to_context

            attach_question_player_to_context(ctx, question, {})
        return dict(ctx)
    if scenario_key == "sleepers":
        session = build_realistic_sleepers_session()
        return dict(session["_acceptance_ctx"])
    session = build_realistic_draft_assistant_session()
    return dict(session["_acceptance_ctx"])


def _solver_text(result: Any) -> str:
    parts = [
        str(getattr(result, "short_answer", "") or ""),
        str(getattr(result, "why", "") or ""),
        str(getattr(result, "interpretation", "") or ""),
        str(getattr(result, "sensitivity_plain", "") or ""),
        str(getattr(result, "conclusion", "") or ""),
        str(getattr(result, "result", "") or ""),
    ]
    coach = (getattr(result, "computed", None) or {}).get("coach_sections")
    if isinstance(coach, dict):
        for key in ("direct_answer", "analyst_framing", "tradeoffs", "applied_math"):
            parts.append(str(coach.get(key) or ""))
        what_if = coach.get("what_if")
        if isinstance(what_if, list):
            parts.extend(str(x) for x in what_if)
    return "\n".join(p for p in parts if p.strip())


def _score_analyst_levels(text: str) -> tuple[list[str], list[str]]:
    low = text.lower()
    present: list[str] = []
    missing: list[str] = []
    for level, keywords in ANALYST_LEVELS:
        if any(k in low for k in keywords):
            present.append(level)
        else:
            missing.append(level)
    return present, missing


def _score_context_citations(text: str, ctx: dict[str, Any]) -> dict[str, bool]:
    low = text.lower()
    hits: dict[str, bool] = {}
    for name, markers in CONTEXT_CITATION_MARKERS.items():
        hits[name] = any(m in low for m in markers)
    # Also verify payload actually had the data (send-side), not just answer text.
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    hits["payload_has_draft_snapshot"] = bool(snap)
    hits["payload_has_recommendations"] = bool(ctx.get("recommended_players") or snap.get("recommended_players"))
    hits["payload_has_queue"] = bool(ctx.get("draft_queue") or snap.get("draft_queue"))
    hits["payload_has_needs"] = bool(
        ctx.get("needed_positions") or snap.get("needed_positions") or ctx.get("category_needs")
    )
    return hits


def _looks_generic(text: str, ctx: dict[str, Any]) -> bool:
    low = text.lower()
    generic_phrases = (
        "top-ranked player",
        "best available player in the league",
        "consult expert rankings",
        "generally recommended",
        "without context",
        "attach draft_snapshot",
    )
    if any(p in low for p in generic_phrases):
        return True
    # Recommending a player already drafted is a hard fail.
    drafted = {"aaron judge", "juan soto", "corbin carroll", "mookie betts", "elly de la cruz"}
    rec_line = low
    if "draft" in low or "lean" in low or "take" in low:
        for name in drafted:
            if name in rec_line and "do not draft" not in rec_line:
                if name not in {"juan soto", "elly de la cruz"}:  # on user roster, ok to mention
                    return True
    # Answer with no scenario-specific names at all.
    scenario_names = ("cal raleigh", "bobby witt", "junior caminero", "jose ramirez", "catcher", "shortstop")
    if not any(n in low for n in scenario_names) and "roster" not in low:
        return True
    return False


def run_manual_acceptance() -> dict[str, Any]:
    _ensure_ami_import()
    from components.applied_math_solvers import solve_suite_question

    from suite_deploy_marker import GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

    results: list[ManualAcceptanceResult] = []
    for page, question, scenario_key in MANUAL_QUESTIONS:
        ctx = _scenario_context(scenario_key, question)
        ctx["page"] = page
        ctx.setdefault("source_app", "Baseball")
        route, solved = solve_suite_question(
            question,
            source_app="baseball",
            context=ctx,
        )
        text = _solver_text(solved)
        present, missing = _score_analyst_levels(text)
        citations = _score_context_citations(text, ctx)
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}

        row = ManualAcceptanceResult(
            page=page,
            question=question,
            scenario_key=scenario_key,
            route_problem_type=str(getattr(route, "problem_type", "") or ""),
            route_problem_type_id=str(getattr(route, "problem_type_id", "") or ""),
            route_confidence=float(getattr(route, "confidence", 0) or 0),
            route_missing_fields=list(getattr(route, "missing_fields", []) or []),
            short_answer=str(getattr(solved, "short_answer", "") or ""),
            why=str(getattr(solved, "why", "") or ""),
            interpretation=str(getattr(solved, "interpretation", "") or ""),
            sensitivity_plain=str(getattr(solved, "sensitivity_plain", "") or ""),
            full_text=text,
            analyst_levels_present=present,
            analyst_levels_missing=missing,
            context_citations=citations,
            context_keys_received=sorted(ctx.keys()),
            draft_snapshot_keys=sorted(snap.keys()) if snap else [],
            generic_risk=_looks_generic(text, ctx),
        )

        if row.route_problem_type_id != "baseball_draft_decision":
            row.failures.append(f"Routed to {row.route_problem_type_id}, expected baseball_draft_decision")
        if len(row.analyst_levels_present) < 4:
            row.failures.append(f"Only {len(row.analyst_levels_present)}/6 analyst levels detected")
        if row.generic_risk:
            row.failures.append("Answer looks generic or ignores saved board")
        answer_citations = {k: v for k, v in citations.items() if not k.startswith("payload_")}
        if sum(1 for v in answer_citations.values() if v) < 2 and "Who should I draft" in question:
            row.failures.append("Next-pick answer cited fewer than 2 board-specific markers")
        if "Who should I draft" in question and not citations.get("recommendations"):
            row.failures.append("Next-pick answer did not cite recommendations/board")
        if "roster need" in question.lower():
            if not citations.get("needs"):
                row.failures.append("Roster-needs answer did not cite position/category needs")
            if "c" not in row.full_text.lower() and "ss" not in row.full_text.lower():
                row.failures.append("Roster-needs answer omitted C/SS gaps from context")
            if "wait" in row.short_answer.lower() and "adp" in row.full_text.lower():
                row.failures.append("Roster-needs question answered as ADP value-edge, not roster diagnosis")
        if "best values" in question.lower():
            if "available" not in row.full_text.lower() and "board" not in row.full_text.lower():
                row.failures.append("Best-values question did not discuss available player pool")
            if row.short_answer.lower().startswith("**wait**") and "adp" in row.full_text.lower():
                row.failures.append("Best-values question answered as single-player ADP edge, not value pool ranking")
        if "sleeper" in question.lower() and "junior caminero" not in row.full_text.lower():
            row.failures.append("Sleeper answer did not name sleeper from context (Junior Caminero)")
        if not citations.get("payload_has_draft_snapshot") and scenario_key == "draft_assistant":
            row.failures.append("Draft Assistant send context missing draft_snapshot")
        if "jose ramirez" in question.lower():
            mode = (getattr(solved, "computed", {}) or {}).get("draft_mode")
            if mode != "player_why":
                row.failures.append(f"Expected player_why mode, got {mode}")
            if "jose ramirez" not in row.full_text.lower():
                row.failures.append("Answer did not name Jose Ramirez from the question")
            low = row.full_text.lower()
            if not any(
                tok in low
                for tok in ("available", "drafted", "not available", "on your roster", "board")
            ):
                row.failures.append("Answer did not state Jose Ramirez draft availability/status")
            if not any(
                tok in low
                for tok in ("cal raleigh", "better fit", "strong pick", "recommendation", "alternative", "compared")
            ):
                row.failures.append("Answer did not compare Jose Ramirez to board recommendations/alternatives")
            if ctx.get("question_player", "").lower() != "jose ramirez":
                row.failures.append("Send context missing question_player=Jose Ramirez")
        if scenario_key.startswith("draft_market"):
            mode = (getattr(solved, "computed", {}) or {}).get("draft_mode")
            if mode != "draft_market_prediction":
                row.failures.append(f"Expected draft_market_prediction mode, got {mode}")
            if row.route_problem_type_id in WRONG_DRAFT_MARKET_ROUTES:
                row.failures.append(
                    f"Draft-market question routed to {row.route_problem_type_id} (projection/compare path)"
                )
            low = row.full_text.lower()
            if "julio" in low and "rodriguez" in low:
                row.failures.append("Answer incorrectly referenced Julio Rodriguez (stale comparison context)")
            if scenario_key == "draft_market_catcher":
                if "cal raleigh" not in low:
                    row.failures.append("Next-catcher answer did not note Cal Raleigh on the board")
                if not any(n in low for n in ("william contreras", "contreras", "rutschman", "will smith")):
                    row.failures.append("Next-catcher answer did not name remaining catchers from context")
                if "off the board" not in low and "already" not in low:
                    row.failures.append("Next-catcher answer did not state Cal Raleigh is already drafted")
                if "cal raleigh" in low and "most likely selected is **cal raleigh**" in low.replace(" ", ""):
                    row.failures.append("Next-catcher answer incorrectly named Cal Raleigh as next pick")
            if scenario_key == "draft_market_position_run":
                if not any(tok in low for tok in ("run", "catcher", "position", "scarcity")):
                    row.failures.append("Position-run answer did not discuss draft flow or position scarcity")
            if scenario_key == "draft_market_make_it_back":
                if "william contreras" not in low and "contreras" not in low:
                    row.failures.append("Make-it-back answer did not name William Contreras from question")
                if "cal raleigh" in low and "william contreras" not in low:
                    row.failures.append("Make-it-back answer incorrectly focused on Cal Raleigh instead of William Contreras")
                if not any(tok in low for tok in ("next pick", "before your", "make it back", "drafted before")):
                    row.failures.append("Make-it-back answer did not address return timing vs next pick")
            if scenario_key == "draft_market_catcher_run":
                if "catcher" not in low:
                    row.failures.append("Catcher-run answer did not reference catcher position")
                if "run" not in low:
                    row.failures.append("Catcher-run answer did not discuss a position run")

        row.passed = not row.failures
        row.notes.append(f"draft_mode={(getattr(solved, 'computed', {}) or {}).get('draft_mode')}")
        results.append(row)

    passed = sum(1 for r in results if r.passed)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_label": SUITE_BUILD_LABEL,
        "commit": GIT_COMMIT_SHORT,
        "solver": "applied-mathematical-intelligence/components/applied_math_solvers.py",
        "method": "real_solve_suite_question_with_harness_context",
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "manual_acceptance": passed == len(results),
        },
        "deploy_checklist": {
            "reboot_streamlit": "Streamlit Cloud → baseball-stat-app dev → Reboot app",
            "confirm_v18": "Draft Room manual save panel or footer: deploy_build contains ami-acceptance-harness-v18",
            "developer_mode": "Enable Developer Mode in Baseball + Applied Intelligence to see context keys received",
            "hydrate_source": "Applied Intelligence should show hydrate_source=question_id_blob after resume",
        },
        "results": [asdict(r) for r in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run manual AMI acceptance against real solver")
    parser.add_argument(
        "--save",
        default=str(ROOT / "docs" / "ami_manual_acceptance_report.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()
    report = run_manual_acceptance()
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    s = report["summary"]
    print(f"Manual AMI acceptance: {s['passed']}/{s['total']} passed")
    print(f"Build: {report['build_label']} ({report['commit']})")
    print(f"Saved: {out}")
    for row in report["results"]:
        status = "PASS" if row["passed"] else "FAIL"
        print(f"  [{status}] {row['page']}: {row['question'][:60]}")
        if row["failures"]:
            for f in row["failures"]:
                print(f"         - {f}")
        print(f"         route={row['route_problem_type_id']} answer={row['short_answer'][:100]}…")


if __name__ == "__main__":
    main()
