"""Harness-only browser console capture for Streamlit fragment-batch warnings."""

from __future__ import annotations

import re
import time
from typing import Any

_FRAGMENT_BATCH_HINT = re.compile(
    r"fragment|widget.?update|different fragment|batch",
    re.I,
)


def attach_console_capture(page) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def _on_console(msg) -> None:
        try:
            text = str(msg.text or "")
        except Exception:
            text = ""
        rows.append(
            {
                "ts": time.time(),
                "type": str(getattr(msg, "type", "") or ""),
                "text": text[:800],
            }
        )

    try:
        page.on("console", _on_console)
    except Exception:
        pass
    return rows


def summarize_fragment_batch_console(
    rows: list[dict[str, Any]],
    *,
    click_ts: float,
    window_s: float = 3.0,
) -> dict[str, Any]:
    t0 = float(click_ts) - 0.25
    t1 = float(click_ts) + window_s
    in_window = [r for r in rows if t0 <= float(r.get("ts") or 0) <= t1]
    hits = [r for r in in_window if _FRAGMENT_BATCH_HINT.search(str(r.get("text") or ""))]
    best = hits[0] if hits else {}
    return {
        "supplementary_only": True,
        "warning_present": bool(hits),
        "messages_in_window": len(in_window),
        "fragment_batch_hint_count": len(hits),
        "full_message": str(best.get("text") or "")[:800],
        "relative_to_click_s": (float(best.get("ts") or click_ts) - click_ts) if hits else None,
    }
