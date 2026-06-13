"""Grounded answer audit — fail answers that cite invented or missing evidence.

Usage:
  python ami_grounded_answer_audit.py
  python ami_grounded_answer_audit.py --save docs/ami_grounded_audit_report.json

This layer runs AFTER routing/harness checks. It validates that answers
cite real context (pick numbers, player names, availability) and do not
use template filler when data is missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
AMI_REPO = ROOT.parent / "applied-mathematical-intelligence"

CATCHER_NAMES = ("contreras", "rutschman", "smith", "raleigh", "realmuto", "heineman")
FORBIDDEN_TEMPLATE = (
    "no clear remaining",
    "no clear next pick",
    "catcher scarcity is tightening",
    "attach ops/war/hr comparison",
    "consult expert rankings",
)
INVENTED_PICK_RE = re.compile(r"\bpick\s+\*?\*?19\b", re.I)


@dataclass
class GroundedCase:
    case_id: str
    question: str
    scenario: str
    audit_id: str


@dataclass
class GroundedResult:
    case_id: str
    question: str
    audit_id: str
    passed: bool = False
    route_id: str = ""
    draft_mode: str = ""
    failures: list[str] = field(default_factory=list)
    evidence_found: list[str] = field(default_factory=list)
    short_answer: str = ""


GROUNDED_CASES: list[GroundedCase] = [
    GroundedCase(
        "catcher_market_full",
        "Who is likely to be the next catcher picked in this draft?",
        "draft_market",
        "draft_market_catcher",
    ),
    GroundedCase(
        "catcher_market_thin",
        "Who is likely to be the next catcher picked in this draft?",
        "draft_market_thin",
        "draft_market_catcher_thin",
    ),
    GroundedCase(
        "olson_schwarber",
        "Which player would be better to draft, Matt Olson or Kyle Schwarber?",
        "draft_compare",
        "draft_compare_olson_schwarber",
    ),
]


def _ensure_ami() -> None:
    path = str(AMI_REPO)
    if path not in sys.path:
        sys.path.insert(0, path)


def _solver_text(result: Any) -> str:
    parts = [
        str(getattr(result, "short_answer", "") or ""),
        str(getattr(result, "why", "") or ""),
        str(getattr(result, "interpretation", "") or ""),
    ]
    coach = (getattr(result, "computed", None) or {}).get("coach_sections")
    if isinstance(coach, dict):
        for key in ("direct_answer", "analyst_framing", "tradeoffs", "formatted_answer"):
            parts.append(str(coach.get(key) or ""))
    return "\n".join(p for p in parts if p.strip())


def _context_pick_round(ctx: dict[str, Any]) -> tuple[int | None, int | None]:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    pick = ctx.get("current_pick") or snap.get("current_pick")
    rnd = ctx.get("draft_round") or snap.get("draft_round")
    try:
        pick_i = int(pick) if pick is not None else None
    except (TypeError, ValueError):
        pick_i = None
    try:
        rnd_i = int(rnd) if rnd is not None else None
    except (TypeError, ValueError):
        rnd_i = None
    return pick_i, rnd_i


def _catcher_pool_names(ctx: dict[str, Any]) -> list[str]:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    names: list[str] = []
    for pool in (
        snap.get("available_players"),
        ctx.get("available_players"),
        snap.get("best_available_players"),
        ctx.get("best_available"),
    ):
        if not isinstance(pool, list):
            continue
        for row in pool:
            if isinstance(row, dict):
                pos = str(row.get("Primary Position") or row.get("position") or "")
                name = str(row.get("player") or row.get("Player") or "")
                if name and ("c" in pos.lower() or "catcher" in pos.lower()):
                    names.append(name.lower())
    drafted = {str(x).split(" (")[0].strip().lower() for x in (ctx.get("drafted_players") or snap.get("drafted_players") or [])}
    return [n for n in names if n.split()[0] not in drafted and n not in drafted]


def audit_draft_market_catcher(
    question: str,
    ctx: dict[str, Any],
    answer: str,
    *,
    thin_context: bool = False,
) -> GroundedResult:
    row = GroundedResult(
        case_id="catcher_market",
        question=question,
        audit_id="draft_market_catcher" if not thin_context else "draft_market_catcher_thin",
    )
    low = answer.lower()
    ctx_pick, ctx_round = _context_pick_round(ctx)
    pool = _catcher_pool_names(ctx)

    for bad in FORBIDDEN_TEMPLATE:
        if bad in low and not thin_context:
            row.failures.append(f"Template phrase without grounding: {bad}")

    if INVENTED_PICK_RE.search(answer):
        row.failures.append("Cites invented pick 19")

    if ctx_pick is not None:
        if f"pick **{ctx_pick}**" not in answer and f"pick {ctx_pick}" not in low:
            if "pick and round not" not in low and "pick not in context" not in low and "pick **" in low:
                m = re.search(r"pick\s+\*?\*?(\d+)", low)
                if m and int(m.group(1)) != ctx_pick:
                    row.failures.append(f"Cited pick {m.group(1)} != context pick {ctx_pick}")
    elif re.search(r"pick\s+\*?\*?\d+", answer):
        if not any(p in low for p in ("pick and round not", "pick not in context", "round not in context", "do not have enough")):
            row.failures.append("Cited specific pick when context has no current_pick")

    if ctx_round is not None and f"round **{ctx_round}**" not in answer:
        m = re.search(r"round\s+\*?\*?(\d+)", low)
        if m and int(m.group(1)) != ctx_round and "round not in context" not in low:
            row.failures.append(f"Cited round {m.group(1)} != context round {ctx_round}")

    if thin_context:
        if not any(p in low for p in ("do not have enough", "not in context", "attach", "pool data")):
            row.failures.append("Thin context should admit insufficient data")
    else:
        if not pool:
            row.failures.append("Fixture missing catcher pool — cannot validate names")
        elif not any(n.split()[0] in low or n in low for n in pool[:3]):
            if not any(c in low for c in CATCHER_NAMES):
                row.failures.append(f"No catcher names from pool {pool[:3]}")
            else:
                row.evidence_found.append("catcher name cited")
        else:
            row.evidence_found.append(f"named catcher from pool: {pool[0]}")

        if pool and ("no clear remaining" in low or "no clear next pick" in low):
            row.failures.append("Says no options while catcher pool exists in context")

        if "cal raleigh" in low and "already" not in low and "off the board" not in low:
            if "cal raleigh" in {str(x).lower() for x in (ctx.get("drafted_players") or [])}:
                row.failures.append("Should note Cal Raleigh drafted when in drafted_players")

    row.passed = not row.failures
    return row


def audit_draft_compare_olson_schwarber(
    question: str,
    ctx: dict[str, Any],
    answer: str,
) -> GroundedResult:
    row = GroundedResult(case_id="olson_schwarber", question=question, audit_id="draft_compare_olson_schwarber")
    coach = {}
    low = answer.lower()
    # Prefer direct recommendation text over context suffix noise.
    direct = answer.split("Context:")[0].split("\n\n")[0].lower()
    check = direct if len(direct) > 20 else low
    if "olson" not in check:
        row.failures.append("Answer missing Matt Olson")
    if "schwarber" not in check:
        row.failures.append("Answer missing Kyle Schwarber")
    if "olson" in check and "schwarber" in check and not any(
        w in check for w in ("vs", "over", "better", "lean", "compare", "draft", "pick")
    ):
        row.failures.append("Answer does not compare both players")

    unrelated = ("juan soto", "aaron judge", "julio rodriguez", "bobby witt")
    for name in unrelated:
        if name in direct:
            row.failures.append(f"Unrelated player cited in recommendation: {name}")

    if any(p in low for p in FORBIDDEN_TEMPLATE):
        row.failures.append("Generic template language without board evidence")

    evidence_markers = ("market rank", "fantasy edge", "available", "drafted", "1b", "of", "position")
    if not any(m in low for m in evidence_markers):
        row.failures.append("No board evidence (rank, availability, position) in answer")
    else:
        row.evidence_found.extend([m for m in evidence_markers if m in low])

    row.passed = not row.failures
    return row


def _scenario_context(scenario: str) -> dict[str, Any]:
    from ami_acceptance_harness import build_draft_market_catcher_context, build_realistic_draft_assistant_session

    if scenario == "draft_market":
        _, ctx = build_draft_market_catcher_context()
        return dict(ctx)
    if scenario == "draft_market_thin":
        session = build_realistic_draft_assistant_session()
        from applied_math_context import build_baseball_applied_math_context

        ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
        for key in ("current_pick", "draft_round", "available_players", "recommended_players", "best_available"):
            ctx.pop(key, None)
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        for key in (
            "current_pick",
            "draft_round",
            "available_players",
            "recommended_players",
            "best_available_players",
            "assistant_top_pick",
            "draft_room_board",
            "canonical_draft_board",
        ):
            snap.pop(key, None)
        ctx["draft_snapshot"] = snap
        ctx.pop("canonical_draft_board", None)
        ctx.pop("draft_projection", None)
        for k in ("available_players", "recommended_players", "best_available", "position_scarcity"):
            ctx.pop(k, None)
        return ctx
    if scenario == "draft_compare":
        session = build_realistic_draft_assistant_session()
        from applied_math_context import attach_question_player_to_context, build_baseball_applied_math_context

        ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
        rows = [
            {"player": "Matt Olson", "Primary Position": "1B", "Market Rank": 30, "Fantasy Edge": 22, "Reason": "HR/RBI floor"},
            {"player": "Kyle Schwarber", "Primary Position": "OF", "Market Rank": 18, "Fantasy Edge": 12, "Reason": "HR/OBP upside"},
            {"player": "Jose Ramirez", "Primary Position": "3B", "Market Rank": 6, "Fantasy Edge": 2},
        ]
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        snap["available_players"] = rows
        snap["recommended_players"] = rows
        snap["current_pick"] = 8
        snap["draft_round"] = 1
        ctx["draft_snapshot"] = snap
        ctx["available_players"] = rows
        ctx["recommended_players"] = rows
        ctx["current_pick"] = 8
        ctx["draft_round"] = 1
        ctx["needed_positions"] = ["1B"]
        q = "Which player would be better to draft, Matt Olson or Kyle Schwarber?"
        attach_question_player_to_context(ctx, q, session)
        return ctx
    return {}


def run_grounded_audit() -> dict[str, Any]:
    _ensure_ami()
    from components.applied_math_solvers import solve_suite_question

    results: list[GroundedResult] = []
    for case in GROUNDED_CASES:
        ctx = _scenario_context(case.scenario)
        ctx["page"] = "Draft Assistant Simulator"
        route, solved = solve_suite_question(case.question, source_app="baseball", context=ctx)
        text = _solver_text(solved)
        if case.audit_id == "draft_market_catcher":
            audit = audit_draft_market_catcher(case.question, ctx, text, thin_context=False)
        elif case.audit_id == "draft_market_catcher_thin":
            audit = audit_draft_market_catcher(case.question, ctx, text, thin_context=True)
        else:
            audit = audit_draft_compare_olson_schwarber(case.question, ctx, text)
        audit.case_id = case.case_id
        audit.route_id = str(getattr(route, "problem_type_id", "") or "")
        audit.draft_mode = str((getattr(solved, "computed", {}) or {}).get("draft_mode") or "")
        audit.short_answer = str(getattr(solved, "short_answer", "") or "")[:220]
        results.append(audit)

    passed = sum(1 for r in results if r.passed)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": [asdict(r) for r in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Grounded AMI answer audit")
    parser.add_argument("--save", default=str(ROOT / "docs" / "ami_grounded_audit_report.json"))
    args = parser.parse_args()
    report = run_grounded_audit()
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    s = report["summary"]
    print(f"Grounded audit: {s['passed']}/{s['total']} passed")
    print(f"Saved: {out}")
    for row in report["results"]:
        status = "PASS" if row["passed"] else "FAIL"
        print(f"  [{status}] {row['case_id']} route={row['route_id']} mode={row['draft_mode'] or '-'}")
        for f in row["failures"]:
            print(f"         - {f}")
    if s["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
