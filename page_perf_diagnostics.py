"""Lightweight page render timing for developer mode."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator


def _perf_ns() -> dict[str, Any]:
    return dict(__import__("streamlit").session_state.get("_page_perf_ns") or {})


def _set_perf_ns(ns: dict[str, Any]) -> None:
    import streamlit as st

    st.session_state["_page_perf_ns"] = ns


def mark_page_perf(phase: str, elapsed_sec: float) -> None:
    import streamlit as st

    try:
        from page_perf_phases import record_perf_phase

        record_perf_phase(st.session_state, phase, elapsed_sec)
        return
    except ImportError:
        pass
    ns = _perf_ns()
    timings = dict(ns.get("timings") or {})
    timings[str(phase)] = round(float(elapsed_sec), 4)
    ns["timings"] = timings
    _set_perf_ns(ns)
    st.session_state["_page_perf_last_phase"] = phase


@contextmanager
def page_perf_phase(phase: str) -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        mark_page_perf(phase, time.perf_counter() - t0)


def start_page_perf_run(active_page: str) -> None:
    import streamlit as st

    st.session_state["_page_perf_ns"] = {
        "page": str(active_page or ""),
        "timings": {},
        "started_at": time.perf_counter(),
    }
    st.session_state.pop("_page_perf_cache_audit", None)


def finish_page_perf_run() -> None:
    import streamlit as st

    ns = _perf_ns()
    started = float(ns.get("started_at") or 0.0)
    if started:
        mark_page_perf("page_render_total", time.perf_counter() - started)


def render_page_perf_diagnostics(st: Any) -> None:
    try:
        from page_perf_phases import render_perf_report

        import streamlit as _st

        render_perf_report(st, _st.session_state)
    except ImportError:
        pass
