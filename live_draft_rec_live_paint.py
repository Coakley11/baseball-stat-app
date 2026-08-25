"""Live interactive recommendation widgets — separate from one-shot heavy/deferred compute."""

from __future__ import annotations

import time
from typing import Any

PREPARED_REC_INTERACTIVE_KEY = "_live_draft_rec_interactive_paint_v1"
HEAVY_REC_COMPUTE_DONE_KEY = "_live_draft_heavy_rec_compute_done"
INTERACTIVE_PAINT_STATUS_KEY = "_live_draft_rec_interactive_paint_status"
# Survives REC_CACHE invalidation so the consuming ScriptRun can re-register st.button
# without waiting for a second rerun (production 19ea13e / 31f2a299: lifecycle stuck at 21).
INTERACTIVE_TOP_REC_SNAPSHOT_KEY = "_live_draft_rec_interactive_top_rec_snapshot"
RUN_STAGE_LEDGER_KEY = "_live_draft_rec_run_stage_ledger"


def note_rec_run_stage(session: dict[str, Any], stage: str, **extra: Any) -> None:
    """Append a narrow per-ScriptRun stage marker for consumption forensics."""
    seq = int(session.get("_solo_stage1_script_run_seq") or session.get("_live_draft_cloud_diag_run_seq") or 0)
    row = {"ts": time.time(), "run_seq": seq, "stage": str(stage), **extra}
    log = list(session.get(RUN_STAGE_LEDGER_KEY) or [])
    log.append(row)
    session[RUN_STAGE_LEDGER_KEY] = log[-80:]
    session["_live_draft_rec_run_stage_last"] = row


def store_prepared_rec_interactive(
    session: dict[str, Any],
    *,
    room_id: str,
    gaps: list[str] | None,
    category_needs: list[str] | None,
    max_cards: int = 6,
    multiplayer: bool = False,
) -> None:
    """Persist render inputs; top_rec rows come from REC_CACHE_KEY (no duplicate scoring)."""
    session[PREPARED_REC_INTERACTIVE_KEY] = {
        "room_id": str(room_id or "").strip(),
        "gaps": list(gaps or []),
        "category_needs": list(category_needs or []),
        "max_cards": int(max_cards),
        "multiplayer": bool(multiplayer),
        "prepared_ts": time.time(),
    }


def store_interactive_top_rec_snapshot(
    session: dict[str, Any],
    top_rec: Any,
    *,
    room_id: str,
) -> None:
    """Keep last-good recommendation rows for same-run button re-registration after cache clear."""
    if top_rec is None or getattr(top_rec, "empty", True):
        return
    try:
        snap_df = top_rec.copy()
    except Exception:
        snap_df = top_rec
    session[INTERACTIVE_TOP_REC_SNAPSHOT_KEY] = {
        "room_id": str(room_id or "").strip(),
        "top_rec": snap_df,
        "snap_ts": time.time(),
    }


def mark_heavy_rec_compute_done(session: dict[str, Any]) -> None:
    session[HEAVY_REC_COMPUTE_DONE_KEY] = True


def heavy_rec_compute_done(session: dict[str, Any]) -> bool:
    return bool(session.get(HEAVY_REC_COMPUTE_DONE_KEY))


def _top_rec_from_cache(session: dict[str, Any]) -> Any:
    try:
        from live_draft_ui_cache import REC_CACHE_KEY

        entry = session.get(REC_CACHE_KEY)
    except ImportError:
        entry = session.get("_live_draft_rec_cache")
    if isinstance(entry, dict):
        return entry.get("top_rec")
    return None


def _top_rec_from_snapshot(session: dict[str, Any], room: dict[str, Any]) -> Any:
    snap = session.get(INTERACTIVE_TOP_REC_SNAPSHOT_KEY)
    if not isinstance(snap, dict):
        return None
    rid = str(room.get("draft_room_id") or "").strip()
    snap_rid = str(snap.get("room_id") or "").strip()
    if rid and snap_rid and snap_rid != rid:
        return None
    return snap.get("top_rec")


