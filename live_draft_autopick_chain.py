"""On-page auto-pick advancement chain — shows where timer→pick→advance stops."""

from __future__ import annotations

import time
from typing import Any

AUTOPICK_CHAIN_KEY = "_live_draft_autopick_chain"

# Ordered stages for the expire → advance pipeline.
CHAIN_STAGES = (
    "timer_hit_zero",
    "auto_pick_selected",
    "auto_pick_applied",
    "board_advanced",
    "next_timer_started",
)


def _chain(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(AUTOPICK_CHAIN_KEY)
    if isinstance(raw, dict):
        return raw
    return {
        "stages": {},
        "stopped_at": None,
        "last_error": None,
        "pick_index": None,
        "selected_player": None,
        "updated_at": None,
    }


def reset_autopick_chain(session: dict[str, Any], *, pick_index: int | None = None) -> dict[str, Any]:
    chain = {
        "stages": {name: {"ok": False, "ts": None, "detail": ""} for name in CHAIN_STAGES},
        "stopped_at": None,
        "last_error": None,
        "pick_index": pick_index,
        "selected_player": None,
        "updated_at": time.time(),
    }
    session[AUTOPICK_CHAIN_KEY] = chain
    return chain


def note_autopick_chain(
    session: dict[str, Any],
    stage: str,
    *,
    ok: bool = True,
    detail: str = "",
    error: str | None = None,
    selected_player: str | None = None,
    pick_index: int | None = None,
) -> dict[str, Any]:
    chain = _chain(session)
    stages = dict(chain.get("stages") or {})
    if stage not in stages:
        stages[stage] = {"ok": False, "ts": None, "detail": ""}
    stages[stage] = {
        "ok": bool(ok),
        "ts": time.time(),
        "detail": str(detail or ""),
    }
    chain["stages"] = stages
    chain["updated_at"] = time.time()
    if pick_index is not None:
        chain["pick_index"] = pick_index
    if selected_player is not None:
        chain["selected_player"] = selected_player
    if error:
        chain["last_error"] = str(error)
        chain["stopped_at"] = stage
    elif ok:
        # Clearest stop point = first incomplete stage after last success.
        stopped = None
        for name in CHAIN_STAGES:
            entry = stages.get(name) or {}
            if not entry.get("ok"):
                stopped = name
                break
        chain["stopped_at"] = stopped
        if stage == CHAIN_STAGES[-1] and ok:
            chain["last_error"] = None
            chain["stopped_at"] = None
    else:
        chain["stopped_at"] = stage
        if error:
            chain["last_error"] = str(error)
    session[AUTOPICK_CHAIN_KEY] = chain
    return chain


def format_autopick_chain_banner(session: dict[str, Any]) -> str:
    chain = _chain(session)
    stages = chain.get("stages") or {}
    parts: list[str] = []
    for name in CHAIN_STAGES:
        entry = stages.get(name) or {}
        mark = "✓" if entry.get("ok") else "·"
        parts.append(f"{mark}{name}")
    stopped = chain.get("stopped_at")
    err = chain.get("last_error")
    player = chain.get("selected_player") or "—"
    idx = chain.get("pick_index")
    line = (
        f"**AUTOPICK CHAIN:** {' → '.join(parts)}  \n"
        f"pick_index=`{idx}` · selected=`{player}` · "
        f"stopped_at=`{stopped or 'complete'}`"
    )
    if err:
        line += f" · error=`{err}`"
    return line


def render_autopick_chain_banner(st: Any, session: dict[str, Any]) -> None:
    chain = session.get(AUTOPICK_CHAIN_KEY)
    if not isinstance(chain, dict) or not chain.get("stages"):
        return
    st.markdown(format_autopick_chain_banner(session))
    stopped = chain.get("stopped_at")
    if stopped:
        st.caption(f"Auto-pick chain stopped at **{stopped}** — draft will not advance until this step succeeds.")
