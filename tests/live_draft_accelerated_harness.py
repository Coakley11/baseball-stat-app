"""Deterministic Solo Live Draft harness — accelerated clock, surface agreement, latency."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from unittest.mock import patch

import pandas as pd

from draft_actions import draft_action_context, draft_status_summary
from live_draft_canonical_snapshot import (
    begin_live_draft_paint,
    get_live_draft_paint_snapshot,
    invalidate_live_draft_paint,
)
from live_draft_pick_commit import PickCommitResult, commit_live_draft_pick
from live_draft_solo_timer import expire_current_pick_and_advance, solo_clock_expired
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining
from live_draft_ui_cache import REC_CACHE_KEY


def as_plain_session(session: Any) -> dict[str, Any]:
    """Copy Streamlit AppTest session_state into a plain dict for harness helpers."""
    if isinstance(session, dict):
        return session
    try:
        from streamlit.runtime.state.safe_session_state import SafeSessionState

        if isinstance(session, SafeSessionState):
            inner = session._state
            raw = getattr(inner, "_new_session_state", None)
            if isinstance(raw, dict) and raw:
                return dict(raw)
    except Exception:
        pass
    out: dict[str, Any] = {}
    try:
        for key in session:
            out[key] = session[key]
        if out:
            return out
    except Exception:
        pass
    try:
        return {k: session[k] for k in session.keys()}  # type: ignore[attr-defined]
    except Exception:
        return {}


def build_four_team_eight_round_room(*, timer_seconds: int = 5, pool_size: int = 400) -> dict:
    """4 teams × 8 picks = 32 picks — deterministic Solo room."""
    teams = ["Team A", "Team B", "Team C", "Team D"]
    picks_per_team = 8
    pick_order = []
    pick_n = 1
    for rnd in range(1, picks_per_team + 1):
        seq = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in seq:
            pick_order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    pool = pd.DataFrame(
        [
            {
                "playerID": f"p{i:03d}",
                "fullName": f"Player {i:03d}",
                "Primary Position": ["C", "1B", "2B", "3B", "SS", "OF", "DH", "UTIL"][i % 8],
                "Expected Fantasy Value": float(500 - i),
                "Decision Score": float(100.0 - (i % 50)),
                "Draft Fit Score": float(1.0 + (i % 10) * 0.05),
                "Positional Fit": float(0.8 + (i % 5) * 0.04),
            }
            for i in range(1, pool_size + 1)
        ]
    )
    room = {
        "draft_room_id": "ACCEL-4x8",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in teams},
        "revision": 1,
        "meta": {"sync": {"revision": 1}},
        "config": {
            "num_teams": 4,
            "picks_per_team": picks_per_team,
            "rounds": picks_per_team,
            "timer_seconds": timer_seconds,
            "teams": teams,
            "your_team": "Team A",
            "user_team": "Team A",
            "draft_setup_mode": "solo",
            "auto_pick_rule": "balanced recommendation",
            "queue_auto_pick": False,
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 0, "P": 0, "BN": 0},
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    return room


def seed_session(room: dict, *, queue: list | None = None) -> dict[str, Any]:
    session: dict[str, Any] = {
        "live_draft_setup_mode": "solo",
        "live_draft_room": room,
        "draft_queue": list(queue or []),
        "active_page": "Live Draft Room",
        REC_CACHE_KEY: {
            "key": ("accel",),
            "top_rec": room["pool"].head(24).copy(),
            "best_avail": room["pool"].head(24).copy(),
            "pos_fit": room["pool"].head(16).copy(),
            "value_sleep": room["pool"].head(16).copy(),
        },
    }
    begin_live_draft_paint(session, room, state_source="harness_start")
    return session


def force_timer_expired(room: dict) -> None:
    room["timer_deadline"] = time.time() - 0.05


@contextmanager
def fast_autopick_scoring() -> Iterator[None]:
    def _fast_score(available, roster_df, rule_key, target_counts, config=None):
        scored = available.copy()
        if "Decision Score" not in scored.columns:
            scored["Decision Score"] = range(len(scored), 0, -1)
        return scored.sort_values("Decision Score", ascending=False), []

    with patch("live_draft_autopick.score_available_for_rule", side_effect=_fast_score):
        yield


@contextmanager
def noop_persist() -> Iterator[None]:
    with patch(
        "live_draft_pick_commit.persist_applied_pick",
        return_value=PickCommitResult(
            ok=True,
            message="ok",
            error="",
            commit_path="harness_noop",
            board_size_before=0,
            board_size_after=0,
            current_pick_index_before=0,
            current_pick_index_after=0,
        ),
    ), patch("baseball_persistent_state.force_save_baseball_state"):
        yield


@contextmanager
def accelerated_draft_patches() -> Iterator[None]:
    """Patches that keep harness runs fast without hiding pick invariants."""
    with fast_autopick_scoring(), noop_persist():
        yield


def assert_surfaces_agree(session: dict[str, Any], room: dict[str, Any], *, label: str = "") -> dict[str, Any]:
    """Sidebar, paint, and draft_action_context must match on pick/team/index."""
    session = as_plain_session(session)
    paint = get_live_draft_paint_snapshot(session)
    summary = draft_status_summary(session)
    ctx = draft_action_context(session)
    prefix = f"{label}: " if label else ""
    team_paint = str(paint.get("team_on_clock") or "")
    team_summary = str(summary.get("on_clock_team") or "")
    team_ctx = str(ctx.get("on_clock_team") or "")
    pick_paint = paint.get("current_pick")
    pick_summary = summary.get("pick")
    pick_ctx = ctx.get("current_pick")
    idx_paint = paint.get("current_pick_index")
    idx_ctx = ctx.get("current_pick_index")
    if str(room.get("status") or "") == "complete":
        return paint
    if team_paint and team_summary:
        assert team_paint == team_summary, f"{prefix}team paint={team_paint} summary={team_summary}"
    if team_paint and team_ctx:
        assert team_paint == team_ctx, f"{prefix}team paint={team_paint} ctx={team_ctx}"
    if pick_paint is not None and pick_summary is not None:
        assert int(pick_paint) == int(pick_summary), f"{prefix}pick paint={pick_paint} summary={pick_summary}"
    if pick_paint is not None and pick_ctx is not None:
        assert int(pick_paint) == int(pick_ctx), f"{prefix}pick paint={pick_paint} ctx={pick_ctx}"
    if idx_paint is not None and idx_ctx is not None:
        assert int(idx_paint) == int(idx_ctx), f"{prefix}idx paint={idx_paint} ctx={idx_ctx}"
    token = paint.get("paint_token")
    if token and ctx.get("paint_token"):
        assert token == ctx.get("paint_token"), f"{prefix}paint_token mismatch"
    return paint


def assert_no_timer_frozen(room: dict[str, Any]) -> None:
    if str(room.get("status") or "") != "in_progress":
        return
    assert not solo_clock_expired(room), "timer stuck at zero after transition"
    assert live_draft_seconds_remaining(room) > 0, "timer did not restart"


def assert_drafted_removed_from_queue_and_recs(
    session: dict[str, Any], *, player_id: str, player_name: str
) -> None:
    rec = session.get(REC_CACHE_KEY) or {}
    for key in ("top_rec", "best_avail", "pos_fit", "value_sleep"):
        table = rec.get(key)
        if isinstance(table, pd.DataFrame) and not table.empty and "playerID" in table.columns:
            assert player_id not in set(table["playerID"].astype(str)), f"{player_name} still in {key}"
    names = {
        str(x.get("fullName") if isinstance(x, dict) else x).strip().lower()
        for x in (session.get("draft_queue") or [])
    }
    assert player_name.lower() not in names, f"{player_name} still in queue"


def simulate_navigation_away_and_back(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Leave Live Draft and return — paint must rebuild from room."""
    session["active_page"] = "Draft Assistant"
    invalidate_live_draft_paint(session)
    session["active_page"] = "Live Draft Room"
    begin_live_draft_paint(session, room, state_source="harness_return")


