#!/usr/bin/env python3
"""Phase 1 queue latency baseline / after probe.

Measures engine-path queue add/remove with and without force_save simulation.

Run from baseball-stat-app root:
  python scripts/profile_live_draft_queue_phase1.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _force_save_cost_ms(iterations: int = 3) -> float:
    """Approximate old critical-path cost: build_baseball_disk_state only (no cloud)."""
    from baseball_persistent_state import build_baseball_disk_state

    st = MagicMock()
    st.session_state = {
        "draft_queue": ["Mike Trout"],
        "draft_state": {"queue": ["Mike Trout"], "watchlist_focus": [], "watchlist_favorites": []},
        "page_filter_state": {},
    }
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            build_baseball_disk_state(st)
        except Exception as exc:
            print(f"WARN build_baseball_disk_state failed: {exc}")
            return -1.0
        times.append((time.perf_counter() - t0) * 1000.0)
    return sum(times) / len(times)


def _queue_ops_ms(*, with_force_save: bool, ops: int = 20) -> tuple[float, float]:
    from draft_state import add_player_to_draft_queue, remove_player_from_draft_queue

    session: dict = {}
    names = [f"Probe Player {i}" for i in range(ops)]

    def _simulate_old_force_save() -> None:
        # Pre-Phase-1 call sites paid for full workspace serialization on every click.
        from baseball_persistent_state import build_baseball_disk_state

        st = MagicMock()
        st.session_state = session
        build_baseball_disk_state(st)

    def _run() -> float:
        t0 = time.perf_counter()
        for name in names:
            add_player_to_draft_queue(session, name)
            if with_force_save:
                _simulate_old_force_save()
        for name in names:
            remove_player_from_draft_queue(session, name)
            if with_force_save:
                _simulate_old_force_save()
        return (time.perf_counter() - t0) * 1000.0

    if with_force_save:
        total = _run()
    else:
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            total = _run()
            assert mock_save.call_count == 0
    per = total / (ops * 2)
    return total, per


def main() -> int:
    print("=== Live Draft Phase 1 queue latency probe ===")
    build_ms = _force_save_cost_ms()
    print(f"build_baseball_disk_state avg: {build_ms:.1f} ms (old path ingredient)")

    # Fewer ops for BEFORE — each op pays ~full workspace serialize.
    before_total, before_per = _queue_ops_ms(with_force_save=True, ops=2)
    print(
        f"BEFORE (2 add+remove with build_baseball_disk_state each): "
        f"total={before_total:.1f} ms  per_op={before_per:.1f} ms"
    )

    after_total, after_per = _queue_ops_ms(with_force_save=False, ops=20)
    print(
        f"AFTER  (20 add+remove, deferred persist only): "
        f"total={after_total:.1f} ms  per_op={after_per:.1f} ms"
    )

    target_ok = after_per < 50.0 and after_per < before_per
    print(f"Engine per-op vs 50ms smoke budget + faster than before: {'PASS' if target_ok else 'FAIL'}")
    print("Note: Streamlit full-page paint not included; Phase 6 isolates that.")
    return 0 if target_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
