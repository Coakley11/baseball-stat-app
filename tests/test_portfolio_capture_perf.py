"""Portfolio capture performance helpers."""

from __future__ import annotations

import portfolio_polish as pp


class _FakeSt:
    def __init__(self):
        self.session_state = {}


def test_capture_perf_helpers():
    st = _FakeSt()
    st.session_state["portfolio_demo_mode"] = True
    assert pp.is_capture_mode(st)
    assert pp.skip_heavy_work(st)
    assert pp.skip_api_refresh(st)
    assert pp.skip_background_persistence(st)