@dataclass
class LatencySample:
    action: str
    elapsed_ms: float


@dataclass
class DraftRunMetrics:
    picks: int = 0
    duplicates: int = 0
    batch_jumps: int = 0
    frozen_zero: int = 0
    surface_mismatches: int = 0
    latencies: list[LatencySample] = field(default_factory=list)

    def record_latency(self, action: str, t0: float) -> None:
        self.latencies.append(LatencySample(action, (time.perf_counter() - t0) * 1000.0))


def expire_one_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    metrics: DraftRunMetrics,
) -> dict[str, Any]:
    board_before = len(room.get("draft_board") or [])
    idx_before = int(room.get("current_pick_index") or 0)
    force_timer_expired(room)
    t0 = time.perf_counter()
    with accelerated_draft_patches():
        result = expire_current_pick_and_advance(room, session=session)
    if metrics.picks >= 2:
        metrics.record_latency("expire", t0)
    assert result.ok, result
    board_after = len(room.get("draft_board") or [])
    assert board_after == board_before + 1, f"batch jump: {board_before} -> {board_after}"
    if board_after - board_before > 1:
        metrics.batch_jumps += 1
    idx_after = int(room.get("current_pick_index") or 0)
    assert idx_after == idx_before + 1 or str(room.get("status") or "") == "complete"
    invalidate_live_draft_paint(session)
    begin_live_draft_paint(session, room, state_source="harness_after_expire")
    try:
        assert_surfaces_agree(session, room, label=f"after_expire_{board_after}")
    except AssertionError:
        metrics.surface_mismatches += 1
        raise
    if str(room.get("status") or "") == "in_progress":
        try:
            assert_no_timer_frozen(room)
        except AssertionError:
            metrics.frozen_zero += 1
            raise
    last = (room.get("draft_board") or [])[-1]
    pid = str(last.get("playerID") or "")
    pname = str(last.get("fullName") or "")
    assert_drafted_removed_from_queue_and_recs(session, player_id=pid, player_name=pname)
    metrics.picks += 1
    return last


