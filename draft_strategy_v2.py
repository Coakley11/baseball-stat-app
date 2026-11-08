"""Saved Draft Strategy v2: each strategy is its own editable queue (Pro). S1: store only, not wired.

A v2 strategy is a superset of v1 (draft_strategy_store): the same ``draft_strategy`` item type
and key (the strategy id), and the v1 fields kept as a mirror, so v1 readers (``players`` in rank
order, ``name``, ``approach``, ``context``) still work and Load into queue is unchanged::

    {schema_version: 2, id, name, created_at, updated_at, revision: int, approach,
     queue: [{name, player_id, position, team, added_at, source}],     # the strategy's own queue
     players: [{rank, name, player_id, position, note}],                # v1 mirror of queue + notes
     notes: {player_key: {text, updated_at, source: user | ami_confirmed}},
     pins: [player_key], priorities: {}, preferences: {}, settings: {},
     context: {}, explanations: [str],
     provenance: {migrated_from, migrated_at, created_from},
     edits: [{rev, at, ops: [{op, ...}], actor}]}                       # last 50

Rules:
- ``upgrade`` turns any v1 row into v2 in memory; it is idempotent and never writes. A v1 row is
  only written as v2 by ``save_strategy_v2`` after the user's first edit, and a one-time backup of
  the v1 row (item type ``draft_strategy_v1_backup``, same key) is stored first.
- Edit operations are pure: each returns a new dict with ``revision`` + 1, an ``edits`` entry and
  the ``players`` mirror rebuilt. ``updated_at`` only changes when the strategy is saved.
- ``save_strategy_v2`` re-reads the stored row fresh and refuses (StrategyError) when its revision
  or ``updated_at`` differs from the base the edits started from: no silent overwrite. An older
  release that edits a v2 row through the v1 fields changes ``updated_at`` without bumping the
  revision; ``upgrade`` then rebuilds the queue from the edited mirror.
- Nothing here reads or writes the global working queue (``draft_queue`` and its mirrors).
- Access is draft_strategy_store's: signed-out guests are refused, and the
  ``draft_strategy_library`` capability (Pro when enforced) is required for every stored call.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable

import draft_strategy_store as store
from draft_strategy_store import StrategyError

SCHEMA_VERSION = 2
ITEM_TYPE = store.ITEM_TYPE
BACKUP_ITEM_TYPE = "draft_strategy_v1_backup"
RESEARCH_ITEM_TYPE = "draft_strategy_research"
MAX_BYTES = 32 * 1024
QUEUE_MAX = 120
NOTE_MAX = 500
PINS_MAX = 25
EDITS_MAX = 50
RESEARCH_MAX = 100
RESEARCH_TEXT_MAX = 1000
NOTE_SOURCES = ("user", "ami_confirmed")
_SOURCE_MAX = 40
_PREF_KEY_MAX = 40


# --- pure model ------------------------------------------------------------------------------


def player_key(name: Any) -> str:
    """The key notes and pins use: the same as draft_queue_modes (trimmed, lower case)."""
    return str(name or "").strip().lower()


def _text(value: Any, limit: int = 200) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _entry(raw: Any, *, added_at: str, source: str) -> dict[str, str] | None:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        return None
    name = " ".join(str(raw.get("name") or "").split())
    if not name:
        return None
    return {
        "name": name,
        "player_id": _text(raw.get("player_id"), 40),
        "position": _text(raw.get("position"), 20),
        "team": _text(raw.get("team"), 20),
        "added_at": _text(raw.get("added_at"), 40) or added_at,
        "source": _text(raw.get("source"), _SOURCE_MAX) or source,
    }


def _ranked(players: Any) -> list[dict[str, Any]]:
    rows = [p for p in players or [] if isinstance(p, dict) and str(p.get("name") or "").strip()]

    def rank(p: dict[str, Any]) -> int:
        try:
            return int(p.get("rank") or 0)
        except (TypeError, ValueError):
            return 0

    return sorted(rows, key=rank)  # stable: ties keep their stored order


def _from_v1(row: dict[str, Any]) -> dict[str, Any]:
    stamp = str(row.get("created_at") or row.get("updated_at") or "")
    noted = str(row.get("updated_at") or stamp)
    players = _ranked(row.get("players"))
    out = copy.deepcopy(row)
    out.update({
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "queue": [e for e in (_entry(p, added_at=stamp, source="v1") for p in players) if e],
        "notes": {player_key(p["name"]): {"text": str(p.get("note")).strip(), "updated_at": noted, "source": "user"}
                  for p in players if str(p.get("note") or "").strip()},
        "pins": [], "priorities": {}, "preferences": {}, "settings": {},
        # migrated_at is filled in when the upgraded row is first saved (upgrade itself stays pure).
        "provenance": {"migrated_from": 1, "migrated_at": None, "created_from": "v1_snapshot"},
        "edits": [],
    })
    return out


def _mirror(s: dict[str, Any]) -> list[dict[str, Any]]:
    notes = s.get("notes") or {}
    return [{"rank": i, "name": e["name"], "player_id": e["player_id"], "position": e["position"],
             "note": str((notes.get(player_key(e["name"])) or {}).get("text") or "")}
            for i, e in enumerate(s.get("queue") or [], start=1)]


def _reconcile_mirror(s: dict[str, Any], raw_players: Any) -> None:
    """An older release edits a v2 row through its v1 ``players``; adopt those edits."""
    if not isinstance(raw_players, list):
        return
    mirror = _ranked(raw_players)
    stamp = str(s.get("updated_at") or "")
    if [player_key(p["name"]) for p in mirror] != [player_key(e["name"]) for e in s["queue"]]:
        by_key = {player_key(e["name"]): e for e in s["queue"]}
        rebuilt = []
        for p in mirror:
            fresh = _entry(p, added_at=stamp, source="v1_writer")
            if not fresh:
                continue
            old = by_key.get(player_key(fresh["name"]))
            if old:
                fresh = {**old, "player_id": old["player_id"] or fresh["player_id"],
                         "position": old["position"] or fresh["position"]}
            rebuilt.append(fresh)
        s["queue"] = _dedupe(rebuilt)
    for p in mirror:
        text = str(p.get("note") or "").strip()
        key = player_key(p.get("name"))
        if text and text != str((s["notes"].get(key) or {}).get("text") or ""):
            s["notes"][key] = {"text": text[:NOTE_MAX], "updated_at": stamp, "source": "user"}


def _dedupe(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    seen, out = set(), []
    for e in entries:
        k = player_key(e["name"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def _clean_notes(raw: Any) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else ():
        if isinstance(v, str):
            v = {"text": v}
        if not isinstance(v, dict):
            continue
        key, text = player_key(k), str(v.get("text") or "").strip()[:NOTE_MAX]
        if key and text:
            src = v.get("source") if v.get("source") in NOTE_SOURCES else "user"
            out[key] = {"text": text, "updated_at": str(v.get("updated_at") or ""), "source": src}
    return out


def upgrade(row: dict[str, Any]) -> dict[str, Any]:
    """Any stored strategy (v1 or v2) as a normalized v2 dict. Pure, idempotent, never writes."""
    if not isinstance(row, dict) or not row.get("id"):
        raise StrategyError("That strategy no longer exists.")
    s = _from_v1(row) if store._schema_version(row) < SCHEMA_VERSION else copy.deepcopy(row)
    s["schema_version"] = max(store._schema_version(s), SCHEMA_VERSION)  # a newer row keeps its version
    s["id"] = str(s["id"])
    s["name"] = " ".join(str(s.get("name") or "").split())[:store.NAME_MAX]
    s["approach"] = s.get("approach") if s.get("approach") in store.APPROACHES else "balanced"
    try:
        s["revision"] = max(0, int(s.get("revision") or 0))
    except (TypeError, ValueError):
        s["revision"] = 0
    for key in ("created_at", "updated_at"):
        s[key] = str(s.get(key) or "")
    stamp = s["created_at"] or s["updated_at"]
    s["queue"] = _dedupe([e for e in (_entry(q, added_at=stamp, source="v1") for q in s.get("queue") or []) if e])
    s["notes"] = _clean_notes(s.get("notes"))
    _reconcile_mirror(s, row.get("players"))
    queued = {player_key(e["name"]) for e in s["queue"]}
    pins: list[str] = []
    for p in s.get("pins") or []:
        k = player_key(p)
        if k in queued and k not in pins:
            pins.append(k)
    s["pins"] = pins[:PINS_MAX]
    for key in ("priorities", "preferences", "settings", "context"):
        s[key] = s.get(key) if isinstance(s.get(key), dict) else {}
    s["explanations"] = [str(x) for x in s.get("explanations") or []][:20] if isinstance(s.get("explanations"), list) else []
    prov = s.get("provenance") if isinstance(s.get("provenance"), dict) else {}
    s["provenance"] = {"migrated_from": None, "migrated_at": None, "created_from": None, **prov}
    s["edits"] = [e for e in s.get("edits") or [] if isinstance(e, dict)][-EDITS_MAX:] if isinstance(s.get("edits"), list) else []
    s["players"] = _mirror(s)
    return s


def encoded_size(s: dict[str, Any]) -> int:
    return len(json.dumps(s, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8"))


def check_size(s: dict[str, Any], what: str = "This strategy") -> None:
    size = encoded_size(s)
    if size > MAX_BYTES:
        raise StrategyError(f"{what} is too large to save ({size // 1024 + 1} KB; the limit is "
                            f"{MAX_BYTES // 1024} KB). Remove some players or shorten notes.")


def new_strategy(name: str, *, approach: str = "balanced", queue: list[Any] | None = None,
                 created_from: str = "blank", context: dict[str, Any] | None = None, at: str | None = None,
                 strategy_id: str | None = None) -> dict[str, Any]:
    """A new, unsaved v2 strategy (save it with ``save_strategy_v2(..., base_revision=None)``)."""
    import uuid

    at = at or store._now()
    clean = " ".join(str(name or "").split())[:store.NAME_MAX]
    if not clean:
        raise StrategyError("Give the strategy a name.")
    entries = _dedupe([e for e in (_entry(q, added_at=at, source="user") for q in queue or []) if e])
    if len(entries) > QUEUE_MAX:
        raise StrategyError(f"A strategy can hold up to {QUEUE_MAX} players.")
    return upgrade({
        "schema_version": SCHEMA_VERSION, "id": strategy_id or uuid.uuid4().hex[:12], "name": clean,
        "approach": approach, "queue": entries, "context": copy.deepcopy(context or {}),
        "created_at": at, "updated_at": at, "revision": 0,
        "provenance": {"migrated_from": None, "migrated_at": None, "created_from": _text(created_from, _SOURCE_MAX)},
    })


# --- edit operations (pure) ---------------------------------------------------------------------


def _apply(strategy: dict[str, Any], op: dict[str, Any], mutate: Callable[[dict[str, Any]], None], *,
           actor: str, at: str | None) -> dict[str, Any]:
    before = upgrade(strategy)
    s = copy.deepcopy(before)
    mutate(s)
    s["players"] = _mirror(s)
    if s == before:
        return before  # nothing changed: no new revision
    s["revision"] = before["revision"] + 1
    s["edits"] = (s["edits"] + [{"rev": s["revision"], "at": at or store._now(), "ops": [op],
                                 "actor": _text(actor, _SOURCE_MAX) or "user"}])[-EDITS_MAX:]
    check_size(s)
    return s


def _index(s: dict[str, Any], name: Any) -> int:
    key = player_key(name)
    for i, e in enumerate(s["queue"]):
        if player_key(e["name"]) == key:
            return i
    raise StrategyError(f"{_text(name, 80) or 'That player'} is not in this strategy.")


def move(strategy: dict[str, Any], name: str, to_index: int, *, actor: str = "user",
         at: str | None = None) -> dict[str, Any]:
    """Move a player to ``to_index`` (0 = top; clamped to the queue)."""
    def m(s: dict[str, Any]) -> None:
        i = _index(s, name)
        entry = s["queue"].pop(i)
        s["queue"].insert(max(0, min(int(to_index), len(s["queue"]))), entry)

    return _apply(strategy, {"op": "move", "player": player_key(name), "to": int(to_index)}, m, actor=actor, at=at)


def insert(strategy: dict[str, Any], player: Any, index: int | None = None, *, source: str = "user",
           actor: str = "user", at: str | None = None) -> dict[str, Any]:
    """Add a player (a name or ``{name, player_id, position, team}``) at ``index`` (default: the end)."""
    stamp = at or store._now()
    entry = _entry(player, added_at=stamp, source=source)
    if not entry:
        raise StrategyError("Choose a player to add.")
    key = player_key(entry["name"])

    def m(s: dict[str, Any]) -> None:
        if any(player_key(e["name"]) == key for e in s["queue"]):
            raise StrategyError(f"{entry['name']} is already in this strategy.")
        if len(s["queue"]) >= QUEUE_MAX:
            raise StrategyError(f"A strategy can hold up to {QUEUE_MAX} players.")
        pos = len(s["queue"]) if index is None else max(0, min(int(index), len(s["queue"])))
        s["queue"].insert(pos, entry)

    return _apply(strategy, {"op": "insert", "player": key, "at": index}, m, actor=actor, at=stamp)


def remove(strategy: dict[str, Any], name: str, *, actor: str = "user", at: str | None = None) -> dict[str, Any]:
    """Take a player off this strategy's queue (and its pins). Research notes are kept."""
    def m(s: dict[str, Any]) -> None:
        s["queue"].pop(_index(s, name))
        s["pins"] = [p for p in s["pins"] if p != player_key(name)]

    return _apply(strategy, {"op": "remove", "player": player_key(name)}, m, actor=actor, at=at)


