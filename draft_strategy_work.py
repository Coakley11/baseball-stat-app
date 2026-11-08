"""Working copies of Pro Draft Strategies being edited on the Draft Strategy page (S2).

Each open strategy has its own working copy in this browser session (``WORK_KEY``), with the
revision and ``updated_at`` it was opened at. Edits change only that copy; switching to another
strategy keeps it (and its "unsaved changes" mark) until the user saves or discards it. Saving goes
through ``draft_strategy_v2.save_strategy_v2``, which refuses when the stored strategy changed
since (another tab or device), so newer work is never silently overwritten.

The Global Queue (``draft_queue``, the Free general-purpose queue) is never read or written here,
except by the two explicit, confirmed transfers:

- ``copy_global_into`` puts the Global Queue's players into this strategy's working copy
  (replace, or add the missing ones to the end). The Global Queue is unchanged.
- ``replace_global_with`` replaces the Global Queue with this strategy's players. The strategy is
  unchanged.

Working copies are session-only (not saved with the workspace) and are dropped on sign-out or an
account switch (draft_queue_contract.clear_queue_for_account_change).
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import draft_strategy_store as store
import draft_strategy_v2 as v2
from draft_strategy_store import StrategyError

WORK_KEY = "_draft_strategy_work"     # {strategy_id: {"strategy", "base_revision", "base_updated_at", "dirty", "new"}}
OPEN_KEY = "_draft_strategy_open_id"  # the strategy shown in the editor
SESSION_KEYS = (WORK_KEY, OPEN_KEY)


def _work(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    work = session.get(WORK_KEY)
    if not isinstance(work, dict):
        work = {}
        session[WORK_KEY] = work
    return work


def _record(strategy: dict[str, Any], *, new: bool = False) -> dict[str, Any]:
    s = v2.upgrade(strategy)
    return {"strategy": s, "base_revision": None if new else s["revision"],
            "base_updated_at": None if new else s["updated_at"], "dirty": bool(new), "new": bool(new)}


def open_strategy(session: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    """The working copy of a saved strategy (loaded once; an existing copy keeps its edits)."""
    work = _work(session)
    if strategy_id not in work:
        work[strategy_id] = _record(v2.get_strategy_v2(session, strategy_id))
    session[OPEN_KEY] = strategy_id
    return work[strategy_id]


def current(session: dict[str, Any]) -> dict[str, Any] | None:
    sid = session.get(OPEN_KEY)
    rec = _work(session).get(sid) if sid else None
    return rec if isinstance(rec, dict) else None


def is_dirty(session: dict[str, Any], strategy_id: str) -> bool:
    rec = _work(session).get(strategy_id)
    return bool(isinstance(rec, dict) and rec.get("dirty"))


def dirty_ids(session: dict[str, Any]) -> list[str]:
    return [sid for sid, rec in _work(session).items() if isinstance(rec, dict) and rec.get("dirty")]


def create(session: dict[str, Any], name: str, *, approach: str = "balanced", from_global: bool = False,
           pool: Any = None) -> dict[str, Any]:
    """A new, unsaved strategy (blank or a copy of the Global Queue); opened in the editor."""
    store._require_access(session)
    names = {str(s.get("name") or "").lower() for s in store.list_strategies(session)}
    names |= {str(r["strategy"]["name"]).lower() for r in _work(session).values() if r.get("new")}
    clean = " ".join(str(name or "").split())[:store.NAME_MAX]
    if clean.lower() in names:
        raise StrategyError(f"You already have a strategy named “{clean}”.")
    queue = _global_entries(session, pool) if from_global else []
    s = v2.new_strategy(clean, approach=approach if approach in store.APPROACHES else "balanced", queue=queue,
                        created_from="global_queue" if from_global else "blank",
                        context=store.current_draft_context(session))
    if from_global:  # the Global Queue's own research notes come along (as the v1 save did, S0)
        try:
            from draft_queue_modes import notes_for

            queued = {v2.player_key(e["name"]): e["name"] for e in s["queue"]}
            for key, text in notes_for(session).items():
                if key in queued and str(text or "").strip():
                    s = v2.set_note(s, queued[key], str(text).strip()[:v2.NOTE_MAX])
        except ImportError:
            pass
        s = {**s, "revision": 0, "edits": []}  # a new strategy starts its history at its first save
    _work(session)[s["id"]] = _record(s, new=True)
    session[OPEN_KEY] = s["id"]
    return _work(session)[s["id"]]


def edit(session: dict[str, Any], strategy_id: str, op: Callable[..., dict[str, Any]], *args: Any,
         **kwargs: Any) -> dict[str, Any]:
    """Apply one draft_strategy_v2 edit to the working copy only (StrategyError leaves it as it was)."""
    rec = _work(session).get(strategy_id)
    if not isinstance(rec, dict):
        raise StrategyError("Open the strategy before editing it.")
    updated = op(rec["strategy"], *args, **kwargs)
    if updated is not rec["strategy"] and updated != rec["strategy"]:
        rec["strategy"] = updated
        rec["dirty"] = True
    return rec


def save(session: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    rec = _work(session).get(strategy_id)
    if not isinstance(rec, dict):
        raise StrategyError("Open the strategy before saving it.")
    saved = v2.save_strategy_v2(session, rec["strategy"], rec["base_revision"])
    _work(session)[strategy_id] = _record(saved)
    return saved


def discard(session: dict[str, Any], strategy_id: str) -> None:
    """Drop unsaved edits: a saved strategy reopens as stored, a new unsaved one is removed."""
    rec = _work(session).pop(strategy_id, None)
    if isinstance(rec, dict) and rec.get("new") and session.get(OPEN_KEY) == strategy_id:
        session.pop(OPEN_KEY, None)


def forget(session: dict[str, Any], strategy_id: str) -> None:
    _work(session).pop(strategy_id, None)
    if session.get(OPEN_KEY) == strategy_id:
        session.pop(OPEN_KEY, None)


# --- transfers between the Global Queue and a strategy ---------------------------------------


def _global_names(session: dict[str, Any]) -> list[str]:
    return store._queue(session)


def _global_entries(session: dict[str, Any], pool: Any = None) -> list[dict[str, Any]]:
    from draft_strategy_ids import with_ids

    meta = session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {}
    out = []
    for name in _global_names(session):
        m = meta.get(name.lower()) if isinstance(meta.get(name.lower()), dict) else {}
        out.append(with_ids({"name": name, "player_id": str(m.get("player_id") or ""),
                             "position": str(m.get("position") or "").replace("—", ""),
                             "team": str(m.get("team") or "").replace("—", "")}, pool))
    return out


def _counts(before: list[str], after: list[str]) -> dict[str, int]:
    b, a = [n.lower() for n in before], [n.lower() for n in after]
    kept = [n for n in a if n in set(b)]
    order_changed = [n for n in b if n in set(a)] != kept
    return {"before": len(b), "after": len(a), "added": len([n for n in a if n not in set(b)]),
            "removed": len([n for n in b if n not in set(a)]), "kept": len(kept), "reordered": int(order_changed)}


def preview_copy_global(session: dict[str, Any], strategy_id: str, *, mode: str = "replace") -> dict[str, Any]:
    """What "Copy Global Queue into This Strategy" would do (changes nothing)."""
    rec = _work(session).get(strategy_id)
    if not isinstance(rec, dict):
        raise StrategyError("Open the strategy first.")
    source = _global_names(session)
    dest = [e["name"] for e in rec["strategy"]["queue"]]
    after = list(source) if mode == "replace" else dest + [n for n in source if n.lower() not in {d.lower() for d in dest}]
    counts = _counts(dest, after)
    return {"source": "Global Queue", "destination": rec["strategy"]["name"], "mode": mode, **counts,
            "needs_confirmation": bool(dest) and (counts["removed"] > 0 or counts["reordered"] > 0),
            "source_count": len(source), "empty_source": not source}


def copy_global_into(session: dict[str, Any], strategy_id: str, *, mode: str = "replace", confirmed: bool = False,
                     pool: Any = None) -> dict[str, Any]:
    """Put the Global Queue's players into this strategy's working copy (Save to keep it)."""
    preview = preview_copy_global(session, strategy_id, mode=mode)
    if preview["empty_source"]:
        raise StrategyError("Your Global Queue is empty; nothing was copied.")
    if preview["needs_confirmation"] and not confirmed:
        raise StrategyError("Confirm before replacing this strategy's players.")
    entries = _global_entries(session, pool)
    if mode == "replace":
        edit(session, strategy_id, v2.replace_queue, entries, context=store.current_draft_context(session))
    else:
        rec = _work(session)[strategy_id]
        have = {v2.player_key(e["name"]) for e in rec["strategy"]["queue"]}
        missing = [e for e in entries if v2.player_key(e["name"]) not in have]
        if len(have) + len(missing) > v2.QUEUE_MAX:
            raise StrategyError(f"A strategy can hold up to {v2.QUEUE_MAX} players; nothing was copied.")
        for e in missing:
            edit(session, strategy_id, v2.insert, {**e, "source": "global_queue"})
    return preview


def preview_replace_global(session: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    """What "Replace Global Queue with This Strategy" would do (changes nothing)."""
    rec = _work(session).get(strategy_id)
    if not isinstance(rec, dict):
        raise StrategyError("Open the strategy first.")
    names = [e["name"] for e in rec["strategy"]["queue"]]
    current_q = _global_names(session)
    counts = _counts(current_q, names)
    return {"source": rec["strategy"]["name"], "destination": "Global Queue", **counts,
            "needs_confirmation": bool(current_q), "unsaved": bool(rec.get("dirty")), "empty_source": not names}


def replace_global_with(session: dict[str, Any], strategy_id: str, *, confirmed: bool = False) -> dict[str, Any]:
    """Replace the Global Queue with this strategy's players (as shown, including unsaved edits).

    The strategy itself is not changed or saved. The Global Queue records where it came from
    (``_draft_strategy_loaded``), so Adaptive explanations can use the strategy's notes."""
    preview = preview_replace_global(session, strategy_id)
    if preview["empty_source"]:
        raise StrategyError("This strategy has no players; your Global Queue was not changed.")
    if preview["needs_confirmation"] and not confirmed:
        raise StrategyError("Confirm before replacing your Global Queue.")
    from draft_state import sync_draft_queue

    s = _work(session)[strategy_id]["strategy"]
    meta = dict(session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {})
    for e in s["queue"]:
        key = e["name"].strip().lower()
        prev = meta.get(key) if isinstance(meta.get(key), dict) else {}
        meta[key] = {**prev, "player_id": prev.get("player_id") or e.get("player_id") or "",
                     "position": prev.get("position") or e.get("position") or "—", "team": prev.get("team") or e.get("team") or "—"}
    sync_draft_queue(session, [e["name"] for e in s["queue"]], reason="replace_global_queue_with_strategy")
    session["_queue_player_meta"] = meta
    session[store.LOADED_KEY] = store.loaded_record(s, store._queue(session))
    try:
        from draft_queue_modes import mark_personal_change

        mark_personal_change(session)
    except ImportError:
        pass
    return preview


def snapshot_for_tests(session: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(_work(session))