def _republish_top_rec_into_cache(session: dict[str, Any], room: dict[str, Any], top_rec: Any) -> None:
    """Ensure REC_CACHE_KEY is populated from snapshot/rebuild so later paint_body defer paths see rows."""
    if top_rec is None or getattr(top_rec, "empty", True):
        return
    try:
        from live_draft_ui_cache import REC_CACHE_KEY

        entry = session.get(REC_CACHE_KEY)
        if not isinstance(entry, dict):
            entry = {}
        entry = dict(entry)
        entry["top_rec"] = top_rec
        entry["restored_for_interactive"] = True
        entry["restored_ts"] = time.time()
        session[REC_CACHE_KEY] = entry
    except ImportError:
        session["_live_draft_rec_cache"] = {
            "top_rec": top_rec,
            "restored_for_interactive": True,
            "restored_ts": time.time(),
        }


def _rebuild_top_rec_into_cache(
    session: dict[str, Any],
    room: dict[str, Any],
    prep: dict[str, Any],
) -> Any:
    """Restore recommendation rows after cache invalidation while HEAVY_PAINT_DONE stays set.

    After first heavy paint, interactive registration never re-enters paint_body. If
    ``REC_CACHE_KEY`` was cleared (poll/pick/invalidate), the consuming ScriptRun would
    otherwise skip ``st.button`` and drop the incoming ``trigger_value=true``.
    """
    note_rec_run_stage(session, "rebuild_started")
    max_cards = int(prep.get("max_cards") or 6)
    cfg = dict(room.get("config") or {})
    team = str(
        cfg.get("user_team")
        or cfg.get("your_team")
        or session.get("live_draft_my_team")
        or session.get("room_your_team")
        or ""
    ).strip() or None
    try:
        from live_draft_recommendations import live_draft_recommendations
        from live_draft_ui_cache import (
            REC_CACHE_KEY,
            filter_recommendation_tables_for_drafted,
            live_draft_ui_cache_key,
        )

        top_n = max(8, max_cards)
        top_rec, best_avail, pos_fit, value_sleep = live_draft_recommendations(
            room, top_n=top_n, team=team, session=session
        )
        top_rec, best_avail, pos_fit, value_sleep = filter_recommendation_tables_for_drafted(
            room, top_rec, best_avail, pos_fit, value_sleep
        )
        session[REC_CACHE_KEY] = {
            "key": live_draft_ui_cache_key(session, room, top_n=top_n, team=team),
            "top_rec": top_rec,
            "best_avail": best_avail,
            "pos_fit": pos_fit,
            "value_sleep": value_sleep,
            "rebuilt_for_interactive": True,
            "rebuilt_ts": time.time(),
        }
        ok = top_rec is not None and not getattr(top_rec, "empty", True)
        note_rec_run_stage(
            session,
            "rebuild_succeeded" if ok else "rebuild_empty",
            top_rec_count=int(len(top_rec)) if ok else 0,
        )
        return top_rec
    except Exception as exc:
        session["_live_draft_rec_interactive_rebuild_error"] = f"{type(exc).__name__}: {exc}"[:240]
        note_rec_run_stage(session, "rebuild_failed", error=str(exc)[:160])
        return None