def replace_queue(strategy: dict[str, Any], players: list[Any], *, context: dict[str, Any] | None = None,
                  actor: str = "user", at: str | None = None) -> dict[str, Any]:
    """Replace the whole queue (Update from queue). Entries already present keep their history."""
    stamp = at or store._now()
    entries = _dedupe([e for e in (_entry(p, added_at=stamp, source="working_queue") for p in players or []) if e])
    if not entries:
        raise StrategyError("Your queue is empty; the strategy was not changed.")
    if len(entries) > QUEUE_MAX:
        raise StrategyError(f"A strategy can hold up to {QUEUE_MAX} players.")

    def m(s: dict[str, Any]) -> None:
        old = {player_key(e["name"]): e for e in s["queue"]}
        merged = []
        for e in entries:
            prev = old.get(player_key(e["name"]))
            merged.append({**e, "added_at": prev["added_at"], "source": prev["source"]} if prev else e)
        s["queue"] = merged
        queued = {player_key(e["name"]) for e in merged}
        s["pins"] = [p for p in s["pins"] if p in queued]
        if context is not None:
            s["context"] = copy.deepcopy(context)

    return _apply(strategy, {"op": "replace_queue", "count": len(entries)}, m, actor=actor, at=stamp)


def set_note(strategy: dict[str, Any], name: str, text: str, *, source: str = "user", actor: str = "user",
             at: str | None = None) -> dict[str, Any]:
    """Set (or, with empty text, remove) the research note for a player."""
    key, body = player_key(name), str(text or "").strip()
    if not key:
        raise StrategyError("Choose a player for the note.")
    if source not in NOTE_SOURCES:
        raise StrategyError("Unknown note source.")
    if len(body) > NOTE_MAX:
        raise StrategyError(f"Notes can be up to {NOTE_MAX} characters.")
    stamp = at or store._now()

    def m(s: dict[str, Any]) -> None:
        if not body:
            s["notes"].pop(key, None)
        elif (s["notes"].get(key) or {}).get("text") != body or s["notes"][key].get("source") != source:
            s["notes"][key] = {"text": body, "updated_at": stamp, "source": source}

    return _apply(strategy, {"op": "set_note", "player": key, "source": source}, m, actor=actor, at=stamp)


