"""In-app persistence trace for draft / settings widgets that fail to persist.

This is a DEV-MODE diagnostic. It answers one question for every tracked setting:

    "Where does the value change back to the default?"

For each tracked key it lets us compare, live on the failing page:

  * session_state value        (what the widget currently shows)
  * canonical value            (room_format / room_your_team, for format/team)
  * page snapshot value        (session page_filter_state[page][key])
  * cloud blob snapshot value  (durable cloud page_filter_state[page][key])
  * cloud blob top-level value (durable cloud state[key], for _GLOBAL_KEYS)
  * disk blob snapshot value   (local durable copy)

Plus two ring buffers of lifecycle events:

  * SAVE events   — recorded inside force_autosave (reason, cloud allowed/blocked,
                    what value was actually written for each tracked key).
  * RESTORE events — recorded inside apply_baseball_disk_state on refresh/navigation
                    (cloud value loaded, snapshot value loaded, final session value).

Reading the table:
  - If after refresh session==default but cloud-blob-snapshot==correct  -> RESTORE drops it.
  - If cloud-blob-snapshot==default/old after a save                     -> SAVE never persisted it.
"""
from __future__ import annotations

import copy
from typing import Any

CANONICAL_FORMAT_KEY = "room_format"
CANONICAL_TEAM_KEY = "room_your_team"

# Settings keys we care about on each failing page. Label is human-friendly; the
# "kind" tags format/team aliases so the table can show the canonical column.
TRACKED_SETTINGS: dict[str, list[dict[str, str]]] = {
    "Live Draft Room": [
        {"key": "live_draft_league_name", "label": "League name"},
        {"key": "live_draft_team_count", "label": "Team count"},
        {"key": "live_draft_num_teams", "label": "Num teams"},
        {"key": "live_draft_picks_per_team", "label": "Picks/team"},
        {"key": "live_draft_type", "label": "Draft type"},
        {"key": "live_draft_scoring", "label": "Scoring", "kind": "format"},
        {"key": "live_draft_timer", "label": "Timer"},
        {"key": "live_draft_proj_style", "label": "Projection style"},
        {"key": "live_draft_proj_window", "label": "Projection window"},
    ],
    "Draft Room Simulator": [
        {"key": "room_your_team", "label": "Your team", "kind": "team"},
        {"key": "room_team_count", "label": "Team count"},
        {"key": "room_rounds", "label": "Rounds"},
        {"key": "room_format", "label": "Scoring format", "kind": "format"},
        {"key": "room_window", "label": "Projection window"},
        {"key": "room_team_names", "label": "Team names"},
        {"key": "fantasy_draft_projection_style", "label": "Projection style"},
    ],
    "Draft Assistant Simulator": [
        {"key": "draft_window", "label": "Projection window"},
        {"key": "draft_format", "label": "League format", "kind": "format"},
        {"key": "draft_top_n", "label": "Top N"},
        {"key": "fantasy_draft_projection_style", "label": "Projection style"},
        {"key": "draft_assistant_synced_team", "label": "Synced team", "kind": "team"},
    ],
    "Draft Simulation Test Mode": [
        {"key": "draft_lab_window", "label": "Projection window"},
        {"key": "draft_lab_scoring_type", "label": "Scoring type", "kind": "format"},
        {"key": "draft_lab_format", "label": "Format"},
        {"key": "draft_lab_projection_style", "label": "Projection style"},
        {"key": "draft_lab_picks_per_team", "label": "Picks/team"},
        {"key": "draft_lab_roster_team", "label": "Roster team", "kind": "team"},
    ],
}

_SAVE_TRACE_KEY = "_settings_save_trace"
_RESTORE_TRACE_KEY = "_settings_restore_trace"
_ONCHANGE_TRACE_KEY = "_settings_onchange_trace"
_TRACE_MAX = 30


def tracked_specs_for_page(page: str) -> list[dict[str, str]]:
    return TRACKED_SETTINGS.get(str(page or "").strip(), [])


def all_tracked_keys() -> set[str]:
    out: set[str] = set()
    for specs in TRACKED_SETTINGS.values():
        for spec in specs:
            out.add(spec["key"])
    return out


