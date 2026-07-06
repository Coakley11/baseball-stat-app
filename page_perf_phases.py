"""Phase-level performance instrumentation — developer mode only."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

_PERF_NS_KEY = "_page_perf_ns"
_CACHE_AUDIT_KEY = "_page_perf_cache_audit"
_CACHE_AUDIT_MAX = 32


def _session(session: dict[str, Any] | None) -> dict[str, Any]:
    if session is not None:
        return session
    import streamlit as st

    return st.session_state


def dev_perf_enabled(session: dict[str, Any] | None = None) -> bool:
    ss = _session(session)
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        import streamlit as st

        return bool(developer_mode_checkbox_enabled(st=st))
    except ImportError:
        pass
    try:
        from page_perf import _dev_mode

        return bool(_dev_mode(ss))
    except ImportError:
        return False


def _ensure_ns(session: dict[str, Any]) -> dict[str, Any]:
    ns = session.get(_PERF_NS_KEY)
    if not isinstance(ns, dict):
        ns = {"page": "", "timings": {}, "started_at": time.perf_counter()}
        session[_PERF_NS_KEY] = ns
    if not isinstance(ns.get("timings"), dict):
        ns["timings"] = {}
    return ns


def record_perf_phase(session: dict[str, Any], phase: str, elapsed_sec: float) -> None:
    if not dev_perf_enabled(session):
        return
    ns = _ensure_ns(session)
    timings = dict(ns.get("timings") or {})
    label = str(phase or "").strip()
    if not label:
        return
    prev = float(timings.get(label) or 0.0)
    timings[label] = round(prev + float(elapsed_sec), 4)
    ns["timings"] = timings
    session[_PERF_NS_KEY] = ns


def record_cache_event(session: dict[str, Any], label: str, *, hit: bool) -> None:
    if not dev_perf_enabled(session):
        return
    audit = session.get(_CACHE_AUDIT_KEY)
    if not isinstance(audit, list):
        audit = []
    audit.append({"label": str(label), "hit": bool(hit)})
    session[_CACHE_AUDIT_KEY] = audit[-_CACHE_AUDIT_MAX:]


@contextmanager
def session_perf_phase(session: dict[str, Any], phase: str) -> Iterator[None]:
    if not dev_perf_enabled(session):
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record_perf_phase(session, phase, time.perf_counter() - t0)


def top_slow_phases(session: dict[str, Any], *, limit: int = 3) -> list[tuple[str, float]]:
    ns = session.get(_PERF_NS_KEY) if isinstance(session.get(_PERF_NS_KEY), dict) else {}
    timings = dict(ns.get("timings") or {})
    skip = {"page_render_total"}
    ranked = [
        (name, float(sec))
        for name, sec in timings.items()
        if name not in skip
    ]
    ranked.sort(key=lambda kv: kv[1], reverse=True)
    return ranked[: max(1, int(limit))]


def cache_audit_summary(session: dict[str, Any]) -> dict[str, dict[str, int]]:
    audit = session.get(_CACHE_AUDIT_KEY)
    if not isinstance(audit, list):
        return {}
    out: dict[str, dict[str, int]] = {}
    for row in audit:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        if not label:
            continue
        bucket = out.setdefault(label, {"hit": 0, "miss": 0})
        if row.get("hit"):
            bucket["hit"] += 1
        else:
            bucket["miss"] += 1
    return out


def render_perf_report(st: Any, session: dict[str, Any]) -> None:
    """Developer sidebar: phase breakdown, top slow paths, cache audit."""
    if not dev_perf_enabled(session):
        return
    ns = session.get(_PERF_NS_KEY)
    if not isinstance(ns, dict):
        return
    timings = dict(ns.get("timings") or {})
    with st.sidebar.expander("Page performance", expanded=False):
        st.text(f"page: {ns.get('page', '')}")
        page_total = float(timings.get("page_render_total") or 0.0)
        if page_total > 0:
            st.text(f"Page render time: {page_total:.3f}s")
        data_build = float(timings.get("data_build") or 0.0)
        if data_build > 0:
            st.text(f"Data build time: {data_build:.3f}s")
        for label in ("cloud_hydration", "cloud_read", "cloud_write"):
            if label in timings:
                title = label.replace("_", " ").title()
                st.text(f"{title}: {float(timings[label]):.3f}s")
        audit = cache_audit_summary(session)
        if audit:
            st.markdown("**Cache hit rate**")
            for label, counts in sorted(audit.items()):
                hits = int(counts.get("hit") or 0)
                misses = int(counts.get("miss") or 0)
                total = hits + misses
                pct = (100.0 * hits / total) if total else 0.0
                st.text(f"{label}: {pct:.0f}% ({hits}/{total})")
        top = top_slow_phases(session, limit=10)
        if top:
            st.markdown("**Top 10 slowest functions**")
            for i, (name, sec) in enumerate(top, start=1):
                st.text(f"{i}. {name}: {sec:.3f}s")
        try:
            from live_draft_perf import render_live_draft_perf_section, summarize_live_draft_phases

            ld_top = summarize_live_draft_phases(session, limit=10)
            if ld_top:
                st.markdown("**Live Draft — top phases**")
                for i, (name, sec) in enumerate(ld_top, start=1):
                    st.text(f"{i}. {name}: {sec:.3f}s")
            try:
                from live_draft_perf import summarize_setup_phases

                setup_top = summarize_setup_phases(session, limit=12)
                if setup_top:
                    st.markdown("**Live Draft setup — top phases**")
                    for i, (name, ms) in enumerate(setup_top, start=1):
                        st.text(f"{i}. {name}: {ms:.1f}ms")
            except ImportError:
                pass
            render_live_draft_perf_section(st, session)
        except ImportError:
            pass
        st.markdown("**All phases**")
        for phase, sec in sorted(timings.items(), key=lambda kv: kv[1], reverse=True):
            st.text(f"{phase}: {sec:.3f}s")
        save_diag = session.get("_draft_library_save_diag")
        if isinstance(save_diag, dict) and save_diag.get("save_request_received"):
            st.markdown("**Last save trace**")
            st.text(f"source: {save_diag.get('save_source') or '—'}")
            st.text(f"draft_id: {save_diag.get('draft_id') or '—'}")
            st.text(
                f"counts: {save_diag.get('draft_archive_count_before')} → {save_diag.get('draft_archive_count_after')}"
            )
            st.text(
                f"cloud/disk: {save_diag.get('cloud_write_success')}/{save_diag.get('disk_write_success')} "
                f"readback: {save_diag.get('draft_in_cloud')}/{save_diag.get('draft_in_disk')}"
            )
