"""
Supabase egress instrumentation — counts reads/writes and response sizes.

Hooked from ``suite_storage_supabase._request``. Summaries live in Streamlit
``session_state`` when available; otherwise an in-process fallback bucket.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

_SOURCE: ContextVar[str] = ContextVar("suite_egress_source", default="unknown")

_PROCESS_TOTALS: dict[str, Any] = {
    "reads": 0,
    "writes": 0,
    "bytes_in": 0,
    "bytes_out": 0,
    "by_table": defaultdict(lambda: {"reads": 0, "writes": 0, "bytes_in": 0}),
}


@dataclass
class EgressEvent:
    method: str
    table: str
    bytes_in: int
    bytes_out: int
    source: str
    cached: bool = False
    path: str = ""


@dataclass
class EgressRunSummary:
    reads: int = 0
    writes: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    by_table: dict[str, dict[str, int]] = field(default_factory=dict)
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    events: list[EgressEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "by_table": self.by_table,
            "by_source": self.by_source,
            "event_count": len(self.events),
        }


def _table_from_path(path: str) -> str:
    return str(path or "").split("/", 1)[0].strip() or path


def _session_bucket() -> EgressRunSummary | None:
    try:
        import streamlit as st  # noqa: WPS433

        raw = st.session_state.get("_suite_egress_summary")
        if isinstance(raw, EgressRunSummary):
            return raw
        summary = EgressRunSummary()
        st.session_state["_suite_egress_summary"] = summary
        return summary
    except Exception:
        return None


def set_egress_source(source: str) -> None:
    _SOURCE.set(str(source or "unknown").strip() or "unknown")


@contextmanager
def egress_source(source: str) -> Iterator[None]:
    token = _SOURCE.set(str(source or "unknown").strip() or "unknown")
    try:
        yield
    finally:
        _SOURCE.reset(token)


def record_egress(
    *,
    method: str,
    path: str,
    bytes_in: int,
    bytes_out: int = 0,
    cached: bool = False,
) -> None:
    table = _table_from_path(path)
    source = _SOURCE.get()
    event = EgressEvent(
        method=method.upper(),
        table=table,
        bytes_in=max(0, int(bytes_in)),
        bytes_out=max(0, int(bytes_out)),
        source=source,
        cached=cached,
        path=path,
    )
    summary = _session_bucket()
    if summary is not None:
        _apply_event(summary, event)
    _apply_process_event(event)


def _apply_event(summary: EgressRunSummary, event: EgressEvent) -> None:
    if len(summary.events) < 200:
        summary.events.append(event)
    row = summary.by_table.setdefault(
        event.table,
        {"reads": 0, "writes": 0, "bytes_in": 0, "bytes_out": 0},
    )
    src = summary.by_source.setdefault(
        event.source,
        {"reads": 0, "writes": 0, "bytes_in": 0},
    )
    if event.method == "GET":
        summary.reads += 0 if event.cached else 1
        row["reads"] += 0 if event.cached else 1
        src["reads"] += 0 if event.cached else 1
    else:
        summary.writes += 1
        row["writes"] += 1
        src["writes"] += 1
    if not event.cached:
        summary.bytes_in += event.bytes_in
        row["bytes_in"] += event.bytes_in
        src["bytes_in"] += event.bytes_in
    summary.bytes_out += event.bytes_out
    row["bytes_out"] += event.bytes_out


def _apply_process_event(event: EgressEvent) -> None:
    table = event.table
    bucket = _PROCESS_TOTALS["by_table"][table]
    if event.method == "GET":
        _PROCESS_TOTALS["reads"] += 0 if event.cached else 1
        bucket["reads"] += 0 if event.cached else 1
    else:
        _PROCESS_TOTALS["writes"] += 1
    if not event.cached:
        _PROCESS_TOTALS["bytes_in"] += event.bytes_in
        bucket["bytes_in"] += event.bytes_in


def get_run_egress_summary() -> dict[str, Any]:
    summary = _session_bucket()
    if summary is not None:
        return summary.to_dict()
    return {
        "reads": _PROCESS_TOTALS["reads"],
        "writes": _PROCESS_TOTALS["writes"],
        "bytes_in": _PROCESS_TOTALS["bytes_in"],
        "bytes_out": _PROCESS_TOTALS["bytes_out"],
        "by_table": dict(_PROCESS_TOTALS["by_table"]),
    }


def reset_run_egress_summary() -> None:
    try:
        import streamlit as st  # noqa: WPS433

        st.session_state["_suite_egress_summary"] = EgressRunSummary()
    except Exception:
        pass


def format_egress_summary_markdown(summary: dict[str, Any] | None = None) -> str:
    data = summary or get_run_egress_summary()
    lines = [
        f"**Supabase egress (this session run):** reads={data.get('reads', 0)}, "
        f"writes={data.get('writes', 0)}, "
        f"download≈{ _human_bytes(int(data.get('bytes_in') or 0))}",
    ]
    by_table = data.get("by_table") or {}
    if by_table:
        lines.append("")
        lines.append("| Table | Reads | Writes | Download |")
        lines.append("|-------|------:|-------:|---------:|")
        for table, row in sorted(by_table.items(), key=lambda kv: -(kv[1].get("bytes_in") or 0)):
            lines.append(
                f"| `{table}` | {row.get('reads', 0)} | {row.get('writes', 0)} | "
                f"{_human_bytes(int(row.get('bytes_in') or 0))} |"
            )
    by_source = data.get("by_source") or {}
    if by_source:
        lines.append("")
        lines.append("**By source:**")
        for source, row in sorted(by_source.items(), key=lambda kv: -(kv[1].get("bytes_in") or 0)):
            lines.append(
                f"- `{source}`: reads={row.get('reads', 0)}, "
                f"download≈{_human_bytes(int(row.get('bytes_in') or 0))}"
            )
    return "\n".join(lines)


def _human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def render_egress_sidebar_panel(st: Any) -> None:
    """Show egress counters when developer mode is on."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except Exception:
        return
    with st.sidebar.expander("Supabase egress (dev)", expanded=False):
        st.markdown(format_egress_summary_markdown())
        summary = _session_bucket()
        if summary and summary.events:
            st.caption("Recent fetches (newest last)")
            tail = summary.events[-12:]
            st.code(json.dumps([e.__dict__ for e in tail], indent=2), language="json")
