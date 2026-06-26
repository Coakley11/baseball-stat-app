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


def finish_page_perf_run() -> None:
    import streamlit as st

    ns = _perf_ns()
    started = float(ns.get("started_at") or 0.0)
    if started:
        mark_page_perf("page_render_total", time.perf_counter() - started)


def render_page_perf_diagnostics(st: Any) -> None:
    ns = _perf_ns()
    if not ns:
        return
    timings = dict(ns.get("timings") or {})
    if not timings:
        return
    with st.sidebar.expander("Page performance", expanded=False):
        st.text(f"page: {ns.get('page', '')}")
        for phase, sec in sorted(timings.items(), key=lambda kv: kv[1], reverse=True):
            st.text(f"{phase}: {sec:.3f}s")
