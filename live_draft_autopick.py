"""Pure live draft auto-pick selection — no Streamlit app imports."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd

from live_draft_pick_engine import live_draft_make_pick
from live_draft_pick_scoring import (
    live_draft_target_counts,
    score_available_for_rule,
)
from live_draft_state import live_draft_get_available
from live_draft_timer_logic import live_draft_current_slot

# Session keys for prepared Auto Pick (same engine, computed before deadline).
SOLO_AUTO_PICK_PLAN_KEY = "_solo_auto_pick_plan"
AUTOPICK_WARM_KEY = "_live_draft_autopick_warm"
WARM_CANDIDATE_LIMIT = 10
_PROFILE_PATH = Path(__file__).resolve().parent / "data" / "tb_probe" / "solo_autopick_profile.jsonl"
# Process-local backup — Streamlit session_state can drop large plan payloads
# across fragment boundaries; expire still needs the prepared candidates.
_PROCESS_WARM_PLANS: dict[str, dict[str, Any]] = {}
# Schedule state by plan-key string: not_scheduled | warming | ready | invalidated
_PROCESS_WARM_SCHEDULE: dict[str, str] = {}
_PROCESS_WARM_SCHEDULE_META: dict[str, dict[str, Any]] = {}
WARM_WORKER_TIMEOUT_S = 20.0
_WARM_BUILD_LOCK = None  # lazy threading.Lock
_WARM_BUILD_IN_FLIGHT = False
_WARM_WORKER_LAUNCHES = 0
_WARM_WORKER_ACTIVE = 0
# Cap warm scoring input so background GIL work cannot starve the 0.5s timer fragment.
WARM_AVAILABLE_ROW_CAP = 120
# Keep at most one warm plan entry per room bucket (current pick only).
WARM_PLAN_CACHE_MAX_ROOMS = 4
# Slim candidate fields — never retain full scored DataFrame rows.
_WARM_CANDIDATE_KEEP_KEYS = (
    "playerID",
    "player_id",
    "mlbam_id",
    "fullName",
    "Player",
    "Primary Position",
    "primary_pos",
    "Eligible Positions",
    "eligible_positions",
    "Decision Score",
    "decision_score",
    "Expected Fantasy Value",
    "Draft Fit Score",
    "Positional Fit",
    "Player Grade",
    "Model Rank",
    "Fantasy Edge",
)


def _warm_build_lock():
    global _WARM_BUILD_LOCK
    if _WARM_BUILD_LOCK is None:
        import threading

        _WARM_BUILD_LOCK = threading.Lock()
    return _WARM_BUILD_LOCK


def _trim_available_for_warm(available: Any) -> Any:
    """Smallest useful subset for top-10 warm plan — avoid full-pool GIL storms."""
    if available is None or getattr(available, "empty", True):
        return available
    try:
        df = available
        if not isinstance(df, pd.DataFrame):
            return available
        if len(df) <= WARM_AVAILABLE_ROW_CAP:
            return df
        for col in (
            "Player Grade",
            "player_grade",
            "Model Rank",
            "model_rank",
            "Fantasy Edge",
            "fantasy_edge",
            "Rank",
            "rank",
        ):
            if col in df.columns:
                try:
                    ranked = pd.to_numeric(df[col], errors="coerce")
                    # Model Rank: lower is better; grades/edge: higher is better.
                    ascending = "rank" in col.lower()
                    order = ranked.fillna(1e18 if ascending else -1e18)
                    return df.assign(_warm_sort=order).sort_values(
                        "_warm_sort", ascending=ascending
                    ).drop(columns=["_warm_sort"]).head(WARM_AVAILABLE_ROW_CAP)
                except Exception:
                    continue
        return df.head(WARM_AVAILABLE_ROW_CAP)
    except Exception:
        return available


def _process_plan_bucket(room: dict[str, Any]) -> str:
    return str(
        room.get("draft_room_id")
        or room.get("draft_id")
        or room.get("id")
        or "solo"
    ).strip() or "solo"


def _board_size(room: dict[str, Any]) -> int:
    board = room.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def _total_expected_picks(room: dict[str, Any]) -> int:
    """Prefer config teams×rounds — never trust a truncated pick_order alone."""
    try:
        from live_draft_safe_mode import total_expected_picks

        return int(total_expected_picks(room) or 0)
    except ImportError:
        pass
    pick_order = room.get("pick_order") or []
    teams = room.get("teams") or []
    cfg = dict(room.get("config") or {})
    rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
    if teams and rounds:
        return len(teams) * rounds
    return len(pick_order) if isinstance(pick_order, list) else 0


def _candidate_names(scored: pd.DataFrame, limit: int = 8) -> list[str]:
    col = "fullName" if "fullName" in scored.columns else "Player"
    if col not in scored.columns:
        return []
    return [str(x) for x in scored.head(limit)[col].astype(str).tolist() if str(x).strip()]


def _note_autopick_profile(payload: dict[str, Any]) -> None:
    try:
        _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _PROFILE_PATH.open("a", encoding="utf-8") as fh:
            import json

            fh.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
    except Exception:
        pass


def _plan_key(room: dict[str, Any], team: str, rule_key: str) -> tuple[Any, ...]:
    return (
        str(room.get("draft_room_id") or room.get("draft_id") or ""),
        int(room.get("current_pick_index") or 0),
        str(team or "").strip(),
        int(_board_size(room)),
        str(rule_key or "").strip().lower(),
    )


def _drafted_keys(room: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    board = room.get("draft_board") or []
    if not isinstance(board, list):
        return keys
    for row in board:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("playerID") or row.get("player_id") or "").strip().lower()
        name = str(row.get("fullName") or row.get("Player") or "").strip().lower()
        if pid:
            keys.add(f"id:{pid}")
        if name:
            keys.add(f"name:{name}")
    return keys


def _row_to_candidate(row: Any, *, slim: bool = True) -> dict[str, Any]:
    if isinstance(row, dict):
        raw = dict(row)
    else:
        try:
            raw = row.to_dict()
        except Exception:
            return {}
    out: dict[str, Any] = {}
    keys = _WARM_CANDIDATE_KEEP_KEYS if slim else tuple(raw.keys())
    for key in keys:
        if key not in raw:
            continue
        v = raw.get(key)
        if v is None:
            out[str(key)] = None
            continue
        try:
            if hasattr(v, "item"):
                v = v.item()
        except Exception:
            pass
        if isinstance(v, (str, int, float, bool)):
            out[str(key)] = v
        else:
            out[str(key)] = str(v)
    return out


def _candidates_from_scored(scored: pd.DataFrame, limit: int = WARM_CANDIDATE_LIMIT) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if scored is None or getattr(scored, "empty", True):
        return out
    for _, row in scored.head(int(limit)).iterrows():
        cand = _row_to_candidate(row, slim=True)
        if cand:
            out.append(cand)
    return out


def _plan_key_token(key: tuple[Any, ...] | list[Any] | None) -> str:
    if not key:
        return ""
    return "|".join(str(x) for x in key)


def _warm_cache_stats() -> dict[str, Any]:
    entries = []
    total_cands = 0
    for bucket, plan in list(_PROCESS_WARM_PLANS.items()):
        n = int(len(plan.get("candidates") or []))
        total_cands += n
        entries.append(
            {
                "bucket": bucket,
                "key": list(plan.get("key") or []),
                "candidates": n,
                "state": _PROCESS_WARM_SCHEDULE.get(_plan_key_token(plan.get("key")), "unknown"),
                "warmed_at": plan.get("warmed_at"),
            }
        )
    return {
        "rooms": len(_PROCESS_WARM_PLANS),
        "schedule_keys": len(_PROCESS_WARM_SCHEDULE),
        "total_candidates": total_cands,
        "worker_launches": int(_WARM_WORKER_LAUNCHES),
        "worker_active": int(_WARM_WORKER_ACTIVE),
        "entries": entries,
    }


def _store_process_warm_plan(room: dict[str, Any], plan: dict[str, Any]) -> None:
    """Store slim warm plan; bound cache to a few room buckets; drop large frames."""
    bucket = _process_plan_bucket(room)
    key = plan.get("key")
    token = _plan_key_token(key if isinstance(key, (tuple, list)) else None)
    slim = {
        "key": key,
        "candidates": list(plan.get("candidates") or []),
        "gaps": list(plan.get("gaps") or []),
        "rule_key": str(plan.get("rule_key") or "").strip().lower(),
        "warmed_at": plan.get("warmed_at") or time.time(),
        "candidate_count": int(plan.get("candidate_count") or len(plan.get("candidates") or [])),
        "source": plan.get("source") or "build_autopick_warm_plan",
    }
    # Never retain a scored DataFrame reference.
    slim.pop("scored", None)
    _PROCESS_WARM_PLANS[bucket] = slim
    if token:
        _PROCESS_WARM_SCHEDULE[token] = "ready"
        # Invalidate other schedule keys for this room.
        rid = str((key or ("",))[0] if key else "")
        for other, state in list(_PROCESS_WARM_SCHEDULE.items()):
            if other != token and other.startswith(f"{rid}|") and state != "warming":
                _PROCESS_WARM_SCHEDULE[other] = "invalidated"
    # Bound room entries.
    while len(_PROCESS_WARM_PLANS) > WARM_PLAN_CACHE_MAX_ROOMS:
        oldest = min(
            _PROCESS_WARM_PLANS.items(),
            key=lambda kv: float((kv[1] or {}).get("warmed_at") or 0.0),
        )[0]
        if oldest == bucket:
            break
        old = _PROCESS_WARM_PLANS.pop(oldest, None)
        if isinstance(old, dict):
            ot = _plan_key_token(old.get("key") if isinstance(old.get("key"), (tuple, list)) else None)
            if ot:
                _PROCESS_WARM_SCHEDULE.pop(ot, None)
    try:
        _note_autopick_profile(
            {
                "event": "warm_cache_store",
                "ts": time.time(),
                "stats": _warm_cache_stats(),
            }
        )
    except Exception:
        pass


def invalidate_autopick_warm_for_room(room: dict[str, Any] | None) -> None:
    if not isinstance(room, dict):
        return
    bucket = _process_plan_bucket(room)
    old = _PROCESS_WARM_PLANS.pop(bucket, None)
    if isinstance(old, dict):
        ot = _plan_key_token(old.get("key") if isinstance(old.get("key"), (tuple, list)) else None)
        if ot:
            _PROCESS_WARM_SCHEDULE[ot] = "invalidated"


def _candidate_still_valid(
    cand: dict[str, Any],
    *,
    drafted: set[str],
    gaps: list[str] | None = None,
) -> bool:
    pid = str(cand.get("playerID") or cand.get("player_id") or "").strip().lower()
    name = str(cand.get("fullName") or cand.get("Player") or "").strip().lower()
    if pid and f"id:{pid}" in drafted:
        return False
    if name and f"name:{name}" in drafted:
        return False
    if not pid and not name:
        return False
    if gaps:
        pos = str(cand.get("Primary Position") or cand.get("Pos") or "").strip().upper()
        elig = str(cand.get("Eligible Positions") or cand.get("Positions") or "").upper()
        gap_u = [str(g).strip().upper() for g in gaps if str(g).strip()]
        if gap_u and pos and pos not in gap_u and not any(g in elig for g in gap_u):
            if "Primary Position" in cand or "Eligible Positions" in cand:
                return False
    return True


def select_warm_autopick_candidate(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team: str,
    rule_key: str,
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    """Cheap validation over prepared candidates. No rescore."""
    meta: dict[str, Any] = {"warm_hit": False, "fallback": False, "checked": 0}
    plan = session.get(SOLO_AUTO_PICK_PLAN_KEY) or session.get(AUTOPICK_WARM_KEY)
    if not isinstance(plan, dict) or not plan.get("candidates"):
        plan = _PROCESS_WARM_PLANS.get(_process_plan_bucket(room))
    if not isinstance(plan, dict):
        meta["no_plan"] = True
        return None, [], meta
    expect = _plan_key(room, team, rule_key)
    got = tuple(plan.get("key") or ())
    if got != expect:
        meta["stale_key"] = True
        meta["expect_key"] = list(expect)
        meta["got_key"] = list(got)
        return None, [], meta
    gaps = list(plan.get("gaps") or [])
    candidates = list(plan.get("candidates") or [])
    if not candidates and isinstance(plan.get("scored"), pd.DataFrame):
        candidates = _candidates_from_scored(plan["scored"])
    drafted = _drafted_keys(room)
    for cand in candidates:
        meta["checked"] = int(meta["checked"]) + 1
        if not isinstance(cand, dict):
            continue
        if _candidate_still_valid(cand, drafted=drafted, gaps=gaps):
            meta["warm_hit"] = True
            meta["selected_rank"] = int(meta["checked"])
            return cand, gaps, meta
    meta["all_invalid"] = True
    return None, gaps, meta


def build_autopick_warm_plan(
    room: dict[str, Any],
    *,
    team: str | None = None,
) -> dict[str, Any] | None:
    """Build a warm Auto Pick plan for the current on-clock pick (no session)."""
    t0 = time.perf_counter()
    stages: dict[str, float] = {}
    try:
        from live_draft_timer_logic import resolve_live_draft_on_clock_slot

        slot = resolve_live_draft_on_clock_slot(room)
    except ImportError:
        slot = live_draft_current_slot(room)
    if not isinstance(slot, dict):
        return None
    on_clock = str(slot.get("Team") or "").strip()
    target_team = str(team or on_clock or "").strip() or on_clock
    if not target_team or str(room.get("status") or "") != "in_progress":
        return None

    t1 = time.perf_counter()
    available = live_draft_get_available(room)
    available = _trim_available_for_warm(available)
    stages["available_ms"] = round((time.perf_counter() - t1) * 1000.0, 2)
    stages["available_rows"] = int(len(available)) if available is not None else 0
    if available is None or getattr(available, "empty", True):
        return None

    t2 = time.perf_counter()
    roster_df = pd.DataFrame(room.get("rosters", {}).get(target_team, []))
    stages["roster_ms"] = round((time.perf_counter() - t2) * 1000.0, 2)
    cfg = dict(room.get("config", {}))
    cfg["current_pick"] = int(slot.get("Pick", 1))
    cfg["room"] = room
    rule_key = str(cfg.get("auto_pick_rule", "balanced recommendation") or "balanced recommendation")
    target_counts = live_draft_target_counts(cfg)

    t3 = time.perf_counter()
    scored, gaps = score_available_for_rule(
        available, roster_df, rule_key, target_counts, config=cfg
    )
    stages["score_available_for_rule_ms"] = round((time.perf_counter() - t3) * 1000.0, 2)
    if isinstance(cfg.get("_score_stages_ms"), dict):
        stages.update({f"score_{k}": v for k, v in cfg["_score_stages_ms"].items()})
    if scored is None or getattr(scored, "empty", True):
        return None

    candidates = _candidates_from_scored(scored, WARM_CANDIDATE_LIMIT)
    # Release large scored frame immediately after extracting top-N slim dicts.
    try:
        del scored
    except Exception:
        pass
    key = _plan_key(room, target_team, rule_key)
    plan = {
        "key": key,
        "candidates": candidates,
        "gaps": list(gaps or []),
        "rule_key": str(rule_key).strip().lower(),
        "team": target_team,
        "pick_index": int(room.get("current_pick_index") or 0),
        "board_len": int(_board_size(room)),
        "warmed_at": time.time(),
        "warm_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "stages": stages,
        "candidate_count": len(candidates),
    }
    _store_process_warm_plan(room, plan)
    _note_autopick_profile(
        {
            "event": "warm_plan_built",
            "ts": time.time(),
            "key": list(key),
            "warm_ms": plan["warm_ms"],
            "stages": stages,
            "candidate_count": len(candidates),
            "cache": _warm_cache_stats(),
            "top": str(
                (candidates[0].get("fullName") or candidates[0].get("Player") or "")
                if candidates
                else ""
            ),
        }
    )
    return plan


def schedule_autopick_warm_plan(room: dict[str, Any]) -> None:
    """Build the next-pick warm plan off the timer fragment thread.

    At most one worker per plan key. Delayed start so the fragment can paint first.
    """
    import threading

    global _WARM_BUILD_IN_FLIGHT, _WARM_WORKER_LAUNCHES, _WARM_WORKER_ACTIVE

    if not isinstance(room, dict):
        return
    try:
        from live_draft_timer_logic import resolve_live_draft_on_clock_slot

        slot = resolve_live_draft_on_clock_slot(room)
    except ImportError:
        slot = live_draft_current_slot(room)
    if not isinstance(slot, dict):
        return
    team = str(slot.get("Team") or "").strip()
    cfg = dict(room.get("config") or {})
    rule_key = str(cfg.get("auto_pick_rule", "balanced recommendation") or "balanced recommendation")
    key = _plan_key(room, team, rule_key)
    token = _plan_key_token(key)
    state = _PROCESS_WARM_SCHEDULE.get(token, "not_scheduled")
    # Stale warming guard — if a worker hung, allow one retry after timeout.
    if state == "warming":
        started_at = float((_PROCESS_WARM_SCHEDULE_META.get(token) or {}).get("started_at") or 0.0)
        if started_at and (time.time() - started_at) > WARM_WORKER_TIMEOUT_S:
            _PROCESS_WARM_SCHEDULE[token] = "not_scheduled"
            state = "not_scheduled"
            try:
                _note_autopick_profile(
                    {
                        "event": "warm_plan_warming_timeout",
                        "ts": time.time(),
                        "key": list(key),
                        "age_s": round(time.time() - started_at, 2),
                    }
                )
            except Exception:
                pass
        else:
            state = "warming"
    if state in ("warming", "ready"):
        try:
            _note_autopick_profile(
                {
                    "event": "warm_plan_skip_state",
                    "ts": time.time(),
                    "state": state,
                    "key": list(key),
                    "cache": _warm_cache_stats(),
                }
            )
        except Exception:
            pass
        return

    lock = _warm_build_lock()
    if lock.locked() or _WARM_BUILD_IN_FLIGHT:
        try:
            _note_autopick_profile(
                {
                    "event": "warm_plan_skip_inflight",
                    "ts": time.time(),
                    "pick_index": int(room.get("current_pick_index") or 0),
                    "key": list(key),
                }
            )
        except Exception:
            pass
        return

    # Do NOT deepcopy the room — live pools are multi‑MB DataFrames.
    # Snapshot the plan identity; worker aborts if the on-clock pick advanced.
    room_ref = room
    scheduled_pick = int(room.get("current_pick_index") or 0)
    scheduled_board = _board_size(room)
    _PROCESS_WARM_SCHEDULE[token] = "warming"
    _PROCESS_WARM_SCHEDULE_META[token] = {"started_at": time.time(), "pick_index": scheduled_pick}

    def _worker() -> None:
        global _WARM_BUILD_IN_FLIGHT, _WARM_WORKER_ACTIVE
        # Brief yield so the fragment paint that scheduled us can flush to the browser.
        time.sleep(0.05)
        if int(room_ref.get("current_pick_index") or 0) != scheduled_pick:
            if _PROCESS_WARM_SCHEDULE.get(token) == "warming":
                _PROCESS_WARM_SCHEDULE[token] = "invalidated"
            return
        if _board_size(room_ref) != scheduled_board:
            if _PROCESS_WARM_SCHEDULE.get(token) == "warming":
                _PROCESS_WARM_SCHEDULE[token] = "invalidated"
            return
        if not lock.acquire(blocking=False):
            if _PROCESS_WARM_SCHEDULE.get(token) == "warming":
                _PROCESS_WARM_SCHEDULE[token] = "not_scheduled"
            return
        _WARM_BUILD_IN_FLIGHT = True
        _WARM_WORKER_ACTIVE += 1
        try:
            _note_autopick_profile(
                {
                    "event": "warm_worker_start",
                    "ts": time.time(),
                    "key": list(key),
                    "thread": threading.current_thread().name,
                    "active_workers": _WARM_WORKER_ACTIVE,
                    "cache": _warm_cache_stats(),
                }
            )
            if int(room_ref.get("current_pick_index") or 0) != scheduled_pick:
                if _PROCESS_WARM_SCHEDULE.get(token) == "warming":
                    _PROCESS_WARM_SCHEDULE[token] = "invalidated"
                return
            build_autopick_warm_plan(room_ref)
            _note_autopick_profile(
                {
                    "event": "warm_worker_end",
                    "ts": time.time(),
                    "key": list(key),
                    "cache": _warm_cache_stats(),
                }
            )
        except Exception as exc:
            if _PROCESS_WARM_SCHEDULE.get(token) == "warming":
                _PROCESS_WARM_SCHEDULE[token] = "not_scheduled"
            try:
                _note_autopick_profile(
                    {
                        "event": "warm_plan_bg_err",
                        "ts": time.time(),
                        "err": f"{type(exc).__name__}: {exc}"[:160],
                        "key": list(key),
                    }
                )
            except Exception:
                pass
        finally:
            _WARM_WORKER_ACTIVE = max(0, int(_WARM_WORKER_ACTIVE) - 1)
            _WARM_BUILD_IN_FLIGHT = False
            try:
                lock.release()
            except Exception:
                pass

    _WARM_WORKER_LAUNCHES += 1
    threading.Thread(target=_worker, name=f"solo-autopick-warm-{token[:24]}", daemon=True).start()
    try:
        _note_autopick_profile(
            {
                "event": "warm_worker_launch",
                "ts": time.time(),
                "key": list(key),
                "launches": _WARM_WORKER_LAUNCHES,
                "cache": _warm_cache_stats(),
            }
        )
    except Exception:
        pass


def store_autopick_warm_cache(
    session: dict[str, Any] | None,
    room: dict[str, Any],
    *,
    team: str | None = None,
) -> bool:
    """Pre-score Auto Pick candidates for the current on-clock pick.

    Called while the pick clock is live (and after pick transitions) so the
    deadline path only validates + commits.
    """
    if session is None or not isinstance(room, dict):
        return False
    plan = build_autopick_warm_plan(room, team=team)
    if not isinstance(plan, dict):
        return False
    session[AUTOPICK_WARM_KEY] = plan
    session[SOLO_AUTO_PICK_PLAN_KEY] = plan
    session["_solo_warm_plan_for_pick"] = int(room.get("current_pick_index") or 0)
    return True


def ensure_solo_auto_pick_plan(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    force: bool = False,
) -> bool:
    """Build/refresh warm plan for the current on-clock pick if missing/stale."""
    if not isinstance(session, dict) or not isinstance(room, dict):
        return False
    if str(room.get("status") or "") != "in_progress":
        return False
    try:
        from live_draft_timer_logic import resolve_live_draft_on_clock_slot

        slot = resolve_live_draft_on_clock_slot(room)
    except ImportError:
        slot = live_draft_current_slot(room)
    if not isinstance(slot, dict):
        return False
    team = str(slot.get("Team") or "").strip()
    rule_key = str((room.get("config") or {}).get("auto_pick_rule") or "balanced recommendation")
    expect = _plan_key(room, team, rule_key)
    plan = session.get(SOLO_AUTO_PICK_PLAN_KEY) or session.get(AUTOPICK_WARM_KEY)
    if (
        not force
        and isinstance(plan, dict)
        and tuple(plan.get("key") or ()) == expect
        and (
            plan.get("candidates")
            or (isinstance(plan.get("scored"), pd.DataFrame) and not plan["scored"].empty)
        )
    ):
        return True
    return store_autopick_warm_cache(session, room, team=team)


def live_draft_auto_pick(
    room: dict[str, Any],
    session: dict[str, Any] | None = None,
    *,
    persist: bool = True,
    finalize: bool = True,
) -> tuple[bool, str]:
    """Select and apply auto-pick using the Draft Setup Auto-Pick Rule on the legal pool.

    Prefers a prepared warm plan (same scoring engine, computed earlier). Deadline
    path should validate + commit, not rescore.
    """
    profile: dict[str, Any] = {"event": "auto_pick", "ts": time.time(), "stages_ms": {}}
    t_all = time.perf_counter()

    def _stage(name: str, t_start: float) -> None:
        profile["stages_ms"][name] = round((time.perf_counter() - t_start) * 1000.0, 2)

    try:
        from live_draft_timer_logic import resolve_live_draft_on_clock_slot

        t0 = time.perf_counter()
        slot = resolve_live_draft_on_clock_slot(room)
        _stage("resolve_slot", t0)
    except ImportError:
        t0 = time.perf_counter()
        slot = live_draft_current_slot(room)
        _stage("resolve_slot", t0)
    if slot is None:
        total = _total_expected_picks(room)
        board = _board_size(room)
        if total > 0 and board < total:
            return False, "Draft pick index out of sync — use Manual Draft to recover."
        return False, "Draft is already complete."

    if str(room.get("status") or "") == "paused":
        return False, "Draft is paused — resume before auto-picking."

    claim_key = ""
    if session is not None:
        try:
            from live_draft_canonical_snapshot import (
                auto_pick_idempotency_key,
                clear_stale_auto_pick_idempotency,
                idempotency_key_committed,
            )

            t0 = time.perf_counter()
            clear_stale_auto_pick_idempotency(session, room)
            claim_key = auto_pick_idempotency_key(room)
            last = str(session.get("_live_draft_last_auto_pick_idempotency_key") or "")
            inflight = str(session.get("_live_draft_in_flight_auto_pick_key") or "")
            room_last = str(room.get("_last_auto_pick_idempotency_key") or "")
            if claim_key and claim_key == inflight:
                if idempotency_key_committed(room, claim_key):
                    return True, "Auto-pick already in progress for this pick."
            if claim_key and (
                (claim_key == last and idempotency_key_committed(room, claim_key))
                or (claim_key == room_last and idempotency_key_committed(room, claim_key))
            ):
                return True, "Auto-pick already applied for this pick."
            if claim_key and (claim_key == last or claim_key == room_last):
                session.pop("_live_draft_last_auto_pick_idempotency_key", None)
                room.pop("_last_auto_pick_idempotency_key", None)
            if claim_key:
                session["_live_draft_in_flight_auto_pick_key"] = claim_key
            _stage("idempotency", t0)
        except ImportError:
            claim_key = ""

    team = slot["Team"]
    cfg = dict(room.get("config", {}))
    cfg["current_pick"] = int(slot.get("Pick", 1))
    cfg["room"] = room
    configured_rule = str(cfg.get("auto_pick_rule", "balanced recommendation") or "balanced recommendation")
    board_before = _board_size(room)
    idx_before = int(room.get("current_pick_index") or 0)

    rec_scored = pd.DataFrame()
    gaps: list[str] = []
    skip_reason = ""
    chosen_dict: dict[str, Any] | None = None
    warm_meta: dict[str, Any] = {}
    available = None
    roster_df = None
    target_counts = None

    # Critical path: validate prepared plan BEFORE pool/scoring work.
    if session is not None:
        session["_live_draft_autopick_used_rec_cache"] = False
        t0 = time.perf_counter()
        chosen_dict, gaps, warm_meta = select_warm_autopick_candidate(
            session, room, team=str(team), rule_key=configured_rule
        )
        _stage("warm_validate", t0)
        profile["warm"] = warm_meta
        if chosen_dict is not None:
            session["_live_draft_autopick_used_warm_cache"] = True
            try:
                rec_scored = pd.DataFrame([chosen_dict])
            except Exception:
                rec_scored = pd.DataFrame()
        else:
            try:
                warm = session.get(AUTOPICK_WARM_KEY)
                if isinstance(warm, dict):
                    warm_key = _plan_key(room, str(team), configured_rule)
                    if tuple(warm.get("key") or ()) == warm_key and isinstance(
                        warm.get("scored"), pd.DataFrame
                    ):
                        cand = warm["scored"]
                        if not cand.empty:
                            drafted = _drafted_keys(room)
                            gaps = list(warm.get("gaps") or [])
                            for _, row in cand.head(WARM_CANDIDATE_LIMIT).iterrows():
                                d = _row_to_candidate(row)
                                if _candidate_still_valid(d, drafted=drafted, gaps=gaps):
                                    chosen_dict = d
                                    rec_scored = cand
                                    session["_live_draft_autopick_used_warm_cache"] = True
                                    warm_meta = {"warm_hit": True, "legacy_scored_df": True}
                                    profile["warm"] = warm_meta
                                    break
            except Exception:
                pass

    rule_key = str(configured_rule or "balanced recommendation").strip() or "balanced recommendation"
    if chosen_dict is None:
        # Expire must stay on the fragment thread — never full-score here.
        # Full ``score_available_for_rule`` pegs the GIL for 0.5–2s+ and starves
        # the 0.5s Solo clock (browser presentation skips 1→3 / 1→4).
        # Still hard-filter to THIS team's open starter needs before rank sort.
        t0 = time.perf_counter()
        available = live_draft_get_available(room)
        roster_df = pd.DataFrame(room.get("rosters", {}).get(team, []) or [])
        try:
            from live_draft_roster_slots import (
                filter_candidates_to_team_open_positions,
                get_remaining_position_needs,
            )

            gaps = list(get_remaining_position_needs(roster_df, cfg) or [])
            available = filter_candidates_to_team_open_positions(
                available, roster_df, config=cfg, room=room
            )
        except ImportError:
            gaps = []
        available = _trim_available_for_warm(available)
        _stage("available_players", t0)
        if available is None or getattr(available, "empty", True):
            total = _total_expected_picks(room)
            board = _board_size(room)
            if total > 0 and board >= total:
                room["status"] = "complete"
            if session is not None:
                session.pop("_live_draft_in_flight_auto_pick_key", None)
            profile["ok"] = False
            profile["total_ms"] = round((time.perf_counter() - t_all) * 1000.0, 2)
            _note_autopick_profile(profile)
            return False, "No players remain in the pool."

        t0 = time.perf_counter()
        drafted = _drafted_keys(room)
        fast = available
        rule_l = rule_key.lower()
        sort_cols: list[tuple[str, bool]] = []
        if "market" in rule_l:
            sort_cols = [("Market Rank", True), ("Model Rank", True), ("Rank", True)]
        elif "model" in rule_l:
            sort_cols = [("Model Rank", True), ("Market Rank", True), ("Rank", True)]
        elif "projected" in rule_l or "fantasy value" in rule_l:
            sort_cols = [
                ("Expected Fantasy Value", False),
                ("Player Grade", False),
                ("Model Rank", True),
            ]
        else:
            sort_cols = [
                ("Model Rank", True),
                ("Market Rank", True),
                ("Player Grade", False),
                ("Rank", True),
            ]
        try:
            for col, ascending in sort_cols:
                if col not in fast.columns:
                    continue
                ranked = pd.to_numeric(fast[col], errors="coerce")
                fill = 1e18 if ascending else -1e18
                fast = (
                    fast.assign(_expire_sort=ranked.fillna(fill))
                    .sort_values("_expire_sort", ascending=ascending)
                    .drop(columns=["_expire_sort"])
                )
                break
        except Exception:
            pass
        for _, row in fast.head(max(WARM_CANDIDATE_LIMIT * 5, 40)).iterrows():
            d = _row_to_candidate(row)
            if _candidate_still_valid(d, drafted=drafted, gaps=gaps):
                chosen_dict = d
                try:
                    rec_scored = pd.DataFrame([d])
                except Exception:
                    rec_scored = pd.DataFrame()
                break
        _stage("fast_rank_fallback", t0)
        if session is not None:
            session["_live_draft_autopick_used_warm_cache"] = False
            profile["warm_miss_fast_rank"] = True
            profile["warm_miss_full_score"] = False
            profile["fast_rank_gaps"] = list(gaps or [])
        # Kick a background warm for the *next* pick — never score on this thread.
        try:
            schedule_autopick_warm_plan(room)
        except Exception:
            pass

    if not chosen_dict:
        if session is not None:
            session.pop("_live_draft_in_flight_auto_pick_key", None)
        profile["ok"] = False
        profile["total_ms"] = round((time.perf_counter() - t_all) * 1000.0, 2)
        _note_autopick_profile(profile)
        return False, "No eligible recommendation for auto-pick."

    top_rec_name = str(chosen_dict.get("fullName") or chosen_dict.get("Player") or "").strip()
    player_id = str(chosen_dict.get("playerID") or chosen_dict.get("player_id") or "").strip()

    from live_draft_pick_engine import build_structured_pick_verdict

    t0 = time.perf_counter()
    verdict = build_structured_pick_verdict(chosen_dict, pick_source="Auto Pick", gaps=gaps)
    _stage("verdict", t0)
    t0 = time.perf_counter()
    ok, msg = live_draft_make_pick(
        room,
        chosen_dict,
        verdict=verdict,
        pick_source="Auto Pick",
        snapshot=chosen_dict,
        session=session,
        enrich_pick_context=False,
    )
    _stage("pick_commit", t0)

    if session is not None:
        try:
            from live_draft_expired_pick import record_autopick_diagnostics

            record_autopick_diagnostics(
                session,
                auto_pick_candidate_list=(
                    _candidate_names(rec_scored)
                    if isinstance(rec_scored, pd.DataFrame)
                    else [top_rec_name]
                ),
                top_recommendation_player=top_rec_name,
                selected_auto_pick_player=top_rec_name if ok else None,
                selected_auto_pick_reason=verdict if ok else msg,
                auto_pick_rule_configured=configured_rule,
                top_recommendation_skipped_reason=skip_reason or None,
                configured_rule_would_pick=top_rec_name if ok else None,
                auto_pick_from_queue=False,
            )
        except ImportError:
            pass
        if ok and finalize:
            try:
                from live_draft_pick_commit import finalize_live_draft_pick_transition

                t0 = time.perf_counter()
                # Solo timer fragment: never block paint on disk persist. Commit
                # mutates in-memory room; persist asynchronously so the 0.5s
                # clock can flush every pick to the browser.
                solo_timer = bool(
                    session.get("_solo_server_timer_active")
                    or session.get("_live_draft_solo_early_timer_painted")
                )
                try:
                    from live_draft_solo_timer import is_solo_live_draft

                    solo_timer = solo_timer or bool(is_solo_live_draft(session, room))
                except Exception:
                    pass
                fin = finalize_live_draft_pick_transition(
                    session,
                    room,
                    source="Auto Pick",
                    player_id=player_id,
                    player_name=top_rec_name,
                    board_size_before=board_before,
                    idx_before=idx_before,
                    persist=not solo_timer,
                    fast_path=True,
                    request_immediate_paint=True,
                )
                _stage("finalize_persist", t0)
                if solo_timer and fin.ok and persist:
                    try:
                        import threading

                        room_ref = room
                        sess_ref = session
                        b_before = board_before
                        i_before = idx_before
                        is_complete = str(room.get("status") or "").strip() == "complete"

                        def _persist_bg() -> None:
                            try:
                                from pathlib import Path
                                import json as _json

                                probe = (
                                    Path(__file__).resolve().parent
                                    / "data"
                                    / "tb_probe"
                                    / "solo_persist_bg.jsonl"
                                )
                                probe.parent.mkdir(parents=True, exist_ok=True)
                                with probe.open("a", encoding="utf-8") as fh:
                                    fh.write(
                                        _json.dumps(
                                            {
                                                "ts": time.time(),
                                                "room_id": str(room_ref.get("draft_room_id") or ""),
                                                "status": str(room_ref.get("status") or ""),
                                                "board": len(room_ref.get("draft_board") or []),
                                                "idx": int(room_ref.get("current_pick_index") or 0),
                                            }
                                        )
                                        + "\n"
                                    )
                            except Exception:
                                pass
                            try:
                                from live_draft_state import (
                                    room_to_persist_dict,
                                    write_canonical_live_draft_state,
                                )

                                write_canonical_live_draft_state(
                                    sess_ref,
                                    room_ref,
                                    reason="Auto Pick",
                                    local_edit=True,
                                )
                                blob = room_to_persist_dict(room_ref, compact_pool=True)
                                rid = str(room_ref.get("draft_room_id") or "").strip()
                                if rid and blob:
                                    from pathlib import Path
                                    import json as _json

                                    rooms_dir = Path(__file__).resolve().parent / "data" / "draft_rooms"
                                    rooms_dir.mkdir(parents=True, exist_ok=True)
                                    (rooms_dir / f"{rid}.json").write_text(
                                        _json.dumps(blob, indent=2, default=str),
                                        encoding="utf-8",
                                    )
                                # Patch workspace disk so refresh restore sees the board.
                                try:
                                    from suite_user_persistence import save_user_state
                                    from pathlib import Path
                                    import json as _json

                                    ws_id = str(
                                        sess_ref.get("_suite_active_workspace_id")
                                        or sess_ref.get("active_workspace_id")
                                        or "daniel"
                                    )
                                    ws_path = (
                                        Path(__file__).resolve().parent
                                        / "data"
                                        / "workspaces"
                                        / ws_id
                                        / "baseball_user_state.json"
                                    )
                                    payload: dict = {}
                                    if ws_path.exists():
                                        try:
                                            payload = _json.loads(
                                                ws_path.read_text(encoding="utf-8")
                                            )
                                        except Exception:
                                            payload = {}
                                    state = payload.get("state") if isinstance(payload, dict) else None
                                    if not isinstance(state, dict):
                                        state = {}
                                        payload = {"state": state}
                                    state["live_draft_room"] = blob
                                    state["live_draft_state"] = blob
                                    pfs = state.get("page_filter_state")
                                    if not isinstance(pfs, dict):
                                        pfs = {}
                                        state["page_filter_state"] = pfs
                                    block = pfs.get("Live Draft Room")
                                    if not isinstance(block, dict):
                                        block = {}
                                        pfs["Live Draft Room"] = block
                                    block["live_draft_room"] = blob
                                    block["live_draft_state"] = blob
                                    try:
                                        save_user_state("baseball", state, workspace_id=ws_id)
                                    except Exception:
                                        pass
                                    ws_path.parent.mkdir(parents=True, exist_ok=True)
                                    ws_path.write_text(
                                        _json.dumps(payload, indent=2, default=str),
                                        encoding="utf-8",
                                    )
                                except Exception as disk_exc:
                                    sess_ref["_solo_persist_disk_err"] = (
                                        f"{type(disk_exc).__name__}: {disk_exc}"
                                    )[:200]
                            except Exception as exc:
                                try:
                                    sess_ref["_solo_persist_bg_err"] = (
                                        f"{type(exc).__name__}: {exc}"
                                    )[:200]
                                except Exception:
                                    pass

                        if is_complete:
                            # Final pick: durable write must finish before browser refresh.
                            # Mid-draft paints stay async so the fragment clock is not starved.
                            _persist_bg()
                            profile["stages_ms"]["persist_deferred"] = 0
                            profile["stages_ms"]["persist_sync_complete"] = 1
                        else:
                            threading.Thread(
                                target=_persist_bg,
                                name="solo-autopick-persist",
                                daemon=True,
                            ).start()
                            profile["stages_ms"]["persist_deferred"] = 1
                    except Exception:
                        pass
                if not fin.ok:
                    try:
                        from live_draft_canonical_snapshot import pick_commit_confirmed

                        if not pick_commit_confirmed(
                            room, pick_index_before=idx_before, board_size_before=board_before
                        ):
                            session.pop("_live_draft_in_flight_auto_pick_key", None)
                            profile["ok"] = False
                            profile["total_ms"] = round((time.perf_counter() - t_all) * 1000.0, 2)
                            _note_autopick_profile(profile)
                            return False, fin.message or msg
                    except ImportError:
                        session.pop("_live_draft_in_flight_auto_pick_key", None)
                        return False, fin.message or msg
            except Exception as exc:
                profile["finalize_err"] = f"{type(exc).__name__}: {exc}"[:120]
        session.pop("_live_draft_in_flight_auto_pick_key", None)
        if ok:
            session["_solo_warm_next_plan_pending"] = True
            session.pop(SOLO_AUTO_PICK_PLAN_KEY, None)
            session.pop(AUTOPICK_WARM_KEY, None)
            try:
                _PROCESS_WARM_PLANS.pop(_process_plan_bucket(room), None)
            except Exception:
                pass

    if ok:
        board_after = _board_size(room)
        idx_after = int(room.get("current_pick_index") or 0)
        complete = str(room.get("status") or "") == "complete"
        if not complete and (board_after <= board_before or idx_after <= idx_before):
            if session is not None:
                try:
                    from live_draft_canonical_snapshot import clear_stale_auto_pick_idempotency

                    clear_stale_auto_pick_idempotency(session, room)
                except ImportError:
                    pass
                session.pop("_live_draft_in_flight_auto_pick_key", None)
            profile["ok"] = False
            profile["total_ms"] = round((time.perf_counter() - t_all) * 1000.0, 2)
            _note_autopick_profile(profile)
            return False, "Auto-pick did not advance the draft board."

    profile["ok"] = bool(ok)
    profile["player"] = top_rec_name
    profile["pick_index_before"] = idx_before
    profile["total_ms"] = round((time.perf_counter() - t_all) * 1000.0, 2)
    _note_autopick_profile(profile)
    if session is not None:
        session["_live_draft_last_autopick_profile"] = profile
        # Also stash on room so fragment txn can read even if session proxy lags.
        room["_last_autopick_profile"] = {
            "warm": profile.get("warm"),
            "stages_ms": profile.get("stages_ms"),
            "total_ms": profile.get("total_ms"),
            "warm_miss_full_score": profile.get("warm_miss_full_score"),
            "ok": profile.get("ok"),
            "player": top_rec_name,
        }
    return ok, msg


def _normalize_player_key(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def _try_queue_auto_pick(
    room: dict[str, Any],
    session: dict[str, Any],
    available: pd.DataFrame,
    team: str,
    *,
    board_before: int = 0,
    idx_before: int = 0,
    persist: bool = True,
    finalize: bool = True,
) -> tuple[bool, str]:
    """Draft the first still-available queued player for the on-clock team.

    Uses only the on-clock participant's private queue scoped by (room, user).
    """
    your_team = ""
    try:
        from draft_room_participant_state import active_participant_team

        your_team = str(active_participant_team(session) or "").strip()
    except ImportError:
        pass
    if not your_team:
        your_team = str(
            room.get("your_team")
            or (room.get("config") or {}).get("your_team")
            or session.get("draft_room_participant_team")
            or session.get("room_your_team")
            or session.get("your_team")
            or ""
        ).strip()
    if your_team and your_team.lower() != str(team or "").strip().lower():
        return False, ""

    queue_raw: list[Any] = []
    try:
        from draft_room_context import resolve_shared_room_code
        from draft_room_participant_state import participant_workflow_slot, resolve_participant_id

        code = str(resolve_shared_room_code(session) or "").strip().upper()
        if code:
            slot = participant_workflow_slot(session, code)
            wf = dict(slot.get("workflow") or {})
            queue_raw = list(wf.get("queue") or [])
            session["_draft_queue_autopick_scope"] = {
                "room_code": code,
                "user_id": resolve_participant_id(session),
                "team": your_team,
                "source": "participant_slot",
            }
    except ImportError:
        pass
    if not queue_raw:
        queue_raw = session.get("draft_queue") or []
        if isinstance(session.get("_draft_queue_autopick_scope"), dict):
            session["_draft_queue_autopick_scope"]["source"] = "session_fallback"
    if not isinstance(queue_raw, list) or not queue_raw:
        return False, ""

    name_col = "fullName" if "fullName" in available.columns else ("Player" if "Player" in available.columns else None)
    if not name_col:
        return False, ""

    available_by_name: dict[str, dict[str, Any]] = {}
    for _, row in available.iterrows():
        key = _normalize_player_key(str(row.get(name_col) or ""))
        if key and key not in available_by_name:
            available_by_name[key] = row.to_dict()

    chosen_dict: dict[str, Any] | None = None
    chosen_name = ""
    for entry in queue_raw:
        if isinstance(entry, dict):
            name = str(entry.get("fullName") or entry.get("Player") or entry.get("name") or "").strip()
        else:
            name = str(entry or "").strip()
        if not name:
            continue
        hit = available_by_name.get(_normalize_player_key(name))
        if hit:
            chosen_dict = hit
            chosen_name = name
            break
    if not chosen_dict:
        return False, ""

    from live_draft_pick_engine import build_structured_pick_verdict

    verdict = build_structured_pick_verdict(chosen_dict, pick_source="Queue Auto Pick", gaps=[])
    player_id = str(chosen_dict.get("playerID") or chosen_dict.get("player_id") or "").strip()
    ok, msg = live_draft_make_pick(
        room,
        chosen_dict,
        verdict=verdict,
        pick_source="Queue Auto Pick",
        snapshot=chosen_dict,
        session=session,
    )
    if ok:
        try:
            from live_draft_expired_pick import record_autopick_diagnostics

            record_autopick_diagnostics(
                session,
                selected_auto_pick_player=chosen_name,
                selected_auto_pick_reason=verdict,
                auto_pick_from_queue=True,
                top_recommendation_player=chosen_name,
            )
        except ImportError:
            pass
        if finalize:
            try:
                from live_draft_pick_commit import finalize_live_draft_pick_transition

                finalize_live_draft_pick_transition(
                    session,
                    room,
                    source="Queue Auto Pick",
                    player_id=player_id,
                    player_name=chosen_name,
                    board_size_before=board_before,
                    idx_before=idx_before,
                    persist=persist,
                    fast_path=True,
                    request_immediate_paint=True,
                )
            except Exception:
                try:
                    from draft_state import remove_drafted_player_from_active_queues

                    remove_drafted_player_from_active_queues(session, chosen_name)
                except Exception:
                    q = [
                        x
                        for x in (session.get("draft_queue") or [])
                        if _normalize_player_key(str(x.get("fullName") if isinstance(x, dict) else x))
                        != _normalize_player_key(chosen_name)
                    ]
                    session["draft_queue"] = q
        return True, msg or f"Queue auto-picked {chosen_name}."
    return False, msg or ""
