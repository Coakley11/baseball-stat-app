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
_KIND: ContextVar[str] = ContextVar("suite_egress_kind", default="")
_CALLER: ContextVar[str] = ContextVar("suite_egress_caller", default="")

_PROCESS_TOTALS: dict[str, Any] = {
    "reads": 0,
    "writes": 0,
    "bytes_in": 0,
    "bytes_out": 0,
    "by_table": defaultdict(lambda: {"reads": 0, "writes": 0, "bytes_in": 0}),
    "full_room_loads": 0,
    "forced_loads": 0,
    "chat_loads": 0,
    "head_loads": 0,
    "poll_calls": 0,
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
    kind: str = ""
    caller: str = ""


@dataclass
class EgressRunSummary:
    reads: int = 0
    writes: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    by_table: dict[str, dict[str, int]] = field(default_factory=dict)
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    by_kind: dict[str, int] = field(default_factory=dict)
    full_room_by_caller: dict[str, int] = field(default_factory=dict)
    events: list[EgressEvent] = field(default_factory=list)
    full_room_loads: int = 0
    forced_loads: int = 0
    chat_loads: int = 0
    head_loads: int = 0
    poll_calls: int = 0
    poll_window_start: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        import time

        now = time.time()
        window = max(1.0, now - float(self.poll_window_start or now))
        return {
            "reads": self.reads,
            "writes": self.writes,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "by_table": self.by_table,
            "by_source": self.by_source,
            "by_kind": self.by_kind,
            "full_room_by_caller": self.full_room_by_caller,
            "event_count": len(self.events),
            "full_room_loads": self.full_room_loads,
            "forced_loads": self.forced_loads,
            "chat_loads": self.chat_loads,
            "head_loads": self.head_loads,
            "poll_calls": self.poll_calls,
            "poll_calls_per_minute": round(self.poll_calls * 60.0 / window, 2),
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


def note_egress_kind(kind: str) -> None:
    """Tag the next request(s) in this context (full_room / chat_sidecar / head / poll)."""
    kind_s = str(kind or "").strip()
    _KIND.set(kind_s)
    if kind_s == "full_room":
        caller = _SOURCE.get() or "unknown"
        try:
            import inspect

            for frame in inspect.stack()[1:8]:
                mod = str(frame.filename or "").replace("\\", "/")
                if "suite_egress_trace" in mod or "draft_room_supabase_store" in mod:
                    continue
                if "site-packages" in mod:
                    continue
                base = mod.rsplit("/", 1)[-1]
                caller = f"{base}:{frame.function}"
                break
        except Exception:
            pass
        _CALLER.set(caller)
    else:
        _CALLER.set("")


@contextmanager
def egress_source(source: str) -> Iterator[None]:
    token = _SOURCE.set(str(source or "unknown").strip() or "unknown")
    try:
        yield
    finally:
        _SOURCE.reset(token)


def record_poll_call() -> None:
    """Count scheduled shared-room poll attempts (admin egress diagnostics)."""
    import time

    summary = _session_bucket()
    if summary is None:
        _PROCESS_TOTALS["poll_calls"] = int(_PROCESS_TOTALS.get("poll_calls") or 0) + 1
        return
    if not summary.poll_window_start:
        summary.poll_window_start = time.time()
    summary.poll_calls += 1


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
    kind = str(_KIND.get() or "").strip()
    caller = str(_CALLER.get() or "").strip()
    event = EgressEvent(
        method=method.upper(),
        table=table,
        bytes_in=max(0, int(bytes_in)),
        bytes_out=max(0, int(bytes_out)),
        source=source,
        cached=cached,
        path=path,
        kind=kind,
        caller=caller,
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
    kind = str(event.kind or "").strip()
    if kind:
        summary.by_kind[kind] = int(summary.by_kind.get(kind) or 0) + (0 if event.cached else 1)
        if kind == "full_room":
            summary.full_room_loads += 0 if event.cached else 1
            if not event.cached:
                label = event.caller or event.source or "unknown"
                summary.full_room_by_caller[label] = int(
                    summary.full_room_by_caller.get(label) or 0
                ) + 1
        elif kind == "chat_sidecar":
            summary.chat_loads += 0 if event.cached else 1
        elif kind == "head":
            summary.head_loads += 0 if event.cached else 1
        elif kind == "forced":
            summary.forced_loads += 0 if event.cached else 1


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
    kind = str(event.kind or "").strip()
    if kind == "full_room" and not event.cached:
        _PROCESS_TOTALS["full_room_loads"] = int(_PROCESS_TOTALS.get("full_room_loads") or 0) + 1
    elif kind == "chat_sidecar" and not event.cached:
        _PROCESS_TOTALS["chat_loads"] = int(_PROCESS_TOTALS.get("chat_loads") or 0) + 1
    elif kind == "head" and not event.cached:
        _PROCESS_TOTALS["head_loads"] = int(_PROCESS_TOTALS.get("head_loads") or 0) + 1


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
        "full_room_loads": _PROCESS_TOTALS.get("full_room_loads", 0),
        "chat_loads": _PROCESS_TOTALS.get("chat_loads", 0),
        "head_loads": _PROCESS_TOTALS.get("head_loads", 0),
        "poll_calls": _PROCESS_TOTALS.get("poll_calls", 0),
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
        f"download≈{_human_bytes(int(data.get('bytes_in') or 0))}",
        f"full_room={data.get('full_room_loads', 0)}, chat={data.get('chat_loads', 0)}, "
        f"head={data.get('head_loads', 0)}, poll/min≈{data.get('poll_calls_per_minute', '—')}",
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
    by_kind = data.get("by_kind") or {}
    if by_kind:
        lines.append("")
        lines.append("**By kind:** " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    full_callers = data.get("full_room_by_caller") or {}
    if full_callers:
        lines.append("")
        lines.append("**Full-room callers:**")
        for caller, count in sorted(full_callers.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{caller}`: {count}")
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
