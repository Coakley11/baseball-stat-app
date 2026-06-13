"""Shared helpers for AMI grounded and quality audit runners."""

from __future__ import annotations

import json
import re
from typing import Any

GENERIC_FILLER = (
    "no clear remaining",
    "no clear next pick",
    "catcher scarcity is tightening",
    "attach ops/war/hr comparison",
    "consult expert rankings",
    "attach draft_snapshot",
    "without context",
)
INVENTED_PICK_RE = re.compile(r"\bpick\s+\*?\*?19\b", re.I)

RECOMMENDATION_WORDS = (
    "recommend",
    "lean",
    "draft",
    "take",
    "prioritize",
    "target",
    "prefer",
    "choose",
    "yes",
    "no",
    "worth",
    "avoid",
    "wait",
    "likely",
    "next",
    "selected",
    "plausible",
    "lead",
    "leads",
    "best",
    "value",
    "run",
)
WHY_WORDS = (
    "because",
    "fit",
    "need",
    "gap",
    "rank",
    "edge",
    "market rank",
    "fantasy edge",
    "slope",
    "r²",
    "r2",
    "valuation",
    "score",
    "available",
    "drafted",
)
ALTERNATIVE_WORDS = (
    "alternative",
    "instead",
    " vs ",
    "versus",
    "compare",
    "tradeoff",
    "over",
    "after",
    "or ",
    "pivot",
)
EVIDENCE_WORDS = (
    "market rank",
    "fantasy edge",
    "rank",
    "edge",
    "adp",
    "pick",
    "round",
    "roster",
    "position",
    "category",
    "slope",
    "trend",
    "filter",
    "hr",
    "sb",
    "available",
    "drafted",
)


def solver_text(result: Any) -> str:
    parts = [
        str(getattr(result, "short_answer", "") or ""),
        str(getattr(result, "why", "") or ""),
        str(getattr(result, "interpretation", "") or ""),
        str(getattr(result, "sensitivity_plain", "") or ""),
    ]
    coach = (getattr(result, "computed", None) or {}).get("coach_sections")
    if isinstance(coach, dict):
        for key in ("direct_answer", "analyst_framing", "tradeoffs", "scarcity", "formatted_answer"):
            parts.append(str(coach.get(key) or ""))
    return "\n".join(p for p in parts if p.strip())


def direct_answer_text(full_text: str) -> str:
    """First recommendation block — less context suffix noise."""
    chunk = full_text.split("Context:")[0].strip()
    parts = [p.strip() for p in chunk.split("\n\n") if p.strip()]
    return parts[0] if parts else chunk


def context_pick_round(ctx: dict[str, Any]) -> tuple[int | None, int | None]:
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


def drafted_names(ctx: dict[str, Any]) -> set[str]:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    names: set[str] = set()
    for src in (ctx.get("drafted_players"), snap.get("drafted_players"), snap.get("canonical_drafted_players")):
        if isinstance(src, list):
            for n in src:
                names.add(str(n).split(" (")[0].strip().lower())
    return names


def pool_player_names(ctx: dict[str, Any], *, limit: int = 12) -> list[str]:
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    out: list[str] = []
    seen: set[str] = set()
    for pool in (
        snap.get("available_players"),
        ctx.get("available_players"),
        snap.get("best_available_players"),
        ctx.get("best_available"),
        snap.get("recommended_players"),
        ctx.get("recommended_players"),
    ):
        if not isinstance(pool, list):
            continue
        for row in pool:
            if isinstance(row, dict):
                name = str(row.get("player") or row.get("Player") or "").strip()
            else:
                name = str(row).split(" (")[0].strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
            if len(out) >= limit:
                return out
    return out


def check_pick_round_grounding(ctx: dict[str, Any], text: str) -> list[str]:
    failures: list[str] = []
    low = text.lower()
    ctx_pick, ctx_round = context_pick_round(ctx)
    if INVENTED_PICK_RE.search(text):
        failures.append("Cites invented pick 19")
    if ctx_pick is not None:
        m = re.search(r"pick\s+\*?\*?(\d+)", low)
        if m and int(m.group(1)) != ctx_pick and "pick and round not" not in low:
            failures.append(f"Wrong pick cited ({m.group(1)} vs context {ctx_pick})")
    elif re.search(r"pick\s+\*?\*?\d+", text):
        if not any(p in low for p in ("pick and round not", "pick not in context", "do not have enough")):
            failures.append("Cited specific pick when context has no current_pick")
    if ctx_round is not None:
        m = re.search(r"round\s+\*?\*?(\d+)", low)
        if m and int(m.group(1)) != ctx_round and "round not in context" not in low:
            failures.append(f"Wrong round cited ({m.group(1)} vs context {ctx_round})")
    return failures


def check_no_generic_filler(text: str) -> list[str]:
    low = text.lower()
    return [f"Generic filler: {phrase}" for phrase in GENERIC_FILLER if phrase in low]


def check_recommends(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in RECOMMENDATION_WORDS)


def check_explains_why(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in WHY_WORDS)


def check_compares_alternatives(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in ALTERNATIVE_WORDS)


def check_has_evidence(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in EVIDENCE_WORDS)


def check_names_present(text: str, names: tuple[str, ...], *, full_text: str = "") -> list[str]:
    low = text.lower()
    full_low = (full_text or text).lower()
    missing: list[str] = []
    for n in names:
        token = n.lower()
        if token not in low and token not in full_low:
            missing.append(n)
    return [f"Missing required name: {n}" for n in missing]


def check_forbidden_names(text: str, names: tuple[str, ...]) -> list[str]:
    low = direct_answer_text(text).lower()
    return [f"Unrelated player in recommendation: {n}" for n in names if n.lower() in low]


def check_not_recommending_drafted(ctx: dict[str, Any], text: str) -> list[str]:
    drafted = drafted_names(ctx)
    direct = direct_answer_text(text).lower()
    failures: list[str] = []
    for name in drafted:
        if not name:
            continue
        # "already drafted" / "off the board" is fine
        if name in direct and not any(p in direct for p in ("already drafted", "off the board", "not available", "already off")):
            if any(w in direct for w in ("lean", "take", "draft", "recommend", "pick")):
                failures.append(f"May recommend drafted player {name} without noting unavailable")
    return failures


def check_scarcity_has_players(text: str, pool: list[str]) -> list[str]:
    low = text.lower()
    if "scarcity" not in low and "thin" not in low and "tier" not in low:
        return []
    if pool and not any(p.split()[0].lower() in low or p.lower() in low for p in pool[:4]):
        return ["Mentions scarcity/tier without naming specific available players"]
    return []


def context_blob(ctx: dict[str, Any]) -> str:
    return json.dumps(ctx, default=str).lower()
