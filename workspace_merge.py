"""Field-level reconciliation of one account's workspace between this session and the cloud.

The account workspace is one ``full_session`` blob, guarded by compare-and-set on its revision.
That guard refuses a stale session's write, which protects newer work but on its own is a dead
end: the Dell can never save again, and never learns what the phone changed, until a refresh.

Reconciling is a three-way merge against the *base* — the blob this session last loaded from
or wrote to the cloud:

* a field only this session changed keeps this session's value;
* a field only the cloud changed (another device) takes the cloud's value;
* a field both changed to the same value is simply that value;
* a field both changed differently is a **conflict**: the cloud keeps its value, this session
  keeps its own, and nothing is decided until the user chooses (``render_workspace_conflicts``).

Dicts merge per key (so two pages, or two filters on one page, never collide). The queue and
the watchlists are ordered lists merged as operations against the base: both devices' additions
are kept, a removal on either device stays removed (an older copy never brings a player back),
and a reorder on one device is kept with the other device's additions placed beside their
neighbours. A reorder on *both* devices is a conflict. The
Saved Draft Library merges per saved draft. The Simulator board and live drafts are atomic: their own guards (``workspace_cloud_guard``,
``draft_board_reconcile``) decide them, and a both-sides change is never merged pick by pick.

Never by size: a smaller board, an emptied queue, or a filter set back to its default is a real
edit when this session made it, and is kept.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

BASE_KEY_PREFIX = "_suite_workspace_base::"
CONFLICTS_KEY_PREFIX = "_suite_workspace_conflicts::"
REAPPLY_KEY_PREFIX = "_suite_workspace_reapply::"
RESOLUTION_KEY_PREFIX = "_suite_workspace_conflict_resolution::"

# Compared whole, by fingerprint. Their own guards own them; merging them field by field could
# produce a board or a draft nobody made.
ATOMIC_TOP_KEYS = frozenset({
    "draft_room_table",
    "draft_room_state",
    "live_draft_state",
    "last_draft_board_snapshot",
    "draft_lab_persisted_state",
    "fantasy_in_season_state",
    "resumable_live_draft_slot",
    "draft_shared_settings",
    "draft_room_shared_meta",
    "draft_room_participant_state",
    "_hof_case_packet",
})
ATOMIC_PAGE_BLOCKS = frozenset({
    "Draft Room Simulator",
    "Draft Room",
    "Live Draft Room",
    "Draft Lab / Simulation",
    "Draft Simulation Test Mode",
})
# Lists of records with an id: merged per record (each record whole), so a draft saved on each
# device keeps both. A conflict path addresses one record as ``@<id>``.
KEYED_LISTS = {"draft_archive_teams": "draft_id"}
_ID = "__id__"
# Leagues merge per league: each league's context is whole, the active league is its own field,
# so editing one league here and switching leagues there are two changes, not one conflict.
LEAGUE_STORE_KEY = "fantasy_league_context_state"
# One explicit choice per record (which fantasy source, research mode on/off): never mixed field
# by field. When both devices chose, the later choice is the account's.
NEWEST_CHOICE_KEYS = frozenset({"fantasy_source_override_selection", "fantasy_research_mode_selection"})
# Rebuilt from the merged state on every save; never merged.
DERIVED_TOP_KEYS = frozenset({"baseball_workspace_state"})
# Ordered player lists: membership merges like a set, and the order is kept (see _ordered_merge).
ORDERED_LIST_LEAVES = frozenset({
    "draft_queue",
    "queue",
    "watchlist_focus",
    "watchlist_favorites",
    "draft_assistant_focus_players",
    "workflow_favorite_targets",
})
# Id sets: both devices' additions kept, either side's removals honoured.
SET_MERGE_LEAVES = frozenset({
    "_deleted_draft_archive_ids",
    "deleted_context_ids",
    "_ami_dismissed_insight_ids",
    "_ami_dismissed_question_ids",
    "trade_offer_inbox_dismissals",
})

# Most-recent-first view history: what this device looked at, never a user conflict.
LOCAL_HISTORY_LEAVES = frozenset({"workflow_recently_viewed", "workflow_recent_compare_pairs"})
# Counters that only ever go up (a reset or new board bumps the Simulator epoch).
MAX_LEAVES = frozenset({"_simulator_board_epoch"})

_MISSING = {"__missing__": True}
_FP = "__fp__"
# Bookkeeping a save or a render rewrites without any user change. Inside a block they must not
# make two devices that only opened a page look like they both edited it.
_VOLATILE_FIELDS = frozenset({"last_updated_at", "updated_at", "last_write_reason", "updated_by_page"})


def _content(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _content(v)
            for k, v in value.items()
            if not str(k).startswith("_") and k not in _VOLATILE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_content(v) for v in value]
    return value


def _fp(value: Any) -> str:
    if isinstance(value, dict) and set(value) == {_FP}:
        return str(value[_FP])
    if value is _MISSING:
        return "missing"
    blob = json.dumps(_content(value), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _same(a: Any, b: Any) -> bool:
    return _fp(a) == _fp(b)


same_value = _same


def _is_atomic(path: tuple[str, ...]) -> bool:
    if len(path) == 1 and path[0] in ATOMIC_TOP_KEYS:
        return True
    if len(path) == 3 and path[0] == LEAGUE_STORE_KEY and path[1] == "contexts":
        return True
    return len(path) == 2 and path[0] == "page_filter_state" and path[1] in ATOMIC_PAGE_BLOCKS


def compact_base(state: dict[str, Any]) -> dict[str, Any]:
    """What a session keeps as its base: atomic parts by fingerprint only (they can be large)."""
    out: dict[str, Any] = {}
    for key, value in (state or {}).items():
        if key in DERIVED_TOP_KEYS:
            continue
        if key in ATOMIC_TOP_KEYS:
            out[key] = {_FP: _fp(value)}
        elif key in KEYED_LISTS and isinstance(value, list):
            id_field = KEYED_LISTS[key]
            out[key] = [{_ID: str(e.get(id_field) or ""), _FP: _fp(e)} for e in value if isinstance(e, dict)]
        elif key == LEAGUE_STORE_KEY and isinstance(value, dict):
            out[key] = copy.deepcopy({k: v for k, v in value.items() if k != "contexts"})
            contexts = value.get("contexts")
            if isinstance(contexts, dict):
                out[key]["contexts"] = {cid: {_FP: _fp(ctx)} for cid, ctx in contexts.items()}
        elif key == "page_filter_state" and isinstance(value, dict):
            out[key] = {
                page: ({_FP: _fp(block)} if page in ATOMIC_PAGE_BLOCKS else copy.deepcopy(block))
                for page, block in value.items()
            }
        else:
            try:
                out[key] = json.loads(json.dumps(value, default=str))
            except (TypeError, ValueError):
                out[key] = {_FP: _fp(value)}
    return out


def _set_merge(base: Any, local: list, remote: list) -> list:
    base_items = list(base) if isinstance(base, list) else []
    removed = {_fp(x) for x in base_items} - {_fp(x) for x in local}
    removed |= {_fp(x) for x in base_items} - {_fp(x) for x in remote}
    out: list = []
    seen: set[str] = set()
    for item in list(remote) + list(local):
        f = _fp(item)
        if f in removed or f in seen:
            continue
        seen.add(f)
        out.append(item)
    return out


def _relative_order(seq: list[str], keep: set[str]) -> list[str]:
    return [f for f in seq if f in keep]


def _ordered_merge(base: Any, local: list, remote: list, path: tuple[str, ...], conflicts: list) -> list:
    """Three-way merge of an ordered list of distinct items (the queue, a watchlist).

    Membership: an item the base had and either side dropped is removed (a deliberate removal,
    or a pick that consumed it); an item either side added is kept. Order: the side that did not
    reorder follows the side that did; the other side's additions go just before the item that
    followed them there, and an addition at the end (Add to Queue) stays at the end. Both sides reordering the same items differently is a
    conflict (the account keeps its order, this session its own, until the user chooses).
    """
    base_items = list(base) if isinstance(base, list) else []
    fb, fl, fr = ([_fp(x) for x in seq] for seq in (base_items, local, remote))
    by_fp: dict[str, Any] = {}
    for f, item in list(zip(fb, base_items)) + list(zip(fr, remote)) + list(zip(fl, local)):
        by_fp.setdefault(f, item)
    removed = (set(fb) - set(fl)) | (set(fb) - set(fr))
    survivors = (set(fl) | set(fr)) - removed
    common = survivors & set(fb) & set(fl) & set(fr)
    base_order = _relative_order(list(dict.fromkeys(fb)), common)
    local_order = _relative_order(list(dict.fromkeys(fl)), common)
    remote_order = _relative_order(list(dict.fromkeys(fr)), common)
    local_moved, remote_moved = local_order != base_order, remote_order != base_order
    if local_moved and remote_moved and local_order != remote_order:
        conflicts.append(path)
        return remote
    lead, other = (fl, fr) if local_moved and not remote_moved else (fr, fl)
    out = [f for f in dict.fromkeys(lead) if f in survivors]
    placed = set(out)
    for i, f in enumerate(other):
        if f in placed or f not in survivors:
            continue
        # Before the next item it preceded there; an append stays at the end.
        follower = next((g for g in other[i + 1:] if g in placed), None)
        out.insert(out.index(follower) if follower is not None else len(out), f)
        placed.add(f)
    return [by_fp[f] for f in out]


def _keyed_merge(base: Any, local: list, remote: list, path: tuple[str, ...], conflicts: list) -> list:
    """Per-record three-way merge of a list of records keyed by ``KEYED_LISTS[path[0]]``."""
    id_field = KEYED_LISTS[path[0]]

    def index(seq: Any, compact: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for e in seq if isinstance(seq, list) else []:
            if isinstance(e, dict):
                rid = str(e.get(_ID) if compact and _ID in e else e.get(id_field) or "")
                if rid:
                    out.setdefault(rid, {_FP: e[_FP]} if compact and _FP in e else e)
        return out

    b, l, r = index(base, compact=True), index(local), index(remote)
    merged: dict[str, Any] = {}
    for rid in dict.fromkeys(list(r) + list(l)):
        bv, lv, rv = b.get(rid, _MISSING), l.get(rid, _MISSING), r.get(rid, _MISSING)
        if _same(lv, rv) or _same(lv, bv):
            value = rv
        elif _same(rv, bv):
            value = lv
        else:
            conflicts.append(path + (f"@{rid}",))  # both changed this record: the account's meanwhile
            value = rv
        if value is not _MISSING:
            merged[rid] = value
    return list(merged.values())


def _choice_order(record: dict[str, Any]) -> tuple[str, int]:
    try:
        seq = int(record.get("local_seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return str(record.get("selected_at") or ""), seq


def _merge(base: Any, local: Any, remote: Any, path: tuple[str, ...], conflicts: list) -> Any:
    if _same(local, remote):
        return remote
    if _same(local, base):
        return remote
    if _same(remote, base):
        return local
    leaf = path[-1] if path else ""
    if len(path) == 1 and leaf in KEYED_LISTS and isinstance(local, list) and isinstance(remote, list):
        return _keyed_merge(base, local, remote, path, conflicts)
    if len(path) == 1 and leaf in NEWEST_CHOICE_KEYS and isinstance(local, dict) and isinstance(remote, dict):
        return max((remote, local), key=_choice_order)  # remote first: a tie keeps the account's
    if _is_atomic(path):
        conflicts.append(path)
        return remote
    if isinstance(local, dict) and isinstance(remote, dict) and _FP not in local and _FP not in remote:
        base_d = base if isinstance(base, dict) and _FP not in base else {}
        merged: dict[str, Any] = {}
        for key in list(dict.fromkeys(list(remote) + list(local))):
            value = _merge(
                base_d.get(key, _MISSING),
                local.get(key, _MISSING),
                remote.get(key, _MISSING),
                path + (str(key),),
                conflicts,
            )
            if value is not _MISSING:
                merged[key] = value
        return merged
    if leaf in ORDERED_LIST_LEAVES and isinstance(local, list) and isinstance(remote, list):
        return _ordered_merge(base, local, remote, path, conflicts)
    if leaf in SET_MERGE_LEAVES and isinstance(local, list) and isinstance(remote, list):
        return _set_merge(base, local, remote)
    if leaf in LOCAL_HISTORY_LEAVES and local is not _MISSING:
        return local
    if leaf in MAX_LEAVES and isinstance(local, (int, float)) and isinstance(remote, (int, float)):
        return max(local, remote)
    if leaf.startswith("_"):
        return local  # diagnostics, flashes and traces: this session's own, never a user conflict
    conflicts.append(path)
    return remote


def three_way_merge(
    base: dict[str, Any] | None,
    local: dict[str, Any],
    remote: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, ...]]]:
    """Merge ``local`` (this session) and ``remote`` (cloud) against ``base``.

    Returns ``(merged, conflicts)``. A conflict path keeps the remote value in ``merged``.
    """
    conflicts: list[tuple[str, ...]] = []
    base = base if isinstance(base, dict) else {}
    merged: dict[str, Any] = {}
    for key in list(dict.fromkeys(list(remote or {}) + list(local or {}))):
        if key in DERIVED_TOP_KEYS:
            if key in local:
                merged[key] = local[key]
            continue
        value = _merge(
            base.get(key, _MISSING),
            (local or {}).get(key, _MISSING),
            (remote or {}).get(key, _MISSING),
            (str(key),),
            conflicts,
        )
        if value is not _MISSING:
            merged[key] = value
    return merged, conflicts


def _record_at(path: tuple[str, ...], container: Any, part: str) -> tuple[int, Any]:
    """``@<id>`` in a keyed list: (index, record), or (-1, _MISSING)."""
    id_field = KEYED_LISTS.get(path[0], "id") if path else "id"
    rid = part[1:]
    for i, e in enumerate(container if isinstance(container, list) else []):
        if isinstance(e, dict) and str(e.get(id_field) or "") == rid:
            return i, e
    return -1, _MISSING


def get_path(state: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = state
    for part in path:
        if isinstance(cur, list) and str(part).startswith("@"):
            cur = _record_at(path, cur, str(part))[1]
            if cur is _MISSING:
                return _MISSING
            continue
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def set_path(state: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if len(path) == 2 and str(path[1]).startswith("@"):
        records = state.get(path[0])
        records = records if isinstance(records, list) else []
        i, _ = _record_at(path, records, str(path[1]))
        if value is _MISSING:
            if i >= 0:
                records.pop(i)
        elif i >= 0:
            records[i] = copy.deepcopy(value)
        else:
            records.append(copy.deepcopy(value))
        state[path[0]] = records
        return
    cur = state
    for part in path[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    if value is _MISSING:
        cur.pop(path[-1], None)
    else:
        cur[path[-1]] = copy.deepcopy(value)


_FINALIZERS: dict[str, Any] = {}


def register_merge_finalizer(app_id: str, fn: Any) -> None:
    """``fn(merged)`` rebuilds an app's derived keys (DERIVED_TOP_KEYS) from a merged state."""
    _FINALIZERS[app_id] = fn


