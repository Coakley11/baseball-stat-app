"""Canonical Draft Workflow state — draft queue + watchlist (sidebar-global)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import workflow_sidebar as wf_sb

DRAFT_DIRTY_KEY = "draft_state_dirty"
DRAFT_LOCAL_EDIT_TS_KEY = "draft_state_last_local_edit_ts"
DRAFT_PENDING_SYNC_KEY = "_draft_workflow_pending_sync"

DRAFT_WORKFLOW_BLOCK = "Draft Workflow"

DRAFT_QUEUE_KEY = wf_sb.SESSION_DRAFT_QUEUE
DRAFT_WATCHLIST_FOCUS_KEY = "draft_assistant_focus_players"
DRAFT_WATCHLIST_FAVORITES_KEY = wf_sb.SESSION_FAVORITES

DRAFT_WIDGET_KEYS = (
    DRAFT_QUEUE_KEY,
    DRAFT_WATCHLIST_FOCUS_KEY,
    DRAFT_WATCHLIST_FAVORITES_KEY,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_player_list(raw: Any) -> list[str]:
    return wf_sb.normalize_dedupe_queue(raw)


def is_draft_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_DIRTY_KEY))


def mark_draft_local_edit(session: dict[str, Any]) -> None:
    session[DRAFT_DIRTY_KEY] = True
    session[DRAFT_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_draft_local_edit(session: dict[str, Any]) -> None:
    session.pop(DRAFT_DIRTY_KEY, None)
    session.pop(DRAFT_LOCAL_EDIT_TS_KEY, None)


def _read_widget_lists(session: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "queue": _normalize_player_list(session.get(DRAFT_QUEUE_KEY)),
        "watchlist_focus": _normalize_player_list(session.get(DRAFT_WATCHLIST_FOCUS_KEY)),
        "watchlist_favorites": _normalize_player_list(session.get(DRAFT_WATCHLIST_FAVORITES_KEY)),
    }


def canonical_draft_workflow(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get("draft_state")
    if not isinstance(meta, dict):
        return None
    return {
        "queue": _normalize_player_list(meta.get("queue")),
        "watchlist_focus": _normalize_player_list(meta.get("watchlist_focus")),
        "watchlist_favorites": _normalize_player_list(meta.get("watchlist_favorites")),
        "last_write_reason": meta.get("last_write_reason"),
    }


def record_draft_field_write(
    session: dict[str, Any],
    field: str,
    source: str,
    old: Any = None,
    new: Any = None,
) -> None:
    session[f"_draft_last_write_{field}"] = source
    if old is not None:
        session[f"_draft_prev_{field}"] = old
    if new is not None:
        session[f"_draft_new_{field}"] = new


def _sync_page_filter_draft_block(session: dict[str, Any], *, data: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(DRAFT_WORKFLOW_BLOCK, {})
    if not isinstance(block, dict):
        block = {}
        pf[DRAFT_WORKFLOW_BLOCK] = block
    src = data if isinstance(data, dict) else _read_widget_lists(session)
    meta = session.get("draft_state")
    block[DRAFT_QUEUE_KEY] = list(src.get("queue") or [])
    block[DRAFT_WATCHLIST_FOCUS_KEY] = list(src.get("watchlist_focus") or [])
    block[DRAFT_WATCHLIST_FAVORITES_KEY] = list(src.get("watchlist_favorites") or [])
    if isinstance(meta, dict):
        block["draft_state"] = {
            "queue": list(meta.get("queue") or []),
            "watchlist_focus": list(meta.get("watchlist_focus") or []),
            "watchlist_favorites": list(meta.get("watchlist_favorites") or []),
            "last_write_reason": meta.get("last_write_reason"),
        }


def write_canonical_draft_state(
    session: dict[str, Any],
    *,
    queue: list[str] | None = None,
    watchlist_focus: list[str] | None = None,
    watchlist_favorites: list[str] | None = None,
    reason: str = "",
    local_edit: bool = False,
    sync_widget_keys: bool = True,
) -> dict[str, Any]:
    """Write canonical draft_state; mirror queue + watchlist widget keys."""
    widget = _read_widget_lists(session)
    q = _normalize_player_list(queue if queue is not None else widget["queue"])
    focus = _normalize_player_list(
        watchlist_focus if watchlist_focus is not None else widget["watchlist_focus"]
    )
    favorites = _normalize_player_list(
        watchlist_favorites if watchlist_favorites is not None else widget["watchlist_favorites"]
    )
    meta = {
        "queue": list(q),
        "watchlist_focus": list(focus),
        "watchlist_favorites": list(favorites),
        "last_write_reason": reason or None,
    }
    session["draft_state"] = meta
    if sync_widget_keys:
        session[DRAFT_QUEUE_KEY] = list(q)
        session[DRAFT_WATCHLIST_FOCUS_KEY] = list(focus)
        session[DRAFT_WATCHLIST_FAVORITES_KEY] = list(favorites)
    payload = {
        "queue": list(q),
        "watchlist_focus": list(focus),
        "watchlist_favorites": list(favorites),
    }
    session["_suite_last_cloud_payload_draft_workflow"] = copy.deepcopy(payload)
    _sync_page_filter_draft_block(session, data=payload)
    record_draft_field_write(session, "draft_workflow", reason or "canonical", new=payload)
    if local_edit:
        mark_draft_local_edit(session)
    return meta


def _draft_workflow_from_blob(state: dict[str, Any]) -> dict[str, list[str]]:
    if not isinstance(state, dict):
        return {"queue": [], "watchlist_focus": [], "watchlist_favorites": []}
    ds = state.get("draft_state")
    if isinstance(ds, dict):
        out = {
            "queue": _normalize_player_list(ds.get("queue")),
            "watchlist_focus": _normalize_player_list(ds.get("watchlist_focus")),
            "watchlist_favorites": _normalize_player_list(ds.get("watchlist_favorites")),
        }
        if out["queue"] or out["watchlist_focus"] or out["watchlist_favorites"]:
            return out
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_WORKFLOW_BLOCK)
        if isinstance(block, dict):
            inner = block.get("draft_state")
            if isinstance(inner, dict):
                out = {
                    "queue": _normalize_player_list(inner.get("queue")),
                    "watchlist_focus": _normalize_player_list(inner.get("watchlist_focus")),
                    "watchlist_favorites": _normalize_player_list(inner.get("watchlist_favorites")),
                }
                if out["queue"] or out["watchlist_focus"] or out["watchlist_favorites"]:
                    return out
            out = {
                "queue": _normalize_player_list(block.get(DRAFT_QUEUE_KEY)),
                "watchlist_focus": _normalize_player_list(block.get(DRAFT_WATCHLIST_FOCUS_KEY)),
                "watchlist_favorites": _normalize_player_list(block.get(DRAFT_WATCHLIST_FAVORITES_KEY)),
            }
            if out["queue"] or out["watchlist_focus"] or out["watchlist_favorites"]:
                return out
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict):
        dw = ws.get("draft_workflow")
        if isinstance(dw, dict):
            return {
                "queue": _normalize_player_list(dw.get("queue")),
                "watchlist_focus": _normalize_player_list(dw.get("watchlist_focus")),
                "watchlist_favorites": _normalize_player_list(dw.get("watchlist_favorites")),
            }
    return {"queue": [], "watchlist_focus": [], "watchlist_favorites": []}


def _draft_widget_drift(session: dict[str, Any]) -> bool:
    widget = _read_widget_lists(session)
    canonical = canonical_draft_workflow(session)
    if not canonical:
        return any(widget.values())
    for key in ("queue", "watchlist_focus", "watchlist_favorites"):
        if widget.get(key) != canonical.get(key):
            return True
    return False


def gather_draft_workflow(session: dict[str, Any]) -> dict[str, list[str]]:
    if is_draft_locally_dirty(session) or session.get(DRAFT_PENDING_SYNC_KEY) or _draft_widget_drift(session):
        widget = _read_widget_lists(session)
        canonical = canonical_draft_workflow(session) or {}
        return {
            "queue": widget["queue"] or canonical.get("queue") or [],
            "watchlist_focus": widget["watchlist_focus"] or canonical.get("watchlist_focus") or [],
            "watchlist_favorites": widget["watchlist_favorites"] or canonical.get("watchlist_favorites") or [],
        }
    canonical = canonical_draft_workflow(session)
    if canonical:
        return {
            "queue": list(canonical.get("queue") or []),
            "watchlist_focus": list(canonical.get("watchlist_focus") or []),
            "watchlist_favorites": list(canonical.get("watchlist_favorites") or []),
        }
    widget = _read_widget_lists(session)
    if any(widget.values()):
        return widget
    blob = _draft_workflow_from_blob(session)
    if any(blob.values()):
        return blob
    return widget


def prepare_draft_workflow(session: dict[str, Any]) -> dict[str, Any]:
    """Reconcile draft queue + watchlist before sidebar widgets render."""
    widget = _read_widget_lists(session)
    drift = _draft_widget_drift(session) or bool(session.get(DRAFT_PENDING_SYNC_KEY))
    if is_draft_locally_dirty(session) or drift:
        canonical = canonical_draft_workflow(session) or {}
        return write_canonical_draft_state(
            session,
            queue=widget["queue"] or canonical.get("queue"),
            watchlist_focus=widget["watchlist_focus"] or canonical.get("watchlist_focus"),
            watchlist_favorites=widget["watchlist_favorites"] or canonical.get("watchlist_favorites"),
            reason="local_edit_preserve" if is_draft_locally_dirty(session) else "widget_drift",
            local_edit=True,
            sync_widget_keys=False,
        )
    canonical = canonical_draft_workflow(session)
    if canonical and any(canonical.get(k) for k in ("queue", "watchlist_focus", "watchlist_favorites")):
        return write_canonical_draft_state(
            session,
            queue=canonical.get("queue"),
            watchlist_focus=canonical.get("watchlist_focus"),
            watchlist_favorites=canonical.get("watchlist_favorites"),
            reason="canonical_preserve",
            sync_widget_keys=not any(widget.values()),
        )
    gathered = gather_draft_workflow(session)
    return write_canonical_draft_state(
        session,
        queue=gathered["queue"],
        watchlist_focus=gathered["watchlist_focus"],
        watchlist_favorites=gathered["watchlist_favorites"],
        reason="reconcile_on_load" if any(gathered.values()) else "empty",
    )


def mark_draft_pending_sync(session: dict[str, Any]) -> None:
    session[DRAFT_PENDING_SYNC_KEY] = True


def flush_draft_workflow_edits(session: dict[str, Any], st_obj: Any = None, *, reason: str = "draft_flush") -> bool:
    pending = bool(session.pop(DRAFT_PENDING_SYNC_KEY, False))
    widget = _read_widget_lists(session)
    canonical = canonical_draft_workflow(session) or {}
    changed = widget != {
        "queue": canonical.get("queue") or [],
        "watchlist_focus": canonical.get("watchlist_focus") or [],
        "watchlist_favorites": canonical.get("watchlist_favorites") or [],
    }
    if not pending and not changed:
        return False
    write_canonical_draft_state(
        session,
        queue=widget["queue"],
        watchlist_focus=widget["watchlist_focus"],
        watchlist_favorites=widget["watchlist_favorites"],
        reason=reason,
        local_edit=True,
        sync_widget_keys=False,
    )
    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st_obj, reason="draft_edit")
        except Exception:
            pass
    return True


def sync_draft_queue(session: dict[str, Any], queue: Any, *, reason: str = "queue_change") -> list[str]:
    q = _normalize_player_list(queue)
    write_canonical_draft_state(session, queue=q, reason=reason, local_edit=True)
    return q


def sync_watchlist(
    session: dict[str, Any],
    *,
    watchlist_focus: Any = None,
    watchlist_favorites: Any = None,
    reason: str = "watchlist_change",
) -> dict[str, list[str]]:
    kwargs: dict[str, Any] = {"reason": reason, "local_edit": True}
    if watchlist_focus is not None:
        kwargs["watchlist_focus"] = _normalize_player_list(watchlist_focus)
    if watchlist_favorites is not None:
        kwargs["watchlist_favorites"] = _normalize_player_list(watchlist_favorites)
    meta = write_canonical_draft_state(session, **kwargs)
    return {
        "watchlist_focus": list(meta.get("watchlist_focus") or []),
        "watchlist_favorites": list(meta.get("watchlist_favorites") or []),
    }


def add_player_to_draft_queue(session: dict[str, Any], player_name: str) -> tuple[list[str], bool]:
    name = str(player_name or "").strip()
    if not name:
        return _normalize_player_list(session.get(DRAFT_QUEUE_KEY)), False
    q = _normalize_player_list(session.get(DRAFT_QUEUE_KEY))
    if name in q:
        return q, False
    q.append(name)
    sync_draft_queue(session, q, reason="add_to_queue")
    return q, True


def add_player_to_watchlist(session: dict[str, Any], player_name: str) -> tuple[list[str], bool]:
    from player_actions import dedupe_append_name

    name = str(player_name or "").strip()
    if not name:
        focus = _normalize_player_list(session.get(DRAFT_WATCHLIST_FOCUS_KEY))
        return focus, False
    focus = _normalize_player_list(session.get(DRAFT_WATCHLIST_FOCUS_KEY))
    if name in focus:
        return focus, False
    focus = dedupe_append_name(focus, name, cap=10)
    favorites = dedupe_append_name(
        _normalize_player_list(session.get(DRAFT_WATCHLIST_FAVORITES_KEY)),
        name,
        cap=wf_sb.FAVORITES_CAP,
    )
    sync_watchlist(session, watchlist_focus=focus, watchlist_favorites=favorites, reason="add_to_watchlist")
    return focus, True


def clear_draft_queue(session: dict[str, Any], *, reason: str = "clear_queue") -> None:
    sync_draft_queue(session, [], reason=reason)


def clear_watchlist(session: dict[str, Any], *, reason: str = "clear_watchlist") -> None:
    sync_watchlist(session, watchlist_focus=[], watchlist_favorites=[], reason=reason)


def restore_draft_workflow_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_draft_locally_dirty(session):
        record_draft_field_write(session, "page_filter_restore", "blocked_local_dirty")
        return False
    snapshot = store.get(DRAFT_WORKFLOW_BLOCK) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    inner = snapshot.get("draft_state")
    if isinstance(inner, dict):
        write_canonical_draft_state(
            session,
            queue=inner.get("queue"),
            watchlist_focus=inner.get("watchlist_focus"),
            watchlist_favorites=inner.get("watchlist_favorites"),
            reason="page_filter_restore",
            local_edit=False,
        )
    else:
        write_canonical_draft_state(
            session,
            queue=snapshot.get(DRAFT_QUEUE_KEY),
            watchlist_focus=snapshot.get(DRAFT_WATCHLIST_FOCUS_KEY),
            watchlist_favorites=snapshot.get(DRAFT_WATCHLIST_FAVORITES_KEY),
            reason="page_filter_restore",
            local_edit=False,
        )
    return True


def apply_cloud_draft_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_draft_locally_dirty(session):
        return False
    data = _draft_workflow_from_blob(state)
    if not data["queue"] and not data["watchlist_focus"] and not data["watchlist_favorites"]:
        return False
    write_canonical_draft_state(
        session,
        queue=data["queue"],
        watchlist_focus=data["watchlist_focus"],
        watchlist_favorites=data["watchlist_favorites"],
        reason="cloud_restore",
        local_edit=False,
    )
    clear_draft_local_edit(session)
    session["_draft_restored_workflow"] = copy.deepcopy(data)
    session["_draft_restore_source"] = session.get("_suite_persist_last_restore_source", "cloud")
    return True


def apply_draft_source_state_from_ami(session: dict[str, Any], source_state: dict[str, Any]) -> None:
    """Restore draft queue + watchlist from Applied Math return."""
    ent = dict(source_state.get("entity_params") or {})
    wp = dict(source_state.get("widget_params") or {})
    queue = ent.get("draft_queue") or wp.get(DRAFT_QUEUE_KEY)
    focus = ent.get("watchlist_focus") or wp.get(DRAFT_WATCHLIST_FOCUS_KEY)
    favorites = ent.get("watchlist_favorites") or wp.get(DRAFT_WATCHLIST_FAVORITES_KEY)
    write_canonical_draft_state(
        session,
        queue=queue if queue is not None else session.get(DRAFT_QUEUE_KEY),
        watchlist_focus=focus if focus is not None else session.get(DRAFT_WATCHLIST_FOCUS_KEY),
        watchlist_favorites=favorites if favorites is not None else session.get(DRAFT_WATCHLIST_FAVORITES_KEY),
        reason="ami_return",
        local_edit=False,
    )
    clear_draft_local_edit(session)


def render_draft_state_debug(st: Any, session: dict[str, Any]) -> None:
    meta = session.get("draft_state")
    if not isinstance(meta, dict):
        meta = {}
    pf = session.get("page_filter_state")
    pf_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get(DRAFT_WORKFLOW_BLOCK)
        if isinstance(block, dict):
            pf_block = block
    cloud_payload = session.get("_suite_last_cloud_payload_draft_workflow")
    rows = {
        "draft_state_dirty": session.get(DRAFT_DIRTY_KEY),
        "last_write_reason": meta.get("last_write_reason"),
        "raw draft_queue widget": session.get(DRAFT_QUEUE_KEY),
        "canonical queue": meta.get("queue"),
        "page_filter_state queue": pf_block.get(DRAFT_QUEUE_KEY),
        "cloud_payload queue": (cloud_payload or {}).get("queue") if isinstance(cloud_payload, dict) else None,
        "raw watchlist_focus widget": session.get(DRAFT_WATCHLIST_FOCUS_KEY),
        "canonical watchlist_focus": meta.get("watchlist_focus"),
        "page_filter_state watchlist_focus": pf_block.get(DRAFT_WATCHLIST_FOCUS_KEY),
        "cloud_payload watchlist_focus": (cloud_payload or {}).get("watchlist_focus")
        if isinstance(cloud_payload, dict)
        else None,
        "raw watchlist_favorites widget": session.get(DRAFT_WATCHLIST_FAVORITES_KEY),
        "canonical watchlist_favorites": meta.get("watchlist_favorites"),
        "page_filter_state watchlist_favorites": pf_block.get(DRAFT_WATCHLIST_FAVORITES_KEY),
        "cloud_payload watchlist_favorites": (cloud_payload or {}).get("watchlist_favorites")
        if isinstance(cloud_payload, dict)
        else None,
        "pending_sync": session.get(DRAFT_PENDING_SYNC_KEY),
        "restored_workflow": session.get("_draft_restored_workflow"),
        "restore_source": session.get("_draft_restore_source"),
        "last_force_save_reason": session.get("_suite_persist_last_save_reason"),
        "last_save_cloud": session.get("_suite_persist_last_save_cloud"),
        "cloud_block_reason": session.get("_suite_autosave_cloud_blocked_reason"),
    }
    with st.sidebar.expander("Draft Workflow state", expanded=False):
        for k, v in rows.items():
            if v is not None and v != "" and v is not False and v != {}:
                st.text(f"{k}: {v}")


def _compact_player_rows(df_or_rows: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    """JSON-safe player rows for AMI source_state (names + key metrics only)."""
    import pandas as pd

    rows: list[dict[str, Any]] = []
    if isinstance(df_or_rows, pd.DataFrame):
        if df_or_rows.empty:
            return rows
        for _, row in df_or_rows.head(limit).iterrows():
            name = str(row.get("Player") or row.get("fullName") or "").strip()
            if not name:
                continue
            entry: dict[str, Any] = {"player": name}
            for col in (
                "Primary Position",
                "Expected Fantasy Value",
                "Model Rank",
                "Market Rank",
                "Sleeper Score",
                "Draft Fit Score",
            ):
                if col in row.index and pd.notna(row[col]):
                    entry[col] = row[col]
            rows.append(entry)
        return rows
    if isinstance(df_or_rows, list):
        for item in df_or_rows[:limit]:
            if isinstance(item, dict):
                name = str(item.get("Player") or item.get("fullName") or item.get("player") or "").strip()
                if name:
                    rows.append({"player": name, **{k: v for k, v in item.items() if k in ("Primary Position", "Expected Fantasy Value")}})
            elif item:
                rows.append({"player": str(item).strip()})
    return rows


def gather_draft_ami_snapshot(page: str, session: dict[str, Any]) -> dict[str, Any]:
    """
    JSON-safe draft context for AMI source_state and solver context.

    Includes queue, watchlist, live draft pick/roster, recommendations, sleepers, and settings.
    """
    dw = gather_draft_workflow(session)
    snapshot: dict[str, Any] = {
        "page": page,
        "draft_queue": list(dw.get("queue") or [])[:12],
        "watchlist_focus": list(dw.get("watchlist_focus") or [])[:20],
        "watchlist_favorites": list(dw.get("watchlist_favorites") or [])[:20],
    }
    scoring: dict[str, Any] = {}
    for key in (
        "draft_format",
        "draft_lab_scoring_type",
        "draft_lab_format",
        "fantasy_draft_projection_style",
        "room_format",
        "room_your_team",
        "room_team_count",
        "room_rounds",
        "draft_window",
        "draft_top_n",
    ):
        val = session.get(key)
        if val is not None and str(val).strip() not in ("", "—"):
            scoring[key] = val
    if scoring:
        snapshot["scoring_settings"] = scoring

    room = session.get("live_draft_room")
    if isinstance(room, dict) and room:
        try:
            from streamlit_app import (
                live_draft_current_slot,
                live_draft_recommendations,
                serialize_live_draft_room,
            )

            serialized = serialize_live_draft_room(room)
            snapshot["draft_state"] = {
                "status": serialized.get("status"),
                "current_pick_index": serialized.get("current_pick_index"),
                "draft_room_id": serialized.get("draft_room_id"),
            }
            cfg = dict(serialized.get("config") or room.get("config") or {})
            for k in ("scoring_type", "draft_type", "league_name", "picks_per_team", "num_teams", "your_team"):
                if cfg.get(k) is not None:
                    scoring.setdefault(k, cfg.get(k))
            if scoring:
                snapshot["scoring_settings"] = scoring
            slot = live_draft_current_slot(room)
            if slot:
                idx = int(serialized.get("current_pick_index") or 0)
                num_teams = int(cfg.get("num_teams") or len(room.get("teams") or []) or 12)
                snapshot["current_pick"] = int(slot.get("Pick") or idx + 1)
                snapshot["draft_round"] = (idx // num_teams) + 1 if num_teams else None
                your_team = str(slot.get("Team") or cfg.get("your_team") or session.get("room_your_team") or "")
                if your_team:
                    snapshot["your_team"] = your_team
                    roster = (room.get("rosters") or {}).get(your_team) or []
                    snapshot["user_roster"] = [
                        str(p.get("fullName") or p.get("Player") or p)[:80]
                        for p in roster[:24]
                        if isinstance(p, dict)
                    ]
            top_rec, best_avail, _pos_fit, sleepers = live_draft_recommendations(room, top_n=8)
            snapshot["recommended_players"] = _compact_player_rows(top_rec)
            snapshot["available_players"] = _compact_player_rows(best_avail)
            snapshot["sleepers"] = _compact_player_rows(sleepers)
        except Exception:
            pass

    drt = session.get("draft_room_table")
    if drt is not None and hasattr(drt, "head"):
        try:
            snapshot["draft_room_board"] = drt.head(24).to_dict(orient="records")
        except Exception:
            pass

    cached = session.get("_ami_draft_snapshot")
    if isinstance(cached, dict):
        for k, v in cached.items():
            if k not in snapshot or not snapshot.get(k):
                snapshot[k] = v

    return snapshot


def build_draft_ami_trace(source_state: dict[str, Any]) -> dict[str, Any]:
    """Trace flags for baseball draft AMI packaging (debug + acceptance)."""
    import json

    ent = dict(source_state.get("entity_params") or {})
    snap = ent.get("draft_snapshot") if isinstance(ent.get("draft_snapshot"), dict) else {}
    payload = json.dumps(source_state, default=str)
    player_count = 0
    for key in ("user_roster", "draft_queue", "recommended_players", "available_players", "sleepers", "watchlist_focus"):
        block = snap.get(key)
        if isinstance(block, list):
            player_count += len(block)
    return {
        "source_app": source_state.get("source_app") or "baseball",
        "source_page": source_state.get("source_page"),
        "source_state_keys": sorted(source_state.keys()),
        "source_state_has_draft_state": bool(snap.get("draft_state")),
        "source_state_has_roster": bool(snap.get("user_roster")),
        "source_state_has_available_players": bool(snap.get("available_players")),
        "source_state_has_recommendations": bool(snap.get("recommended_players")),
        "source_state_has_sleepers": bool(snap.get("sleepers")),
        "source_state_has_scoring_settings": bool(snap.get("scoring_settings")),
        "source_state_has_selected_players": bool(snap.get("draft_queue") or snap.get("watchlist_focus")),
        "source_state_player_count": player_count,
        "source_state_payload_size": len(payload),
    }