def _repr(value: Any) -> Any:
    """JSON-safe compact repr for trace storage / display."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]" if len(value) > 6 else list(value)
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return str(value)


def _ring_push(session: dict[str, Any], ring_key: str, entry: dict[str, Any]) -> None:
    ring = session.get(ring_key)
    if not isinstance(ring, list):
        ring = []
    ring.append(entry)
    session[ring_key] = ring[-_TRACE_MAX:]


def _snapshot_block(state: dict[str, Any], page: str) -> dict[str, Any]:
    pf = state.get("page_filter_state") if isinstance(state, dict) else None
    if isinstance(pf, dict):
        block = pf.get(page)
        if isinstance(block, dict):
            return block
    return {}


# ── recorders (called from the central save / restore choke points) ──────────

def record_onchange(session: dict[str, Any], key: str, *, handler: str, save_page_state: bool, force_save: bool, reason: str) -> None:
    """Called from a widget on_change to log that the edit fired and what it triggered."""
    _ring_push(session, _ONCHANGE_TRACE_KEY, {
        "key": key,
        "handler": handler,
        "new_value": _repr(session.get(key)),
        "save_page_state_called": bool(save_page_state),
        "force_save_called": bool(force_save),
        "reason": reason,
    })


def record_save_event(
    session: dict[str, Any],
    *,
    reason: str,
    state: dict[str, Any],
    saved_disk: bool,
    saved_cloud: bool,
    cloud_block: str | None,
) -> None:
    """Called inside force_autosave (baseball) to log exactly what was persisted."""
    try:
        active = str(session.get("active_page") or "").strip()
        specs = tracked_specs_for_page(active)
        block = _snapshot_block(state, active)
        per_key = {}
        for spec in specs:
            k = spec["key"]
            per_key[k] = {
                "session": _repr(session.get(k)),
                "saved_snapshot": _repr(block.get(k)),
                "saved_toplevel": _repr(state.get(k)) if k in state else None,
            }
        _ring_push(session, _SAVE_TRACE_KEY, {
            "active_page": active,
            "reason": reason,
            "saved_disk": bool(saved_disk),
            "saved_cloud": bool(saved_cloud),
            "cloud_save_allowed": not bool(cloud_block),
            "cloud_block_reason": cloud_block or "",
            "canonical_format": _repr(session.get(CANONICAL_FORMAT_KEY)),
            "canonical_team": _repr(session.get(CANONICAL_TEAM_KEY)),
            "tracked": per_key,
        })
    except Exception:
        pass


def record_restore_event(session: dict[str, Any], *, cloud_state: dict[str, Any], page: str) -> None:
    """Called inside apply_baseball_disk_state after restore to log final values."""
    try:
        specs = tracked_specs_for_page(page)
        if not specs:
            return
        cloud_block = _snapshot_block(cloud_state, page)
        per_key = {}
        for spec in specs:
            k = spec["key"]
            per_key[k] = {
                "cloud_snapshot": _repr(cloud_block.get(k)),
                "cloud_toplevel": _repr(cloud_state.get(k)) if k in cloud_state else None,
                "final_session": _repr(session.get(k)),
            }
        _ring_push(session, _RESTORE_TRACE_KEY, {
            "page": page,
            "blob_canonical_format": _repr(cloud_state.get(CANONICAL_FORMAT_KEY)),
            "final_canonical_format": _repr(session.get(CANONICAL_FORMAT_KEY)),
            "blob_canonical_team": _repr(cloud_state.get(CANONICAL_TEAM_KEY)),
            "final_canonical_team": _repr(session.get(CANONICAL_TEAM_KEY)),
            "tracked": per_key,
        })
    except Exception:
        pass


# ── live comparison table (read-only; loads durable blobs on demand) ─────────

def build_comparison_rows(
    session: dict[str, Any],
    page: str,
    *,
    cloud_state: dict[str, Any] | None,
    disk_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Per-tracked-key comparison of every storage tier for the given page."""
    specs = tracked_specs_for_page(page)
    sess_block = _snapshot_block(session, page)
    cloud_block = _snapshot_block(cloud_state or {}, page)
    disk_block = _snapshot_block(disk_state or {}, page)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        k = spec["key"]
        kind = spec.get("kind", "")
        canonical = None
        if kind == "format":
            canonical = session.get(CANONICAL_FORMAT_KEY)
        elif kind == "team":
            canonical = session.get(CANONICAL_TEAM_KEY)
        rows.append({
            "setting": spec["label"],
            "key": k,
            "session": _repr(session.get(k)),
            "canonical": _repr(canonical) if kind else "n/a",
            "page_snapshot": _repr(sess_block.get(k)),
            "cloud_snapshot": _repr(cloud_block.get(k)),
            "cloud_toplevel": _repr((cloud_state or {}).get(k)) if k in (cloud_state or {}) else "n/a",
            "disk_snapshot": _repr(disk_block.get(k)),
        })
    return rows


def get_save_trace(session: dict[str, Any]) -> list[dict[str, Any]]:
    return session.get(_SAVE_TRACE_KEY) or []


def get_restore_trace(session: dict[str, Any]) -> list[dict[str, Any]]:
    return session.get(_RESTORE_TRACE_KEY) or []


def get_onchange_trace(session: dict[str, Any]) -> list[dict[str, Any]]:
    return session.get(_ONCHANGE_TRACE_KEY) or []
