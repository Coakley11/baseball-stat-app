"""Always-on Add-to-Queue lifecycle boundaries for browser/server proof.

Writes durable JSONL under data/tb_probe/ so Playwright can prove:
  widget_rendered → button_return_true → dispatch → mutate → rerun → surfaces
without requiring Stage1 diag query flags.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

LIFECYCLE_KEY = "_live_draft_queue_click_lifecycle"
LIFECYCLE_LEDGER_KEY = "_live_draft_queue_click_lifecycle_ledger"
PROBE_ELEMENT_ID = "ld-queue-click-lifecycle"
_MAX_LEDGER = 48
_LOG_PATH = Path(__file__).resolve().parent / "data" / "tb_probe" / "queue_click_lifecycle.jsonl"


def _queue_names(session: dict[str, Any]) -> list[str]:
    try:
        from draft_state import DRAFT_QUEUE_KEY

        qkey = DRAFT_QUEUE_KEY
    except ImportError:
        qkey = "draft_queue"
    names = [str(x).strip() for x in (session.get(qkey) or []) if str(x).strip()]
    if names:
        return names
    for alt in ("_live_draft_queue_last_good", "_live_draft_queue_sidebar_mirror"):
        names = [str(x).strip() for x in (session.get(alt) or []) if str(x).strip()]
        if names:
            return names
    ds = session.get("draft_state")
    if isinstance(ds, dict):
        return [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]
    return []


def note_queue_click_lifecycle(
    session: dict[str, Any],
    boundary: str,
    **fields: Any,
) -> dict[str, Any]:
    """Record one explicit lifecycle boundary (session + durable JSONL)."""
    row: dict[str, Any] = {
        "ts": time.time(),
        "boundary": str(boundary or "").strip(),
        "queue": _queue_names(session),
        "queue_len": len(_queue_names(session)),
        **{k: v for k, v in fields.items() if v is not None},
    }
    session[LIFECYCLE_KEY] = dict(row)
    ledger = list(session.get(LIFECYCLE_LEDGER_KEY) or [])
    ledger.append(dict(row))
    session[LIFECYCLE_LEDGER_KEY] = ledger[-_MAX_LEDGER:]
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass
    return row


def render_queue_click_lifecycle_probe(st: Any, session: dict[str, Any]) -> None:
    """Always emit a compact DOM probe for the latest lifecycle row."""
    last = dict(session.get(LIFECYCLE_KEY) or {})
    if not last:
        return
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    q = list(last.get("queue") or [])
    st.markdown(
        f'<div id="{PROBE_ELEMENT_ID}" '
        f'data-boundary="{safe(last.get("boundary"))}" '
        f'data-widget-key="{safe(last.get("widget_key"))}" '
        f'data-player-id="{safe(last.get("player_id"))}" '
        f'data-player-name="{safe(last.get("player_name"))}" '
        f'data-button-return="{1 if last.get("button_return_value") else 0}" '
        f'data-queue-len="{int(last.get("queue_len") or 0)}" '
        f'data-queue="{safe("|".join(q[:8]))}" '
        f'data-rerun-requested="{1 if last.get("rerun_requested") else 0}" '
        f'data-ts="{safe(last.get("ts"))}"></div>',
        unsafe_allow_html=True,
    )
