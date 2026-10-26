"""``ask()``: one question in, one grounded read-only answer out, with timings."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, MutableMapping

import pandas as pd

from ami_assistant.capabilities import GROUNDING_LABELS
from ami_assistant.context import build_ami_context
from ami_assistant.conversation import Turn, load_conversation, save_conversation
from ami_assistant.data import BaseballDataset, dataset_from_yearly, load_standalone_dataset
from ami_assistant.fantasy_router import FANTASY_INTENTS
from ami_assistant.provider import AnswerProvider, ComposeRequest, DeterministicProvider
from ami_assistant.router import STAT_INTENTS, Router
from ami_assistant.tools import REGISTRY

log = logging.getLogger(__name__)
MAX_QUESTION_CHARS = 500


@dataclass
class AmiResponse:
    answer: str
    intent: str
    grounding: str
    grounding_label: str
    basis: list[str] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    context_summary: str = ""
    used_context: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    provider: str = ""
    error: bool = False


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def ask(
    question: str,
    *,
    session_state: MutableMapping[str, Any] | None = None,
    active_page: str = "",
    yearly_df: pd.DataFrame | None = None,
    dataset: BaseballDataset | None = None,
    provider: AnswerProvider | None = None,
    remember: bool = True,
    entitlement: Any = None,
) -> AmiResponse:
    """``entitlement``: the plan snapshot the host already resolved this run (the same one its page
    gate uses). Tools tied to an enforced plan feature check it; AMI never resolves it itself."""
    t_all = time.perf_counter()
    timings: dict[str, float] = {}
    q = str(question or "").strip()[:MAX_QUESTION_CHARS]
    session = session_state if session_state is not None else {}
    try:
        t = time.perf_counter()
        ctx = build_ami_context(session, active_page)
        conv = load_conversation(session)
        timings["context_ms"] = _ms(t)

        t = time.perf_counter()
        if dataset is None:
            dataset = dataset_from_yearly(yearly_df) if yearly_df is not None else load_standalone_dataset()
        timings["dataset_ms"] = _ms(t)

        t = time.perf_counter()
        plan = Router(dataset).route(q, ctx, conv)
        timings["route_ms"] = _ms(t)

        t = time.perf_counter()
        results: dict[str, list[Any]] = {}
        tool_log: list[dict[str, Any]] = []
        for call in plan.calls:
            res = REGISTRY.call(call.name, call.args, dataset=dataset, session=session, entitlement=entitlement)
            results.setdefault(call.name, []).append(res)
            tool_log.append({"tool": call.name, "ok": res.ok, "ms": res.elapsed_ms, "error_code": res.error_code})
        timings["tools_ms"] = _ms(t)

        t = time.perf_counter()
        provider = provider or DeterministicProvider(dataset.latest_season, dataset.first_season)
        composed = provider.compose(
            ComposeRequest(
                question=q,
                plan=plan,
                results=results,
                context=ctx.as_dict(),
                tool_schemas=REGISTRY.schemas(),
            )
        )
        timings["compose_ms"] = _ms(t)

        ok = all(entry["ok"] for entry in tool_log)
        if remember and session_state is not None:
            if plan.intent in STAT_INTENTS and ok:
                conv.remember(
                    intent=plan.intent,
                    player_ids=[p.player_id for p in plan.players],
                    player_names=[p.name for p in plan.players],
                    year_range=list(plan.year_range) if plan.year_range else None,
                    window=plan.window,
                    stats=plan.stats if plan.intent in ("compare", "leaderboard") else [],
                    position=plan.position,
                    page=ctx.page,
                )
            elif plan.intent in FANTASY_INTENTS:
                # Same league/team every turn (resolved fresh); remember the slot, player and week.
                conv.remember(intent=plan.intent, position=plan.position, page=ctx.page,
                              subject_player=plan.subject, week=plan.week)
            conv.add_turn(Turn(q, composed.text, plan.intent, plan.grounding, [e["tool"] for e in tool_log]))
            save_conversation(session_state, conv)
        timings["total_ms"] = _ms(t_all)
        return AmiResponse(
            answer=composed.text,
            intent=plan.intent,
            grounding=plan.grounding,
            grounding_label=GROUNDING_LABELS.get(plan.grounding, ""),
            basis=composed.basis,
            tools=tool_log,
            context_summary=ctx.summary(),
            used_context=list(plan.used_context),
            timings_ms=timings,
            provider=getattr(provider, "name", ""),
        )
    except Exception:
        log.exception("AMI assistant failed for page %s", active_page)
        timings["total_ms"] = _ms(t_all)
        return AmiResponse(
            answer="Sorry — I hit a problem answering that. Try rephrasing, or ask about a specific player or page.",
            intent="error",
            grounding="",
            grounding_label="",
            timings_ms=timings,
            error=True,
        )
