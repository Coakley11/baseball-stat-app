"""Read-only draft intelligence from the snapshot the draft pages already computed.

Draft Assistant Simulator and Live Draft Room cache their recommendation state in
``session["_ami_draft_snapshot"]`` / ``session["_ami_draft_projection"]``
(``applied_math_context.cache_draft_assistant_ami_context`` / ``cache_live_draft_ami_context``).
These tools only *read* those dicts — they never recompute scores, never call the
snapshot gatherers (which touch session state), and never draft or queue anyone.
"""

from __future__ import annotations

from typing import Any, Mapping

from ami_assistant.safety import clean_text
from ami_assistant.tools.registry import MISSING_DRAFT_CONTEXT, NOT_IN_POOL, ToolResult, fail, tool
from player_name_normalization import normalize_player_name_for_merge

SNAPSHOT_KEY = "_ami_draft_snapshot"
PROJECTION_KEY = "_ami_draft_projection"
SLEEPERS_KEY = "_ami_sleepers_snapshot"
DRAFT_PAGES = ("Draft Assistant Simulator", "Live Draft Room")

# Fields copied from each recommendation row (display names from draft_score_display).
REC_FIELDS = (
    "player",
    "Primary Position",
    "Team",
    "Decision Score",
    "Player Grade",
    "Roster Fit Score",
    "Fantasy Edge",
    "Model Rank",
    "Market Rank",
    "Scarcity Score",
    "Positional Fit",
    "Survival Probability",
    "Survival Label",
    "why_this_pick",
    "reason",
)
_SAFE_SCALARS = (str, int, float, bool)


def _clean_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    for key in REC_FIELDS:
        val = row.get(key)
        if isinstance(val, str):
            val = clean_text(val, 300)
        if isinstance(val, _SAFE_SCALARS) and val != "":
            out[key] = val
    return out


def _texts(values: Any, limit: int) -> list[str]:
    items = values if isinstance(values, (list, tuple)) else []
    return [t for t in (clean_text(v, 60) for v in items) if t][:limit]