def manual_one_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    metrics: DraftRunMetrics,
) -> dict[str, Any]:
    from live_draft_state import live_draft_get_available

    available = live_draft_get_available(room)
    assert not available.empty
    row = available.iloc[0].to_dict()
    board_before = len(room.get("draft_board") or [])
    t0 = time.perf_counter()
    with accelerated_draft_patches():
        result = commit_live_draft_pick(session, room, row, source="harness_manual", fast_path=True)
    metrics.record_latency("manual_pick", t0)
    assert result.ok, result
    assert len(room.get("draft_board") or []) == board_before + 1
    invalidate_live_draft_paint(session)
    begin_live_draft_paint(session, room, state_source="harness_after_manual")
    assert_surfaces_agree(session, room, label="after_manual")
    assert_no_timer_frozen(room)
    metrics.picks += 1
    return row


def auto_pick_now(
    session: dict[str, Any],
    room: dict[str, Any],
    metrics: DraftRunMetrics,
) -> None:
    from live_draft_autopick import live_draft_auto_pick

    board_before = len(room.get("draft_board") or [])
    t0 = time.perf_counter()
    with accelerated_draft_patches():
        ok, msg = live_draft_auto_pick(room, session)
    metrics.record_latency("auto_pick_now", t0)
    assert ok, msg
    assert len(room.get("draft_board") or []) == board_before + 1
    invalidate_live_draft_paint(session)
    begin_live_draft_paint(session, room, state_source="harness_after_auto_now")
    assert_surfaces_agree(session, room, label="after_auto_now")
    assert_no_timer_frozen(room)
    metrics.picks += 1