def finalize_merged(app_id: str, merged: dict[str, Any]) -> None:
    fn = _FINALIZERS.get(app_id)
    if fn is None:
        return
    try:
        fn(merged)
    except Exception:
        pass


def remote_contributed(local: dict[str, Any], merged: dict[str, Any]) -> bool:
    """True when the merge took anything from the cloud that this session does not show yet."""
    for key in set(local) | set(merged):
        if key in DERIVED_TOP_KEYS:
            continue
        if not _same(local.get(key, _MISSING), merged.get(key, _MISSING)):
            return True
    return False


# --- session bookkeeping -------------------------------------------------------------------


def record_base(session: Any, app_id: str, state: dict[str, Any] | None) -> None:
    """This session is now in step with ``state`` (it loaded it, or wrote it)."""
    if not isinstance(state, dict):
        return
    try:
        session[BASE_KEY_PREFIX + app_id] = compact_base(state)
    except Exception:
        pass


def session_base(session: Any, app_id: str) -> dict[str, Any] | None:
    try:
        base = session.get(BASE_KEY_PREFIX + app_id)
    except Exception:
        return None
    return base if isinstance(base, dict) else None


HELD_BASE_KEY_PREFIX = "_suite_workspace_held_base::"
# What this session itself held when it made that rebased write (its pre-merge display).
HELD_LOCAL_KEY_PREFIX = "_suite_workspace_held_local::"