def _snapshot(session: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    snap = session.get(SNAPSHOT_KEY) if hasattr(session, "get") else None
    proj = session.get(PROJECTION_KEY) if hasattr(session, "get") else None
    return (snap if isinstance(snap, dict) else {}), (proj if isinstance(proj, dict) else {})


def _missing() -> ToolResult:
    return fail(
        "get_active_draft_context",
        MISSING_DRAFT_CONTEXT,
        "There's no draft in progress in this session. Open Draft Assistant Simulator (or Live Draft Room) "
        "so it can build recommendations, then ask again.",
    )


def _rows(snap: dict[str, Any], proj: dict[str, Any], key: str, alt: str = "") -> list[dict[str, Any]]:
    raw = snap.get(key) or (proj.get(alt) if alt else None) or []
    return [_clean_row(r) for r in raw if isinstance(r, Mapping) and r.get("player")]


def _position_matches(row: Mapping[str, Any], position: str) -> bool:
    pos = str(row.get("Primary Position") or "").upper()
    return position.upper() in {p.strip() for p in pos.replace("/", ",").split(",")}


@tool(
    "get_active_draft_context",
    capability="draft_intelligence",
    description="Current draft state from the draft pages: pick, round, your team, roster, position and category needs.",
    reuses=("applied_math_context.cache_draft_assistant_ami_context (session snapshot, read-only)",),
    needs_session=True,
)
def get_active_draft_context(*, session: Mapping[str, Any]) -> ToolResult:
    snap, proj = _snapshot(session)
    if not snap and not proj:
        return _missing()
    data = {
        "source_page": clean_text(snap.get("page"), 60),
        "current_pick": snap.get("current_pick", proj.get("current_pick")),
        "draft_round": snap.get("draft_round", proj.get("draft_round")),
        "my_next_pick": snap.get("my_next_pick", proj.get("my_next_pick")),
        "team": clean_text(proj.get("assistant_team"), 60),
        "draft_format": clean_text(proj.get("draft_format"), 40),
        "roster": _texts(snap.get("user_roster") or proj.get("my_roster"), 24),
        "needed_positions": _texts(snap.get("needed_positions") or proj.get("needed_positions"), 12),
        "category_needs": _texts(snap.get("category_needs") or proj.get("category_needs"), 12),
        "category_diagnostics": [d for d in (snap.get("category_diagnostics") or []) if isinstance(d, Mapping)][:12],
        "position_scarcity": [d for d in (snap.get("position_scarcity_table") or []) if isinstance(d, Mapping)][:12],
        "drafted_count": proj.get("drafted_total"),
    }
    return ToolResult(tool="get_active_draft_context", ok=True, data=data)


@tool(
    "get_draft_recommendations",
    capability="draft_intelligence",
    description=(
        "The draft page's own ranked recommendations (Decision Score, Player Grade, Roster Fit, Why this pick) "
        "and best available players, optionally for one position."
    ),
    parameters={"properties": {"position": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}},
    reuses=("draft_ami_helpers.compact_recommendation_rows (cached rows)", "draft_score_display.SCORE_TOOLTIPS"),
    needs_session=True,
)
def get_draft_recommendations(*, session: Mapping[str, Any], position: str | None = None, limit: int = 5) -> ToolResult:
    snap, proj = _snapshot(session)
    if not snap and not proj:
        r = _missing()
        r.tool = "get_draft_recommendations"
        return r
    recs = _rows(snap, proj, "recommended_players", "top_recommendations")
    best = _rows(snap, proj, "best_available_players", "best_available")
    pool = _rows(snap, proj, "available_players", "available_players")
    limit = max(1, min(int(limit or 5), 10))
    data: dict[str, Any] = {
        "source_page": clean_text(snap.get("page"), 60),
        "current_pick": snap.get("current_pick", proj.get("current_pick")),
        "needed_positions": _texts(snap.get("needed_positions") or proj.get("needed_positions"), 12),
        "position": position or None,
    }
    if position:
        seen: set[str] = set()
        matches = []
        for row in recs + best + pool:
            if _position_matches(row, position) and row["player"] not in seen:
                seen.add(row["player"])
                matches.append(row)
        data["recommendations"] = matches[:limit]
        data["note"] = "" if matches else f"No {position.upper()} appears in the draft page's current recommendation lists."
    else:
        data["recommendations"] = recs[:limit]
        data["best_available"] = best[:limit]
    return ToolResult(tool="get_draft_recommendations", ok=True, data=data)


@tool(
    "explain_draft_recommendation",
    capability="draft_intelligence",
    description="Why the draft page recommends a player: the row's scores and its 'Why this pick' text, verbatim.",
    parameters={"properties": {"player": {"type": "string"}}, "required": ["player"]},
    reuses=("draft_ami_helpers.compact_recommendation_rows (cached rows)",),
    needs_session=True,
)
def explain_draft_recommendation(*, session: Mapping[str, Any], player: str) -> ToolResult:
    snap, proj = _snapshot(session)
    if not snap and not proj:
        r = _missing()
        r.tool = "explain_draft_recommendation"
        return r
    want = normalize_player_name_for_merge(str(player).split(" (")[0])
    lists = (
        ("recommendations", _rows(snap, proj, "recommended_players", "top_recommendations")),
        ("best_available", _rows(snap, proj, "best_available_players", "best_available")),
        ("available_players", _rows(snap, proj, "available_players", "available_players")),
    )
    for list_name, rows in lists:
        for idx, row in enumerate(rows):
            if normalize_player_name_for_merge(row["player"]) == want:
                return ToolResult(
                    tool="explain_draft_recommendation",
                    ok=True,
                    data={
                        "row": row,
                        "list": list_name,
                        "position_in_list": idx + 1,
                        "source_page": clean_text(snap.get("page"), 60),
                        "needed_positions": _texts(snap.get("needed_positions"), 12),
                    },
                )
    return fail(
        "explain_draft_recommendation",
        NOT_IN_POOL,
        f"{player} isn't in the draft page's current recommendation lists (they may be drafted or ranked lower).",
    )


@tool(
    "get_team_needs",
    capability="draft_intelligence",
    description="Your draft team's open positions and category strengths/weaknesses versus the remaining pool.",
    reuses=("applied_math_context.cache_draft_assistant_ami_context (category_diagnostics)",),
    needs_session=True,
)
def get_team_needs(*, session: Mapping[str, Any]) -> ToolResult:
    res = get_active_draft_context(session=session)
    res.tool = "get_team_needs"
    if not res.ok:
        return res
    d = res.data
    diags = d.get("category_diagnostics") or []
    res.data = {
        "team": d.get("team"),
        "source_page": d.get("source_page"),
        "current_pick": d.get("current_pick"),
        "needed_positions": d.get("needed_positions"),
        "category_needs": d.get("category_needs"),
        "weak_categories": [x for x in diags if x.get("status") == "weak"],
        "strong_categories": [x for x in diags if x.get("status") == "strong"],
        "roster": d.get("roster"),
    }
    return res


@tool(
    "get_sleepers_busts",
    capability="historical_analytics",
    description="The Fantasy Sleepers & Busts page's current sleeper and bust lists (as last shown on that page).",
    reuses=("applied_math_context.cache_fantasy_sleepers_ami_context (session snapshot, read-only)",),
    needs_session=True,
)
def get_sleepers_busts(*, session: Mapping[str, Any]) -> ToolResult:
    snap = session.get(SLEEPERS_KEY) if hasattr(session, "get") else None
    if not isinstance(snap, dict) or not (snap.get("sleeper_candidates") or snap.get("bust_risks")):
        return fail(
            "get_sleepers_busts",
            MISSING_DRAFT_CONTEXT,
            "Sleeper and bust lists come from the Fantasy Sleepers & Busts page — open it once so AMI can read them.",
        )
    keep = ("player", "Primary Position", "Market Rank", "Model Rank", "Fantasy Edge", "Sleeper Score", "reason", "Reason")

    def rows(key: str) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in r.items() if k in keep and isinstance(v, _SAFE_SCALARS)}
            for r in (snap.get(key) or [])
            if isinstance(r, Mapping)
        ][:8]

    return ToolResult(
        tool="get_sleepers_busts",
        ok=True,
        data={
            "fantasy_format": str(snap.get("fantasy_format") or ""),
            "sleepers": rows("sleeper_candidates"),
            "busts": rows("bust_risks"),
        },
    )