def pin(strategy: dict[str, Any], name: str, *, actor: str = "user", at: str | None = None) -> dict[str, Any]:
    def m(s: dict[str, Any]) -> None:
        key = player_key(s["queue"][_index(s, name)]["name"])
        if key not in s["pins"]:
            if len(s["pins"]) >= PINS_MAX:
                raise StrategyError(f"You can pin up to {PINS_MAX} players.")
            s["pins"].append(key)

    return _apply(strategy, {"op": "pin", "player": player_key(name)}, m, actor=actor, at=at)


def unpin(strategy: dict[str, Any], name: str, *, actor: str = "user", at: str | None = None) -> dict[str, Any]:
    def m(s: dict[str, Any]) -> None:
        s["pins"] = [p for p in s["pins"] if p != player_key(name)]

    return _apply(strategy, {"op": "unpin", "player": player_key(name)}, m, actor=actor, at=at)


def _scalar_ok(v: Any) -> bool:
    if isinstance(v, (str, int, float, bool)):
        return True
    return isinstance(v, list) and len(v) <= 50 and all(isinstance(x, (str, int, float, bool)) for x in v)


def _merge_values(field: str, values: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    if not isinstance(values, dict):
        raise StrategyError(f"Strategy {field} must be a set of named values.")
    for k, v in values.items():
        if not isinstance(k, str) or not k.strip() or len(k) > _PREF_KEY_MAX:
            raise StrategyError(f"Strategy {field} names must be 1-{_PREF_KEY_MAX} characters.")
        if v is not None and not _scalar_ok(v):
            raise StrategyError(f"Strategy {field} values must be text, numbers, yes/no or short lists.")

    def m(s: dict[str, Any]) -> None:
        for k, v in values.items():
            if v is None:
                s[field].pop(k, None)
            else:
                s[field][k] = copy.deepcopy(v)

    return m


def set_settings(strategy: dict[str, Any], values: dict[str, Any], *, actor: str = "user",
                 at: str | None = None) -> dict[str, Any]:
    """Merge ``values`` into ``settings`` (a ``None`` value removes that setting)."""
    return _apply(strategy, {"op": "set_settings", "keys": sorted(values or {})},
                  _merge_values("settings", values), actor=actor, at=at)


def set_preferences(strategy: dict[str, Any], values: dict[str, Any], *, actor: str = "user",
                    at: str | None = None) -> dict[str, Any]:
    """Merge ``values`` into ``preferences`` (a ``None`` value removes that preference)."""
    return _apply(strategy, {"op": "set_preferences", "keys": sorted(values or {})},
                  _merge_values("preferences", values), actor=actor, at=at)


def rename(strategy: dict[str, Any], new_name: str, *, actor: str = "user", at: str | None = None) -> dict[str, Any]:
    clean = " ".join(str(new_name or "").split())[:store.NAME_MAX]
    if not clean:
        raise StrategyError("Give the strategy a name.")

    def m(s: dict[str, Any]) -> None:
        s["name"] = clean

    return _apply(strategy, {"op": "rename"}, m, actor=actor, at=at)


# --- storage ---------------------------------------------------------------------------------


def _fetch(backend: Any, key: str) -> dict[str, Any] | None:
    """The stored row read fresh (``fetch`` bypasses the per-session read cache)."""
    fetch = getattr(backend, "fetch", None)
    if callable(fetch):
        row = store._store_call(fetch, key)
    else:  # a backend without a single-row read
        row = next((r for r in store._store_call(backend.all) if isinstance(r, dict) and r.get("id") == key), None)
    return row if isinstance(row, dict) else None


def get_strategy_v2(session: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    """A saved strategy as v2 (upgraded in memory; nothing is written). Edit it, then save it with
    ``base_revision=<its revision>``."""
    return upgrade(store.get_strategy(session, strategy_id))


def list_strategies_v2(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [upgrade(s) for s in store.list_strategies(session)]


def get_v1_backup(session: dict[str, Any], strategy_id: str) -> dict[str, Any] | None:
    """The v1 row as it was before its first v2 save (``{"backup_of", "backed_up_at", "strategy"}``)."""
    store._require_access(session)
    return _fetch(store._backend(BACKUP_ITEM_TYPE), strategy_id)


def save_strategy_v2(session: dict[str, Any], strategy: dict[str, Any], base_revision: int | None) -> dict[str, Any]:
    """Store an edited strategy; ``base_revision`` is the revision the edits started from.

    ``None`` saves a new strategy (refused if its id exists). Otherwise the stored row is read
    fresh and the save is refused when it was changed since (revision or ``updated_at``). An
    unedited strategy is not written (v1 rows stay v1 until the user's first edit). Before the
    first v2 write of a v1 row, a one-time backup of that row is stored. Never touches the global
    working queue.
    """
    store._require_access(session)
    s = upgrade(strategy)
    if s["schema_version"] > SCHEMA_VERSION:
        raise StrategyError("This strategy was saved by a newer version of Baseball Explorer; reload the page.")
    backend = store._backend(ITEM_TYPE)
    stored = _fetch(backend, s["id"])
    if base_revision is None:
        if stored is not None:
            raise StrategyError("A strategy with this id already exists; nothing was saved.")
    else:
        if stored is None:
            raise StrategyError("That strategy no longer exists.")
        stored_version = store._schema_version(stored)
        if stored_version > SCHEMA_VERSION:
            raise StrategyError("This strategy was saved by a newer version of Baseball Explorer; reload the page.")
        stored_rev = upgrade(stored)["revision"] if stored_version >= SCHEMA_VERSION else 0
        if stored_rev != int(base_revision) or str(stored.get("updated_at") or "") != s["updated_at"]:
            raise StrategyError("This strategy was changed somewhere else (another tab or device) since you "
                                "opened it. Reload it and make your change again; nothing was saved.")
        if s["revision"] < stored_rev:
            raise StrategyError("This strategy is older than the saved one; reload it. Nothing was saved.")
        if s["revision"] == stored_rev:
            return upgrade(stored)  # nothing edited: nothing to write
    s["name"] = store._clean_name(s["name"], store.list_strategies(session), exclude_id=s["id"])
    now = store._now()
    s["updated_at"] = now
    if stored is not None and store._schema_version(stored) < SCHEMA_VERSION and not s["provenance"].get("migrated_at"):
        s["provenance"]["migrated_at"] = now
    check_size(s)
    if stored is not None and store._schema_version(stored) < SCHEMA_VERSION:
        backups = store._backend(BACKUP_ITEM_TYPE)
        if _fetch(backups, s["id"]) is None:
            store._store_call(backups.put, s["id"], str(stored.get("name") or s["name"]),
                              {"backup_of": s["id"], "backed_up_at": now, "strategy": copy.deepcopy(stored)})
    store._store_call(backend.put, s["id"], s["name"], s)
    return s


# --- research log (API only) --------------------------------------------------------------------


def research_log(session: dict[str, Any], strategy_id: str) -> list[dict[str, Any]]:
    """A strategy's research entries, oldest first (item type ``draft_strategy_research``)."""
    store._require_access(session)
    row = _fetch(store._backend(RESEARCH_ITEM_TYPE), strategy_id) or {}
    return [e for e in row.get("entries") or [] if isinstance(e, dict)]


def append_research(session: dict[str, Any], strategy_id: str, text: str, *, kind: str = "note",
                    player: str = "", source: str = "user", at: str | None = None) -> dict[str, Any]:
    """Append one entry to the strategy's research log (keeps the newest ``RESEARCH_MAX``)."""
    store._require_access(session)
    body = str(text or "").strip()
    if not body:
        raise StrategyError("Write something to add to the research log.")
    if len(body) > RESEARCH_TEXT_MAX:
        raise StrategyError(f"Research entries can be up to {RESEARCH_TEXT_MAX} characters.")
    if source not in NOTE_SOURCES:
        raise StrategyError("Unknown research source.")
    strategy = store.get_strategy(session, strategy_id)
    backend = store._backend(RESEARCH_ITEM_TYPE)
    row = _fetch(backend, strategy_id) or {}
    entry = {"at": at or store._now(), "kind": _text(kind, _SOURCE_MAX) or "note", "text": body,
             "player_key": player_key(player), "source": source}
    entries = ([e for e in row.get("entries") or [] if isinstance(e, dict)] + [entry])[-RESEARCH_MAX:]
    payload = {"schema_version": 1, "strategy_id": strategy_id, "entries": entries, "updated_at": entry["at"]}
    check_size(payload, "This research log")
    store._store_call(backend.put, strategy_id, str(strategy.get("name") or strategy_id), payload)
    return entry
