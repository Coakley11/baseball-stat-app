"""Narrow diagnostics for recommendation-card Add-to-Queue (QUEUE1C3 app path)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

TRACE_LEDGER_KEY = "_live_draft_rec_queue_click_trace_ledger"
TRACE_LAST_KEY = "_live_draft_rec_queue_click_trace_last"
WIDGET_REGISTRY_KEY = "_live_draft_rec_queue_widget_registry"
MAX_LEDGER = 24


def new_rec_queue_event_id() -> str:
    return uuid.uuid4().hex[:12]


def _ledger(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw = session.get(TRACE_LEDGER_KEY)
    if not isinstance(raw, list):
        raw = []
        session[TRACE_LEDGER_KEY] = raw
    return raw


def _append_ledger(session: dict[str, Any], row: dict[str, Any]) -> None:
    book = _ledger(session)
    book.append(row)
    if len(book) > MAX_LEDGER:
        del book[: len(book) - MAX_LEDGER]
    session[TRACE_LAST_KEY] = dict(row)


def register_rec_queue_widget(
    session: dict[str, Any],
    *,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    surface: str = "rec_card",
    already_queued: bool = False,
    canonical_widget_key: str | None = None,
) -> None:
    reg = session.get(WIDGET_REGISTRY_KEY)
    if not isinstance(reg, dict):
        reg = {}
        session[WIDGET_REGISTRY_KEY] = reg
    entry = {
        "room_id": str(room_id or "").strip(),
        "pick_index": int(pick_index),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "canonical_widget_key": str(canonical_widget_key or "").strip() or None,
        "surface": str(surface or "rec_card"),
        "already_queued": bool(already_queued),
        "ts": time.time(),
    }
    reg[str(widget_key)] = entry
    keys = list(reg.keys())
    session["_live_draft_rec_queue_widget_key_count"] = len(keys)
    dupes = _duplicate_widget_keys(reg)
    if dupes:
        session["_live_draft_rec_queue_widget_key_dupes"] = dupes
    else:
        session.pop("_live_draft_rec_queue_widget_key_dupes", None)


def _duplicate_widget_keys(reg: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for k in reg:
        ks = str(k)
        if ks in seen:
            dupes.append(ks)
        seen.add(ks)
    return dupes


LEGACY_REC_QUEUE_KEY_TEMPLATE = "rec_card_queue_{pick_index}_{stable_key}"
COLLISION_SAFE_REC_QUEUE_KEY_TEMPLATE = "rec_card_queue_{room_id}_{pick_index}_{stable_key}_{surface}"


def build_rec_card_queue_widget_key(
    *,
    room_id: str,
    pick_index: int,
    stable_key: str,
    surface: str = "rec_card",
) -> str:
    """Collision-safe widget key (room + pick + player + surface)."""
    rid = str(room_id or "noroom").strip().upper()[:16]
    sk = str(stable_key or "unknown").strip()[:48]
    surf = str(surface or "rec_card").strip()[:24]
    return f"rec_card_queue_{rid}_{int(pick_index)}_{sk}_{surf}"


def begin_rec_queue_click_trace(
    session: dict[str, Any],
    *,
    event_id: str,
    room_id: str,
    pick_index: int,
    player_id: str,
    player_name: str,
    widget_key: str,
    queue_before: list[str],
) -> None:
    eid = str(event_id or "").strip() or new_rec_queue_event_id()
    row: dict[str, Any] = {
        "event_id": eid,
        "ts": time.time(),
        "room_id": str(room_id or "").strip(),
        "pick_index": int(pick_index),
        "player_id": str(player_id or "").strip(),
        "player_name": str(player_name or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "surface": "rec_card",
        "button_event_observed": True,
        "callback_entered": True,
        "queue_before_mutation": list(queue_before)[:20],
        "mutation_helper_entered": False,
        "mutation_result": None,
        "queue_immediately_after_mutation": [],
        "added": False,
        "persistence_write_attempted": False,
        "persistence_write_result": None,
        "exception": None,
        "session_queue_key": "draft_queue",
    }
    _append_ledger(session, row)


def note_rec_queue_mutation_trace(
    session: dict[str, Any],
    *,
    event_id: str,
    mutation_helper_entered: bool,
    mutation_result: Any,
    queue_after: list[str],
    added: bool,
    exception: str | None = None,
) -> None:
    last = dict(session.get(TRACE_LAST_KEY) or {})
    if str(last.get("event_id") or "") != str(event_id):
        return
    last["mutation_helper_entered"] = bool(mutation_helper_entered)
    last["mutation_result"] = mutation_result
    last["queue_immediately_after_mutation"] = list(queue_after)[:20]
    last["added"] = bool(added)
    if exception:
        last["exception"] = str(exception)[:500]
    try:
        from live_draft_queue_persist import is_draft_queue_persist_dirty

        last["persistence_write_attempted"] = True
        last["persistence_write_result"] = "persist_dirty" if is_draft_queue_persist_dirty(session) else "not_dirty"
    except ImportError:
        last["persistence_write_attempted"] = False
    session[TRACE_LAST_KEY] = last
    book = _ledger(session)
    if book and str(book[-1].get("event_id") or "") == str(event_id):
        book[-1] = dict(last)
    else:
        _append_ledger(session, last)


def note_rec_queue_post_prepare(session: dict[str, Any], *, prepare_reason: str = "") -> None:
    """Run at end of prepare_draft_workflow — links rerun/hydration to last click trace."""
    last = dict(session.get(TRACE_LAST_KEY) or {})
    if not last.get("event_id"):
        return
    try:
        from draft_state import DRAFT_QUEUE_KEY, is_draft_locally_dirty

        q = [str(x).strip() for x in (session.get(DRAFT_QUEUE_KEY) or []) if str(x).strip()]
        ds_q: list[str] = []
        ds = session.get("draft_state")
        if isinstance(ds, dict):
            ds_q = [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]
    except ImportError:
        q = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]
        ds_q = []
        is_draft_locally_dirty = lambda _s: bool(_s.get("draft_state_dirty"))  # type: ignore[assignment,misc]

    snap = {
        "event_id": last.get("event_id"),
        "ts": time.time(),
        "phase": "post_prepare_draft_workflow",
        "prepare_reason": str(prepare_reason or ""),
        "queue_after_rerun_hydration": list(q)[:20],
        "draft_state_queue": list(ds_q)[:20],
        "locally_dirty": bool(is_draft_locally_dirty(session)),
        "hydrate_skipped": session.get("_live_draft_queue_hydrate_skipped"),
        "empty_write_blocked": session.get("_live_draft_queue_empty_write_blocked"),
        "stale_hydrate_blocked": session.get("_live_draft_queue_stale_hydrate_blocked"),
    }
    last["post_prepare"] = snap
    session[TRACE_LAST_KEY] = last
    book = _ledger(session)
    if book:
        book[-1] = dict(last)


def classify_rec_queue_trace(record: dict[str, Any] | None) -> str:
    """Map app-side trace to QUEUE1C3* subcode."""
    if not isinstance(record, dict) or not record.get("event_id"):
        return "QUEUE1C3"
    if not record.get("callback_entered"):
        return "QUEUE1C3A"
    if not record.get("mutation_helper_entered"):
        return "QUEUE1C3B"
    if record.get("exception"):
        return "QUEUE1C3G"
    added = bool(record.get("added"))
    after_mut = list(record.get("queue_immediately_after_mutation") or [])
    post = record.get("post_prepare") if isinstance(record.get("post_prepare"), dict) else {}
    after_hydrate = list(post.get("queue_after_rerun_hydration") or [])
    if added and after_mut and not after_hydrate:
        return "QUEUE1C3D"
    if added and after_mut and after_hydrate and not _name_in_queue(record.get("player_name"), after_hydrate):
        return "QUEUE1C3E" if post.get("draft_state_queue") else "QUEUE1C3D"
    if not added and not after_mut:
        return "QUEUE1C3C"
    if added and after_mut and _name_in_queue(record.get("player_name"), after_hydrate):
        return "QUEUE1C3F"
    return "QUEUE1C3_8"


def _name_in_queue(name: Any, queue: list[str]) -> bool:
    target = str(name or "").strip().lower()
    if not target:
        return False
    return target in {str(x).strip().lower() for x in queue}


def trace_export_payload(session: dict[str, Any]) -> dict[str, Any]:
    last = dict(session.get(TRACE_LAST_KEY) or {})
    reg = session.get(WIDGET_REGISTRY_KEY) if isinstance(session.get(WIDGET_REGISTRY_KEY), dict) else {}
    return {
        "last": last,
        "classification": classify_rec_queue_trace(last),
        "widget_registry_size": len(reg),
        "widget_key_dupes": session.get("_live_draft_rec_queue_widget_key_dupes") or [],
        "ledger_len": len(_ledger(session)),
    }


def render_rec_queue_click_trace_probe(st: Any, session: dict[str, Any]) -> None:
    """Hidden DOM probe for production harness (solo_component_diag surfaces)."""
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        if not solo_component_diag_enabled(st, session):
            return
    except ImportError:
        if not session.get("_solo_component_diag_enabled"):
            return
    payload = json.dumps(trace_export_payload(session), default=str)[:8000]
    last = dict(session.get(TRACE_LAST_KEY) or {})
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    st.markdown(
        f'<div id="rec-card-queue-click-trace" '
        f'data-event-id="{safe(last.get("event_id"))}" '
        f'data-callback-entered="{1 if last.get("callback_entered") else 0}" '
        f'data-added="{1 if last.get("added") else 0}" '
        f'data-classification="{safe(classify_rec_queue_trace(last))}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
