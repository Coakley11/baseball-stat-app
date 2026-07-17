"""Developer Mode latency instrumentation for Live Draft transactional actions."""

from __future__ import annotations

import time
from typing import Any

ACTION_LATENCY_KEY = "_live_draft_action_latency"
ACTION_HISTORY_KEY = "_live_draft_action_latency_history"
MAX_HISTORY = 24


def _now() -> float:
    return time.perf_counter()


def begin_action(session: dict[str, Any], action: str, **fields: Any) -> dict[str, Any]:
    row = {
        "action": str(action),
        "t0": _now(),
        "marks": {},
        "ms": {},
        **{k: v for k, v in fields.items() if v is not None},
    }
    session[ACTION_LATENCY_KEY] = row
    return row


def mark_action(session: dict[str, Any], label: str) -> None:
    row = session.get(ACTION_LATENCY_KEY)
    if not isinstance(row, dict):
        return
    t0 = float(row.get("t0") or _now())
    now = _now()
    marks = dict(row.get("marks") or {})
    ms = dict(row.get("ms") or {})
    marks[label] = now
    ms[f"{label}_ms"] = int((now - t0) * 1000)
    # Segment from previous mark when available.
    prev_labels = [k for k in marks if k != label]
    if prev_labels:
        prev = max(prev_labels, key=lambda k: float(marks[k]))
        ms[f"{prev}_to_{label}_ms"] = int((now - float(marks[prev])) * 1000)
    row["marks"] = marks
    row["ms"] = ms
    session[ACTION_LATENCY_KEY] = row


def finish_action(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    row = session.get(ACTION_LATENCY_KEY)
    if not isinstance(row, dict):
        return {}
    t0 = float(row.get("t0") or _now())
    total_ms = int((_now() - t0) * 1000)
    ms = dict(row.get("ms") or {})
    ms["total_action_ms"] = total_ms
    row["ms"] = ms
    row.update({k: v for k, v in fields.items() if v is not None})
    row["finished"] = True
    session[ACTION_LATENCY_KEY] = row
    hist = list(session.get(ACTION_HISTORY_KEY) or [])
    hist.append(
        {
            "action": row.get("action"),
            "total_action_ms": total_ms,
            "ms": dict(ms),
            "detail": row.get("detail"),
        }
    )
    session[ACTION_HISTORY_KEY] = hist[-MAX_HISTORY:]
    return row


def record_queue_latency(session: dict[str, Any], **fields: Any) -> None:
    """Merge queue-specific timing fields into the active / last action row."""
    row = session.get(ACTION_LATENCY_KEY)
    if not isinstance(row, dict):
        row = begin_action(session, "queue")
    ms = dict(row.get("ms") or {})
    for key, val in fields.items():
        if val is None:
            continue
        if str(key).endswith("_ms") or str(key).endswith("_at"):
            ms[str(key)] = val
        else:
            row[str(key)] = val
    row["ms"] = ms
    session[ACTION_LATENCY_KEY] = row


def format_action_latency(session: dict[str, Any]) -> str:
    row = session.get(ACTION_LATENCY_KEY)
    if not isinstance(row, dict):
        return ""
    ms = row.get("ms") if isinstance(row.get("ms"), dict) else {}
    action = row.get("action") or "?"
    parts = [f"action={action}"]
    for key in (
        "queue_click_to_local_update_ms",
        "queue_persist_ms",
        "room_reload_ms",
        "recommendation_rebuild_ms",
        "projection_rebuild_ms",
        "full_page_render_ms",
        "pick_validation_ms",
        "pick_commit_ms",
        "room_persist_ms",
        "total_action_ms",
    ):
        if ms.get(key) is not None:
            parts.append(f"{key}={ms.get(key)}")
    return " | ".join(parts)


def render_action_latency_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    if not developer_mode:
        return
    line = format_action_latency(session)
    if line:
        st.caption(f"Live action latency: {line}")
    hist = session.get(ACTION_HISTORY_KEY)
    if isinstance(hist, list) and hist:
        with st.expander("Recent Live Draft action latency", expanded=False):
            for item in reversed(hist[-8:]):
                st.text(
                    f"{item.get('action')}: total={item.get('total_action_ms')}ms "
                    f"{item.get('ms') or {}}"
                )
