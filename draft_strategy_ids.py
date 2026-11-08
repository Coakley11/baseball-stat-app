"""Stable player ids (MLBAM) for saved Draft Strategies, resolved offline and only when unambiguous.

Notes and pins are keyed by player name (``draft_strategy_v2.player_key``), as the queue's own
notes have always been. This attaches an MLBAM id to a strategy entry, and to its note, when the id
is certain, so a later name change ("Ronald Acuna" / "Ronald Acuña Jr.") still finds the note
(``draft_strategy_v2.note_for`` looks up by id first, then by name).

Resolution never calls the network: the draft pool row (an ``MLBAM ID`` / ``mlbam_id`` /
``key_mlbam`` column), then player_photos' built-in seed map, then its id cache file. A name that
matches two different players in the pool (two "Will Smith"s) is ambiguous: no id is attached, the
entry keeps its name key and is flagged ``id_status = "ambiguous"`` so a later slice can ask the user.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

ID_COLUMNS = ("MLBAM ID", "mlbam_id", "MLBAMID", "key_mlbam", "mlbamid")
NAME_COLUMNS = ("fullName", "Player", "Name", "player_name")


def _norm(name: Any) -> str:
    from player_photos import _normalize_name_key

    return _normalize_name_key(str(name or ""))


def _as_id(value: Any) -> str:
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return ""
    return str(n) if n > 0 else ""


def _pool_ids(pool: pd.DataFrame | None, key: str) -> set[str]:
    if not isinstance(pool, pd.DataFrame) or pool.empty:
        return set()
    name_col = next((c for c in NAME_COLUMNS if c in pool.columns), None)
    id_col = next((c for c in ID_COLUMNS if c in pool.columns), None)
    if name_col is None:
        return set()
    rows = pool[pool[name_col].map(_norm) == key]
    if rows.empty:
        return set()
    if id_col is None:
        return {""} if len(rows) == 1 else {"", "?"}  # present, but the pool carries no ids
    ids = {_as_id(v) for v in rows[id_col].tolist()}
    if len(rows) > 1 and ids == {""}:
        return {"", "?"}  # several same-named players without ids: ambiguous
    return ids


def resolve(name: Any, pool: pd.DataFrame | None = None, *, mlbam_id: Any = None) -> tuple[str, str]:
    """``(mlbam_id, id_status)``: ``(id, "ok")``, ``("", "ambiguous")`` or ``("", "")`` (unknown)."""
    direct = _as_id(mlbam_id)
    if direct:
        return direct, "ok"
    key = _norm(name)
    if not key:
        return "", ""
    ids = _pool_ids(pool, key)
    real = {i for i in ids if i and i != "?"}
    if len(real) > 1 or "?" in ids:
        return "", "ambiguous"
    if len(real) == 1:
        return real.pop(), "ok"
    try:
        from player_photos import _load_mlbam_cache, _seed_mlbam_id

        seeded = _seed_mlbam_id(full_name=str(name))
        if seeded:
            return str(int(seeded)), "ok"
        cached = _load_mlbam_cache().get(f"name:{key}")
        if cached:
            return _as_id(cached), "ok" if _as_id(cached) else ""
    except Exception:
        pass
    return "", ""


def with_ids(player: Any, pool: pd.DataFrame | None = None) -> dict[str, Any]:
    """A player (name or dict) as a strategy entry dict with ``mlbam_id`` / ``id_status`` filled in."""
    entry = dict(player) if isinstance(player, dict) else {"name": str(player or "")}
    mid, status = resolve(entry.get("name"), pool, mlbam_id=entry.get("mlbam_id"))
    entry["mlbam_id"], entry["id_status"] = mid, status
    return entry
