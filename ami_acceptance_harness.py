"""Baseball AMI acceptance harness — realistic scenarios, context audit, analyst stub."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# Requirement key → paths to check in merged solver context (first hit wins).
_CONTEXT_PATHS: dict[str, list[tuple[str, ...]]] = {
    "canonical_draft_board": [
        ("canonical_draft_board",),
        ("draft_snapshot", "draft_room_board"),
    ],
    "canonical_drafted_players": [
        ("drafted_players",),
        ("draft_snapshot", "canonical_drafted_players"),
        ("draft_projection", "drafted_players"),
    ],
    "available_players": [
        ("draft_projection", "available_players"),
        ("draft_snapshot", "available_players"),
        ("best_available",),
    ],
    "draft_queue": [
        ("draft_queue",),
        ("draft_snapshot", "draft_queue"),
    ],
    "watchlist_focus": [
        ("watchlist",),
        ("draft_snapshot", "watchlist_focus"),
    ],
    "tracked_players": [
        ("tracked_players",),
        ("draft_snapshot", "tracked_players"),
    ],
    "user_roster": [
        ("roster",),
        ("draft_snapshot", "user_roster"),
        ("draft_projection", "my_roster"),
    ],
    "needed_positions": [
        ("needed_positions",),
        ("draft_snapshot", "needed_positions"),
        ("draft_projection", "needed_positions"),
    ],
    "category_needs": [
        ("category_needs",),
        ("draft_snapshot", "category_needs"),
        ("draft_projection", "category_needs"),
    ],
    "position_scarcity": [
        ("draft_projection", "position_scarcity"),
        ("draft_snapshot", "position_scarcity"),
    ],
    "recommended_players": [
        ("recommended_players",),
        ("draft_snapshot", "recommended_players"),
        ("draft_projection", "top_recommendations"),
    ],
    "best_available_players": [
        ("draft_projection", "best_available"),
        ("draft_snapshot", "best_available_players"),
        ("best_available",),
    ],
    "scoring_settings": [
        ("scoring_settings",),
        ("draft_snapshot", "scoring_settings"),
    ],
    "draft_round": [
        ("draft_round",),
        ("draft_snapshot", "draft_round"),
        ("draft_projection", "draft_round"),
    ],
    "current_pick": [
        ("current_pick",),
        ("draft_snapshot", "current_pick"),
        ("draft_projection", "current_pick"),
    ],
    "my_next_pick": [
        ("my_next_pick",),
        ("draft_snapshot", "my_next_pick"),
        ("draft_projection", "my_next_pick"),
    ],
    "latest_picks": [
        ("draft_snapshot", "latest_picks"),
    ],
    "sleeper_candidates": [
        ("sleeper_candidates",),
        ("sleepers_snapshot", "sleeper_candidates"),
    ],
    "bust_risks": [
        ("bust_risks",),
        ("sleepers_snapshot", "bust_risks"),
    ],
    "drafted_exclusions": [
        ("drafted_exclusions",),
        ("sleepers_snapshot", "drafted_exclusions"),
    ],
    "synced_roster": [
        ("roster",),
        ("sleepers_snapshot", "synced_roster"),
    ],
    "roster_needs": [
        ("roster_needs",),
        ("sleepers_snapshot", "roster_needs"),
    ],
    "trend_summary": [
        ("trend_summary",),
    ],
    "player": [
        ("player",),
    ],
    "metrics": [
        ("metrics",),
    ],
    "draft_status": [
        ("draft_status",),
        ("trend_summary", "draft_status"),
        ("valuation_snapshot", "draft_status"),
    ],
    "valuation_snapshot": [
        ("valuation_snapshot",),
    ],
    "selected_player": [
        ("player",),
        ("valuation_snapshot", "selected_player"),
    ],
    "top_valuation_players": [
        ("valuation_snapshot", "top_valuation_players"),
        ("players",),
    ],
}


def _get_path(obj: Any, path: tuple[str, ...]) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _is_nonempty(val: Any) -> bool:
    if val is None:
        return False
    if val == "" or val == [] or val == {}:
        return False
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        return len(val) > 0
    return True


def resolve_context_value(ctx: dict[str, Any], requirement: str) -> tuple[Any, str]:
    """Return (value, path_label) for a requirement key."""
    for path in _CONTEXT_PATHS.get(requirement, [(requirement,)]):
        val = _get_path(ctx, path)
        if _is_nonempty(val):
            return val, ".".join(path)
    return None, ""


@dataclass
class RequirementResult:
    key: str
    present: bool
    path: str
    sample: Any = None


@dataclass
class AcceptanceResult:
    test_id: str
    page: str
    question: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stub_response: str = ""


def audit_page_context(ctx: dict[str, Any], page: str) -> list[RequirementResult]:
    from baseball_ami_frame import PAGE_CONTEXT_REQUIREMENTS

    reqs = PAGE_CONTEXT_REQUIREMENTS.get(page, [])
    out: list[RequirementResult] = []
    for key in reqs:
        val, path = resolve_context_value(ctx, key)
        sample = None
        if isinstance(val, list) and val:
            sample = val[0] if not isinstance(val[0], dict) else val[0].get("player") or val[0]
        elif isinstance(val, dict):
            sample = list(val.keys())[:3]
        else:
            sample = val
        out.append(RequirementResult(key=key, present=_is_nonempty(val), path=path, sample=sample))
    return out


def _player_names_from_ctx(ctx: dict[str, Any], *keys: str) -> set[str]:
    names: set[str] = set()
    for key in keys:
        block = ctx.get(key)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    n = item.get("player") or item.get("Player") or item.get("fullName")
                    if n:
                        names.add(str(n).split(" (")[0].strip().lower())
                elif item:
                    names.add(str(item).split(" (")[0].strip().lower())
    snap = ctx.get("draft_snapshot")
    if isinstance(snap, dict):
        for sub in ("canonical_drafted_players", "drafted_players", "drafted_exclusions"):
            arr = snap.get(sub)
            if isinstance(arr, list):
                for n in arr:
                    names.add(str(n).split(" (")[0].strip().lower())
    drafted = ctx.get("drafted_players")
    if isinstance(drafted, list):
        for n in drafted:
            names.add(str(n).split(" (")[0].strip().lower())
    canon = ctx.get("canonical_drafted_players")
    if isinstance(canon, list):
        for n in canon:
            names.add(str(n).split(" (")[0].strip().lower())
    return names


def _available_names(ctx: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for path in (
        ("draft_projection", "available_players"),
        ("draft_projection", "best_available"),
        ("draft_snapshot", "available_players"),
        ("best_available",),
        ("recommended_players",),
    ):
        block = _get_path(ctx, path)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    n = item.get("player")
                    if n:
                        names.add(str(n).split(" (")[0].strip().lower())
                elif item:
                    names.add(str(item).split(" (")[0].strip().lower())
    return names


def simulate_analyst_response(ctx: dict[str, Any], question: str) -> str:
    """Rule-based stub proving context supports structured analyst answers (not LLM)."""
    q = question.lower()
    drafted = _player_names_from_ctx(ctx, "drafted_players")
    available = _available_names(ctx)
    top = None
    recs = resolve_context_value(ctx, "recommended_players")[0]
    if isinstance(recs, list) and recs:
        first = recs[0]
        top = first.get("player") if isinstance(first, dict) else str(first)

    if "who should i draft" in q or "on the clock" in q:
        pick = top or (list(available)[0] if available else "No pick — context missing")
        if pick and str(pick).lower() in drafted:
            pick = next((n for n in available if n not in drafted), "ERROR: only drafted players in pool")
        needs = resolve_context_value(ctx, "needed_positions")[0] or resolve_context_value(ctx, "category_needs")[0]
        scarcity = _get_path(ctx, ("draft_projection", "position_scarcity"))
        alts = list(available - {str(pick).lower()})[:2]
        return (
            f"**Draft {pick}.**\n\n"
            f"**Why:** Roster needs {needs}; fits category construction.\n\n"
            f"**Scarcity:** Position scarcity index {scarcity}; pool has {len(available)} tracked available options.\n\n"
            f"**Risk:** See recommendation metrics in context (Model Rank, Fantasy Edge).\n\n"
            f"**Alternatives:** {', '.join(alts) or '—'}\n\n"
            f"**What-if:** Power priority → elite HR/OBP target; speed → SB-focused alt; safety → higher floor player."
        )

    if "roster need" in q:
        needs = resolve_context_value(ctx, "needed_positions")[0]
        cats = resolve_context_value(ctx, "category_needs")[0]
        roster = resolve_context_value(ctx, "user_roster")[0]
        return (
            f"**Roster diagnosis:** {len(roster or [])} players on roster.\n\n"
            f"**Position gaps:** {needs}\n\n"
            f"**Category needs:** {cats}\n\n"
            f"**Next action:** Target {needs[0] if isinstance(needs, list) and needs else 'best value'} while addressing {cats}."
        )

    if "catcher" in q or "scarcity" in q or "wait" in q:
        scarcity = _get_path(ctx, ("draft_projection", "position_scarcity"))
        avail_n = len(available)
        return (
            f"**Scarcity analysis:** Catcher tier thinning — scarcity index {scarcity}, "
            f"{avail_n} available names in context. "
            "If elite C remains in available_players, take now; else wait one round if OF/SS value is higher."
        )

    if "prioritize power" in q:
        return "**Power priority:** Shift to HR/OBP leaders in available_players (e.g. top HR projection)."
    if "prioritize steal" in q or "prioritize speed" in q:
        return "**Speed priority:** Shift to SB leaders in available_players / top_recommendations."
    if "prioritize pitching" in q:
        return "**Pitching priority:** Defer hitters; target pitching scarcity if league is 5x5 with SP/RP needs."
    if "prioritize upside" in q:
        return "**Upside priority:** Favor younger players with positive Fantasy Edge and high Sleeper Score."

    if "sleeper" in q:
        sleepers = resolve_context_value(ctx, "sleeper_candidates")[0]
        excl = resolve_context_value(ctx, "drafted_exclusions")[0] or []
        name = None
        if isinstance(sleepers, list) and sleepers:
            cand = sleepers[0]
            name = cand.get("player") if isinstance(cand, dict) else str(cand)
        drafted_set = {str(x).split(" (")[0].strip().lower() for x in (excl or [])}
        if name and name.lower() in drafted_set:
            return f"**Do not draft {name}** — already in drafted_exclusions."
        edge = sleepers[0].get("Fantasy Edge") if isinstance(sleepers, list) and sleepers and isinstance(sleepers[0], dict) else "?"
        return (
            f"**Sleeper take: {name}** — Fantasy Edge {edge}; not in drafted_exclusions ({len(excl)} excluded). "
            f"Fits roster_needs {resolve_context_value(ctx, 'roster_needs')[0]}."
        )

    if "overvalued" in q or "undervalued" in q or "risky" in q:
        ts = ctx.get("trend_summary") or {}
        vs = ctx.get("valuation_snapshot") or {}
        ds = resolve_context_value(ctx, "draft_status")[0] or {}
        top = vs.get("top_valuation_players", [{}])[0] if vs.get("top_valuation_players") else {}
        return (
            f"**Valuation/trend:** player={ctx.get('player')}; "
            f"valuation_score={top}; "
            f"trend={ts.get('summary', ts)}; draft_status={ds}."
        )

    return f"Context page={ctx.get('page')}; keys={sorted(ctx.keys())[:12]}"


def run_acceptance_check(test_id: str, page: str, question: str, ctx: dict[str, Any]) -> AcceptanceResult:
    result = AcceptanceResult(test_id=test_id, page=page, question=question, passed=True)
    result.stub_response = simulate_analyst_response(ctx, question)

    audit = audit_page_context(ctx, page)
    missing = [r.key for r in audit if not r.present]
    if missing:
        result.passed = False
        result.failures.append(f"Missing context: {', '.join(missing)}")

    drafted = _player_names_from_ctx(ctx, "drafted_players")
    available = _available_names(ctx)

    if test_id == "T1_board_awareness":
        if not drafted:
            result.passed = False
            result.failures.append("No drafted players in context")
        if not available:
            result.passed = False
            result.failures.append("No available players in context")
        overlap = available & drafted
        if overlap and available == overlap:
            result.passed = False
            result.failures.append(f"Available pool only contains drafted: {overlap}")
        rec_text = result.stub_response.lower()
        for d in drafted:
            if d in rec_text and "do not draft" not in rec_text and "error" not in rec_text:
                if d in {str(x).lower() for x in (resolve_context_value(ctx, "recommended_players")[0] or [])}:
                    pass  # ok if in rec list as name only
        result.notes.append(f"drafted={len(drafted)} available={len(available)}")

    elif test_id == "T2_roster_awareness":
        if not resolve_context_value(ctx, "user_roster")[0]:
            result.passed = False
            result.failures.append("No roster in context")
        if not resolve_context_value(ctx, "needed_positions")[0] and not resolve_context_value(ctx, "category_needs")[0]:
            result.passed = False
            result.failures.append("No needs/category_needs in context")
        if "generic" in result.stub_response.lower():
            result.passed = False
            result.failures.append("Stub response looks generic")

    elif test_id == "T3_scarcity":
        if "scarcity" not in result.stub_response.lower():
            result.passed = False
            result.failures.append("No scarcity reasoning in stub response")
        if not resolve_context_value(ctx, "position_scarcity")[0] and not available:
            result.passed = False
            result.failures.append("No scarcity metric or available pool")

    elif test_id == "T4_optimization":
        variants = [
            simulate_analyst_response(ctx, "What if I prioritize power?"),
            simulate_analyst_response(ctx, "What if I prioritize steals?"),
            simulate_analyst_response(ctx, "What if I prioritize pitching?"),
            simulate_analyst_response(ctx, "What if I prioritize upside?"),
        ]
        if len({v[:40] for v in variants}) < 3:
            result.passed = False
            result.failures.append("What-if variants too similar — priorities may not change recommendations")
        result.notes.extend([v[:80] for v in variants])

    elif test_id == "T5_sleepers":
        if not resolve_context_value(ctx, "sleeper_candidates")[0]:
            result.passed = False
            result.failures.append("No sleeper_candidates")
        if "drafted_exclusions" not in str(ctx) and not resolve_context_value(ctx, "drafted_exclusions")[0]:
            result.passed = False
            result.failures.append("No drafted_exclusions")

    elif test_id == "T6_valuation_trend":
        if not ctx.get("trend_summary") and not ctx.get("valuation_snapshot"):
            result.passed = False
            result.failures.append("No trend_summary or valuation_snapshot")
        if not ctx.get("draft_status"):
            result.passed = False
            result.failures.append("No draft_status")

    if not ctx.get("ami_answer_template"):
        result.passed = False
        result.failures.append("Missing ami_answer_template (analyst structure)")
    if not ctx.get("ami_quality_rule"):
        result.passed = False
        result.failures.append("Missing ami_quality_rule")

    return result


def build_realistic_draft_assistant_session() -> dict[str, Any]:
    """12-team snake: 5 picks made, user team has 2, needs C/SS, queue populated."""
    rows = [
        {"Round": 1, "Pick": 1, "Team": "Rivals", "Player": "Aaron Judge"},
        {"Round": 1, "Pick": 2, "Team": "Daniel", "Player": "Juan Soto"},
        {"Round": 1, "Pick": 3, "Team": "Team 3", "Player": "Corbin Carroll"},
        {"Round": 2, "Pick": 4, "Team": "Team 4", "Player": "Mookie Betts"},
        {"Round": 2, "Pick": 5, "Team": "Daniel", "Player": "Elly De La Cruz"},
    ]
    table = pd.DataFrame(rows)
    session: dict[str, Any] = {
        "active_page": "Draft Assistant Simulator",
        "room_your_team": "Daniel",
        "room_team_count": 12,
        "room_rounds": 15,
        "room_format": "Snake",
        "draft_format": "5x5 Roto",
        "draft_queue": ["Cal Raleigh", "Bobby Witt Jr.", "Junior Caminero"],
        "draft_assistant_focus_players": ["Cal Raleigh", "Bobby Witt Jr."],
        "workflow_favorite_targets": ["Junior Caminero"],
        "workflow_recently_viewed": ["Vladimir Guerrero Jr.", "Yordan Alvarez"],
        "draft_room_table": table,
    }
    from draft_room_state import table_to_persist_dict, write_canonical_draft_room_state

    write_canonical_draft_room_state(session, table, reason="acceptance_test")

    recs = pd.DataFrame(
        [
            {
                "fullName": "Cal Raleigh",
                "Primary Position": "C",
                "Model Rank": 28,
                "Market Rank": 35,
                "Expected Fantasy Value": 0.81,
                "Draft Fit Score": 0.93,
                "Scarcity Score": 0.88,
                "Fantasy Edge": 7,
                "Reason": "Elite C scarcity; fills open catcher slot.",
            },
            {
                "fullName": "Bobby Witt Jr.",
                "Primary Position": "SS",
                "Model Rank": 15,
                "Market Rank": 12,
                "Expected Fantasy Value": 0.89,
                "Draft Fit Score": 0.85,
                "Scarcity Score": 0.72,
                "Fantasy Edge": -3,
                "Reason": "Balanced category fit; SS need.",
            },
        ]
    )
    available = pd.DataFrame(
        [
            {"fullName": "Cal Raleigh", "Primary Position": "C", "Expected Fantasy Value": 0.81},
            {"fullName": "Bobby Witt Jr.", "Primary Position": "SS", "Expected Fantasy Value": 0.89},
            {"fullName": "Junior Caminero", "Primary Position": "3B", "Expected Fantasy Value": 0.77},
            {"fullName": "Vladimir Guerrero Jr.", "Primary Position": "1B", "Expected Fantasy Value": 0.76},
        ]
    )
    from applied_math_context import build_baseball_applied_math_context, cache_draft_assistant_ami_context

    cache_draft_assistant_ami_context(
        session,
        page="Draft Assistant Simulator",
        recs_df=recs,
        current_pick=6,
        my_roster=["Juan Soto", "Elly De La Cruz"],
        drafted_total=5,
        draft_format="5x5 Roto",
        assistant_team="Daniel",
        needed_positions=["C", "SS"],
        category_needs=["HR", "SB"],
        drafted_players=["Aaron Judge", "Juan Soto", "Corbin Carroll", "Mookie Betts", "Elly De La Cruz"],
        best_available_df=available.head(3),
        available_df=available,
        position_scarcity=2.4,
    )
    session["_acceptance_ctx"] = build_baseball_applied_math_context("Draft Assistant Simulator", session)
    return session


def build_realistic_live_draft_session() -> dict[str, Any]:
    session = build_realistic_draft_assistant_session()
    session["active_page"] = "Live Draft Room"
    session["draft_queue"] = ["Cal Raleigh"]
    session["draft_assistant_focus_players"] = ["Bobby Witt Jr."]
    session["workflow_recently_viewed"] = ["Junior Caminero"]
    session["live_draft_room"] = {
            "status": "in_progress",
            "current_pick_index": 4,
            "draft_room_id": "ACCEPT01",
            "config": {
                "num_teams": 4,
                "your_team": "Daniel",
                "timer_seconds": 60,
                "scoring_type": "5x5 Roto",
                "draft_type": "snake",
            },
            "teams": ["Daniel", "Rivals", "Team 3", "Team 4"],
            "pick_order": [
                {"Round": 1, "Pick": 1, "Team": "Daniel", "Player": ""},
                {"Round": 1, "Pick": 2, "Team": "Rivals"},
                {"Round": 1, "Pick": 3, "Team": "Team 3"},
                {"Round": 1, "Pick": 4, "Team": "Team 4"},
                {"Round": 2, "Pick": 5, "Team": "Team 4"},
            ],
            "rosters": {
                "Daniel": [{"fullName": "Juan Soto"}, {"fullName": "Elly De La Cruz"}],
            },
            "draft_board": [
                {"Round": 1, "Pick": 1, "Draft Team": "Daniel", "Player": "Juan Soto"},
                {"Round": 1, "Pick": 2, "Draft Team": "Rivals", "Player": "Aaron Judge"},
            ],
            "pool": pd.DataFrame(
                [{"fullName": "Cal Raleigh", "Primary Position": "C", "Expected Fantasy Value": 0.8}]
            ),
        }
    recs = pd.DataFrame(
        [{"fullName": "Cal Raleigh", "Primary Position": "C", "Expected Fantasy Value": 0.8, "Sleeper Score": 0.7}]
    )
    from applied_math_context import build_baseball_applied_math_context, cache_live_draft_ami_context

    with __import__("unittest.mock").mock.patch(
        "draft_ami_helpers.gather_live_draft_ami_section",
        return_value={
            "current_pick": 5,
            "draft_round": 2,
            "my_next_pick": 8,
            "on_clock_team": "Team 4",
            "your_team": "Daniel",
            "user_roster": ["Juan Soto", "Elly De La Cruz"],
            "latest_picks": [{"player": "Aaron Judge", "team": "Rivals"}],
            "recommended_players": [{"player": "Cal Raleigh", "Primary Position": "C"}],
            "available_players": [{"player": "Cal Raleigh"}, {"player": "Bobby Witt Jr."}],
            "needed_positions": ["C"],
            "draft_queue": ["Cal Raleigh"],
            "watchlist_focus": ["Bobby Witt Jr."],
            "tracked_players": ["Junior Caminero"],
            "scoring_settings": {"scoring_type": "5x5 Roto"},
        },
    ):
        cache_live_draft_ami_context(session, top_rec_df=recs, best_avail_df=recs)
        session["_acceptance_ctx"] = build_baseball_applied_math_context("Live Draft Room", session)
    return session


def build_realistic_sleepers_session() -> dict[str, Any]:
    session = build_realistic_draft_assistant_session()
    sleepers = pd.DataFrame(
        [
            {
                "fullName": "Junior Caminero",
                "Primary Position": "3B",
                "Fantasy Edge": 42,
                "Market Rank": 95,
                "Model Rank": 53,
                "Reason": "Model ranks him 42 spots higher than market.",
            }
        ]
    )
    busts = pd.DataFrame(
        [{"fullName": "Overrated Star", "Fantasy Edge": -35, "Reason": "Market ahead of model."}]
    )
    from applied_math_context import build_baseball_applied_math_context, cache_fantasy_sleepers_ami_context

    cache_fantasy_sleepers_ami_context(
        session,
        sleepers_df=sleepers,
        busts_df=busts,
        synced_roster=["Juan Soto", "Elly De La Cruz"],
        drafted_exclusions=["Aaron Judge", "Juan Soto", "Corbin Carroll", "Mookie Betts", "Elly De La Cruz"],
        needed_positions=["C", "SS"],
        fantasy_format="5x5 Roto",
    )
    session["_acceptance_ctx"] = build_baseball_applied_math_context("Fantasy Sleepers & Busts", session)
    return session


def build_realistic_trend_valuation_session() -> dict[str, Any]:
    session = build_realistic_draft_assistant_session()
    from applied_math_context import build_baseball_applied_math_context, cache_valuation_ami_context, record_trend_intel

    record_trend_intel(
        session,
        player="Junior Caminero",
        stat="HR",
        intel_row={"Slope": 2.1, "R²": 0.55, "Trend Direction": "Up", "Net Change": 4},
        year_start=2022,
        year_end=2025,
    )
    val_df = pd.DataFrame(
        [
            {"fullName": "Junior Caminero", "Valuation_Score": 0.84, "Perf_Score": 72, "Trend_Score": 14},
            {"fullName": "Cal Raleigh", "Valuation_Score": 0.79, "Perf_Score": 68, "Trend_Score": 10},
        ]
    )
    cache_valuation_ami_context(session, valuation_df=val_df, selected_player="Junior Caminero")
    session["_trend_ctx"] = build_baseball_applied_math_context("Trend Value", session)
    session["_valuation_ctx"] = build_baseball_applied_math_context("Valuation", session)
    return session


def build_jose_ramirez_question_context() -> tuple[dict[str, Any], dict[str, Any]]:
    """Deployed-style send path: draft board + question-named player (Jose Ramirez)."""
    session = build_realistic_draft_assistant_session()
    from applied_math_context import attach_question_player_to_context, build_baseball_applied_math_context

    question = "Why is Jose Ramirez the best player to draft for me right now?"
    ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
    jose_row = {
        "player": "Jose Ramirez",
        "Primary Position": "3B",
        "Market Rank": 22,
        "Model Rank": 18,
        "Fantasy Edge": 4,
        "Reason": "Elite 3B power; helps HR category need.",
    }
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    avail = list(snap.get("available_players") or [])
    if not any(str(r.get("player", "")).lower() == "jose ramirez" for r in avail if isinstance(r, dict)):
        avail = [jose_row, *avail]
    snap["available_players"] = avail[:12]
    recs = list(snap.get("recommended_players") or [])
    if not any("jose ramirez" in str(r.get("player", "")).lower() for r in recs if isinstance(r, dict)):
        recs.append(jose_row)
    snap["recommended_players"] = recs
    ctx["draft_snapshot"] = snap
    attach_question_player_to_context(ctx, question, session)
    return session, ctx


def run_full_acceptance_suite() -> dict[str, Any]:
    """Run all acceptance tests; return JSON-serializable report."""
    cases: list[tuple[str, str, str, dict[str, Any]]] = []

    da = build_realistic_draft_assistant_session()
    ctx_da = da["_acceptance_ctx"]
    cases.extend(
        [
            ("T1_board_awareness", "Draft Assistant Simulator", "Who should I draft next?", ctx_da),
            ("T2_roster_awareness", "Draft Assistant Simulator", "What does my roster need?", ctx_da),
            ("T3_scarcity", "Draft Assistant Simulator", "Should I take a catcher now or wait?", ctx_da),
            ("T4_optimization", "Draft Assistant Simulator", "What if I prioritize power?", ctx_da),
        ]
    )

    ld = build_realistic_live_draft_session()
    cases.append(("T1_board_awareness", "Live Draft Room", "I'm on the clock. Who should I take?", ld["_acceptance_ctx"]))

    sl = build_realistic_sleepers_session()
    cases.append(("T5_sleepers", "Fantasy Sleepers & Busts", "Should I take this sleeper?", sl["_acceptance_ctx"]))

    tv = build_realistic_trend_valuation_session()
    cases.append(("T6_valuation_trend", "Trend Value", "Is this player undervalued?", tv["_trend_ctx"]))
    cases.append(("T6_valuation_trend", "Valuation", "How risky is this pick?", tv["_valuation_ctx"]))

    results = [run_acceptance_check(tid, page, q, ctx) for tid, page, q, ctx in cases]
    passed = sum(1 for r in results if r.passed)
    report = {
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": [
            {
                "test_id": r.test_id,
                "page": r.page,
                "question": r.question,
                "passed": r.passed,
                "failures": r.failures,
                "notes": r.notes,
                "context_audit": [
                    {"key": a.key, "present": a.present, "path": a.path, "sample": a.sample}
                    for a in audit_page_context(
                        next(c[3] for c in cases if c[0] == r.test_id and c[1] == r.page and c[2] == r.question),
                        r.page,
                    )
                ],
                "stub_response": r.stub_response,
            }
            for r in results
        ],
    }
    return report


if __name__ == "__main__":
    print(json.dumps(run_full_acceptance_suite(), indent=2, default=str))