def merge_base(session: Any, app_id: str, local: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The base to merge against. After a rebased write the session still shows its pre-merge
    values until the merged state is applied on the next rerun; until then the pre-rebase base is
    held, so those stale values read as "unchanged here" and never as edits that undo the merge.

    Given ``local``, that applies per field: a field that still shows what this session held when
    it wrote is unchanged here; anything else is measured against what it wrote. (Measuring a
    value it wrote itself against the pre-rebase base turned another device's newer explicit
    choice into a conflict; measuring its pre-merge display against what it wrote turned the
    other device's merged-in additions into removals.)"""
    try:
        held = session.get(HELD_BASE_KEY_PREFIX + app_id)
        held_local = session.get(HELD_LOCAL_KEY_PREFIX + app_id)
    except Exception:
        held, held_local = None, None
    written = session_base(session, app_id)
    if not isinstance(held, dict):
        return written
    if isinstance(local, dict) and isinstance(written, dict) and isinstance(held_local, dict):
        return _hold_aware_base(written, held_local, local)
    return held


def _plain_dict(value: Any) -> bool:
    return isinstance(value, dict) and value is not _MISSING and _FP not in value


def _hold_aware_base(written: Any, shown: Any, local: Any, path: tuple[str, ...] = ()) -> Any:
    """Per field: ``shown`` (the pre-merge display) where ``local`` still equals it, else ``written``."""
    leaf = path[-1] if path else ""
    if len(path) == 1 and leaf in KEYED_LISTS and isinstance(written, list):
        if not isinstance(shown, list) or not isinstance(local, list):
            return written
        id_field = KEYED_LISTS[leaf]
        shown_by_id = {str(e.get(_ID) or ""): e for e in shown if isinstance(e, dict)}
        local_by_id = {str(e.get(id_field) or ""): e for e in local if isinstance(e, dict)}

        def fp_of(entry: Any) -> Any:
            return {_FP: entry[_FP]} if isinstance(entry, dict) and _FP in entry else _MISSING

        out = []
        for entry in written:
            rid = str(entry.get(_ID) or "") if isinstance(entry, dict) else ""
            mine, before = local_by_id.get(rid, _MISSING), shown_by_id.get(rid, _MISSING)
            stale = before is not _MISSING and not _same(mine, fp_of(entry)) and _same(mine, fp_of(before))
            out.append(before if stale else entry)
        for rid, before in shown_by_id.items():  # a record the write dropped that this page still shows
            if rid not in {str(e.get(_ID) or "") for e in written if isinstance(e, dict)}                     and _same(local_by_id.get(rid, _MISSING), fp_of(before)):
                out.append(before)
        return out
    if path and _same(local, written):
        return written
    if _plain_dict(written) and _plain_dict(local):
        shown_d = shown if _plain_dict(shown) else {}
        out = {
            key: _hold_aware_base(value, shown_d.get(key, _MISSING), local.get(key, _MISSING), path + (str(key),))
            for key, value in written.items()
        }
        for key, value in shown_d.items():  # a field the write dropped that this page still shows
            if key not in out and _same(local.get(key, _MISSING), value):
                out[key] = value
        return out
    if shown is not _MISSING and local is not _MISSING and _same(local, shown):
        return shown
    return written


def hold_merge_base(session: Any, app_id: str, base: dict[str, Any] | None,
                    local: dict[str, Any] | None = None) -> None:
    if isinstance(base, dict) and HELD_BASE_KEY_PREFIX + app_id not in session:
        session[HELD_BASE_KEY_PREFIX + app_id] = base
        if isinstance(local, dict):
            session[HELD_LOCAL_KEY_PREFIX + app_id] = compact_base(local)


def holding_merge_base(session: Any, app_id: str) -> bool:
    try:
        return isinstance(session.get(HELD_BASE_KEY_PREFIX + app_id), dict)
    except Exception:
        return False


def release_merge_base(session: Any, app_id: str) -> None:
    try:
        session.pop(HELD_BASE_KEY_PREFIX + app_id, None)
        session.pop(HELD_LOCAL_KEY_PREFIX + app_id, None)
    except Exception:
        pass


BOARD_KEYS = ("draft_room_table", "draft_room_state")


def board_conflicted(paths: list[tuple[str, ...]]) -> bool:
    """Both devices changed the Simulator board: ``draft_board_reconcile`` asks the user, not this merge."""
    return any(path and path[0] in BOARD_KEYS for path in paths)


def open_conflicts(session: Any, app_id: str) -> list[dict[str, Any]]:
    try:
        rows = session.get(CONFLICTS_KEY_PREFIX + app_id)
    except Exception:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def note_conflicts(session: Any, app_id: str, paths: list[tuple[str, ...]], local: dict, remote: dict) -> None:
    rows = {tuple(r["path"]): r for r in open_conflicts(session, app_id)}
    for path in paths:
        rows[tuple(path)] = {
            "path": list(path),
            "label": conflict_label(path),
            "local": copy.deepcopy(get_path(local, path)),
            "remote": copy.deepcopy(get_path(remote, path)),
        }
    session[CONFLICTS_KEY_PREFIX + app_id] = list(rows.values())


def pin_conflicts_to_remote(session: Any, app_id: str, outgoing: dict[str, Any], remote: dict[str, Any]) -> None:
    """While a conflict is open, a save writes the account's side of it, never this session's."""
    for row in open_conflicts(session, app_id):
        path = tuple(row.get("path") or ())
        if path:
            set_path(outgoing, path, get_path(remote, path))


def keep_local_for_conflicts(session: Any, app_id: str, merged: dict[str, Any], local: dict[str, Any]) -> None:
    """Applying the account's state must not replace this session's side of an open conflict."""
    for row in open_conflicts(session, app_id):
        path = tuple(row.get("path") or ())
        if path:
            set_path(merged, path, get_path(local, path))


def conflict_label(path: tuple[str, ...] | list[str]) -> str:
    parts = [str(p) for p in path]
    if parts and parts[0] == "page_filter_state" and len(parts) >= 2:
        return f"{parts[1]}: {' / '.join(parts[2:]) or 'settings'}"
    names = {
        "draft_queue": "Draft queue",
        "watchlist_focus": "Watchlist",
        "watchlist_favorites": "Tracked players",
        "draft_room_table": "Simulator board",
        "draft_room_state": "Simulator board",
        "live_draft_state": "Live draft",
        "draft_archive_teams": "Saved Draft Library",
        "fantasy_league_context_state": "Leagues",
    }
    if len(parts) == 2 and parts[0] in KEYED_LISTS and parts[1].startswith("@"):
        return f"Saved Draft Library: a draft ({parts[1][1:]})"
    if len(parts) == 3 and parts[0] == LEAGUE_STORE_KEY and parts[1] == "contexts":
        return f"League settings ({parts[2].split(':', 1)[-1]})"
    if len(parts) == 2 and parts[0] == LEAGUE_STORE_KEY and parts[1] == "active_league_context_id":
        return "Active league"
    head = names.get(parts[0], parts[0].replace("_", " ").strip().capitalize()) if parts else "Settings"
    return head if len(parts) == 1 else f"{head}: {' / '.join(parts[1:])}"


# --- in-flight widget edits ----------------------------------------------------------------

_NAV_WIDGET_KEYS = frozenset({"main_sidebar_page", "active_page", "_mobile_quick_nav_select"})


def widget_edits_this_run() -> dict[str, Any]:
    """Keyed widget values the user changed in the browser for this rerun.

    These arrive before the script runs. Applying a workspace blob on the same rerun writes over
    them through the session-state API before the page (and its "dirty" flag) ever sees them —
    the edit that caused the rerun silently reverted. Callers re-apply these after a restore.
    """
    try:
        from page_state import _is_ephemeral_widget_key
        from streamlit.runtime.state import get_session_state

        inner = get_session_state()._state
        id_to_key = inner._key_id_mapper.id_key_mapping
        widgets = inner._new_widget_state
        out: dict[str, Any] = {}
        for wid in list(widgets.keys()):
            meta = widgets.widget_metadata.get(wid)
            if meta is None or "trigger" in str(getattr(meta, "value_type", "")):
                continue
            key = id_to_key.get(wid)
            if not key or key in _NAV_WIDGET_KEYS or _is_ephemeral_widget_key(key):
                continue
            if not inner._widget_changed(wid):
                continue
            out[key] = copy.deepcopy(widgets[wid])
        return out
    except Exception:
        return {}


def reapply_widget_edits(session: Any, edits: dict[str, Any]) -> list[str]:
    applied: list[str] = []
    for key, value in (edits or {}).items():
        try:
            session[key] = copy.deepcopy(value)
            applied.append(key)
        except Exception:
            continue
    return applied


# --- UI ------------------------------------------------------------------------------------


def render_workspace_conflicts(st: Any, app_id: str = "baseball") -> None:
    """Both devices changed the same saved setting differently. Both sides are kept until the
    user picks one; nothing is overwritten in the meantime."""
    rows = open_conflicts(st.session_state, app_id)
    if not rows:
        return
    labels = sorted({str(r.get("label") or "a setting") for r in rows})
    shown = ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")
    st.warning(
        f"Another device changed **{shown}** while this one changed it too. This device still shows "
        "its own version; your account keeps the other device's. Choose which to keep.",
        icon=":material/sync_problem:",
    )
    keep_col, load_col = st.columns(2)
    with keep_col:
        if st.button("Keep this device's version", key="ws_conflict_keep_local_btn", width="stretch"):
            # Closing the conflict un-pins it: the next save writes this device's side.
            st.session_state.pop(CONFLICTS_KEY_PREFIX + app_id, None)
            st.session_state.pop(f"_suite_autosave_fp::{app_id}", None)  # so the next autosave writes
            st.rerun()
    with load_col:
        if st.button("Use the saved version", key="ws_conflict_use_saved_btn", width="stretch"):
            st.session_state[RESOLUTION_KEY_PREFIX + app_id] = "remote"
            st.session_state[REAPPLY_KEY_PREFIX + app_id] = True
            st.rerun()
