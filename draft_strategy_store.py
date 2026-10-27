"""Saved Draft Strategies: named, reusable snapshots of the global working queue (Pro).

A strategy is a snapshot, never a second queue: drafting consumes the working queue
(draft_queue_contract) but never a saved strategy. Loading replaces the whole working queue
with the strategy's ordered players (never merges), after confirmation when the queue is not
empty, and leaves the strategy unchanged.

Storage is the account-scoped saved-items table (item_type ``draft_strategy``), so the account
and guest isolation of suite_storage_supabase applies; a single-user install without cloud
storage keeps a JSON file in its workspace. Signed-out guests cannot save. Every operation checks
the ``draft_strategy_library`` capability (FeatureId.DRAFT_STRATEGIES), which becomes Pro-only
when that feature is enforced.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any

ITEM_TYPE = "draft_strategy"
APP_ID = "baseball"
CAPABILITY = "draft_strategy_library"
SCHEMA_VERSION = 1
NAME_MAX = 80
APPROACHES = ("balanced", "best_available", "value_based", "positional_scarcity", "roster_aware")
_CONTEXT_KEYS = ("room_format", "room_window", "fantasy_draft_projection_style", "room_team_count", "room_rounds")


class StrategyError(RuntimeError):
    """A strategy operation was refused or failed; ``str(exc)`` is safe to show the user."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --- storage -----------------------------------------------------------------------------


class _CloudBackend:
    def put(self, key: str, title: str, payload: dict[str, Any]) -> None:
        import suite_storage_supabase as sss

        sss.upsert_saved_item(APP_ID, ITEM_TYPE, key, title=title, payload=payload)

    def all(self) -> list[dict[str, Any]]:
        import suite_storage_supabase as sss

        rows = sss.load_saved_items(app=APP_ID, item_type=ITEM_TYPE, limit=200)
        return [r["payload"] for r in rows or [] if isinstance(r, dict) and isinstance(r.get("payload"), dict)]

    def delete(self, key: str) -> None:
        import suite_storage_supabase as sss

        sss.invalidate_saved_item(APP_ID, ITEM_TYPE, key)


class _LocalBackend:
    """Single-user install without cloud storage: one JSON file in the active workspace."""

    def _path(self):
        from suite_workspace import resolve_workspace_id, workspace_dir

        return workspace_dir(resolve_workspace_id()) / "draft_strategies.json"

    def _read(self) -> dict[str, Any]:
        path = self._path()
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
        tmp.replace(path)

    def put(self, key: str, title: str, payload: dict[str, Any]) -> None:
        del title
        data = self._read()
        data[key] = payload
        self._write(data)

    def all(self) -> list[dict[str, Any]]:
        return [v for v in self._read().values() if isinstance(v, dict)]

    def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._write(data)


def _backend():
    try:
        from suite_storage_config import cloud_storage_enabled

        if cloud_storage_enabled():
            return _CloudBackend()
    except ImportError:
        pass
    return _LocalBackend()


def _require_access(session: dict[str, Any]) -> None:
    try:
        from suite_auth import is_anonymous_guest

        if is_anonymous_guest(session):
            raise StrategyError("Sign in to save and load draft strategies.")
    except ImportError:
        pass
    import baseball_monetization as bm
    from baseball_monetization_ui import current_entitlement

    if not bm.entitlement_for_capability(current_entitlement(session), CAPABILITY):
        raise StrategyError("Saved Draft Strategies are a Pro feature.")


def _store_call(fn, *args) -> Any:
    try:
        return fn(*args)
    except StrategyError:
        raise
    except Exception as exc:
        raise StrategyError(f"Couldn't reach saved strategies ({type(exc).__name__}); nothing was changed.") from exc


# --- model -------------------------------------------------------------------------------


def _queue(session: dict[str, Any]) -> list[str]:
    from draft_state import DRAFT_QUEUE_KEY, _normalize_player_list

    return _normalize_player_list(session.get(DRAFT_QUEUE_KEY))


def _entries_from_queue(session: dict[str, Any], notes: dict[str, str] | None) -> list[dict[str, Any]]:
    meta = session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {}
    notes = {str(k).lower(): str(v) for k, v in (notes or {}).items()}
    out = []
    for rank, name in enumerate(_queue(session), start=1):
        m = meta.get(name.lower()) if isinstance(meta.get(name.lower()), dict) else {}
        out.append({"rank": rank, "name": name, "player_id": str(m.get("player_id") or ""),
                    "position": str(m.get("position") or ""), "note": notes.get(name.lower(), "")})
    return out


def current_draft_context(session: dict[str, Any]) -> dict[str, Any]:
    """The draft settings a strategy was prepared under (copied, small)."""
    ctx = {k: copy.deepcopy(session.get(k)) for k in _CONTEXT_KEYS if session.get(k) not in (None, "")}
    shared = session.get("draft_shared_settings")
    if isinstance(shared, dict):
        ctx["shared_settings"] = {k: v for k, v in shared.items() if isinstance(v, (str, int, float, bool))}
    return ctx


def _clean_name(name: str, existing: list[dict[str, Any]], *, exclude_id: str = "") -> str:
    clean = " ".join(str(name or "").split())[:NAME_MAX]
    if not clean:
        raise StrategyError("Give the strategy a name.")
    if any(s.get("name", "").lower() == clean.lower() and s.get("id") != exclude_id for s in existing):
        raise StrategyError(f"You already have a strategy named “{clean}”.")
    return clean


