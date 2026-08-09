"""Single Pause-sibling click step — fresh frame/locator each invocation."""

from __future__ import annotations

import time
from typing import Any

from stage1_dom_click_capture import (
    CAPTURE_TARGET_PAUSE_SIBLING,
    prepare_isolated_dom_click_capture,
    read_and_summarize_dom_click_capture,
)
from stage1_pause_sibling_scrape import (
    PAUSE_SIBLING_IMPL_REV,
    SIBLING_BUTTON_LABEL,
    evaluate_sibling_click_pass,
    scrape_pause_sibling_generation,
    scrape_pause_sibling_probe,
    sibling_delta,
    wait_for_pause_sibling_probe,
)
from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame


def execute_pause_sibling_click(
    page,
    *,
    phase: str,
    session_hint: str = "",
    require_count_baseline: int | None = None,
    timeout_s: float = 22.0,
) -> dict[str, Any]:
    """Click sibling once; re-resolve app frame and locator (no stale element reuse)."""
    out: dict[str, Any] = {"step": phase, "started_ts": time.time()}
    frame = resolve_streamlit_app_frame(page)
    out["frame_binding"] = describe_page_frames(page)
    out["locator_reacquired"] = True
    out["generation_before_click"] = scrape_pause_sibling_generation(page, frame=frame)
    before = scrape_pause_sibling_probe(page, frame=frame)
    out["scrape_before"] = before
    if not before.get("probe_found") or str(before.get("impl_rev") or "") != PAUSE_SIBLING_IMPL_REV:
        out["setup_abort"] = "SIBLING_LEDGER_NOT_EXPOSED"
        out["finished_ts"] = time.time()
        return out
    bc = int(before.get("count") or 0)
    if require_count_baseline is not None and bc != require_count_baseline:
        out["setup_abort"] = "SIBLING_COUNT_BASELINE_MISMATCH"
        out["expected_count_baseline"] = require_count_baseline
        out["actual_count_baseline"] = bc
        out["finished_ts"] = time.time()
        return out
    loc = frame.get_by_role("button", name=SIBLING_BUTTON_LABEL, exact=True)
    try:
        loc.first.wait_for(state="attached", timeout=12000)
        loc.first.wait_for(state="visible", timeout=12000)
        out["target_attached"] = True
        out["target_visible"] = True
        out["target_enabled"] = bool(loc.first.is_enabled())
        loc.first.scroll_into_view_if_needed(timeout=12000)
    except Exception as exc:
        out["setup_abort"] = "UI_NOT_EXPOSED"
        out["click_error"] = str(exc)[:240]
        out["finished_ts"] = time.time()
        return out
    prep = prepare_isolated_dom_click_capture(
        frame, capture_target=CAPTURE_TARGET_PAUSE_SIBLING, frame_url_hint=str(frame.url or "")
    )
    out["dom_click_capture_prep"] = prep
    seq_before = before.get("full_app_run_seq")
    try:
        loc.first.click(timeout=12000)
        out["click_dispatched"] = True
    except Exception as exc:
        out["click_dispatched"] = False
        out["click_error"] = str(exc)[:240]
        out["finished_ts"] = time.time()
        return out
    min_count = bc + 1
    wait = wait_for_pause_sibling_probe(
        page,
        frame,
        timeout_s=timeout_s,
        min_count=min_count,
        session_id_hint=session_hint,
    )
    out["probe_wait"] = wait
    after = dict(wait.get("scrape") or {})
    out["scrape_after"] = after
    frame_after = resolve_streamlit_app_frame(page)
    out["generation_after_click"] = scrape_pause_sibling_generation(page, frame=frame_after)
    dom = read_and_summarize_dom_click_capture(frame, capture_target=CAPTURE_TARGET_PAUSE_SIBLING)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    delta = sibling_delta(before, after)
    out["delta"] = delta
    out["app_rerun_observed"] = (
        after.get("full_app_run_seq") is not None
        and seq_before is not None
        and int(after.get("full_app_run_seq") or 0) > int(seq_before or 0)
    )
    if delta.get("observability_abort"):
        out["sibling_pass"] = False
        out["observability_abort"] = delta["observability_abort"]
        out["pass_evidence"] = {"failure": delta["observability_abort"]}
    else:
        passed, ev = evaluate_sibling_click_pass(delta, expected_delta=1)
        out["sibling_pass"] = passed
        out["pass_evidence"] = ev
        out["last_event_id"] = ev.get("event_id")
    out["finished_ts"] = time.time()
    return out
