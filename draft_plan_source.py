"""Which plan a draft starts from: the Global Queue (default) or a saved Pro strategy (S2).

The choice is per draft (Solo, Live/Shared, Simulator) and lives in that draft's own adaptive state
(``draft_queue_adaptive[<source>]["draft_plan_source"]``), so it is personal and never reaches the
Shared Draft room (draft_room_shared_state lists these keys as private).

Choosing a strategy copies its queue, pins, notes, research and approach into the draft: the
copy is this draft's Fixed plan, and Adaptive re-orders a separate working order from it, as it
does for the Global Queue. Neither the saved strategy nor the Global Queue changes, unless the
user explicitly saves the draft's copy back (``save_back``, confirmed and revision-checked).
Auto Pick is not involved: it follows the room's rule and never reads any queue or plan.
"""

from __future__ import annotations

import copy
from typing import Any

KEY = "draft_plan_source"
GLOBAL = "global"


def _state(session: dict[str, Any], source: str) -> dict[str, Any] | None:
    states = session.get("draft_queue_adaptive")
    st = states.get(source) if isinstance(states, dict) else None
    return st if isinstance(st, dict) else None


def current(session: dict[str, Any], source: str) -> dict[str, Any] | None:
    """This draft's strategy plan (a copy), or None when it follows the Global Queue."""
    if not source:
        return None
    st = _state(session, source)
    plan = (st or {}).get(KEY)
    return plan if isinstance(plan, dict) and plan.get("kind") == "strategy" else None


def plan_queue(session: dict[str, Any], source: str) -> list[str] | None:
    plan = current(session, source)
    return list(plan.get("queue") or []) if plan else None


def _copy_of(session: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    import draft_strategy_v2 as v2

    s = v2.get_strategy_v2(session, strategy_id)
    research: dict[str, str] = {}
    try:
        for entry in v2.research_log(session, strategy_id):
            if entry.get("player_key"):
                research[str(entry["player_key"])] = str(entry.get("text") or "")
    except Exception:
        research = {}
    return {"kind": "strategy", "id": s["id"], "name": s["name"], "approach": s["approach"],
            "revision": s["revision"], "updated_at": s["updated_at"],
            "queue": [e["name"] for e in s["queue"]],
            "pins": [p for p in s["pins"]],
            "notes": {k: str(v.get("text") or "") for k, v in (s.get("notes") or {}).items()},
            "research": research, "preferences": copy.deepcopy(s.get("preferences") or {}),
            "edited": False}


def choose(session: dict[str, Any], source: str, choice: str) -> str:
    """Use the Global Queue (``"global"``) or a saved strategy id as this draft's plan.

    Returns a message for the user. The draft's Adaptive order and original-plan snapshot restart
    from the new plan; the strategy's approach becomes the selected strategy approach."""
    st = _state(session, source)
    if st is None:
        return "Open the draft first."
    if not choice or choice == GLOBAL:
        st.pop(KEY, None)
        msg = "This draft now follows your Global Queue."
    else:
        plan = _copy_of(session, choice)
        st[KEY] = plan
        if plan["approach"]:
            session["draft_strategy_approach"] = plan["approach"]
        msg = (f"This draft now follows “{plan['name']}” ({len(plan['queue'])} players). Your saved strategy "
               "and your Global Queue are not changed.")
    # Recalculate from the new plan: the order, the audit trail and the original plan restart.
    st["orders"], st["history"], st["sig"], st["reviewed_at"] = {}, [], None, 0
    st.pop("snapshot", None)
    try:
        from draft_queue_modes import mark_personal_change

        mark_personal_change(session)
    except ImportError:
        pass
    return msg


def set_pins(session: dict[str, Any], source: str, names: list[str]) -> None:
    plan = current(session, source)
    if plan is not None:
        plan["pins"] = [str(n).strip().lower() for n in names if str(n).strip()]
        plan["edited"] = True


def set_note(session: dict[str, Any], source: str, name: str, text: str) -> None:
    plan = current(session, source)
    key = str(name or "").strip().lower()
    if plan is None or not key:
        return
    body = str(text or "").strip()[:500]
    if body:
        plan["notes"][key] = body
    else:
        plan["notes"].pop(key, None)
    plan["edited"] = True


def add_player(session: dict[str, Any], source: str, name: str) -> None:
    plan = current(session, source)
    if plan is not None and name.strip().lower() not in {q.lower() for q in plan["queue"]}:
        plan["queue"].append(name.strip())
        plan["edited"] = True


def notes(plan: dict[str, Any]) -> dict[str, str]:
    """The plan's notes for explanations (research findings fill in where there is no note)."""
    out = {k: f"Research: {v}" for k, v in (plan.get("research") or {}).items() if v}
    out.update({k: v for k, v in (plan.get("notes") or {}).items() if v})
    return out


def save_back(session: dict[str, Any], source: str, *, confirmed: bool) -> dict[str, Any]:
    """Write this draft's copy (order, pins, notes) back to the saved strategy (explicit).

    Refused when the saved strategy changed since this draft copied it (another tab or device)."""
    import draft_strategy_v2 as v2
    from draft_strategy_store import StrategyError

    if not confirmed:
        raise StrategyError("Confirm before saving this draft's plan back to the strategy.")
    plan = current(session, source)
    if plan is None:
        raise StrategyError("This draft follows your Global Queue; there is no strategy to save back to.")
    s = v2.get_strategy_v2(session, plan["id"])
    if s["revision"] != plan["revision"] or s["updated_at"] != plan["updated_at"]:
        raise StrategyError(f"“{plan['name']}” was changed somewhere else since this draft copied it. "
                            "Nothing was saved; choose it again to start from the newer version.")
    base = s["revision"]
    by_key = {v2.player_key(e["name"]): e for e in s["queue"]}
    s = v2.replace_queue(s, [by_key.get(q.lower(), {"name": q, "source": "draft_plan"}) for q in plan["queue"]])
    want = [p for p in plan["pins"] if p in {q.lower() for q in plan["queue"]}][:v2.PINS_MAX]
    for key in [p for p in s["pins"] if p not in want]:
        s = v2.unpin(s, key)
    for key in [p for p in want if p not in s["pins"]]:
        s = v2.pin(s, next(q for q in plan["queue"] if q.lower() == key))
    for key, text in plan["notes"].items():
        name = next((q for q in plan["queue"] if q.lower() == key), key)
        current_note = (s["notes"].get(key) or {}).get("text")
        if text != current_note:
            s = v2.set_note(s, name, text[:v2.NOTE_MAX])
    for key in [k for k in s["notes"] if k not in plan["notes"]]:
        s = v2.set_note(s, key, "")
    saved = v2.save_strategy_v2(session, s, base)
    plan.update({"revision": saved["revision"], "updated_at": saved["updated_at"], "edited": False})
    return saved