def list_strategies(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Saved strategies, most recently updated first."""
    _require_access(session)
    rows = [s for s in _store_call(_backend().all) if s.get("schema_version") == SCHEMA_VERSION and s.get("id")]
    return sorted(rows, key=lambda s: str(s.get("updated_at") or ""), reverse=True)


def get_strategy(session: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    for s in list_strategies(session):
        if s.get("id") == strategy_id:
            return s
    raise StrategyError("That strategy no longer exists.")


def _put(strategy: dict[str, Any]) -> dict[str, Any]:
    _store_call(_backend().put, strategy["id"], strategy["name"], strategy)
    return strategy


def save_strategy(
    session: dict[str, Any],
    name: str,
    *,
    approach: str = "balanced",
    notes: dict[str, str] | None = None,
    explanations: list[str] | None = None,
) -> dict[str, Any]:
    """Save the current working queue as a new named strategy."""
    _require_access(session)
    entries = _entries_from_queue(session, notes)
    if not entries:
        raise StrategyError("Add players to your queue before saving a strategy.")
    now = _now()
    strategy = {
        "schema_version": SCHEMA_VERSION,
        "id": uuid.uuid4().hex[:12],
        "name": _clean_name(name, list_strategies(session)),
        "approach": approach if approach in APPROACHES else "balanced",
        "players": entries,
        "explanations": [str(x) for x in (explanations or [])][:20],
        "context": current_draft_context(session),
        "created_at": now,
        "updated_at": now,
    }
    return _put(strategy)


def update_strategy(session: dict[str, Any], strategy_id: str, *, confirm_overwrite: bool) -> dict[str, Any]:
    """Overwrite a strategy's players with the current working queue (explicit, confirmed)."""
    if not confirm_overwrite:
        raise StrategyError("Confirm before replacing this strategy's players with your current queue.")
    current = get_strategy(session, strategy_id)
    entries = _entries_from_queue(session, {p["name"]: p.get("note", "") for p in current.get("players") or []})
    if not entries:
        raise StrategyError("Your queue is empty; the strategy was not changed.")
    updated = {**copy.deepcopy(current), "players": entries, "context": current_draft_context(session), "updated_at": _now()}
    return _put(updated)


def rename_strategy(session: dict[str, Any], strategy_id: str, new_name: str) -> dict[str, Any]:
    current = get_strategy(session, strategy_id)
    name = _clean_name(new_name, list_strategies(session), exclude_id=strategy_id)
    return _put({**copy.deepcopy(current), "name": name, "updated_at": _now()})


def duplicate_strategy(session: dict[str, Any], strategy_id: str, new_name: str = "") -> dict[str, Any]:
    current = get_strategy(session, strategy_id)
    existing = list_strategies(session)
    name = _clean_name(new_name or f"{current['name']} (copy)", existing)
    now = _now()
    return _put({**copy.deepcopy(current), "id": uuid.uuid4().hex[:12], "name": name, "created_at": now, "updated_at": now})


def delete_strategy(session: dict[str, Any], strategy_id: str, *, confirmed: bool) -> None:
    if not confirmed:
        raise StrategyError("Confirm before deleting this strategy.")
    get_strategy(session, strategy_id)
    _store_call(_backend().delete, strategy_id)


def load_strategy(session: dict[str, Any], strategy_id: str, *, confirm_replace: bool = False) -> dict[str, Any]:
    """Replace the whole working queue with the strategy's ordered players.

    Returns ``{"needs_confirmation": True, ...}`` (and changes nothing) when the queue is not empty
    and ``confirm_replace`` is False. The strategy itself is never modified.
    """
    strategy = get_strategy(session, strategy_id)
    names = [str(p.get("name") or "").strip() for p in sorted(strategy.get("players") or [], key=lambda p: int(p.get("rank") or 0))]
    names = [n for n in names if n]
    current = _queue(session)
    if current and not confirm_replace:
        return {
            "needs_confirmation": True,
            "message": (
                f"Loading this strategy will replace your current {len(current)}-player queue with the "
                f"{len(names)} players in {strategy['name']}. Continue?"
            ),
        }
    from draft_state import sync_draft_queue

    meta = session.get("_queue_player_meta") if isinstance(session.get("_queue_player_meta"), dict) else {}
    meta = dict(meta)
    for p in strategy.get("players") or []:
        key = str(p.get("name") or "").strip().lower()
        if key and p.get("player_id"):
            meta[key] = {**(meta.get(key) or {}), "player_id": p["player_id"],
                         "position": (meta.get(key) or {}).get("position") or p.get("position") or "—",
                         "team": (meta.get(key) or {}).get("team") or "—"}
    sync_draft_queue(session, names, reason="load_saved_strategy")
    session["_queue_player_meta"] = meta
    return {"needs_confirmation": False, "loaded": len(names), "warnings": _context_warnings(strategy, session)}


def _context_warnings(strategy: dict[str, Any], session: dict[str, Any]) -> list[str]:
    saved, now = strategy.get("context") or {}, current_draft_context(session)
    labels = {"room_format": "scoring format", "room_team_count": "number of teams", "room_rounds": "rounds",
              "room_window": "projection window", "fantasy_draft_projection_style": "projection style"}
    out = []
    for key, label in labels.items():
        if key in saved and key in now and saved[key] != now[key]:
            out.append(f"This strategy was prepared for {label} {saved[key]}; your current draft uses {now[key]}.")
    return out