def _during_clock_ops(
    pick_cycle: int,
    session: dict[str, Any],
    room: dict[str, Any],
    metrics: DraftRunMetrics,
) -> None:
    """Queue/control operations while the countdown is active (before completing the pick)."""
    if str(room.get("status") or "") != "in_progress":
        return
    assert_surfaces_agree(session, room, label=f"cycle_{pick_cycle}_start")
    assert_no_timer_frozen(room)

    if pick_cycle == 7:
        t0 = time.perf_counter()
        session.setdefault("draft_queue", []).insert(0, f"Player {50 + pick_cycle:03d}")
        metrics.record_latency("queue_add", t0)
    elif pick_cycle == 9:
        t0 = time.perf_counter()
        q = list(session.get("draft_queue") or [])
        if q:
            session["draft_queue"] = q[1:]
        metrics.record_latency("queue_remove", t0)
    elif pick_cycle == 11:
        from live_draft_timer_logic import live_draft_pause_timer, live_draft_resume_timer

        t0 = time.perf_counter()
        live_draft_pause_timer(room)
        invalidate_live_draft_paint(session)
        begin_live_draft_paint(session, room, state_source="harness_paused")
        assert_surfaces_agree(session, room, label="paused")
        left = int(room.get("paused_remaining_seconds") or 0)
        room["status"] = "in_progress"
        live_draft_resume_timer(room, left)
        invalidate_live_draft_paint(session)
        begin_live_draft_paint(session, room, state_source="harness_resumed")
        assert_surfaces_agree(session, room, label="resumed")
        metrics.record_latency("pause_resume", t0)
    elif pick_cycle == 12:
        from live_draft_timer_logic import live_draft_reset_timer

        t0 = time.perf_counter()
        live_draft_reset_timer(room)
        invalidate_live_draft_paint(session)
        begin_live_draft_paint(session, room, state_source="harness_reset")
        assert_surfaces_agree(session, room, label="reset_timer")
        metrics.record_latency("reset_timer", t0)
    elif pick_cycle == 13:
        t0 = time.perf_counter()
        q = list(session.get("draft_queue") or [])
        if len(q) >= 2:
            q[0], q[1] = q[1], q[0]
            session["draft_queue"] = q
        metrics.record_latency("queue_reorder", t0)
    elif pick_cycle == 14:
        t0 = time.perf_counter()
        simulate_navigation_away_and_back(session, room)
        assert_surfaces_agree(session, room, label="nav_return")
        metrics.record_latency("nav_away_back", t0)


def run_accelerated_full_draft(*, repeat: int = 3) -> list[DraftRunMetrics]:
    """Run 32-pick draft with mixed operations; repeat for flake detection."""
    all_metrics: list[DraftRunMetrics] = []
    for _run in range(repeat):
        room = build_four_team_eight_round_room()
        queue = [f"Player {i:03d}" for i in range(10, 30)]
        session = seed_session(room, queue=queue)
        metrics = DraftRunMetrics()
        seen_ids: set[str] = set()

        for pick_cycle in range(1, 33):
            if str(room.get("status") or "") == "complete":
                break
            _during_clock_ops(pick_cycle, session, room, metrics)
            if pick_cycle == 6:
                last = manual_one_pick(session, room, metrics)
            elif pick_cycle in (8, 15, 22):
                auto_pick_now(session, room, metrics)
                last = (room.get("draft_board") or [])[-1]
            else:
                last = expire_one_pick(session, room, metrics)
            pid = str(last.get("playerID") or "")
            if pid in seen_ids:
                metrics.duplicates += 1
            seen_ids.add(pid)

        assert str(room.get("status") or "") == "complete"
        assert len(room.get("draft_board") or []) == 32
        assert len(seen_ids) == 32
        all_metrics.append(metrics)
    return all_metrics
