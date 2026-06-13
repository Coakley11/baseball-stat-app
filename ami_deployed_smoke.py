"""Deployed AMI smoke test — verify GitHub commits, Cloud app identity, solver path.

Usage:
  python ami_deployed_smoke.py
  python ami_deployed_smoke.py --save docs/ami_deployed_smoke_report.json

Checks:
  1. origin/dev HEAD matches expected commits (baseball a2a0575, AMI 9ddb738+)
  2. Streamlit Cloud apps respond (optional fetch)
  3. Seven page-family questions through real solver (deploy-equivalent path)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
AMI_REPO = ROOT.parent / "applied-mathematical-intelligence"

EXPECTED_BASEBALL_COMMIT = "a2a0575"
EXPECTED_AMI_COMMIT_PREFIX = "9ddb738"

BASEBALL_URL = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
AMI_URL = "https://applied-mathematical-intelligence-8l8bqrzpp6fghaj7xuig53.streamlit.app"

SMOKE_CASES: list[dict[str, Any]] = [
    {
        "id": "draft_assistant",
        "page": "Draft Assistant Simulator",
        "question": "Who should I draft next?",
        "expected_route": "baseball_draft_decision",
        "expected_mode": "next_pick",
        "context_keys": ("draft_snapshot", "recommended_players", "draft_queue"),
        "answer_markers": ("draft", "roster", "cal raleigh"),
        "scenario": "draft_assistant",
    },
    {
        "id": "draft_market",
        "page": "Draft Assistant Simulator",
        "question": "Who is likely to be the next catcher picked in this draft?",
        "expected_route": "baseball_draft_decision",
        "expected_mode": "draft_market_prediction",
        "forbidden_routes": ("baseball_future_accumulation",),
        "context_keys": ("draft_snapshot", "drafted_players"),
        "answer_markers": ("catcher", "contreras", "cal raleigh"),
        "forbidden_answer": ("julio rodriguez", "accumulate more"),
        "scenario": "draft_market",
    },
    {
        "id": "sleepers",
        "page": "Fantasy Sleepers & Busts",
        "question": "Should I take this sleeper?",
        "expected_route": "baseball_draft_decision",
        "expected_mode": "sleeper",
        "context_keys": ("sleeper_candidates", "drafted_exclusions"),
        "answer_markers": ("junior caminero", "sleeper"),
        "scenario": "sleepers",
    },
    {
        "id": "trend",
        "page": "Trend Value",
        "question": "Is this player likely to keep improving?",
        "expected_route": "baseball_trend_significance",
        "forbidden_routes": ("baseball_future_accumulation",),
        "context_keys": ("trend_summary", "player"),
        "answer_markers": ("trend", "slope", "r²", "r2", "meaningful", "noise"),
        "scenario": "trend",
    },
    {
        "id": "valuation",
        "page": "Valuation",
        "question": "Is this player undervalued?",
        "expected_route": "baseball_valuation",
        "context_keys": ("valuation_snapshot",),
        "answer_markers": ("valuation", "undervalued", "overvalued", "score"),
        "scenario": "valuation",
    },
    {
        "id": "comparison",
        "page": "Comparison Tool",
        "question": "Which player is better for power?",
        "expected_route": "baseball_player_comparison",
        "context_keys": ("player_a", "player_b", "comparison_stats"),
        "answer_markers": ("soto", "judge", "power", "hr", "compare"),
        "scenario": "comparison",
    },
    {
        "id": "historical",
        "page": "Historical Explorer",
        "question": "Why does this player keep appearing with these filters?",
        "expected_route": "baseball_historical_comparison",
        "context_keys": ("historical_snapshot", "filters_applied"),
        "answer_markers": ("bonds", "filter", "hr", "historical", "outlier"),
        "scenario": "historical",
    },
]


@dataclass
class SmokeResult:
    id: str
    page: str
    question: str
    passed: bool = False
    route_id: str = ""
    draft_mode: str = ""
    context_keys_received: list[str] = field(default_factory=list)
    cited_page_data: bool = False
    generic: bool = False
    failures: list[str] = field(default_factory=list)
    short_answer: str = ""


def _git_remote_short_commit(repo: Path, branch: str = "dev") -> str:
    url = {
        ROOT.parent / "baseball-stat-app": "https://github.com/Coakley11/baseball-stat-app.git",
        AMI_REPO: "https://github.com/Coakley11/Applied-mathematical-intelligence.git",
    }.get(repo.resolve())
    if not url:
        return ""
    proc = subprocess.run(
        ["git", "ls-remote", url, f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return ""
    return proc.stdout.strip().split()[0][:7]


def _fetch_commit_from_app(url: str, pattern: str) -> str:
    try:
        req = Request(url, headers={"User-Agent": "ami-deployed-smoke/1.0"})
        with urlopen(req, timeout=45) as resp:
            html = resp.read(500_000).decode("utf-8", errors="replace")
        m = re.search(pattern, html, flags=re.I)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _scenario_context(scenario: str, question: str) -> dict[str, Any]:
    from ami_acceptance_harness import (
        build_draft_market_catcher_context,
        build_realistic_comparison_session,
        build_realistic_draft_assistant_session,
        build_realistic_historical_session,
        build_realistic_sleepers_session,
        build_realistic_trend_valuation_session,
    )

    if scenario == "draft_market":
        _, ctx = build_draft_market_catcher_context()
        return dict(ctx)
    if scenario == "sleepers":
        return dict(build_realistic_sleepers_session()["_acceptance_ctx"])
    if scenario == "trend":
        tv = build_realistic_trend_valuation_session()
        ctx = dict(tv["_trend_ctx"])
        ctx.setdefault(
            "trend_summary",
            {"player": "Junior Caminero", "stat": "HR", "slope": 1.8, "r2": 0.55, "direction": "Up"},
        )
        ctx["player"] = "Junior Caminero"
        return ctx
    if scenario == "valuation":
        return dict(build_realistic_trend_valuation_session()["_valuation_ctx"])
    if scenario == "comparison":
        return dict(build_realistic_comparison_session()["_acceptance_ctx"])
    if scenario == "historical":
        return dict(build_realistic_historical_session()["_acceptance_ctx"])
    return dict(build_realistic_draft_assistant_session()["_acceptance_ctx"])


def _ensure_ami_import() -> None:
    if not AMI_REPO.is_dir():
        raise SystemExit(f"AMI repo not found: {AMI_REPO}")
    path = str(AMI_REPO)
    if path not in sys.path:
        sys.path.insert(0, path)


def run_deployed_smoke() -> dict[str, Any]:
    baseball_remote = _git_remote_short_commit(ROOT)
    ami_remote = _git_remote_short_commit(AMI_REPO)
    ami_live_commit = _fetch_commit_from_app(AMI_URL, r"commit[`'\"]([0-9a-f]{7})")

    deploy_check = {
        "baseball_github_dev": baseball_remote,
        "ami_github_dev": ami_remote,
        "baseball_expected": EXPECTED_BASEBALL_COMMIT,
        "ami_expected_prefix": EXPECTED_AMI_COMMIT_PREFIX,
        "baseball_github_ok": baseball_remote == EXPECTED_BASEBALL_COMMIT,
        "ami_github_ok": ami_remote.startswith(EXPECTED_AMI_COMMIT_PREFIX[:7]),
        "ami_live_commit_detected": ami_live_commit,
        "ami_live_ok": ami_live_commit.startswith(EXPECTED_AMI_COMMIT_PREFIX[:7]) if ami_live_commit else None,
        "baseball_url": BASEBALL_URL,
        "ami_url": AMI_URL,
        "reboot_note": "Set STREAMLIT_API_TOKEN to POST /apps/{appId}/restart (manual reboot via Manage app if unset)",
    }

    _ensure_ami_import()
    from components.applied_math_solvers import solve_suite_question

    results: list[SmokeResult] = []
    for case in SMOKE_CASES:
        ctx = _scenario_context(case["scenario"], case["question"])
        ctx["page"] = case["page"]
        route, solved = solve_suite_question(case["question"], source_app="baseball", context=ctx)
        text = "\n".join(
            filter(
                None,
                [
                    str(getattr(solved, "short_answer", "") or ""),
                    str(getattr(solved, "why", "") or ""),
                    str(getattr(solved, "interpretation", "") or ""),
                ],
            )
        )
        low = text.lower()
        row = SmokeResult(
            id=case["id"],
            page=case["page"],
            question=case["question"],
            route_id=str(getattr(route, "problem_type_id", "") or ""),
            draft_mode=str((getattr(solved, "computed", {}) or {}).get("draft_mode") or ""),
            context_keys_received=sorted(ctx.keys()),
            short_answer=str(getattr(solved, "short_answer", "") or "")[:180],
        )
        if row.route_id != case["expected_route"]:
            row.failures.append(f"route {row.route_id} != {case['expected_route']}")
        for bad in case.get("forbidden_routes") or ():
            if row.route_id == bad:
                row.failures.append(f"forbidden route {bad}")
        if case.get("expected_mode") and row.draft_mode != case["expected_mode"]:
            row.failures.append(f"mode {row.draft_mode} != {case['expected_mode']}")
        for key in case.get("context_keys") or ():
            if key not in ctx and key.lower() not in json.dumps(ctx, default=str).lower():
                row.failures.append(f"missing context key {key}")
        row.cited_page_data = any(m.lower() in low for m in case.get("answer_markers") or ())
        if not row.cited_page_data:
            row.failures.append(f"answer missing markers {case.get('answer_markers')}")
        for bad in case.get("forbidden_answer") or ():
            if bad.lower() in low:
                row.failures.append(f"forbidden phrase in answer: {bad}")
        generic_phrases = ("attach draft_snapshot", "consult expert rankings", "without context")
        row.generic = any(p in low for p in generic_phrases)
        if row.generic:
            row.failures.append("answer looks generic")
        row.passed = not row.failures
        results.append(row)

    passed = sum(1 for r in results if r.passed)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deploy_check": deploy_check,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "deploy_ready": deploy_check["baseball_github_ok"]
            and deploy_check["ami_github_ok"]
            and passed == len(results),
        },
        "results": [asdict(r) for r in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deployed AMI smoke test")
    parser.add_argument(
        "--save",
        default=str(ROOT / "docs" / "ami_deployed_smoke_report.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()
    report = run_deployed_smoke()
    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    s = report["summary"]
    d = report["deploy_check"]
    print(f"GitHub dev: baseball={d['baseball_github_dev']} ami={d['ami_github_dev']}")
    print(f"AMI live commit (HTML): {d.get('ami_live_commit_detected') or 'not detected'}")
    print(f"Smoke: {s['passed']}/{s['total']} passed · deploy_ready={s['deploy_ready']}")
    print(f"Saved: {out}")
    for row in report["results"]:
        status = "PASS" if row["passed"] else "FAIL"
        print(f"  [{status}] {row['id']}: route={row['route_id']} mode={row['draft_mode'] or '-'}")
        for f in row["failures"]:
            print(f"         - {f}")
    if not s["deploy_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
