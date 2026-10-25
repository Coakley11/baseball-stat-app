"""Solo Preparing/Ready Pick-1 product snapshot — Start must only flip state.

Heavy recommendation / needs / available / rankings prep belongs here (timer off),
not on the first in_progress ScriptRun after Start Draft.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PICK1_SNAPSHOT_KEY = "_solo_pick1_product_snapshot"
PICK1_TIMINGS_KEY = "_solo_pick1_prewarm_timings"
PICK1_READY_FLAG = "_solo_pick1_product_ready"


def _probe_write(name: str, payload: dict[str, Any]) -> None:
    """Developer-only prewarm probe dump.

    Gated at the writer so every call site is covered: prewarm runs repeatedly
    while Solo sits in Preparing/Ready, and normal users must not pay disk I/O
    on the path this work exists to keep fast.
    """
    try:
        import streamlit as _st
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=_st):
            return
    except Exception:
        return
    try:
        out = Path(__file__).resolve().parent / "data" / "tb_probe" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _team_for_pick1(session: dict[str, Any], room: dict[str, Any]) -> str:
    cfg = dict(room.get("config") or {})
    return str(
        cfg.get("your_team")
        or cfg.get("user_team")
        or session.get("room_your_team")
        or session.get("live_draft_my_team")
        or ""
    ).strip()


def pick1_snapshot_is_ready(session: dict[str, Any] | None, room: dict[str, Any] | None = None) -> bool:
    if not isinstance(session, dict):
        return False
    snap = session.get(PICK1_SNAPSHOT_KEY)
    flag = bool(session.get(PICK1_READY_FLAG))
    if not isinstance(snap, dict) or not snap.get("ok"):
        return False
    if room is None:
        room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return bool(flag or snap.get("ok"))
    try:
        pick_index = int(room.get("current_pick_index") or 0)
    except (TypeError, ValueError):
        pick_index = 0
    if pick_index != 0:
        return False
    board = room.get("draft_board")
    try:
        board_len = len(board) if board is not None else 0
    except Exception:
        board_len = 0
    if board_len != 0:
        return False
    rid = str(room.get("draft_room_id") or "").strip()
    snap_rid = str(snap.get("room_id") or "").strip()
    if rid and snap_rid and snap_rid != rid and not flag:
        return False
    return True


def rebind_pick1_snapshot_cache_keys(session: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    """After Start mutates room metadata, retarget cache keys without rescoring."""
    out: dict[str, Any] = {"ok": False, "rebound": []}
    if not isinstance(room, dict):
        out["reason"] = "no_room"
        return out
    try:
        from live_draft_ui_cache import (
            AVAILABLE_CACHE_KEY,
            DECISION_CACHE_KEY,
            REC_CACHE_KEY,
            WHY_COLUMN_CACHE_KEY,
            available_pool_cache_key,
            live_draft_ui_cache_key,
        )
    except ImportError:
        out["reason"] = "cache_import"
        return out

    team = _team_for_pick1(session, room) or None
    ui_key_10 = live_draft_ui_cache_key(session, room, top_n=10, team=team)
    ui_key_8 = live_draft_ui_cache_key(session, room, top_n=8, team=team)
    avail_key = available_pool_cache_key(room)

    entry = session.get(REC_CACHE_KEY)
    if isinstance(entry, dict) and entry.get("top_rec") is not None:
        entry = dict(entry)
        # Prefer the heavy-paint key (top_n=10); early path tolerates key mismatch via snapshot.
        entry["key"] = ui_key_10
        entry["key_top_n_8"] = ui_key_8
        entry["rebound_after_start"] = True
        session[REC_CACHE_KEY] = entry
        out["rebound"].append("rec")

    avail = session.get(AVAILABLE_CACHE_KEY)
    if isinstance(avail, dict) and (
        avail.get("df") is not None or avail.get("available") is not None
    ):
        avail = dict(avail)
        avail["key"] = avail_key
        session[AVAILABLE_CACHE_KEY] = avail
        out["rebound"].append("available")

    decision = session.get(DECISION_CACHE_KEY)
    if isinstance(decision, dict):
        decision = dict(decision)
        decision["key"] = ui_key_10
        session[DECISION_CACHE_KEY] = decision
        out["rebound"].append("decision")

    why = session.get(WHY_COLUMN_CACHE_KEY)
    if isinstance(why, dict):
        why = dict(why)
        why["key"] = ui_key_10
        session[WHY_COLUMN_CACHE_KEY] = why
        out["rebound"].append("why")

    try:
        from live_draft_rec_live_paint import INTERACTIVE_TOP_REC_SNAPSHOT_KEY

        snap = session.get(INTERACTIVE_TOP_REC_SNAPSHOT_KEY)
        if isinstance(snap, dict):
            snap = dict(snap)
            snap["cache_key"] = ui_key_8
            snap["pick_index"] = int(room.get("current_pick_index") or 0)
            snap["board_len"] = len(room.get("draft_board") or [])
            snap["room_id"] = str(room.get("draft_room_id") or "").strip()
            session[INTERACTIVE_TOP_REC_SNAPSHOT_KEY] = snap
            out["rebound"].append("interactive")
    except ImportError:
        pass

    try:
        from live_draft_rec_live_paint import rec_paint_state_version

        session["_solo_rec_paint_version"] = list(rec_paint_state_version(session, room))
    except Exception:
        pass

    meta = session.get(PICK1_SNAPSHOT_KEY)
    if isinstance(meta, dict):
        meta = dict(meta)
        meta["ui_cache_key"] = ui_key_10
        meta["rebound_ts"] = time.time()
        session[PICK1_SNAPSHOT_KEY] = meta

    out["ok"] = bool(out["rebound"])
    return out


def ensure_ready_pick1_product_snapshot(
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full Pick-1 decision-support snapshot while the clock is still off.

    Idempotent: returns immediately when a matching ready snapshot already exists.
    """
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    out: dict[str, Any] = {
        "ok": False,
        "reason": "",
        "timings_ms": {},
        "room_id": "",
    }
    if not isinstance(live, dict):
        out["reason"] = "no_room"
        return out

    rid = str(live.get("draft_room_id") or "").strip()
    out["room_id"] = rid
    if pick1_snapshot_is_ready(session, live):
        out["ok"] = True
        out["reason"] = "already_ready"
        out["timings_ms"] = dict(session.get(PICK1_TIMINGS_KEY) or {})
        return out

    timings: dict[str, float] = {}
    t_all = time.perf_counter()

    def _mark(name: str, t0: float) -> None:
        timings[name] = round((time.perf_counter() - t0) * 1000.0, 1)

    # 1) Canonical projections / pool (existing Ready warm).
    t0 = time.perf_counter()
    try:
        from live_draft_ready_contract import ensure_ready_pool_warm, set_prestart_phase, PHASE_PREPARING

        set_prestart_phase(session, PHASE_PREPARING)
        warm = ensure_ready_pool_warm(session, live)
        out["pool_warm"] = {k: warm.get(k) for k in ("ok", "attached", "reason") if k in warm}
        live = session.get("live_draft_room") or live
        # Pool attach may replace the room blob — refresh identity before stamping snapshot.
        rid = str((live or {}).get("draft_room_id") or "").strip() or rid
        out["room_id"] = rid
    except Exception as exc:
        out["pool_warm_error"] = f"{type(exc).__name__}:{exc}"[:160]
        warm = {"ok": False}
    _mark("pool_warm", t0)
    if not warm.get("ok"):
        try:
            from live_draft_fast_solo_start import _pool_has_projection_player_grades

            if not _pool_has_projection_player_grades((live or {}).get("pool")):
                out["reason"] = "pool_not_ready"
                out["timings_ms"] = timings
                # Do not clear a previously-good Pick-1 snapshot / ready flag.
                if not pick1_snapshot_is_ready(session, live):
                    session[PICK1_READY_FLAG] = False
                _probe_write("pick1_prewarm.json", out)
                return out
        except Exception:
            out["reason"] = "pool_not_ready"
            out["timings_ms"] = timings
            if not pick1_snapshot_is_ready(session, live):
                session[PICK1_READY_FLAG] = False
            _probe_write("pick1_prewarm.json", out)
            return out

    # Ensure Pick-1 structural invariants while still not_started.
    try:
        from live_draft_ready_contract import enforce_prestart_invariants

        enforce_prestart_invariants(live, session)
        session["live_draft_room"] = live
    except Exception:
        pass

    team = _team_for_pick1(session, live)
    if team:
        session["room_your_team"] = team

    # 2) Available-player pool (cached).
    t0 = time.perf_counter()
    avail = None
    try:
        from live_draft_ui_cache import cached_live_draft_get_available

        avail = cached_live_draft_get_available(session, live)
        out["available_rows"] = int(len(avail)) if avail is not None else 0
    except Exception as exc:
        out["available_error"] = f"{type(exc).__name__}:{exc}"[:160]
        try:
            from live_draft_state import live_draft_get_available

            avail = live_draft_get_available(live)
            out["available_rows"] = int(len(avail)) if avail is not None else 0
        except Exception as exc2:
            out["available_error2"] = f"{type(exc2).__name__}:{exc2}"[:160]
    _mark("available_players", t0)

    # 3) Position needs + category outlook + decision cache.
    t0 = time.perf_counter()
    tracker: dict[str, Any] = {}
    outlook: dict[str, Any] = {}
    gaps: list[str] = []
    category_needs: list[str] = []
    category_levels: dict[str, str] = {}
    try:
        from live_draft_roster_tracker import build_team_roster_tracker, roster_df_for_team
        from draft_needs import infer_hitter_category_need_levels

        if team:
            tracker = build_team_roster_tracker(live, team)
            gaps = [str(g) for g in (tracker.get("gaps") or []) if str(g).strip()]
            roster_df = roster_df_for_team(live, team)
            levels = infer_hitter_category_need_levels(
                roster_df,
                avail,
                fantasy_format=str(
                    (live.get("config") or {}).get("fantasy_format")
                    or (live.get("config") or {}).get("scoring_type")
                    or "5x5 Roto"
                ),
            )
            category_needs = [str(d.get("label") or "") for d in levels if d.get("label")]
            category_levels = {
                str(d.get("label") or "").upper(): str(d.get("level") or "Low")
                for d in levels
                if d.get("label")
            }
            try:
                from live_draft_category_outlook import compute_category_outlook

                outlook = compute_category_outlook(
                    roster_df,
                    avail,
                    config=dict(live.get("config") or {}),
                    roster_gaps=list(gaps),
                )
            except Exception as exc:
                out["outlook_error"] = f"{type(exc).__name__}:{exc}"[:120]
            try:
                from live_draft_ui_cache import live_draft_ui_cache_key, store_live_draft_decision_context

                store_live_draft_decision_context(
                    session,
                    cache_key=live_draft_ui_cache_key(session, live, top_n=8, team=team or None),
                    tracker_team=team,
                    tracker=tracker,
                    outlook=outlook,
                    gaps=gaps,
                    category_needs=category_needs,
                )
            except Exception as exc:
                out["decision_store_error"] = f"{type(exc).__name__}:{exc}"[:120]
    except Exception as exc:
        out["needs_error"] = f"{type(exc).__name__}:{exc}"[:160]
    _mark("position_category_needs", t0)
    out["gaps"] = gaps[:12]
    out["category_needs"] = category_needs[:12]

    # Store paint-ready team-needs payload for Start (avoid recompute).
    session["_solo_pick1_team_needs"] = {
        "team": team,
        "tracker": tracker,
        "category_needs": category_needs,
        "category_levels": category_levels,
        "outlook": outlook,
        "room_id": rid,
        "pick_index": 0,
        "board_len": 0,
    }

    # 4) Recommendation scoring + interactive snapshot (+ autopick warm side-effect).
    # Use top_n=10 so keys match the active Live Draft heavy-paint path.
    t0 = time.perf_counter()
    rec_ok = False
    try:
        from live_draft_rec_live_paint import (
            ensure_prepared_rec_interactive,
            store_interactive_top_rec_snapshot,
            store_prepared_rec_interactive,
        )
        from live_draft_recommendations import live_draft_recommendations
        from live_draft_ui_cache import (
            REC_CACHE_KEY,
            filter_recommendation_tables_for_drafted,
            live_draft_ui_cache_key,
        )

        store_prepared_rec_interactive(
            session,
            room_id=rid,
            gaps=gaps,
            category_needs=category_needs,
            max_cards=6,
            multiplayer=False,
        )
        ensure_prepared_rec_interactive(session, live)
        top_n = 10
        top_rec, best_avail, pos_fit, value_sleep = live_draft_recommendations(
            live, top_n=top_n, team=team or None, session=session
        )
        top_rec, best_avail, pos_fit, value_sleep = filter_recommendation_tables_for_drafted(
            live, top_rec, best_avail, pos_fit, value_sleep
        )
        ui_key = live_draft_ui_cache_key(session, live, top_n=top_n, team=team or None)
        session[REC_CACHE_KEY] = {
            "key": ui_key,
            "top_rec": top_rec,
            "best_avail": best_avail,
            "pos_fit": pos_fit,
            "value_sleep": value_sleep,
            "prewarm_pick1": True,
            "rebuilt_ts": time.time(),
        }
        # Also alias under top_n=8 (early interactive path) so both keys hit.
        try:
            session["_solo_pick1_rec_key_aliases"] = {
                "top_n_10": ui_key,
                "top_n_8": live_draft_ui_cache_key(session, live, top_n=8, team=team or None),
            }
        except Exception:
            pass
        if top_rec is not None and not getattr(top_rec, "empty", True):
            store_interactive_top_rec_snapshot(
                session, top_rec, room_id=rid, room=live
            )
            rec_ok = True
        out["recs_ok"] = rec_ok
        out["top_rec_rows"] = int(len(top_rec)) if rec_ok else 0
    except Exception as exc:
        out["recs_error"] = f"{type(exc).__name__}:{exc}"[:160]
        rec_ok = False
    _mark("recommendation_scoring", t0)

    # 5) Why Recommended enrichment (best-effort).
    t0 = time.perf_counter()
    try:
        from live_draft_ui_cache import (
            REC_CACHE_KEY,
            enrich_live_draft_recommendations_with_why,
            live_draft_ui_cache_key,
        )

        entry = session.get(REC_CACHE_KEY)
        if isinstance(entry, dict) and entry.get("top_rec") is not None:
            tables = {
                "top_rec": entry.get("top_rec"),
                "best_avail": entry.get("best_avail"),
                "pos_fit": entry.get("pos_fit"),
                "value_sleep": entry.get("value_sleep"),
            }
            tables = {k: v for k, v in tables.items() if v is not None}
            ui_key = live_draft_ui_cache_key(session, live, top_n=8, team=team or None)
            enriched = enrich_live_draft_recommendations_with_why(session, ui_key, tables)
            if isinstance(enriched, dict):
                for name, frame in enriched.items():
                    if name in entry and frame is not None:
                        entry[name] = frame
                session[REC_CACHE_KEY] = entry
                try:
                    from live_draft_rec_live_paint import store_interactive_top_rec_snapshot

                    top = enriched.get("top_rec") or entry.get("top_rec")
                    store_interactive_top_rec_snapshot(
                        session, top, room_id=rid, room=live
                    )
                except Exception:
                    pass
                out["why_enriched"] = True
    except Exception as exc:
        out["why_error"] = f"{type(exc).__name__}:{exc}"[:160]
    _mark("why_enrichment", t0)

    # 6) Manual Draft option list (lightweight string list for Start paint).
    t0 = time.perf_counter()
    try:
        from draft_ui import _manual_draft_options_from_pool

        options = _manual_draft_options_from_pool(avail) if avail is not None else []
        session["_solo_pick1_manual_options"] = {
            "room_id": rid,
            "options": list(options)[:5000],
            "available_count": int(len(avail)) if avail is not None else 0,
        }
        out["manual_options"] = int(len(options))
    except Exception as exc:
        out["manual_error"] = f"{type(exc).__name__}:{exc}"[:160]
    _mark("manual_options", t0)

    # 7) Photo prefetch for top recommendation cards.
    t0 = time.perf_counter()
    photo_n = 0
    try:
        from live_draft_ui_cache import REC_CACHE_KEY

        entry = session.get(REC_CACHE_KEY) or {}
        top = entry.get("top_rec") if isinstance(entry, dict) else None
        if top is not None and not getattr(top, "empty", True):
            get_player_photo_info = None
            try:
                from player_photos import get_player_photo_info as _gppi

                get_player_photo_info = _gppi
            except ImportError:
                pass
            if callable(get_player_photo_info):
                for _, row in top.head(6).iterrows():
                    try:
                        get_player_photo_info(row=row, use_api=True)
                        photo_n += 1
                    except Exception:
                        continue
        out["photos_prefetched"] = photo_n
    except Exception as exc:
        out["photo_error"] = f"{type(exc).__name__}:{exc}"[:120]
    _mark("photos", t0)

    # 8) Explicit Auto Pick warm plan.
    t0 = time.perf_counter()
    try:
        from live_draft_autopick import schedule_autopick_warm_plan

        schedule_autopick_warm_plan(live)
        out["autopick_warm"] = True
    except Exception as exc:
        out["autopick_error"] = f"{type(exc).__name__}:{exc}"[:120]
    _mark("autopick_warm", t0)

    rankings_ok = bool(rec_ok)

    timings["total"] = round((time.perf_counter() - t_all) * 1000.0, 1)
    session[PICK1_TIMINGS_KEY] = timings

    ok = bool(rankings_ok and out.get("available_rows", 0) > 0)
    out["ok"] = ok
    out["reason"] = "ready" if ok else "incomplete"
    out["timings_ms"] = timings
    out["ui_cache_key"] = None
    try:
        from live_draft_ui_cache import live_draft_ui_cache_key

        out["ui_cache_key"] = live_draft_ui_cache_key(session, live, top_n=8, team=team or None)
    except Exception:
        pass

    session[PICK1_SNAPSHOT_KEY] = {
        "ok": ok,
        "room_id": rid,
        "team": team,
        "ts": time.time(),
        "reason": out["reason"],
        "available_rows": out.get("available_rows"),
        "recs_ok": bool(rec_ok),
        "gaps": gaps[:12],
        "category_needs": category_needs[:12],
        "photos_prefetched": photo_n,
        "ui_cache_key": out.get("ui_cache_key"),
        "timings_ms": timings,
    }
    session[PICK1_READY_FLAG] = bool(ok)
    if ok:
        try:
            from live_draft_ready_contract import PHASE_READY, set_prestart_phase

            set_prestart_phase(session, PHASE_READY)
        except Exception:
            pass
        try:
            from live_draft_fast_solo_start import clear_defer_heavy_first_paint

            clear_defer_heavy_first_paint(session)
        except Exception:
            session.pop("_live_draft_defer_heavy_first_paint", None)
            session.pop("_live_draft_defer_heavy_loading", None)

    _probe_write("pick1_prewarm.json", out)
    return out