def render_rec_interactive_widgets(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    fmt_rate_4=None,
    fmt_int=None,
) -> bool:
    """Render recommendation card Streamlit widgets from prepared cache (live path)."""
    note_rec_run_stage(session, "interactive_invoked")
    status: dict[str, Any] = {
        "ts": time.time(),
        "ok": False,
        "fail_reason": "",
        "cache_hit": False,
        "cache_rebuilt": False,
        "snapshot_used": False,
        "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
    }
    prep = session.get(PREPARED_REC_INTERACTIVE_KEY)
    if not isinstance(prep, dict):
        status["fail_reason"] = "prepared_interactive_missing"
        session[INTERACTIVE_PAINT_STATUS_KEY] = status
        note_rec_run_stage(session, "interactive_failed", fail_reason=status["fail_reason"])
        return False
    rid = str(room.get("draft_room_id") or "").strip()
    if rid and str(prep.get("room_id") or "").strip() not in ("", rid):
        status["fail_reason"] = "prepared_room_mismatch"
        session[INTERACTIVE_PAINT_STATUS_KEY] = status
        note_rec_run_stage(session, "interactive_failed", fail_reason=status["fail_reason"])
        return False
    top_rec = _top_rec_from_cache(session)
    if top_rec is not None and not getattr(top_rec, "empty", True):
        status["cache_hit"] = True
        note_rec_run_stage(session, "cache_hit", top_rec_count=int(len(top_rec)))
    else:
        note_rec_run_stage(session, "cache_miss")
        # Prefer last-good snapshot over expensive rebuild so the consuming ScriptRun
        # re-registers the same buttons without requiring an extra rerun.
        top_rec = _top_rec_from_snapshot(session, room)
        if top_rec is not None and not getattr(top_rec, "empty", True):
            status["snapshot_used"] = True
            _republish_top_rec_into_cache(session, room, top_rec)
            note_rec_run_stage(session, "snapshot_restored", top_rec_count=int(len(top_rec)))
        else:
            top_rec = _rebuild_top_rec_into_cache(session, room, prep)
            status["cache_rebuilt"] = top_rec is not None and not getattr(top_rec, "empty", True)
            if top_rec is None or getattr(top_rec, "empty", True):
                status["fail_reason"] = "top_rec_missing_after_rebuild"
                session[INTERACTIVE_PAINT_STATUS_KEY] = status
                note_rec_run_stage(session, "interactive_failed", fail_reason=status["fail_reason"])
                return False
    gaps = list(prep.get("gaps") or [])
    category_needs = list(prep.get("category_needs") or [])
    max_cards = int(prep.get("max_cards") or 6)
    multiplayer = bool(prep.get("multiplayer"))
    try:
        from live_draft_room_ui import render_live_draft_rec_cards, render_live_draft_rec_summary_banner

        render_live_draft_rec_summary_banner(st, top_rec, gaps=gaps)
        render_live_draft_rec_cards(
            st,
            session,
            room,
            top_rec,
            max_cards=max_cards,
            multiplayer=multiplayer,
            fmt_rate_4=fmt_rate_4,
            fmt_int=fmt_int,
            gaps=gaps,
            category_needs=category_needs,
        )
        store_interactive_top_rec_snapshot(session, top_rec, room_id=rid)
        status["ok"] = True
        status["fail_reason"] = ""
        status["top_rec_count"] = int(len(top_rec)) if hasattr(top_rec, "__len__") else 0
        session[INTERACTIVE_PAINT_STATUS_KEY] = status
        note_rec_run_stage(
            session,
            "interactive_ok",
            top_rec_count=status["top_rec_count"],
            cache_hit=status["cache_hit"],
            snapshot_used=status["snapshot_used"],
            cache_rebuilt=status["cache_rebuilt"],
        )
        return True
    except ImportError:
        status["fail_reason"] = "room_ui_import_error"
        session[INTERACTIVE_PAINT_STATUS_KEY] = status
        note_rec_run_stage(session, "interactive_failed", fail_reason=status["fail_reason"])
        return False
    except Exception as exc:
        status["fail_reason"] = f"interactive_exception:{type(exc).__name__}"
        status["exception"] = str(exc)[:200]
        session[INTERACTIVE_PAINT_STATUS_KEY] = status
        session["_live_draft_rec_interactive_paint_error"] = f"{type(exc).__name__}: {exc}"[:240]
        note_rec_run_stage(session, "interactive_failed", fail_reason=status["fail_reason"])
        return False


def count_add_to_queue_widget_keys_in_session(session: dict[str, Any], *, room_id: str, pick_index: int) -> int:
    """Test helper: count registered rec-card queue keys for one pick (duplicate detection)."""
    prefix = f"rec_card_queue_{str(room_id or '').strip().upper()[:16]}_{int(pick_index)}_"
    reg = session.get("_live_draft_rec_queue_render_registry")
    if not isinstance(reg, list):
        return 0
    return sum(
        1
        for row in reg
        if isinstance(row, dict) and str(row.get("widget_key") or "").startswith(prefix)
    )
